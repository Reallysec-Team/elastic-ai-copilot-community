import { useEffect, useState, type ReactNode } from 'react'
import { useNavigate } from '@tanstack/react-router'
import { HugeiconsIcon } from '@hugeicons/react'
import { AlertCircleIcon, BellRingIcon, CheckIcon, ChevronDownIcon, ChevronRightIcon, Cancel01Icon, CopyIcon, Download01Icon, FileTextIcon, Loading03Icon, Share01Icon, ShieldAlertIcon, ShieldCheckIcon } from '@hugeicons/core-free-icons'
import { GatedButton, useGate } from '@/components/gated-button'
import { api, type ApiError, type InvestigateResponse } from '@/lib/api'
import { streamInvestigate, type InvestigateStageEvent } from '@/lib/streamingClient'
import { Dialog, DialogContent, DialogHeader, DialogFooter, DialogTitle } from '@/components/ui/dialog'
import { Button } from '@/components/ui/button'
import { NavDropdownAction, NavDropdownGeneric } from '@/components/NavDropdown'
import { LabelMono, Pill } from '@/components/ui/Pill'
import { Badge } from '@/components/reui/badge'
import { Frame, FrameDescription, FrameHeader, FramePanel, FrameTitle } from '@/components/reui/frame'
import {
  Timeline, TimelineContent, TimelineDate, TimelineHeader, TimelineIndicator, TimelineItem,
  TimelineSeparator, TimelineTitle,
} from '@/components/reui/timeline'
import { Collapsible, CollapsibleContent, CollapsibleTrigger } from '@/components/ui/collapsible'
import { setHandoff } from '@/lib/handoff'
import {
  getStatusLocal,
  loadStatuses,
  saveStatus,
  statusLabel,
  STATUS_ORDER,
  type TriageStatus,
} from '@/lib/triageStatus'
import { useT, translate } from '@/lib/i18n'
import { cn, formatBytes } from '@/lib/utils'
import { commonCopy } from '@/locales/common'
import { dialogsCopy } from '@/locales/dialogs'
import { severityLabel } from '@/lib/severity'

/*
 * InvestigationDialog — DEVELOP workflow color (blue), wider 840px frame.
 * Owns the investigate fetch and the optional incident-report export.
 */

type Severity = 'info' | 'low' | 'medium' | 'high' | 'critical'
type Confidence = 'low' | 'medium' | 'high'
type ReportPhase = 'idle' | 'pending' | 'done' | 'error'

export interface InvestigationDialogProps {
  open: boolean
  onOpenChange: (v: boolean) => void
  alert: Record<string, unknown> | null
  index: string
  windowMinutes?: number
  /* Disposition, delegated to the caller.
   *
   * Left alone, the dialog keyed the mark by `inv:<index>:<subject>` in the
   * triage namespace — a THIRD key space that neither 分诊 (keyed by cluster_id)
   * nor 实时告警 (keyed by alert_id, and a different server kind entirely) ever
   * reads. Marking 已处置 here therefore showed up nowhere, while the surface it
   * was opened from still listed the item as 未处置.
   *
   * A caller that owns a disposition for this subject passes both props; the
   * dialog then reads and writes THAT one. 查询页 (ChatPage) — an arbitrary ES doc with
   * no list behind it — passes neither and keeps the standalone `inv:` key. */
  dispo?: TriageStatus | null
  onDispoChange?: (next: TriageStatus) => void
}

/**
 * 弹窗标题：优先用模型给的告警类型，退回到告警文档里的规则名，再退回一句中文。
 * 后端把缺失的 alert_type 兜成 "unknown"，所以那个值也要当成「没有」。
 */
export function alertTitle(
  alertType: string | null | undefined,
  doc: Record<string, unknown> | null,
): string {
  const t = (alertType ?? '').trim()
  if (t && t.toLowerCase() !== 'unknown') return t
  const src = (doc?._source ?? doc) as Record<string, unknown> | undefined
  const candidates = [
    src?.['kibana.alert.rule.name'],
    (src?.rule as Record<string, unknown> | undefined)?.name,
    src?.rule_name,
  ]
  for (const c of candidates) {
    if (typeof c === 'string' && c.trim()) return c.trim()
  }
  return translate(dialogsCopy, 'invTitle')
}

export function InvestigationDialog({
  open,
  onOpenChange,
  alert: alertDoc,
  index,
  windowMinutes,
  dispo: dispoProp,
  onDispoChange,
}: InvestigationDialogProps) {
  const t = useT(dialogsCopy)
  const c = useT(commonCopy)
  const feishuGate = useGate('write')
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const [data, setData] = useState<InvestigateResponse | null>(null)
  const [stages, setStages] = useState<InvestigateStageEvent[]>([])
  const [reqKey, setReqKey] = useState(0)
  const [reportPhase, setReportPhase] = useState<ReportPhase>('idle')
  const [reportSize, setReportSize] = useState<number>(0)
  const [reportError, setReportError] = useState<string | null>(null)
  const [copied, setCopied] = useState(false)
  const [copyError, setCopyError] = useState<string | null>(null)
  const navigate = useNavigate()
  // 推送结论 (M2) — dispatch to Feishu targets.
  const [notifyState, setNotifyState] = useState<'idle' | 'sending' | 'sent' | 'none' | 'error'>('idle')
  const [notifyMsg, setNotifyMsg] = useState<string | null>(null)
  // Disposition (L2). Owned by the caller when it has a list to keep in sync
  // (see the props doc); otherwise local, keyed by the investigated subject.
  const delegated = !!onDispoChange
  const [localDispo, setLocalDispo] = useState<TriageStatus | null>(null)
  const dispo = delegated ? dispoProp ?? null : localDispo
  const dispoKey = data ? investigationKey(index, data) : null
  // 发送报告到飞书 (cloud doc + group).
  const [feishuState, setFeishuState] = useState<'idle' | 'sending' | 'done'>('idle')
  const [feishuMsg, setFeishuMsg] = useState<string | null>(null)

  useEffect(() => {
    // Always reset to loading first so a re-open / target change never renders the
    // previous alert's result on the first frame. Done unconditionally (even when
    // closed) so the next open starts clean.
    // eslint-disable-next-line react-hooks/set-state-in-effect -- reset when the dialog opens / target changes
    setLoading(true); setError(null); setData(null); setStages([])
    setReportPhase('idle'); setReportSize(0); setReportError(null)
    setNotifyState('idle'); setNotifyMsg(null); setLocalDispo(null)
    setFeishuState('idle'); setFeishuMsg(null)
    if (!open || !alertDoc) { setLoading(false); return }
    let done = false
    // Consume the staged-progress SSE stream: each `stage` marker upserts the
    // live checklist (keyed so active→done replaces in place); the terminal
    // `result` frame lands the full investigation.
    const ctrl = streamInvestigate(
      { index, alert: alertDoc, window_minutes: windowMinutes },
      {
        onStage: (e) =>
          setStages((prev) => {
            const i = prev.findIndex((s) => s.key === e.key)
            if (i === -1) return [...prev, e]
            const next = prev.slice(); next[i] = e; return next
          }),
        onResult: (r) => { done = true; setData(r); setLoading(false) },
        onError: (msg) => { done = true; setError(msg || t('invErrInvestigate')); setLoading(false) },
      },
    )
    return () => { if (!done) ctrl.abort() }
  }, [open, alertDoc, index, windowMinutes, reqKey, t])

  // Load any existing team disposition for the investigated subject. Skipped
  // when the caller owns it — its value is already the authoritative one.
  useEffect(() => {
    if (delegated || !dispoKey) return
    setLocalDispo(getStatusLocal(dispoKey)) // instant paint from local cache
    void loadStatuses().then((all) => { if (all[dispoKey]) setLocalDispo(all[dispoKey]) })
  }, [delegated, dispoKey])

  function onToDetectionRule() {
    if (!data) return
    // Seed the detection-rule copilot with the confirmed threat so the analyst
    // gets a Kibana rule to catch it next time — the exit the dialog was missing.
    const subject = data.affected_assets?.[0]
    const subjectHint = subject
      ? t('invSubjectHint', { type: subject.type, id: subject.id })
      : ''
    setHandoff('detection-rule', {
      question: t('invDetectionQuestion', {
        alertType: data.alert_type,
        subjectHint,
        summary: data.summary ?? '',
      }).trim(),
      index,
    })
    onOpenChange(false)
    navigate({ to: '/detection-rules' })
  }

  async function onNotify() {
    if (!data) return
    setNotifyState('sending'); setNotifyMsg(null)
    try {
      const r = await api.investigateNotify(data as unknown as Record<string, unknown>)
      if (r.dispatched > 0) {
        setNotifyState('sent'); setNotifyMsg(t('invNotifyPushed', { n: r.dispatched }))
      } else {
        setNotifyState('none')
        setNotifyMsg(t('invNotifyNoChannel'))
      }
    } catch (e) {
      setNotifyState('error')
      setNotifyMsg((e as ApiError).message || t('invNotifyFailed'))
    }
  }

  function onChangeDispo(next: TriageStatus) {
    const prev = dispo
    if (delegated) {
      onDispoChange!(next)
    } else {
      if (!dispoKey) return
      setLocalDispo(next)
      void saveStatus(dispoKey, next)
    }
    // 升级 → 询问是否推送值班；复用「推送结论」派发（同一飞书渠道）。
    if (next === 'escalated' && prev !== 'escalated' && notifyState !== 'sending' && notifyState !== 'sent') {
      if (window.confirm(t('invConfirmEscalate'))) void onNotify()
    }
  }

  async function onSendReportToFeishu() {
    if (!data || !alertDoc) return
    setFeishuState('sending'); setFeishuMsg(null)
    try {
      const r = await api.reportIncident({
        index, alert: alertDoc,
        investigation: data as unknown as Record<string, unknown>,
        include_evidence: true,
      })
      // One composed action: create the shareable doc AND announce its link to
      // the group (the backend puts doc_url inside the group card), so the two
      // halves read as a single "publish the report" intent rather than two
      // separate noises. Re-click is guarded below (button locks after success).
      const res = await api.reportToFeishu({
        title: t('invReportTitle', { alertType: data.alert_type ?? '' }).trim(),
        markdown: r.markdown ?? '',
        severity: data.severity,
        to_doc: true,
        to_group: true,
      })
      const parts: string[] = []
      if (res.doc_url) parts.push(t('invFeishuDoc', { url: res.doc_url }))
      if (res.dispatched > 0) parts.push(t('invFeishuAnnounced', { n: res.dispatched }))
      if (res.errors?.length) parts.push(res.errors.join('；'))
      setFeishuMsg(parts.join(' · ') || t('invFeishuSubmitted'))
    } catch (e) {
      setFeishuMsg((e as ApiError).message || t('invFeishuFailed'))
    } finally {
      setFeishuState('done')
    }
  }

  async function onExportReport() {
    if (!data || !alertDoc) return
    setReportPhase('pending'); setReportError(null)
    try {
      const r = await api.reportIncident({
        index,
        alert: alertDoc,
        investigation: data as unknown as Record<string, unknown>,
        include_evidence: true,
      })
      const md = r.markdown ?? ''
      const blob = new Blob([md], { type: 'text/markdown;charset=utf-8' })
      const url = URL.createObjectURL(blob)
      const a = document.createElement('a')
      const ts = new Date().toISOString().replace(/[:.]/g, '-').slice(0, 19)
      const safeType = (data.alert_type || 'incident').replace(/[^a-zA-Z0-9-_]+/g, '-')
      a.href = url
      a.download = `incident-report-${safeType}-${ts}.md`
      document.body.appendChild(a); a.click(); document.body.removeChild(a)
      URL.revokeObjectURL(url)
      setReportSize(blob.size); setReportPhase('done')
    } catch (e) {
      const err = e as ApiError
      setReportError(err.message || t('invErrExport'))
      setReportPhase('error')
    }
  }

  async function onCopyReport() {
    if (!data || !alertDoc) return
    setCopyError(null)
    try {
      const r = await api.reportIncident({
        index,
        alert: alertDoc,
        investigation: data as unknown as Record<string, unknown>,
        include_evidence: true,
      })
      if (!navigator.clipboard?.writeText) throw new Error(t('clipboardUnsupported'))
      await navigator.clipboard.writeText(r.markdown ?? '')
      setCopied(true)
      setTimeout(() => setCopied(false), 1500)
    } catch (e) {
      const err = e as ApiError
      setCopyError(err.message || t('copyFailed'))
      setTimeout(() => setCopyError(null), 3000)
    }
  }

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent className="flex flex-col gap-0 overflow-hidden p-0 sm:max-w-[840px] max-h-[86vh]">
        <DialogHeader className="flex-row items-start justify-between gap-4 border-b px-6 pt-5 pb-4">
          <div className="flex flex-col gap-1">
            <span className="label-mono">{t('invTitle')}</span>
            {/* 模型没给 alert_type 时后端兜的是字符串 "unknown"，于是弹窗标题就是
                大写的 unknown —— 而这条告警叫什么我们本来就知道（规则名就在传进来
                的 alertDoc 里）。实测过一次：ES 里查不到对应原始事件时模型会略过
                alert_type，标题直接变成 unknown。 */}
            <DialogTitle className="text-base font-semibold">
              {alertTitle(data?.alert_type, alertDoc)}
            </DialogTitle>
          </div>
          <div className="flex shrink-0 items-center gap-2 pt-1 pr-8">{
            <>
              {data?.severity && <Pill tone={sevTone(data.severity)}>{severityLabel(data.severity)}</Pill>}
              {data?.is_likely_false_positive && <Pill tone="sev-high">{t('invLikelyFp')}</Pill>}
              {data?.confidence && (
                <Pill tone={confTone(data.confidence)}>
                  <span className="label-mono mr-1 opacity-70">{t('confidence')}</span>
                  {data.confidence}
                </Pill>
              )}
              {data?.agentic && (
                <Pill tone="sev-info">
                  <span className="label-mono mr-1 opacity-70">{t('invAgenticRounds')}</span>
                  {t('invRounds', { n: data.agentic_steps ?? 0 })}
                </Pill>
              )}
              {typeof data?.context_count === 'number' && (
                <span className="font-mono text-11 text-muted-foreground">
                  {t('invContextCount', { n: data.context_count })}
                </span>
              )}
              {!!data?.rag_chunks_used && data.rag_chunks_used > 0 && (
                <span className="font-mono text-11 text-info">
                  {t('invRagCount', { n: data.rag_chunks_used })}
                </span>
              )}
            </>
          }</div>
        </DialogHeader>
        <div className="flex-1 min-h-0 space-y-4 overflow-auto px-6 py-5">
          {loading && <LoadingBlock stages={stages} />}
          {error && (
            <ErrorBlock
              message={error}
              onRetry={() => { setError(null); setReqKey((n) => n + 1) }}
            />
          )}
          {!loading && !error && data && (
            <>
              <InvestigationContent data={data} />
              <InvestigationNextSteps
                dispo={dispo}
                onChangeDispo={onChangeDispo}
                onToDetectionRule={onToDetectionRule}
                onNotify={onNotify}
                notifyState={notifyState}
                notifyMsg={notifyMsg}
              />
            </>
          )}
        </div>
        <DialogFooter className="mx-0 mb-0 px-6 py-4">
          {reportPhase === 'pending' && (
            <span className="mr-auto text-12 text-fg-muted">{t('invGeneratingReport')}</span>
          )}
          {reportPhase === 'done' && (
            <span className="mr-auto text-12 text-success-foreground">
              {t('invDownloaded', { size: formatBytes(reportSize) })}
            </span>
          )}
          {reportPhase === 'error' && reportError && (
            <span className="mr-auto truncate text-12 text-destructive">{reportError}</span>
          )}
          {copyError && (
            <span className="mr-auto truncate text-12 text-destructive">{copyError}</span>
          )}
          {feishuMsg && !copyError && (
            <span className="mr-auto truncate text-12 text-fg-muted" title={feishuMsg}>{feishuMsg}</span>
          )}
          <Button variant="outline" onClick={() => onOpenChange(false)}>{c('close')}</Button>
          <NavDropdownGeneric
            align="end"
            trigger={
              <Button variant="default" className="rounded-full" disabled={!data || reportPhase === 'pending'}>
                {reportPhase === 'pending' || feishuState === 'sending' ? (
                  <HugeiconsIcon icon={Loading03Icon} strokeWidth={2} className="size-3.5 animate-spin" />
                ) : (
                  <HugeiconsIcon icon={Share01Icon} strokeWidth={2} className="size-3.5" />
                )}
                {t('exportShare')}
                <HugeiconsIcon icon={ChevronDownIcon} strokeWidth={2} className="size-3.5 opacity-70" />
              </Button>
            }
          >
            <NavDropdownAction
              onSelect={onCopyReport}
              disabled={!data || reportPhase === 'pending'}
              icon={copied ? <HugeiconsIcon icon={CheckIcon} strokeWidth={2} className="size-4" /> : <HugeiconsIcon icon={CopyIcon} strokeWidth={2} className="size-4" />}
              label={copied ? t('copied') : t('copyMarkdown')}
            />
            <NavDropdownAction
              onSelect={onExportReport}
              disabled={!data || reportPhase === 'pending'}
              icon={reportPhase === 'pending' ? <HugeiconsIcon icon={Loading03Icon} strokeWidth={2} className="size-4 animate-spin" /> : <HugeiconsIcon icon={Download01Icon} strokeWidth={2} className="size-4" />}
              label={t('invExportReport')}
            />
            <NavDropdownAction
              onSelect={onSendReportToFeishu}
              disabled={!data || !feishuGate.allowed || feishuState === 'sending' || feishuState === 'done'}
              icon={
                feishuState === 'sending' ? <HugeiconsIcon icon={Loading03Icon} strokeWidth={2} className="size-4 animate-spin" />
                  : feishuState === 'done' ? <HugeiconsIcon icon={CheckIcon} strokeWidth={2} className="size-4" />
                  : <HugeiconsIcon icon={FileTextIcon} strokeWidth={2} className="size-4" />
              }
              label={feishuState === 'done' ? t('sentToFeishu') : t('sendToFeishu')}
              hint={feishuGate.allowed ? t('feishuHint') : feishuGate.reason}
            />
          </NavDropdownGeneric>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  )
}

/** Stable disposition/handoff key for an investigated subject: the primary
 * affected asset if the model named one, else the alert type. Same entity →
 * same key, so a mark here reconciles with the triage board. */
function investigationKey(index: string, data: InvestigateResponse): string {
  const a = data.affected_assets?.[0]
  const subject = a ? `${a.type}:${a.id}` : data.alert_type || 'unknown'
  return `inv:${index}:${subject}`
}

/* The exits the investigation dialog was missing (audit M2/L2): mark a
 * disposition (team-shared), turn the confirmed threat into a detection rule,
 * or push the conclusion to the team — so 调查 → 报告 is no longer a dead-end. */
function InvestigationNextSteps({
  dispo,
  onChangeDispo,
  onToDetectionRule,
  onNotify,
  notifyState,
  notifyMsg,
}: {
  dispo: TriageStatus | null
  onChangeDispo: (s: TriageStatus) => void
  onToDetectionRule: () => void
  onNotify: () => void
  notifyState: 'idle' | 'sending' | 'sent' | 'none' | 'error'
  notifyMsg: string | null
}) {
  const t = useT(dialogsCopy)

  return (
    <section className="mt-6 space-y-3 rounded-xl bg-accent px-4 py-3.5 [box-shadow:var(--shadow-ring-light)]">
      <div className="flex flex-wrap items-center gap-x-2 gap-y-2">
        <LabelMono>{t('invDisposition')}</LabelMono>
        {STATUS_ORDER.map((s) => {
          const on = dispo === s
          return (
            <button
              key={s}
              type="button"
              onClick={() => onChangeDispo(s)}
              aria-pressed={on}
              className={cn(
                'rounded-full px-2.5 py-1 text-12 transition-colors',
                on
                  ? 'bg-foreground font-semibold text-primary-foreground'
                  : 'font-medium text-muted-foreground [box-shadow:var(--shadow-ring-light)] hover:text-foreground',
              )}
            >
              {statusLabel(s)}
            </button>
          )
        })}
      </div>
      <div className="flex flex-wrap items-center gap-2 [box-shadow:0_1px_0_var(--color-line)_inset] pt-3">
        <Button variant="outline" className="rounded-full" size="sm" onClick={onToDetectionRule} title={t('invToDetectionRuleTitle')}>
          <HugeiconsIcon icon={ShieldCheckIcon} strokeWidth={2} className="size-3.5 text-preview" />
          {t('invToDetectionRule')}
        </Button>
        <GatedButton
          gate="write"
          variant="outline" className="rounded-full"
          size="sm"
          onClick={onNotify}
          disabled={notifyState === 'sending' || notifyState === 'sent'}
          title={t('invNotifyTitle')}
        >
          {notifyState === 'sending' ? <HugeiconsIcon icon={Loading03Icon} strokeWidth={2} className="size-3.5 animate-spin" /> : <HugeiconsIcon icon={BellRingIcon} strokeWidth={2} className="size-3.5" />}
          {notifyState === 'sent' ? t('invNotified') : t('invNotify')}
        </GatedButton>
        {notifyMsg && (
          <span
            className={cn(
              'text-12',
              notifyState === 'sent' ? 'text-success-foreground'
                : notifyState === 'error' ? 'text-destructive'
                : 'text-fg-muted',
            )}
          >
            {notifyMsg}
          </span>
        )}
      </div>
    </section>
  )
}

export function InvestigationContent({ data }: { data: InvestigateResponse }) {
  const t = useT(dialogsCopy)
  return (
    <div className="space-y-6">
      {data.degraded && <DegradedBanner />}

      {data.summary && (
        <p className="text-16 text-foreground" style={{ lineHeight: 1.6 }}>{data.summary}</p>
      )}

      {data.is_likely_false_positive && data.false_positive_reason && (
        <Section title={t('invSecFp')}>
          <div className={cn('rounded-lg bg-accent px-4 py-3', '[box-shadow:var(--shadow-ring-light)]')}>
            <div className="mb-1 flex items-center gap-1.5">
              <HugeiconsIcon icon={ShieldAlertIcon} strokeWidth={2} className="size-3.5 text-muted-foreground" />
              <span className="label-mono">{t('invSecFp')}</span>
            </div>
            <p className="text-14 leading-[1.55] text-fg-strong">{data.false_positive_reason}</p>
          </div>
        </Section>
      )}

      {data.timeline?.length > 0 && (
        <Section title={t('invSecTimeline')}>
          {/* 事件时间线照 solution-agents-3 的 Step Trace：竖线 + 圆点 + 等宽时间 + 事件。 */}
          <Timeline defaultValue={data.timeline.length}>
            {data.timeline.map((ev, i) => (
              <TimelineItem key={i} step={i + 1} className="group-data-[orientation=vertical]/timeline:not-last:pb-4">
                <TimelineHeader>
                  <TimelineSeparator className="bg-border group-data-[orientation=vertical]/timeline:h-[calc(100%-1rem-0.5rem)] group-data-[orientation=vertical]/timeline:translate-y-5" />
                  <TimelineDate className="font-mono text-12 text-muted-foreground">{ev.time}</TimelineDate>
                  <TimelineIndicator className="size-2.5 border-none bg-primary group-data-[orientation=vertical]/timeline:-left-6 group-data-[orientation=vertical]/timeline:top-1.5" />
                </TimelineHeader>
                <TimelineContent className="text-14 leading-[1.55] text-foreground">{ev.event}</TimelineContent>
              </TimelineItem>
            ))}
          </Timeline>
        </Section>
      )}

      {data.attack_chain?.length > 0 && (
        <Section title={t('invSecKillChain')}>
          <ul className="space-y-2">
            {data.attack_chain.map((step, i) => (
              <li key={i} className="flex items-start gap-2 text-14 leading-[1.55]">
                <span className="mt-[7px] block size-1.5 shrink-0 rounded-full bg-info" aria-hidden="true" />
                <span>
                  <span className="font-medium text-develop">{step.phase}</span>
                  {step.evidence && <><span className="text-fg-faint"> · </span><span className="text-fg-strong">{step.evidence}</span></>}
                </span>
              </li>
            ))}
          </ul>
        </Section>
      )}

      {data.mitre_techniques?.length > 0 && (
        <Section title="MITRE ATT&CK">
          <div className={cn('overflow-hidden rounded-lg bg-card', '[box-shadow:var(--shadow-ring-light)]')}>
            <table className="w-full text-left">
              <thead>
                <tr className="[box-shadow:0_1px_0_var(--color-line)_inset]">
                  <th scope="col" className="px-3 py-2 align-middle"><LabelMono>ID</LabelMono></th>
                  <th scope="col" className="px-3 py-2 align-middle"><LabelMono>{t('invColTechnique')}</LabelMono></th>
                  <th scope="col" className="px-3 py-2 align-middle"><LabelMono>{t('invColEvidence')}</LabelMono></th>
                </tr>
              </thead>
              <tbody>
                {data.mitre_techniques.map((m, i) => (
                  <tr key={`${m.id}-${i}`} className={cn('align-top', i > 0 && '[box-shadow:0_1px_0_var(--color-line)_inset]')}>
                    <td className="px-3 py-2"><Pill tone="gray"><code className="font-mono text-11">{m.id}</code></Pill></td>
                    <td className="px-3 py-2 text-13 text-foreground">{m.name}</td>
                    <td className="px-3 py-2 text-13 leading-[1.5] text-fg-muted">{m.evidence}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </Section>
      )}

      {data.affected_assets?.length > 0 && (
        <Section title={t('invSecAssets')}>
          <div className="flex flex-wrap gap-1.5">
            {data.affected_assets.map((a, i) => (
              <Pill key={`${a.type}-${a.id}-${i}`} tone="gray">
                <code className="font-mono text-11">{a.type}:{a.id}</code>
              </Pill>
            ))}
          </div>
        </Section>
      )}

      {data.recommended_actions?.length > 0 && (
        <Section title={t('invSecRecommendation')}>
          <ol className="space-y-1.5">
            {data.recommended_actions.map((s, i) => (
              <li key={i} className="flex items-start gap-3 text-14 leading-[1.55] text-foreground">
                <span className="mt-[1px] inline-flex size-5 shrink-0 items-center justify-center rounded-full bg-secondary font-mono text-11 text-fg-muted">{i + 1}</span>
                <span>{s}</span>
              </li>
            ))}
          </ol>
        </Section>
      )}

      {data.agentic && data.tool_trace && data.tool_trace.length > 0 && (
        <TraceSection trace={data.tool_trace} />
      )}
    </div>
  )
}

function TraceSection({
  trace,
}: {
  trace: NonNullable<InvestigateResponse['tool_trace']>
}) {
  const t = useT(dialogsCopy)
  const failed = trace.filter((s) => s.error).length
  /* agentic 的工具调用轨迹照 solution-agents-3 的 Step Trace：Frame 卡头写「N 步，M 步失败」，
     面板里一条 Timeline，每步一个节点（成功 = 主色勾，失败 = 红叉），节点下面一个可折叠的
     小 Frame 装工具名 / 索引 / 命中数或错误；失败的默认展开。 */
  return (
    <Frame stacked spacing="sm" className="w-full">
      <FrameHeader>
        <div className="flex min-w-0 flex-col gap-0.5">
          <FrameTitle>{t('invSecAgentic')}</FrameTitle>
          <FrameDescription className="text-xs">
            {failed > 0 ? t('invTraceFailed', { n: trace.length, f: failed }) : t('invTraceOk', { n: trace.length })}
          </FrameDescription>
        </div>
      </FrameHeader>
      <FramePanel>
        <Timeline defaultValue={trace.length}>
          {trace.map((step, i) => {
            const idx = parseTraceIndex(step.args)
            return (
              <TimelineItem key={i} step={i + 1}>
                <TimelineHeader>
                  <TimelineSeparator className="bg-border group-data-[orientation=vertical]/timeline:h-[calc(100%-1.25rem-0.5rem)] group-data-[orientation=vertical]/timeline:translate-y-6" />
                  <div className="flex min-w-0 flex-wrap items-center gap-2">
                    <TimelineTitle className="font-mono text-sm font-semibold">{step.tool}</TimelineTitle>
                    {idx && <span className="font-mono text-11 text-muted-foreground">{idx}</span>}
                    {step.error
                      ? <Badge size="sm" variant="destructive-light">{t('invStepFailed')}</Badge>
                      : <span className="text-xs tabular-nums text-muted-foreground">{t('invStepHits', { n: step.hit_count })}</span>}
                  </div>
                  <TimelineIndicator
                    className={cn(
                      'flex size-5 items-center justify-center border-none bg-primary text-primary-foreground',
                      step.error && 'bg-destructive/10 text-destructive dark:bg-destructive/20',
                    )}
                  >
                    <HugeiconsIcon icon={step.error ? Cancel01Icon : CheckIcon} strokeWidth={2} className="size-3" aria-hidden="true" />
                  </TimelineIndicator>
                </TimelineHeader>
                <TimelineContent className="mt-2">
                  <Frame stacked dense spacing="sm">
                    <Collapsible defaultOpen={!!step.error} className="group/collapsible">
                      <CollapsibleTrigger type="button" className="flex w-full" aria-label={step.tool}>
                        <FrameHeader className="flex grow flex-row items-center justify-between gap-2">
                          <span className="min-w-0 truncate text-sm font-medium text-muted-foreground">{t('invStepArgs')}</span>
                          <HugeiconsIcon icon={ChevronRightIcon} strokeWidth={2} className="size-4 shrink-0 text-muted-foreground transition-transform duration-200 group-data-open/collapsible:rotate-90" aria-hidden="true" />
                        </FrameHeader>
                      </CollapsibleTrigger>
                      <CollapsibleContent>
                        <FramePanel className="space-y-2">
                          <pre className="overflow-x-auto whitespace-pre-wrap break-all font-mono text-11 leading-[1.5] text-fg-muted">{step.args}</pre>
                          {step.error && (
                            <div className="font-mono text-11 leading-[1.5] text-destructive">{step.error}</div>
                          )}
                        </FramePanel>
                      </CollapsibleContent>
                    </Collapsible>
                  </Frame>
                </TimelineContent>
              </TimelineItem>
            )
          })}
        </Timeline>
      </FramePanel>
    </Frame>
  )
}

/** Best-effort pull of the `index` out of the tool-call args JSON for display. */
function parseTraceIndex(args: string): string | null {
  try {
    const o = JSON.parse(args) as { index?: unknown }
    return typeof o.index === 'string' ? o.index : null
  } catch {
    return null
  }
}

function DegradedBanner() {
  const t = useT(dialogsCopy)
  return (
    <div
      role="status"
      className={cn(
        'flex items-start gap-3 rounded-xl bg-accent px-4 py-3',
        '[box-shadow:var(--shadow-ring-light)]',
      )}
    >
      <HugeiconsIcon icon={AlertCircleIcon} strokeWidth={2} className="mt-0.5 size-4 shrink-0 text-destructive" />
      <div className="flex-1 text-13 leading-[1.5] text-fg-muted">
        <div className="mb-0.5 font-medium text-foreground">{t('degradedTitle')}</div>
        {t('invDegradedBody')}
      </div>
    </div>
  )
}

function Section({ title, children }: { title: string; children: ReactNode }) {
  return (
    <section className="space-y-2">
      <LabelMono>{title}</LabelMono>
      {children}
    </section>
  )
}

function LoadingBlock({ stages }: { stages: InvestigateStageEvent[] }) {
  const t = useT(dialogsCopy)
  // Before the first SSE stage lands, keep the original single-line spinner so an
  // empty box never flashes.
  if (stages.length === 0) {
    return (
      <div className="flex items-center gap-3 px-1 py-8 text-14 text-fg-muted">
        <HugeiconsIcon icon={Loading03Icon} strokeWidth={2} className="size-4 animate-spin text-info" />
        <span>{t('invAnalysing')}</span>
      </div>
    )
  }
  const done = stages.filter((s) => s.status === 'done').length
  /* 进度阶段照 solution-agents-3 的 Step Trace：完成的是主色勾，进行中的是带光环的转圈。 */
  return (
    <div className="px-1 py-6" role="status" aria-live="polite">
      <Timeline value={done}>
        {stages.map((s, i) => (
          <TimelineItem key={s.key} step={i + 1} className="group-data-[orientation=vertical]/timeline:not-last:pb-4">
            <TimelineHeader>
              <TimelineSeparator className="bg-border group-data-[orientation=vertical]/timeline:h-[calc(100%-1.25rem-0.5rem)] group-data-[orientation=vertical]/timeline:translate-y-6" />
              <div className="flex min-w-0 flex-wrap items-center gap-2">
                <TimelineTitle className={cn('text-sm', s.status === 'done' ? 'text-foreground' : 'font-semibold text-fg-strong')}>
                  {s.label}{s.status === 'active' && '…'}
                </TimelineTitle>
                {s.detail && <span className="font-mono text-12 text-muted-foreground">{s.detail}</span>}
              </div>
              <TimelineIndicator
                className={cn(
                  'flex size-5 items-center justify-center border-none',
                  s.status === 'done' ? 'bg-primary text-primary-foreground' : 'bg-muted text-muted-foreground ring-2 ring-primary/20',
                )}
              >
                {s.status === 'done'
                  ? <HugeiconsIcon icon={CheckIcon} strokeWidth={2} className="size-3" aria-hidden="true" />
                  : <HugeiconsIcon icon={Loading03Icon} strokeWidth={2} className="size-3 animate-spin text-info" aria-hidden="true" />}
              </TimelineIndicator>
            </TimelineHeader>
          </TimelineItem>
        ))}
      </Timeline>
    </div>
  )
}

function ErrorBlock({ message, onRetry }: { message: string; onRetry: () => void }) {
  const t = useT(dialogsCopy)
  return (
    <div className={cn('flex items-start gap-3 rounded-xl bg-destructive-subtle px-4 py-3', '[box-shadow:0_0_0_1px_rgba(255,91,79,0.3)]')}>
      <HugeiconsIcon icon={AlertCircleIcon} strokeWidth={2} className="mt-0.5 size-4 shrink-0 text-destructive" />
      <div className="flex-1 text-13 leading-[1.5] text-destructive-foreground">
        <div>{message}</div>
        <button
          onClick={onRetry}
          className="mt-2 inline-flex items-center gap-1 rounded-md bg-card px-2 py-1 text-12 font-medium text-foreground [box-shadow:var(--shadow-ring-light)] hover:[box-shadow:var(--shadow-ring)]"
        >
          {t('retry')}
        </button>
      </div>
    </div>
  )
}

function sevTone(s: Severity) { return (`sev-${s}` as const) }
function confTone(c: Confidence) {
  if (c === 'high') return 'sev-info' as const
  if (c === 'medium') return 'gray' as const
  return 'sev-medium' as const
}
