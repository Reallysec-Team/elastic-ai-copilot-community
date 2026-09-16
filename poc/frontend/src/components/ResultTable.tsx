import { useEffect, useMemo, useState, type KeyboardEvent } from 'react'
import { HugeiconsIcon } from '@hugeicons/react'
import { Cancel01Icon, ChevronDownIcon, ChevronRightIcon, CopyIcon, Download01Icon, LayoutThreeColumnIcon, ShieldAlertIcon, SparklesIcon } from '@hugeicons/core-free-icons'
import {
  useTable, type ColumnDef, type PaginationState, type RowSelectionState, type SortingState,
  type ColumnVisibilityState,
} from '@tanstack/react-table'
import type { ExecuteResponse } from '@/lib/api'
import { DataGrid, dataGridFeatures, type DataGridFeatures } from '@/components/reui/data-grid/data-grid'
import { DataGridColumnHeader } from '@/components/reui/data-grid/data-grid-column-header'
import { DataGridPagination } from '@/components/reui/data-grid/data-grid-pagination'
import { DataGridScrollArea } from '@/components/reui/data-grid/data-grid-scroll-area'
import {
  DataGridTable, DataGridTableRowSelect, DataGridTableRowSelectAll,
} from '@/components/reui/data-grid/data-grid-table'
import { Button } from '@/components/ui/button'
import { Checkbox } from '@/components/ui/checkbox'
import { Input } from '@/components/ui/input'
import { Popover, PopoverContent, PopoverTrigger } from '@/components/ui/popover'
import { aggBucketsToCsv, downloadCsv, hitsToCsv } from '@/lib/csv'
import { subAggCols, subAggValue } from '@/lib/subAgg'
import { copyText } from '@/lib/clipboard'
import { hitKey } from '@/lib/hitKey'
import { getColumns, getPrefs, saveColumns, savePref } from '@/lib/prefs'
import { useT, translate } from '@/lib/i18n'
import { cn } from '@/lib/utils'
import { commonCopy } from '@/locales/common'
import { componentsCopy } from '@/locales/components'

const PREFERRED_COLUMNS = [
  '@timestamp',
  'clientip',
  'request',
  'response',
  'bytes',
  'geo.src',
]

const PAGE_SIZES = [25, 50, 100] as const

export type SortDir = 'asc' | 'desc'

function getNested(obj: Record<string, unknown>, path: string): unknown {
  const parts = path.split('.')
  let cur: unknown = obj
  for (const p of parts) {
    if (cur && typeof cur === 'object' && p in (cur as object)) {
      cur = (cur as Record<string, unknown>)[p]
    } else {
      return undefined
    }
  }
  return cur
}

function formatCell(v: unknown): string {
  if (v == null) return ''
  if (typeof v === 'string') return v
  if (typeof v === 'number' || typeof v === 'boolean') return String(v)
  if (Array.isArray(v)) return v.map(formatCell).join(', ')
  return JSON.stringify(v)
}

// Strings longer than this look like analyzed text (message / request / agent),
// which ES refuses to sort on without fielddata — disable header sort for them.
const SORT_STRLEN_MAX = 48
// How many hits to sample when judging a column's sortability (perf cap).
const SORT_SAMPLE = 50
// Field names that are conventionally keyword/numeric/date even when we can't
// see a value to judge (e.g. the sampled rows were all null for that column).
const KEYWORDISH_NAME =
  /(^|\.)(@?timestamp|.*time|.*date|.*_at|status|response|code|level|severity|priority|action|method|verb|result|outcome|state|type|category|tag|host|hostname|service|env|environment|region|zone|country|city|user|username|account|id|uid|sid|pid|port|count|total|sum|bytes|size|length|duration|latency|score|rank|age|version|price|amount|rate)$/i

/** True for ISO-ish date strings or epoch timestamps — safely sortable. */
function looksDateLike(s: string): boolean {
  return /^\d{4}-\d{2}-\d{2}[T ]/.test(s) || /^\d{10,13}$/.test(s)
}

/**
 * Decide whether a column can be pushed down as an ES sort without tripping a
 * fielddata error. Heuristic, by design: numbers/booleans/dates and `.keyword`
 * fields are sortable; objects/arrays and long free-text strings are not; when
 * we have no value to judge we fall back to a field-name convention.
 */
function isSortableColumn(col: string, sample: { _source?: Record<string, unknown> }[]): boolean {
  if (col.endsWith('.keyword')) return true
  let sawValue = false
  let maxLen = 0
  for (const h of sample) {
    const v = getNested(h._source ?? {}, col)
    if (v == null) continue
    sawValue = true
    if (typeof v === 'object') return false // object / array → not sortable
    if (typeof v === 'number' || typeof v === 'boolean') continue
    if (typeof v === 'string') {
      if (looksDateLike(v)) continue
      if (v.length > maxLen) maxLen = v.length
    }
  }
  if (!sawValue) return KEYWORDISH_NAME.test(col)
  return maxLen <= SORT_STRLEN_MAX
}

/** Compare two cell values — numeric when both parse as numbers, else lexical. */
function compareCells(a: unknown, b: unknown): number {
  const an = typeof a === 'number' ? a : Number(a)
  const bn = typeof b === 'number' ? b : Number(b)
  const aNum = a !== '' && a != null && !Number.isNaN(an)
  const bNum = b !== '' && b != null && !Number.isNaN(bn)
  if (aNum && bNum) return an - bn
  return formatCell(a).localeCompare(formatCell(b))
}

interface ResultTableProps {
  response: ExecuteResponse
  onExplain?: (doc: Record<string, unknown>) => void
  onInvestigate?: (doc: Record<string, unknown>) => void
  /**
   * When provided, clicking a column header pushes the sort down to ES (real
   * top-N over the whole result set) instead of sorting only the fetched page.
   * The parent re-executes with the sort injected into the DSL.
   */
  onServerSort?: (col: string, dir: SortDir | null) => void
  /** The sort currently applied server-side, so the header reflects it. */
  serverSort?: { col: string; dir: SortDir } | null
  /** When set (the index name), remembers this surface's column set + page size. */
  prefKey?: string
  /**
   * Drill into one aggregation bucket — re-run the query filtered to that
   * bucket so the analyst gets raw hits (and with them 解释 / 调查 / 分诊).
   * Without this an aggregation-only answer is a dead-end table of numbers.
   * `nextKey` is the following bucket's key, used to bound a histogram bucket.
   */
  onDrill?: (aggName: string, bucket: Record<string, unknown>, nextKey?: unknown) => void
}

type Hit = { _id?: string; _index?: string; _source?: Record<string, unknown> }

/*
 * 命中文档表。表体是 ReUI DataGrid（TanStack v9），原来手写的 <table> 搬过来时
 * 逐条保留的行为：
 *
 * - 列集合：所有命中里见过的字段（`walkKeys`），常用列排前；默认显示这个索引
 *   存过的列集（和本次结果取交集），否则前 8 列。列选择器带搜索 / 全选 / 恢复
 *   默认，DataGrid 自带的 ColumnVisibility 没有搜索，ES 文档动辄上百个字段，
 *   所以自己的 `ColumnPicker` 留着，只是换成 Popover。
 * - 排序：只有看起来是数字 / keyword / 日期的列可排（`isSortableColumn`），
 *   分析型长文本推到 ES 会 400。有 `onServerSort` 时是 manualSorting——ES 已经
 *   排好，表头只反映 `serverSort`；否则客户端按 `compareCells` 排。
 *   点击循环 asc → desc → 清除。
 * - 分页 25 / 50 / 100，存进 prefs；新响应到达重置到第一页。
 * - 多选：行 key 是索引限定的 `_id`（`hitKey`），重跑 / 排序后仍能对上；
 *   重跑后只保留还在的行，没有稳定 id 时清空。批量条：复制 JSON（带成功 /
 *   失败提示）、导出 CSV、清除。
 * - 行动作：解释 / 调查；键盘 ↑↓ 在行间移动焦点，Enter 解释，I 调查
 *   （DataGrid 的行不收 onKeyDown，这段挂在容器上代理）。
 * - 有聚合就先画聚合（桶是答案，文档是证据）。
 */
export function ResultTable({
  response,
  onExplain,
  onInvestigate,
  onServerSort,
  serverSort,
  prefKey,
  onDrill,
}: ResultTableProps) {
  const t = useT(componentsCopy)
  const hits = useMemo(() => response.hits?.hits ?? [], [response])
  const aggs = response.aggregations
  const showActions = !!(onExplain || onInvestigate)

  // Every field seen across all hits (not capped — feeds the column picker).
  const allColumns = useMemo(() => {
    if (hits.length === 0) return []
    const seen = new Set<string>()
    const all: string[] = []
    for (const h of hits) walkKeys(h._source ?? {}, '', seen, all)
    const preferred = PREFERRED_COLUMNS.filter((c) => seen.has(c))
    const rest = all.filter((c) => !preferred.includes(c))
    return [...preferred, ...rest]
  }, [hits])

  // Default visible set = preferred + first others, capped at 8. Fewer columns
  // by default keeps rows readable; users add more via the column picker.
  // Prefer the user's saved column set for this index (intersected with what
  // the current result actually has); otherwise the first 8 columns.
  const defaultVisible = useMemo(() => {
    const saved = prefKey ? getColumns(prefKey) : null
    if (saved) {
      const inter = allColumns.filter((c) => saved.includes(c))
      if (inter.length) return inter
    }
    return allColumns.slice(0, 8)
  }, [allColumns, prefKey])
  const [visible, setVisible] = useState<string[]>(defaultVisible)
  const [sorting, setSorting] = useState<SortingState>([])
  const [pagination, setPagination] = useState<PaginationState>(() => {
    const p = getPrefs().pageSize
    return { pageIndex: 0, pageSize: p && (PAGE_SIZES as readonly number[]).includes(p) ? p : PAGE_SIZES[0] }
  })
  const [rowSelection, setRowSelection] = useState<RowSelectionState>({})
  const [copyNote, setCopyNote] = useState<string | null>(null)

  // When a fresh response arrives, reset the view (columns / sort / page).
  useEffect(() => {
    // eslint-disable-next-line react-hooks/set-state-in-effect -- reset view when a fresh response arrives
    setVisible(defaultVisible)
    setSorting([])
    setPagination((p) => ({ ...p, pageIndex: 0 }))
  }, [defaultVisible])

  // Preserve row selection across re-executes / sorts: keep the entries whose
  // stable `_id` is still present, drop the ones that vanished. Only clear
  // outright when the rows carry no stable id (selection can't be re-matched).
  useEffect(() => {
    const validKeys = new Set<string>()
    let hasStableId = false
    hits.forEach((h, i) => {
      if (h._id != null) hasStableId = true
      validKeys.add(hitKey(h, i))
    })
    // eslint-disable-next-line react-hooks/set-state-in-effect -- prune selection to the rows that survived a re-execute
    setRowSelection((cur) => {
      const keys = Object.keys(cur)
      if (keys.length === 0) return cur
      if (!hasStableId) return {}
      const next: RowSelectionState = {}
      for (const k of keys) if (validKeys.has(k)) next[k] = true
      return Object.keys(next).length === keys.length ? cur : next
    })
  }, [hits])

  // Server-sort mode: ES already returned the rows in order, so don't re-sort
  // client-side, and drive the header indicator from the parent's serverSort.
  const serverMode = !!onServerSort
  const activeSorting = useMemo<SortingState>(
    () => (serverMode ? (serverSort ? [{ id: serverSort.col, desc: serverSort.dir === 'desc' }] : []) : sorting),
    [serverMode, serverSort, sorting],
  )

  // Which columns may be sorted (header clickable). Sorting an analyzed
  // text / geo field pushes an ES sort that 400s on fielddata, so we only open
  // sort on columns that look numeric / keyword / date.
  const sortableCols = useMemo(() => {
    const sample = hits.slice(0, SORT_SAMPLE)
    const m = new Map<string, boolean>()
    for (const c of allColumns) m.set(c, isSortableColumn(c, sample))
    return m
  }, [allColumns, hits])

  const columns = useMemo<ColumnDef<DataGridFeatures, Hit>[]>(() => {
    const defs: ColumnDef<DataGridFeatures, Hit>[] = [
      {
        id: 'select',
        header: () => <DataGridTableRowSelectAll />,
        cell: ({ row }) => <DataGridTableRowSelect row={row} />,
        enableSorting: false,
        enableHiding: false,
        enableResizing: false,
        size: 40,
      },
      ...allColumns.map<ColumnDef<DataGridFeatures, Hit>>((c) => ({
        id: c,
        accessorFn: (h) => getNested(h._source ?? {}, c),
        // 外面那层 span 只为挂 title：鼠标停上去说清为什么这列点不动
        // （分析型文本推 ES 排序会 400）。DataGridColumnHeader 的 title 是列名。
        header: ({ column }) => (
          <span className="contents" title={sortableCols.get(c) ? t('clickToSort') : t('notSortable')}>
            <DataGridColumnHeader title={c} column={column} className="font-mono text-11" />
          </span>
        ),
        cell: ({ getValue }) => <CellValue value={getValue()} />,
        enableSorting: sortableCols.get(c) ?? false,
        sortingFn: (a: { getValue: (id: string) => unknown }, b: { getValue: (id: string) => unknown }) => compareCells(a.getValue(c), b.getValue(c)),
        minSize: 96,
        maxSize: 420,
        meta: { headerTitle: c, cellClassName: 'align-top text-13 leading-[1.55]' },
      })),
    ]
    if (showActions) {
      defs.push({
        id: 'actions',
        header: () => <span className="font-mono text-11">{t('colActions')}</span>,
        cell: ({ row }) => {
          const doc = row.original._source ?? {}
          return (
            <div className="inline-flex items-center gap-1 whitespace-nowrap">
              {onExplain && (
                <Button variant="outline" size="xs" onClick={() => onExplain(doc)} title={t('explainWithAi')}>
                  <HugeiconsIcon icon={SparklesIcon} strokeWidth={2} className="size-3.5" />
                  <span className="hidden sm:inline">{t('explain')}</span>
                </Button>
              )}
              {onInvestigate && (
                // Elevated over 解释: 调查 is the primary security next-step,
                // so it carries the ship tint by default instead of only on
                // hover — the funnel the NextStepStrip points at.
                <Button
                  variant="outline"
                  size="xs"
                  onClick={() => onInvestigate(doc)}
                  title={t('investigateAsAlert')}
                  className="border-destructive/20 bg-destructive/8 text-destructive hover:bg-destructive/16 hover:text-destructive"
                >
                  <HugeiconsIcon icon={ShieldAlertIcon} strokeWidth={2} className="size-3.5" />
                  <span className="hidden sm:inline">{t('investigate')}</span>
                </Button>
              )}
            </div>
          )
        },
        enableSorting: false,
        enableHiding: false,
        meta: { headerClassName: 'text-right', cellClassName: 'text-right' },
      })
    }
    return defs
  }, [allColumns, sortableCols, showActions, onExplain, onInvestigate, t])

  const columnVisibility = useMemo<ColumnVisibilityState>(() => {
    const v: ColumnVisibilityState = {}
    for (const c of allColumns) v[c] = visible.includes(c)
    return v
  }, [allColumns, visible])

  const keyOf = (h: Hit, i: number) => hitKey(h, i)

  const table = useTable({
    features: dataGridFeatures,
    columns,
    data: hits,
    getRowId: (row, index) => keyOf(row, index),
    state: { sorting: activeSorting, pagination, rowSelection, columnVisibility },
    enableRowSelection: true,
    enableSortingRemoval: true,
    manualSorting: serverMode,
    autoResetPageIndex: false,
    onSortingChange: (updater) => {
      const next = typeof updater === 'function' ? updater(activeSorting) : updater
      if (serverMode) {
        const s = next[0]
        onServerSort!(s ? s.id : (activeSorting[0]?.id ?? ''), s ? (s.desc ? 'desc' : 'asc') : null)
      } else {
        setSorting(next)
      }
    },
    onPaginationChange: (updater) => {
      setPagination((cur) => {
        const next = typeof updater === 'function' ? updater(cur) : updater
        if (next.pageSize !== cur.pageSize) savePref({ pageSize: next.pageSize })
        return next
      })
    },
    onRowSelectionChange: setRowSelection,
  })

  const selectedHits = table.getSelectedRowModel().rows.map((r) => r.original)
  const selectedCount = selectedHits.length

  function copySelected() {
    const docs = selectedHits.map((h) => h._source ?? {})
    // Had no success indicator AND no failure path: on an http:// gateway the
    // Clipboard API is absent, the optional chain swallowed it, and the analyst
    // pasted stale content into a ticket believing the copy worked.
    void copyText(JSON.stringify(docs, null, 2))
      .then(() => {
        setCopyNote(translate(commonCopy, 'copied'))
        window.setTimeout(() => setCopyNote(null), 2000)
      })
      .catch((e: unknown) => {
        setCopyNote(e instanceof Error ? e.message : translate(componentsCopy, 'copyFailed'))
        window.setTimeout(() => setCopyNote(null), 4000)
      })
  }

  function exportSelected() {
    const ts = new Date().toISOString().replace(/[:.]/g, '-')
    downloadCsv(`selection-${ts}.csv`, hitsToCsv(selectedHits))
  }

  /* 键盘：↑↓ 在行之间移动焦点（落到那一行的第一个可聚焦控件——多选框），
     Enter 解释、I 调查当前行。DataGrid 的行本身不可聚焦、也不收 onKeyDown，
     所以在容器上代理，按 data-row-id 找回文档。 */
  function onGridKeyDown(e: KeyboardEvent<HTMLDivElement>) {
    const tr = (e.target as HTMLElement).closest('tr')
    if (!tr || !tr.parentElement || tr.parentElement.tagName !== 'TBODY') return
    if (e.key === 'ArrowDown' || e.key === 'ArrowUp') {
      const sib = (e.key === 'ArrowDown' ? tr.nextElementSibling : tr.previousElementSibling) as HTMLElement | null
      const focusable = sib?.querySelector<HTMLElement>('button, [tabindex="0"], input')
      if (focusable) {
        e.preventDefault()
        focusable.focus()
      }
      return
    }
    // 行动作按钮上的 Enter 让按钮自己处理；多选框（role=checkbox 的 button）不算。
    const el = e.target as HTMLElement
    if (el.tagName === 'BUTTON' && el.getAttribute('role') !== 'checkbox' && e.key === 'Enter') return
    const rowIdx = Array.from(tr.parentElement.children).indexOf(tr)
    const row = table.getRowModel().rows[rowIdx]
    if (!row) return
    if (e.key === 'Enter' && onExplain) {
      e.preventDefault()
      onExplain(row.original._source ?? {})
    } else if ((e.key === 'i' || e.key === 'I') && onInvestigate) {
      e.preventDefault()
      onInvestigate(row.original._source ?? {})
    }
  }

  if (hits.length === 0 && aggs) return <AggregationView aggs={aggs} onDrill={onDrill} />
  if (hits.length === 0) {
    return (
      <div className="px-5 py-12 text-center">
        <div className="text-14 text-foreground">{t('noDocs')}</div>
        <div className="mx-auto mt-2 max-w-[440px] text-13 leading-[1.6] text-muted-foreground">
          {t('noDocsHint')}
        </div>
      </div>
    )
  }

  return (
    <div>
      {/* A DSL that asks for buckets AND keeps a sample (size:20 + aggs) used to
          render only the sample: the aggregation branch above requires zero
          hits. So "按 source.ip 聚合，定位高频失败地址" computed the answer and
          then showed 25 rows of raw logs instead. The buckets are the answer,
          the documents are the evidence — show both, answer first. */}
      {aggs && <AggregationView aggs={aggs} onDrill={onDrill} />}

      <DataGrid
        table={table}
        recordCount={hits.length}
        tableLayout={{ dense: true, rowBorder: true, headerSticky: true, columnsResizable: false, columnsMovable: false, columnsVisibility: true }}
        tableClassNames={{ edgeCell: 'first:ps-3 last:pe-3' }}
      >
        {/* Toolbar */}
        <div className="flex flex-wrap items-center justify-between gap-3 px-4 py-2 [box-shadow:0_-1px_0_var(--color-line)_inset]">
          <ColumnPicker
            all={allColumns}
            visible={visible}
            onChange={(cols) => {
              setVisible(cols)
              if (prefKey) saveColumns(prefKey, cols)
            }}
          />
          <DataGridPagination
            sizes={[...PAGE_SIZES]}
            info={t('paginationInfo')}
            rowsPerPageLabel={t('perPage')}
            previousPageLabel={t('prevPage')}
            nextPageLabel={t('nextPage')}
            className="py-0"
          />
        </div>

        {/* Batch action bar — appears once rows are selected */}
        {selectedCount > 0 && (
          <div className="flex items-center gap-2 bg-accent px-4 py-2 [box-shadow:0_-1px_0_var(--color-line)_inset]">
            <span className="font-mono text-12 text-foreground">
              {t('selectedRows', { n: selectedCount })}
            </span>
            <Button variant="outline" size="xs" onClick={copySelected}>
              <HugeiconsIcon icon={CopyIcon} strokeWidth={2} className="size-3.5" /> {t('copyJson')}
            </Button>
            {copyNote && <span className="text-12 text-muted-foreground">{copyNote}</span>}
            <Button variant="outline" size="xs" onClick={exportSelected}>
              <HugeiconsIcon icon={Download01Icon} strokeWidth={2} className="size-3.5" /> {t('exportCsv')}
            </Button>
            <Button variant="ghost" size="xs" className="ml-auto text-muted-foreground" onClick={() => setRowSelection({})}>
              <HugeiconsIcon icon={Cancel01Icon} strokeWidth={2} className="size-3.5" /> {t('clear')}
            </Button>
          </div>
        )}

        <div onKeyDown={onGridKeyDown}>
          <DataGridScrollArea>
            <DataGridTable />
          </DataGridScrollArea>
        </div>
      </DataGrid>
    </div>
  )
}

function ColumnPicker({
  all,
  visible,
  onChange,
}: {
  all: string[]
  visible: string[]
  onChange: (next: string[]) => void
}) {
  const t = useT(componentsCopy)
  const [filter, setFilter] = useState('')

  const shown = all.filter((c) => c.toLowerCase().includes(filter.trim().toLowerCase()))

  function toggle(col: string) {
    if (visible.includes(col)) {
      // keep at least one column
      if (visible.length > 1) onChange(visible.filter((c) => c !== col))
    } else {
      // preserve canonical (all) order
      onChange(all.filter((c) => c === col || visible.includes(c)))
    }
  }

  return (
    <Popover>
      <PopoverTrigger render={<Button variant="outline" size="xs" />}>
        <HugeiconsIcon icon={LayoutThreeColumnIcon} strokeWidth={2} className="size-3.5 text-muted-foreground" />
        {t('columnsCount', { shown: visible.length, total: all.length })}
        <HugeiconsIcon icon={ChevronDownIcon} strokeWidth={2} className="size-3 text-muted-foreground" />
      </PopoverTrigger>
      <PopoverContent align="start" className="w-[280px] p-0">
        <div className="border-b px-2 py-2">
          <Input
            value={filter}
            onChange={(e) => setFilter(e.target.value)}
            placeholder={t('filterFields')}
            aria-label={t('filterFields')}
            className="h-7 text-12"
            autoFocus
          />
        </div>
        <div className="max-h-[300px] overflow-y-auto p-1.5">
          {shown.length === 0 ? (
            <div className="px-2.5 py-4 text-center text-12 text-muted-foreground">
              {t('noMatchingField')}
            </div>
          ) : (
            shown.map((c) => {
              const on = visible.includes(c)
              return (
                <label
                  key={c}
                  className="flex w-full cursor-pointer items-center gap-2.5 rounded-md px-2.5 py-1.5 text-left transition-colors hover:bg-accent"
                >
                  <Checkbox checked={on} onCheckedChange={() => toggle(c)} aria-label={c} />
                  <code className="truncate font-mono text-12 text-foreground">{c}</code>
                </label>
              )
            })
          )}
        </div>
        <div className="flex items-center justify-between gap-2 border-t px-3 py-2">
          <Button variant="link" size="xs" className="h-auto p-0 text-11" onClick={() => onChange(all)}>
            {t('selectAll')}
          </Button>
          <Button variant="link" size="xs" className="h-auto p-0 text-11 text-muted-foreground" onClick={() => onChange(all.slice(0, 8))}>
            {t('restoreDefault')}
          </Button>
        </div>
      </PopoverContent>
    </Popover>
  )
}

function walkKeys(
  obj: Record<string, unknown>,
  prefix: string,
  seen: Set<string>,
  out: string[],
  depth = 0,
) {
  if (depth > 3) return
  for (const [k, v] of Object.entries(obj)) {
    const path = prefix ? `${prefix}.${k}` : k
    if (v && typeof v === 'object' && !Array.isArray(v)) {
      walkKeys(v as Record<string, unknown>, path, seen, out, depth + 1)
    } else {
      if (!seen.has(path)) {
        seen.add(path)
        out.push(path)
      }
    }
  }
}

function CellValue({ value }: { value: unknown }) {
  const text = formatCell(value)
  if (!text) return <span className="text-fg-faint">—</span>
  // Long blobs (JSON, stack traces) stay expandable so they don't dominate.
  if (text.length > 120) return <ExpandableCell text={text} />
  // Everything else renders on a single line, bounded by the cell's max-width,
  // truncated with an ellipsis; the full value shows on hover (native tooltip).
  const numeric = typeof value === 'number'
  return (
    <span
      className={cn('block max-w-[420px] truncate', numeric && 'tabular-nums')}
      title={text}
    >
      {text}
    </span>
  )
}

function ExpandableCell({ text }: { text: string }) {
  const t = useT(componentsCopy)
  const [open, setOpen] = useState(false)
  if (!open) {
    return (
      <button
        className="block max-w-[420px] truncate text-left text-foreground hover:underline"
        title={text}
        onClick={() => setOpen(true)}
      >
        {text.slice(0, 100)}…
      </button>
    )
  }
  return (
    <div className="max-w-[560px] space-y-1">
      <div className="font-mono text-12 leading-[1.5] break-all">{text}</div>
      <button
        className="text-11 text-link hover:underline"
        onClick={() => setOpen(false)}
      >
        {t('collapse')}
      </button>
    </div>
  )
}

const AGG_TH = 'px-4 py-2 font-mono text-11 font-medium uppercase tracking-wide text-muted-foreground'
const AGG_BUCKET_CAP = 200

function fmtNum(v: unknown): string {
  if (typeof v === 'number') return Number.isInteger(v) ? v.toLocaleString() : v.toFixed(2)
  if (v == null) return '—'
  return String(v)
}

/* Render aggregations as compact key/count tables instead of raw JSON. Handles
 * the common shapes (terms / date_histogram buckets, single-value metrics,
 * percentiles); falls back to JSON for anything exotic so nothing is hidden. */
function AggregationView({
  aggs,
  onDrill,
}: {
  aggs: Record<string, unknown>
  onDrill?: ResultTableProps['onDrill']
}) {
  return (
    <div className="space-y-6 px-5 py-5">
      {Object.entries(aggs).map(([name, body]) => (
        <AggBlock key={name} name={name} body={body} onDrill={onDrill} />
      ))}
    </div>
  )
}

function AggBlock({
  name,
  body,
  onDrill,
}: {
  name: string
  body: unknown
  onDrill?: ResultTableProps['onDrill']
}) {
  const t = useT(componentsCopy)
  const b = (body ?? {}) as Record<string, unknown>
  const buckets = Array.isArray(b.buckets) ? (b.buckets as Record<string, unknown>[]) : null

  if (buckets) {
    // Numeric sub-aggregation columns (besides the implicit doc_count), unioned
    // over every bucket — see subAggCols. `nested` is what we can't put in a
    // cell; it gets said out loud below rather than disappearing.
    const { cols: subCols, nested } = subAggCols(buckets)
    const shown = buckets.slice(0, AGG_BUCKET_CAP)
    // An in-cell bar makes the shape readable. "5xx 哪个时段爆发" returned 156
    // rows of 0 and 1 — the answer was in there, but finding the spike meant
    // reading every row. Scaled to the largest bucket ON SCREEN, so a capped
    // list still shows the right relative heights.
    const maxCount = Math.max(1, ...shown.map((b) => Number(b.doc_count) || 0))
    return (
      <div>
        <div className="mb-2 flex items-center justify-between gap-3">
          <span className="flex items-baseline gap-2">
            <span className="label-mono">{name}</span>
            {/* Only advertise drilling when there is a row to drill into — an
                empty aggregation used to show the hint over a header-only
                table. */}
            {onDrill && shown.length > 0 && (
              <span className="text-12 text-muted-foreground">{t('drillHint')}</span>
            )}
          </span>
          <button
            type="button"
            onClick={() => {
              const ts = new Date().toISOString().replace(/[:.]/g, '-').slice(0, 19)
              const safeName = name.replace(/[\\/<>:"|?*]+/g, '_')
              downloadCsv(`agg-${safeName}-${ts}.csv`, aggBucketsToCsv(buckets, subCols))
            }}
            className="inline-flex items-center gap-1 rounded-md px-2 py-1 text-12 font-medium text-muted-foreground [box-shadow:var(--shadow-ring-light)] transition-colors hover:text-foreground"
            title={t('exportBucketsTitle')}
          >
            <HugeiconsIcon icon={Download01Icon} strokeWidth={2} className="size-3.5" /> {t('exportCsv')}
          </button>
        </div>
        <div className="overflow-x-auto rounded-lg [box-shadow:var(--shadow-ring-light)]">
          <table className="w-full border-collapse text-13">
            <thead>
              <tr className="[box-shadow:0_-1px_0_var(--color-line)_inset]">
                {/* 表头原来是 key / doc_count（AGG_TH 还会转成大写）——那是 ES 的
                    字段名，这张表是给看结果的人的。子聚合那几列保留原名，因为它们
                    是用户自己在 DSL 里起的名字。 */}
                <th scope="col" className={cn(AGG_TH, 'text-left')}>{t('aggGroup')}</th>
                <th scope="col" className={cn(AGG_TH, 'text-right')}>{t('aggCount')}</th>
                {subCols.map((c) => (
                  <th scope="col" key={c} className={cn(AGG_TH, 'text-right')}>{c}</th>
                ))}
              </tr>
            </thead>
            <tbody>
              {shown.map((bk, i) => (
                <tr key={i} className="[box-shadow:0_-1px_0_var(--color-line)_inset]">
                  <td className="px-4 py-2 align-top text-foreground">
                    {onDrill ? (
                      <button
                        type="button"
                        onClick={() => onDrill(name, bk, buckets[i + 1]?.key)}
                        className={cn(
                          'group inline-flex items-center gap-1 rounded-md px-1 py-0.5 -mx-1',
                          'text-left text-info transition-colors',
                          'hover:bg-info/10',
                        )}
                        title={t('drillTitle')}
                      >
                        {String(bk.key_as_string ?? bk.key)}
                        <HugeiconsIcon icon={ChevronRightIcon} strokeWidth={2} className="size-3.5 opacity-0 transition-opacity group-hover:opacity-70" />
                      </button>
                    ) : (
                      String(bk.key_as_string ?? bk.key)
                    )}
                  </td>
                  <td className="relative px-4 py-2 text-right align-top tabular-nums text-foreground">
                    <span
                      aria-hidden
                      className="pointer-events-none absolute inset-y-1 right-0 rounded-sm bg-info/15"
                      style={{ width: `${((Number(bk.doc_count) || 0) / maxCount) * 100}%` }}
                    />
                    <span className="relative">{fmtNum(bk.doc_count)}</span>
                  </td>
                  {subCols.map((c) => (
                    <td key={c} className="px-4 py-2 text-right align-top tabular-nums text-foreground">
                      {fmtNum(subAggValue(bk[c]))}
                    </td>
                  ))}
                </tr>
              ))}
            </tbody>
          </table>
        </div>
        {buckets.length > shown.length && (
          <div className="px-1 pt-2 text-12 text-muted-foreground">
            {t('bucketsHidden', { n: (buckets.length - shown.length).toLocaleString() })}
          </div>
        )}
        {nested.length > 0 && (
          <div className="px-1 pt-2 text-12 text-muted-foreground">
            {t('nestedAggNote', { names: nested.join(', ') })}
          </div>
        )}
      </div>
    )
  }

  // Single-value metric (sum / avg / max / min / cardinality / value_count).
  if (typeof b.value === 'number') {
    return (
      <div className="flex items-baseline gap-3">
        <span className="label-mono">{name}</span>
        <span className="text-18 font-semibold tabular-nums text-foreground">
          {b.value.toLocaleString()}
        </span>
      </div>
    )
  }

  // Multi-value metric (percentiles / stats.values).
  if (b.values && typeof b.values === 'object') {
    return (
      <div>
        <div className="label-mono mb-2">{name}</div>
        <div className="flex flex-wrap gap-x-6 gap-y-1">
          {Object.entries(b.values as Record<string, unknown>).map(([k, v]) => (
            <span key={k} className="text-13 tabular-nums text-foreground">
              <span className="text-muted-foreground">{k}</span> {fmtNum(v)}
            </span>
          ))}
        </div>
      </div>
    )
  }

  // Unknown shape — keep the raw JSON so nothing is silently dropped.
  return (
    <div>
      <div className="label-mono mb-2">{name}</div>
      <pre
        className={cn(
          'overflow-x-auto rounded-lg bg-accent p-4',
          'font-mono text-12 leading-[1.5] text-foreground',
          '[box-shadow:var(--shadow-ring-light)]',
        )}
      >
        {JSON.stringify(body, null, 2)}
      </pre>
    </div>
  )
}
