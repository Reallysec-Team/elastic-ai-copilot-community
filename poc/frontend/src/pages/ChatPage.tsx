/*
 * 智能查询 —— the product's single query surface.
 *
 * Replaces the old QueryPage. Same backend (/api/generate/stream → /api/execute)
 * and the same capabilities; what changed is the shape: one composer, an
 * append-only stream of answers, and every action scoped to the answer it
 * belongs to instead of to the page.
 *
 * Three deliberate differences from the page it replaces:
 *
 *   • The generated DSL executes automatically. The old page made the analyst
 *     click 执行查询; in a conversation an answer that stops at JSON is not an
 *     answer. Trust is preserved by showing the query under 查看生成的查询 —
 *     editable, re-runnable, visible on demand instead of blocking by default.
 *
 *   • Submitting CONTINUES the conversation. The old page started a fresh one on
 *     every submit (a repeated question there was diverging because the prior
 *     turns kept narrowing it); here continuation is the entire point, so the
 *     escape hatch is an explicit 新话题 button.
 *
 *   • Per-answer actions (sort, size, drill-down, save, feedback, Kibana) live
 *     on the answer card and appear only when they apply. On the old page they
 *     were always on screen, whether or not the current result could use them.
 */

import { useCallback, useEffect, useId, useMemo, useRef, useState } from 'react'
import { useNavigate } from '@tanstack/react-router'
import { HugeiconsIcon } from '@hugeicons/react'
import { AlertCircleIcon, Bookmark01Icon, CalendarClockIcon, ChevronDownIcon, ChevronRightIcon, ExternalLinkIcon, Layers01Icon, ListChecksIcon, Loading03Icon, PencilIcon, PlayIcon, RefreshCwIcon, SendIcon, SparklesIcon, ThumbsDownIcon, ThumbsUpIcon } from '@hugeicons/core-free-icons'
import { toast } from 'sonner'
import { useGate } from '@/components/gated-button'
import { api, type ApiError, type ExecuteResponse } from '@/lib/api'
import { AiChat } from '@/components/blocks/ai-chat-1/components/ai-chat'
import { CustomPartProvider } from '@/components/blocks/ai-chat-1/components/chat-thread'
import {
  NEW_THREAD_ID,
  type MessagePart,
  type PersonRecord,
  type StarterCategory,
  type ThreadRecord,
  type TranscriptRecord,
} from '@/components/blocks/ai-chat-1/components/data'
import { Alert, AlertDescription } from '@/components/reui/alert'
import { Frame, FrameHeader, FramePanel, FrameTitle } from '@/components/reui/frame'
import { Button } from '@/components/ui/button'
import { Textarea } from '@/components/ui/textarea'
import { Pill } from '@/components/ui/Pill'
import { DslPreview } from '@/components/DslPreview'
import { ResultTable, type SortDir } from '@/components/ResultTable'
import { IndexCombobox } from '@/components/IndexCombobox'
import { OperatingOverview } from '@/components/home/OperatingOverview'
import { ExplainLogDialog, type ExplainResultPayload } from '@/components/ExplainLogDialog'
import { InvestigationDialog } from '@/components/InvestigationDialog'
import { cachedDefaultIndex } from '@/lib/defaultIndex'
import { buildDrillDsl } from '@/lib/drilldown'
import { buildExecDsl, genCostText } from '@/lib/execDsl'
import { countHits, isEmptyResult } from '@/lib/emptyResult'
import { classifyError } from '@/lib/errorHelp'
import {
  buildBranchProbe,
  buildRelaxProbe,
  deadBranches,
  relaxations,
  shouldBranches,
  type DeadBranch,
} from '@/lib/relaxQuery'
import { setHandoff } from '@/lib/handoff'
import {
  NEW_QUERY_EVENT,
  pushHistory,
  relativeTime,
  setPending,
  takePending,
} from '@/lib/history'
import { savePref } from '@/lib/prefs'
import {
  addSaved,
  listSavedLocal,
  SAVED_QUERIES_EVENT,
  type SavedQuery,
} from '@/lib/savedQueries'
import {
  buildProbeDsl,
  fetchScope,
  friendlyIndexName,
  hitsDistribution,
  isMultiIndex,
  parseProbe,
  scopeLabel,
  type IndexHitCount,
} from '@/lib/searchScope'
import {
  dataReachesIntoFuture,
  extractQueryStart,
  hoursAhead,
  fetchTimeRanges,
  formatDay,
  formatRange,
  isWindowAfterData,
  type TimeRange,
} from '@/lib/timeRange'
import type { AppliedTimeWindow } from '@/lib/api'
import {
  ALL_TIME,
  rangeLabel,
  resolveRange,
  TimeRangePicker,
  type TimeRange as PickedRange,
} from '@/components/shared/time-range-picker'
import {
  streamGenerate, streamSuggestAngles, type IndexRouting, type StreamDoneEvent,
} from '@/lib/streamingClient'
import { getLang, useT, translate, type Translate } from '@/lib/i18n'
import { chatCopy, type ChatKey } from '@/locales/chat'
import { commonCopy } from '@/locales/common'
import { cn } from '@/lib/utils'
import { apiErrorMessage } from '@/locales/errors'
import { GenerationProgress } from '@/components/chat/generation-progress'

type Phase = 'generating' | 'executing' | 'done' | 'error'

interface Turn {
  id: string
  question: string
  index: string
  phase: Phase
  /** Raw model output while the DSL is still streaming. */
  streamText: string | null
  /** 进度条的三个时间戳 + 推理文本（components/chat/generation-progress.tsx）。 */
  startedAt: number
  writingAt: number | null
  runningAt: number | null
  thinking: string
  gen: StreamDoneEvent | null
  promptVersion: string | null
  result: ExecuteResponse | null
  error: string | null
  /** Where the error came from — only a genuine execution failure is worth
   * feeding back to the model for repair. */
  errorSource: 'generate' | 'execute' | 'sort' | null
  /** Replayed from history with a cached DSL, so no LLM call was made. */
  cached: boolean
  /** 这一轮的索引是谁定的。null = 用户自己指定的（旧的历史回放也是 null）。 */
  routing: IndexRouting | null
  /** 0-hit rescue: where the data actually lives, probed across every index. */
  rescue: IndexHitCount[] | null
  rescueProbing: boolean
  /** Which indices a 全部日志 answer actually drew from. */
  spread: IndexHitCount[] | null
  /** Set on an empty result whose time window starts after the data ends. */
  /* 0 命中的时间侧解释。两种，文案和处置方向不同：
       after_data   问的窗口在数据之后 —— 索引陈旧或采集断了
       future_data  索引里有「未来」的日志 —— 采集端时区配错或数据源时钟快了 */
  stale: {
    range: TimeRange
    queryStart: number | null
    kind: 'after_data' | 'future_data'
  } | null
  /** Clauses that, dropped one at a time, would have returned rows. */
  relaxed: { label: string; count: number; query: Record<string, unknown> }[] | null
  /** Data sources that matched nothing while the total looked healthy. */
  dead: DeadBranch[] | null
  size: number
  serverSort: { col: string; dir: SortDir } | null
  /** Set while showing the raw documents behind one aggregation bucket. */
  drill: { label: string } | null
  dslEdited: boolean
  feedbackSent: 'up' | 'down' | null
  showNegFeedback: boolean
  feedbackError: string | null
  kibanaLoading: boolean
  kibanaError: string | null
}

const DEFAULT_SIZE = 50

/** 聚合结果里的分组数：取第一个带 buckets 的聚合。数不出来就退回 0。 */
function aggGroupCount(result: { aggregations?: Record<string, unknown> | null } | null): number {
  const aggs = result?.aggregations
  if (!aggs) return 0
  for (const v of Object.values(aggs)) {
    const buckets = (v as { buckets?: unknown })?.buckets
    if (Array.isArray(buckets)) return buckets.length
  }
  return 0
}

function newTurn(id: string, question: string, index: string, phase: Phase): Turn {
  return {
    id,
    question,
    index,
    phase,
    streamText: phase === 'generating' ? '' : null,
    startedAt: Date.now(),
    writingAt: null,
    runningAt: null,
    thinking: '',
    routing: null,
    gen: null,
    promptVersion: null,
    result: null,
    error: null,
    errorSource: null,
    cached: false,
    rescue: null,
    rescueProbing: false,
    spread: null,
    stale: null,
    relaxed: null,
    dead: null,
    size: DEFAULT_SIZE,
    serverSort: null,
    drill: null,
    dslEdited: false,
    feedbackSent: null,
    showNegFeedback: false,
    feedbackError: null,
    kibanaLoading: false,
    kibanaError: null,
  }
}

/* Openers for the empty state. Each one has to be answerable by a single ES
 * query — the first thing a new user clicks teaches them what this box can be
 * asked, so an unanswerable example ("环境安全吗？") teaches the wrong lesson. */
/* 六张，三列两行。卡上的大字是小白会问的那句（「有人在攻击我们吗？」）——能问出
 * 精确问题的人不需要这些卡。点卡不直接发：傻问题有很多种具体查法，替人挑一种
 * 等于替人下结论，所以展开四条具体问法让他挑，挑不到就把大标题放进输入框自己写。
 * 每条具体问法都必须是一条 ES 查询能答的；每条标了它要哪类数据（DATA_KINDS），
 * 这台网关上没有那类索引的选项不列，免得点了查到一堆「没有匹配」。 */
const DATA_KINDS: Record<string, RegExp> = {
  auth: /auth|secur|login|sshd|audit/i,
  windows: /win|security/i,
  web: /nginx|apache|access|http|web|kibana_sample_data_logs/i,
  nginxerr: /nginx.*err|error/i,
  app: /app|java|service|docker|k8s|syslog|nginx|access|kibana_sample_data_logs/i,
  docker: /docker|container|k8s|kube/i,
  alerts: /alert|siem|detection/i,
  metrics: /metric|system|host/i,
  mysql: /mysql|slow/i,
}
const OPENER_KEYS: Array<{ q: ChatKey; options: Array<[ChatKey, string]> }> = [
  { q: 'opener1', options: [['opener1Opt1', 'auth'], ['opener1Opt2', 'web'], ['opener1Opt3', 'web'], ['opener1Opt4', 'alerts']] },
  { q: 'opener2', options: [['opener2Opt1', 'app'], ['opener2Opt2', 'app'], ['opener2Opt3', 'web'], ['opener2Opt4', 'docker']] },
  { q: 'opener3', options: [['opener3Opt1', 'alerts'], ['opener3Opt2', 'alerts'], ['opener3Opt3', 'auth'], ['opener3Opt4', 'windows']] },
  { q: 'opener4', options: [['opener4Opt1', 'web'], ['opener4Opt2', 'web'], ['opener4Opt3', 'web'], ['opener4Opt4', 'nginxerr']] },
  { q: 'opener5', options: [['opener5Opt1', 'auth'], ['opener5Opt2', 'auth'], ['opener5Opt3', 'auth'], ['opener5Opt4', 'auth']] },
  { q: 'opener6', options: [['opener6Opt1', 'metrics'], ['opener6Opt2', 'metrics'], ['opener6Opt3', 'metrics'], ['opener6Opt4', 'mysql']] },
]

export function ChatPage() {
  const t = useT(chatCopy)
  /* `t` 是这一页里已经被 Turn 用掉的名字（`turns.map((t) => …)`），所以在那些
     回调里取名 `tr`，指的是同一份文案表。 */
  const tr = t
  const navigate = useNavigate()
  // 空字符串 = 自动。首页不预选索引 —— 「查哪个索引」正是这个产品声称要替用户
  // 省掉的问题，预选一个只是把它换成「你确定要在这个索引里查吗」。
  const [index, setIndex] = useState('')
  /* 界面上的时间范围。默认「全部时间」= 不传 = 后端什么都不改，所以不碰它的人
     感觉不到它存在。选了之后它覆盖问题里说的时间（见 backend/time_window.py），
     覆盖了什么会在结果上方那枚 chip 里写出来。 */
  const [timeRange, setTimeRange] = useState<PickedRange>(ALL_TIME)
  const rangeRef = useRef(timeRange)
  useEffect(() => {
    rangeRef.current = timeRange
  }, [timeRange])
  const [turns, setTurns] = useState<Turn[]>([])
  const [conversationId, setConversationId] = useState<string | null>(null)
  const [explainDoc, setExplainDoc] = useState<Record<string, unknown> | null>(null)
  const [investigateDoc, setInvestigateDoc] = useState<Record<string, unknown> | null>(null)
  const [explainTurnId, setExplainTurnId] = useState<string | null>(null)

  const ctrlRef = useRef<AbortController | null>(null)
  /* 最后一次请求打开的会话 id，用来丢弃后返回的旧请求（见 openThread）。 */
  const requestedThreadRef = useRef<string | null>(null)
  /* One execute may be in flight per answer: a header sort and a size change can
   * overlap on the SAME card, and whichever resolved last used to win. Keyed by
   * turn so two cards never cancel each other. */
  const execCtrls = useRef(new Map<string, AbortController>())
  const bottomRef = useRef<HTMLDivElement>(null)

  const busy = turns.some((t) => t.phase === 'generating' || t.phase === 'executing')

  useEffect(() => {
    bottomRef.current?.scrollIntoView({ behavior: 'smooth', block: 'end' })
  }, [turns.length])

  useEffect(() => {
    const ctrls = execCtrls.current
    return () => {
      ctrlRef.current?.abort()
      for (const c of ctrls.values()) c.abort()
    }
  }, [])

  const patch = useCallback((id: string, p: Partial<Turn>) => {
    setTurns((ts) => ts.map((t) => (t.id === id ? { ...t, ...p } : t)))
  }, [])

  /*
   * Which indices match this filter? One request, no documents — a terms agg
   * over the `_index` metafield, with backing indices folded back into the data
   * stream the user actually picks from.
   */
  const probeIndices = useCallback(
    async (target: string, dsl: Record<string, unknown>): Promise<IndexHitCount[]> => {
      const probe = await api.execute({ index: target, dsl: buildProbeDsl(dsl) })
      const known = target.split(',')
      const merged: IndexHitCount[] = []
      for (const b of parseProbe(probe)) {
        const name = friendlyIndexName(b.index, known)
        const prev = merged.find((f) => f.index === name)
        if (prev) prev.count += b.count
        else merged.push({ index: name, count: b.count })
      }
      return merged.sort((a, b) => b.count - a.count)
    },
    [],
  )

  /*
   * Which single condition emptied the result.
   *
   * A model that guesses "OOM" when the log says "Out of memory" produces a
   * query that is valid, executes fine, and returns nothing — indistinguishable
   * on screen from "this really did not happen". Re-running the query without
   * each clause turns that into "去掉『message 里包含 "OOM"』后有 2 条".
   */
  const probeRelaxations = useCallback(
    async (id: string, idx: string, dsl: Record<string, unknown>) => {
      const candidates = relaxations(dsl)
      if (candidates.length === 0) return
      const counted = await Promise.all(
        candidates.map(async (c) => {
          try {
            const r = await api.execute({ index: idx, dsl: buildRelaxProbe(c.query) })
            const t = r.hits?.total
            const count = typeof t === 'number' ? t : (t?.value ?? 0)
            return { label: c.label, count, query: c.query }
          } catch {
            return { label: c.label, count: 0, query: c.query }
          }
        }),
      )
      const hits = counted.filter((c) => c.count > 0).sort((a, b) => b.count - a.count)
      if (hits.length > 0) patch(id, { relaxed: hits })
    },
    [patch],
  )

  /*
   * The same false negative with the total hiding it.
   *
   * A cross-index question is one `should` branch per data source. Ask 「Java 和
   * nginx 各报了什么错」 and nginx can return 8000 rows while Java returns 0 —
   * the total looks healthy, the table renders, and half the question silently
   * went unanswered. So this runs on SUCCESS, not on 0 hits: one filters agg
   * counts every branch at once. Best-effort garnish — any failure stays quiet.
   */
  const probeDeadBranches = useCallback(
    async (id: string, idx: string, dsl: Record<string, unknown>, signal: AbortSignal) => {
      const probe = buildBranchProbe(dsl)
      if (!probe) return
      try {
        const dead = deadBranches(dsl, await api.execute({ index: idx, dsl: probe }, signal))
        if (dead.length > 0) patch(id, { dead })
      } catch {
        // A guardrail that pops an error is worse than no guardrail.
      }
    },
    [patch],
  )

  /*
   * 0 hits used to be a dead end: the analyst is told nothing was found and has
   * no way to learn whether the query was wrong or simply pointed at the wrong
   * index. Probe the same filter across every index and say where the data is.
   *
   * Reach is limited by design, and the UI says so: this can only rescue "right
   * query, wrong index". When the index was wrong the model ALSO wrote the query
   * against that index's mapping, so the same filter matches nothing anywhere —
   * that case needs a regenerate, which the empty branch offers.
   */
  const rescue = useCallback(
    async (id: string, idx: string, dsl: Record<string, unknown>) => {
      patch(id, { rescueProbing: true })
      try {
        const scope = await fetchScope()
        // Staleness first: when the question's window starts after the newest
        // document, the empty result is fully explained and the index is not
        // the culprit. Blaming the index here sent operators hunting for data
        // that was never missing, only old.
        if (scope) {
          const ranges = await fetchTimeRanges(scope)
          const names = isMultiIndex(idx) ? idx.split(',') : [idx]
          const spans = names.map((n) => ranges[n]).filter(Boolean) as TimeRange[]
          if (spans.length > 0) {
            const span = spans.reduce((a, b) => ({
              lo: Math.min(a.lo, b.lo),
              hi: Math.max(a.hi, b.hi),
            }))
            const queryStart = extractQueryStart(dsl)
            if (isWindowAfterData(queryStart, span)) {
              patch(id, { stale: { range: span, queryStart: queryStart as number, kind: 'after_data' } })
              return
            }
            /* 数据整体跑到了未来：问「最近 1 小时」同样查不到，但上面那条判不出来
               —— 查询起点（now-1h）确实早于数据终点（now+8h）。不说的话用户拿到的
               是一个没有任何解释的空结果，而原因跟他的查询无关。 */
            if (dataReachesIntoFuture(span)) {
              patch(id, { stale: { range: span, queryStart, kind: 'future_data' } })
              return
            }
          }
        }
        // A wrong clause is a likelier cause than a wrong index — the query
        // was written against THIS index's mapping — so ask that first.
        await probeRelaxations(id, idx, dsl)
        if (isMultiIndex(idx)) return // already searched everything
        if (!scope || scope === idx) return
        const found = (await probeIndices(scope, dsl)).filter((f) => f.index !== idx)
        patch(id, { rescue: found })
      } catch {
        /* best-effort — a failed probe just leaves the empty result as it was */
      } finally {
        patch(id, { rescueProbing: false })
      }
    },
    [patch, probeIndices, probeRelaxations],
  )

  /**
   * Run one query for one answer. `raw` is the DSL exactly as sent to ES (the
   * caller has already applied size / sort / drill), so drill-downs and probes
   * share this path without it needing to know about them.
   */
  const runExecute = useCallback(
    async (
      id: string,
      idx: string,
      raw: Record<string, unknown>,
      opts: {
        fromSort?: boolean
        drill?: { label: string } | null
        rescueOn0?: boolean
        question?: string
        /* 这一轮不要带界面的时间窗：问题自己说了时间，模型写进 DSL 的那段就是
           答案。不这样的话，onDone 里刚同步过去的筛选器值还没落到 ref 上，执行
           时会把上一次的窗口盖到一个「问题赢」的查询上。 */
        noWindow?: boolean
      } = {},
    ) => {
      execCtrls.current.get(id)?.abort()
      const ctrl = new AbortController()
      execCtrls.current.set(id, ctrl)
      patch(id, {
        phase: 'executing',
        runningAt: Date.now(),
        error: null,
        errorSource: null,
        rescue: null,
        spread: null,
        stale: null,
        relaxed: null,
        dead: null,
      })
      try {
        const r = await api.execute(
          {
            index: idx,
            dsl: raw,
            question: opts.question,
            ...(opts.noWindow ? {} : resolveRange(rangeRef.current)),
          },
          ctrl.signal,
        )
        if (execCtrls.current.get(id) !== ctrl) return // superseded — drop stale result
        patch(id, { result: r, phase: 'done', drill: opts.drill ?? null })
        if (opts.rescueOn0 !== false && isEmptyResult(r)) {
          // An aggregation with empty buckets is as much a dead end as zero
          // hits — it used to render a header-only table and explain nothing.
          void rescue(id, idx, raw)
        } else if (isMultiIndex(idx) && r.aggregations) {
          // An aggregation returns no hits, so the per-index breakdown that a
          // document answer gets for free has to be asked for.
          void probeIndices(idx, raw)
            .then((spread) => patch(id, { spread }))
            .catch(() => {})
        }
        if (!isEmptyResult(r) && shouldBranches(raw).length >= 2) {
          void probeDeadBranches(id, idx, raw, ctrl.signal) // after the table, never before
        }
      } catch (e) {
        if (ctrl.signal.aborted) return
        const err = e as ApiError
        // A fielddata error means the (header-driven) sort hit an analyzed text
        // or geo field — that is not something "带着报错重修" should re-feed to
        // the model. Treat sort-triggered runs and fielddata failures as 'sort'.
        const isSortErr =
          !!opts.fromSort || /fielddata is disabled|set fielddata=true/i.test(err.message)
        patch(id, {
          phase: 'error',
          error: err.message,
          errorSource: isSortErr ? 'sort' : 'execute',
        })
      } finally {
        if (execCtrls.current.get(id) === ctrl) execCtrls.current.delete(id)
      }
    },
    [patch, probeIndices, probeDeadBranches, rescue],
  )

  /** Execute an answer's generated DSL with its current size + sort applied. */
  const executeTurn = useCallback(
    (
      t: Turn,
      over: {
        dsl?: Record<string, unknown>
        size?: number
        sort?: { col: string; dir: SortDir } | null
        index?: string
        fromSort?: boolean
      } = {},
    ) => {
      const dsl = over.dsl ?? t.gen?.dsl
      if (!dsl) return
      const size = over.size ?? t.size
      const sort = over.sort !== undefined ? over.sort : t.serverSort
      void runExecute(t.id, over.index ?? t.index, buildExecDsl(dsl, size, sort), {
        fromSort: over.fromSort,
      })
    },
    [runExecute],
  )

  /* 把还在跑的轮次收尾成 error 态。abort() 只掐连接，AbortError 在
     streamingClient.ts:96 被吞掉 —— 被打断的那一轮收不到 onError，
     不主动收尾就永远停在 generating。stopRun 和 send 共用这一段。 */
  const failRunningTurns = useCallback((phases: Phase[], message: string) => {
    setTurns((ts) =>
      ts.map((t) =>
        phases.includes(t.phase)
          ? { ...t, phase: 'error' as const, errorSource: null, streamText: null, error: message }
          : t,
      ),
    )
  }, [])

  const send = useCallback(
    (raw: string, opts: { overrideIndex?: string; fixContext?: string } = {}) => {
      const question = raw.trim()
      const idx = (opts.overrideIndex ?? index).trim()
      // idx 为空是合法的：网关会按问题挑，meta 帧里回传挑中的那个。
      if (!question) return
      // 上一轮还在流式生成时从历史/常用点一条（setPending → rst-pending-changed
      // → hydrate → sendRef），下面的 abort 会让它彻底收不到回调。先收尾，
      // 且只动 generating：executing 的轮次这里不 abort，它们能自己跑完。
      failRunningTurns(['generating'], t('interrupted'))
      const id = `${Date.now()}-${Math.random().toString(36).slice(2, 8)}`
      setTurns((ts) => [...ts, newTurn(id, question, idx, 'generating')])

      ctrlRef.current?.abort()
      // meta 帧回来之前不知道最终查哪儿；onDone 用这个值，而不是闭包里的 idx。
      let resolvedIdx = idx
      ctrlRef.current = streamGenerate(
        {
          index: idx,
          // The repair loop feeds the execution error back to the model. The
          // question shown on screen stays clean.
          question: opts.fixContext
            ? `${question}\n\n[上一次执行该 DSL 报错，请据此修正后重新生成]:\n${opts.fixContext}`
            : question,
          conversation_id: conversationId,
          ...resolveRange(rangeRef.current),
        },
        {
          onMeta: (e) => {
            if (e.conversation_id) {
              setConversationId(e.conversation_id)
              setThreadsKey((k) => k + 1)
            }
            // 网关挑的索引要立刻落到这一轮上：执行、Kibana 链接、保存、0 命中
            // 回捞全都读 turn.index，晚一步它们就都打在空串上。
            if (e.index) {
              resolvedIdx = e.index
              patch(id, { index: e.index, routing: e.routing ?? null })
            }
            patch(id, { promptVersion: e.prompt_version ?? null })
          },
          onChunk: (e) =>
            setTurns((ts) =>
              ts.map((t) =>
                t.id === id
                  ? { ...t, streamText: (t.streamText ?? '') + e.text, writingAt: t.writingAt ?? Date.now() }
                  : t,
              ),
            ),
          onThinking: (e) =>
            setTurns((ts) =>
              ts.map((t) => (t.id === id ? { ...t, thinking: t.thinking + e.text } : t)),
            ),
          onDone: (e) => {
            patch(id, { gen: e, streamText: null })
            if (!e.dsl) {
              patch(id, {
                phase: 'error',
                errorSource: 'generate',
                error: e.validation_error ?? t('errNoDsl'),
              })
              return
            }
            /* 问题里明确说了时间 → 它赢，并把筛选器同步显示成同一段。同步是这条
               规则能成立的关键：否则筛选器写着「全部时间」、结果按 9 月 23 日跑，
               界面上两个地方互相矛盾，用户接着改筛选器时也不知道自己在改什么。 */
            const qWins = e.time_window?.mode === 'question_wins'
            if (qWins && e.time_window?.since) {
              setTimeRange({
                kind: 'custom',
                since: e.time_window.since,
                until: e.time_window.until ?? undefined,
              })
            }
            pushHistory({ question, index: resolvedIdx, dsl: e.dsl, confidence: e.confidence })
            setThreadsKey((k) => k + 1)
            // 自动挑出来的索引不写成用户的默认值 —— 那是这一个问题的答案，
            // 不是他的偏好；写进去下一个问题就被上一个问题的路由结果绑住了。
            if (idx) savePref({ defaultIndex: idx })
            void runExecute(id, resolvedIdx, buildExecDsl(e.dsl, DEFAULT_SIZE, null), {
              question,
              noWindow: qWins,
            })
          },
          onError: (m) =>
            patch(id, {
              phase: 'error',
              streamText: null,
              errorSource: 'generate',
              error: m || t('errGenerate'),
            }),
        },
      )
    },
    [conversationId, failRunningTurns, index, patch, runExecute, t],
  )

  /* Latest `send`, readable from listeners registered once on mount. Declared
   * before the hydrate effect below so it is refreshed first on every commit. */
  const sendRef = useRef(send)
  useEffect(() => {
    sendRef.current = send
  }, [send])

  /* Replay from 历史 / 我的常用 / 字段字典. A cached DSL skips the LLM entirely —
   * that is the whole point of storing it — so the answer starts at 'executing'. */
  useEffect(() => {
    function hydrate() {
      const p = takePending()
      if (!p?.question) return
      const idx = (p.index ?? cachedDefaultIndex()).trim()
      if (p.index) setIndex(p.index)
      if (!idx) return
      if (!p.dsl) {
        sendRef.current(p.question, { overrideIndex: idx })
        return
      }
      const cachedDsl = p.dsl
      const id = `${Date.now()}-${Math.random().toString(36).slice(2, 8)}`
      const base = newTurn(id, p.question, idx, 'executing')
      setTurns((ts) => [
        ...ts,
        {
          ...base,
          cached: true,
          promptVersion: p.prompt_version ?? null,
          gen: {
            type: 'done',
            dsl: cachedDsl,
            explanation: '',
            confidence: p.confidence ?? 'medium',
          },
        },
      ])
      void runExecute(id, idx, buildExecDsl(cachedDsl, DEFAULT_SIZE, null))
    }
    hydrate()
    window.addEventListener('rst-pending-changed', hydrate)
    return () => window.removeEventListener('rst-pending-changed', hydrate)
  }, [runExecute])

  const onNewTopic = useCallback(() => {
    ctrlRef.current?.abort()
    for (const c of execCtrls.current.values()) c.abort()
    execCtrls.current.clear()
    setConversationId(null)
    setTurns([])
    // 新会话回到自动，而不是回到上一次钉住的索引。
    setIndex('')
  }, [])

  /* ⌘K「新建查询」. The palette can only navigate, and navigating to `/` while
   * already on `/` doesn't remount — so the command needs an explicit reset to
   * land on, or it silently does nothing. */
  useEffect(() => {
    window.addEventListener(NEW_QUERY_EVENT, onNewTopic)
    return () => window.removeEventListener(NEW_QUERY_EVENT, onNewTopic)
  }, [onNewTopic])

  /* When the same filter matches nothing anywhere, the index was probably wrong
   * BEFORE the query was written — the model had the wrong mapping in front of
   * it. Re-asking against the full scope gives it every field to work with. */
  const regenerateInScope = useCallback(
    async (question: string) => {
      const scope = await fetchScope()
      if (!scope) return
      setIndex(scope)
      savePref({ defaultIndex: scope })
      send(question, { overrideIndex: scope })
    },
    [send],
  )

  /* Drill from one aggregation bucket into the raw documents behind it.
   * An aggregation-only answer renders as numbers with no next step — every
   * downstream action (解释 / 调查 / 送去分诊) needs hits. We rebuild the SAME
   * query with the bucket's own constraint appended and aggs dropped, so the
   * drill is exactly "these N docs", not a fresh guess. */
  const onDrill = useCallback(
    (t: Turn, aggName: string, bucket: Record<string, unknown>, nextKey?: unknown) => {
      const dsl = t.gen?.dsl
      if (!dsl) return
      const drilled = buildDrillDsl(dsl, aggName, bucket, nextKey, t.size)
      if (!drilled) {
        patch(t.id, {
          phase: 'error',
          error: tr('errDrillNotBucketed', { agg: aggName }),
          errorSource: null,
        })
        return
      }
      patch(t.id, { serverSort: null })
      void runExecute(t.id, t.index, drilled.dsl, {
        drill: { label: drilled.label },
        rescueOn0: false,
      })
    },
    [patch, runExecute, tr],
  )

  const saveQuery = useCallback(async (t: Turn) => {
    const dsl = t.gen?.dsl
    if (!dsl) return
    const name = window.prompt(tr('promptSaveName'), t.question.slice(0, 24))
    if (name === null) return
    const finalName = name.trim() || t.question.slice(0, 24)
    await addSaved({ name: finalName, question: t.question, index: t.index, dsl })
    // addSaved never throws (a sync failure flips the global 未同步 chip); the
    // local write always lands, so confirm it.
    toast.success(tr('okSavedQuery', { name: finalName }))
  }, [tr])

  const kibanaLink = useCallback(
    async (t: Turn) => {
      const dsl = t.gen?.dsl
      if (!dsl) return
      patch(t.id, { kibanaLoading: true, kibanaError: null })
      try {
        const r = await api.kibanaLink({ index: t.index, dsl })
        window.open(r.url, '_blank', 'noopener,noreferrer')
      } catch (e) {
        patch(t.id, { kibanaError: e instanceof Error ? e.message : String(e) })
      } finally {
        patch(t.id, { kibanaLoading: false })
      }
    },
    [patch],
  )

  const sendFeedback = useCallback(
    async (t: Turn, correct: boolean, comment?: string, suggestedDsl?: Record<string, unknown>) => {
      try {
        await api.feedback({
          question: t.question,
          index: t.index,
          dsl: t.gen?.dsl ?? null,
          correct,
          comment: comment ?? null,
          suggested_dsl: suggestedDsl ?? null,
          prompt_version: t.promptVersion,
          dsl_was_edited: t.dslEdited,
        })
        patch(t.id, {
          feedbackSent: correct ? 'up' : 'down',
          showNegFeedback: false,
          feedbackError: null,
        })
      } catch (e) {
        // Its OWN slot, not the turn's error: a 👎 that silently fails is worse
        // than no button — the analyst thinks the correction was filed and it is
        // nowhere.
        patch(t.id, {
          feedbackError:
            e instanceof Error ? `${tr('errFeedback')}: ${e.message}` : tr('errFeedback'),
        })
      }
    },
    [patch, tr],
  )

  const sendToTriage = useCallback(
    (t: Turn) => {
      const all = t.result?.hits?.hits ?? []
      if (all.length === 0) return
      // The triage page caps a batch at 100 and truncates the rest anyway. Cap
      // here so we don't serialize + hand off 900 docs that get dropped on
      // arrival; tell the operator what was taken.
      const MAX = 100
      const truncated =
        all.length > MAX ? tr('triageTruncated', { max: MAX, total: all.length }) : ''
      setHandoff('triage', {
        // Keep the {_id, _source} envelope. Handing over a bare _source dropped
        // the document id, so every cluster arrived with an empty alert-id list
        // and 「查看 alert ID 列表」 showed (0) — nothing could be traced back
        // to the document it came from.
        alerts: all.slice(0, MAX).map((h) => ({ _id: h._id, _source: h._source ?? {} })),
        sourceNote: tr('triageSourceNote', {
          question: t.question,
          index: t.index,
          truncated,
        }),
      })
      navigate({ to: '/triage' })
    },
    [navigate, tr],
  )

  const explainTurn = turns.find((t) => t.id === explainTurnId) ?? null
  const explainPayload: ExplainResultPayload | null = useMemo(() => {
    if (!explainTurn?.result || !explainTurn.gen?.dsl) return null
    const t = explainTurn.result.hits?.total
    return {
      question: explainTurn.question,
      dsl: explainTurn.gen.dsl,
      aggregations: explainTurn.result.aggregations ?? null,
      // 5 is the backend's contract (ExplainResultRequest.sample_hits max_length).
      sample_hits: (explainTurn.result.hits?.hits ?? []).slice(0, 5).map((h) => h._source ?? {}),
      total: typeof t === 'number' ? t : t && typeof t === 'object' ? Number(t.value ?? 0) : null,
    }
  }, [explainTurn])

  /* Bumped whenever a send opens or extends a conversation, so the switcher
     reflects the thread you are in rather than the list as it was on mount. */
  const [threadsKey, setThreadsKey] = useState(0)
  const threads = useThreads(threadsKey)
  const { starters, saved } = useStarters()
  /* The open thread names itself from the question in front of you. The
     server list cannot: it is refreshed the moment a conversation is created,
     which is before its first turn has been written, so its title for the
     thread you are in is "(空会话)" until the answer lands. */
  const title =
    turns[0]?.question.slice(0, 60) ??
    (conversationId
      ? (threads.find((t) => t.id === conversationId)?.title ?? t('currentThread'))
      : t('newThread'))

  /** Abort whatever is in flight and mark the turns it was writing. */
  const stopRun = useCallback(() => {
    ctrlRef.current?.abort()
    for (const c of execCtrls.current.values()) c.abort()
    execCtrls.current.clear()
    failRunningTurns(['generating', 'executing'], t('stopped'))
  }, [failRunningTurns, t])

  /*
   * Open a past conversation. Its turns are replayed from the DSL the server
   * kept, NOT re-executed: opening a ten-turn thread would otherwise fire ten
   * queries at the cluster to redraw a page nobody has read yet. Each answer
   * carries its query and a 运行 button, so a turn costs a click when it is
   * the one you actually came back for.
   */
  const openThread = useCallback(
    async (id: string) => {
      if (id === conversationId) return
      stopRun()
      // 连点两个会话时，先点的那个若后返回会盖掉后点的：屏幕上的内容和
      // 抽屉里高亮的 activeThreadId 就不是同一个会话了。回来时对不上就丢弃。
      requestedThreadRef.current = id
      try {
        const c = await api.conversation(id)
        if (requestedThreadRef.current !== id) return
        setConversationId(id)
        setTurns(
          c.turns.map((t, i) => {
            // 失败也是历史：问过、答失败了的那一轮留着，能重试。老记录没有
            // status，按 done。
            const status = t.status ?? 'done'
            const ok = status === 'done' && !!t.dsl
            const replayError = ok
              ? null
              : status === 'failed'
                ? tr('turnFailedReplay', {
                    msg: apiErrorMessage(
                      { detail: t.error?.message ?? '', code: t.error?.code },
                      t.error?.message ?? '',
                    ),
                  })
                : status === 'aborted'
                  ? tr('turnAbortedReplay')
                  : status === 'pending'
                    ? tr('turnPendingReplay')
                    : tr('errNoReplayableQuery')
            return {
              ...newTurn(`${id}_${i}`, t.question, index, ok ? 'done' : 'error'),
              cached: true,
              gen: ok
                ? {
                    type: 'done' as const,
                    dsl: t.dsl!,
                    explanation: t.explanation ?? '',
                    confidence: 'medium' as const,
                  }
                : null,
              error: replayError,
              errorSource: ok ? null : ('generate' as const),
            }
          }),
        )
      } catch (e) {
        if (requestedThreadRef.current !== id) return
        toast.error(
          e instanceof Error ? `${tr('errOpenThread')}: ${e.message}` : tr('errOpenThread'),
        )
      }
    },
    [conversationId, index, stopRun, tr],
  )

  /* A saved query carries its own DSL, so picking one by its question text
     replays it instead of paying for a generation that would rewrite it. */
  const onComposerSend = useCallback(
    (text: string) => {
      const hit = saved.find((s) => s.question === text)
      if (hit?.dsl) {
        setPending({ question: hit.question, index: hit.index, dsl: hit.dsl })
        return
      }
      send(text)
    },
    [saved, send],
  )

  /*
   * The transcript the chat surface renders. One question and one answer per
   * turn: the answer is a single `result` part, because everything an answer
   * can grow (the query behind it, the table, a relaxation offer, feedback)
   * belongs to the same card and keeps mutating after it lands.
   */
  const transcript = useMemo<TranscriptRecord>(
    () => ({
      messages: turns.flatMap((t) => [
        {
          id: `${t.id}_q`,
          role: 'user' as const,
          author: viewer(),
          at: '',
          parts: [{ kind: 'text' as const, text: t.question }],
        },
        {
          id: `${t.id}_a`,
          role: 'assistant' as const,
          author: null,
          at: '',
          parts: [{ kind: 'result' as const, turnId: t.id }],
        },
      ]),
    }),
    [turns],
  )

  const live = turns[turns.length - 1]
  const activityLabel =
    live && (live.phase === 'generating' || live.phase === 'executing')
      ? live.phase === 'generating'
        ? t('activityGenerating')
        : t('activityExecuting', { scope: scopeLabel(live.index) })
      : t('activityIdle')

  /*
   * `renderPart` hands the surface this product's own part kinds. It returns an
   * element rather than a rendered tree: the transcript memoizes a part on its
   * content, and a `result` part's content — a turn id — never changes while
   * the turn behind it does.
   */
  const renderPart = useCallback(
    (part: MessagePart) => {
      if (part.kind !== 'result') return null
      const t = turns.find((x) => x.id === part.turnId)
      if (!t) return null
      return (
        <TurnView
          turn={t}
          onRetry={() => send(t.question, { overrideIndex: t.index })}
          onRepair={() =>
            send(t.question, { overrideIndex: t.index, fixContext: t.error ?? undefined })
          }
          onRegenerateInScope={() => void regenerateInScope(t.question)}
          onRun={() => executeTurn(t)}
          onRelax={(q) => {
            // Re-run THIS answer's DSL with the clause dropped, rather than
            // re-asking the model: the operator already agreed to the
            // relaxation, and a fresh generation could reintroduce it.
            const base = t.gen?.dsl ?? {}
            executeTurn(t, { dsl: { ...base, query: q } })
          }}
          onAskWithDataWindow={() => {
            if (!t.stale) return
            // Re-ask with the window spelled out. Rewriting the DSL by hand
            // would only move the range clause; the question itself said
            // "最近 30 天", and the answer should match what was asked.
            send(
              tr('askWithDataWindow', {
                question: t.question,
                lo: formatDay(t.stale.range.lo),
                hi: formatDay(t.stale.range.hi),
              }),
              { overrideIndex: t.index },
            )
          }}
          onDslChange={(next) => {
            patch(t.id, {
              gen: t.gen ? { ...t.gen, dsl: next } : t.gen,
              dslEdited: true,
              cached: false,
            })
            executeTurn(t, { dsl: next })
          }}
          onSizeChange={(n) => {
            patch(t.id, { size: n })
            executeTurn(t, { size: n })
          }}
          onServerSort={(col, dir) => {
            const next = dir ? { col, dir } : null
            patch(t.id, { serverSort: next })
            executeTurn(t, { sort: next, fromSort: true })
          }}
          onDrill={(aggName, bucket, nextKey) => onDrill(t, aggName, bucket, nextKey)}
          onExitDrill={() => {
            patch(t.id, { drill: null })
            executeTurn(t)
          }}
          onSwitchIndex={(nextIndex) => {
            setIndex(nextIndex)
            savePref({ defaultIndex: nextIndex })
            patch(t.id, { index: nextIndex, result: null, rescue: null, spread: null })
            executeTurn(t, { index: nextIndex })
          }}
          onExplainResult={() => setExplainTurnId(t.id)}
          onExplainDoc={setExplainDoc}
          onInvestigateDoc={setInvestigateDoc}
          onSendToTriage={() => sendToTriage(t)}
          onSaveQuery={() => void saveQuery(t)}
          onKibanaLink={() => void kibanaLink(t)}
          onFeedbackUp={() => void sendFeedback(t, true)}
          onFeedbackDownToggle={() => patch(t.id, { showNegFeedback: !t.showNegFeedback })}
          onFeedbackDown={(comment, dsl) => void sendFeedback(t, false, comment, dsl)}
          onDismissFeedbackError={() => patch(t.id, { feedbackError: null })}
        />
      )
    },
    [
      tr,
      executeTurn,
      kibanaLink,
      onDrill,
      patch,
      regenerateInScope,
      saveQuery,
      send,
      sendFeedback,
      sendToTriage,
      turns,
    ],
  )

  return (
    /* 这一页是满高的对话面，不套模板那个 `max-w-[71rem]` 的卡片页容器 ——
       模板没有对应的页，硬套等于给聊天框加一圈白边。
       高度从视口里扣掉顶栏和内容列的上内边距；`-mb-4` 把下内边距吃回来。
       顶栏高度读 `--header-height` 而不是写死数字：阶段 2 把它从 60px 改成
       50px，写死的那版会让整页多出一条滚动条。 */
    // 整页滚：这一页不再自己占满视口、让消息区内部滚——输入框跟在内容后面，
    // 滚动条只有外壳那一条。min-h 只为让空态（概览 + 示例）仍撑满一屏。
    <div className="flex min-h-[calc(100svh-var(--header-height)-2rem)] flex-col">
      {/* 这一页的可见标题是空态里那句「想查什么，直接问」，问完第一句就没了 ——
          在这儿留一个只给读屏和测试看的 h1。面包屑删掉之前，这个 h1 是它出的。 */}
      <h1 className="sr-only">{t('srTitle')}</h1>
      <CustomPartProvider render={renderPart}>
        <AiChat
          /* 这个块自带的 h-14 头就画在正文里。它曾经 portal 进外壳顶栏（当时
             那条栏在桌面上是空的），现在顶栏归产品身份，不再收页面内容。 */
          threads={threads}
          activeThreadId={conversationId ?? NEW_THREAD_ID}
          transcript={transcript}
          title={title}
          streaming={busy}
          stopped={false}
          arrivingId={null}
          stoppedIds={EMPTY_IDS}
          activityLabel={activityLabel}
          starters={starters}
          /* 提问之前先说今天有什么要处理 —— 版式照 tempo 的 home。
             问出第一个问题之后整块随空态一起消失。 */
          emptyExtra={<OperatingOverview />}
          heading={t('heading')}
          subheading={t('subheading')}
          composerPlaceholder={t('composerPlaceholder')}
          composerTools={
            <>
            <IndexCombobox
              value={index}
              onChange={(v) => {
                setIndex(v)
                // 只有明确钉住一个索引才写偏好；回到自动就把偏好清掉。
                savePref({ defaultIndex: v })
              }}
              placeholder={t('indexAuto')}
              /* 默认自动，选择器退成「钉住一个索引」的高级选项。「全部日志」也留着：
                 路由兜底本来就是它，但用户可能想强制一次全量。 */
              allowAuto
              allowAll
              /* 不写 h-8：外层 h-8 而里面的触发器是 h-9，多出的 4px 让它比旁边的
                 时间按钮低 2px。让外层随内容高，范围带用 items-center 对齐两者。 */
              className="w-auto min-w-32 max-w-80 border-0 bg-transparent shadow-none"
            />
            {/* 与实时告警、调用审计、运营报告同一个组件。默认「全部时间」——
                不选就完全不改变行为；选了它就是唯一的时间来源，覆盖问题里说的
                时间（覆盖了什么，结果上方那枚 chip 会写出来）。 */}
            <TimeRangePicker
              value={timeRange}
              onChange={setTimeRange}
              className="h-8 border-0 bg-transparent shadow-none"
            />
            </>
          }
          onSelectThread={(id) => void openThread(id)}
          onDeleteThread={(id) => {
            void api
              .conversationDelete(id)
              .then(() => setThreadsKey((k) => k + 1))
              .catch((e: ApiError) => toast.error(e.message))
          }}
          onNewChat={onNewTopic}
          onSend={onComposerSend}
          onStop={stopRun}
          onArrived={NOOP}
        />
      </CustomPartProvider>

      <ExplainLogDialog
        open={!!explainDoc}
        onOpenChange={(v) => !v && setExplainDoc(null)}
        doc={explainDoc}
        index={index}
        onUpgradeToInvestigate={() => {
          setInvestigateDoc(explainDoc)
          setExplainDoc(null)
        }}
      />
      <ExplainLogDialog
        open={!!explainTurnId}
        onOpenChange={(v) => !v && setExplainTurnId(null)}
        doc={null}
        index={explainTurn?.index ?? index}
        resultPayload={explainPayload}
        onUseSuggestion={(s) => {
          setExplainTurnId(null)
          send(s)
        }}
      />
      <InvestigationDialog
        open={!!investigateDoc}
        onOpenChange={(v) => !v && setInvestigateDoc(null)}
        alert={investigateDoc}
        index={index}
      />
    </div>
  )
}

/** Stable identities: a new array or lambda here would re-render the surface. */
const EMPTY_IDS: string[] = []
const NOOP = () => {}

/** The signed-in analyst. Only the initials are drawn — the surface renders an
    avatar fallback when there is no image, which is every deployment here. */
function viewer(): PersonRecord {
  const name = translate(chatCopy, 'viewerName')
  return { name, initials: name, avatar: '' }
}

/**
 * The zero state's two offers, in the order they are useful: what you saved
 * because you run it often, then examples that teach what the box answers.
 * A saved query carries its DSL, so picking one skips the model entirely.
 */
function useStarters(): { starters: StarterCategory[]; saved: SavedQuery[] } {
  const t = useT(chatCopy)
  const [saved, setSaved] = useState<SavedQuery[]>(listSavedLocal)
  // 这台网关能查到的索引名。拿不到就当全有（选项全列）。
  const [indexNames, setIndexNames] = useState<string[] | null>(null)
  useEffect(() => {
    let live = true
    void api
      .indices()
      .then((r) => { if (live) setIndexNames(r.indices.map((i) => i.name)) })
      .catch(() => {})
    return () => { live = false }
  }, [])

  useEffect(() => {
    const refreshSaved = () => setSaved(listSavedLocal())
    window.addEventListener(SAVED_QUERIES_EVENT, refreshSaved)
    return () => window.removeEventListener(SAVED_QUERIES_EVENT, refreshSaved)
  }, [])

  /* 原来还有一栏「最近」：本机历史里最近 5 个问题，点了重新生成一次。它和
     下面的「最近的会话」说的是同一批问题，后者还能免费回放，两个「最近」并排
     只会让人猜区别。删掉那栏，只留「我的常用」和「试试」。 */
  const starters = useMemo<StarterCategory[]>(() => {
    const groups: StarterCategory[] = []
    if (saved.length > 0)
      groups.push({
        id: 'saved',
        label: t('starterSaved'),
        icon: <HugeiconsIcon icon={Bookmark01Icon} strokeWidth={2} aria-hidden="true" />,
        prompts: saved.map((s) => ({ label: s.question, text: s.question })),
      })
    groups.push({
      id: 'samples',
      label: t('starterSamples'),
      icon: <HugeiconsIcon icon={SparklesIcon} strokeWidth={2} aria-hidden="true" />,
      prompts: OPENER_KEYS.map(({ q, options }) => {
        const has = (kind: string) =>
          indexNames == null || indexNames.some((n) => DATA_KINDS[kind]?.test(n))
        const fitting = options.filter(([, kind]) => has(kind))
        // 一条都不合适就全列：宁可查空，也别给一张点不开的卡。
        const shown = fitting.length > 0 ? fitting : options
        return {
          label: t(q),
          hint: t(shown[0][0]),
          text: t(q),
          options: shown.map(([k]) => ({ label: t(k), text: `${t(q)}${t('openerJoin')}${t(k)}` })),
          // 烧一次额度，换几条这台网关上真能查的新角度。
          moreAngles: (existing, onAngle) =>
            streamSuggestAngles(
              { question: t(q), indices: indexNames ?? [], existing, lang: getLang() },
              onAngle,
            ),
        }
      }),
    })
    return groups
  }, [indexNames, saved, t])

  return { starters, saved }
}

/** Server-side conversations, in the shape the thread switcher reads. */
function useThreads(reloadKey: number): ThreadRecord[] {
  const [threads, setThreads] = useState<ThreadRecord[]>([])

  useEffect(() => {
    let live = true
    void api
      .conversationsList({ limit: 30 })
      .then(({ conversations }) => {
        if (!live) return
        const dayAgo = Date.now() - 24 * 3600 * 1000
        setThreads(
          // 后端从 2026-09-15 起会话和第一轮同一次写入，不再有 0 轮次的空壳；
          // 老壳由后端 reap 清掉。失败 / 中断的会话照列，角标说明状态。
          conversations.map((c) => ({
            id: c.id,
            title: c.first_question?.slice(0, 60) || translate(chatCopy, 'emptyThreadTitle'),
            updatedLabel: relativeTime(c.last_at * 1000),
            recency: c.last_at * 1000 >= dayAgo ? ('today' as const) : ('earlier' as const),
            pinned: false,
            artifact:
              c.last_status === 'failed'
                ? translate(chatCopy, 'threadLastFailed')
                : c.last_status === 'aborted'
                  ? translate(chatCopy, 'threadLastAborted')
                  : c.last_status === 'pending'
                    ? translate(chatCopy, 'threadLastPending')
                    : c.turn_count > 1
                      ? translate(chatCopy, 'turnCount', { n: c.turn_count })
                      : undefined,
          })),
        )
      })
      // A history list that cannot load is not worth an error surface of its
      // own: the box still works, and the switcher just shows nothing.
      .catch(() => {})
    return () => {
      live = false
    }
  }, [reloadKey])

  return threads
}
interface TurnViewProps {
  turn: Turn
  onRetry: () => void
  /** Run a replayed turn's cached query. Only a replay arrives without rows. */
  onRun: () => void
  onRepair: () => void
  onRegenerateInScope: () => void
  onAskWithDataWindow: () => void
  onRelax: (query: Record<string, unknown>) => void
  onDslChange: (next: Record<string, unknown>) => void
  onSizeChange: (n: number) => void
  onServerSort: (col: string, dir: SortDir | null) => void
  onDrill: (aggName: string, bucket: Record<string, unknown>, nextKey?: unknown) => void
  onExitDrill: () => void
  onSwitchIndex: (index: string) => void
  onExplainResult: () => void
  onExplainDoc: (d: Record<string, unknown>) => void
  onInvestigateDoc: (d: Record<string, unknown>) => void
  onSendToTriage: () => void
  onSaveQuery: () => void
  onKibanaLink: () => void
  onFeedbackUp: () => void
  onFeedbackDownToggle: () => void
  onFeedbackDown: (comment: string, dsl?: Record<string, unknown>) => void
  onDismissFeedbackError: () => void
}

function TurnView({
  turn,
  onRetry,
  onRun,
  onRepair,
  onRegenerateInScope,
  onAskWithDataWindow,
  onRelax,
  onDslChange,
  onSizeChange,
  onServerSort,
  onDrill,
  onExitDrill,
  onSwitchIndex,
  onExplainResult,
  onExplainDoc,
  onInvestigateDoc,
  onSendToTriage,
  onSaveQuery,
  onKibanaLink,
  onFeedbackUp,
  onFeedbackDownToggle,
  onFeedbackDown,
  onDismissFeedbackError,
}: TurnViewProps) {
  const [dslOpen, setDslOpen] = useState(false)
  const hits = turn.result?.hits?.hits ?? []
  const total = turn.result ? countHits(turn.result) : 0
  const t = useT(chatCopy)
  const hasAggs = !!turn.result?.aggregations
  const empty = !!turn.result && isEmptyResult(turn.result)
  const dist = turn.result ? hitsDistribution(turn.result) : []
  const spread = turn.spread ?? []
  const dsl = turn.gen?.dsl ?? null

  return (
    // The question bubble is the transcript's job — this is only the answer.
    // 照 ai-chat-11 的 AnswerSlab：回复是一张回执，不是气泡。chrome 条说明这次
    // 运行是谁答的、在哪查的、查到多少、花了多久多少钱；正文是结果；最下面
    // 一格 bg-muted 的面板是这次运行产出的「工件」——生成的 DSL 及其操作。
    <Frame
      dense
      spacing="sm"
      stacked
      // stacked 只把「面板 + 面板」的接缝抹方，header 后面的第一块面板上角仍是
      // 圆的，圆角外露出 frame 的灰底，看着像边框被遮了一截。这里把它抹方。
      className="flex w-full min-w-0 flex-col dark:border-white/15 [&_[data-slot=frame-panel-header]+[data-slot=frame-panel]]:rounded-t-none"
      aria-busy={turn.phase === 'generating' || turn.phase === 'executing' || undefined}
    >
      <FrameHeader className="flex-row flex-wrap items-center gap-2 py-2">
        <FrameTitle className="shrink-0 text-sm">
          {turn.cached ? t('replay') : phaseLabel(t, turn.phase)}
        </FrameTitle>
        {/* 查的是哪儿，以及这个「哪儿」是谁定的。自动挑的必须说出来 ——
            悄悄替人选一个索引再把结果当答案，比让他自己选更糟。
            历史回放还没定索引时这一段整个不画，别留个孤零零的小圆点。 */}
        {turn.index && (
          <>
            <ChromeDot />
            <span
              className="min-w-0 truncate font-mono text-xs text-muted-foreground"
              title={turn.routing ? `${turn.index}
${turn.routing.reason}` : turn.index}
            >
              {scopeLabel(turn.index)}
            </span>
          </>
        )}
        {turn.routing && turn.routing.source !== 'given' && (
          <span className="shrink-0 text-xs text-muted-foreground" title={turn.routing.reason}>
            {turn.routing.source === 'conversation' ? t('inheritedIndex') : t('autoPickedIndex')}
          </span>
        )}

        <div className="ms-auto flex items-center gap-2">
          {/* 命中数 · 耗时 · 成本，一串 tabular 小字。聚合查询的 size 是 0，
              hits.total 当然是 0 —— 有聚合时报的是分组数。 */}
          {(turn.result || (turn.gen && !turn.cached && genCostText(turn.gen))) && (
            <span className="hidden items-center gap-1.5 text-xs text-muted-foreground tabular-nums sm:flex">
              {turn.result && (
                <span>
                  {hasAggs
                    ? t('aggGroups', { n: aggGroupCount(turn.result).toLocaleString() })
                    : t('hitCount', { n: total.toLocaleString() })}
                </span>
              )}
              {turn.result && typeof turn.result.took === 'number' && (
                <>
                  <ChromeDot />
                  <span>{turn.result.took} ms</span>
                </>
              )}
              {turn.gen && !turn.cached && genCostText(turn.gen) && (
                <>
                  {turn.result && <ChromeDot />}
                  {/* chrome 条只放「32.4s · 6371 tok」，in/out 拆分进 title —— 否则
                      和左边的索引说明挤成两行。 */}
                  <span className="font-mono" title={`${t('genCostTitle')}: ${genCostText(turn.gen)}`}>
                    {genCostText(turn.gen).replace(/ \(.*\)$/, '')}
                  </span>
                </>
              )}
            </span>
          )}
          {turn.gen && !turn.cached && (
            <Pill tone={confidenceTone(turn.gen.confidence)}>
              <span title={t('confidenceTitle')}>
                {t('confidence', { level: confidenceLabel(t, turn.gen.confidence) })}
              </span>
            </Pill>
          )}
          {dsl && (
            <FeedbackButtons
              sent={turn.feedbackSent}
              onUp={onFeedbackUp}
              onDownClick={onFeedbackDownToggle}
            />
          )}
        </div>
      </FrameHeader>
      <FramePanel className="space-y-4 py-4 bg-card shadow-none!">
          {(turn.phase === 'generating' || turn.phase === 'executing') && (
            <GenerationProgress
              startedAt={turn.startedAt}
              writingAt={turn.writingAt}
              runningAt={turn.runningAt}
              thinking={turn.thinking}
              scope={scopeLabel(turn.index)}
            />
          )}

          {turn.gen?.explanation && (
            <p className="text-15 leading-relaxed text-foreground">{turn.gen.explanation}</p>
          )}

          {/* A replayed turn holds its query but no rows: running it is a
              deliberate click, never a page load's worth of cluster work. */}
          {turn.cached && !turn.result && turn.gen?.dsl && !turn.error && (
            <Button variant="outline" size="sm" onClick={onRun}>
              <HugeiconsIcon icon={PlayIcon} strokeWidth={2} className="size-3.5" />
              {t('runQuery')}
            </Button>
          )}

          {turn.error && (
            <TurnError
              message={turn.error}
              onRetry={onRetry}
              // Only a genuine execution failure is worth re-feeding to the model.
              onRepair={turn.errorSource === 'execute' ? onRepair : undefined}
              // The model often refuses precisely BECAUSE the index is wrong
              // ("这个索引是 Web 访问日志，没有登录事件字段"). Retrying against the
              // same index reproduces the refusal; widening the scope is the way out.
              onRegenerateInScope={isMultiIndex(turn.index) ? undefined : onRegenerateInScope}
            />
          )}

          {turn.feedbackError && (
            <p className="inline-flex items-center gap-1.5 text-12 text-destructive">
              <HugeiconsIcon icon={AlertCircleIcon} strokeWidth={2} className="size-3.5 shrink-0" />
              {turn.feedbackError}
              <button
                type="button"
                onClick={onDismissFeedbackError}
                className="ml-1 underline underline-offset-2 hover:opacity-80"
              >
                {t('gotIt')}
              </button>
            </p>
          )}

          {turn.showNegFeedback && (
            <NegFeedbackForm onCancel={onFeedbackDownToggle} onSubmit={onFeedbackDown} />
          )}

          {turn.drill && (
            <div className="flex flex-wrap items-center gap-2 rounded-xl bg-accent px-3.5 py-2.5 text-12">
              <span className="text-fg-muted">{t('drilledTo', { label: turn.drill.label })}</span>
              <button
                type="button"
                onClick={onExitDrill}
                className="underline decoration-dotted underline-offset-2 transition-colors hover:text-info"
              >
                {t('backToStats')}
              </button>
            </div>
          )}

          {turn.result && (
            <>
              {/* 命中数 / 耗时搬到了上面的 chrome 条；这里只剩「实际查的时间窗」——
                  它覆盖了问题里的时间时必须写出来。 */}
              <TimeWindowChip window={turn.gen?.time_window ?? turn.result.time_window} />

              {spread.length > 1 && (
                <IndexBreakdown label={t('breakdownAggregated')} items={spread} onPick={onSwitchIndex} />
              )}
              {spread.length <= 1 && dist.length > 1 && (
                <IndexBreakdown label={t('breakdownFrom')} items={dist} onPick={onSwitchIndex} />
              )}

              {/* Nothing matched — an empty table (and its export button) is
                  noise. The explanation below it is the answer. */}
              {/* Above the table, deliberately. This says half the question
                  went unanswered; below twenty rows of the half that DID
                  answer, nobody has a reason to scroll down to find it. */}
            {turn.dead && turn.dead.length > 0 && (
              <div className="space-y-2.5 rounded-xl bg-warning-subtle px-4 py-3">
                <p className="text-13 leading-[1.6] text-warning">
                  <HugeiconsIcon icon={AlertCircleIcon} strokeWidth={2} className="mr-1.5 inline size-3.5 align-[-2px]" />
                  {turn.dead.length > 1
                    ? t('deadSourcesN', { n: turn.dead.length })
                    : t('deadSourcesOne')}
                  {t('deadSourcesTail')}
                </p>
                <div className="flex flex-col gap-2.5">
                  {turn.dead.slice(0, 3).map((b) => (
                    <div key={b.key} className="space-y-1.5">
                      <p className="font-mono text-12 text-foreground">{b.label}</p>
                      {b.relaxations.slice(0, 3).map((r) => (
                        <button
                          key={r.label}
                          type="button"
                          onClick={() => onRelax(r.query)}
                          className={cn(
                            'group flex w-full items-center gap-2 rounded-lg px-3 py-2 text-left text-13',
                            'bg-card [box-shadow:var(--shadow-ring-light)]',
                            'transition-colors hover:[box-shadow:var(--shadow-ring)]',
                          )}
                        >
                          <span className="text-fg-muted">{t('tryThis')}</span>
                          <span className="font-mono text-12 text-foreground">{r.label}</span>
                          <HugeiconsIcon icon={ChevronRightIcon} strokeWidth={2} className="ml-auto size-3.5 shrink-0 opacity-0 transition-opacity group-hover:opacity-70" />
                        </button>
                      ))}
                    </div>
                  ))}
                </div>
                <p className="text-12 text-fg-muted">
                  {t('deadHint')}
                </p>
              </div>
            )}

              {!empty && (
                <ResultTable
                  response={turn.result}
                  prefKey={turn.index}
                  onExplain={onExplainDoc}
                  onInvestigate={onInvestigateDoc}
                  onServerSort={onServerSort}
                  serverSort={turn.serverSort}
                  onDrill={turn.drill ? undefined : onDrill}
                />
              )}

              {!empty && (hits.length > 0 || hasAggs) && (
                <div className="flex flex-wrap items-center gap-2 pt-1">
                  <Button variant="outline" className="rounded-full" size="sm" onClick={onExplainResult}>
                    <HugeiconsIcon icon={SparklesIcon} strokeWidth={2} className="size-3.5" />
                    {t('explainResults')}
                  </Button>
                  {hits.length > 0 && (
                    <Button variant="outline" className="rounded-full" size="sm" onClick={onSendToTriage}>
                      <HugeiconsIcon icon={ListChecksIcon} strokeWidth={2} className="size-3.5" />
                      {t('sendToTriage')}
                    </Button>
                  )}
                </div>
              )}
            </>
          )}

          {turn.stale && (
            <div className="space-y-2 rounded-xl bg-warning-subtle px-4 py-3">
              <p className="text-13 leading-[1.6] text-warning">
                <HugeiconsIcon icon={CalendarClockIcon} strokeWidth={2} className="mr-1.5 inline size-3.5 align-[-2px]" />
                {turn.stale.kind === 'future_data' ? (
                  <>
                    {t('staleFutureLead', { scope: scopeLabel(turn.index) })}{' '}
                    {t('staleFutureLatest', {
                      hi: formatDay(turn.stale.range.hi),
                      hours: Math.round(hoursAhead(turn.stale.range)),
                    })}{' '}
                    {t('staleFutureCause')}
                  </>
                ) : (
                  <>
                    {t('staleWindow', {
                      start: formatDay(turn.stale.queryStart ?? Date.now()),
                      scope: scopeLabel(turn.index),
                      hi: formatDay(turn.stale.range.hi),
                    })}
                  </>
                )}
              </p>
              <p className="text-12 text-fg-muted">
                {t('staleDataRange', { range: formatRange(turn.stale.range) })}
                {turn.stale.kind === 'future_data' && t('staleBaselineHint')}
              </p>
              <Button variant="outline" className="rounded-full" size="sm" onClick={onAskWithDataWindow}>
                <HugeiconsIcon icon={CalendarClockIcon} strokeWidth={2} className="size-3.5" />
                {t('askDataRange', { range: formatRange(turn.stale.range) })}
              </Button>
            </div>
          )}

          {turn.relaxed && turn.relaxed.length > 0 && (
            <div className="space-y-2.5 rounded-xl bg-warning-subtle px-4 py-3">
              <p className="text-13 leading-[1.6] text-warning">
                <HugeiconsIcon icon={AlertCircleIcon} strokeWidth={2} className="mr-1.5 inline size-3.5 align-[-2px]" />
                {t('relaxedLead')}
              </p>
              <div className="flex flex-col gap-1.5">
                {turn.relaxed.slice(0, 3).map((r) => (
                  <button
                    key={r.label}
                    type="button"
                    onClick={() => onRelax(r.query)}
                    className={cn(
                      'group flex items-center gap-2 rounded-lg px-3 py-2 text-left text-13',
                      'bg-card [box-shadow:var(--shadow-ring-light)]',
                      'transition-colors hover:[box-shadow:var(--shadow-ring)]',
                    )}
                  >
                    <span className="text-fg-muted">{t('relaxedDrop')}</span>
                    <span className="font-mono text-12 text-foreground">{r.label}</span>
                    <span className="text-fg-muted">{t('relaxedThenHas')}</span>
                    <span className="font-medium text-info">
                      {t('relaxedCount', { n: r.count.toLocaleString() })}
                    </span>
                    <HugeiconsIcon icon={ChevronRightIcon} strokeWidth={2} className="ml-auto size-3.5 shrink-0 opacity-0 transition-opacity group-hover:opacity-70" />
                  </button>
                ))}
              </div>
              <p className="text-12 text-fg-muted">
                {t('relaxedHint')}
              </p>
            </div>
          )}

          {turn.rescueProbing && (
            <div className="flex items-center gap-2 text-12 text-muted-foreground">
              <HugeiconsIcon icon={Loading03Icon} strokeWidth={2} className="size-3.5 animate-spin" />
              {t('rescueProbing')}
            </div>
          )}

          {!turn.stale && turn.rescue && turn.rescue.length > 0 && (
            <div className="space-y-2 rounded-xl bg-info-subtle px-4 py-3">
              <p className="text-13 leading-[1.6] text-foreground">
                <HugeiconsIcon icon={Layers01Icon} strokeWidth={2} className="mr-1.5 inline size-3.5 align-[-2px]" />
                {t('rescueLead', { scope: scopeLabel(turn.index) })}
              </p>
              <div className="flex flex-wrap gap-2">
                {turn.rescue.slice(0, 4).map((d) => (
                  <Button
                    key={d.index}
                    variant="outline" className="rounded-full"
                    size="sm"
                    onClick={() => onSwitchIndex(d.index)}
                  >
                    <span className="font-mono">{d.index}</span>
                    <span className="text-muted-foreground">
                      {t('rescueCount', { n: d.count.toLocaleString() })}
                    </span>
                  </Button>
                ))}
              </div>
            </div>
          )}

          {!turn.stale && turn.rescue && turn.rescue.length === 0 && !turn.rescueProbing && (
            <div className="space-y-2">
              <p className="text-12 leading-[1.6] text-muted-foreground">
                {t('rescueNoneLead', { scope: scopeLabel(turn.index) })}
              </p>
              {!isMultiIndex(turn.index) && (
                <Button variant="outline" className="rounded-full" size="sm" onClick={onRegenerateInScope}>
                  <HugeiconsIcon icon={Layers01Icon} strokeWidth={2} className="size-3.5" />
                  {t('regenerateAllLogs')}
                </Button>
              )}
            </div>
          )}

      </FramePanel>

      {/* The query is always available, never in the way. 照 ai-chat-11 的
          payload 面板：这次运行产出的工件单独一格、浅底，和结果正文分开。 */}
      {(dsl || turn.streamText) && (
        <FramePanel className="bg-muted/40 py-3 shadow-none!">
            <div className="space-y-3">
              <button
                type="button"
                onClick={() => setDslOpen((v) => !v)}
                className="inline-flex items-center gap-1 text-12 text-muted-foreground transition-colors hover:text-foreground"
              >
                {dslOpen ? (
                  <HugeiconsIcon icon={ChevronDownIcon} strokeWidth={2} className="size-3.5" />
                ) : (
                  <HugeiconsIcon icon={ChevronRightIcon} strokeWidth={2} className="size-3.5" />
                )}
                {t('showGeneratedQuery')}
                {turn.dslEdited && (
                  <span className="ml-1 inline-flex items-center gap-1 text-info">
                    <HugeiconsIcon icon={PencilIcon} strokeWidth={2} className="size-3" /> {t('handEdited')}
                  </span>
                )}
              </button>

              {dslOpen && (
                <div className="space-y-3">
                  <DslPreview
                    value={dsl}
                    streamingText={turn.streamText}
                    onChange={dsl ? onDslChange : undefined}
                  />
                  {dsl && (
                    <div className="flex flex-wrap items-center gap-2">
                      <Button
                        variant="outline" className="rounded-full"
                        size="sm"
                        onClick={onKibanaLink}
                        disabled={turn.kibanaLoading}
                      >
                        {turn.kibanaLoading ? (
                          <HugeiconsIcon icon={Loading03Icon} strokeWidth={2} className="size-3.5 animate-spin" />
                        ) : (
                          <HugeiconsIcon icon={ExternalLinkIcon} strokeWidth={2} className="size-3.5" />
                        )}
                        {t('openInKibana')}
                      </Button>
                      <Button variant="outline" className="rounded-full" size="sm" onClick={onSaveQuery}>
                        <HugeiconsIcon icon={Bookmark01Icon} strokeWidth={2} className="size-3.5" />
                        {t('saveAsQuery')}
                      </Button>
                      {!hasAggs && (
                        <label className="inline-flex items-center gap-1.5 text-12 text-muted-foreground">
                          <span className="font-mono text-11 uppercase tracking-wide">{t('takeFirst')}</span>
                          <select
                            value={turn.size}
                            onChange={(e) => onSizeChange(Number(e.target.value))}
                            className="cursor-pointer rounded-md bg-card px-1.5 py-1 text-12 text-foreground outline-none transition-shadow [box-shadow:var(--shadow-ring-light)] hover:[box-shadow:var(--shadow-ring)]"
                            title={t('sizeTitle')}
                          >
                            {[10, 50, 200, 1000].map((n) => (
                              <option key={n} value={n}>
                                {n}
                              </option>
                            ))}
                          </select>
                          <span>{t('unitRows')}</span>
                        </label>
                      )}
                    </div>
                  )}
                  {turn.kibanaError && (
                    <p className="text-12 text-destructive">
                      {t('errKibanaLink', { err: turn.kibanaError })}
                    </p>
                  )}
                </div>
              )}
            </div>
        </FramePanel>
      )}
    </Frame>
  )
}

/** chrome 条里各段之间的小圆点（照 ai-chat-11）。 */
function ChromeDot() {
  return <span aria-hidden="true" className="size-1 shrink-0 rounded-full bg-muted-foreground/40" />
}

/*
 * 实际生效的时间窗。只在用户选了范围时出现 —— 默认「全部时间」什么都不显示。
 *
 * `replaced` 那句是这枚 chip 存在的主要理由：问题里说的是「最近 30 分钟」，跑出去
 * 的是选择器选的窗口。悄悄改写用户的查询比不改更糟，所以要在结果旁边说出来。
 */
function TimeWindowChip({ window: w }: { window?: AppliedTimeWindow }) {
  const t = useT(chatCopy)
  if (!w) return null
  if (w.unsupported) {
    return (
      <span
        className="pill pill-gray text-destructive"
        title={t('noDateFieldTitle')}
      >
        {t('noDateField')}
      </span>
    )
  }
  const label = rangeLabel(
    w.since ? { kind: 'custom', since: w.since, until: w.until ?? undefined } : ALL_TIME,
  )
  /* 三种模式说三句不同的话。`intersected` 那句尤其不能省：问题里说的是「每天
     凌晨」这种形状，筛选器只是又收窄了一层，结果比两者单独看都少 —— 不说清楚
     的话，用户会以为筛选器没生效。 */
  const suffix =
    w.mode === 'question_wins'
      ? `${w.question_text ? t('windowQuestionText', { text: w.question_text }) : ''}${t('windowSynced')}`
      : w.mode === 'replaced'
        ? t('windowReplaced')
        : w.mode === 'intersected'
          ? t('windowIntersected')
          : ''
  return (
    <span className="pill pill-gray" title={w.field ? t('windowFieldTitle', { field: w.field }) : undefined}>
      {label}
      {suffix}
    </span>
  )
}

function IndexBreakdown({
  label,
  items,
  onPick,
}: {
  label: string
  items: IndexHitCount[]
  onPick: (index: string) => void
}) {
  const t = useT(chatCopy)
  return (
    <div className="flex flex-wrap items-center gap-x-3 gap-y-1.5 rounded-xl bg-accent px-3.5 py-2.5 text-12">
      <span className="flex items-center gap-1.5 text-fg-muted">
        <HugeiconsIcon icon={Layers01Icon} strokeWidth={2} className="size-3.5 shrink-0" />
        {label}
      </span>
      {items.slice(0, 4).map((d) => (
        <button
          key={d.index}
          type="button"
          onClick={() => onPick(d.index)}
          title={t('rerunOnIndex', { index: d.index })}
          className="font-mono text-foreground underline decoration-dotted underline-offset-2 transition-colors hover:text-info"
        >
          {d.index} ({d.count.toLocaleString()})
        </button>
      ))}
      <span className="text-fg-faint">{t('pickIndexHint')}</span>
    </div>
  )
}

function TurnError({
  message,
  onRetry,
  onRepair,
  onRegenerateInScope,
}: {
  message: string
  onRetry: () => void
  onRepair?: () => void
  onRegenerateInScope?: () => void
}) {
  const t = useT(chatCopy)
  const { hint } = classifyError(message)
  return (
    // Alert lays its children out on a grid whose first column is the icon
    // slot; anything dropped in beside the description becomes its own row and
    // wraps to nothing. The whole body is one description, one element deep.
    <Alert variant="destructive">
      <HugeiconsIcon icon={AlertCircleIcon} strokeWidth={2} className="size-4" />
      <AlertDescription>
        <div className="flex flex-col items-start gap-2">
          <span>{message}</span>
          {hint && <span className="text-xs leading-relaxed text-muted-foreground">{hint}</span>}
          <div className="flex flex-wrap gap-2">
        <Button variant="outline" size="sm" onClick={onRetry}>
          <HugeiconsIcon icon={RefreshCwIcon} strokeWidth={2} className="size-3.5" />
          {t('retry')}
        </Button>
        {onRepair && (
          <Button variant="outline" size="sm" onClick={onRepair}>
            <HugeiconsIcon icon={SparklesIcon} strokeWidth={2} className="size-3.5" />
            {t('repairWithError')}
          </Button>
        )}
        {onRegenerateInScope && (
          <Button variant="outline" size="sm" onClick={onRegenerateInScope}>
            <HugeiconsIcon icon={Layers01Icon} strokeWidth={2} className="size-3.5" />
            {t('regenerateAllLogsError')}
          </Button>
        )}
          </div>
        </div>
      </AlertDescription>
    </Alert>
  )
}

function FeedbackButtons({
  sent,
  onUp,
  onDownClick,
}: {
  sent: 'up' | 'down' | null
  onUp: () => void
  onDownClick: () => void
}) {
  const t = useT(chatCopy)
  const fbGate = useGate('write')
  const hintId = useId()
  if (sent === 'up') {
    return (
      <span className="inline-flex items-center gap-1.5 rounded-full bg-success-subtle px-2.5 py-1 text-11 font-medium text-success-foreground">
        <HugeiconsIcon icon={ThumbsUpIcon} strokeWidth={2} className="size-3" />
        {t('feedbackUpDone')}
      </span>
    )
  }
  if (sent === 'down') {
    return (
      <span className="inline-flex items-center gap-1.5 rounded-full bg-destructive-subtle px-2.5 py-1 text-11 font-medium text-destructive-foreground">
        <HugeiconsIcon icon={ThumbsDownIcon} strokeWidth={2} className="size-3" />
        {t('feedbackDownDone')}
      </span>
    )
  }
  return (
    <div className="flex items-center gap-1">
      <button
        type="button"
        aria-disabled={!fbGate.allowed || undefined}
        aria-describedby={fbGate.allowed ? undefined : hintId}
        onClick={fbGate.allowed ? onUp : undefined}
        className={cn(
          'inline-flex size-7 items-center justify-center rounded-md',
          'text-muted-foreground transition-colors',
          'hover:bg-success-subtle hover:text-success-foreground',
        )}
        title={fbGate.allowed ? t('feedbackUpTitle') : fbGate.reason}
      >
        <HugeiconsIcon icon={ThumbsUpIcon} strokeWidth={2} className="size-3.5" />
      </button>
      <button
        type="button"
        aria-disabled={!fbGate.allowed || undefined}
        aria-describedby={fbGate.allowed ? undefined : hintId}
        onClick={fbGate.allowed ? onDownClick : undefined}
        className={cn(
          'inline-flex size-7 items-center justify-center rounded-md',
          'text-muted-foreground transition-colors',
          'hover:bg-destructive-subtle hover:text-destructive-foreground',
        )}
        title={fbGate.allowed ? t('feedbackDownTitle') : fbGate.reason}
      >
        <HugeiconsIcon icon={ThumbsDownIcon} strokeWidth={2} className="size-3.5" />
      </button>
      {!fbGate.allowed && (
        <span id={hintId} className="sr-only">
          {fbGate.reason}
        </span>
      )}
    </div>
  )
}

function NegFeedbackForm({
  onCancel,
  onSubmit,
}: {
  onCancel: () => void
  onSubmit: (comment: string, suggestedDsl?: Record<string, unknown>) => void
}) {
  const t = useT(chatCopy)
  const c = useT(commonCopy)
  const [comment, setComment] = useState('')
  const [suggested, setSuggested] = useState('')
  const [jsonError, setJsonError] = useState<string | null>(null)

  function handleSubmit() {
    let parsed: Record<string, unknown> | undefined
    if (suggested.trim()) {
      try {
        parsed = JSON.parse(suggested) as Record<string, unknown>
      } catch {
        // 静默丢掉解析失败、只提交 comment 的话，界面随后会说「反馈已记录」，
        // 用户以为改好的 DSL 已经送出去了 —— 其实没有。停下来说一句。
        setJsonError(t('errBadJson'))
        return
      }
    }
    setJsonError(null)
    onSubmit(comment.trim(), parsed)
  }

  return (
    <div
      className={cn(
        'space-y-3 rounded-xl bg-destructive-subtle px-4 py-3',
        '[box-shadow:0_0_0_1px_rgba(255,91,79,0.2)]',
      )}
    >
      <div className="flex items-center gap-2">
        <HugeiconsIcon icon={ThumbsDownIcon} strokeWidth={2} className="size-3.5 text-destructive" />
        <span className="text-13 font-medium text-destructive-foreground">{t('negHeading')}</span>
      </div>
      {/* 写成事实（而不是抱怨）的会被沉淀成知识库条目，下次自动用上。
          例子放在 placeholder 里 —— 教这个形状最省的地方。 */}
      <Textarea
        value={comment}
        onChange={(e) => setComment(e.target.value)}
        placeholder={t('negCommentPlaceholder')}
        className="min-h-[60px] text-13"
      />
      <Textarea
        value={suggested}
        onChange={(e) => {
          setSuggested(e.target.value)
          setJsonError(null)
        }}
        placeholder={t('negDslPlaceholder')}
        className="min-h-[80px] font-mono text-12"
      />
      {jsonError ? (
        <p className="text-12 text-destructive-foreground">{jsonError}</p>
      ) : null}
      <div className="flex items-center gap-2">
        <Button variant="default" size="sm" onClick={handleSubmit}>
          <HugeiconsIcon icon={SendIcon} strokeWidth={2} className="size-3" />
          {t('submitFeedback')}
        </Button>
        <Button variant="ghost" size="sm" onClick={onCancel}>
          {c('cancel')}
        </Button>
      </div>
    </div>
  )
}

function phaseLabel(t: Translate<ChatKey>, p: Phase): string {
  return {
    generating: t('phaseGenerating'),
    executing: t('phaseExecuting'),
    done: t('phaseDone'),
    error: t('phaseError'),
  }[p]
}

function confidenceLabel(t: Translate<ChatKey>, c: 'low' | 'medium' | 'high'): string {
  return { low: t('confLow'), medium: t('confMedium'), high: t('confHigh') }[c]
}

function confidenceTone(c: 'low' | 'medium' | 'high') {
  if (c === 'high') return 'sev-info' as const
  if (c === 'medium') return 'gray' as const
  return 'sev-medium' as const
}

export default ChatPage
