import { useEffect, useState } from 'react'
import { HugeiconsIcon } from '@hugeicons/react'
import { AlertCircleIcon, Cancel01Icon, CheckIcon, ChevronDownIcon, ChevronUpIcon, CopyIcon, PencilIcon } from '@hugeicons/core-free-icons'
import { useT } from '@/lib/i18n'
import { cn } from '@/lib/utils'
import { commonCopy } from '@/locales/common'
import { componentsCopy } from '@/locales/components'

// Fold DSL bodies taller than this so a long query doesn't push the 执行 button
// off-screen. Short ones render whole (no toggle).
const COLLAPSE_LINES = 14

interface Props {
  /** Parsed DSL (rendered as pretty JSON). Required when not streaming. */
  value?: Record<string, unknown> | null
  /** Called when the user saves a hand-edit. If omitted, the edit button is hidden. */
  onChange?: (next: Record<string, unknown>) => void
  /** Notified the first time the value differs from the original LLM output. */
  onEdited?: () => void
  /**
   * If set, the component renders raw streaming text in mono with a blinking
   * caret, ignoring `value`. Switch this off (and set `value`) once the
   * stream's `done` event lands — the structured JSON view takes over.
   */
  streamingText?: string | null
}

export function DslPreview({ value, onChange, onEdited, streamingText }: Props) {
  const t = useT(componentsCopy)
  const c = useT(commonCopy)
  const [copied, setCopied] = useState(false)
  const [editing, setEditing] = useState(false)
  const [draft, setDraft] = useState('')
  const [error, setError] = useState<string | null>(null)
  const [collapsed, setCollapsed] = useState(true)

  const isStreaming = streamingText !== null && streamingText !== undefined
  const json = !isStreaming && value ? JSON.stringify(value, null, 2) : ''
  const lineCount = json ? json.split('\n').length : 0
  const collapsible = lineCount > COLLAPSE_LINES

  // Re-fold whenever a fresh DSL lands so each new (usually long) result starts
  // compact instead of inheriting the previous one's expanded state.
  // eslint-disable-next-line react-hooks/set-state-in-effect -- reset fold on new DSL
  useEffect(() => { setCollapsed(true) }, [json])

  async function onCopy() {
    try {
      await navigator.clipboard.writeText(json)
      setCopied(true)
      setTimeout(() => setCopied(false), 1500)
    } catch {
      // ignore
    }
  }

  /** Validate a draft string → error message, or null when it's a valid DSL object. */
  function validateDraft(text: string): string | null {
    if (!text.trim()) return t('errEmpty')
    let parsed: unknown
    try {
      parsed = JSON.parse(text)
    } catch (e) {
      return e instanceof Error ? `${t('errJsonParse')}: ${e.message}` : t('errJsonParse')
    }
    if (typeof parsed !== 'object' || parsed === null || Array.isArray(parsed)) {
      return t('errNotObject')
    }
    return null
  }

  function onDraftChange(text: string) {
    setDraft(text)
    setError(validateDraft(text))
  }

  function startEdit() {
    setDraft(json)
    setError(validateDraft(json))
    setEditing(true)
  }

  function cancelEdit() {
    setEditing(false)
    setError(null)
  }

  function saveEdit() {
    const err = validateDraft(draft)
    if (err) {
      setError(err)
      return
    }
    onChange?.(JSON.parse(draft) as Record<string, unknown>)
    onEdited?.()
    setEditing(false)
    setError(null)
  }

  if (isStreaming) {
    return (
      <div
        className={cn(
          'relative overflow-hidden rounded-lg bg-accent',
          '[box-shadow:var(--shadow-ring-light)]',
        )}
      >
        <div className="absolute right-2 top-2 z-10 flex items-center gap-2">
          <span className="inline-flex items-center gap-1.5 rounded-full bg-card px-2 py-0.5 text-11 font-medium text-info [box-shadow:var(--shadow-ring-light)]">
            <span className="block size-1.5 rounded-full bg-info animate-pulse" aria-hidden="true" />
            STREAMING
          </span>
        </div>
        <pre
          className={cn(
            'm-0 overflow-x-auto px-4 py-3 pr-32 min-h-[120px]',
            'font-mono text-13 leading-[1.55] text-foreground whitespace-pre-wrap break-words',
          )}
        >
          <code>{streamingText}</code>
          <span className="inline-block w-[7px] h-[14px] -mb-[2px] ml-[1px] bg-info animate-pulse align-middle" />
        </pre>
      </div>
    )
  }

  if (!value) return null

  return (
    <div
      className={cn(
        'relative overflow-hidden rounded-lg bg-accent',
        '[box-shadow:var(--shadow-ring-light)]',
      )}
    >
      {/* Toolbar */}
      <div className="absolute right-2 top-2 z-10 flex items-center gap-1">
        {!editing && onChange && (
          <button
            onClick={startEdit}
            className={cn(
              'inline-flex items-center gap-1 rounded-md',
              'bg-card px-2 py-1 text-12 font-medium text-fg-muted',
              '[box-shadow:var(--shadow-ring-light)]',
              'hover:text-foreground hover:[box-shadow:var(--shadow-ring)]',
              'transition-shadow duration-100',
            )}
            title={t('editDslTitle')}
          >
            <HugeiconsIcon icon={PencilIcon} strokeWidth={2} className="size-3.5" />
            {t('edit')}
          </button>
        )}
        {!editing && (
          <button
            onClick={onCopy}
            className={cn(
              'inline-flex items-center gap-1 rounded-md',
              'bg-card px-2 py-1 text-12 font-medium text-fg-muted',
              '[box-shadow:var(--shadow-ring-light)]',
              'hover:text-foreground hover:[box-shadow:var(--shadow-ring)]',
              'transition-shadow duration-100',
            )}
          >
            {copied ? <HugeiconsIcon icon={CheckIcon} strokeWidth={2} className="size-3.5" /> : <HugeiconsIcon icon={CopyIcon} strokeWidth={2} className="size-3.5" />}
            {copied ? c('copied') : c('copy')}
          </button>
        )}
        {editing && (
          <>
            <button
              onClick={cancelEdit}
              className={cn(
                'inline-flex items-center gap-1 rounded-md',
                'bg-card px-2 py-1 text-12 font-medium text-fg-muted',
                '[box-shadow:var(--shadow-ring-light)]',
                'hover:text-foreground',
              )}
            >
              <HugeiconsIcon icon={Cancel01Icon} strokeWidth={2} className="size-3.5" />
              {c('cancel')}
            </button>
            <button
              onClick={saveEdit}
              disabled={!!error}
              className={cn(
                'inline-flex items-center gap-1 rounded-md',
                'bg-foreground px-2 py-1 text-12 font-medium text-primary-foreground',
                'transition-transform',
                error
                  ? 'cursor-not-allowed opacity-40'
                  : 'hover:opacity-90 active:scale-[0.97]',
              )}
              title={error ? t('saveTitleInvalid') : t('saveTitleValid')}
            >
              <HugeiconsIcon icon={CheckIcon} strokeWidth={2} className="size-3.5" />
              {c('save')}
            </button>
          </>
        )}
      </div>

      {!editing ? (
        <>
          <pre
            className={cn(
              'm-0 overflow-x-auto px-4 py-3 pr-32',
              'font-mono text-13 leading-[1.55] text-foreground',
              collapsible && collapsed && 'max-h-[220px] overflow-y-hidden',
            )}
          >
            <code>{json}</code>
          </pre>
          {collapsible && collapsed && (
            // Fade the clipped tail so it reads as "there's more".
            <div className="pointer-events-none absolute inset-x-0 bottom-9 h-10 bg-gradient-to-b from-transparent to-accent" />
          )}
          {collapsible && (
            <button
              onClick={() => setCollapsed((c) => !c)}
              className={cn(
                'flex w-full items-center justify-center gap-1.5 py-2',
                'text-12 font-medium text-fg-muted',
                '[box-shadow:0_1px_0_var(--color-line)_inset] hover:text-foreground',
                'transition-colors',
              )}
            >
              {collapsed ? (
                <><HugeiconsIcon icon={ChevronDownIcon} strokeWidth={2} className="size-3.5" />{t('expandAll', { n: lineCount })}</>
              ) : (
                <><HugeiconsIcon icon={ChevronUpIcon} strokeWidth={2} className="size-3.5" />{t('collapse')}</>
              )}
            </button>
          )}
        </>
      ) : (
        <div className="space-y-2 px-4 py-3 pr-32">
          <textarea
            value={draft}
            onChange={(e) => onDraftChange(e.target.value)}
            spellCheck={false}
            className={cn(
              'min-h-[260px] w-full resize-y rounded-md bg-card px-3 py-2',
              'font-mono text-13 leading-[1.55] text-foreground',
              error
                ? '[box-shadow:0_0_0_1px_rgba(255,91,79,0.35)]'
                : '[box-shadow:var(--shadow-ring-light)]',
              'focus-visible:outline-none focus-visible:[box-shadow:var(--shadow-focus)]',
            )}
          />
          {error ? (
            <div
              className={cn(
                'flex items-start gap-2 rounded-md bg-destructive-subtle px-2.5 py-1.5',
                '[box-shadow:0_0_0_1px_rgba(255,91,79,0.3)]',
              )}
            >
              <HugeiconsIcon icon={AlertCircleIcon} strokeWidth={2} className="mt-0.5 size-3.5 shrink-0 text-destructive" />
              <span className="text-12 text-destructive-foreground">{error}</span>
            </div>
          ) : (
            <div className="flex items-center gap-1.5 text-12 text-info">
              <HugeiconsIcon icon={CheckIcon} strokeWidth={2} className="size-3.5 shrink-0" />
              <span>{t('jsonValid')}</span>
            </div>
          )}
          <p className="text-11 text-muted-foreground">
            {t('saveHint')}
          </p>
        </div>
      )}
    </div>
  )
}
