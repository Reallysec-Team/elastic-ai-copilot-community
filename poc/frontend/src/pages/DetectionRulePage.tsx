import { useEffect, useMemo, useState, type ReactNode } from 'react'
import { HugeiconsIcon } from '@hugeicons/react'
import {
  AlertCircleIcon,
  CheckIcon,
  CheckmarkCircle02Icon,
  ChevronDownIcon,
  CopyIcon,
  CornerDownLeftIcon,
  Delete02Icon,
  Download01Icon,
  HistoryIcon,
  Loading03Icon,
  SaveIcon,
  ShieldAlertIcon,
  SparklesIcon,
} from '@hugeicons/core-free-icons'
import { toast } from 'sonner'
import { ThinkingToggle, useThinking } from '@/components/ThinkingToggle'
import { api, type ApiError } from '@/lib/api'
import { useT, translate, type Translate } from '@/lib/i18n'
import { commonCopy } from '@/locales/common'
import { detectionRuleCopy, type DetectionRuleKey } from '@/locales/detectionRule'
import { Alert, AlertDescription } from '@/components/reui/alert'
import {
  Frame,
  FrameFooter,
  FrameHeader,
  FramePanel,
  FrameTitle,
} from '@/components/reui/frame'
import { PageHeader } from '@/components/shell/page-header'
import { Button } from '@/components/ui/button'
import { Label } from '@/components/ui/label'
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from '@/components/ui/select'
import { Textarea } from '@/components/ui/textarea'
import { IndexCombobox } from '@/components/IndexCombobox'
import { Badge } from '@/components/reui/badge'
import {
  CodeBlock, CodeBlockContent, CodeBlockCopyButton, CodeBlockHeader, CodeBlockLanguage, CodeBlockTitle,
} from '@/components/reui/code-block/code-block'
import { Item } from '@/components/ui/item'
import { ScrollArea, ScrollBar } from '@/components/ui/scroll-area'
import { cachedDefaultIndex, resolveDefaultIndex } from '@/lib/defaultIndex'
import { Pill } from '@/components/ui/Pill'
import { takeHandoff } from '@/lib/handoff'
import { cn } from '@/lib/utils'

type RuleHint = 'auto' | 'query' | 'threshold' | 'eql'
type Phase = 'idle' | 'loading' | 'done' | 'error'

interface DetectionRuleResult {
  rule: Record<string, unknown> | null
  explanation: string
  confidence: string
  confidence_reason?: string
  rule_type: string | null
  rag_chunks_used?: number
}

// A generated rule kept in the team-shared state store (kind `detection_rule`),
// so a rule crafted once can be reloaded/exported later instead of regenerated.
interface SavedRule {
  id: string
  question: string
  index: string
  created_at: string
  result: DetectionRuleResult
}

/* 只有 `auto` 那档是文案，其余三档是后端认的规则类型名 —— 翻过去就和
   `rule_type_hint` 对不上了。 */
const HINT_OPTIONS: { value: RuleHint; label: string; key?: DetectionRuleKey }[] = [
  { value: 'auto', label: '', key: 'ruleTypeAuto' },
  { value: 'query', label: 'query (KQL)' },
  { value: 'threshold', label: 'threshold' },
  { value: 'eql', label: 'eql' },
]

function hintLabel(t: Translate<DetectionRuleKey>, o: { label: string; key?: DetectionRuleKey }) {
  return o.key ? t(o.key) : o.label
}

const EXAMPLES: {
  text: DetectionRuleKey
  q: DetectionRuleKey
  tag: 'threshold' | 'query' | 'eql'
}[] = [
  { text: 'ex1', q: 'ex1q', tag: 'threshold' },
  { text: 'ex2', q: 'ex2q', tag: 'query' },
  { text: 'ex3', q: 'ex3q', tag: 'eql' },
]

export function DetectionRulePage() {
  const t = useT(detectionRuleCopy)
  const thinking = useThinking()
  const [index, setIndex] = useState(cachedDefaultIndex())
  const [question, setQuestion] = useState('')
  const [hint, setHint] = useState<RuleHint>('auto')
  const [phase, setPhase] = useState<Phase>('idle')
  const [errorMsg, setErrorMsg] = useState<string | null>(null)
  const [result, setResult] = useState<DetectionRuleResult | null>(null)
  const [handoffNote, setHandoffNote] = useState<string | null>(null)
  const [savedTick, setSavedTick] = useState(0)

  const canSubmit = !!index.trim() && !!question.trim() && phase !== 'loading'

  // Pick up a handoff from the Query page ("转成检测规则").
  // 索引默认值原来写死 `auth-logs-*`——客户 ES 上没有这个索引，第一次生成就报
  // index_not_found。改成和智能查询同一套：用户存过的默认索引，否则问 ES 拿
  // 最忙的那个（`resolveDefaultIndex`）。
  useEffect(() => {
    const h = takeHandoff('detection-rule')
    if (h) {
      // eslint-disable-next-line react-hooks/set-state-in-effect -- one-shot handoff hydration from Query page
      if (h.question) setQuestion(h.question)
      if (h.index) setIndex(h.index)
      setHandoffNote(t('handoffNote'))
    }
    if (!h?.index && !cachedDefaultIndex()) {
      void resolveDefaultIndex().then((idx) => setIndex((cur) => cur || idx))
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps -- one-shot on mount
  }, [])

  async function onGenerate() {
    if (!canSubmit) return
    setPhase('loading')
    setErrorMsg(null)
    setResult(null)
    try {
      const r = await api.detectionRule({
        index: index.trim(),
        question: question.trim(),
        rule_type_hint: hint === 'auto' ? undefined : hint,
        reasoning: thinking,
      })
      setResult(r as DetectionRuleResult)
      setPhase('done')
    } catch (e) {
      const err = e as ApiError
      setErrorMsg(err.message || t('errGenerate'))
      setPhase('error')
    }
  }

  async function onSaveRule() {
    if (!result?.rule) return
    const id = `${Date.now()}`
    try {
      await api.statePut('detection_rule', id, {
        id,
        question: question.trim(),
        index: index.trim(),
        created_at: new Date().toISOString(),
        result,
      } satisfies SavedRule)
      toast.success(t('okSaved'))
      setSavedTick((n) => n + 1)
    } catch (e) {
      toast.error(e instanceof Error ? `${t('errSave')}: ${e.message}` : t('errSave'))
    }
  }

  function onLoadSaved(rec: SavedRule) {
    setIndex(rec.index)
    setQuestion(rec.question)
    setResult(rec.result)
    setPhase('done')
    setErrorMsg(null)
  }

  const hasRule = phase === 'done' && result?.rule != null
  const isRefusal = phase === 'done' && result && result.rule == null
  const showEmpty = phase === 'idle' && !result

  return (
    <div className="@container flex w-full flex-col gap-5">
      <PageHeader title={t('title')} />

      {handoffNote && (
        <Alert variant="info">
          <HugeiconsIcon icon={ShieldAlertIcon} strokeWidth={2} className="size-4" />
          <AlertDescription>
            <span>{handoffNote}</span>
          </AlertDescription>
        </Alert>
      )}

      <section aria-label={t('secIntent')} className="flex flex-col gap-3">
        <InputCard
          index={index}
          question={question}
          hint={hint}
          loading={phase === 'loading'}
          canSubmit={canSubmit}
          onIndexChange={setIndex}
          onQuestionChange={setQuestion}
          onHintChange={setHint}
          onSubmit={onGenerate}
          showExamples={showEmpty}
        />

        <div className="flex items-center gap-3">
          <SavedRules reloadKey={savedTick} onLoad={onLoadSaved} />
        </div>
      </section>

      {errorMsg && phase === 'error' && (
        <Alert variant="destructive">
          <HugeiconsIcon icon={AlertCircleIcon} strokeWidth={2} className="size-4" />
          <AlertDescription>
            <span>{errorMsg}</span>
          </AlertDescription>
        </Alert>
      )}

      {(hasRule || isRefusal) && result && (
        <section aria-label={t('secResult')}>
          {hasRule ? (
            <RuleCard result={result} onSave={onSaveRule} />
          ) : (
            <RefusalCard result={result} />
          )}
        </section>
      )}
    </div>
  )
}

/* ---------- Input ---------- */

function InputCard({
  index,
  question,
  hint,
  loading,
  canSubmit,
  onIndexChange,
  onQuestionChange,
  onHintChange,
  onSubmit,
  showExamples,
}: {
  index: string
  question: string
  hint: RuleHint
  loading: boolean
  canSubmit: boolean
  onIndexChange: (v: string) => void
  onQuestionChange: (v: string) => void
  onHintChange: (v: RuleHint) => void
  onSubmit: () => void
  /** 还没生成过任何规则时，在意图输入框下面直接给三条可点的例子。 */
  showExamples: boolean
}) {
  const t = useT(detectionRuleCopy)
  return (
    <Frame dense spacing="sm" className="flex w-full min-w-0 flex-col [--frame-panel-header-py-adjust:2px]">
      <FrameHeader className="flex-row items-center justify-between gap-4">
        <FrameTitle>{t('cardIntentTitle')}</FrameTitle>
      </FrameHeader>
      <FramePanel className="space-y-4 py-5 bg-card shadow-none!">
        <div className="space-y-1.5">
          <Label>{t('fieldIndex')}</Label>
          <IndexCombobox
            value={index}
            onChange={onIndexChange}
            placeholder="logs-*"
          />
        </div>

        <div className="space-y-1.5">
          <Label>{t('fieldIntent')}</Label>
          <Textarea
            value={question}
            onChange={(e) => onQuestionChange(e.target.value)}
            placeholder={t('intentPlaceholder')}
            spellCheck={false}
            className="min-h-[120px]"
          />
          {/* 例子原来是页面下方一个独立区块，离输入框隔着「已生成规则」那一行 ——
              它的用处是「不知道怎么写就点一条填进去」，那就得贴着输入框。 */}
          {showExamples && (
            <div className="pt-1.5">
              <ExamplesPanel onPick={onQuestionChange} />
            </div>
          )}
        </div>

        <div className="space-y-1.5">
          <Label>{t('fieldRuleType')}</Label>
          {/* `auto` is a real choice ("let the model decide"), not "unset" — so it
              is a normal option, and Base UI's Select never sees an empty value. */}
          <Select value={hint} onValueChange={(v) => onHintChange(v as RuleHint)}>
            <SelectTrigger className="w-[200px]" aria-label={t('fieldRuleType')}>
              <SelectValue>
                {(v) => {
                  const o = HINT_OPTIONS.find((x) => x.value === v)
                  return o ? hintLabel(t, o) : String(v)
                }}
              </SelectValue>
            </SelectTrigger>
            <SelectContent>
              {HINT_OPTIONS.map((o) => (
                <SelectItem key={o.value} value={o.value}>{hintLabel(t, o)}</SelectItem>
              ))}
            </SelectContent>
          </Select>
        </div>

        <div className="flex items-center gap-3 pt-1">
          <Button onClick={onSubmit} disabled={!canSubmit}>
            {loading ? (
              <>
                <HugeiconsIcon icon={Loading03Icon} strokeWidth={2} className="size-4 animate-spin" />
                {t('generating')}
              </>
            ) : (
              <>
                <HugeiconsIcon icon={SparklesIcon} strokeWidth={2} className="size-4" />
                {t('generate')}
              </>
            )}
          </Button>
          <ThinkingToggle />
        </div>
      </FramePanel>
    </Frame>
  )
}

/* ---------- Examples ---------- */

/* 示例照 ai-chat-10 的 StarterCards（`ThreadStart` 里那种）：三列描边 Item 卡，
   整卡可点，右下角一枚规则类型徽标。原来是一竖条分隔线行。 */
function ExamplesPanel({ onPick }: { onPick: (q: string) => void }) {
  const t = useT(detectionRuleCopy)
  return (
    <div className="space-y-2">
      <Label className="text-muted-foreground">{t('examples')}</Label>
      <div className="grid gap-2 sm:grid-cols-3">
        {EXAMPLES.map((ex) => (
          <Item
            key={ex.text}
            variant="outline"
            render={<button type="button" />}
            onClick={() => onPick(t(ex.q))}
            className="group/ex h-full flex-col items-start gap-2 text-start hover:bg-accent/50"
          >
            <span className="min-w-0 text-sm/5 text-foreground">{t(ex.text)}</span>
            <span className="flex w-full items-center justify-between">
              <Badge variant="secondary" size="xs" className="font-mono">{ex.tag}</Badge>
              <HugeiconsIcon icon={CornerDownLeftIcon} strokeWidth={2} className="size-4 shrink-0 opacity-40 transition-opacity group-hover/ex:opacity-100" aria-hidden="true" />
            </span>
          </Item>
        ))}
      </div>
    </div>
  )
}

/* ---------- Saved rules (team-shared) ---------- */

function SavedRules({
  reloadKey,
  onLoad,
}: {
  reloadKey: number
  onLoad: (rec: SavedRule) => void
}) {
  const t = useT(detectionRuleCopy)
  const c = useT(commonCopy)
  const [open, setOpen] = useState(false)
  const [rules, setRules] = useState<Array<{ key: string; value: SavedRule }> | null>(null)
  // A failed fetch must NOT render as "还没有保存的规则" — that reads as "your
  // rules were deleted" and offers no retry.
  const [error, setError] = useState<string | null>(null)

  async function load() {
    setError(null)
    try {
      const { items } = await api.stateList<SavedRule>('detection_rule')
      setRules(items.filter((it) => it.value && it.value.result))
    } catch (e) {
      setError(e instanceof Error ? e.message : t('errLoadSaved'))
    }
  }

  // Same shape as ConversationsPage.onDelete: confirm first, and drop the row
  // only once the server has actually accepted the delete. Removing it
  // optimistically and swallowing the failure told the user a rule was gone
  // while it was still live in the detection engine — it reappeared on reload.
  async function onDelete(key: string, title: string) {
    if (!window.confirm(t('confirmDelete', { name: title }))) return
    setError(null)
    try {
      await api.stateDelete('detection_rule', key)
      setRules((rs) => (rs ? rs.filter((x) => x.key !== key) : rs))
    } catch (e) {
      setError(e instanceof Error ? e.message : t('errDeleteSaved'))
    }
  }

  // A save bumps reloadKey — drop the cache so the next open refetches, and
  // refresh immediately if the list is already open.
  useEffect(() => {
    if (reloadKey === 0) return
    setRules(null)
    if (open) void load()
    // eslint-disable-next-line react-hooks/exhaustive-deps -- refetch trigger only
  }, [reloadKey])

  async function toggle() {
    const next = !open
    setOpen(next)
    if (next && rules === null) void load()
  }

  return (
    <div className="relative">
      <Button variant="outline" size="sm" onClick={toggle}>
        <HugeiconsIcon icon={HistoryIcon} strokeWidth={2} className="size-3.5" />
        {t('savedRules')}
      </Button>
      {open && (
        <div
          className={cn(
            'absolute left-0 top-full z-30 mt-1.5 max-h-[360px] w-[340px] overflow-auto',
            'rounded-lg border bg-popover p-1.5 shadow-md',
          )}
        >
          {error ? (
            <div className="px-3 py-4 text-center text-xs text-destructive">
              <div className="mb-2">{t('loadFailed', { err: error })}</div>
              <button type="button" onClick={() => void load()} className="underline underline-offset-2 hover:opacity-80">
                {c('retry')}
              </button>
            </div>
          ) : rules === null ? (
            <div className="px-3 py-4 text-center text-xs text-muted-foreground">{c('loading')}…</div>
          ) : rules.length === 0 ? (
            <div className="px-3 py-4 text-center text-xs text-muted-foreground">{t('noSavedRules')}</div>
          ) : (
            rules.map((r) => {
              const name = String(r.value.result?.rule?.name || r.value.question || t('untitled'))
              return (
                <div
                  key={r.key}
                  className="group flex items-center gap-1.5 rounded-md px-1 transition-colors hover:bg-accent"
                >
                  <button
                    type="button"
                    onClick={() => {
                      onLoad(r.value)
                      setOpen(false)
                    }}
                    className="min-w-0 flex-1 rounded-md px-1.5 py-2 text-left"
                  >
                    <div className="truncate text-13 text-foreground">{name}</div>
                    <div className="font-mono text-11 text-muted-foreground">
                      {(r.value.created_at || '').slice(0, 19).replace('T', ' ')} ·{' '}
                      {r.value.result?.rule_type ?? '?'}
                    </div>
                  </button>
                  <button
                    type="button"
                    aria-label={c('delete')}
                    onClick={() => void onDelete(r.key, name)}
                    className="shrink-0 rounded-md p-1.5 text-muted-foreground opacity-0 transition-opacity hover:text-destructive group-hover:opacity-100"
                  >
                    <HugeiconsIcon icon={Delete02Icon} strokeWidth={2} className="size-3.5" />
                  </button>
                </div>
              )
            })
          )}
        </div>
      )}
    </div>
  )
}

/* ---------- Generated Rule ---------- */

function RuleCard({
  result,
  onSave,
}: {
  result: DetectionRuleResult
  onSave: () => void
}) {
  const t = useT(detectionRuleCopy)
  const c2 = useT(commonCopy)
  const rule = result.rule!
  const ruleType = (result.rule_type ?? (rule.type as string) ?? 'query') as string
  const fullJson = useMemo(() => JSON.stringify(rule, null, 2), [rule])
  const [copied, setCopied] = useState(false)
  const [showFull, setShowFull] = useState(false)
  const [showSteps, setShowSteps] = useState(false)

  async function copyJson() {
    try {
      await navigator.clipboard.writeText(fullJson)
      setCopied(true)
      setTimeout(() => setCopied(false), 1500)
    } catch {
      // ignore
    }
  }

  // Kibana's Security → Rules → Import expects NDJSON (one rule object per line).
  // Exporting it directly means the analyst imports the file instead of hand-
  // pasting JSON — closing the "generated rule → live rule" gap.
  function downloadNdjson() {
    const blob = new Blob([JSON.stringify(rule) + '\n'], { type: 'application/x-ndjson;charset=utf-8' })
    const url = URL.createObjectURL(blob)
    const a = document.createElement('a')
    const name = String((rule.name as string) || (rule.rule_id as string) || 'detection-rule')
      .replace(/[\\/<>:"|?*]+/g, '_').slice(0, 48)
    a.href = url
    a.download = `${name}.ndjson`
    document.body.appendChild(a); a.click(); document.body.removeChild(a)
    setTimeout(() => URL.revokeObjectURL(url), 1000)
  }

  // The LLM occasionally returns malformed shapes (tags as a string, query /
  // threshold as objects). Guard every field so a bad payload renders safely
  // instead of throwing (tags.map) or crashing React (rendering an object).
  const tags = Array.isArray(rule.tags)
    ? (rule.tags as unknown[]).map((t) => String(t))
    : []
  const query =
    rule.query == null
      ? ''
      : typeof rule.query === 'string'
        ? rule.query
        : JSON.stringify(rule.query, null, 2)
  const threshold =
    ruleType === 'threshold' && rule.threshold && typeof rule.threshold === 'object'
      ? (rule.threshold as Record<string, unknown>)
      : null

  const meta: { label: string; value: string; mono?: boolean }[] = [
    { label: 'name', value: String(rule.name ?? '—') },
    { label: 'severity', value: String(rule.severity ?? '—'), mono: true },
    { label: 'risk_score', value: String(rule.risk_score ?? '—'), mono: true },
    { label: 'language', value: String(rule.language ?? '—'), mono: true },
    { label: 'from', value: String(rule.from ?? '—'), mono: true },
    { label: 'interval', value: String(rule.interval ?? '—'), mono: true },
  ]

  return (
    <Frame dense spacing="sm" className="flex w-full min-w-0 flex-col [--frame-panel-header-py-adjust:2px]">
      <FrameHeader className="flex-row items-center justify-between gap-4">
        <FrameTitle>{t('cardRuleTitle')}</FrameTitle>
        <div className="flex items-center gap-2">
          <Pill tone="blue">{ruleType}</Pill>
          <Pill tone={confidenceTone(result.confidence)}>
            {t('confidence', { level: result.confidence })}
          </Pill>
        </div>
      </FrameHeader>
      <FramePanel className="space-y-5 py-5 bg-card shadow-none!">
        {!!result.rag_chunks_used && result.rag_chunks_used > 0 && (
          <div className="font-mono text-11 text-muted-foreground">
            {t('ragUsed', { n: result.rag_chunks_used })}
          </div>
        )}
        {result.explanation && (
          <p className="text-sm leading-relaxed text-muted-foreground">
            {result.explanation}
          </p>
        )}

        {/* Metadata grid */}
        <div className="grid grid-cols-1 gap-x-6 gap-y-2.5 sm:grid-cols-2">
          {meta.map((m) => (
            <Field key={m.label} label={m.label} value={m.value} mono={m.mono} />
          ))}
          <EnabledField />
        </div>

        {/* Tags */}
        {tags.length > 0 && (
          <div className="space-y-1.5">
            <Label className="text-muted-foreground">{t('labelTags')}</Label>
            <div className="flex flex-wrap gap-1.5">
              {tags.map((t) => (
                <Pill key={t} tone={t === 'rst-copilot-generated' ? 'blue' : 'gray'}>
                  <code className="font-mono text-11">{t}</code>
                </Pill>
              ))}
            </div>
          </div>
        )}

        {/* Query */}
        {query && (
          <div>
            <RuleCode value={query} language={ruleType === 'eql' ? 'eql' : 'kql'} title={ruleType === 'eql' ? t('labelEql') : t('labelKql')} />
          </div>
        )}

        {/* Threshold block */}
        {threshold && (
          <div>
            <RuleCode value={JSON.stringify(threshold, null, 2)} language="json" title={t('labelThreshold')} />
          </div>
        )}

        {/* Collapsible full JSON */}
        <div className="space-y-1.5">
          <button
            type="button"
            onClick={() => setShowFull((v) => !v)}
            className={cn(
              'inline-flex items-center gap-1 rounded-md px-2 py-1 -ml-2',
              'text-13 font-medium text-foreground',
              'hover:bg-accent cursor-pointer transition-colors',
            )}
          >
            <HugeiconsIcon
              icon={ChevronDownIcon}
              strokeWidth={2}
              className={cn('size-3.5 transition-transform duration-150', showFull && 'rotate-180')}
            />
            {t('showFullJson')}
          </button>
          {showFull && <RuleCode value={fullJson} language="json" title={t('showFullJson')} foldable />}
        </div>
      </FramePanel>
      <FrameFooter className="gap-3">
        <div className="flex flex-wrap items-center gap-3">
          <Button variant="outline" size="sm" onClick={copyJson}>
            <HugeiconsIcon
              icon={copied ? CheckIcon : CopyIcon}
              strokeWidth={2}
              className="size-3.5"
            />
            {copied ? c2('copied') : t('copyJson')}
          </Button>
          <Button variant="outline" size="sm" onClick={downloadNdjson} title={t('exportNdjsonTitle')}>
            <HugeiconsIcon icon={Download01Icon} strokeWidth={2} className="size-3.5" />
            {t('exportNdjson')}
          </Button>
          <Button variant="outline" size="sm" onClick={onSave} title={t('saveRuleTitle')}>
            <HugeiconsIcon icon={SaveIcon} strokeWidth={2} className="size-3.5" />
            {t('saveRule')}
          </Button>
          <Button variant="ghost" size="sm" onClick={() => setShowSteps((v) => !v)}>
            <HugeiconsIcon
              icon={ChevronDownIcon}
              strokeWidth={2}
              className={cn('size-3.5 transition-transform duration-150', showSteps && 'rotate-180')}
            />
            {t('showDeploySteps')}
          </Button>
        </div>
        {showSteps && <DeploySteps />}
      </FrameFooter>
    </Frame>
  )
}

function DeploySteps() {
  const t = useT(detectionRuleCopy)
  const steps: ReactNode[] = [
    t('step1'),
    t('step2'),
    <>
      <strong className="font-medium text-foreground">{t('step3Strong')}</strong>
      {t('step3Rest')}
    </>,
    t('step4'),
  ]
  return (
    <div className="rounded-lg border bg-muted/50 p-4">
      <ol className="space-y-2 text-13 leading-relaxed text-foreground">
        {steps.map((s, i) => (
          <li key={i} className="flex items-start gap-2.5">
            <span
              className={cn(
                'mt-0.5 inline-flex size-5 shrink-0 items-center justify-center rounded-full',
                'border border-primary bg-card font-mono text-11 font-medium text-primary',
              )}
            >
              {i + 1}
            </span>
            <span>{s}</span>
          </li>
        ))}
      </ol>
    </div>
  )
}

/* ---------- Helpers ---------- */

function Field({
  label,
  value,
  mono,
}: {
  label: string
  value: string
  mono?: boolean
}) {
  return (
    <div className="flex items-baseline justify-between gap-3">
      <span className="font-mono text-xs text-muted-foreground">{label}</span>
      <span
        className={cn(
          'truncate text-right text-13 text-foreground',
          mono && 'font-mono text-xs',
        )}
        title={value}
      >
        {value}
      </span>
    </div>
  )
}

function EnabledField() {
  return (
    <div className="flex items-baseline justify-between gap-3">
      <span className="font-mono text-xs text-muted-foreground">enabled</span>
      <span
        className="inline-flex items-center gap-1.5 font-mono text-xs text-foreground"
        title={translate(detectionRuleCopy, 'enabledTitle')}
      >
        <HugeiconsIcon icon={CheckmarkCircle02Icon} strokeWidth={2} className="size-3.5 text-success" />
        false
      </span>
    </div>
  )
}

/*
 * 规则里的 KQL / EQL / JSON 用 ReUI CodeBlock：头部标题 + 语言标签 + 复制，JSON
 * 可折叠。KQL / EQL 不在 shiki 的语言表里，不着色，但标签照样标——看的人要
 * 知道这段该贴进 Kibana 的哪个框。
 */
function RuleCode({ value, language, title, foldable }: { value: string; language: string; title: string; foldable?: boolean }) {
  return (
    <CodeBlock code={value} language={language} foldable={foldable} className="w-full min-w-0">
      <CodeBlockHeader>
        <CodeBlockTitle>{title}</CodeBlockTitle>
        <CodeBlockLanguage>{language}</CodeBlockLanguage>
        <div className="ms-auto flex items-center gap-1">
          <CodeBlockCopyButton />
        </div>
      </CodeBlockHeader>
      <ScrollArea className="rounded-(--code-block-radius) **:data-[slot=scroll-area-viewport]:max-h-[calc(24*var(--code-block-line-height)+var(--code-block-padding))] [&>[data-slot=scroll-area-viewport]>div]:block!">
        <CodeBlockContent />
        <ScrollBar orientation="horizontal" />
      </ScrollArea>
    </CodeBlock>
  )
}

function RefusalCard({ result }: { result: DetectionRuleResult }) {
  const t = useT(detectionRuleCopy)
  return (
    <Frame dense spacing="sm" className="flex w-full min-w-0 flex-col [--frame-panel-header-py-adjust:2px]">
      <FrameHeader className="flex-row items-center justify-between gap-4">
        <div className="flex items-center gap-2.5">
          <HugeiconsIcon icon={ShieldAlertIcon} strokeWidth={2} className="size-4 text-destructive" />
          <FrameTitle>{t('refusalTitle')}</FrameTitle>
        </div>
        <Pill tone="sev-medium">{t('confidence', { level: result.confidence })}</Pill>
      </FrameHeader>
      <FramePanel className="space-y-3 py-5 bg-card shadow-none!">
        {result.explanation && (
          <p className="text-sm leading-relaxed text-foreground">{result.explanation}</p>
        )}
        {result.confidence_reason && (
          <p className="text-13 leading-relaxed text-muted-foreground">
            {result.confidence_reason}
          </p>
        )}
        <div className="rounded-lg border bg-muted/50 px-3.5 py-2.5">
          <p className="text-13 leading-relaxed text-muted-foreground">
            <strong className="font-medium text-foreground">{t('suggestLabel')}</strong>
            {t('suggestBody')}
          </p>
        </div>
      </FramePanel>
    </Frame>
  )
}

function confidenceTone(c: string) {
  if (c === 'high') return 'sev-info' as const
  if (c === 'medium') return 'gray' as const
  return 'sev-medium' as const
}
