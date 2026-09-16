import { useCallback, useEffect, useMemo, useRef, useState, type ReactNode } from 'react'
import { HugeiconsIcon } from '@hugeicons/react'
import { AlertCircleIcon, Cancel01Icon, Download01Icon, HistoryIcon, LightbulbIcon, SaveIcon, ShieldAlertIcon, SparklesIcon, TriangleAlertIcon } from '@hugeicons/core-free-icons'
import { api, type ApiError } from '@/lib/api'
import { toast } from 'sonner'
import { Alert, AlertDescription } from '@/components/reui/alert'
import { Frame, FrameHeader, FramePanel, FrameTitle } from '@/components/reui/frame'
import { MixDonut, type DonutSlice } from '@/components/blocks/chart-13/components/mix-donut'
import { ClusterQueue } from '@/components/triage/ClusterQueue'
import { StatCards, type StatCard } from '@/components/blocks/dashboard-1/components/stat-cards'
import { PageHeader } from '@/components/shell/page-header'
import { Button } from '@/components/ui/button'
import { Label } from '@/components/ui/label'
import {
  Select, SelectContent, SelectItem, SelectTrigger, SelectValue,
} from '@/components/ui/select'
import { Input } from '@/components/ui/input'
import { Textarea } from '@/components/ui/textarea'
import { Popover, PopoverContent, PopoverTrigger } from '@/components/ui/popover'
import { Skeleton } from '@/components/ui/skeleton'
import { IndexCombobox } from '@/components/IndexCombobox'
import { Pill } from '@/components/ui/Pill'
import { InvestigationDialog } from '@/components/InvestigationDialog'
import { downloadCsv, escapeCell } from '@/lib/csv'
import { expandPath, takeHandoff } from '@/lib/handoff'
import { getStatusLocal, loadStatuses, probeSync, saveStatus, statusLabel, STATUS_ORDER, type TriageStatus } from '@/lib/triageStatus'
import { useT } from '@/lib/i18n'
import { commonCopy } from '@/locales/common'
import { triageCopy } from '@/locales/triage'
import { classifyError } from '@/lib/errorHelp'
import { syncWarning } from '@/lib/syncHealth'
import { cn } from '@/lib/utils'
import { severityLabel } from '@/lib/severity'

type Severity = 'info' | 'low' | 'medium' | 'high' | 'critical'

type Cluster = {
  cluster_id: string
  rule_id: string
  subject_field: string
  subject_value: string
  count: number
  alert_ids: string[]
  first_seen: string | null
  last_seen: string | null
  severity: string
  priority_rank: number
  recommendation: string
  is_likely_fp: boolean
  fp_reason: string
  attack_intent: string
}

type TriageResult = {
  total_alerts: number
  total_clusters: number
  scored_clusters: number
  truncated: boolean
  degraded?: boolean
  degraded_reason?: string
  rag_chunks_used?: number
  clusters: Cluster[]
  skipped_clusters?: Array<{ cluster_id: string; count: number; reason: string }>
}

const DEFAULT_ALERT_INDEX = '.alerts-security.alerts-default'

/* Base UI 的 Select 不能拿空串当值（空串 = 没选），所以"全部"用哨兵。 */
const ALL = '__all__'

/* 环形图里严重度用自己的语义色刻度，不用图表调色板。 */
const SEV_FILL: Record<string, string> = {
  critical: 'var(--color-foreground)',
  high: 'var(--color-destructive)',
  medium: 'var(--color-warning)',
  low: 'var(--color-muted-foreground)',
  info: 'var(--color-info)',
}

/** Best-effort extraction of an alert doc's source index. */
function alertIndex(doc: Record<string, unknown>): string | null {
  const src = doc?._source as Record<string, unknown> | undefined
  const candidates = [doc?._index, src?._index, src?.index]
  for (const c of candidates) {
    if (typeof c === 'string' && c.trim()) return c.trim()
  }
  return null
}

const ES_QUERY_PLACEHOLDER = `{\n  "bool": {\n    "filter": [\n      { "term": { "kibana.alert.status": "active" } }\n    ]\n  }\n}`

export function TriagePage() {
  const t = useT(triageCopy)
  // 交接来的告警（实时告警／智能查询「送去分诊」）。空 = 走 ES 拉取。
  const [handoffAlerts, setHandoffAlerts] = useState<Record<string, unknown>[]>([])
  const [esIndex, setEsIndex] = useState('.alerts-security.alerts-default')
  const [esQuery, setEsQuery] = useState('')
  const [windowMinutes, setWindowMinutes] = useState(60)
  const [maxAlerts, setMaxAlerts] = useState(100)
  const [maxClustersToLlm, setMaxClustersToLlm] = useState(30)
  const [loading, setLoading] = useState(false)
  const [errorMsg, setErrorMsg] = useState<string | null>(null)
  const [result, setResult] = useState<TriageResult | null>(null)
  const [handoffNote, setHandoffNote] = useState<string | null>(null)
  // Notice when a pasted batch is auto-truncated to the cap (Wave fix #3).
  const [truncateNote, setTruncateNote] = useState<string | null>(null)
  // The alerts actually triaged in paste mode — kept so "深入调查" can recover the
  // real source index of each cluster instead of hardcoding one (#4).
  const [pastedAlerts, setPastedAlerts] = useState<Record<string, unknown>[]>([])
  // cluster_id → source index, captured at save time and restored when a past
  // run is re-loaded. Without it, a loaded run has no pastedAlerts to resolve
  // against, so every 深入调查 fell back to the alerts-default index.
  const [savedIndexMap, setSavedIndexMap] = useState<Record<string, string> | null>(null)
  // Cluster → Investigation dialog (Round 12).
  const [investigateAlert, setInvestigateAlert] = useState<Record<string, unknown> | null>(null)
  const [investigateCluster, setInvestigateCluster] = useState<Cluster | null>(null)
  const [investigateIndex, setInvestigateIndex] = useState('.alerts-security.alerts-default')

  // Team-shared cluster disposition (Wave 2 #6) — loaded from the server.
  const [statuses, setStatuses] = useState<Record<string, TriageStatus>>({})
  /* Save / export feedback. sonner keeps the same rule the hand-rolled note had: a success message
   * expires, an error stays until it is dismissed — someone who looked away
   * must not miss the one message that says the save did NOT happen. */
  const showNote = useCallback((text: string, tone: 'ok' | 'err') => {
    if (tone === 'ok') toast.success(text)
    else toast.error(text, { duration: Infinity })
  }, [])

  // Side-by-side compare tray (Wave 3 #8) — selected cluster_ids.
  const [compareIds, setCompareIds] = useState<string[]>([])
  // P0: warn when disposition can't reach the server (local-only, team won't see it).
  const [syncWarn, setSyncWarn] = useState<string | null>(null)

  function toggleCompare(id: string) {
    setCompareIds((cur) => (cur.includes(id) ? cur.filter((x) => x !== id) : [...cur, id]))
  }

  // Resolve the ES index to investigate a cluster against. In ES mode that's the
  // queried index; in paste mode we recover the real index carried by one of the
  // cluster's own source alerts (handoffs from the Query page carry business-log
  // indices), falling back to the security-alerts default only as a last resort.
  function indexForCluster(c: Cluster): string {
    // A restored past run carries its own resolved index per cluster.
    const fromSaved = savedIndexMap?.[c.cluster_id]
    if (fromSaved) return fromSaved
    if (handoffAlerts.length === 0) return esIndex.trim() || DEFAULT_ALERT_INDEX
    const ids = new Set(c.alert_ids.map(String))
    for (const a of pastedAlerts) {
      const id = a?._id
      if (id != null && ids.has(String(id))) {
        const idx = alertIndex(a)
        if (idx) return idx
      }
    }
    for (const a of pastedAlerts) {
      const idx = alertIndex(a)
      if (idx) return idx
    }
    return DEFAULT_ALERT_INDEX
  }

  function openInvestigate(c: Cluster) {
    setInvestigateIndex(indexForCluster(c))
    setInvestigateAlert(clusterToAlert(c))
    setInvestigateCluster(c)
  }

  /* The ONE place a cluster's disposition changes. Lifted out of the card's
   * inline handler so the investigation dialog can mark the same cluster
   * through it — the dialog used to write a separate `inv:` key that this page
   * never reads, so a cluster marked 已处置 in the dialog still showed 未处置
   * in the list behind it. */
  function changeClusterStatus(c: Cluster, next: TriageStatus) {
    const prev = statuses[c.cluster_id] ?? getStatusLocal(c.cluster_id)
    setStatuses((s) => ({ ...s, [c.cluster_id]: next }))
    void saveStatus(c.cluster_id, next).then((ok) => {
      setSyncWarn(ok ? null : syncWarning(t('syncScopeStatus')))
    })
    // 升级 → 询问是否推送值班（仅在从非升级切到升级时触发一次）
    if (next === 'escalated' && prev !== 'escalated') {
      if (window.confirm(t('confirmEscalate'))) {
        void api
          .triageEscalate(c as unknown as Record<string, unknown>)
          .then((r) => {
            if (r.dispatched > 0) {
              showNote(t('okDispatched', { n: r.dispatched }), 'ok')
            } else {
              setSyncWarn(t('warnNoChannel'))
            }
          })
          .catch((e) =>
            setSyncWarn(t('errEscalate', { err: e instanceof Error ? e.message : '' })),
          )
      }
    }
  }

  // Pull the team's dispositions whenever a fresh result lands so marks made by
  // other analysts show up. Async setState → not the sync set-state-in-effect.
  useEffect(() => {
    if (result) {
      void loadStatuses().then(setStatuses)
      void probeSync().then((ok) =>
        setSyncWarn(ok ? null : syncWarning(t('syncScopeStatus'))),
      )
    }
  }, [result, t])

  // Pick up a handoff from the Query page ("送去分诊").
  useEffect(() => {
    const h = takeHandoff('triage')
    if (h && h.alerts.length > 0) {
      // eslint-disable-next-line react-hooks/set-state-in-effect -- hydrate once from the Query-page handoff
      setHandoffAlerts(h.alerts)
      setHandoffNote(h.sourceNote ?? t('handoffReceived', { n: h.alerts.length }))
    }
  }, [t])

  async function onSubmit() {
    setErrorMsg(null)
    setResult(null)
    setTruncateNote(null)
    setSavedIndexMap(null) // a fresh run resolves indices live, not from a saved map
    let payload: Parameters<typeof api.triageBatch>[0]
    if (handoffAlerts.length > 0) {
      let alerts = handoffAlerts
      // Backend caps the batch at MAX_ALERTS; truncate up front (with a clear
      // notice) instead of sending an oversized body that hard-400s.
      if (alerts.length > maxAlerts) {
        setTruncateNote(t('truncateNote', { got: alerts.length, max: maxAlerts }))
        alerts = alerts.slice(0, maxAlerts)
      }
      setPastedAlerts(alerts)
      payload = {
        alerts,
        max_alerts: maxAlerts,
        max_clusters_to_llm: maxClustersToLlm,
      }
    } else {
      if (!esIndex.trim()) return setErrorMsg(t('errIndexRequired'))
      let queryObj: Record<string, unknown> | undefined
      const rawQ = esQuery.trim()
      if (rawQ) {
        try {
          queryObj = JSON.parse(rawQ)
        } catch (e) {
          return setErrorMsg(t('errQueryJson', { err: (e as Error).message }))
        }
      }
      payload = {
        index: esIndex.trim(),
        query: queryObj,
        window_minutes: windowMinutes,
        max_alerts: maxAlerts,
        max_clusters_to_llm: maxClustersToLlm,
      }
    }
    setLoading(true)
    try {
      const r = await api.triageBatch(payload)
      setResult(r)
    } catch (e) {
      setErrorMsg((e as ApiError).message || t('errRequest'))
    } finally {
      setLoading(false)
    }
  }

  const sortedClusters = useMemo(
    () => (result ? [...result.clusters].sort((a, b) => a.priority_rank - b.priority_rank) : []),
    [result],
  )

  /* 结果列表的分流。一次分诊常有几十组，而"先看哪几组"就是这一页存在的理由——
     严重度和处置状态各一个筛选，比让人从头滚到尾快。导出 CSV 走的仍是全量，
     筛选是看的方式，不是结果本身。 */
  const [sevFilter, setSevFilter] = useState<string>(ALL)
  const [statusFilter, setStatusFilter] = useState<string>(ALL)

  const visibleClusters = useMemo(
    () =>
      sortedClusters.filter((c) => {
        if (sevFilter !== ALL && normalizeSev(c.severity) !== sevFilter) return false
        if (statusFilter !== ALL) {
          const st = statuses[c.cluster_id] ?? getStatusLocal(c.cluster_id)
          if (st !== statusFilter) return false
        }
        return true
      }),
    [sevFilter, sortedClusters, statusFilter, statuses],
  )

  const sevSlices = useMemo<DonutSlice[]>(
    () =>
      (['critical', 'high', 'medium', 'low', 'info'] as const)
        .map((sv) => ({
          key: sv,
          name: severityLabel(sv),
          count: sortedClusters.filter((c) => normalizeSev(c.severity) === sv).length,
          color: SEV_FILL[sv],
        }))
        .filter((s) => s.count > 0),
    [sortedClusters],
  )

  const sevCounts = useMemo(() => {
    const out: Record<string, number> = {}
    for (const c of sortedClusters) {
      const s = normalizeSev(c.severity)
      out[s] = (out[s] ?? 0) + 1
    }
    return out
  }, [sortedClusters])

  async function onSaveRun() {
    if (!result) return
    const note = window.prompt(t('promptSaveNote'), '') ?? ''
    const runId = `${Date.now()}`
    // Snapshot each cluster's resolved source index so a re-loaded run can still
    // investigate against the right index (the raw alerts aren't persisted).
    const indexMap: Record<string, string> = {}
    for (const c of result.clusters) indexMap[c.cluster_id] = indexForCluster(c)
    try {
      await api.statePut('triage_result', runId, {
        id: runId,
        created_at: new Date().toISOString(),
        note,
        result,
        index_map: indexMap,
      })
      showNote(t('okSaved'), 'ok')
    } catch (e) {
      showNote(e instanceof Error ? `${t('errSave')}: ${e.message}` : t('errSave'), 'err')
    }
  }

  function onExportCsv() {
    if (!result) return
    const ts = new Date().toISOString().replace(/[:.]/g, '-').slice(0, 19)
    downloadCsv(`triage-${ts}.csv`, clustersToCsv(sortedClusters, statuses))
  }

  return (
    <div className="@container flex w-full flex-col gap-5">
      <PageHeader
        title={t('title')}
      />

      <section aria-label={t('secSubmit')}>
      <Frame dense spacing="sm" className="flex w-full min-w-0 flex-col [--frame-panel-header-py-adjust:2px]">
        <FrameHeader>
          <FrameTitle>{t('cardSubmitTitle')}</FrameTitle>
        </FrameHeader>
        <FramePanel className="flex flex-col gap-4 bg-card shadow-none!">
          {/* 只剩「从 ES 拉」这一条输入。原来还有个「直接粘贴 JSON」的大文本框，
              那是联调期留下的：日常没人手抄告警 JSON，真正会走这条路的是从实时
              告警／智能查询「送去分诊」的交接 —— 交接照旧走同一条内部通道，下面
              那张卡片就是它，只是不再需要一个空文本框摆在页面正中。 */}
          {handoffAlerts.length > 0 ? (
            <div className="flex flex-wrap items-center gap-2 rounded-md bg-info-subtle px-3 py-2 text-12 text-badge-fg">
              <HugeiconsIcon icon={ShieldAlertIcon} strokeWidth={2} className="size-3.5 shrink-0" />
              <span>{handoffNote ?? t('handoffReceived', { n: handoffAlerts.length })}</span>
              <Button
                variant="ghost"
                size="sm"
                className="ms-auto h-6 px-2 text-12"
                onClick={() => { setHandoffAlerts([]); setHandoffNote(null) }}
              >
                {t('switchToEs')}
              </Button>
            </div>
          ) : (
            <div className="space-y-4">
              <Field label={t('fieldIndex')}>
                <IndexCombobox value={esIndex} onChange={setEsIndex} placeholder=".alerts-security.alerts-default" />
              </Field>
              <Field label={t('fieldQuery')}>
                <Textarea
                  value={esQuery}
                  onChange={(e) => setEsQuery(e.target.value)}
                  placeholder={ES_QUERY_PLACEHOLDER}
                  spellCheck={false}
                  className="min-h-[120px] font-mono text-12 leading-[1.55]"
                />
              </Field>
            </div>
          )}

          {/* WINDOW applies in both modes: in ES mode it bounds the pull; in
              paste mode it is the time window 深入调查 uses to gather context.
              It was hidden in paste mode, silently pinned at 60 min. */}
          <Field label={t('fieldWindow')}>
            <Input
              type="number"
              min={1}
              value={windowMinutes}
              onChange={(e) => setWindowMinutes(clampInt(e.target.value, 1, 7 * 24 * 60, 60))}
              className="max-w-[160px] tabular-nums"
            />
            <p className="text-12 leading-[1.5] text-muted-foreground">
              {handoffAlerts.length > 0
                ? t('windowHintHandoff')
                : t('windowHintEs')}
            </p>
          </Field>

          <div className="grid grid-cols-2 gap-4 pt-1">
            <Field label={t('fieldMaxAlerts')}>
              <Input
                type="number"
                min={1}
                max={100}
                value={maxAlerts}
                onChange={(e) => setMaxAlerts(clampInt(e.target.value, 1, 100, 100))}
                className="tabular-nums"
              />
            </Field>
            <Field label={t('fieldMaxClusters')}>
              <Input
                type="number"
                min={1}
                max={30}
                value={maxClustersToLlm}
                onChange={(e) => setMaxClustersToLlm(clampInt(e.target.value, 1, 30, 30))}
                className="tabular-nums"
              />
            </Field>
          </div>

          <div className="flex items-center gap-3 pt-2">
            <Button variant="default" className="rounded-full" onClick={onSubmit} disabled={loading}>
              <HugeiconsIcon icon={SparklesIcon} strokeWidth={2} className="size-3.5" />
              {loading ? t('running') : t('start')}
            </Button>
          </div>
        </FramePanel>
      </Frame>
      </section>

      {errorMsg && <ErrorBanner message={errorMsg} />}
      {truncateNote && (
        <Banner icon={<HugeiconsIcon icon={TriangleAlertIcon} strokeWidth={2} className="mt-0.5 size-4 shrink-0 text-destructive" />}>
          {truncateNote}
        </Banner>
      )}
      {loading && <LoadingSkeleton />}

      {result && !loading && (
        <section aria-label={t('secResult')} className="flex w-full min-w-0 flex-col gap-5">
          {!!result.rag_chunks_used && result.rag_chunks_used > 0 && (
            <div className="font-mono text-11 text-info">
              {t('ragUsed', { n: result.rag_chunks_used })}
            </div>
          )}
          {result.degraded && (
            <Banner icon={<HugeiconsIcon icon={AlertCircleIcon} strokeWidth={2} className="mt-0.5 size-4 shrink-0 text-destructive" />}>
              {result.degraded_reason || t('degradedFallback')}
            </Banner>
          )}
          {result.truncated && (
            <Banner icon={<HugeiconsIcon icon={TriangleAlertIcon} strokeWidth={2} className="mt-0.5 size-4 shrink-0 text-destructive" />}>
              {t('truncatedClusters', {
                n: Math.max(0, result.total_clusters - result.scored_clusters),
                max: maxClustersToLlm,
              })}
            </Banner>
          )}
          <div className="grid min-w-0 auto-rows-fr items-stretch gap-5 @4xl:grid-cols-3">
            <div className="min-w-0 @4xl:col-span-2">
              <SummaryStrip result={result} />
            </div>
            <MixDonut
              className="h-full"
              title={t('sevMix')}
              centerLabel={t('centerClusters')}
              slices={sevSlices}
              emptyText={t('sevMixEmpty')}
            />
          </div>
          <div className="flex flex-wrap items-center gap-2">
            <Button variant="outline" className="rounded-full" size="sm" onClick={onSaveRun}>
              <HugeiconsIcon icon={SaveIcon} strokeWidth={2} className="size-3.5" />
              {t('saveRun')}
            </Button>
            <Button variant="outline" className="rounded-full" size="sm" onClick={onExportCsv}>
              <HugeiconsIcon icon={Download01Icon} strokeWidth={2} className="size-3.5" />
              {t('exportCsv')}
            </Button>
            <PastRuns
              onLoad={(run) => {
                setResult(run.result)
                setSavedIndexMap(run.index_map ?? null)
              }}
            />
          </div>
          {syncWarn && (
            <Banner icon={<HugeiconsIcon icon={TriangleAlertIcon} strokeWidth={2} className="mt-0.5 size-4 shrink-0 text-destructive" />}>
              {syncWarn}
            </Banner>
          )}
          <div className="flex flex-wrap items-center justify-between gap-3">
            <div className="text-sm text-muted-foreground">
              {visibleClusters.length === sortedClusters.length
                ? t('countAll', { n: sortedClusters.length })
                : t('countFiltered', {
                    shown: visibleClusters.length,
                    total: sortedClusters.length,
                  })}
            </div>
            <div className="flex flex-wrap items-center gap-2">
              <Select value={sevFilter} onValueChange={(v) => setSevFilter(String(v))}>
                <SelectTrigger className="h-8! w-36" aria-label={t('filterBySeverity')}>
                  <SelectValue>
                    {(v) =>
                      String(v) === ALL
                        ? t('sevAll', { n: sortedClusters.length })
                        : t('sevOption', {
                            name: severityLabel(String(v)),
                            n: sevCounts[String(v)] ?? 0,
                          })
                    }
                  </SelectValue>
                </SelectTrigger>
                <SelectContent>
                  <SelectItem value={ALL}>{t('sevAll', { n: sortedClusters.length })}</SelectItem>
                  {(['critical', 'high', 'medium', 'low', 'info'] as const)
                    .filter((sv) => (sevCounts[sv] ?? 0) > 0)
                    .map((sv) => (
                      <SelectItem key={sv} value={sv}>
                        {t('sevOption', { name: severityLabel(sv), n: sevCounts[sv] ?? 0 })}
                      </SelectItem>
                    ))}
                </SelectContent>
              </Select>

              <Select value={statusFilter} onValueChange={(v) => setStatusFilter(String(v))}>
                <SelectTrigger className="h-8! w-36" aria-label={t('filterByStatus')}>
                  <SelectValue>
                    {(v) =>
                      String(v) === ALL ? t('statusAll') : statusLabel(String(v) as TriageStatus)
                    }
                  </SelectValue>
                </SelectTrigger>
                <SelectContent>
                  <SelectItem value={ALL}>{t('statusAll')}</SelectItem>
                  {STATUS_ORDER.map((st) => (
                    <SelectItem key={st} value={st}>{statusLabel(st)}</SelectItem>
                  ))}
                </SelectContent>
              </Select>
            </div>
          </div>

          <ClusterQueue
            clusters={visibleClusters}
            statuses={Object.fromEntries(visibleClusters.map((c) => [c.cluster_id, statuses[c.cluster_id] ?? getStatusLocal(c.cluster_id)]))}
            compareIds={compareIds}
            onChangeStatus={(c, next) => changeClusterStatus(c as Cluster, next)}
            onToggleCompare={toggleCompare}
            onInvestigate={(c) => openInvestigate(c as Cluster)}
            emptyText={t('noMatchingClusters')}
          />
        </section>
      )}

      {compareIds.length >= 1 && (
        <CompareTray
          clusters={sortedClusters.filter((c) => compareIds.includes(c.cluster_id))}
          statuses={statuses}
          onRemove={(id) => toggleCompare(id)}
          onClear={() => setCompareIds([])}
          onInvestigate={(c) => openInvestigate(c)}
        />
      )}

      <InvestigationDialog
        open={!!investigateAlert}
        onOpenChange={(v) => { if (!v) { setInvestigateAlert(null); setInvestigateCluster(null) } }}
        alert={investigateAlert}
        index={investigateIndex}
        windowMinutes={windowMinutes}
        dispo={
          investigateCluster
            ? statuses[investigateCluster.cluster_id] ?? getStatusLocal(investigateCluster.cluster_id)
            : null
        }
        onDispoChange={(s) => { if (investigateCluster) changeClusterStatus(investigateCluster, s) }}
      />
    </div>
  )
}

function Field({ label, children }: { label: string; children: ReactNode }) {
  // Real <label> so the eyebrow is programmatically tied to the control it wraps
  // (screen readers announce the input's name). Implicit association covers the
  // single-input Field uses here.
  return (
    <label className="block space-y-2">
      {/* 这些标签原来是 INDEX / MAX CLUSTERS TO LLM 这种全大写英文，全站只有这一页
          这么写；换成中文后等宽字体也一起去掉。 */}
      <Label className="text-xs text-muted-foreground">{label}</Label>
      {children}
    </label>
  )
}




/*
 * 结果概览，用 `@reui/dashboard-1` 的 `StatCards`（和平台体检同一个区块）。
 *
 * 原来是四格，第四格是 TRUNCATED YES/NO —— 截断本来就有自己的 banner 在上面
 * 说清楚「哪几个聚类没打分、怎么办」，一个 YES 重复不了那句话。截断这件事现在
 * 由「已评分」那格的图标底色说：黄的就是没打完。
 */
function SummaryStrip({ result }: { result: TriageResult }) {
  const t = useT(triageCopy)
  const urgent = result.clusters.filter((c) => {
    const s = normalizeSev(c.severity)
    return s === 'high' || s === 'critical'
  }).length

  const cards: StatCard[] = [
    {
      label: t('kpiTotalLabel', { n: result.total_clusters }),
      title: t('kpiTotal'),
      value: result.total_alerts.toLocaleString(),
      icon: <HugeiconsIcon icon={ShieldAlertIcon} strokeWidth={2} aria-hidden="true" />,
    },
    {
      label: t('kpiScoredLabel', { n: result.total_clusters }),
      title: t('kpiScored'),
      value: result.scored_clusters.toLocaleString(),
      // 截断过就是黄的：这个数字比总组数小是有原因的，颜色得说出来。
      tone: result.truncated ? 'warning' : undefined,
      icon: <HugeiconsIcon icon={SparklesIcon} strokeWidth={2} aria-hidden="true" />,
    },
    {
      label: t('kpiUrgentLabel', { n: result.clusters.length }),
      title: t('kpiUrgent'),
      value: String(urgent),
      tone: urgent > 0 ? 'destructive' : undefined,
      icon: <HugeiconsIcon icon={TriangleAlertIcon} strokeWidth={2} aria-hidden="true" />,
    },
  ]
  return <StatCards cards={cards} />
}

function Banner({ icon, children }: { icon: ReactNode; children: ReactNode }) {
  return (
    <Alert variant="warning">
      {icon}
      <AlertDescription>{children}</AlertDescription>
    </Alert>
  )
}

function ErrorBanner({ message }: { message: string }) {
  const help = classifyError(message)
  return (
    <Alert variant="destructive">
      <HugeiconsIcon icon={AlertCircleIcon} strokeWidth={2} className="size-4" />
      <AlertDescription>
        <div className="flex flex-col gap-1">
          <div className="break-words">{message}</div>
          {help.hint && (
            <div className="flex items-start gap-1 text-muted-foreground">
              <HugeiconsIcon icon={LightbulbIcon} strokeWidth={2} className="mt-0.5 size-3.5 shrink-0" />
              <span>{help.hint}</span>
            </div>
          )}
        </div>
      </AlertDescription>
    </Alert>
  )
}

const SEV_TONE: Record<Severity, 'sev-info' | 'sev-low' | 'sev-medium' | 'sev-high' | 'sev-critical'> = {
  info: 'sev-info',
  low: 'sev-low',
  medium: 'sev-medium',
  high: 'sev-high',
  critical: 'sev-critical',
}


function LoadingSkeleton() {
  const t = useT(triageCopy)
  const [secs, setSecs] = useState(0)
  const rootRef = useRef<HTMLDivElement>(null)
  useEffect(() => {
    // 表单比首屏高,这块进度在视口外 —— 冷启动验收时看起来像点了没反应。
    rootRef.current?.scrollIntoView({ behavior: 'smooth', block: 'start' })
    const t = setInterval(() => setSecs((s) => s + 1), 1000)
    return () => clearInterval(t)
  }, [])
  const slow = secs >= 30
  return (
    <div ref={rootRef} className="reveal flex w-full min-w-0 flex-col gap-3">
      <div role="status" className="flex items-center gap-2 px-1">
        <HugeiconsIcon icon={SparklesIcon} strokeWidth={2} className="size-3.5 animate-pulse text-info" />
        <span
          className={cn(
            'font-mono text-12 tabular-nums',
            slow ? 'text-destructive' : 'text-muted-foreground',
          )}
        >
          {t('loadingLine', { secs })}
          {slow ? t('loadingSlowHint') : ''}
        </span>
      </div>
      {[0, 1, 2].map((i) => (
        <Frame key={i} dense spacing="sm">
          <FramePanel className="flex flex-col gap-3 bg-card shadow-none!">
            <Skeleton className="h-4 w-2/5 rounded bg-secondary" />
            <Skeleton className="h-3 w-3/4 rounded bg-secondary" />
            <Skeleton className="h-3 w-1/2 rounded bg-secondary" />
          </FramePanel>
        </Frame>
      ))}
    </div>
  )
}

/** Synthesise an alert doc from a cluster summary so an investigation can
 * gather ES context around the subject. Shared by the card + compare tray. */
function clusterToAlert(c: Cluster): Record<string, unknown> {
  return {
    ...expandPath(c.subject_field, c.subject_value),
    rule: { id: c.rule_id, name: c.attack_intent },
    'kibana.alert.rule.name': c.attack_intent,
    event: { action: c.attack_intent },
  }
}

function CompareTray({
  clusters,
  statuses,
  onRemove,
  onClear,
  onInvestigate,
}: {
  clusters: Cluster[]
  statuses: Record<string, TriageStatus>
  onRemove: (id: string) => void
  onClear: () => void
  onInvestigate: (c: Cluster) => void
}) {
  const t = useT(triageCopy)
  return (
    <section aria-label={t('secCompare')} className="w-full min-w-0">
      <div className="mb-2 flex items-center justify-between">
        <span className="font-mono text-xs text-muted-foreground">
          {t('compareHeading', { n: clusters.length })}
        </span>
        <Button variant="ghost" size="sm" onClick={onClear}>{t('clearCompare')}</Button>
      </div>
      {/* 四边都留 4px：卡片的边框是 box-shadow 画的 1px 环，落在盒子外面，
          容器只给 pb-2 的话上边和首尾两张卡的侧边会被 overflow 裁掉 ——
          和告警流那处是同一个毛病。 */}
      <div className="flex gap-3 overflow-x-auto p-1 pb-2">
        {clusters.map((c) => {
          const sev = normalizeSev(c.severity)
          const status = statuses[c.cluster_id] ?? 'open'
          return (
            <div
              key={c.cluster_id}
              className="flex w-[280px] shrink-0 flex-col gap-2 rounded-xl bg-card p-3 [box-shadow:var(--shadow-ring-light)]"
            >
              <div className="flex items-center justify-between gap-2">
                <div className="flex items-center gap-2">
                  <span className="text-16 font-semibold tabular-nums tracking-[-0.5px] text-foreground">
                    #{c.priority_rank}
                  </span>
                  <Pill tone={SEV_TONE[sev]}>{severityLabel(sev)}</Pill>
                </div>
                <button
                  onClick={() => onRemove(c.cluster_id)}
                  title={t('removeFromCompare')}
                  className="inline-flex size-6 items-center justify-center rounded-md text-fg-faint transition-colors hover:text-destructive"
                >
                  <HugeiconsIcon icon={Cancel01Icon} strokeWidth={2} className="size-3.5" />
                </button>
              </div>
              <div className="text-13 font-medium text-foreground">{c.attack_intent || c.rule_id}</div>
              <code
                className="block truncate font-mono text-11 text-muted-foreground"
                title={`${c.subject_field}=${c.subject_value}`}
              >
                {c.subject_field}=<span className="text-code-blue">{c.subject_value}</span>
              </code>
              <div className="flex items-center gap-2 font-mono text-11 text-muted-foreground">
                <span className="tabular-nums">
                  <strong className="text-foreground">{c.count}</strong> alerts
                </span>
                <span>·</span>
                <span>{statusLabel(status)}</span>
              </div>
              <p className="line-clamp-4 text-12 leading-[1.5] text-fg-strong">
                {c.recommendation}
              </p>
              <button
                onClick={() => onInvestigate(c)}
                className="mt-auto inline-flex items-center justify-center gap-1.5 rounded-md py-1.5 text-12 font-medium text-muted-foreground [box-shadow:var(--shadow-ring-light)] transition-colors hover:text-info"
              >
                <HugeiconsIcon icon={SparklesIcon} strokeWidth={2} className="size-3.5" />
                {t('investigate')}
              </button>
            </div>
          )
        })}
      </div>
    </section>
  )
}

function clustersToCsv(clusters: Cluster[], statuses: Record<string, TriageStatus>): string {
  // Reuse the shared, formula-injection-hardened cell escaper — the subject /
  // attack_intent / recommendation columns carry model- and data-derived text
  // (e.g. an attacker-controlled username) that must not execute in Excel/WPS.
  const esc = escapeCell
  const cols = [
    'priority_rank', 'severity', 'attack_intent', 'subject', 'count',
    'first_seen', 'last_seen', 'status', 'is_likely_fp', 'recommendation',
  ]
  const lines = [cols.join(',')]
  for (const c of clusters) {
    lines.push([
      c.priority_rank, c.severity, c.attack_intent,
      `${c.subject_field}=${c.subject_value}`, c.count,
      c.first_seen ?? '', c.last_seen ?? '',
      statuses[c.cluster_id] ?? 'open', c.is_likely_fp, c.recommendation,
    ].map(esc).join(','))
  }
  return '﻿' + lines.join('\n') + '\n'
}

interface SavedRun {
  id: string
  created_at: string
  note: string
  result: TriageResult
  /** cluster_id → source index, captured at save time (added later; may be absent
   *  on older saved runs, which then fall back to the alerts-default index). */
  index_map?: Record<string, string>
}

function PastRuns({ onLoad }: { onLoad: (r: SavedRun) => void }) {
  const t = useT(triageCopy)
  const c = useT(commonCopy)
  const [open, setOpen] = useState(false)
  const [runs, setRuns] = useState<Array<{ key: string; value: SavedRun }> | null>(null)
  // A failed fetch must NOT render as "还没有保存的分诊" — that reads as "your
  // saved triage runs are gone" and offers no retry.
  const [error, setError] = useState<string | null>(null)

  async function load() {
    setError(null)
    try {
      const { items } = await api.stateList<SavedRun>('triage_result')
      setRuns(items.filter((it) => it.value && it.value.result))
    } catch (e) {
      setError(e instanceof Error ? e.message : t('errLoadRuns'))
    }
  }

  return (
    <Popover
      open={open}
      onOpenChange={(next) => {
        setOpen(next)
        if (next && runs === null) void load()
      }}
    >
      <PopoverTrigger render={<Button variant="outline" className="rounded-full" size="sm" />}>
        <HugeiconsIcon icon={HistoryIcon} strokeWidth={2} className="size-3.5" />
        {t('pastRuns')}
      </PopoverTrigger>
      <PopoverContent
        align="start"
        sideOffset={6}
        className={cn(
          'max-h-[360px] w-[320px] gap-0 overflow-auto p-1.5 ring-0',
          'rounded-lg bg-card [box-shadow:var(--shadow-pop)]',
        )}
      >
        {error ? (
          <div className="px-3 py-4 text-center text-12 text-destructive">
            <div className="mb-2">{t('loadFailed', { err: error })}</div>
            <button type="button" onClick={() => void load()} className="underline underline-offset-2 hover:opacity-80">
              {c('retry')}
            </button>
          </div>
        ) : runs === null ? (
          <div className="px-3 py-4 text-center text-12 text-muted-foreground">{c('loading')}…</div>
        ) : runs.length === 0 ? (
          <div className="px-3 py-4 text-center text-12 text-fg-faint">{t('noSavedRuns')}</div>
        ) : (
          runs.map((r) => (
            <button
              key={r.key}
              type="button"
              onClick={() => {
                onLoad(r.value)
                setOpen(false)
              }}
              className="block w-full rounded-md px-2.5 py-2 text-left transition-colors hover:bg-accent"
            >
              <div className="truncate text-13 text-foreground">{r.value.note || t('noNote')}</div>
              <div className="font-mono text-11 text-muted-foreground">
                {(r.value.created_at || '').slice(0, 19).replace('T', ' ')} ·{' '}
                {r.value.result?.total_clusters ?? '?'} clusters
              </div>
            </button>
          ))
        )}
      </PopoverContent>
    </Popover>
  )
}

function clampInt(raw: string, min: number, max: number, fallback: number): number {
  const n = Number.parseInt(raw, 10)
  if (Number.isNaN(n)) return fallback
  if (n < min) return min
  if (n > max) return max
  return n
}

function normalizeSev(s: string): Severity {
  const v = (s || '').toLowerCase()
  if (v === 'critical' || v === 'high' || v === 'medium' || v === 'low' || v === 'info') return v
  return 'info'
}

