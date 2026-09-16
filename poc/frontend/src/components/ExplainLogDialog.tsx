import { useEffect, useMemo, useRef, useState, type ReactNode } from 'react'
import { HugeiconsIcon } from '@hugeicons/react'
import { AlertCircleIcon, ArrowRight01Icon, BookOpen01Icon, CheckIcon, ChevronDownIcon, CopyIcon, Download01Icon, FileTextIcon, Loading03Icon, RefreshCwIcon, Share01Icon, SparklesIcon } from '@hugeicons/core-free-icons'
import { api, type ApiError } from '@/lib/api'
import { Dialog, DialogContent, DialogHeader, DialogFooter, DialogTitle } from '@/components/ui/dialog'
import { Button } from '@/components/ui/button'
import { NavDropdownAction, NavDropdownGeneric } from '@/components/NavDropdown'
import { copyText } from '@/lib/clipboard'
import { LabelMono, Pill } from '@/components/ui/Pill'
import { useT, translate } from '@/lib/i18n'
import { cn, clipText } from '@/lib/utils'
import { commonCopy } from '@/locales/common'
import { dialogsCopy } from '@/locales/dialogs'
import { severityLabel } from '@/lib/severity'

/*
 * ExplainLogDialog — DEVELOP workflow color (blue).
 * Calls /api/explain-log when opened, then renders the structured response.
 * The endpoint returns a generic record; we cast & narrow with helpers below.
 */

type Severity = 'info' | 'low' | 'medium' | 'high' | 'critical'
type Confidence = 'low' | 'medium' | 'high'

interface KeyField {
  name?: string
  value?: unknown
  why?: string
}

interface ExplainLogResponse {
  summary?: string
  log_type?: string
  key_fields?: KeyField[]
  indicators?: string[]
  investigation?: string[]
  severity?: Severity
  confidence?: Confidence
  rag_chunks_used?: number
  /** True when the LLM output couldn't be parsed and a safe placeholder was returned. */
  degraded?: boolean
}

/** Payload for the result-set flavour (`/api/explain-result`). */
export interface ExplainResultPayload {
  question?: string
  dsl: Record<string, unknown>
  aggregations?: Record<string, unknown> | null
  sample_hits?: Record<string, unknown>[]
  total?: number | null
}

export interface ExplainLogDialogProps {
  open: boolean
  onOpenChange: (v: boolean) => void
  /** Single-document mode. Ignored when `resultPayload` is given. */
  doc: Record<string, unknown> | null
  index?: string
  onUpgradeToInvestigate?: () => void
  /**
   * Result-set mode: interpret a whole query result (aggregations + samples)
   * instead of one document. Same response shape, so the body below renders
   * either one unchanged — only the endpoint and the labels differ.
   */
  resultPayload?: ExplainResultPayload | null
  /**
   * Turn one 排查建议 into the next query. Without this the dialog is a dead
   * end: the model names concrete next steps and the analyst can only retype
   * them by hand.
   */
  onUseSuggestion?: (suggestion: string) => void
}

export function ExplainLogDialog({
  open,
  onOpenChange,
  doc,
  index,
  onUpgradeToInvestigate,
  resultPayload,
  onUseSuggestion,
}: ExplainLogDialogProps) {
  const t = useT(dialogsCopy)
  const c = useT(commonCopy)
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const [data, setData] = useState<ExplainLogResponse | null>(null)
  const [reqKey, setReqKey] = useState(0)
  /* Cache the analysis for the exact input that produced it. The call is
   * deterministic (temperature=0), so re-opening the dialog to re-read a result
   * used to buy the identical answer a second time. Keyed by target identity;
   * `reqKey` is bumped by 重新分析 to force a real refetch. */
  const cacheRef = useRef<{ key: string; data: ExplainLogResponse } | null>(null)
  const cacheKey = useMemo(
    () => JSON.stringify(resultPayload ?? doc ?? null) + `|${index ?? ''}`,
    [resultPayload, doc, index],
  )

  useEffect(() => {
    const cached = cacheRef.current
    if (open && cached && cached.key === cacheKey) {
      setData(cached.data)
      setLoading(false)
      setError(null)
      return
    }
    // Reset to the loading state up-front (even when closed) so a re-open or a
    // change of target doc never flashes the previous log's analysis on frame 1.
    setLoading(true)
    setError(null)
    setData(null)
    if (!open || (!doc && !resultPayload)) {
      setLoading(false)
      return
    }
    let cancelled = false
    const ac = new AbortController()
    const p = resultPayload
      ? api.explainResult({ ...resultPayload, index }, ac.signal)
      : api.explainLog({ doc: doc!, index }, ac.signal)
    p
      .then((r) => {
        if (cancelled) return
        cacheRef.current = { key: cacheKey, data: r as ExplainLogResponse }
        setData(r as ExplainLogResponse)
      })
      .catch((e) => {
        if (cancelled) return
        const err = e as ApiError
        setError(err.message || t('exErrExplain'))
      })
      .finally(() => {
        if (cancelled) return
        setLoading(false)
      })
    return () => {
      cancelled = true
      ac.abort()
    }
  }, [open, doc, index, reqKey, resultPayload, cacheKey, t])

  const sev = data?.severity
  const conf = data?.confidence
  const isResult = !!resultPayload
  const heading = isResult ? t('exHeadingResult') : t('exHeadingLog')

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent className="flex flex-col gap-0 overflow-hidden p-0 sm:max-w-[720px] max-h-[86vh]">
        <DialogHeader className="flex-row items-start justify-between gap-4 border-b px-6 pt-5 pb-4">
          <div className="flex flex-col gap-1">
            <span className="label-mono">{heading}</span>
            <DialogTitle className="text-base font-semibold">{data?.log_type ?? (isResult ? t('exTitleResult') : t('exTitleLog'))}</DialogTitle>
          </div>
          <div className="flex shrink-0 items-center gap-2 pt-1 pr-8">{
            <>
              {sev && <Pill tone={sevTone(sev)}>{severityLabel(sev)}</Pill>}
              {conf && (
                <Pill tone={confTone(conf)}>
                  <span className="label-mono mr-1 opacity-70">{t('confidence')}</span>
                  {conf}
                </Pill>
              )}
            </>
          }</div>
        </DialogHeader>

        <div className="flex-1 min-h-0 space-y-4 overflow-auto px-6 py-5">
          {loading && <LoadingBlock what={isResult ? t('exWhatResult') : t('exWhatLog')} />}
          {error && (
            <ErrorBlock
              message={error}
              onRetry={() => {
                setError(null)
                setReqKey((n) => n + 1)
              }}
            />
          )}
          {!loading && !error && data && (
            <Content data={data} onUseSuggestion={onUseSuggestion} />
          )}
        </div>

        <DialogFooter className="mx-0 mb-0 px-6 py-4">
          <Button variant="outline" onClick={() => onOpenChange(false)}>
            {c('close')}
          </Button>
          {/* Re-analysis is opt-in now that the result is cached — the call is
              deterministic, so an automatic refetch on every re-open was buying
              the same answer twice. */}
          <Button
            variant="ghost"
            disabled={loading || (!doc && !resultPayload)}
            onClick={() => {
              cacheRef.current = null
              setReqKey((n) => n + 1)
            }}
            title={t('exReanalyseTitle')}
          >
            <HugeiconsIcon icon={RefreshCwIcon} strokeWidth={2} className={cn('size-3.5', loading && 'animate-spin')} />
            {t('exReanalyse')}
          </Button>
          <ExportShareMenu data={data} heading={heading} disabled={!data || loading} />
          {onUpgradeToInvestigate && (
            <Button
              variant="default" className="rounded-full"
              onClick={() => {
                onUpgradeToInvestigate()
              }}
            >
              {t('exOpenInInvestigation')}
              <HugeiconsIcon icon={ArrowRight01Icon} strokeWidth={2} className="size-3.5" />
            </Button>
          )}
        </DialogFooter>
      </DialogContent>
    </Dialog>
  )
}

/* Render the analysis as Markdown so it can leave the dialog — into a ticket,
 * a report, or a Feishu doc. Mirrors the investigation dialog's export. */
function toMarkdown(data: ExplainLogResponse, heading: string): string {
  const L: string[] = [`# ${heading}：${data.log_type ?? ''}`.trim(), '']
  if (data.summary) L.push(data.summary, '')
  L.push(
    translate(dialogsCopy, 'exMdSeverity', { v: data.severity ?? 'info' }),
    translate(dialogsCopy, 'exMdConfidence', { v: data.confidence ?? 'medium' }),
    '',
  )
  if (data.key_fields?.length) {
    L.push(translate(dialogsCopy, 'exMdKeyFields'), '')
    for (const f of data.key_fields) {
      L.push(`- \`${f.name ?? ''}\` = ${formatValue(f.value)}${f.why ? `（${f.why}）` : ''}`)
    }
    L.push('')
  }
  if (data.indicators?.length) {
    L.push(translate(dialogsCopy, 'exMdIndicators'), '', ...data.indicators.map((s) => `- ${s}`), '')
  }
  if (data.investigation?.length) {
    L.push(translate(dialogsCopy, 'exMdInvestigation'), '', ...data.investigation.map((s, i) => `${i + 1}. ${s}`), '')
  }
  return L.join('\n')
}

function ExportShareMenu({
  data,
  heading,
  disabled,
}: {
  data: ExplainLogResponse | null
  heading: string
  disabled?: boolean
}) {
  const t = useT(dialogsCopy)
  const [copied, setCopied] = useState(false)
  const [copyErr, setCopyErr] = useState<string | null>(null)
  const [feishu, setFeishu] = useState<'idle' | 'sending' | 'done' | 'error'>('idle')

  const md = data ? toMarkdown(data, heading) : ''
  const title = `${heading}：${data?.log_type ?? ''}`.trim()

  return (
    <NavDropdownGeneric
      align="end"
      trigger={
        <Button variant="outline" className="rounded-full" disabled={disabled}>
          {feishu === 'sending' ? (
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
        icon={copied ? <HugeiconsIcon icon={CheckIcon} strokeWidth={2} className="size-4" /> : <HugeiconsIcon icon={CopyIcon} strokeWidth={2} className="size-4" />}
        label={copyErr ? copyErr : copied ? t('copied') : t('copyMarkdown')}
        onSelect={() => {
          // Only claim success once the write actually resolved.
          void copyText(md)
            .then(() => {
              setCopyErr(null)
              setCopied(true)
              window.setTimeout(() => setCopied(false), 2000)
            })
            .catch((e: unknown) => {
              setCopyErr(e instanceof Error ? e.message : t('copyFailed'))
              window.setTimeout(() => setCopyErr(null), 4000)
            })
        }}
      />
      <NavDropdownAction
        icon={<HugeiconsIcon icon={Download01Icon} strokeWidth={2} className="size-4" />}
        label={t('exportMarkdownFile')}
        onSelect={() => {
          const blob = new Blob([md], { type: 'text/markdown;charset=utf-8' })
          const url = URL.createObjectURL(blob)
          const a = document.createElement('a')
          a.href = url
          a.download = `${title.replace(/[\\/<>:"|?*]+/g, '_') || 'analysis'}.md`
          a.click()
          URL.revokeObjectURL(url)
        }}
      />
      <NavDropdownAction
        icon={
          feishu === 'sending' ? (
            <HugeiconsIcon icon={Loading03Icon} strokeWidth={2} className="size-4 animate-spin" />
          ) : feishu === 'done' ? (
            <HugeiconsIcon icon={CheckIcon} strokeWidth={2} className="size-4" />
          ) : (
            <HugeiconsIcon icon={FileTextIcon} strokeWidth={2} className="size-4" />
          )
        }
        label={
          feishu === 'done'
            ? t('sentToFeishu')
            : feishu === 'error'
              ? t('sendFailedRetry')
              : t('sendToFeishu')
        }
        disabled={feishu === 'sending' || feishu === 'done'}
        hint={t('feishuHint')}
        onSelect={() => {
          setFeishu('sending')
          api
            .reportToFeishu({ title, markdown: md, severity: data?.severity ?? 'info' })
            .then(() => setFeishu('done'))
            .catch(() => setFeishu('error'))
        }}
      />
    </NavDropdownGeneric>
  )
}

function Content({
  data,
  onUseSuggestion,
}: {
  data: ExplainLogResponse
  onUseSuggestion?: (s: string) => void
}) {
  const t = useT(dialogsCopy)
  return (
    <div className="space-y-5">
      {data.degraded && <DegradedBanner />}

      {!!data.rag_chunks_used && data.rag_chunks_used > 0 && (
        <div className="inline-flex items-center gap-1.5 rounded-full bg-info/10 px-2.5 py-1 text-12 font-medium text-info">
          <HugeiconsIcon icon={BookOpen01Icon} strokeWidth={2} className="size-3.5" />
          {t('exRagUsed', { n: data.rag_chunks_used })}
        </div>
      )}
      {data.summary && (
        <p
          className="font-medium text-15 text-foreground"
          style={{ lineHeight: 1.55 }}
        >
          {data.summary}
        </p>
      )}

      {Array.isArray(data.key_fields) && data.key_fields.length > 0 && (
        <Section title={t('exSecKeyFields')}>
          <div className="space-y-2">
            {data.key_fields.map((f, i) => (
              <div
                key={`${f.name ?? 'field'}-${i}`}
                className={cn(
                  'rounded-lg bg-card px-3 py-2.5',
                  '[box-shadow:var(--shadow-ring-light)]',
                )}
              >
                <div className="flex items-baseline justify-between gap-3">
                  <code className="font-mono text-12 text-foreground">
                    {f.name ?? '—'}
                  </code>
                  <code className="truncate font-mono text-12 text-fg-muted">
                    {clipText(formatValue(f.value), 200)}
                  </code>
                </div>
                {f.why && (
                  <p className="mt-1 text-13 leading-[1.5] text-muted-foreground">{f.why}</p>
                )}
              </div>
            ))}
          </div>
        </Section>
      )}

      {Array.isArray(data.indicators) && data.indicators.length > 0 && (
        <Section title={t('exSecIndicators')}>
          <ul className="space-y-1.5">
            {data.indicators.map((s, i) => (
              <li key={i} className="flex items-start gap-2 text-14 leading-[1.55] text-foreground">
                <span className="mt-[7px] block size-1.5 shrink-0 rounded-full bg-destructive" aria-hidden="true" />
                <span>{s}</span>
              </li>
            ))}
          </ul>
        </Section>
      )}

      {Array.isArray(data.investigation) && data.investigation.length > 0 && (
        <Section
        title={onUseSuggestion ? t('exSecInvestigationClickable') : t('exSecInvestigation')}
      >
          <ol className="space-y-1.5">
            {data.investigation.map((s, i) => (
              <li
                key={i}
                className="flex items-start gap-3 text-14 leading-[1.55] text-foreground"
              >
                <span className="mt-[1px] inline-flex size-5 shrink-0 items-center justify-center rounded-full bg-secondary font-mono text-11 text-fg-muted">
                  {i + 1}
                </span>
                {/* A suggestion the analyst can act on beats one they have to
                    retype. Clicking sends the text back to the query page,
                    which fills the search box and regenerates. */}
                {onUseSuggestion ? (
                  <button
                    type="button"
                    onClick={() => onUseSuggestion(s)}
                    className={cn(
                      'group -my-0.5 -mx-1.5 flex flex-1 items-start gap-2 rounded-md px-1.5 py-0.5 text-left',
                      'transition-colors hover:bg-info/10',
                    )}
                    title={t('exUseSuggestionTitle')}
                  >
                    <span className="flex-1">{s}</span>
                    <HugeiconsIcon icon={ArrowRight01Icon} strokeWidth={2} className="mt-1 size-3.5 shrink-0 text-info opacity-0 transition-opacity group-hover:opacity-100" />
                  </button>
                ) : (
                  <span>{s}</span>
                )}
              </li>
            ))}
          </ol>
        </Section>
      )}
    </div>
  )
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
        {t('exDegradedBody')}
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

function LoadingBlock({ what }: { what: string }) {
  const t = useT(dialogsCopy)
  return (
    <div className="flex items-center gap-3 px-1 py-6 text-14 text-fg-muted">
      <HugeiconsIcon icon={Loading03Icon} strokeWidth={2} className="size-4 animate-spin text-info" />
      <HugeiconsIcon icon={SparklesIcon} strokeWidth={2} className="size-3.5 text-info" />
      <span>{t('exAnalysing', { what })}</span>
    </div>
  )
}

function ErrorBlock({ message, onRetry }: { message: string; onRetry: () => void }) {
  const t = useT(dialogsCopy)
  return (
    <div
      className={cn(
        'flex items-start gap-3 rounded-xl bg-destructive-subtle px-4 py-3',
        '[box-shadow:0_0_0_1px_rgba(255,91,79,0.3)]',
      )}
    >
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

function formatValue(v: unknown): string {
  if (v == null) return ''
  if (typeof v === 'string') return v
  if (typeof v === 'number' || typeof v === 'boolean') return String(v)
  try {
    return JSON.stringify(v)
  } catch {
    return String(v)
  }
}

function sevTone(s: Severity) {
  return (`sev-${s}` as const)
}

function confTone(c: Confidence) {
  if (c === 'high') return 'sev-info' as const
  if (c === 'medium') return 'gray' as const
  return 'sev-medium' as const
}
