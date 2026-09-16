import { useCallback, useEffect, useLayoutEffect, useRef, useState, type KeyboardEvent as ReactKeyboardEvent } from 'react'
import { createPortal } from 'react-dom'
import { HugeiconsIcon } from '@hugeicons/react'
import { DatabaseIcon, Layers01Icon, Loading03Icon, RefreshCwIcon, Search01Icon, SparklesIcon, UnfoldMoreIcon } from '@hugeicons/core-free-icons'
import { api } from '@/lib/api'
import { buildScope, isMultiIndex, resetScopeCache, scopeLabel } from '@/lib/searchScope'
import { fetchTimeRanges, formatRange, resetTimeRangeCache, type TimeRange } from '@/lib/timeRange'
import { useT, translate } from '@/lib/i18n'
import { cn } from '@/lib/utils'
import { componentsCopy } from '@/locales/components'

/*
 * Combobox-style index picker. Reads from /api/indices, lets users type a
 * filter, refresh from ES, or just type a free index name (wildcards allowed).
 *
 * Designed to drop in wherever a plain index `<Input>` would live. Keeps the
 * shadow-as-border + Geist Mono aesthetic.
 *
 * Props mirror Input: `value` + `onChange`. Free-text is always allowed.
 *
 * Usage:
 *   <IndexCombobox value={index} onChange={setIndex} />
 */

interface IndexEntry {
  name: string
  kind: 'index' | 'alias' | 'data_stream'
  attributes: string[]
  doc_count: number
  store_size: string
  health: string
}

interface Props {
  value: string
  onChange: (v: string) => void
  /** Visible width override (Tailwind class). Defaults to full width of parent. */
  className?: string
  placeholder?: string
  disabled?: boolean
  /** Auto-fetch the index list when component mounts. Default true. */
  autoload?: boolean
  /** Compact pill-style trigger (used inside the chat composer). */
  compact?: boolean
  /**
   * Offer a pinned 自动选择 option that clears the pin and lets the gateway route
   * the question itself (backend/index_router.py). For the chat surface, where
   * "which index" is exactly the question the product claims to remove.
   */
  allowAuto?: boolean
  /**
   * Offer a pinned 全部日志 option that selects every queryable index at once.
   * Only for surfaces where "I don't know which index" is a legitimate starting
   * point (the chat composer). A detection rule or a field-dictionary scan needs
   * one concrete target, so those keep it off.
   */
  allowAll?: boolean
}

export function IndexCombobox({
  value,
  onChange,
  className,
  placeholder = translate(componentsCopy, 'indexPlaceholder'),
  disabled,
  autoload = true,
  compact = false,
  allowAll = false,
  allowAuto = false,
}: Props) {
  const t = useT(componentsCopy)
  const [open, setOpen] = useState(false)
  const [indices, setIndices] = useState<IndexEntry[]>([])
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const [filter, setFilter] = useState('')
  const [highlight, setHighlight] = useState(0)
  /* Data span per target. A stale index is the most common reason a query
   * comes back empty, and the list used to give no hint of it. */
  const [ranges, setRanges] = useState<Record<string, TimeRange>>({})

  const wrapRef = useRef<HTMLDivElement>(null)
  const panelRef = useRef<HTMLDivElement>(null)
  const filterRef = useRef<HTMLInputElement>(null)
  const listRef = useRef<HTMLDivElement>(null)

  /* The panel is PORTALED to <body> rather than positioned absolutely inside the
   * wrapper. Absolute positioning is clipped by any scrolling ancestor, and the
   * picker lives inside DialogBody (`overflow-auto`) on the 面板 editor — the
   * list was cut off at the dialog edge with no way to see or scroll to the rest.
   * `position: fixed` alone doesn't help either: DialogContent is translated, so
   * it becomes the containing block for fixed children. */
  const [rect, setRect] = useState<{ left: number; top: number; width: number; below: boolean } | null>(null)

  const measure = useCallback(() => {
    const el = wrapRef.current
    if (!el) return
    const r = el.getBoundingClientRect()
    const PANEL_MAX = 360 // filter row + list max-height + footer
    const below = window.innerHeight - r.bottom >= PANEL_MAX || r.top < PANEL_MAX
    /* 面板宽度不再跟着触发器走。触发器在首页 composer 里被限成 256px，面板照抄
       之后每个索引名都被截成 `logs-…` —— 六行长得一模一样，反而是右边的
       `2,825 docs` 占满了宽度。名字是这行的身份，先保证它读得完：按最长的
       索引名算宽（13px 等宽字约 7.8px/字符）+ 徽标、文档数、日期范围那一截
       固定的 ~330px，再夹在 420 和视口之间。 */
    const PANEL_MIN = 420
    const longest = indices.reduce((m, i) => Math.max(m, i.name.length), 0)
    const wanted = Math.ceil(longest * 7.8) + 330
    const width = Math.min(Math.max(r.width, PANEL_MIN, wanted), window.innerWidth - 16)
    setRect({
      // 加宽之后可能顶出右边缘，往左收回来。
      left: Math.max(8, Math.min(r.left, window.innerWidth - width - 8)),
      top: below ? r.bottom + 6 : r.top - 6,
      width,
      below,
    })
  }, [compact, indices])

  useLayoutEffect(() => {
    if (!open) return
    measure()
    // Re-measure on anything that can move the trigger. `true` captures scrolls
    // in ancestor containers (the dialog body), not just the window.
    window.addEventListener('scroll', measure, true)
    window.addEventListener('resize', measure)
    return () => {
      window.removeEventListener('scroll', measure, true)
      window.removeEventListener('resize', measure)
    }
  }, [open, measure])

  async function refresh() {
    setLoading(true)
    setError(null)
    try {
      const r = await api.indices()
      setIndices(r.indices)
      // Both derived caches hang off this list, so a manual refresh drops them.
      resetScopeCache()
      resetTimeRangeCache()
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e))
    } finally {
      setLoading(false)
    }
  }

  useEffect(() => {
    // eslint-disable-next-line react-hooks/set-state-in-effect -- (re)load the index list when autoload flips
    if (autoload) refresh()
  }, [autoload])

  useEffect(() => {
    if (indices.length === 0) return
    let live = true
    void fetchTimeRanges(buildScope(indices)).then((r) => {
      if (live) setRanges(r)
    })
    return () => {
      live = false
    }
  }, [indices])

  // Close on outside click + Esc
  useEffect(() => {
    if (!open) return
    function onDoc(e: MouseEvent) {
      const t = e.target as Node
      // The panel is no longer a DOM child of the wrapper, so it has to be
      // checked separately or every click inside it would close the picker.
      if (!wrapRef.current?.contains(t) && !panelRef.current?.contains(t)) setOpen(false)
    }
    function onKey(e: KeyboardEvent) {
      if (e.key === 'Escape') setOpen(false)
    }
    window.addEventListener('mousedown', onDoc)
    window.addEventListener('keydown', onKey)
    return () => {
      window.removeEventListener('mousedown', onDoc)
      window.removeEventListener('keydown', onKey)
    }
  }, [open])

  useEffect(() => {
    if (open) {
      setTimeout(() => filterRef.current?.focus(), 50)
    }
  }, [open])

  const filtered = indices.filter((i) => {
    if (!filter.trim()) return true
    return i.name.toLowerCase().includes(filter.trim().toLowerCase())
  })

  // Currently-selected index's stats (for the inline doc_count hint).
  const selected = indices.find((i) => i.name === value) || null

  const listboxId = `idx-listbox-${Math.abs((value || placeholder).split('').reduce((a, c) => a * 31 + c.charCodeAt(0), 7)) % 1_000_000}`

  // Unified, navigable option list — free-text/wildcard entry first (when it
  // doesn't collide with a real index), then the filtered indices.
  const freeText = filter.trim()
  const showFreeText = !!freeText && !filtered.some((i) => i.name === freeText)
  // 全部日志 is only offered unfiltered — once the user types a filter they have
  // a target in mind, and a "search everything" row on top of their search is noise.
  const scopeValue = allowAll && !freeText && indices.length > 1 ? buildScope(indices) : ''
  const options: { id: string; value: string }[] = [
    ...(scopeValue ? [{ id: `${listboxId}-opt-all`, value: scopeValue }] : []),
    ...(showFreeText ? [{ id: `${listboxId}-opt-free`, value: freeText }] : []),
    ...filtered.map((i) => ({ id: `${listboxId}-opt-${i.name}`, value: i.name })),
  ]
  const activeIdx = options.length === 0 ? -1 : Math.min(highlight, options.length - 1)
  const activeOptionId = activeIdx >= 0 ? options[activeIdx].id : undefined

  function commit(v: string) {
    onChange(v)
    setOpen(false)
  }

  function onFilterKeyDown(e: ReactKeyboardEvent<HTMLInputElement>) {
    if (e.key === 'ArrowDown') {
      e.preventDefault()
      setHighlight((h) => Math.min(h + 1, options.length - 1))
    } else if (e.key === 'ArrowUp') {
      e.preventDefault()
      setHighlight((h) => Math.max(h - 1, 0))
    } else if (e.key === 'Enter') {
      e.preventDefault()
      // Enter selects the highlighted option, falling back to the first match.
      const pick = options[activeIdx] ?? options[0]
      if (pick) commit(pick.value)
    } else if (e.key === 'Escape') {
      e.preventDefault()
      setOpen(false)
    }
  }

  // Reset highlight to the top whenever the candidate list changes.
  useEffect(() => {
    // eslint-disable-next-line react-hooks/set-state-in-effect -- keep highlight in range as filter/list changes
    setHighlight(0)
  }, [filter, open, indices.length])

  // Keep the highlighted option scrolled into view.
  useEffect(() => {
    if (!open || !activeOptionId) return
    listRef.current?.querySelector(`#${CSS.escape(activeOptionId)}`)?.scrollIntoView({ block: 'nearest' })
  }, [open, activeOptionId])

  return (
    <div ref={wrapRef} className={cn('relative', compact ? 'w-fit' : 'w-full', className)}>
      {/* Trigger */}
      <button
        type="button"
        role="combobox"
        aria-haspopup="listbox"
        aria-expanded={open}
        aria-controls={listboxId}
        aria-label={placeholder}
        onClick={() => !disabled && setOpen((v) => !v)}
        disabled={disabled}
        className={cn(
          'inline-flex items-center gap-2 rounded-md bg-card text-left',
          'transition-shadow duration-100',
          'focus-visible:outline-none focus-visible:[box-shadow:var(--shadow-focus)]',
          'disabled:bg-accent disabled:cursor-not-allowed',
          compact
            ? cn(
                'px-2 py-0.5 font-mono text-12 text-foreground',
                'bg-secondary hover:bg-border',
                '[box-shadow:none]',
              )
            : cn(
                'flex h-9 w-full px-3 py-2 font-mono text-13 text-foreground',
                '[box-shadow:var(--shadow-ring-light)] hover:[box-shadow:var(--shadow-ring)]',
              ),
        )}
      >
        {!compact && <HugeiconsIcon icon={DatabaseIcon} strokeWidth={2} className="size-3.5 shrink-0 text-muted-foreground" />}
        <span
          className={cn(
            'flex-1 truncate',
            !value && 'text-fg-faint font-sans',
            isMultiIndex(value) && 'font-sans',
          )}
          title={value || undefined}
        >
          {value ? scopeLabel(value) : placeholder}
        </span>
        {compact && selected && (
          <span className="font-mono text-10 text-muted-foreground tabular-nums">
            {selected.doc_count.toLocaleString()}
          </span>
        )}
        <HugeiconsIcon icon={UnfoldMoreIcon} strokeWidth={2} className={cn('shrink-0 text-muted-foreground', compact ? 'size-3' : 'size-3.5')} />
      </button>

      {open && rect && createPortal(
        <div
          ref={panelRef}
          id={listboxId}
          role="listbox"
          aria-label={placeholder}
          style={{
            position: 'fixed',
            left: rect.left,
            width: rect.width,
            ...(rect.below ? { top: rect.top } : { bottom: window.innerHeight - rect.top }),
          }}
          className={cn(
            // Above Radix's z-50 dialog content — the picker is opened FROM a dialog.
            'z-[60] overflow-hidden rounded-lg bg-card',
            '[box-shadow:var(--shadow-pop)]',
          )}
        >
          {/* Filter row + actions */}
          <div className="flex items-center gap-2 px-3 py-2 [box-shadow:0_1px_0_var(--color-line)_inset]">
            <HugeiconsIcon icon={Search01Icon} strokeWidth={2} className="size-3.5 shrink-0 text-fg-faint" />
            <input
              ref={filterRef}
              value={filter}
              onChange={(e) => setFilter(e.target.value)}
              onKeyDown={onFilterKeyDown}
              role="combobox"
              aria-expanded={open}
              aria-controls={listboxId}
              aria-activedescendant={activeOptionId}
              aria-autocomplete="list"
              placeholder={t('filterPlaceholder')}
              className="flex-1 bg-transparent text-13 text-foreground placeholder:text-fg-faint outline-none"
            />
            <button
              type="button"
              onClick={refresh}
              disabled={loading}
              className={cn(
                'inline-flex size-6 items-center justify-center rounded-md',
                'text-muted-foreground transition-colors',
                'hover:bg-accent hover:text-foreground',
                'disabled:opacity-50',
              )}
              title={t('refreshFromEs')}
            >
              {loading ? <HugeiconsIcon icon={Loading03Icon} strokeWidth={2} className="size-3.5 animate-spin" /> : <HugeiconsIcon icon={RefreshCwIcon} strokeWidth={2} className="size-3.5" />}
            </button>
          </div>

          {/* List */}
          <div ref={listRef} className="max-h-[280px] overflow-y-auto">
            {error && (
              <div className="px-3 py-3 text-12 text-destructive">
                {error}
              </div>
            )}

            {!error && loading && indices.length === 0 && (
              <div className="flex items-center justify-center gap-2 py-6 text-12 text-muted-foreground">
                <HugeiconsIcon icon={Loading03Icon} strokeWidth={2} className="size-3.5 animate-spin" />
                {t('loadingIndices')}
              </div>
            )}

            {!error && !loading && filtered.length === 0 && indices.length === 0 && (
              <div className="px-3 py-6 text-center text-12 text-muted-foreground">
                {t('noIndices')}
              </div>
            )}

            {!error && filtered.length === 0 && indices.length > 0 && (
              <div className="px-3 py-6 text-center text-12 text-muted-foreground">
                {t('noMatchingIndex', { q: filter })}
              </div>
            )}

            {/* 自动选择 — 回到「网关按问题挑」，也就是不选的那个状态 */}
            {allowAuto && (
              <button
                type="button"
                id={`${listboxId}-opt-auto`}
                role="option"
                aria-selected={value === ''}
                onClick={() => commit('')}
                className={cn(
                  'flex w-full items-center gap-3 px-3 py-2 text-left transition-colors',
                  activeOptionId === `${listboxId}-opt-auto`
                    ? cn('bg-accent', 'outline-2 -outline-offset-2 outline-focus')
                    : 'hover:bg-accent',
                )}
              >
                <HugeiconsIcon icon={SparklesIcon} strokeWidth={2} className="size-3.5 shrink-0 text-muted-foreground" />
                <div className="min-w-0 flex-1">
                  <span className="block text-13 font-medium text-foreground">{t('autoPick')}</span>
                  <span className="block truncate text-11 text-muted-foreground">
                    {t('autoPickDesc')}
                  </span>
                </div>
              </button>
            )}

            {/* 全部日志 — for the user who cannot answer "which index" yet */}
            {scopeValue && (
              <button
                type="button"
                id={`${listboxId}-opt-all`}
                role="option"
                aria-selected={value === scopeValue}
                onClick={() => commit(scopeValue)}
                title={scopeValue}
                className={cn(
                  'flex w-full items-center gap-3 px-3 py-2 text-left transition-colors',
                  activeOptionId === `${listboxId}-opt-all`
                    ? cn('bg-accent', 'outline-2 -outline-offset-2 outline-focus')
                    : 'hover:bg-accent',
                )}
              >
                <HugeiconsIcon icon={Layers01Icon} strokeWidth={2} className="size-3.5 shrink-0 text-muted-foreground" />
                <div className="min-w-0 flex-1">
                  <span className="block text-13 font-medium text-foreground">{t('allLogs')}</span>
                  <span className="block truncate text-11 text-muted-foreground">
                    {t('allLogsDesc')}
                  </span>
                </div>
                <span className="font-mono text-11 tabular-nums text-fg-faint">
                  {t('nIndices', { n: scopeValue.split(',').length })}
                </span>
              </button>
            )}

            {/* Free-text option when filter doesn't match an existing entry */}
            {filter.trim() && !filtered.some((i) => i.name === filter.trim()) && (
              <button
                type="button"
                id={`${listboxId}-opt-free`}
                role="option"
                aria-selected={activeOptionId === `${listboxId}-opt-free`}
                onClick={() => commit(freeText)}
                className={cn(
                  'flex w-full items-center gap-2 px-3 py-2 text-left',
                  'text-13 text-foreground',
                  activeOptionId === `${listboxId}-opt-free`
                    ? cn('bg-accent', 'outline-2 -outline-offset-2 outline-focus')
                    : 'hover:bg-accent',
                )}
              >
                <span className="label-mono">USE</span>
                <code className="flex-1 truncate font-mono">{filter.trim()}</code>
                <span className="text-11 text-muted-foreground">{t('asWildcard')}</span>
              </button>
            )}

            {filtered.map((i) => {
              const active = i.name === value
              const optId = `${listboxId}-opt-${i.name}`
              const highlighted = activeOptionId === optId
              return (
                <button
                  key={i.name}
                  id={optId}
                  type="button"
                  role="option"
                  aria-selected={active}
                  onClick={() => commit(i.name)}
                  className={cn(
                    'flex w-full items-center gap-3 px-3 py-2 text-left',
                    'transition-colors',
                    active && 'bg-accent',
                    highlighted && cn('bg-accent', 'outline-2 -outline-offset-2 outline-focus'),
                    !active && !highlighted && 'hover:bg-accent',
                  )}
                >
                  <KindBadge kind={i.kind} />
                  <div className="min-w-0 flex-1">
                    <code
                      title={i.name}
                      className="block truncate font-mono text-13 text-foreground"
                    >
                      {i.name}
                    </code>
                  </div>
                  <span className="font-mono text-11 tabular-nums text-muted-foreground">
                    {i.doc_count.toLocaleString()} docs
                  </span>
                  {ranges[i.name] ? (
                    <span
                      className="font-mono text-11 tabular-nums text-fg-faint"
                      title={t('dataRangeTitle', { size: i.store_size })}
                    >
                      {formatRange(ranges[i.name])}
                    </span>
                  ) : (
                    <span className="font-mono text-11 text-fg-faint">{i.store_size}</span>
                  )}
                </button>
              )
            })}
          </div>

          <div className="flex items-center justify-between gap-2 px-3 py-2 [box-shadow:0_-1px_0_var(--color-line)_inset]">
            <span className="font-mono text-11 text-muted-foreground">
              {t('nTargets', { n: indices.length })}
            </span>
          </div>
        </div>,
        document.body,
      )}
    </div>
  )
}

function KindBadge({ kind }: { kind: IndexEntry['kind'] }) {
  const tone =
    kind === 'data_stream'
      ? 'bg-info-subtle text-info-foreground'
      : kind === 'alias'
        ? 'bg-warning-subtle text-warning'
        : 'bg-secondary text-fg-muted'
  const label =
    kind === 'data_stream' ? 'DS' : kind === 'alias' ? 'ALIAS' : 'IDX'
  return (
    <span
      className={cn(
        'inline-flex shrink-0 items-center justify-center rounded-md',
        'px-1.5 py-0.5 font-mono text-[9px] font-semibold tracking-wider',
        tone,
      )}
      style={{ minWidth: 32 }}
    >
      {label}
    </span>
  )
}
