import { useEffect, useMemo, useState, type ReactNode } from 'react'
import { HugeiconsIcon } from '@hugeicons/react'
import {
  Activity02Icon, CheckmarkCircle02Icon, ClipboardCheckIcon, InformationCircleIcon,
  Loading03Icon, PlayIcon,
  TriangleAlertIcon,
} from '@hugeicons/core-free-icons'
import { GatedButton } from '@/components/gated-button'
import { api, type ApiError, type BaselineResult, type BaselineRunSummary } from '@/lib/api'
import { useT, type Translate } from '@/lib/i18n'
import { baselineCopy, type BaselineKey } from '@/locales/baseline'
import { MixDonut, type DonutSlice } from '@/components/blocks/chart-13/components/mix-donut'
import { TrendCard, type TrendPoint } from '@/components/blocks/chart-18/components/trend-card'
import { StatCards, type StatCard } from '@/components/blocks/dashboard-1/components/stat-cards'
import { EntityList, type EntityRow } from '@/components/blocks/list-8/components/entity-list'
import { Badge } from '@/components/reui/badge'
import { Alert, AlertDescription } from '@/components/reui/alert'
import { Frame, FramePanel } from '@/components/reui/frame'
import { PageHeader } from '@/components/shell/page-header'
import { Collapsible, CollapsibleContent, CollapsibleTrigger } from '@/components/ui/collapsible'
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from '@/components/ui/select'
import { Tabs, TabsContent, TabsList, TabsTrigger } from '@/components/ui/tabs'
import { cn } from '@/lib/utils'
import { BaselineResultsTable } from '@/components/baseline/BaselineResultsTable'
import { VERDICT_STYLE, verdictLabel } from '@/components/baseline/verdictStyle'
import { BaselineRulesTab } from '@/components/baseline/BaselineRulesTab'
import { BaselineRunsTab } from '@/components/baseline/BaselineRunsTab'
import { BlockLoading } from '@/components/shared/block-states'

type FieldMap = {
  host_field: string
  query_field: string
  col_prefix: string
  source: string
  confident: boolean
}

type Tab = 'results' | 'rules' | 'runs'

/* Select 不能用空串当 value（空串是「没选」），所以「全部」走这个哨兵。 */
const ALL_VERDICTS = '__all__'

const TABS: { id: Tab; label: BaselineKey }[] = [
  { id: 'results', label: 'tabResults' },
  { id: 'rules', label: 'tabRules' },
  { id: 'runs', label: 'tabRuns' },
]

export function BaselinePage() {
  const t = useT(baselineCopy)
  const [tab, setTab] = useState<Tab>('results')
  const [summary, setSummary] = useState<BaselineRunSummary | null>(null)
  // 通过率趋势要的是历史轮次，不是当前这一轮 —— 一轮只有一个点。
  const [runs, setRuns] = useState<BaselineRunSummary[]>([])
  const [results, setResults] = useState<BaselineResult[]>([])
  const [fieldMap, setFieldMap] = useState<FieldMap | null>(null)
  const [running, setRunning] = useState(false)
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)
  const [verdictFilter, setVerdictFilter] = useState<string>('')

  async function loadLatest() {
    setLoading(true)
    setError(null)
    try {
      const [s, fm, rs] = await Promise.all([
        api.baselineSummary(),
        api.baselineFieldMap().catch(() => null),
        // 趋势是锦上添花，取不到就不画，不该把整页拖成加载失败。
        api.baselineRuns(30).catch(() => null),
      ])
      setSummary(s.run)
      setFieldMap(fm)
      setRuns(rs?.runs ?? [])
      if (s.run) {
        const r = await api.baselineResults({ run_id: s.run.run_id, size: 2000 })
        setResults(r.results)
      } else {
        setResults([])
      }
    } catch (e) {
      setError((e as ApiError).message || t('errLoad'))
    } finally {
      setLoading(false)
    }
  }

  useEffect(() => {
    void loadLatest()
  }, [])

  async function runNow() {
    setRunning(true)
    setError(null)
    try {
      const s = await api.baselineRun(null)
      setSummary(s)
      const r = await api.baselineResults({ run_id: s.run_id, size: 2000 })
      setResults(r.results)
      const rs = await api.baselineRuns(30).catch(() => null)
      setRuns(rs?.runs ?? [])
    } catch (e) {
      setError((e as ApiError).message || t('errRun'))
    } finally {
      setRunning(false)
    }
  }

  const hosts = useMemo(() => Array.from(new Set(results.map((r) => r.host))).sort(), [results])
  const filtered = useMemo(
    () => (verdictFilter ? results.filter((r) => r.verdict === verdictFilter) : results),
    [results, verdictFilter],
  )

  // 单机评分（按 host 聚合 pass/(pass+fail)）
  const hostScores = useMemo(() => {
    const m = new Map<string, { pass: number; fail: number }>()
    for (const r of results) {
      const e = m.get(r.host) ?? { pass: 0, fail: 0 }
      if (r.verdict === 'pass') e.pass++
      else if (r.verdict === 'fail') e.fail++
      m.set(r.host, e)
    }
    return m
  }, [results])

  return (
    <div className="@container flex w-full flex-col gap-5">
      <PageHeader
        title={t('title')}
        actions={
          tab === 'results' ? (
            <GatedButton gate="write" onClick={runNow} disabled={running}>
              <HugeiconsIcon
                icon={running ? Loading03Icon : PlayIcon}
                strokeWidth={2}
                className={cn('size-4', running && 'animate-spin')}
              />
              {running ? t('running') : t('runNow')}
            </GatedButton>
          ) : undefined
        }
      />

      <Tabs value={tab} onValueChange={(v) => setTab(v as Tab)} className="flex-col gap-5">
        {/* 用原语自己的 TabsList —— 原来那串 data-active:bg-info
            是在把它重画成一排胶囊按钮。 */}
        <TabsList>
          {TABS.map((tab) => (
            <TabsTrigger key={tab.id} value={tab.id}>{t(tab.label)}</TabsTrigger>
          ))}
        </TabsList>

        <TabsContent value="results">
          <ResultsTab
            summary={summary}
            runs={runs}
            fieldMap={fieldMap}
            error={error}
            loading={loading}
            verdictFilter={verdictFilter}
            setVerdictFilter={setVerdictFilter}
            hosts={hosts}
            filtered={filtered}
            hostScores={hostScores}
          />
        </TabsContent>
        <TabsContent value="rules">
          <BaselineRulesTab />
        </TabsContent>
        <TabsContent value="runs">
          <BaselineRunsTab />
        </TabsContent>
      </Tabs>
    </div>
  )
}

function ResultsTab({
  summary,
  runs,
  fieldMap,
  error,
  loading,
  verdictFilter,
  setVerdictFilter,
  hosts,
  filtered,
  hostScores,
}: {
  summary: BaselineRunSummary | null
  runs: BaselineRunSummary[]
  fieldMap: FieldMap | null
  error: string | null
  loading: boolean
  verdictFilter: string
  setVerdictFilter: (v: string) => void
  hosts: string[]
  filtered: BaselineResult[]
  hostScores: Map<string, { pass: number; fail: number }>
}) {
  const t = useT(baselineCopy)
  return (
    <div className="flex min-w-0 flex-col gap-5">
      {/* 字段自检只在真的跑过一轮之后才有意义：一条结果都没有的时候它必然是
          「低置信度」，而那时候该说的是「还没有数据」（下面那块空态已经在说），
          不是先甩一个警告三角。跑过之后，自检通过是说明（信息图标），拿不准
          才是警告。 */}
      {fieldMap && summary && (
        <Alert variant={fieldMap.confident ? 'default' : 'warning'}>
          <HugeiconsIcon
            icon={fieldMap.confident ? InformationCircleIcon : TriangleAlertIcon}
            strokeWidth={2}
            className="size-4"
          />
          <AlertDescription className="text-xs">
            {/* AlertDescription 是 grid，每个子节点自成一行——整句包成一个 span，
                否则每个 <code> 会被拆到单独一行。 */}
            <span>
              {t('fieldMapCheck')}: {t('fieldMapHost')}=<code>{fieldMap.host_field}</code> ·{' '}
              {t('fieldMapRuleKey')}=<code>{fieldMap.query_field}</code> ·{' '}
              {t('fieldMapPrefix')}=<code>{fieldMap.col_prefix}</code> ·{' '}
              {t('fieldMapSource')}={fieldMap.source}
              {!fieldMap.confident && ` · ${t('fieldMapLowConfidence')}`}
            </span>
          </AlertDescription>
        </Alert>
      )}

      {error && (
        <Alert variant="destructive">
          <HugeiconsIcon icon={TriangleAlertIcon} strokeWidth={2} className="size-4" />
          <AlertDescription>{error}</AlertDescription>
        </Alert>
      )}

      {summary && (
        <>
          <section aria-label={t('secSummary')}>
            <StatCards cards={summaryCards(t, summary)} />
          </section>
          <section
            aria-label={t('secTrend')}
            className="grid auto-rows-fr items-stretch gap-5 @4xl:grid-cols-3"
          >
            <div className="min-w-0 @4xl:col-span-2">
              <TrendCard
                title={t('trendTitle')}
                points={trendPoints(runs)}
                valueLabel={t('unitScore')}
                empty={t('trendEmpty')}
              />
            </div>
            <div className="min-w-0">
              <MixDonut
                title={t('verdictMix')}
                centerLabel={t('unitResults')}
                slices={verdictSlices(summary)}
                emptyText={t('verdictMixEmpty')}
              />
            </div>
          </section>
        </>
      )}

      <section aria-label={t('secFilter')} className="flex flex-wrap items-center gap-2">
        <Select
          value={verdictFilter || ALL_VERDICTS}
          onValueChange={(v) => setVerdictFilter(v === ALL_VERDICTS ? '' : String(v))}
        >
          <SelectTrigger className="w-[170px]" aria-label={t('filterByVerdict')}>
            <SelectValue>
              {(v) => (v === ALL_VERDICTS ? t('verdictAll') : verdictLabel(String(v)))}
            </SelectValue>
          </SelectTrigger>
          <SelectContent>
            <SelectItem value={ALL_VERDICTS}>{t('verdictAll')}</SelectItem>
            {['fail', 'pass', 'stale', 'manual_review', 'error'].map((v) => (
              <SelectItem key={v} value={v}>{verdictLabel(v)}</SelectItem>
            ))}
          </SelectContent>
        </Select>
        <span className="ml-auto text-xs text-muted-foreground">
          {t('countHostsResults', { hosts: hosts.length, results: filtered.length })}
        </span>
      </section>

      <section aria-label={t('secResults')} className="min-w-0">
        {loading ? (
          <BlockLoading />
        ) : !summary ? (
          <BaselineOnboarding />
        ) : (
          <BaselineResultsTable results={filtered} />
        )}
      </section>

      {hosts.length > 0 && (
        <section aria-label={t('secHostScores')}>
          <EntityList
            title={t('hostScoresTitle')}
            hint={t('hostScoresDesc')}
            rows={hostRows(t, hosts, hostScores)}
          />
        </section>
      )}
    </div>
  )
}

/* Baseline is inert until osquery results land in ES — the rule library alone
 * produces nothing. This walks the operator through the missing data pipeline
 * instead of the old one-line "前置：…" note that assumed they already knew. */
function BaselineOnboarding() {
  const t = useT(baselineCopy)
  /* 前两步的正文里嵌着要照抄的命令，所以文案分成「命令前」和「命令后」两截；
     后三步是整句，直接一个键。 */
  const steps: { t: string; d: ReactNode }[] = [
    {
      t: t('onboardStep1'),
      d: (
        <>
          <code className="rounded bg-muted px-1 font-mono text-xs">
            python -m scripts.baseline_setup_indices
          </code>
          {t('onboardStep1Body')}
        </>
      ),
    },
    {
      t: t('onboardStep2'),
      d: (
        <>
          <code className="rounded bg-muted px-1 font-mono text-xs">
            python -m scripts.baseline_load_rules --file backend/baseline/data/rules_normal.json
          </code>
          {t('onboardStep2Body')}
        </>
      ),
    },
    { t: t('onboardStep3'), d: t('onboardStep3Body') },
    { t: t('onboardStep4'), d: t('onboardStep4Body') },
    { t: t('onboardStep5'), d: t('onboardStep5Body') },
  ]
  /* 五步接入是「第一次装的时候看一遍」的东西，不是这一页的常驻内容 —— 摊开在
     空态里，每次数据没跑出来都要重读一遍五步。收进一个默认关着的展开区：一句话
     说清为什么是空的，要照做的人点开就有，已经装完的人不用再看第二遍。 */
  const [open, setOpen] = useState(false)

  return (
    <Frame dense spacing="sm">
      <FramePanel className="flex flex-col gap-3 bg-card py-6 shadow-none!">
        <div className="text-sm">{t('onboardIntro')}</div>
        <Collapsible open={open} onOpenChange={setOpen}>
          <CollapsibleTrigger className="text-13 text-primary underline-offset-2 hover:underline">
            {open ? t('onboardHide') : t('onboardShow')}
          </CollapsibleTrigger>
          <CollapsibleContent className="mt-3 flex flex-col gap-4">
            <ol className="space-y-3">
              {steps.map((s) => (
                <li key={s.t} className="flex gap-3">
                  <span className="mt-0.5 shrink-0 font-mono text-xs font-semibold text-primary">{s.t}</span>
                  <span className="text-sm leading-relaxed text-muted-foreground">{s.d}</span>
                </li>
              ))}
            </ol>
            <div className="text-xs text-muted-foreground">{t('onboardHint')}</div>
          </CollapsibleContent>
        </Collapsible>
      </FramePanel>
    </Frame>
  )
}

/* ---------------- 概览的三块数据 ---------------- */

/*
 * score 为 null = 这一轮什么都没评到。渲染成数字（或 100）等于给一台没人检查过的
 * 主机报「完全合规」。
 */
function summaryCards(t: Translate<BaselineKey>, s: BaselineRunSummary): StatCard[] {
  const scored = s.pass + s.fail
  return [
    {
      label: t('kpiScoreLabel', { hosts: s.host_count, rules: s.rule_count }),
      title: t('kpiScore'),
      value: s.score == null ? t('notScored') : String(s.score),
      tone: s.score != null && s.score < 80 ? 'warning' : undefined,
      icon: <HugeiconsIcon icon={ClipboardCheckIcon} strokeWidth={2} aria-hidden="true" />,
    },
    {
      label: t('kpiPassLabel', { n: scored }),
      title: t('kpiPass'),
      value: String(s.pass),
      icon: <HugeiconsIcon icon={CheckmarkCircle02Icon} strokeWidth={2} aria-hidden="true" />,
    },
    {
      label: t('kpiFailLabel'),
      title: t('kpiFail'),
      value: String(s.fail),
      tone: s.fail > 0 ? 'destructive' : undefined,
      icon: <HugeiconsIcon icon={TriangleAlertIcon} strokeWidth={2} aria-hidden="true" />,
    },
    {
      // 这两类都没有结论，但原因不同：一个是规则要求人看，一个是判定过程本身出错。
      label: t('kpiOtherLabel'),
      title: t('kpiOther'),
      value: `${s.manual_review} / ${s.error}`,
      tone: s.error > 0 ? 'warning' : undefined,
      icon: <HugeiconsIcon icon={Activity02Icon} strokeWidth={2} aria-hidden="true" />,
    },
  ]
}

/* 判定分布。判定这套词汇自己拥有颜色，所以显式传 fill，不走环的默认调色板。 */
function verdictSlices(s: BaselineRunSummary): DonutSlice[] {
  return (
    [
      ['pass', s.pass],
      ['fail', s.fail],
      ['manual_review', s.manual_review],
      ['error', s.error],
    ] as const
  )
    .filter(([, n]) => n > 0)
    .map(([k, n]) => ({
      key: k,
      name: verdictLabel(k),
      count: n,
      color: VERDICT_STYLE[k].fill,
    }))
}

/* 历史轮次按时间正序，最多画最近 30 轮。没打分的轮次跳过 —— 画成 0 分会读成
 * 「那天全挂了」。 */
function trendPoints(runs: BaselineRunSummary[]): TrendPoint[] {
  return runs
    .filter((r) => r.score != null)
    .slice()
    .sort((a, b) => (a.started_at < b.started_at ? -1 : 1))
    .map((r) => ({ period: (r.started_at || '').slice(5, 16).replace('T', ' '), value: r.score }))
}

function hostRows(
  t: Translate<BaselineKey>,
  hosts: string[],
  scores: Map<string, { pass: number; fail: number }>,
): EntityRow[] {
  return hosts.map((h) => {
    const e = scores.get(h) ?? { pass: 0, fail: 0 }
    const denom = e.pass + e.fail
    const score = denom === 0 ? null : Math.round((e.pass / denom) * 1000) / 10
    return {
      id: h,
      title: <span className="font-mono">{h}</span>,
      meta: t('hostScoreMeta', { pass: e.pass, fail: e.fail }),
      action: (
        <Badge
          size="sm"
          variant={score == null ? 'secondary' : score >= 80 ? 'success-light' : 'destructive-light'}
          className="shrink-0 tabular-nums"
        >
          {score == null ? t('notScored') : score}
        </Badge>
      ),
    }
  })
}
