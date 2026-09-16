import { memo, useCallback, useEffect, useMemo, useRef, useState } from 'react'
import { useNavigate } from '@tanstack/react-router'

import { GateNotice, GatedButton, useGate, useIsAdmin } from '@/components/gated-button'
import { Route as AlertsRoute } from '@/routes/_app/alerts'
import { useVirtualizer } from '@tanstack/react-virtual'
import { HugeiconsIcon } from '@hugeicons/react'
import { Activity02Icon, ArrowUp01Icon, BellRingIcon, Bookmark01Icon, Cancel01Icon, CheckIcon, ChevronDownIcon, ChevronRightIcon, CopyIcon, ExternalLinkIcon, Layers01Icon, ListChecksIcon, Loading03Icon, PauseIcon, PlayIcon, RadioIcon, Search01Icon, ShieldAlertIcon, SparklesIcon, TaskDone02Icon, TriangleAlertIcon, WifiDisconnected01Icon } from '@hugeicons/core-free-icons'
import {
  api,
  type AlertDetail,
  type AlertIngestStatus,
  type AlertKibanaLink,
  type ApiError,
  type AssetContext,
  type RealtimeAlert,
} from '@/lib/api'
import { toast } from 'sonner'
import { Frame, FrameDescription, FrameHeader, FramePanel, FrameTitle } from '@/components/reui/frame'
import { InputGroup, InputGroupAddon, InputGroupButton, InputGroupInput } from '@/components/ui/input-group'
import { MixDonut, type DonutSlice } from '@/components/blocks/chart-13/components/mix-donut'
import { TrendCard, type TrendStat } from '@/components/blocks/chart-18/components/trend-card'
import { SummaryCards, type SummaryCardData } from '@/components/blocks/solution-agents-1/components/summary-cards'
import { useT, translate } from '@/lib/i18n'
import { severityLabel } from '@/lib/severity'
import { alertsCopy, type AlertsKey } from '@/locales/alerts'
import { commonCopy } from '@/locales/common'
import { PageHeader } from '@/components/shell/page-header'
import { Button } from '@/components/ui/button'
import {
  Sheet, SheetContent, SheetFooter, SheetHeader, SheetTitle,
} from '@/components/ui/sheet'
import { Label } from '@/components/ui/label'
import { Input } from '@/components/ui/input'
import { Pill } from '@/components/ui/Pill'
import { Checkbox } from '@/components/ui/checkbox'
import {
  Collapsible,
  CollapsibleContent,
  CollapsibleTrigger,
} from '@/components/ui/collapsible'
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from '@/components/ui/select'
import { InvestigationDialog } from '@/components/InvestigationDialog'
import {
  buildDisplayItems,
  formatTs,
  matchesFilters,
  type Filters,
} from '@/lib/alertsFeed'
import { expandPath, setHandoff } from '@/lib/handoff'
import {
  parseRange, resolveRange, serializeRange, TimeRangePicker,
} from '@/components/shared/time-range-picker'
import { syncWarning } from '@/lib/syncHealth'
import {
  alertStatus,
  statusLabel,
  STATUS_ORDER,
  type TriageStatus,
} from '@/lib/triageStatus'
import { cn } from '@/lib/utils'
import { BlockError, BlockLoading } from '@/components/shared/block-states'

const DEFAULT_ALERT_INDEX = '.alerts-security.alerts-default'

/** Best doc + index to feed the investigation from an alert: the real _source
 * (detail.raw) when loaded, else synthesized from the normalized fields. Always
 * carries @timestamp so context gathering anchors on the event time. */
/** 接入方式：poll = 网关定时去拉，webhook = 对方推过来。页面上不写英文。 */
const ORIGIN_KEY: Record<string, AlertsKey> = { poll: 'originPoll', webhook: 'originWebhook' }

function originLabel(origin: string): string {
  const key = ORIGIN_KEY[origin]
  return key ? translate(alertsCopy, key) : origin
}

function alertToDoc(d: AlertDetail): Record<string, unknown> {
  if (d.raw && typeof d.raw === 'object') return d.raw as Record<string, unknown>
  const doc: Record<string, unknown> = {
    '@timestamp': d['@timestamp'],
    rule: { id: d.rule_id, name: d.rule_name },
    'kibana.alert.rule.name': d.rule_name,
  }
  if (d.subject_field && d.subject_value != null) {
    Object.assign(doc, expandPath(d.subject_field, String(d.subject_value)))
  }
  return doc
}

const SENTINEL_PREFIX = '<set ·' // masked-secret marker from GET /api/settings

/*
 * 实时告警 — backlog via /api/alerts (paged, backend cursor) + a live SSE stream
 * (/api/alerts/stream). EventSource auto-reconnects; we reflect status in a pill.
 * The feed is virtualized, groups consecutive same-subject alerts, and buffers
 * live pushes while the user has scrolled away from the top.
 */

const PAGE_SIZE = 50
const ROW_EST = 56 // px — virtualizer size hint; rows re-measure on mount
const OVERSCAN = 8
const RULE_DEBOUNCE_MS = 400
const TOP_THRESHOLD_PX = 8 // scrollTop under this counts as "at top"
const VIEWS_KEY = 'rst.alertViews'
// How long the undo offer stays on screen after a disposition.
const UNDO_MS = 10_000
// 概览聚合最快多久跟一次实时告警。
const STATS_REFRESH_MS = 30_000

const RANGE_MS: Record<string, number> = {
  '5m': 300_000,
  '15m': 900_000,
  '30m': 1_800_000,
  '1h': 3_600_000,
  '6h': 21_600_000,
  '12h': 43_200_000,
  '24h': 86_400_000,
  '7d': 604_800_000,
}
/** 告警排查的档位比别处密：值班时「刚刚有没有新的」问的是 5 分钟。 */
const ALERT_PRESETS = ['5m', '15m', '1h', '6h', '24h', '7d']

/* 环形图里严重度用自己的语义色，不用图表调色板 —— critical 不是"轮到哪个槽
   就是哪个颜色"。刻度跟 Pill 的那套一致：越高越红，critical 单独跳出色阶。 */
const SEV_FILL: Record<string, string> = {
  critical: 'var(--color-foreground)',
  high: 'var(--color-destructive)',
  medium: 'var(--color-warning)',
  low: 'var(--color-muted-foreground)',
  info: 'var(--color-info)',
}

/* 概览图上的时间范围。比筛选器里那 9 档少 —— 这是"看趋势"的粒度，
   5 分钟窗口画不出趋势，只会得到一根柱。 */
const OVERVIEW_RANGES: { value: string; label: AlertsKey }[] = [
  { value: '1h', label: 'range1h' },
  { value: '6h', label: 'range6h' },
  { value: '24h', label: 'range24h' },
  { value: '7d', label: 'range7d' },
]

/** 速率图的横轴标签。窗口越长刻度越粗 —— 7 天的图上写时分只会糊成一片。 */
function formatBucket(ts: string, range: string) {
  const d = new Date(ts)
  if (Number.isNaN(d.getTime())) return ts
  const hh = String(d.getHours()).padStart(2, '0')
  const mm = String(d.getMinutes()).padStart(2, '0')
  if (range === '7d') return `${d.getMonth() + 1}/${d.getDate()}`
  if (range === '1h') return `${hh}:${mm}`
  return `${hh}:00`
}

const SEVERITIES = ['info', 'low', 'medium', 'high', 'critical'] as const
const SEV_TONE: Record<string, 'sev-info' | 'sev-low' | 'sev-medium' | 'sev-high' | 'sev-critical'> = {
  info: 'sev-info',
  low: 'sev-low',
  medium: 'sev-medium',
  high: 'sev-high',
  critical: 'sev-critical',
}

interface SavedView extends Filters {
  name: string
}

function loadViews(): SavedView[] {
  try {
    const raw = localStorage.getItem(VIEWS_KEY)
    if (!raw) return []
    const parsed = JSON.parse(raw)
    return Array.isArray(parsed) ? (parsed as SavedView[]) : []
  } catch {
    return []
  }
}

/* Data + SSE + pagination + pause/buffer. Kept as one hook so the page body is
 * just rendering. Refs mirror state the (mount-once) SSE handler reads. */
function useAlertFeed(filters: Filters) {
  const [alerts, setAlerts] = useState<RealtimeAlert[]>([])
  const [buffer, setBuffer] = useState<RealtimeAlert[]>([])
  const [loading, setLoading] = useState(true)
  const [loadingMore, setLoadingMore] = useState(false)
  const [hasMore, setHasMore] = useState(true)
  const [error, setError] = useState<string | null>(null)
  const [connected, setConnected] = useState(false)
  const [manualPaused, setManualPaused] = useState(false)
  const [atTop, setAtTop] = useState(true)

  const scrollRef = useRef<HTMLDivElement | null>(null)
  const mountedRef = useRef(true)
  const atTopRef = useRef(true)
  const manualPausedRef = useRef(false)
  const filtersRef = useRef(filters)
  const sinceRef = useRef<string | undefined>(undefined)
  const untilRef = useRef<string | undefined>(undefined)
  const alertsRef = useRef<RealtimeAlert[]>([])
  const bufferRef = useRef<RealtimeAlert[]>([])
  const hasMoreRef = useRef(true)
  const loadingMoreRef = useRef(false)

  // Sync render-visible state into refs the SSE / scroll closures read.
  // In an effect, not during render: writing a ref while rendering is a side
  // effect in what must be a pure function, and React may render a component
  // more than once per commit. No dependency array — this has to run after
  // EVERY render or a closure reads a stale value. Both readers (the SSE
  // handler and the scroll handler) fire after paint, so being one commit
  // "late" during render is not observable to them.
  useEffect(() => {
    filtersRef.current = filters
    alertsRef.current = alerts
    bufferRef.current = buffer
    manualPausedRef.current = manualPaused
    hasMoreRef.current = hasMore
    loadingMoreRef.current = loadingMore
  })

  useEffect(() => {
    mountedRef.current = true
    return () => {
      mountedRef.current = false
    }
  }, [])

  // Page 1: refetch whenever a filter changes. `since` is fixed at query time
  // (Date.now reference) and reused for the cursor + live gating for this query.
  useEffect(() => {
    let alive = true
    const { since, until } = resolveRange(parseRange(filters.timeRange))
    sinceRef.current = since
    untilRef.current = until
    setLoading(true)
    setError(null)
    setBuffer([])
    setHasMore(true)
    api
      .alertsList({
        limit: PAGE_SIZE,
        severity: filters.severity || undefined,
        rule: filters.rule || undefined,
        since,
        until,
      })
      .then((r) => {
        if (!alive) return
        setAlerts(r.alerts)
        setHasMore(r.alerts.length >= PAGE_SIZE)
      })
      .catch((e) => alive && setError((e as ApiError).message || translate(alertsCopy, 'errLoad')))
      .finally(() => alive && setLoading(false))
    return () => {
      alive = false
    }
  }, [filters.severity, filters.rule, filters.timeRange])

  const loadMore = useCallback(() => {
    if (loadingMoreRef.current || !hasMoreRef.current) return
    const cur = alertsRef.current
    const oldest = cur[cur.length - 1]
    if (!oldest) return
    loadingMoreRef.current = true
    setLoadingMore(true)
    const f = filtersRef.current
    api
      .alertsList({
        limit: PAGE_SIZE,
        severity: f.severity || undefined,
        rule: f.rule || undefined,
        since: sinceRef.current,
        before: oldest['@timestamp'],
      })
      .then((r) => {
        if (!mountedRef.current) return
        // 请求飞在路上时用户可能改了严重度／规则／时间窗：页 1 的 effect 已经用新
        // 筛选重取并 setAlerts 了，这一页是按旧筛选取的，append 进去就是把不该出现
        // 的告警塞进列表。filters 是 useMemo 对象，筛选没变时引用不变。
        if (filtersRef.current !== f) return
        const seen = new Set(alertsRef.current.map((a) => a.alert_id))
        const fresh = r.alerts.filter((a) => !seen.has(a.alert_id))
        setAlerts((prev) => {
          const cur = new Set(prev.map((a) => a.alert_id))
          return [...prev, ...fresh.filter((a) => !cur.has(a.alert_id))]
        })
        // 光看 r.alerts.length 会热循环：游标是 before=最旧一条的 @timestamp，若整页
        // 都是已在列表里的 id（例如 ≥PAGE_SIZE 条告警共享同一个 @timestamp），列表和
        // 最旧时间戳都不变，hasMore 仍为 true，loadingMore 一落地就再发同一个请求。
        // 这一轮去重后没有新增行 = 游标推不动，收摊。
        setHasMore(fresh.length > 0 && r.alerts.length >= PAGE_SIZE)
      })
      // 翻页失败原来整个吞掉，用户点「加载更多」只看到毫无反应。复用这一页顶部
      // 那条错误横幅。
      .catch((e) => {
        if (mountedRef.current && filtersRef.current === f) {
          setError((e as ApiError).message || translate(alertsCopy, 'errLoadMore'))
        }
      })
      .finally(() => {
        loadingMoreRef.current = false
        if (mountedRef.current) setLoadingMore(false)
      })
  }, [])

  const flushBuffer = useCallback(() => {
    const buf = bufferRef.current
    if (buf.length) {
      setAlerts((prev) => {
        const seen = new Set(prev.map((a) => a.alert_id))
        return [...buf.filter((a) => !seen.has(a.alert_id)), ...prev]
      })
    }
    setBuffer([])
    scrollRef.current?.scrollTo({ top: 0 })
    atTopRef.current = true
    setAtTop(true)
  }, [])

  const handleScroll = useCallback(() => {
    const el = scrollRef.current
    if (!el) return
    const top = el.scrollTop <= TOP_THRESHOLD_PX
    const wasTop = atTopRef.current
    atTopRef.current = top
    setAtTop(top)
    // Returned to top with no manual pause → auto-resume + flush the buffer.
    if (top && !wasTop && !manualPausedRef.current) flushBuffer()
  }, [flushBuffer])

  // SSE opened once; auto-reconnects. Live alerts are gated by the active
  // filters, then either prepended (live, at top) or buffered (paused/scrolled).
  useEffect(() => {
    const es = new EventSource('/api/alerts/stream')
    es.onopen = () => mountedRef.current && setConnected(true)
    es.onerror = () => mountedRef.current && setConnected(false)
    es.onmessage = (e) => {
      let a: RealtimeAlert
      try {
        a = JSON.parse(e.data) as RealtimeAlert
      } catch {
        return
      }
      if (!matchesFilters(a, filtersRef.current, sinceRef.current, untilRef.current)) return
      const pausedEffective = manualPausedRef.current || !atTopRef.current
      if (pausedEffective) {
        setBuffer((prev) => (prev.some((x) => x.alert_id === a.alert_id) ? prev : [a, ...prev]))
      } else {
        setAlerts((prev) => (prev.some((x) => x.alert_id === a.alert_id) ? prev : [a, ...prev]))
      }
    }
    return () => es.close()
  }, [])

  return {
    alerts,
    buffer,
    loading,
    loadingMore,
    hasMore,
    error,
    connected,
    manualPaused,
    setManualPaused,
    atTop,
    scrollRef,
    handleScroll,
    flushBuffer,
    loadMore,
  }
}

/*
 * 概览读的是服务端聚合，不是屏幕上那几行。
 *
 * 流是无限滚动的：手上永远只有已经加载的那一段，用它算"这一天各严重度多少条"
 * 会随着往下滚一直变。所以严重度分布、到达速率、Top 规则都由 `/api/alerts/stats`
 * 在整个窗口上算。严重度筛选不传给它 —— 那正是它要画的东西。
 */
function useAlertStats(range: string, rule: string, newestId: string | undefined) {
  const [stats, setStats] = useState<{
    total: number
    by_severity: { key: string; count: number }[]
    by_rule: { key: string; count: number }[]
    over_time: { ts: string; count: number }[]
  } | null>(null)
  const [error, setError] = useState<string | null>(null)

  useEffect(() => {
    let live = true
    const ms = RANGE_MS[range]
    void api
      .alertsStats({
        rule: rule || undefined,
        since: ms ? new Date(Date.now() - ms).toISOString() : undefined,
      })
      .then((r) => {
        if (!live) return
        setStats(r)
        setError(null)
      })
      .catch((e) => {
        // 概览挂了不把告警流一起拖下水 —— 流才是这一页的主体。但也不能把它
        // 画成 0：算不出来和没有告警是两回事，下面那张流里可能正列着五十条。
        if (!live) return
        setStats(null)
        setError(e instanceof Error ? e.message : String(e))
      })
    return () => {
      live = false
    }
  }, [range, rule, newestId])

  return { stats, error }
}

export default function RealtimeAlertsPage() {
  const t = useT(alertsCopy)
  const c = useT(commonCopy)
  const navigate = useNavigate()
  /*
   * 深链参数。别的页面（安全态势的「最近告警」「最吵的规则」）要能指到这里的
   * 某一条、某一类，而不是把人扔在列表首页自己找。
   *
   *   ?alert=<alert_id>   打开这一条的详情
   *   ?rule=<rule 关键字>  用它预置规则筛选
   *
   * 用完就把参数从地址栏抹掉（replace，不进历史）：留着的话，用户手动改了筛选、
   * 关掉了弹窗，一刷新又跳回原样，等于筛选条被地址栏劫持。
   */
  const { alert: deepLinkAlert, rule: deepLinkRule } = AlertsRoute.useSearch()
  /* 抹掉一个深链参数。两处调用形状一样，提出来只是为了不把
     `navigate({ search })` 那一堆泛型写两遍。 */
  const clearDeepLink = AlertsRoute.useNavigate()
  // `alertId` is carried explicitly: `doc` is the RAW ES document, which has no
  // alert_id of ours to dig back out.
  const [investigate, setInvestigate] =
    useState<{ doc: Record<string, unknown>; index: string; alertId: string } | null>(null)
  const [severity, setSeverity] = useState('')
  // 序列化成字符串存：已保存的视图里放的就是它，老视图（'6h'）继续有效。
  const [timeRange, setTimeRange] = useState('')
  const [ruleInput, setRuleInput] = useState('')
  const [rule, setRule] = useState('')
  const [grouped, setGrouped] = useState(true)
  const [expanded, setExpanded] = useState<Set<string>>(() => new Set())
  const [selected, setSelected] = useState<RealtimeAlert | null>(null)
  const [views, setViews] = useState<SavedView[]>(() => loadViews())
  const [viewName, setViewName] = useState('')

  // Debounce the rule text before it becomes an active (refetching) filter.
  useEffect(() => {
    const id = setTimeout(() => setRule(ruleInput.trim()), RULE_DEBOUNCE_MS)
    return () => clearTimeout(id)
  }, [ruleInput])

  /* ?rule= 直接落成筛选。两个 state 都写：ruleInput 是输入框里看得见的字，rule 是
     真正在过滤的值 —— 只写后者的话，输入框是空的但列表被筛着，没人找得到怎么清。 */
  useEffect(() => {
    if (!deepLinkRule) return
    setRuleInput(deepLinkRule)
    setRule(deepLinkRule)
    void clearDeepLink({ search: (prev) => ({ ...prev, rule: undefined }), replace: true })
  }, [deepLinkRule, clearDeepLink])

  const filters = useMemo<Filters>(() => ({ severity, rule, timeRange }), [severity, rule, timeRange])
  /* 概览自己的时间窗，和下面流的筛选分开：流常常盯着"近 15 分钟"，
     而"这一天怎么走的"要的是更长的一段。 */
  const [overviewRange, setOverviewRange] = useState('24h')
  const feed = useAlertFeed(filters)
  const { alerts, buffer, loading, loadingMore, hasMore, error, connected, manualPaused, setManualPaused, atTop, loadMore } =
    feed

  /* Disposition. Team-shared, same machinery as triage but its own namespace.
   * Without it this page was read-only: a false positive could not be closed
   * out, so it stayed at the top of the list forever and the next analyst had
   * to re-judge it. Marking is NOT deletion — the alert stays queryable and
   * auditable, it just leaves the working set. */
  const [dispo, setDispo] = useState<Record<string, TriageStatus>>({})
  const [showHandled, setShowHandled] = useState(false)
  const [picked, setPicked] = useState<Set<string>>(() => new Set())
  const [dispoWarn, setDispoWarn] = useState<string | null>(null)

  useEffect(() => {
    void alertStatus.loadStatuses().then(setDispo)
  }, [])

  /* ?alert= 打开那一条。不从已加载的流里找 —— 那条可能被当前筛选或时间窗排除在
     外，甚至根本不在第一页；直接按 id 取详情，取不到就当没这个参数（记录可能已经
     过期或被删），不打断这一页本来的用法。AlertDetail 是 RealtimeAlert 的超集。 */
  useEffect(() => {
    if (!deepLinkAlert) return
    let alive = true
    void api
      .alertDetail(deepLinkAlert)
      .then((d) => { if (alive) setSelected(d) })
      .catch(() => {})
    void clearDeepLink({ search: (prev) => ({ ...prev, alert: undefined }), replace: true })
    return () => { alive = false }
  }, [deepLinkAlert, clearDeepLink])

  const visibleAlerts = useMemo(() => {
    if (showHandled) return alerts
    return alerts.filter((a) => {
      const s = dispo[a.alert_id]
      return s !== 'handled' && s !== 'fp'
    })
  }, [alerts, dispo, showHandled])

  const closedCount = alerts.length - visibleAlerts.length

  /* 概览的刷新节奏。直接把 alerts[0]?.alert_id 当依赖，SSE 每推一条新告警就换一次
     值，等于每条实时告警都重打一次 /api/alerts/stats 的聚合查询 —— 告警高峰期请求
     量是按告警速率走的。改成固定 30s 采样一次最新 id：请求量按时间封顶，与告警速率
     无关。代价是概览最多滞后 30s；它是趋势图，滞后半分钟读不出差别，而下面的告警流
     仍然是逐条实时的。 */
  const newestId = alerts[0]?.alert_id
  const newestIdRef = useRef(newestId)
  useEffect(() => {
    newestIdRef.current = newestId
  })
  const [statsTick, setStatsTick] = useState(newestId)
  useEffect(() => {
    // 值没变时 setState 不会触发重渲染，所以空转的定时器是免费的。
    const id = window.setInterval(() => setStatsTick(newestIdRef.current), STATS_REFRESH_MS)
    return () => window.clearInterval(id)
  }, [])

  const { stats, error: statsError } = useAlertStats(overviewRange, rule, statsTick)

  const ratePoints = useMemo(
    () =>
      (stats?.over_time ?? []).map((p) => ({
        period: formatBucket(p.ts, overviewRange),
        value: p.count,
      })),
    [overviewRange, stats],
  )

  const sevSlices = useMemo<DonutSlice[]>(() => {
    const rows = stats?.by_severity ?? []
    // 按严重度排序，不按数量 —— 图例要读成一把刻度尺，而不是排行榜。
    const order = [...SEVERITIES].reverse() as readonly string[]
    return [...rows]
      .sort((a, b) => order.indexOf(a.key) - order.indexOf(b.key))
      .map((r) => ({
        key: r.key,
        name: severityLabel(r.key),
        count: r.count,
        color: SEV_FILL[r.key],
      }))
  }, [stats])

  /* solution-agents-1 第一行的四张摘要卡：窗口内告警 / 高危以上 / 已处置 / 连接。
     前两个读服务端聚合（和折线同一次查询），后两个是这条流自己的状态。 */
  const summaryCards = useMemo<SummaryCardData[]>(() => {
    const rows = stats?.by_severity ?? []
    const urgent = rows.filter((r) => r.key === 'critical' || r.key === 'high').reduce((n, r) => n + r.count, 0)
    const num = (n: number) => (stats ? n.toLocaleString() : '—')
    return [
      {
        id: 'total',
        title: `${num(stats?.total ?? 0)} ${t('kpiAlertsUnit')}`,
        description: t('sumTotalDesc', { range: t(OVERVIEW_RANGES.find((r) => r.value === overviewRange)?.label ?? 'range24h') }),
        icon: <HugeiconsIcon icon={BellRingIcon} strokeWidth={2} aria-hidden="true" />,
        iconBg: 'bg-primary',
      },
      {
        id: 'urgent',
        title: num(urgent),
        description: t('sumUrgentDesc'),
        icon: <HugeiconsIcon icon={TriangleAlertIcon} strokeWidth={2} aria-hidden="true" />,
        iconBg: stats && urgent > 0 ? 'bg-destructive' : 'bg-success',
      },
      {
        id: 'closed',
        title: String(closedCount),
        description: t('sumClosedDesc', { n: alerts.length }),
        icon: <HugeiconsIcon icon={TaskDone02Icon} strokeWidth={2} aria-hidden="true" />,
        iconBg: 'bg-info',
      },
      {
        id: 'stream',
        title: connected ? t('live') : t('paused'),
        description: manualPaused ? t('sumStreamPaused') : connected ? t('sumStreamLive') : t('sumStreamDown'),
        icon: <HugeiconsIcon icon={connected ? RadioIcon : WifiDisconnected01Icon} strokeWidth={2} aria-hidden="true" />,
        iconBg: connected ? 'bg-success' : 'bg-warning',
      },
    ]
  }, [stats, t, overviewRange, closedCount, alerts.length, connected, manualPaused])

  const overviewStats = useMemo<TrendStat[]>(() => {
    const rows = stats?.by_severity ?? []
    const urgent = rows
      .filter((r) => r.key === 'critical' || r.key === 'high')
      .reduce((sum, r) => sum + r.count, 0)
    const topRule = stats?.by_rule?.[0]
    // 没算出来时写 —— 不是 0：0 会被读成"这段时间很安静"。
    const num = (n: number) => (stats ? n.toLocaleString() : '—')
    return [
      {
        id: 'total',
        label: t('kpiAlerts'),
        value: num(stats?.total ?? 0),
        note: stats ? t('kpiAlertsUnit') : undefined,
        icon: <HugeiconsIcon icon={BellRingIcon} strokeWidth={2} aria-hidden="true" />,
      },
      {
        id: 'urgent',
        label: t('kpiUrgent'),
        value: num(urgent),
        tone: stats && urgent > 0 ? 'destructive' : 'default',
        icon: <HugeiconsIcon icon={TriangleAlertIcon} strokeWidth={2} aria-hidden="true" />,
      },
      {
        id: 'top',
        label: t('kpiNoisiest'),
        value: topRule ? String(topRule.count) : '—',
        note: topRule?.key,
        icon: <HugeiconsIcon icon={Activity02Icon} strokeWidth={2} aria-hidden="true" />,
      },
    ]
  }, [stats, t])

  /* Applies a disposition and returns the statuses it replaced, so the caller
   * can put them back. Marking is instant and removes the row from the default
   * view — without an undo, a mis-click means hunting for the row behind the
   * 显示已处置 toggle to reverse it. */
  const applyDispo = useCallback(
    async (ids: string[], next: TriageStatus): Promise<Record<string, TriageStatus>> => {
      const prev: Record<string, TriageStatus> = {}
      setDispo((cur) => {
        const m = { ...cur }
        for (const id of ids) {
          prev[id] = cur[id] ?? 'open'
          if (next === 'open') delete m[id]
          else m[id] = next
        }
        return m
      })
      const oks = await Promise.all(ids.map((id) => alertStatus.saveStatus(id, next)))
      setDispoWarn(oks.every(Boolean) ? null : syncWarning(translate(alertsCopy, 'syncScopeStatus')))
      return prev
    },
    [],
  )

  /** Put every affected alert back to what it was, grouped by target status. */
  const runUndo = useCallback(
    async (prev: Record<string, TriageStatus>) => {
      const byStatus = new Map<TriageStatus, string[]>()
      for (const [id, s] of Object.entries(prev)) {
        const list = byStatus.get(s) ?? []
        list.push(id)
        byStatus.set(s, list)
      }
      for (const [s, ids] of byStatus) await applyDispo(ids, s)
    },
    [applyDispo],
  )

  /* Marking is instant and drops the row out of the default view, so a mis-click
   * means hunting for it behind the 显示已处置 toggle. The undo used to be a
   * bar rendered inside the card with its own state, ref-mirror and timeout;
   * sonner already owns "a message with one action that expires", so the whole
   * mechanism is the toast's `action` plus the `prev` this closure captured. */
  const markDispo = useCallback(
    async (ids: string[], next: TriageStatus) => {
      if (ids.length === 0) return
      setPicked(new Set())
      const prev = await applyDispo(ids, next)
      toast(t('markedToast', { n: ids.length, status: statusLabel(next) }), {
        duration: UNDO_MS,
        action: { label: t('undo'), onClick: () => void runUndo(prev) },
      })
    },
    [applyDispo, runUndo, t],
  )

  const items = useMemo(
    () => buildDisplayItems(visibleAlerts, grouped, expanded),
    [visibleAlerts, grouped, expanded],
  )

  const virt = useVirtualizer({
    count: items.length,
    getScrollElement: () => feed.scrollRef.current,
    estimateSize: () => ROW_EST,
    overscan: OVERSCAN,
  })
  const virtualItems = virt.getVirtualItems()

  // Infinite scroll driven off the virtualizer: once the last virtual row is the
  // last display item, ask for the next backend page (guarded inside loadMore).
  useEffect(() => {
    const last = virtualItems[virtualItems.length - 1]
    if (last && last.index >= items.length - 1) loadMore()
  }, [virtualItems, items.length, loadMore])

  // ...but the virtualizer only exists while there is something to virtualize.
  // Disposition every loaded alert and `items` empties, the scroll container
  // unmounts, `virtualItems` is empty, and the effect above can never fire
  // again — so the backlog stops loading exactly when the analyst has cleared
  // the visible page, which is the normal way to work a queue. Keep pulling
  // while the server still has pages and everything fetched is closed out.
  useEffect(() => {
    if (items.length === 0 && alerts.length > 0 && hasMore && !loading && !loadingMore) {
      loadMore()
    }
  }, [items.length, alerts.length, hasMore, loading, loadingMore, loadMore])

  const togglePick = useCallback((id: string) => {
    setPicked((cur) => {
      const next = new Set(cur)
      if (next.has(id)) next.delete(id)
      else next.add(id)
      return next
    })
  }, [])

  const toggleGroup = useCallback((key: string) => {
    setExpanded((prev) => {
      const next = new Set(prev)
      if (next.has(key)) next.delete(key)
      else next.add(key)
      return next
    })
  }, [])

  function persistViews(next: SavedView[]) {
    setViews(next)
    try {
      localStorage.setItem(VIEWS_KEY, JSON.stringify(next))
    } catch {
      /* localStorage disabled — won't persist, OK */
    }
  }
  function saveCurrentView() {
    const name = viewName.trim()
    if (!name) return
    persistViews([...views.filter((v) => v.name !== name), { name, severity, rule, timeRange }])
    setViewName('')
  }
  function applyView(v: SavedView) {
    setSeverity(v.severity)
    setRuleInput(v.rule)
    setRule(v.rule) // apply immediately, skip debounce
    setTimeRange(v.timeRange)
  }

  return (
    <div className="@container flex w-full flex-col gap-5">
      <PageHeader
        title={t('title')}
        actions={<ConnectionPill connected={connected} />}
      />

      <section aria-label={t('secSummary')}>
        <SummaryCards cards={summaryCards} />
      </section>

      {/* 概览：这一段时间里告警怎么来的、都是什么严重度。读的是服务端聚合，
          所以它说的是整个窗口，不是下面已经滚出来的那几行。 */}
      <section
        aria-label={t('secOverview')}
        className="grid min-w-0 auto-rows-fr items-stretch gap-5 @4xl:grid-cols-3"
      >
        <TrendCard
          className="h-full min-w-0 @4xl:col-span-2"
          title={t('chartRate')}
          tabs={OVERVIEW_RANGES.map((r) => ({ value: r.value, label: t(r.label) }))}
          activeTab={overviewRange}
          onTabChange={setOverviewRange}
          stats={overviewStats}
          points={ratePoints}
          valueLabel={t('unitAlerts')}
          empty={statsError ? t('statsError', { err: statsError }) : t('noAlertsInWindow')}
        />
        <MixDonut
          className="h-full"
          title={t('severityMix')}
          centerLabel={t('centerAlerts')}
          slices={sevSlices}
          emptyText={statsError ? t('statsErrorDonut') : t('noAlertsInWindow')}
        />
      </section>


      {error && <BlockError message={error} />}

      <section aria-label={t('secFeed')}>
      <Frame dense spacing="sm" className="flex w-full min-w-0 flex-col [--frame-panel-header-py-adjust:2px]">
        {/* 卡头照 solution-agents-1 的 Run Queue：左「标题 + 在看几条」，右边是流的开关。 */}
        <FrameHeader className="flex-row items-center justify-between gap-3">
          <div className="flex flex-col gap-px">
            <FrameTitle className="text-balance">{t('feedTitle')}</FrameTitle>
            <FrameDescription className="text-xs text-pretty">{t('countAlerts', { n: alerts.length })}</FrameDescription>
          </div>
          <div className="flex shrink-0 items-center gap-2">
            <Button variant={grouped ? 'default' : 'outline'} className="rounded-full" size="sm" onClick={() => setGrouped((g) => !g)}>
              <HugeiconsIcon icon={Layers01Icon} strokeWidth={2} className="size-3.5" /> {t('group')}
            </Button>
            <Button variant="outline" size="sm" onClick={() => setManualPaused((p) => !p)} title={manualPaused ? t('paused') : !atTop ? t('pausedOffTop') : t('live')}>
              <HugeiconsIcon icon={manualPaused ? PlayIcon : PauseIcon} strokeWidth={2} className="size-3.5" />
              {manualPaused ? t('resume') : t('pause')}
            </Button>
          </div>
        </FrameHeader>
        <FramePanel className="flex flex-col gap-3 bg-card shadow-none!">
          <FilterBar
            severity={severity}
            onSeverity={setSeverity}
            ruleInput={ruleInput}
            onRuleInput={setRuleInput}
            timeRange={timeRange}
            onTimeRange={setTimeRange}
            views={views}
            viewName={viewName}
            onViewName={setViewName}
            onSaveView={saveCurrentView}
            onApplyView={applyView}
            onDeleteView={(name) => persistViews(views.filter((v) => v.name !== name))}
          />

          {/* Disposition controls. Closed alerts leave the working set by
              default — a false positive that stays pinned at the top is the
              reason this page felt unusable — but they are one toggle away and
              never deleted. */}
          <div className="flex flex-wrap items-center gap-x-3 gap-y-1.5">
            <Label className="cursor-pointer text-xs font-normal text-muted-foreground">
              <Checkbox checked={showHandled} onCheckedChange={() => setShowHandled((v) => !v)} />
              {t('showClosed')}
            </Label>
            {closedCount > 0 && !showHandled && (
              <span className="text-12 text-muted-foreground">
                {t('hiddenClosed', { n: closedCount })}
              </span>
            )}
            {picked.size > 0 && (
              <span className="ml-auto inline-flex flex-wrap items-center gap-2">
                <span className="font-mono text-xs">{t('picked', { n: picked.size })}</span>
                <Button variant="outline" size="sm" onClick={() => void markDispo([...picked], 'handled')}>{t('markHandled')}</Button>
                <Button variant="outline" size="sm" onClick={() => void markDispo([...picked], 'fp')}>{t('markFp')}</Button>
                <Button variant="outline" size="sm" onClick={() => void markDispo([...picked], 'open')}>{t('markOpen')}</Button>
                <Button variant="ghost" size="sm" onClick={() => setPicked(new Set())}>{t('clearSelection')}</Button>
              </span>
            )}
          </div>
          {dispoWarn && <p className="text-xs text-destructive">{dispoWarn}</p>}

          {loading ? (
            <BlockLoading className="py-12 text-13" />
          ) : items.length === 0 ? (
            /* Two very different situations used to share one message. Telling
               an operator whose ingest is working perfectly to go configure
               ingest — because the analyst had just closed out every alert on
               screen — sent people to debug a healthy pipeline. */
            alerts.length > 0 ? (
              <div className="py-10 text-center text-13 leading-[1.7] text-muted-foreground">
                {t('allClosed', { n: alerts.length })}
                {hasMore && (loadingMore ? t('loadingMoreInline') : t('fetchingOlder'))}
                <div className="pt-2">
                  <button
                    type="button"
                    onClick={() => setShowHandled(true)}
                    className="text-12 text-link hover:underline"
                  >
                    {t('showClosed')}
                  </button>
                  {hasMore && !loadingMore && (
                    <>
                      <span className="px-2 text-fg-faint">·</span>
                      <button
                        type="button"
                        onClick={() => loadMore()}
                        className="text-12 text-link hover:underline"
                      >
                        {t('loadMore')}
                      </button>
                    </>
                  )}
                </div>
              </div>
            ) : (
              <p className="py-10 text-center text-13 leading-[1.7] text-muted-foreground">
                {t('noAlertsYet')}
              </p>
            )
          ) : (
            <div className="relative">
              {buffer.length > 0 && (
                <button
                  type="button"
                  onClick={feed.flushBuffer}
                  className="absolute left-1/2 top-2 z-10 inline-flex -translate-x-1/2 items-center gap-1.5 rounded-full bg-foreground px-3 py-1 text-12 font-medium text-primary-foreground [box-shadow:var(--shadow-ring)] transition-all hover:opacity-90 active:scale-[0.98]"
                >
                  <HugeiconsIcon icon={ArrowUp01Icon} strokeWidth={2} className="size-3.5" />
                  {t('newAlerts', { n: buffer.length })}
                </button>
              )}
              <div
                ref={feed.scrollRef}
                onScroll={feed.handleScroll}
                /* 四边都要留一点：告警行的边框不是 border，是 box-shadow 画的
                   1px 环（--shadow-ring-light），它落在元素盒子外面。原来只有
                   pr-1，于是左边和顶上的那一圈被 overflow 裁掉 —— 看起来像"框
                   没画全"。焦点环是 2px，4px 的内边距两个都够。 */
                className="max-h-[calc(100vh-360px)] min-h-[360px] overflow-y-auto p-1"
              >
                <div style={{ height: `${virt.getTotalSize()}px`, width: '100%', position: 'relative' }}>
                  {virtualItems.map((vi) => {
                    const item = items[vi.index]
                    return (
                      <div
                        key={item.id}
                        data-index={vi.index}
                        ref={virt.measureElement}
                        style={{
                          position: 'absolute',
                          top: 0,
                          left: 0,
                          width: '100%',
                          transform: `translateY(${vi.start}px)`,
                          paddingBottom: 6,
                        }}
                      >
                        {item.kind === 'group' ? (
                          <AlertRow
                            alert={item.head}
                            count={item.count}
                            expanded={item.expanded}
                            onToggle={() => toggleGroup(item.groupKey)}
                            onClick={() => setSelected(item.head)}
                            status={dispo[item.head.alert_id] ?? 'open'}
                            onStatus={(s) => void markDispo([item.head.alert_id], s)}
                            checked={picked.has(item.head.alert_id)}
                            onCheck={() => togglePick(item.head.alert_id)}
                          />
                        ) : (
                          <AlertRow
                            alert={item.alert}
                            child={item.child}
                            onClick={() => setSelected(item.alert)}
                            status={dispo[item.alert.alert_id] ?? 'open'}
                            onStatus={(s) => void markDispo([item.alert.alert_id], s)}
                            checked={picked.has(item.alert.alert_id)}
                            onCheck={() => togglePick(item.alert.alert_id)}
                          />
                        )}
                      </div>
                    )
                  })}
                </div>
                {/* 外层也要进条件：还能继续加载时里面渲染 null，但这个 div 照样
                    占 24px，在列表底下留一条谁也看不出是什么的空白。 */}
                {(loadingMore || !hasMore) && (
                  <div className="py-3 text-center text-12 text-muted-foreground">
                    {loadingMore ? (
                      <span className="inline-flex items-center gap-1.5">
                        <HugeiconsIcon icon={Loading03Icon} strokeWidth={2} className="size-3.5 animate-spin" /> {c('loading')}…
                      </span>
                    ) : (
                      t('noMore')
                    )}
                  </div>
                )}
              </div>
            </div>
          )}
        </FramePanel>
      </Frame>
      </section>

      {/* 摄取配置原来夹在概览和告警流中间：它是装机时配一次的东西，天天用的是
          上面那条流。沉到告警流下面，折叠态只露状态药丸。 */}
      <section aria-label={t('secIngest')}>
        <IngestConfigBlock />
      </section>

      {selected && (
        <AlertDetailSheet
          alert={selected}
          onClose={() => setSelected(null)}
          onInvestigate={(doc, index) => {
            setInvestigate({ doc, index, alertId: selected.alert_id })
            setSelected(null)
          }}
          onSendToTriage={(doc, note) => {
            setHandoff('triage', { alerts: [doc], sourceNote: note })
            void navigate({ to: '/triage' })
          }}
        />
      )}

      <InvestigationDialog
        open={!!investigate}
        onOpenChange={(v) => !v && setInvestigate(null)}
        alert={investigate?.doc ?? null}
        index={investigate?.index ?? DEFAULT_ALERT_INDEX}
        windowMinutes={30}
        /* Own the disposition so a mark inside the dialog lands on THIS alert
         * and the row behind it updates. Left to the dialog it went to a
         * separate `inv:` key in the triage namespace, which this list never
         * reads — the alert stayed 未处置 after being marked 已处置. */
        dispo={investigate ? dispo[investigate.alertId] ?? 'open' : null}
        onDispoChange={(s) => { if (investigate) void markDispo([investigate.alertId], s) }}
      />
    </div>
  )
}

function FilterBar({
  severity,
  onSeverity,
  ruleInput,
  onRuleInput,
  timeRange,
  onTimeRange,
  views,
  viewName,
  onViewName,
  onSaveView,
  onApplyView,
  onDeleteView,
}: {
  severity: string
  onSeverity: (v: string) => void
  ruleInput: string
  onRuleInput: (v: string) => void
  timeRange: string
  onTimeRange: (v: string) => void
  views: SavedView[]
  viewName: string
  onViewName: (v: string) => void
  onSaveView: () => void
  onApplyView: (v: SavedView) => void
  onDeleteView: (name: string) => void
}) {
  const t = useT(alertsCopy)
  /* One wrapping row, not two stacked ones. Saved views are a filter control
   * like severity or time range, so they read as a stray footer when parked on
   * their own line. flex-wrap keeps a narrow viewport working — the row breaks
   * where it must instead of being split by hand. */
  return (
    <div className="flex flex-wrap items-center gap-x-2 gap-y-2">
      <span className="flex items-center gap-2 text-13 text-fg-muted">
        {t('filterSeverity')}
        <Select value={severity} onValueChange={(v) => onSeverity(v ?? '')}>
          <SelectTrigger aria-label={t('filterSeverity')} className="text-13">
            <SelectValue>
              {(v: string | null) =>
                v ? t('sevWithCode', { name: severityLabel(v), code: v }) : t('filterAll')
              }
            </SelectValue>
          </SelectTrigger>
          <SelectContent>
            <SelectItem value="">{t('filterAll')}</SelectItem>
            {SEVERITIES.map((s) => (
              <SelectItem key={s} value={s}>
                {t('sevWithCode', { name: severityLabel(s), code: s })}
              </SelectItem>
            ))}
          </SelectContent>
        </Select>
      </span>

      {/* 规则搜索照 Run Queue 的搜索框：带放大镜、有内容时出清除钮。 */}
      <InputGroup className="h-8 w-[200px]">
        <InputGroupAddon align="inline-start">
          <HugeiconsIcon icon={Search01Icon} strokeWidth={2} className="size-4 text-muted-foreground" aria-hidden="true" />
        </InputGroupAddon>
        <InputGroupInput
          value={ruleInput}
          onChange={(e) => onRuleInput(e.target.value)}
          placeholder={t('rulePlaceholder')}
          aria-label={t('rulePlaceholder')}
          className="text-13"
        />
        {ruleInput.length > 0 && (
          <InputGroupAddon align="inline-end">
            <InputGroupButton size="icon-xs" aria-label="clear" onClick={() => onRuleInput('')}>
              <HugeiconsIcon icon={Cancel01Icon} strokeWidth={2} className="size-3.5" aria-hidden="true" />
            </InputGroupButton>
          </InputGroupAddon>
        )}
      </InputGroup>

      {/* 预设 + 精确到分钟的自定义区间。事后复盘常常是「昨晚 21:47 到 22:15
          发生了什么」，只有近 N 小时这种档位是够不着的。 */}
      <TimeRangePicker
        value={parseRange(timeRange)}
        onChange={(v) => onTimeRange(serializeRange(v))}
        presets={ALERT_PRESETS}
        className="h-8"
      />

      {/* Saved views, inline with the filters they capture. */}
      <span className="inline-flex items-center gap-1 pl-1 text-12 text-muted-foreground">
        <HugeiconsIcon icon={Bookmark01Icon} strokeWidth={2} className="size-3.5" /> {t('views')}
      </span>
      {views.map((v) => (
        <span key={v.name} className="pill pill-gray inline-flex items-center gap-1">
          <button type="button" onClick={() => onApplyView(v)} className="cursor-pointer">
            {v.name}
          </button>
          <button
            type="button"
            onClick={() => onDeleteView(v.name)}
            aria-label={t('deleteView', { name: v.name })}
            className="cursor-pointer text-muted-foreground hover:text-foreground"
          >
            <HugeiconsIcon icon={Cancel01Icon} strokeWidth={2} className="size-3" />
          </button>
        </span>
      ))}
      <Input
        value={viewName}
        onChange={(e) => onViewName(e.target.value)}
        onKeyDown={(e) => e.key === 'Enter' && onSaveView()}
        placeholder={t('viewNamePlaceholder')}
        className="h-8 w-[110px] text-13"
      />
      <Button variant="outline" size="sm" onClick={onSaveView} disabled={!viewName.trim()}>
        {t('saveView')}
      </Button>

    </div>
  )
}

function ConnectionPill({ connected }: { connected: boolean }) {
  const t = useT(alertsCopy)
  return (
    <Pill tone={connected ? 'sev-info' : 'sev-medium'} title={connected ? t('sseConnected') : t('sseDisconnected')}>
      <HugeiconsIcon
        icon={connected ? RadioIcon : WifiDisconnected01Icon}
        strokeWidth={2}
        className="size-3.5"
      />
      {connected ? t('liveShort') : t('reconnecting')}
    </Pill>
  )
}

// memo: rows keep a stable `alert` ref across SSE prepends, so only new rows
// render. Group heads reuse the same visuals plus a ×N badge + expand chevron.
const AlertRow = memo(function AlertRow({
  alert,
  onClick,
  count,
  expanded,
  onToggle,
  child,
  status = 'open',
  onStatus,
  checked,
  onCheck,
}: {
  alert: RealtimeAlert
  onClick: () => void
  count?: number
  expanded?: boolean
  onToggle?: () => void
  child?: boolean
  status?: TriageStatus
  onStatus?: (s: TriageStatus) => void
  checked?: boolean
  onCheck?: () => void
}) {
  const sev = alert.severity in SEV_TONE ? alert.severity : 'info'
  const isGroup = count !== undefined
  return (
    <div
      role="button"
      tabIndex={0}
      onClick={onClick}
      onKeyDown={(e) => (e.key === 'Enter' || e.key === ' ') && (e.preventDefault(), onClick())}
      className={cn(
        'flex cursor-pointer flex-wrap items-center gap-x-3 gap-y-1 rounded-lg px-3 py-2 [box-shadow:var(--shadow-ring-light)] transition-shadow hover:[box-shadow:var(--shadow-ring)] focus-visible:outline-none focus-visible:[box-shadow:var(--shadow-focus)]',
        child && 'ml-6 bg-accent',
        status !== 'open' && 'opacity-60',
      )}
    >
      {onCheck && (
        <Checkbox
          checked={!!checked}
          onClick={(e) => e.stopPropagation()}
          onCheckedChange={onCheck}
          aria-label={translate(alertsCopy, 'selectAlert')}
          className={cn(
            'shrink-0 cursor-pointer',
            // keep the develop-blue accent the native control had; `primary`
            // forwards to --t-fg, which reads as a plain black tick here.
            'data-checked:border-info data-checked:bg-info',
          )}
        />
      )}
      {isGroup && (
        <button
          type="button"
          onClick={(e) => {
            e.stopPropagation()
            onToggle?.()
          }}
          aria-label={translate(alertsCopy, expanded ? 'collapseGroup' : 'expandGroup')}
          className="-ml-1 shrink-0 cursor-pointer rounded p-0.5 hover:bg-accent"
        >
          <HugeiconsIcon icon={ChevronRightIcon} strokeWidth={2}
            className={cn('size-4 text-muted-foreground transition-transform', expanded && 'rotate-90')}
          />
        </button>
      )}
      <Pill tone={SEV_TONE[sev]}>{severityLabel(sev)}</Pill>
      <span className="shrink-0 text-14 font-medium text-foreground">{alert.rule_name}</span>
      {alert.summary ? (
        <span className="min-w-0 flex-1 truncate text-12 text-muted-foreground" title={alert.summary}>
          {alert.summary}
        </span>
      ) : alert.subject_field ? (
        <code className="min-w-0 flex-1 truncate font-mono text-12 text-fg-muted">
          {alert.subject_field}={alert.subject_value}
        </code>
      ) : null}
      <span className="ml-auto flex shrink-0 items-center gap-2">
        {isGroup && <Pill tone="gray">×{count}</Pill>}
        {onStatus && <RowDispo status={status} onStatus={onStatus} />}
        <Pill tone="gray">{originLabel(alert.origin)}</Pill>
        <span className="font-mono text-11 text-muted-foreground">{formatTs(alert['@timestamp'])}</span>
      </span>
    </div>
  )
})

/* Per-row disposition. A native <select> rather than the four pills the triage
 * cards use: a row is one dense line in a virtualised list, and four buttons
 * per row would dominate it. Marking 已处置 / 误报 drops the row out of the
 * default view; the alert itself is never deleted. */
function RowDispo({ status, onStatus }: { status: TriageStatus; onStatus: (s: TriageStatus) => void }) {
  /* 原来是原生 <select>：一行里挤着一个系统样式的下拉，和页面上其它下拉（严重度、
     时间窗）不是一套皮。换成同一个 Select 原语；点它不能连带把整行的详情面板
     打开，所以按下和点击都要拦住冒泡。 */
  /* 处置状态是团队共享的（后端 SHARED_KINDS），只读账号改不了 —— 后端现在会 403。
     和 GatedButton 一样用 aria-disabled 而不是 disabled：还能 Tab 到、能读到原因。 */
  const gate = useGate('write')
  return (
    <div onClick={(e) => e.stopPropagation()} onPointerDown={(e) => e.stopPropagation()}>
      <Select
        value={status}
        onValueChange={(v) => { if (gate.allowed) onStatus((v ?? status) as TriageStatus) }}
      >
        <SelectTrigger
          size="sm"
          className={cn('h-6! w-24 px-1.5 text-11', !gate.allowed && 'opacity-60 cursor-not-allowed')}
          aria-label={translate(alertsCopy, 'dispoAria')}
          aria-disabled={!gate.allowed || undefined}
          title={gate.allowed ? undefined : gate.reason}
          onPointerDown={(e) => { if (!gate.allowed) e.preventDefault() }}
          onKeyDown={(e) => { if (!gate.allowed && e.key !== 'Tab') e.preventDefault() }}
        >
          <SelectValue>{(v) => statusLabel(String(v) as TriageStatus)}</SelectValue>
        </SelectTrigger>
        <SelectContent>
          {STATUS_ORDER.map((s) => (
            <SelectItem key={s} value={s}>{statusLabel(s)}</SelectItem>
          ))}
        </SelectContent>
      </Select>
    </div>
  )
}

/* ---------------- 摄取配置（源A 轮询 + 源B webhook） ---------------- */

function IngestConfigBlock() {
  const t = useT(alertsCopy)
  const c = useT(commonCopy)
  const isAdmin = useIsAdmin()
  const [open, setOpen] = useState(false)
  const [status, setStatus] = useState<AlertIngestStatus | null>(null)
  const [loading, setLoading] = useState(true)
  const [saving, setSaving] = useState(false)
  const [saved, setSaved] = useState(false)
  const [err, setErr] = useState<string | null>(null)

  // Sentinel-aware secret: `secretMasked` is the '<set · N chars>' marker (or ''
  // when unset). We only send the secret key on save if the user typed a new
  // value or ticked 清除. Mirrors SettingsPage exactly.
  const [index, setIndex] = useState('')
  const [interval, setInterval] = useState('')
  const [secretMasked, setSecretMasked] = useState('')
  const [secret, setSecret] = useState('')
  const [clearSecret, setClearSecret] = useState(false)
  const [origIndex, setOrigIndex] = useState('')
  const [origInterval, setOrigInterval] = useState('')

  async function load() {
    setLoading(true)
    setErr(null)
    try {
      // GET /api/settings 要管理员。非管理员照发只会拿一个 403，然后在已经写着
      // "这项操作需要管理员权限"的 GateNotice 旁边再叠一条"读取失败"——把一句
      // 说清楚的话变成两句互相矛盾的话。状态那条不要管理员，照拉。
      const [s, st] = await Promise.all([
        isAdmin
          ? api.getSettings().then((r) => r.settings)
          : Promise.resolve({} as Record<string, string>),
        api.alertIngestStatus(),
      ])
      const idx = s['alerts.ingest_index'] ?? ''
      const iv = s['alerts.ingest_interval'] ?? ''
      setIndex(idx)
      setOrigIndex(idx)
      setInterval(iv)
      setOrigInterval(iv)
      setSecretMasked(s['alerts.webhook_secret'] ?? '')
      setStatus(st)
    } catch (e) {
      setErr((e as ApiError).message || t('errLoadIngest'))
    } finally {
      setLoading(false)
    }
  }

  useEffect(() => {
    void load()
  }, [])

  const secretSet = secretMasked.startsWith(SENTINEL_PREFIX)

  async function save() {
    setErr(null)
    setSaving(true)
    try {
      const diff: Record<string, string> = {}
      if (index !== origIndex) diff['alerts.ingest_index'] = index.trim()
      if (interval !== origInterval) diff['alerts.ingest_interval'] = interval.trim()
      if (clearSecret) diff['alerts.webhook_secret'] = ''
      else if (secret.trim()) diff['alerts.webhook_secret'] = secret.trim()
      if (Object.keys(diff).length > 0) await api.saveSettings(diff)
      setSecret('')
      setClearSecret(false)
      await load()
      setSaved(true)
      setTimeout(() => setSaved(false), 1800)
    } catch (e) {
      setErr((e as ApiError).message || t('errSave'))
    } finally {
      setSaving(false)
    }
  }

  return (
    <Frame dense spacing="sm" className="flex w-full min-w-0 flex-col [--frame-panel-header-py-adjust:2px]">
      <Collapsible open={open} onOpenChange={setOpen}>
        <FrameHeader>
          <CollapsibleTrigger className="flex w-full items-center justify-between gap-3 text-left">
            <div className="flex flex-wrap items-center gap-2">
              <FrameTitle>{t('ingestTitle')}</FrameTitle>
              {status && <StatusPills status={status} />}
            </div>
            <HugeiconsIcon icon={ChevronDownIcon} strokeWidth={2} className={cn('size-4 shrink-0 text-muted-foreground transition-transform', open && 'rotate-180')} />
          </CollapsibleTrigger>
        </FrameHeader>
        <CollapsibleContent>
          <FramePanel className="flex flex-col gap-5 bg-card shadow-none!">
            <GateNotice gate="admin" />
            {err && <BlockError message={err} />}

            {/* 轮询拉取：网关按间隔尾随告警索引，准实时 */}
            <div className="space-y-1">
              <p className="text-12 font-medium text-fg-muted">{t('pollTitle')}</p>
              <p className="text-11 text-muted-foreground">{t('pollDesc')}</p>
            </div>
            <label className="block space-y-1.5">
              <Label className="font-mono text-xs text-muted-foreground">{t('fieldAlertIndex')}</Label>
              <Input
                value={index}
                onChange={(e) => setIndex(e.target.value)}
                placeholder=".alerts-security.alerts-default"
                disabled={loading}
                className="font-mono text-12"
              />
            </label>

            <label className="block space-y-1.5">
              <Label className="font-mono text-xs text-muted-foreground">{t('fieldPollInterval')}</Label>
              <Input
                type="number"
                min={1}
                value={interval}
                onChange={(e) => setInterval(e.target.value)}
                placeholder="10"
                disabled={loading}
                className="font-mono text-12"
              />
            </label>

            {/* Webhook 推送：Kibana 规则触发即回调，零延迟 */}
            <div className="space-y-1 pt-1">
              <p className="text-12 font-medium text-fg-muted">{t('webhookTitle')}</p>
              <p className="text-11 text-muted-foreground">{t('webhookDesc')}</p>
            </div>
            <label className="block space-y-1.5">
              <Label className="font-mono text-xs text-muted-foreground">{t('fieldSecret')}</Label>
              <Input
                type="password"
                autoComplete="new-password"
                value={secret}
                onChange={(e) => setSecret(e.target.value)}
                disabled={loading || clearSecret}
                placeholder={secretSet ? t('secretSetPlaceholder') : t('secretUnsetPlaceholder')}
                className="font-mono text-12"
              />
              {secretSet && (
                <Label className="cursor-pointer text-xs font-normal text-muted-foreground">
                  <Checkbox
                    checked={clearSecret}
                    onCheckedChange={(v) => { setClearSecret(!!v); setSecret('') }}
                  />
                  {t('clearSecret')}
                </Label>
              )}
            </label>

            <div className="flex items-center justify-end gap-3">
              {status?.cursor_ts && (
                <span className="mr-auto font-mono text-11 text-muted-foreground">
                  {t('cursor', { ts: status.cursor_ts })}
                </span>
              )}
              <GatedButton gate="admin" variant="default" className="rounded-full" size="sm" onClick={save} disabled={saving || loading}>
                {saving ? <HugeiconsIcon icon={Loading03Icon} strokeWidth={2} className="size-3.5 animate-spin" /> : saved ? <HugeiconsIcon icon={CheckIcon} strokeWidth={2} className="size-3.5" /> : null}
                {saving ? `${c('saving')}…` : saved ? c('saved') : c('save')}
              </GatedButton>
            </div>
          </FramePanel>
        </CollapsibleContent>
      </Collapsible>
    </Frame>
  )
}

function StatusPills({ status }: { status: AlertIngestStatus }) {
  const t = useT(alertsCopy)
  return (
    <span className="flex flex-wrap items-center gap-1.5">
      <Pill tone={status.enabled ? 'blue' : 'gray'}>
        {t('pillPoll')} {status.enabled ? t('pillEnabled') : t('pillNotConfigured')}
      </Pill>
      {status.enabled && !status.whitelisted && (
        <span className="inline-flex items-center gap-1 rounded-full bg-warning-subtle px-2 py-0.5 text-11 font-medium text-warning">
          <HugeiconsIcon icon={ShieldAlertIcon} strokeWidth={2} className="size-3" />
          {t('pillNotWhitelisted')}
        </span>
      )}
      <Pill tone={status.webhook_enabled ? 'blue' : 'gray'}>
        {t('pillWebhook')} {status.webhook_enabled ? t('pillWebhookOn') : t('pillWebhookOff')}
      </Pill>
      {/* 一批告警突然没摘要时，这里是唯一能看出「是撞上了预算，不是坏了」的地方。 */}
      {(status.summary_skipped_recent ?? 0) > 0 && (
        <span
          className="inline-flex items-center gap-1 rounded-full bg-warning-subtle px-2 py-0.5 text-11 font-medium text-warning"
          title={t('pillSummarySkippedHint', { budget: String(status.summary_budget_s ?? 20) })}
        >
          <HugeiconsIcon icon={ShieldAlertIcon} strokeWidth={2} className="size-3" />
          {t('pillSummarySkipped', { n: String(status.summary_skipped_recent) })}
        </span>
      )}
    </span>
  )
}

/* ---------------- 告警详情 ---------------- */

/*
 * 侧边抽屉，不是居中弹窗 —— roster 的 `features/approvals/ticket-sheet` 就是
 * 这个形态：告警是一条一条过的，抽屉留着后面那条流的上下文，弹窗把它整个盖掉。
 */
function AlertDetailSheet({
  alert,
  onClose,
  onInvestigate,
  onSendToTriage,
}: {
  alert: RealtimeAlert
  onClose: () => void
  onInvestigate: (doc: Record<string, unknown>, index: string) => void
  onSendToTriage: (doc: Record<string, unknown>, note: string) => void
}) {
  const t = useT(alertsCopy)
  const c = useT(commonCopy)
  const [detail, setDetail] = useState<AlertDetail>(() => alert)
  const [link, setLink] = useState<AlertKibanaLink | null>(null)
  const [enrichment, setEnrichment] = useState<AssetContext | null>(null)
  const [enrichLoaded, setEnrichLoaded] = useState(false)
  const [showRaw, setShowRaw] = useState(false)
  const [copied, setCopied] = useState(false)

  useEffect(() => {
    let alive = true
    api.alertDetail(alert.alert_id).then((d) => alive && setDetail(d)).catch(() => {})
    api.alertKibanaLink(alert.alert_id).then((l) => alive && setLink(l)).catch(() => {})
    api
      .alertEnrichment(alert.alert_id)
      .then((r) => alive && (setEnrichment(r.enrichment), setEnrichLoaded(true)))
      .catch(() => alive && setEnrichLoaded(true))
    return () => {
      alive = false
    }
  }, [alert.alert_id])

  const sev = detail.severity in SEV_TONE ? detail.severity : 'info'
  const sourceIndex = link?.source_index ?? detail.source_index ?? ''
  const sourceId = link?.source_id ?? detail.source_id ?? ''

  /*
   * 这张表的行名原来是 ES 字段名（rule_name / source_index / ingested_at…），
   * 面向的却是看告警的人，不是读文档的人 —— 原始记录有右下角「复制文档 ID」和
   * Discover 两个出口。改成中文；主体那一行仍带上它的真实字段名，因为「哪个字段
   * 是主体」本身就是信息。
   *
   * 「AI 摘要」在没有摘要时会退化成规则名（后端拿 rule_name 兜底），一行字重复
   * 上面的标题 —— 和标题一样就不显示了。
   */
  const summary = detail.summary && detail.summary !== detail.rule_name ? detail.summary : null
  /* 摘要那一行有三种「空」：关掉了、生成失败、撞上了预算。只有最后一种是产品自己
     的决定，得说出来 —— 否则运维只能看到一行空白。 */
  const summaryValue = summary ?? (detail.summary_skipped ? t('rowSummarySkipped') : null)
  /* `isTime` 而不是拿标签去比字符串：标签会随语言变，比中文原文的写法在英文界面
     下就不成立了。 */
  const rows: Array<{ label: string; value: string | null | undefined; isTime?: boolean }> = [
    { label: t('rowSummary'), value: summaryValue },
    { label: t('rowRule'), value: detail.rule_name },
    { label: t('rowRuleId'), value: detail.rule_id },
    {
      label: detail.subject_field
        ? t('rowSubjectField', { field: detail.subject_field })
        : t('rowSubject'),
      value: detail.subject_field ? detail.subject_value : null,
    },
    { label: t('rowTime'), value: detail['@timestamp'], isTime: true },
    { label: t('rowOrigin'), value: originLabel(detail.origin) },
    { label: t('rowSourceIndex'), value: detail.source_index },
    { label: t('rowSourceId'), value: detail.source_id },
    { label: t('rowIngestedAt'), value: detail.ingested_at, isTime: true },
  ]

  async function copyId() {
    try {
      await navigator.clipboard.writeText(sourceIndex ? `${sourceIndex}/${sourceId}` : sourceId)
      setCopied(true)
      setTimeout(() => setCopied(false), 1500)
    } catch {
      // clipboard blocked (insecure ctx) — nothing to surface
    }
  }

  return (
    <Sheet open onOpenChange={(v) => !v && onClose()}>
      <SheetContent side="right" variant="inset" className="flex flex-col gap-0 p-0">
        <SheetHeader className="flex-row items-start justify-between gap-4 border-b px-6 pt-5 pb-4 pr-14">
          <SheetTitle className="min-w-0 text-base font-semibold">{detail.rule_name || detail.alert_id}</SheetTitle>
          <Pill tone={SEV_TONE[sev]}>{severityLabel(sev)}</Pill>
        </SheetHeader>
        <div className="flex min-h-0 flex-1 flex-col gap-4 overflow-auto px-6 py-5">
          <dl className="grid grid-cols-[minmax(0,140px)_1fr] gap-x-4 gap-y-2">
            {rows.map((r) => (
              <div key={r.label} className="contents">
                <dt className="text-11 text-muted-foreground">{r.label}</dt>
                <dd className="break-all text-13 text-foreground">
                  {r.isTime ? formatTs(r.value ?? undefined) : r.value || '—'}
                </dd>
              </div>
            ))}
          </dl>

          <div className="mt-4 space-y-2">
            <div className="flex items-center gap-2">
              <span className="font-mono text-11 text-muted-foreground">{t('assetContext')}</span>
              {enrichment && (
                <Pill tone="blue">{enrichment.source}</Pill>
              )}
              {enrichment && (
                <Pill tone="gray">{t('confidence', { level: enrichment.confidence })}</Pill>
              )}
              {enrichment && enrichment.candidates > 1 && (
                <Pill tone="gray">{t('candidates', { n: enrichment.candidates })}</Pill>
              )}
            </div>
            {!enrichLoaded ? (
              <p className="text-12 text-muted-foreground">{t('resolving')}</p>
            ) : enrichment ? (
              <dl className="grid grid-cols-[minmax(0,140px)_1fr] gap-x-4 gap-y-1.5 rounded-lg bg-accent p-3 [box-shadow:var(--shadow-ring-light)]">
                {([
                  [t('assetBusinessName'), enrichment.business_name],
                  [t('assetCriticality'), enrichment.criticality],
                  [t('assetCategory'), enrichment.category],
                  [t('assetOwner'), enrichment.owner],
                  [t('assetDepartment'), enrichment.department],
                ] as Array<[string, string | null | undefined]>).map(([k, v]) => (
                  <div key={k} className="contents">
                    <dt className="font-mono text-11 text-muted-foreground">{k}</dt>
                    <dd className="break-all text-13 text-foreground">{v || '—'}</dd>
                  </div>
                ))}
                {enrichment.confidence === 'medium' && (
                  <div className="contents">
                    <dt className="font-mono text-11 text-muted-foreground">{t('assetNote')}</dt>
                    <dd className="text-12 text-warning">{t('assetNoteDrift')}</dd>
                  </div>
                )}
              </dl>
            ) : (
              <p className="text-12 text-muted-foreground">{t('noAssetContext')}</p>
            )}
          </div>

          {detail.raw && (
            <Collapsible open={showRaw} onOpenChange={setShowRaw} className="space-y-2">
              <CollapsibleTrigger className="flex items-center gap-1.5 text-12 text-fg-muted hover:text-foreground">
                <HugeiconsIcon icon={ChevronDownIcon} strokeWidth={2} className={cn('size-3.5 transition-transform', showRaw && 'rotate-180')} />
                {t('rawJson')}
              </CollapsibleTrigger>
              <CollapsibleContent
                className="max-h-[320px] overflow-auto rounded-lg bg-accent p-3 font-mono text-11 leading-[1.5] text-foreground [box-shadow:var(--shadow-ring-light)]"
                render={<pre />}
              >
                {JSON.stringify(detail.raw, null, 2)}
              </CollapsibleContent>
            </Collapsible>
          )}
        </div>
        {/* Why Discover is unavailable, on its own full-width row. The backend
            already explains it (usually "create a Kibana data view titled
            '<index>'"), but that string only ever reached `title` on the
            disabled button — which suppresses pointer events, so the tooltip
            never fired and the operator saw a dead grey control with no path
            forward. It gets a row of its own because a sentence dropped into
            the button row squeezes the buttons into unreadable columns. */}
        {!link?.discover_url && link?.discover_error && (
          <div className="px-6 pt-3 text-12 leading-[1.5] text-muted-foreground">
            <span className="font-medium text-fg-muted">{t('discoverUnavailable')}</span>
            {link.discover_error}
          </div>
        )}
        {/* 链接生成了，但主机名是内部的 —— 点开大概率连不上，而原因（访问网关用的
            地址不在 RST_CORS_ORIGINS 里）只写在网关日志里的话，运维只会看到一条
            打不开的链接。 */}
        {link?.origin_ignored && (
          <div className="px-6 pt-3 text-12 leading-[1.5] text-warning">
            {t('discoverOriginIgnored')}
          </div>
        )}
        <SheetFooter className="flex-row flex-wrap items-center gap-2">
          {/* left: primary next-step actions — investigate / send to triage. Real
              alerts are the natural investigation input, so these lead. */}
          <div className="mr-auto flex min-w-0 items-center gap-2">
            <Button
              variant="default" className="rounded-full"
              size="sm"
              onClick={() => onInvestigate(alertToDoc(detail), sourceIndex || DEFAULT_ALERT_INDEX)}
              title={t('investigateTitle')}
            >
              <HugeiconsIcon icon={SparklesIcon} strokeWidth={2} className="size-3.5" /> {t('investigate')}
            </Button>
            <Button
              variant="outline" className="rounded-full"
              size="sm"
              onClick={() =>
                onSendToTriage(
                  alertToDoc(detail),
                  t('triageSourceNote', { name: detail.rule_name || detail.alert_id }),
                )
              }
              title={t('sendToTriageTitle')}
            >
              <HugeiconsIcon icon={ListChecksIcon} strokeWidth={2} className="size-3.5" /> {t('sendToTriage')}
            </Button>
          </div>
          {/* right: Kibana pivots + copy */}
          {/* The reason Discover is unavailable is rendered as its own row
              ABOVE this one (see the block before DialogFooter) — prose in a
              button row has no width to spare and crushes its siblings. The
              titled wrapper keeps hover working: `title` on the disabled button
              itself never fires, because a disabled button eats pointer events. */}
          <span title={link?.discover_error ?? undefined} className="inline-flex">
            <Button
              variant="outline"
              size="sm"
              onClick={() => link?.discover_url && window.open(link.discover_url, '_blank', 'noopener,noreferrer')}
              disabled={!link?.discover_url}
            >
              <HugeiconsIcon icon={ExternalLinkIcon} strokeWidth={2} className="size-3.5" /> Discover
            </Button>
          </span>
          <Button
            variant="outline"
            size="sm"
            onClick={() => link && window.open(link.security_url, '_blank', 'noopener,noreferrer')}
            disabled={!link}
          >
            <HugeiconsIcon icon={ShieldAlertIcon} strokeWidth={2} className="size-3.5" /> Security
          </Button>
          <Button variant="outline" className="rounded-full" size="sm" onClick={copyId} disabled={!sourceId}>
            {copied ? <HugeiconsIcon icon={CheckIcon} strokeWidth={2} className="size-3.5" /> : <HugeiconsIcon icon={CopyIcon} strokeWidth={2} className="size-3.5" />}
            {copied ? c('copied') : t('copyDocId')}
          </Button>
        </SheetFooter>
      </SheetContent>
    </Sheet>
  )
}

