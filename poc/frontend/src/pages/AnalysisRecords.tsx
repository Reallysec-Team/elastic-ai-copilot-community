import { useCallback, useEffect, useRef, useState } from 'react'
import { useNavigate } from '@tanstack/react-router'
import { HugeiconsIcon } from '@hugeicons/react'
import { AlertCircleIcon, ListChecksIcon, Loading03Icon, ScrollTextIcon, Search01Icon, SearchVisualIcon, SparklesIcon } from '@hugeicons/core-free-icons'
import { api, type AnalysisSummary, type AnalysisRecord, type InvestigateResponse } from '@/lib/api'
import { Alert, AlertDescription } from '@/components/reui/alert'
import { Badge } from '@/components/reui/badge'
import {
  Timeline, TimelineContent, TimelineHeader, TimelineIndicator, TimelineItem, TimelineSeparator,
} from '@/components/reui/timeline'
import { cn } from '@/lib/utils'
import { Frame, FramePanel } from '@/components/reui/frame'
import { Button } from '@/components/ui/button'
import { Empty, EmptyDescription, EmptyHeader, EmptyMedia, EmptyTitle } from '@/components/ui/empty'
import { InputGroup, InputGroupAddon, InputGroupInput } from '@/components/ui/input-group'
import { PageHeader } from '@/components/shell/page-header'
import {
  Sheet, SheetContent, SheetFooter, SheetHeader, SheetTitle,
} from '@/components/ui/sheet'
import { Tabs, TabsList, TabsTrigger } from '@/components/ui/tabs'
import { InvestigationContent } from '@/components/InvestigationDialog'
import { relativeTime, setPending } from '@/lib/history'
import { followUpQuestion, recordTitle } from '@/lib/analysisFollowUp'
import { SeverityBadge } from '@/components/severity-badge'
import { useT } from '@/lib/i18n'
import { analysisCopy, type AnalysisKey } from '@/locales/analysis'
import { commonCopy } from '@/locales/common'

/* 三种 kind 全在这儿 —— `result_explain`（查询结果解读）原来漏了一档，界面上那类
   记录的标签直接显示成原始字符串。 */
const KIND_KEY: Record<string, AnalysisKey> = {
  investigation: 'kindInvestigation', triage: 'kindTriage', result_explain: 'kindResultExplain',
}

/*
 * 顶部分类按 kind 切：它是「这条记录怎么来的」，互斥、稳定、后端本来就支持。
 * 不按严重度切 —— 严重度是个过滤器，同一条记录重跑一次就可能换一档。
 * `all` 是本地哨兵，发请求时抹成不带 kind 参数。
 */
const ALL = 'all'
const KIND_TABS: Array<{ id: string; label: AnalysisKey }> = [
  { id: ALL, label: 'kindAll' },
  { id: 'investigation', label: 'kindInvestigation' },
  { id: 'triage', label: 'kindTriage' },
  { id: 'result_explain', label: 'kindResultExplain' },
]

const PAGE = 30

/* 三个分支（错误 / 空 / 列表）都要顶着同一个标题，所以标题在外层这一层。
   这页原来根本没有 PageHeader —— 它一直没被路由指向过，面包屑给它兜的是原始
   path 段，屏幕上写着 "analysis"。 */
function Shell({ children }: { children: React.ReactNode }) {
  return (
    <div className="@container flex w-full flex-col gap-5">
      {children}
    </div>
  )
}


export function AnalysisRecords() {
  const t = useT(analysisCopy)
  const c = useT(commonCopy)
  const [items, setItems] = useState<AnalysisSummary[]>([])
  const [total, setTotal] = useState(0)
  const [loading, setLoading] = useState(false)
  const [loadingMore, setLoadingMore] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const [openId, setOpenId] = useState<string | null>(null)
  const [kind, setKind] = useState(ALL)
  /* 输入框里的字和真正发出去的关键词分开，中间隔一层 300ms 防抖：每个字符打一次
     ES 查询没必要，而只在前端过滤已加载的那一页，正好解决不了「记录太多翻不到」。 */
  const [term, setTerm] = useState('')
  const [q, setQ] = useState('')

  useEffect(() => {
    const t = setTimeout(() => setQ(term.trim()), 300)
    return () => clearTimeout(t)
  }, [term])

  /* 代次守卫，load 和 loadMore 共用一个计数：
     - 连打关键词（"ad"→"admin"）时两次搜索同时在飞，先发的慢请求后回来会把列表
       盖回旧关键词的结果，和输入框对不上；
     - 翻页在飞时改 kind / q，回来的那一页会被 append 到新筛选的列表尾部。
     只认最后一次发出的请求。 */
  const reqRef = useRef(0)

  const load = useCallback(async () => {
    const reqId = ++reqRef.current
    setLoading(true)
    setError(null)
    try {
      const r = await api.analysisList({
        limit: PAGE,
        kind: kind === ALL ? undefined : kind,
        q: q || undefined,
      })
      if (reqId !== reqRef.current) return
      setItems(r.records)
      setTotal(r.total)
    } catch (e) {
      if (reqId !== reqRef.current) return
      setError(e instanceof Error ? e.message : String(e))
    } finally {
      setLoading(false)
    }
  }, [kind, q])

  useEffect(() => {
    // eslint-disable-next-line react-hooks/set-state-in-effect -- initial load
    load()
  }, [load])

  /* 游标翻页：`before` 传最后一条的 created_at，后端是 `lt`。用 offset 会在新记录
     进来时把同一条推到下一页里重复出现。 */
  const loadMore = async () => {
    const last = items[items.length - 1]
    if (!last) return
    const reqId = ++reqRef.current
    setLoadingMore(true)
    try {
      const r = await api.analysisList({
        limit: PAGE,
        kind: kind === ALL ? undefined : kind,
        q: q || undefined,
        before: last.created_at,
      })
      if (reqId !== reqRef.current) return
      setItems((prev) => [...prev, ...r.records])
      setTotal(r.total)
    } catch (e) {
      if (reqId !== reqRef.current) return
      setError(e instanceof Error ? e.message : String(e))
    } finally {
      setLoadingMore(false)
    }
  }

  const filtered = kind !== ALL || q !== ''

  return (
    <Shell>
      <PageHeader title={t('title')} />

      {/* 工具条永远在，空态和错误态也在 —— 筛掉了所有记录之后，还得有地方把筛选
          清回去。 */}
      <section aria-label={t('secFilter')} className="flex flex-wrap items-center gap-3">
        <Tabs value={kind} onValueChange={setKind}>
          <TabsList>
            {KIND_TABS.map((tab) => (
              <TabsTrigger key={tab.id} value={tab.id}>{t(tab.label)}</TabsTrigger>
            ))}
          </TabsList>
        </Tabs>

        <InputGroup className="w-full sm:w-72">
          <InputGroupAddon align="inline-start">
            <HugeiconsIcon icon={Search01Icon} strokeWidth={2} aria-hidden="true" className="size-4" />
          </InputGroupAddon>
          <InputGroupInput
            type="search"
            placeholder={t('searchPlaceholder')}
            aria-label={t('searchAria')}
            value={term}
            onChange={(e) => setTerm(e.target.value)}
          />
        </InputGroup>

        <span className="font-mono text-xs text-muted-foreground">
          {filtered ? t('countMatched', { n: total }) : t('countTotal', { n: total })}
        </span>
      </section>

      {error && (
        <Alert variant="destructive">
          <HugeiconsIcon icon={AlertCircleIcon} strokeWidth={2} className="size-4" />
          <AlertDescription>{error}</AlertDescription>
        </Alert>
      )}

      {!error && items.length === 0 && !loading && (
        <Empty>
          <EmptyHeader>
            <EmptyMedia variant="icon">
              <HugeiconsIcon icon={ScrollTextIcon} strokeWidth={2} />
            </EmptyMedia>
            <EmptyTitle>{filtered ? t('emptyFilteredTitle') : t('emptyTitle')}</EmptyTitle>
            <EmptyDescription>
              {filtered ? t('emptyFilteredDesc') : t('emptyDesc')}
            </EmptyDescription>
          </EmptyHeader>
        </Empty>
      )}

      {/* 列表照 `@reui/timeline-3`（活动流）：一条竖线，每条记录一个带色的类型图标做
          节点，正文是「标题 + 类型 + 严重度」+ 两行摘要 + 时间/查看。原来是一摞
          可点的 Frame 卡，30 条一屏看不出先后。 */}
      {items.length > 0 && (
        <section aria-label={t('secList')}>
          <Frame dense spacing="sm">
            <FramePanel className="bg-card px-5 py-4 shadow-none!">
              <Timeline defaultValue={items.length}>
                {items.map((r, i) => {
                  const kindIcon = r.kind === 'investigation' ? SearchVisualIcon : r.kind === 'triage' ? ListChecksIcon : SparklesIcon
                  const kindTone = r.kind === 'investigation' ? 'bg-primary' : r.kind === 'triage' ? 'bg-info' : 'bg-warning'
                  return (
                    <TimelineItem
                      key={r.id}
                      step={i + 1}
                      className="group-data-[orientation=vertical]/timeline:ms-10 group-data-[orientation=vertical]/timeline:not-last:pb-5"
                    >
                      <TimelineHeader>
                        <TimelineSeparator className="bg-border! group-data-[orientation=vertical]/timeline:top-2 group-data-[orientation=vertical]/timeline:-left-8 group-data-[orientation=vertical]/timeline:h-[calc(100%-2.25rem)] group-data-[orientation=vertical]/timeline:translate-y-6" />
                        <TimelineIndicator
                          className={cn(
                            'flex size-7 items-center justify-center border-none text-white group-data-[orientation=vertical]/timeline:-left-8 [&_svg]:size-3.5',
                            kindTone,
                          )}
                        >
                          <HugeiconsIcon icon={kindIcon} strokeWidth={2} aria-hidden="true" />
                        </TimelineIndicator>
                      </TimelineHeader>
                      <TimelineContent className="min-w-0 pb-1">
                        <button
                          type="button"
                          onClick={() => setOpenId(r.id)}
                          className="group/rec block w-full min-w-0 cursor-pointer text-left outline-none"
                        >
                          <p className="text-sm leading-5">
                            <span className="font-medium text-foreground group-hover/rec:text-primary group-focus-visible/rec:underline">
                              {recordTitle(r)}
                            </span>{' '}
                            <span className="text-muted-foreground">
                              {KIND_KEY[r.kind] ? t(KIND_KEY[r.kind]) : r.kind}
                            </span>
                          </p>
                          {r.summary && (
                            <p className="mt-1 line-clamp-2 text-xs leading-4 text-muted-foreground">{r.summary}</p>
                          )}
                        </button>
                        <div className="mt-2 flex flex-wrap items-center gap-2">
                          <SeverityBadge severity={r.severity} />
                          <span className="font-mono text-11 text-muted-foreground">{relativeTime(r.created_at * 1000)}</span>
                          <Button size="xs" variant="outline" className="ms-auto" onClick={() => setOpenId(r.id)}>
                            {c('view')}
                          </Button>
                        </div>
                      </TimelineContent>
                    </TimelineItem>
                  )
                })}
              </Timeline>
            </FramePanel>
          </Frame>
        </section>
      )}

      {items.length > 0 && items.length < total && (
        <Button
          variant="outline"
          className="self-center"
          disabled={loadingMore}
          onClick={() => void loadMore()}
        >
          {loadingMore && (
            <HugeiconsIcon icon={Loading03Icon} strokeWidth={2} className="size-4 animate-spin" />
          )}
          {t('loadMore', { n: total - items.length })}
        </Button>
      )}

      <AnalysisDetailSheet
        id={openId}
        open={!!openId}
        onOpenChange={(v) => !v && setOpenId(null)}
      />
    </Shell>
  )
}

function AnalysisDetailSheet({
  id, open, onOpenChange,
}: {
  id: string | null
  open: boolean
  onOpenChange: (v: boolean) => void
}) {
  const t = useT(analysisCopy)
  const c = useT(commonCopy)
  const [rec, setRec] = useState<AnalysisRecord | null>(null)
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState<string | null>(null)

  useEffect(() => {
    if (!open || !id) {
      // eslint-disable-next-line react-hooks/set-state-in-effect -- reset on close
      setRec(null); setError(null)
      return
    }
    let alive = true
    setLoading(true); setError(null)
    api
      .analysisDetail(id)
      .then((r) => alive && setRec(r))
      .catch((e) => alive && setError(e instanceof Error ? e.message : String(e)))
      .finally(() => alive && setLoading(false))
    return () => { alive = false }
  }, [id, open])

  const navigate = useNavigate()
  const followUp = rec ? followUpQuestion(rec) : null

  return (
    <Sheet open={open} onOpenChange={onOpenChange}>
      <SheetContent side="right" variant="inset" className="flex flex-col gap-0 p-0">
        <SheetHeader className="flex-row items-start justify-between gap-4 border-b px-6 pt-5 pb-4 pr-14">
          <div className="flex min-w-0 flex-col gap-1">
            <span className="font-mono text-xs text-muted-foreground">
              {rec?.kind === 'triage' ? t('detailTriage') : t('detailInvestigation')}
            </span>
            <SheetTitle className="text-base font-semibold">
              {rec ? recordTitle(rec) : t('detailFallbackTitle')}
            </SheetTitle>
          </div>
          {rec && <SeverityBadge severity={rec.severity} />}
        </SheetHeader>
        <div className="flex min-h-0 flex-1 flex-col gap-4 overflow-auto px-6 py-5">
          {loading && (
            <div className="flex items-center gap-2 py-8 text-13 text-muted-foreground">
              <HugeiconsIcon icon={Loading03Icon} strokeWidth={2} className="size-3.5 animate-spin" />
              {c('loading')}…
            </div>
          )}
          {error && (
            <Alert variant="destructive">
              <HugeiconsIcon icon={AlertCircleIcon} strokeWidth={2} className="size-4" />
              <AlertDescription>{error}</AlertDescription>
            </Alert>
          )}
          {rec && !loading && rec.kind === 'investigation' && (
            <InvestigationContent data={rec.payload as unknown as InvestigateResponse} />
          )}
          {rec && !loading && rec.kind === 'triage' && (
            <TriageContent payload={rec.payload} />
          )}
        </div>
        <SheetFooter className="flex-row items-center justify-between gap-2">
          {/* 归档记录原来是个死胡同：看完只能关掉。记录里没有指回某条告警的 id
              （payload 就是那次调查／分诊的结果本身），能接回去的是**主体** ——
              host / ip / user。给它一个直接去查这个主体的出口。分诊记录的主体是
              「N clusters」，接不出问题，那种就不显示按钮。 */}
          {followUp ? (
            <Button
              variant="outline"
              size="sm"
              onClick={() => {
                setPending({ question: followUp })
                navigate({ to: '/' })
              }}
            >
              <HugeiconsIcon icon={Search01Icon} strokeWidth={2} className="size-3.5" />
              {t('askAboutSubject')}
            </Button>
          ) : (
            <span />
          )}
          <Button size="sm" onClick={() => onOpenChange(false)}>{c('close')}</Button>
        </SheetFooter>
      </SheetContent>
    </Sheet>
  )
}


function TriageContent({ payload }: { payload: Record<string, unknown> }) {
  const clusters = Array.isArray(payload.clusters) ? payload.clusters : []
  return (
    <div className="flex flex-col gap-3">
      {clusters.map((c, i) => {
        const cl = c as Record<string, unknown>
        const sev = String(cl.severity ?? 'info')
        return (
          <div key={i} className="rounded-xl border border-border px-4 py-3">
            <div className="flex flex-wrap items-center gap-2">
              <span className="font-mono text-xs text-muted-foreground">#{String(cl.priority_rank ?? i + 1)}</span>
              <SeverityBadge severity={sev} />
              {cl.attack_intent ? <Badge size="sm" variant="secondary">{String(cl.attack_intent)}</Badge> : null}
            </div>
            {cl.recommendation ? (
              <p className="mt-2 text-13 leading-[1.55] text-fg-muted">
                {String(cl.recommendation)}
              </p>
            ) : null}
          </div>
        )
      })}
    </div>
  )
}
