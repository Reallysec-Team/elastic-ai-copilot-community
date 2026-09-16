import { useEffect, useRef, useState } from 'react'
import { HugeiconsIcon } from '@hugeicons/react'
import { AlertCircleIcon, CheckIcon, ChevronDownIcon, ChevronRightIcon, CopyIcon, Download01Icon, FileTextIcon, Layers01Icon, Loading03Icon, RefreshCwIcon, ShieldAlertIcon, SparklesIcon, TriangleAlertIcon } from '@hugeicons/core-free-icons'
import { Bar, BarChart, LabelList, XAxis, YAxis } from 'recharts'
import { AdminOnlyView, GatedButton, useIsAdmin } from '@/components/gated-button'
import { api, type ApiError } from '@/lib/api'
import { useT, translate, type Translate } from '@/lib/i18n'
import { severityLabel } from '@/lib/severity'
import { commonCopy } from '@/locales/common'
import { reportsCopy, type ReportsKey } from '@/locales/reports'
import { Alert, AlertDescription } from '@/components/reui/alert'
import { Frame, FrameHeader, FramePanel, FrameTitle } from '@/components/reui/frame'
import { MixDonut, type DonutSlice } from '@/components/blocks/chart-13/components/mix-donut'
import { TrendCard } from '@/components/blocks/chart-18/components/trend-card'
import { StatCards, type StatCard } from '@/components/blocks/dashboard-1/components/stat-cards'
import { PageHeader } from '@/components/shell/page-header'
import {
  resolveRange, TimeRangePicker, type TimeRange,
} from '@/components/shared/time-range-picker'
import { Button } from '@/components/ui/button'
import { Pill } from '@/components/ui/Pill'
import { ChartContainer, type ChartConfig } from '@/components/ui/chart'
import {
  actionAxisMax,
  actionBarData,
  barChartHeight,
  categoryAxis,
  prefersReducedMotion,
  truncTick,
} from '@/components/charts/chartData'
import { cn } from '@/lib/utils'
import { Markdown } from '@/components/markdown'
import { Badge } from '@/components/reui/badge'

/*
 * Reports — on-demand 日 / 周 / 月报 + automated patrol archive. The on-demand
 * path hits /api/reports/generate (audit + provider health + license). The
 * scheduler (RST_REPORT_SCHEDULE) archives reports to ES; the "自动巡检历史"
 * card lists them via /api/reports/history with health + triage summaries.
 */

type Period = 'daily' | 'weekly' | 'monthly'

// Backend contract (report_agg.py `assemble_summary`) — the raw api.ts type still
// describes the old flat audit-only shape, so we override `summary` here rather
// than touching the shared client type.
interface ReportSummary {
  exec: { alerts_total: number; high_critical: number; entities: number; analyzed: number }
  alerts: {
    total: number
    timeline: { ts: string; count: number }[]
    by_origin: { poll: number; webhook: number }
    severity: { severity: string; count: number; pct: number }[]
    top_rules: { rule_name: string; count: number; severity: string }[]
    top_entities: {
      value: string
      field: string
      count: number
      business_name: string | null
      criticality: string | null
      owner: string | null
    }[]
  }
  analysis: { total: number; by_kind: Record<string, number>; high_ratio: number; top_topics: string[] }
  baseline: {
    run_at: string | null
    pass_rate: number | null
    by_verdict: Record<string, number>
    top_fails: { rule_id: string; host: string; severity: string }[]
  }
  audit: {
    total: number
    success_rate: number
    by_action: { action: string; count: number }[]
    top_indexes: { index: string; count: number }[]
    top_users: { user: string; count: number }[]
  }
}

type ReportData = Omit<Awaited<ReturnType<typeof api.reportGenerate>>, 'summary'> & {
  summary: ReportSummary
}
type Provider = {
  id: string
  model: string
  base_url: string
  enabled: boolean
  consec_failures?: number
  last_ok_at?: number | string | null
  last_error?: string | null
}

/** 报告没有「全部时间」这个选项 —— 一份没有区间的运营报告说不出任何事。 */
const REPORT_PRESETS = ['24h', '7d', '30d']

/** 三张卡各自对应的时长，供选择器打开时作为起点。 */
const PERIOD_PRESET: Record<Period, string> = { daily: '24h', weekly: '7d', monthly: '30d' }

const PERIODS: Array<{ key: Period; name: ReportsKey; hint: ReportsKey }> = [
  { key: 'daily', name: 'periodDaily', hint: 'periodDailyHint' },
  { key: 'weekly', name: 'periodWeekly', hint: 'periodWeeklyHint' },
  { key: 'monthly', name: 'periodMonthly', hint: 'periodMonthlyHint' },
]

export function ReportsPage() {
  const t = useT(reportsCopy)
  const c = useT(commonCopy)
  const [period, setPeriod] = useState<Period | null>(null)
  const [data, setData] = useState<ReportData | null>(null)
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const [providers, setProviders] = useState<Provider[] | null>(null)
  // Race token: a slow response from a previously selected period must not
  // overwrite the result of a newer request.
  const reqIdRef = useRef(0)
  /* 自定义区间。三张周期卡是快捷入口，这个是「就要昨晚那两小时」的出口 ——
     事后复盘时后者才是常态。 */
  const [range, setRange] = useState<TimeRange | null>(null)

  async function generate(p: Period, custom?: TimeRange) {
    const myId = ++reqIdRef.current
    setPeriod(p)
    if (custom) setRange(custom)
    setLoading(true)
    setError(null)
    try {
      const [r, ph] = await Promise.all([
        api.reportGenerate(p, custom ? resolveRange(custom) : undefined),
        api.llmProviders().catch(() => ({ providers: [] as Provider[] })),
      ])
      if (myId !== reqIdRef.current) return // stale response — discard
      // ponytail: api.ts's inline reportGenerate() type still describes the old
      // audit-only summary; report_agg.py already returns the tiered shape (Task 6/7).
      // Cast at this one boundary instead of touching the shared client type.
      setData(r as unknown as ReportData)
      setProviders(ph.providers ?? [])
    } catch (e) {
      if (myId !== reqIdRef.current) return
      const err = e as ApiError
      setError(err.message ?? String(e))
    } finally {
      if (myId === reqIdRef.current) setLoading(false)
    }
  }

  return (
    <div className="@container flex w-full flex-col gap-5">
      <PageHeader
        title={t('title')}
      />

      <section aria-label={t('secPeriod')} className="min-w-0">
        <PeriodSelector
          active={period}
          loading={loading}
          range={range}
          onPick={(p) => {
            setRange(null)
            void generate(p)
          }}
          onPickRange={(v) => void generate(period ?? 'daily', v)}
          onRegenerate={() => period && generate(period, range ?? undefined)}
        />
      </section>

      {error && (
        <Alert variant="destructive">
          <HugeiconsIcon icon={AlertCircleIcon} strokeWidth={2} className="size-4" />
          <AlertDescription>
            <div className="flex flex-col items-start gap-2">
              <div>{error}</div>
              <GatedButton gate="admin" variant="outline" size="sm" onClick={() => period && generate(period)}>
                <HugeiconsIcon icon={RefreshCwIcon} strokeWidth={2} className="size-3.5" />
                {c('retry')}
              </GatedButton>
            </div>
          </AlertDescription>
        </Alert>
      )}

      {!period && !loading && !error && (
        <Frame dense spacing="sm" className="flex w-full min-w-0 flex-col [--frame-panel-header-py-adjust:2px]">
          <FramePanel className="flex flex-col items-center gap-4 py-16 text-center bg-card shadow-none!">
            <div className="inline-flex size-12 items-center justify-center rounded-full bg-badge-bg">
              <HugeiconsIcon icon={FileTextIcon} strokeWidth={2} className="size-5 text-info" />
            </div>
            <p className="max-w-[420px] text-14 text-fg-muted">
              {t('emptyPick')}
            </p>
          </FramePanel>
        </Frame>
      )}

      {loading && (
        <Frame dense spacing="sm" className="flex w-full min-w-0 flex-col [--frame-panel-header-py-adjust:2px]">
          <FramePanel className="flex flex-col items-center gap-3 py-16 text-center bg-card shadow-none!">
            <HugeiconsIcon icon={Loading03Icon} strokeWidth={2} className="size-5 animate-spin text-info" />
            <p className="text-14 text-fg-muted">{t('generating')}</p>
          </FramePanel>
        </Frame>
      )}

      {!loading && data && period && <ReportView data={data} providers={providers ?? []} />}

      <section aria-label={t('secPatrol')}>
        <PatrolHistory />
      </section>
    </div>
  )
}

/* ----- Automated patrol history (scheduler archive) ----- */

type PatrolItem = Awaited<ReturnType<typeof api.reportsHistory>>['reports'][number]

/*
 * 归档列表来自 GET /api/reports/history，那条挂着 require_admin。原来的
 * `.catch(() => setItems([]))` 把 403 折成了空列表 —— 于是非管理员看到的是
 * 「暂无巡检报告」，一句不真的话：报告是有的，只是这个账号看不到。
 */
function PatrolHistory() {
  const t = useT(reportsCopy)
  const c = useT(commonCopy)
  const isAdmin = useIsAdmin()
  const [items, setItems] = useState<PatrolItem[] | null>(null)
  const [loading, setLoading] = useState(true)
  const [openKey, setOpenKey] = useState<string | null>(null)

  useEffect(() => {
    if (!isAdmin) return
    let alive = true
    api
      .reportsHistory({ limit: 20 })
      .then((r) => alive && setItems(r.reports))
      .catch(() => alive && setItems([]))
      .finally(() => alive && setLoading(false))
    return () => {
      alive = false
    }
  }, [isAdmin])

  return (
    <Frame dense spacing="sm" className="flex w-full min-w-0 flex-col [--frame-panel-header-py-adjust:2px]">
      <FrameHeader>
        <FrameTitle>{t('patrolTitle')}</FrameTitle>
      </FrameHeader>
      <FramePanel className="py-3 bg-card shadow-none!">
        {!isAdmin ? (
          <AdminOnlyView className="py-8" />
        ) : loading ? (
          <div className="py-4 text-center text-13 text-muted-foreground">{c('loading')}…</div>
        ) : !items || items.length === 0 ? (
          <p className="py-3 text-13 leading-[1.7] text-muted-foreground">
            {t('patrolEmpty')}
          </p>
        ) : (
          <ul className="space-y-1.5">
            {items.map((it) => {
              const id = `${it.period}-${it.boundary_key}`
              const open = openKey === id
              return (
                <li key={id} className="overflow-hidden rounded-lg [box-shadow:var(--shadow-ring-light)]">
                  <button
                    type="button"
                    onClick={() => setOpenKey(open ? null : id)}
                    className="flex w-full flex-wrap items-center gap-x-3 gap-y-1 px-3 py-2 text-left transition-colors hover:bg-accent"
                  >
                    {open ? (
                      <HugeiconsIcon icon={ChevronDownIcon} strokeWidth={2} className="size-3.5 shrink-0 text-muted-foreground" />
                    ) : (
                      <HugeiconsIcon icon={ChevronRightIcon} strokeWidth={2} className="size-3.5 shrink-0 text-muted-foreground" />
                    )}
                    <Pill tone="gray">{it.period}</Pill>
                    <code className="font-mono text-12 text-foreground">{it.boundary_key}</code>
                    <span className="font-mono text-11 text-muted-foreground">{formatTs(it.generated_at)}</span>
                    <span className="ml-auto flex items-center gap-3 font-mono text-11 text-muted-foreground">
                      {it.health && <HealthFlags h={it.health} />}
                      {it.security_triage && <TriageBadge t={it.security_triage} />}
                    </span>
                  </button>
                  {open && (
                    <div className="space-y-2 px-3 pb-3">
                      <div className="max-h-[420px] overflow-auto rounded-lg bg-accent px-4 py-3 [box-shadow:var(--shadow-ring-light)]">
                        {it.markdown ? <Markdown>{it.markdown}</Markdown> : <p className="text-sm text-muted-foreground">{t('noBody')}</p>}
                      </div>
                      <Button variant="outline" className="rounded-full" size="sm" onClick={() => downloadMd(it.markdown ?? '', `patrol-${id}`)}>
                        <HugeiconsIcon icon={Download01Icon} strokeWidth={2} className="size-3.5" />
                        {t('downloadMd')}
                      </Button>
                    </div>
                  )}
                </li>
              )
            })}
          </ul>
        )}
      </FramePanel>
    </Frame>
  )
}

/* 巡检那次的两项健康结论。原来是 `✓ 写` `审计 off` 这种原始关键字——写 ES
   成不成、审计开没开，用徽标 + 中英文案说清。 */
function HealthFlags({ h }: { h: NonNullable<PatrolItem['health']> }) {
  const t = useT(reportsCopy)
  const writeOk = h.es_write === 'ok'
  return (
    <span className="inline-flex items-center gap-1.5" title={t('healthTitle')}>
      <Badge size="xs" variant={writeOk ? 'success-light' : 'destructive-light'}>
        {writeOk ? t('healthWriteOk') : t('healthWriteFail')}
      </Badge>
      <Badge size="xs" variant={h.audit_enabled ? 'secondary' : 'warning-light'}>
        {h.audit_enabled ? t('healthAuditOn') : t('healthAuditOff')}
      </Badge>
    </span>
  )
}

function TriageBadge({ t: triage }: { t: NonNullable<PatrolItem['security_triage']> }) {
  const t = useT(reportsCopy)
  const sc = triage.severity_counts ?? {}
  const high = (sc.high ?? 0) + (sc.critical ?? 0)
  return (
    <span title={t('triageTitle')} className={high > 0 ? 'text-destructive' : ''}>
      {t('triageSummary', { n: triage.total_clusters ?? 0 })}
      {high > 0 ? t('triageHigh', { n: high }) : ''}
    </span>
  )
}

function downloadMd(markdown: string, name: string) {
  const blob = new Blob([markdown], { type: 'text/markdown;charset=utf-8' })
  const url = URL.createObjectURL(blob)
  const a = document.createElement('a')
  a.href = url
  a.download = `${name}.md`
  document.body.appendChild(a)
  a.click()
  document.body.removeChild(a)
  URL.revokeObjectURL(url)
}


function PeriodSelector({
  active,
  loading,
  range,
  onPick,
  onPickRange,
  onRegenerate,
}: {
  active: Period | null
  loading: boolean
  range: TimeRange | null
  onPick: (p: Period) => void
  onPickRange: (v: TimeRange) => void
  onRegenerate: () => void
}) {
  const t = useT(reportsCopy)
  return (
    /* 吸附在顶栏下方。这三张卡是这一页的主控件 —— 报告本身很长，读到一半想换个
       周期时，它们已经滚进那条 60px 的不透明顶栏里被切掉大半。
       `-mx-4.5 px-4.5` 把底色铺到内容列的边缘，否则滚动的内容会从两侧的
       padding 里透出来。 */
    <div className="sticky top-(--header-height) z-10 -mx-4.5 space-y-3 bg-background px-4.5 pt-1 pb-3">
      <div className="grid grid-cols-1 gap-3 sm:grid-cols-3">
        {PERIODS.map((p) => {
          // 选了自定义区间之后，三张卡都不该显示成选中 —— 那份报告不再是「过去
          // 24 小时」的了。
          const isActive = active === p.key && !range
          return (
            <button
              key={p.key}
              type="button"
              disabled={loading}
              onClick={() => onPick(p.key)}
              className={cn(
                'group relative rounded-lg bg-card px-5 py-4 text-left transition-shadow duration-150',
                'disabled:cursor-not-allowed disabled:opacity-60',
                isActive
                  ? '[box-shadow:0_0_0_2px_var(--color-develop),0_8px_24px_-12px_rgba(10,114,239,0.25)]'
                  : '[box-shadow:var(--shadow-ring-light)] hover:[box-shadow:var(--shadow-ring)]',
              )}
            >
              <div className="flex items-baseline justify-between">
                <span className={cn('label-mono', isActive && 'text-info')}>
                  {p.key.toUpperCase()}
                </span>
                {isActive && (
                  <span className="inline-flex items-center gap-1 text-11 text-info">
                    <span className="block size-1.5 rounded-full bg-info" aria-hidden="true" />
                    {t('selected')}
                  </span>
                )}
              </div>
              <div className="mt-2 text-base font-semibold text-foreground">{t(p.name)}</div>
              <div className="mt-0.5 text-12 text-muted-foreground">{t(p.hint)}</div>
            </button>
          )
        })}
      </div>
      <div className="flex flex-wrap items-center justify-end gap-2">
        {/* 与实时告警、调用审计同一个组件。三张卡是快捷入口；事后复盘要的是
            「昨晚 21:47 到 22:15」，那由它给。 */}
        <TimeRangePicker
          value={range ?? { kind: 'preset', preset: PERIOD_PRESET[active ?? 'daily'] }}
          onChange={onPickRange}
          presets={REPORT_PRESETS}
          allowAll={false}
          className="h-8"
        />
        {active && (
          <Button variant="outline" className="rounded-full" size="sm" onClick={onRegenerate} disabled={loading}>
            <HugeiconsIcon icon={RefreshCwIcon} strokeWidth={2} className={cn('size-3.5', loading && 'animate-spin')} />
            {t('regenerate')}
          </Button>
        )}
      </div>
    </div>
  )
}

/* ----- Report view ----- */

function ReportView({ data, providers }: { data: ReportData; providers: Provider[] }) {
  const t = useT(reportsCopy)
  const s = data.summary
  // Degrade instead of crashing when the response predates the tiered summary
  // shape (e.g. a stale gateway still running the old audit-only reports.py, or
  // an archived old-format report). exec is the first tiered-only key.
  if (!s?.exec) {
    return (
      <div className="flex min-w-0 flex-col gap-5">
        <Frame dense spacing="sm" className="flex w-full min-w-0 flex-col [--frame-panel-header-py-adjust:2px]">
          <FramePanel className="space-y-2 py-5 bg-card shadow-none!">
            <Pill tone="gray">{t('legacyPill')}</Pill>
            <p className="text-14 text-fg-muted">{t('legacyBody')}</p>
          </FramePanel>
        </Frame>
        {data.markdown && <MarkdownBlock markdown={data.markdown} period={data.period} />}
      </div>
    )
  }
  return (
    <div className="flex min-w-0 flex-col gap-5">
      <Frame dense spacing="sm" className="flex w-full min-w-0 flex-col [--frame-panel-header-py-adjust:2px]">
        <FrameHeader>
          <div className="flex flex-wrap items-baseline justify-between gap-3">
            <div className="space-y-0.5">
              <FrameTitle>{data.label}</FrameTitle>
              <p className="font-mono text-11 text-muted-foreground">
                {t('reportRange', {
                  start: formatTs(data.start_at),
                  end: formatTs(data.end_at),
                  generated: formatTs(data.generated_at),
                })}
              </p>
            </div>
            {data.license_status && (
              <Pill tone="gray">
                license · <code className="font-mono">{data.license_status}</code>
              </Pill>
            )}
          </div>
        </FrameHeader>
      </Frame>

      <section aria-label={t('secExec')}>
        <StatCards cards={execCards(t, s)} />
      </section>

      {/* 态势：左边这段时间告警怎么来的，右边这些告警是什么严重度。 */}
      <section
        aria-label={t('secTimeline')}
        className="grid auto-rows-fr items-stretch gap-5 @4xl:grid-cols-3"
      >
        <div className="min-w-0 @4xl:col-span-2">
          <TrendCard
            className="h-full"
            title={t('timelineTitle')}
            points={s.alerts.timeline.map((p) => ({ period: formatTick(p.ts), value: p.count }))}
            valueLabel={t('unitAlerts')}
            empty={t('noAlertsInPeriod')}
          />
        </div>
        <div className="min-w-0">
          <MixDonut
            className="h-full"
            title={t('severityMix')}
            centerLabel={t('centerAlerts')}
            slices={severitySlices(s.alerts.severity)}
            emptyText={t('noAlertsInPeriod')}
          />
        </div>
      </section>

      <section
        aria-label={t('secTopRulesEntities')}
        className="grid auto-rows-fr items-stretch gap-5 @4xl:grid-cols-2"
      >
        <div className="min-w-0">
          <RankCard
            className="h-full"
            title={t('topRules')}
            rows={s.alerts.top_rules.map((r) => ({ key: r.rule_name, value: r.count }))}
          />
        </div>
        <div className="min-w-0">
          <EntitiesCard rows={s.alerts.top_entities} />
        </div>
      </section>

      <section aria-label={t('secBaseline')}>
        <BaselineCard baseline={s.baseline} />
      </section>

      <section aria-label={t('secByAction')}>
        <Frame dense spacing="sm" className="flex w-full min-w-0 flex-col [--frame-panel-header-py-adjust:2px]">
          <FrameHeader>
            <FrameTitle>{t('byActionTitle')}</FrameTitle>
          </FrameHeader>
          <FramePanel className="py-5 bg-card shadow-none!">
            <ActionBars buckets={s.audit.by_action.map((a) => ({ key: a.action, count: a.count }))} />
          </FramePanel>
        </Frame>
      </section>

      <section
        aria-label={t('secTopIndexUser')}
        className="grid auto-rows-fr items-stretch gap-5 @4xl:grid-cols-2"
      >
        <div className="min-w-0">
          <RankCard
            className="h-full"
            title={t('topIndexes')}
            eyebrow={t('successRate', { rate: (s.audit.success_rate * 100).toFixed(1) })}
            rows={s.audit.top_indexes.map((r) => ({ key: r.index, value: r.count }))}
          />
        </div>
        <div className="min-w-0">
          <RankCard
            className="h-full"
            title={t('topUsers')}
            rows={s.audit.top_users.map((r) => ({ key: r.user, value: r.count }))}
          />
        </div>
      </section>

      <section aria-label={t('secProviders')}>
        <Frame dense spacing="sm" className="flex w-full min-w-0 flex-col [--frame-panel-header-py-adjust:2px]">
          <FrameHeader>
            <FrameTitle>{t('providersTitle')}</FrameTitle>
          </FrameHeader>
          <FramePanel className="py-0 bg-card shadow-none!">
            <ProviderTable providers={providers} />
          </FramePanel>
        </Frame>
      </section>

      <section aria-label={t('secFullReport')}>
        <MarkdownBlock markdown={data.markdown} period={data.period} />
      </section>
    </div>
  )
}

/* ----- Charts (recharts via ui/chart.tsx) ----- */

const ACTION_CONFIG = {
  count: { label: translate(reportsCopy, 'chartCount'), color: 'var(--chart-1)' },
} satisfies ChartConfig

/**
 * Category tick. Axis width is sized to the batch (see `categoryAxis`), so this
 * usually renders the full name; when the cap bites it ellipsises on the right
 * and keeps the whole value in an SVG <title>, replacing the old `title=` hover.
 * recharts clones this element with x/y/payload — hence the optional props.
 */
function CategoryTick({
  x,
  y,
  payload,
  maxChars,
}: {
  x?: number
  y?: number
  payload?: { value?: string | number }
  maxChars: number
}) {
  const full = String(payload?.value ?? '')
  return (
    <text x={x} y={y} dy={4} textAnchor="end" fontSize={12} className="font-mono">
      <title>{full}</title>
      {truncTick(full, maxChars)}
    </text>
  )
}

const BAR_LABEL = {
  fontSize: 12,
  className: 'fill-foreground font-mono tabular-nums',
} as const

function EntitiesCard({
  rows,
}: {
  rows: {
    value: string
    field: string
    count: number
    business_name: string | null
    criticality: string | null
    owner: string | null
  }[]
}) {
  return (
    <Frame dense spacing="sm" className="flex h-full w-full min-w-0 flex-col [--frame-panel-header-py-adjust:2px]">
      <FrameHeader>
        <FrameTitle>{translate(reportsCopy, 'topEntities')}</FrameTitle>
      </FrameHeader>
      <FramePanel className="py-3 bg-card shadow-none!">
        {rows.length === 0 ? (
          <div className="py-2 text-13 text-muted-foreground">
            {translate(reportsCopy, 'noData')}
          </div>
        ) : (
          <ul className="space-y-0.5">
            {rows.slice(0, 8).map((r, i) => (
              <li
                key={`${r.value}-${i}`}
                className="flex items-center justify-between gap-2 py-1.5 text-13 [box-shadow:0_-1px_0_var(--color-line)_inset] first:[box-shadow:none]"
              >
                <span className="min-w-0 flex-1">
                  <code className="block truncate font-mono text-12 text-foreground" title={r.value}>
                    {r.business_name ?? (r.value || '—')}
                  </code>
                  <span className="block truncate text-11 text-muted-foreground">
                    {r.field}
                    {r.criticality && ` · ${r.criticality}`}
                    {r.owner && ` · ${r.owner}`}
                  </span>
                </span>
                <span className="shrink-0 font-mono tabular-nums text-fg-muted">
                  {r.count.toLocaleString()}
                </span>
              </li>
            ))}
          </ul>
        )}
      </FramePanel>
    </Frame>
  )
}

function BaselineCard({
  baseline,
}: {
  baseline: {
    run_at: string | null
    pass_rate: number | null
    by_verdict: Record<string, number>
    top_fails: { rule_id: string; host: string; severity: string }[]
  }
}) {
  const t = useT(reportsCopy)
  return (
    <Frame dense spacing="sm" className="flex w-full min-w-0 flex-col [--frame-panel-header-py-adjust:2px]">
      <FrameHeader>
        <FrameTitle>{t('baselineTitle')}</FrameTitle>
      </FrameHeader>
      <FramePanel className="space-y-4 py-5 bg-card shadow-none!">
        {baseline.run_at === null ? (
          <div className="text-13 text-muted-foreground">{t('baselineEmpty')}</div>
        ) : (
          <>
            <div className="grid grid-cols-2 gap-3 sm:grid-cols-3">
              <Stat
                label={t('passRate')}
                value={baseline.pass_rate === null ? '—' : `${baseline.pass_rate.toFixed(1)}%`}
              />
              {Object.entries(baseline.by_verdict).map(([k, v]) => (
                <Stat key={k} label={k} value={v.toLocaleString()} />
              ))}
            </div>
            <p className="font-mono text-11 text-muted-foreground">
              {t('lastRun', { time: formatTs(baseline.run_at) })}
            </p>
            {baseline.top_fails.length > 0 && (
              <ul className="space-y-0.5">
                {baseline.top_fails.slice(0, 8).map((f, i) => (
                  <li
                    key={`${f.rule_id}-${f.host}-${i}`}
                    className="flex items-center justify-between gap-2 py-1.5 text-13 [box-shadow:0_-1px_0_var(--color-line)_inset] first:[box-shadow:none]"
                  >
                    <code className="truncate font-mono text-12 text-foreground" title={f.rule_id}>
                      {f.rule_id}
                    </code>
                    <span className="truncate font-mono text-12 text-fg-muted">{f.host}</span>
                    <Pill tone={severityTone(f.severity)}>{f.severity}</Pill>
                  </li>
                ))}
              </ul>
            )}
          </>
        )}
      </FramePanel>
    </Frame>
  )
}

/*
 * 基线那几格用的小指标砖。执行摘要那排换成了 `StatCards`（区块的四格），
 * 这里留一个更小的版本：基线的格子数随判定种类变（1~5 格），套四列的区块
 * 会排出空位，而这几个数字本来就是附在基线卡里的，不需要自己一张卡。
 */
function Stat({ label, value }: { label: string; value: string }) {
  return (
    <div className="rounded-lg border bg-card px-4 py-3">
      <div className="font-mono text-xs text-muted-foreground">{label}</div>
      <div className="mt-1.5 text-2xl font-semibold tabular-nums tracking-tight text-foreground">
        {value}
      </div>
    </div>
  )
}

function ActionBars({ buckets }: { buckets: Array<{ key: string; count: number }> }) {
  if (buckets.length === 0)
    return (
      <div className="text-13 text-muted-foreground">
        {translate(reportsCopy, 'noActionData')}
      </div>
    )
  const data = actionBarData(buckets)
  const axis = categoryAxis(buckets.map((b) => b.key))
  return (
    <ChartContainer
      config={ACTION_CONFIG}
      className="aspect-auto w-full"
      style={{ height: barChartHeight(buckets.length) }}
    >
      <BarChart data={data} layout="vertical" margin={{ top: 4, right: 72, bottom: 4, left: 4 }}>
        <XAxis type="number" domain={[0, actionAxisMax(buckets)]} hide />
        <YAxis
          type="category"
          dataKey="key"
          width={axis.width}
          tickLine={false}
          axisLine={false}
          tick={<CategoryTick maxChars={axis.maxChars} />}
        />
        <Bar
          dataKey="bar"
          radius={2}
          fill="var(--color-count)"
          fillOpacity={0.6}
          isAnimationActive={!prefersReducedMotion()}
        >
          <LabelList dataKey="label" position="right" offset={8} {...BAR_LABEL} />
        </Bar>
      </BarChart>
    </ChartContainer>
  )
}

function RankCard({
  title,
  eyebrow,
  rows,
  className,
}: {
  title: string
  eyebrow?: string
  rows: Array<{ key: string; value: number }>
  className?: string
}) {
  return (
    <Frame dense spacing="sm" className={cn('flex w-full min-w-0 flex-col [--frame-panel-header-py-adjust:2px]', className)}>
      <FrameHeader>
        <div className="flex items-baseline justify-between">
          <FrameTitle>{title}</FrameTitle>
          {eyebrow && <span className="font-mono text-xs text-muted-foreground">{eyebrow}</span>}
        </div>
      </FrameHeader>
      <FramePanel className="py-3 bg-card shadow-none!">
        {rows.length === 0 ? (
          <div className="py-2 text-13 text-muted-foreground">
            {translate(reportsCopy, 'noData')}
          </div>
        ) : (
          <ul className="space-y-0.5">
            {rows.slice(0, 8).map((r, i) => (
              <li
                key={`${r.key}-${i}`}
                className="flex items-center justify-between gap-2 py-1.5 text-13 [box-shadow:0_-1px_0_var(--color-line)_inset] first:[box-shadow:none]"
              >
                <code className="truncate font-mono text-12 text-foreground" title={r.key}>
                  {r.key || '—'}
                </code>
                <span className="font-mono tabular-nums text-fg-muted">{r.value.toLocaleString()}</span>
              </li>
            ))}
          </ul>
        )}
      </FramePanel>
    </Frame>
  )
}

function ProviderTable({ providers }: { providers: Provider[] }) {
  if (providers.length === 0) {
    return (
      <div className="px-5 py-6 text-13 text-muted-foreground">
        {translate(reportsCopy, 'providersEmpty')}
      </div>
    )
  }
  return (
    <div className="overflow-x-auto">
      <table className="w-full border-collapse text-13">
        <thead>
          <tr className="[box-shadow:0_-1px_0_var(--color-line)_inset]">
            {['', 'ID', 'MODEL', 'BASE_URL', translate(reportsCopy, 'colStatus'), 'CONSEC FAIL'].map((h, i) => (
              <th
                key={i}
                className="px-4 py-2 text-left font-mono text-11 font-medium uppercase tracking-wide text-muted-foreground"
              >
                {h}
              </th>
            ))}
          </tr>
        </thead>
        <tbody>
          {providers.map((p) => {
            const failed = (p.consec_failures ?? 0) >= 1
            const dot = !p.enabled
              ? 'bg-fg-faint'
              : failed
                ? 'bg-destructive'
                : 'bg-success'
            return (
              <tr key={p.id} className="[box-shadow:0_-1px_0_var(--color-line)_inset]">
                <td className="px-4 py-2">
                  <span className={cn('block size-2 rounded-full', dot)} aria-hidden="true" />
                </td>
                <td className="px-4 py-2 font-mono text-12 text-foreground">{p.id}</td>
                <td className="px-4 py-2 font-mono text-12 text-fg-muted">{p.model}</td>
                <td className="px-4 py-2 font-mono text-11 text-muted-foreground">
                  <span className="block max-w-[260px] truncate" title={p.base_url}>
                    {p.base_url}
                  </span>
                </td>
                <td className="px-4 py-2 text-12">
                  {!p.enabled ? (
                    <span className="text-muted-foreground">disabled</span>
                  ) : failed ? (
                    <span className="text-destructive">failing</span>
                  ) : (
                    <span className="text-success-foreground">healthy</span>
                  )}
                </td>
                <td className="px-4 py-2 font-mono text-12 tabular-nums text-foreground">
                  {p.consec_failures ?? 0}
                </td>
              </tr>
            )
          })}
        </tbody>
      </table>
    </div>
  )
}

function MarkdownBlock({ markdown, period }: { markdown: string; period: string }) {
  const t = useT(reportsCopy)
  const c = useT(commonCopy)
  const [copied, setCopied] = useState(false)
  async function copy() {
    try {
      await navigator.clipboard.writeText(markdown)
      setCopied(true)
      setTimeout(() => setCopied(false), 1500)
    } catch {
      // ignore
    }
  }
  function download() {
    const ts = new Date().toISOString().replace(/[:.]/g, '-').slice(0, 19)
    const blob = new Blob([markdown], { type: 'text/markdown;charset=utf-8' })
    const url = URL.createObjectURL(blob)
    const a = document.createElement('a')
    a.href = url
    a.download = `report-${period}-${ts}.md`
    document.body.appendChild(a)
    a.click()
    document.body.removeChild(a)
    URL.revokeObjectURL(url)
  }
  return (
    <Frame dense spacing="sm" className="flex w-full min-w-0 flex-col [--frame-panel-header-py-adjust:2px]">
      <FrameHeader>
        <div className="flex items-baseline justify-between gap-3">
          <FrameTitle>{t('markdownTitle')}</FrameTitle>
          <div className="flex items-center gap-2">
            <Button variant="outline" className="rounded-full" size="sm" onClick={copy}>
              {copied ? <HugeiconsIcon icon={CheckIcon} strokeWidth={2} className="size-3.5" /> : <HugeiconsIcon icon={CopyIcon} strokeWidth={2} className="size-3.5" />}
              {copied ? c('copied') : c('copy')}
            </Button>
            <Button variant="default" className="rounded-full" size="sm" onClick={download}>
              <HugeiconsIcon icon={Download01Icon} strokeWidth={2} className="size-3.5" />
              {t('downloadMd')}
            </Button>
          </div>
        </div>
      </FrameHeader>
      <FramePanel className="py-5 bg-card shadow-none!">
        {/* 正文渲染成文档，不再是塞在代码块里的原始 Markdown；复制 / 下载
            拿的仍是原文。 */}
        <div className="max-h-[480px] overflow-auto rounded-lg bg-accent px-4 py-3 [box-shadow:var(--shadow-ring-light)]">
          <Markdown>{markdown}</Markdown>
        </div>
      </FramePanel>
    </Frame>
  )
}

/* 严重度在环形图里用自己的语义色刻度，和实时告警 / 批量分诊同一套。 */
const SEV_FILL: Record<string, string> = {
  critical: 'var(--color-foreground)',
  high: 'var(--color-destructive)',
  medium: 'var(--color-warning)',
  low: 'var(--color-muted-foreground)',
  info: 'var(--color-info)',
  informational: 'var(--color-info)',
}

function severitySlices(rows: { severity: string; count: number }[]): DonutSlice[] {
  return rows
    .filter((r) => r.count > 0)
    .map((r) => ({
      key: r.severity,
      name: severityLabel(r.severity),
      count: r.count,
      color: SEV_FILL[r.severity],
    }))
}

function execCards(t: Translate<ReportsKey>, s: ReportSummary): StatCard[] {
  return [
    {
      label: t('kpiTotalLabel'),
      title: t('kpiTotal'),
      value: s.exec.alerts_total.toLocaleString(),
      icon: <HugeiconsIcon icon={ShieldAlertIcon} strokeWidth={2} aria-hidden="true" />,
    },
    {
      label: t('kpiUrgentLabel'),
      title: t('kpiUrgent'),
      value: s.exec.high_critical.toLocaleString(),
      tone: s.exec.high_critical > 0 ? 'destructive' : undefined,
      icon: <HugeiconsIcon icon={TriangleAlertIcon} strokeWidth={2} aria-hidden="true" />,
    },
    {
      label: t('kpiEntitiesLabel'),
      title: t('kpiEntities'),
      value: s.exec.entities.toLocaleString(),
      icon: <HugeiconsIcon icon={Layers01Icon} strokeWidth={2} aria-hidden="true" />,
    },
    {
      label: t('kpiAnalyzedLabel'),
      title: t('kpiAnalyzed'),
      value: s.exec.analyzed.toLocaleString(),
      icon: <HugeiconsIcon icon={SparklesIcon} strokeWidth={2} aria-hidden="true" />,
    },
  ]
}

/** 时间线的横轴刻度：同一天只写时分，跨天带上日期。 */
function formatTick(ts: string): string {
  const d = new Date(ts)
  if (Number.isNaN(d.getTime())) return ts
  const hh = String(d.getHours()).padStart(2, '0')
  const today = new Date()
  const sameDay =
    d.getFullYear() === today.getFullYear() &&
    d.getMonth() === today.getMonth() &&
    d.getDate() === today.getDate()
  return sameDay ? `${hh}:00` : `${d.getMonth() + 1}/${d.getDate()} ${hh}:00`
}

function severityTone(sev: string): 'sev-info' | 'sev-low' | 'sev-medium' | 'sev-high' | 'sev-critical' {
  switch (sev) {
    case 'critical':
      return 'sev-critical'
    case 'high':
      return 'sev-high'
    case 'medium':
      return 'sev-medium'
    case 'low':
      return 'sev-low'
    default:
      return 'sev-info'
  }
}

function formatTs(s: string): string {
  try {
    const d = new Date(s)
    if (isNaN(d.getTime())) return s
    return d.toLocaleString()
  } catch {
    return s
  }
}
