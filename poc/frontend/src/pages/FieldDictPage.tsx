import { useEffect, useMemo, useState } from 'react'
import { HugeiconsIcon } from '@hugeicons/react'
import {
  Analytics01Icon, Cancel01Icon, CopyIcon, Loading03Icon, Search01Icon, SendIcon,
  SparklesIcon, Table01Icon, TriangleAlertIcon,
} from '@hugeicons/core-free-icons'
import { toast } from 'sonner'
import { useTable, type ColumnDef, type PaginationState } from '@tanstack/react-table'

import { api, type ApiError } from '@/lib/api'
import { cachedDefaultIndex, resolveDefaultIndex } from '@/lib/defaultIndex'
import { setPending } from '@/lib/history'
import { useT, translate, type Translate } from '@/lib/i18n'
import { fieldDictCopy, type FieldDictKey } from '@/locales/fieldDict'
import { cn } from '@/lib/utils'
import { IndexCombobox } from '@/components/IndexCombobox'
import { MixDonut, type DonutSlice } from '@/components/blocks/chart-13/components/mix-donut'
import { StatCards, type StatCard } from '@/components/blocks/dashboard-1/components/stat-cards'
import { Alert, AlertDescription } from '@/components/reui/alert'
import { Badge } from '@/components/reui/badge'
import {
  DataGrid, dataGridFeatures, type DataGridFeatures,
} from '@/components/reui/data-grid/data-grid'
import { DataGridColumnHeader } from '@/components/reui/data-grid/data-grid-column-header'
import { DataGridPagination } from '@/components/reui/data-grid/data-grid-pagination'
import { DataGridScrollArea } from '@/components/reui/data-grid/data-grid-scroll-area'
import { DataGridTable } from '@/components/reui/data-grid/data-grid-table'
import {
  Frame, FrameFooter, FrameHeader, FramePanel, FrameTitle,
} from '@/components/reui/frame'
import { PageHeader } from '@/components/shell/page-header'
import { Button } from '@/components/ui/button'
import { Empty, EmptyDescription, EmptyHeader, EmptyMedia, EmptyTitle } from '@/components/ui/empty'
import {
  InputGroup, InputGroupAddon, InputGroupButton, InputGroupInput,
} from '@/components/ui/input-group'
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from '@/components/ui/select'
import { Separator } from '@/components/ui/separator'
import { HintTip } from '@/components/hint-tip'

/*
 * 字段字典 —— 扫一个索引的 mapping，给出每个字段的类型、独立值数和样本值，
 * 让人在写问题之前先摸清数据。
 *
 * 版式按 roster 的 `features/approvals`：PageHeader（索引选择 + 扫描按钮在
 * actions 里）+ 一张 Frame 卡（工具条 + data-grid + 分页）。
 *
 * 扫完之后先给一排概览：三格 `StatCards`（文档数 / 扫到的字段数 / 空字段数）
 * 加一个 `MixDonut`（字段类型分布）。它们都按**整份扫描结果**算，不按当前筛选或
 * 当前页 —— 翻页和改类型筛选时这排数字不该跟着变。
 *
 * 「空字段」是这页真正值得先看的一格：mapping 里声明了、采样里一条值都没有。
 * 它把「这个字段读不出来」和「这个字段没有数据」分开，省得有人照着 mapping
 * 写了个永远查不出东西的问题。
 *
 * 自己写的固定定位 toast 也没有了，换成 sonner（依赖本来就在，只是从来没挂过
 * Toaster，见 `components/ui/sonner.tsx`）。
 */

type FieldDictResponse = Awaited<ReturnType<typeof api.fieldDict>>
type FieldRow = FieldDictResponse['fields'][number]
type Phase = 'idle' | 'loading' | 'ready' | 'error'
type TypeBucket = 'all' | 'keyword' | 'text' | 'date' | 'number' | 'other'

const PAGE_SIZE = 25

const SAMPLE_INDICES = [
  'kibana_sample_data_logs',
  'auth-logs-*',
  'nginx-access-*',
  'firewall-*',
]

/* 只有两档需要翻译，其余四档就是 ES 的类型名本身 —— 那不是文案，翻过去反而和
   mapping 对不上。`key` 有值的走文案表，没有的原样显示。 */
const TYPE_FILTERS: { id: TypeBucket; label: string; key?: FieldDictKey }[] = [
  { id: 'all', label: '', key: 'typeAll' },
  { id: 'keyword', label: 'keyword' },
  { id: 'text', label: 'text' },
  { id: 'date', label: 'date' },
  { id: 'number', label: 'long·integer' },
  { id: 'other', label: '', key: 'typeOther' },
]

function typeLabel(t: Translate<FieldDictKey>, f: { label: string; key?: FieldDictKey }): string {
  return f.key ? t(f.key) : f.label
}

const NUMERIC_TYPES = new Set([
  'long', 'integer', 'short', 'byte',
  'double', 'float', 'half_float', 'scaled_float', 'unsigned_long',
])

function bucketOf(type: string): TypeBucket {
  if (type === 'keyword' || type === 'ip') return 'keyword'
  if (type === 'text' || type === 'match_only_text' || type === 'wildcard') return 'text'
  if (type === 'date' || type === 'date_nanos') return 'date'
  if (NUMERIC_TYPES.has(type)) return 'number'
  return 'other'
}

/* 类型的语义配色：keyword 是主键一类的东西，number 能算，date 能排，text 只能
 * 全文匹配。原来是四组字面 CSS 变量，现在走 Badge 的语义 variant。 */
const TYPE_VARIANT: Record<TypeBucket, 'primary-light' | 'success-light' | 'warning-light' | 'secondary'> = {
  all: 'secondary',
  keyword: 'primary-light',
  number: 'success-light',
  date: 'warning-light',
  text: 'secondary',
  other: 'secondary',
}

function formatSampleValue(v: unknown): string {
  if (v === null || v === undefined) return 'null'
  if (typeof v === 'string') return v
  if (typeof v === 'number' || typeof v === 'boolean') return String(v)
  try { return JSON.stringify(v) } catch { return String(v) }
}

export function FieldDictPage() {
  const t = useT(fieldDictCopy)
  const [index, setIndex] = useState(cachedDefaultIndex)
  const [phase, setPhase] = useState<Phase>('idle')
  const [errorMsg, setErrorMsg] = useState<string | null>(null)
  const [data, setData] = useState<FieldDictResponse | null>(null)
  const [filterText, setFilterText] = useState('')
  const [activeBucket, setActiveBucket] = useState<TypeBucket>('all')
  const [pagination, setPagination] = useState<PaginationState>({ pageIndex: 0, pageSize: PAGE_SIZE })

  // Fresh install has no saved default — resolve one from the cluster rather
  // than preselecting the Kibana sample index the customer does not have.
  useEffect(() => {
    if (index) return
    let live = true
    void resolveDefaultIndex().then((v) => {
      if (live) setIndex(v)
    })
    return () => {
      live = false
    }
  }, [index])

  async function copyText(text: string) {
    try {
      await navigator.clipboard.writeText(text)
      toast.success(t('copied', { text }))
    } catch {
      toast.error(t('errCopy'))
    }
  }

  async function onScan() {
    const idx = index.trim()
    if (!idx) { setErrorMsg(t('errIndexRequired')); setPhase('error'); return }
    setPhase('loading'); setErrorMsg(null)
    try {
      const r = await api.fieldDict({ index: idx })
      setData(r); setPhase('ready')
      setPagination((p) => ({ ...p, pageIndex: 0 }))
    } catch (e) {
      setErrorMsg((e as ApiError).message || t('errScan')); setPhase('error')
    }
  }

  function onInsertQuestion(field: FieldRow) {
    setPending({
      question: t('aggQuestion', { field: field.name }),
      index: index.trim() || undefined,
    })
    toast.success(t('stagedToQuery'))
  }

  const filtered = useMemo<FieldRow[]>(() => {
    if (!data) return []
    const q = filterText.trim().toLowerCase()
    return data.fields.filter((f) => {
      if (activeBucket !== 'all' && bucketOf(f.type) !== activeBucket) return false
      if (q && !f.name.toLowerCase().includes(q)) return false
      return true
    })
  }, [data, filterText, activeBucket])

  const maxCardinality = useMemo(() => {
    if (!data) return 0
    let m = 0
    for (const f of data.fields) {
      if (typeof f.cardinality_approx === 'number' && f.cardinality_approx > m) m = f.cardinality_approx
    }
    return m
  }, [data])

  const overview = useMemo(() => {
    if (!data) return null
    const byBucket = new Map<TypeBucket, number>()
    let empty = 0
    let top: FieldRow | null = null
    for (const f of data.fields) {
      const b = bucketOf(f.type)
      byBucket.set(b, (byBucket.get(b) ?? 0) + 1)
      if ((f.samples?.length ?? 0) === 0) empty += 1
      if (typeof f.cardinality_approx === 'number'
        && f.cardinality_approx > (top?.cardinality_approx ?? -1)) top = f
    }
    // 类型这套词汇没有自己的颜色刻度（严重度才有），所以走 MixDonut 的默认调色板；
    // 类型和颜色的对应关系在表里由 Badge 说，环只负责分布。
    const slices: DonutSlice[] = TYPE_FILTERS
      .filter((t) => t.id !== 'all')
      .map((f) => ({ key: f.id, name: typeLabel(t, f), count: byBucket.get(f.id) ?? 0 }))
      .filter((s) => s.count > 0)
    return { slices, empty, top }
  }, [data, t])

  // 换筛选就回第一页，否则「第 8 页」会落在只剩 3 页的结果里，看起来像空表。
  useEffect(() => {
    setPagination((p) => (p.pageIndex === 0 ? p : { ...p, pageIndex: 0 }))
  }, [filterText, activeBucket])

  const columns = useMemo<ColumnDef<DataGridFeatures, FieldRow>[]>(
    () =>
      fieldColumns({
        maxCardinality,
        onCopyName: (f) => void copyText(f.name),
        onCopyValue: (f, v) => void copyText(`${f.name}:"${formatSampleValue(v)}"`),
        onInsert: onInsertQuestion,
      }),
    // eslint-disable-next-line react-hooks/exhaustive-deps -- handlers are stable enough; the bar scale is the real input
    [maxCardinality, index],
  )

  const table = useTable({
    features: dataGridFeatures,
    columns,
    data: filtered,
    pageCount: Math.max(1, Math.ceil(filtered.length / pagination.pageSize)),
    getRowId: (row) => row.name,
    autoResetPageIndex: false,
    state: { pagination },
    onPaginationChange: setPagination,
  })

  const isLoading = phase === 'loading'
  const hasResult = phase === 'ready' && data !== null

  return (
    <div className="@container flex w-full flex-col gap-5">
      <PageHeader
        title={t('title')}
        actions={
          <div className="flex w-full items-center gap-2 sm:w-auto">
            <div className="w-full sm:w-[320px]">
              <IndexCombobox
                value={index}
                onChange={setIndex}
                placeholder={t('indexPlaceholder')}
                disabled={isLoading}
              />
            </div>
            <Button className="shrink-0" onClick={() => void onScan()} disabled={isLoading}>
              <HugeiconsIcon
                icon={isLoading ? Loading03Icon : Search01Icon}
                strokeWidth={2}
                className={cn('size-3.5', isLoading && 'animate-spin')}
              />
              {isLoading ? t('scanning') : t('scan')}
            </Button>
          </div>
        }
      />

      {errorMsg && phase === 'error' && (
        <Alert variant="destructive">
          <HugeiconsIcon icon={TriangleAlertIcon} strokeWidth={2} className="size-4" />
          <AlertDescription>{errorMsg}</AlertDescription>
        </Alert>
      )}

      {!hasResult && (
        <Empty>
          <EmptyHeader>
            <EmptyMedia variant="icon">
              <HugeiconsIcon icon={SparklesIcon} strokeWidth={2} />
            </EmptyMedia>
            <EmptyTitle>{t('pickIndexTitle')}</EmptyTitle>
            <EmptyDescription>{t('pickIndexDesc')}</EmptyDescription>
          </EmptyHeader>
          <div className="flex flex-wrap items-center justify-center gap-2">
            {SAMPLE_INDICES.map((s) => (
              <Button key={s} variant="outline" size="sm" className="font-mono" onClick={() => setIndex(s)}>
                {s}
              </Button>
            ))}
          </div>
        </Empty>
      )}

      {/* 四格排成 2×2，高度才和右边的环大致齐。三格排成一行只有环的一半高，
          左边会空出一大片白 —— 试过。 */}
      {hasResult && data && overview && (
        <section
          aria-label={t('secOverview')}
          className="grid auto-rows-fr items-stretch gap-5 @4xl:grid-cols-3"
        >
          <div className="min-w-0 @4xl:col-span-2">
            <StatCards cards={overviewCards(t, data, overview.empty, overview.top)} />
          </div>
          <div className="min-w-0">
            <MixDonut
              title={t('typeMix')}
              centerLabel={t('unitFields')}
              slices={overview.slices}
              emptyText={t('noUsableFields')}
            />
          </div>
        </section>
      )}

      {hasResult && data && (
        <section aria-label={t('secTable')}>
          <DataGrid
            table={table}
            recordCount={filtered.length}
            emptyMessage={t('gridEmpty')}
            tableLayout={{
              dense: true,
              rowBorder: true,
              columnsPinnable: true,
              columnsResizable: false,
              columnsMovable: false,
              columnsVisibility: true,
            }}
            tableClassNames={{
              edgeCell: 'first:ps-(--frame-panel-header-px) last:pe-(--frame-panel-header-px)',
            }}
          >
            <Frame dense spacing="sm" className="flex w-full min-w-0 flex-col [--frame-panel-header-py-adjust:2px]">
              <FrameHeader className="flex-row items-center justify-between gap-3">
                <FrameTitle className="flex items-center gap-1.5">
                  {t('cardTitle')}
                  <HintTip text={t('cardDesc')} />
                </FrameTitle>
              </FrameHeader>

              <FramePanel className="min-h-0 flex-1 bg-card p-0! shadow-none!">
                <div className="flex flex-wrap items-center gap-2 px-3 py-3">
                  <InputGroup className="w-full min-w-48 sm:w-64">
                    <InputGroupAddon align="inline-start">
                      <HugeiconsIcon icon={Search01Icon} strokeWidth={2} aria-hidden="true" />
                    </InputGroupAddon>
                    <InputGroupInput
                      placeholder={t('filterByName')}
                      aria-label={t('filterByName')}
                      value={filterText}
                      onChange={(e) => setFilterText(e.target.value)}
                      className="font-mono text-xs"
                    />
                    {filterText.length > 0 && (
                      <InputGroupAddon align="inline-end">
                        <InputGroupButton aria-label={t('clearFilter')} size="icon-xs" onClick={() => setFilterText('')}>
                          <HugeiconsIcon icon={Cancel01Icon} strokeWidth={2} aria-hidden="true" />
                        </InputGroupButton>
                      </InputGroupAddon>
                    )}
                  </InputGroup>

                  <Select value={activeBucket} onValueChange={(v) => setActiveBucket(v as TypeBucket)}>
                    <SelectTrigger className="w-[170px]" aria-label={t('filterByType')}>
                      <SelectValue>
                        {(v) => {
                          const f = TYPE_FILTERS.find((x) => x.id === v)
                          return f ? typeLabel(t, f) : t('typeAll')
                        }}
                      </SelectValue>
                    </SelectTrigger>
                    <SelectContent>
                      {TYPE_FILTERS.map((f) => (
                        <SelectItem key={f.id} value={f.id} className={f.id === 'all' ? undefined : 'font-mono'}>
                          {typeLabel(t, f)}
                        </SelectItem>
                      ))}
                    </SelectContent>
                  </Select>

                  <span className="ml-auto font-mono text-xs tabular-nums text-muted-foreground">
                    {t('countFields', {
                      shown: filtered.length.toLocaleString(),
                      total: data.fields.length.toLocaleString(),
                    })}
                  </span>
                </div>
                <Separator />
                <DataGridScrollArea>
                  <DataGridTable />
                </DataGridScrollArea>
              </FramePanel>

              <FrameFooter>
                <DataGridPagination sizes={[25, 50, 100]} info={t('paginationInfo')} className="py-0" />
              </FrameFooter>
            </Frame>
          </DataGrid>
        </section>
      )}
    </div>
  )
}

/* ---------------- Overview ---------------- */

/** 索引说明：一个就写名字，多个只写数量 —— 卡片顶上那行放不下十二个索引名。 */
function indexLabel(t: Translate<FieldDictKey>, index: string): string {
  const parts = index.split(',').map((x) => x.trim()).filter(Boolean)
  if (parts.length <= 1) return index
  return t('indexCount', { n: parts.length })
}

function overviewCards(
  t: Translate<FieldDictKey>,
  data: FieldDictResponse, emptyFields: number, top: FieldRow | null,
): StatCard[] {
  const scanned = data.fields.length
  return [
    {
      /* 原来直接把 data.index 打上去。选「全部日志」时它是十二个索引名逗号拼起来
         的一长串，在卡片顶上折成八行，把「文档数 23,730」挤到卡片外面。多于一个
         索引时只写数量。 */
      label: indexLabel(t, data.index),
      title: t('kpiDocs'),
      value: data.doc_count.toLocaleString(),
      icon: <HugeiconsIcon icon={Table01Icon} strokeWidth={2} aria-hidden="true" />,
    },
    {
      label: t('kpiScannedLabel', { n: data.total_fields_in_mapping.toLocaleString() }),
      title: t('kpiScanned'),
      value: scanned.toLocaleString(),
      // 截断过就是黄的：这个数比 mapping 里的字段数小是有原因的，颜色得说出来。
      hint: data.truncated ? t('kpiTruncated') : undefined,
      tone: data.truncated ? 'warning' : undefined,
      icon: <HugeiconsIcon icon={Analytics01Icon} strokeWidth={2} aria-hidden="true" />,
    },
    {
      label: t('kpiEmptyLabel', { n: scanned.toLocaleString() }),
      title: t('kpiEmpty'),
      value: emptyFields.toLocaleString(),
      tone: emptyFields > 0 ? 'warning' : undefined,
      icon: <HugeiconsIcon icon={TriangleAlertIcon} strokeWidth={2} aria-hidden="true" />,
    },
    {
      // 基数最高的那个字段基本就是这份数据的「主键」——请求 id、会话 id 之类。
      // 知道它是谁，写问题的时候才知道该按什么去分组、该按什么去去重。
      label: top?.name ?? t('kpiTopNone'),
      title: t('kpiTop'),
      value: top?.cardinality_approx?.toLocaleString() ?? '—',
      icon: <HugeiconsIcon icon={SparklesIcon} strokeWidth={2} aria-hidden="true" />,
    },
  ]
}

/* ---------------- Columns ---------------- */

function fieldColumns({
  maxCardinality, onCopyName, onCopyValue, onInsert,
}: {
  maxCardinality: number
  onCopyName: (f: FieldRow) => void
  onCopyValue: (f: FieldRow, v: unknown) => void
  onInsert: (f: FieldRow) => void
}): ColumnDef<DataGridFeatures, FieldRow>[] {
  return [
    {
      id: 'name',
      accessorKey: 'name',
      header: ({ column }) => <DataGridColumnHeader title={translate(fieldDictCopy, 'colField')} column={column} />,
      size: 260,
      meta: { cellClassName: 'max-w-[20rem]' },
      cell: ({ row }) => (
        <div className="flex min-w-0 flex-col gap-1.5">
          <span className="font-mono text-xs break-all">{row.original.name}</span>
          <Badge size="sm" variant={TYPE_VARIANT[bucketOf(row.original.type)]} className="w-fit font-mono">
            {row.original.type}
          </Badge>
        </div>
      ),
    },
    {
      id: 'cardinality',
      accessorKey: 'cardinality_approx',
      header: ({ column }) => <DataGridColumnHeader title={translate(fieldDictCopy, 'colCardinality')} column={column} />,
      size: 180,
      cell: ({ row }) => <CardinalityCell value={row.original.cardinality_approx} max={maxCardinality} />,
    },
    {
      id: 'samples',
      header: ({ column }) => <DataGridColumnHeader title={translate(fieldDictCopy, 'colSamples')} column={column} />,
      size: 420,
      enableSorting: false,
      meta: { cellClassName: 'max-w-[34rem]' },
      cell: ({ row }) => <SamplesCell field={row.original} onCopy={onCopyValue} />,
    },
    {
      id: 'actions',
      header: '',
      size: 88,
      enableSorting: false,
      meta: { cellClassName: 'text-right' },
      cell: ({ row }) => (
        <div className="flex items-center justify-end gap-1">
          <Button
            variant="ghost"
            size="icon-sm"
            title={translate(fieldDictCopy, 'copyFieldName')}
            aria-label={translate(fieldDictCopy, 'copyFieldName')}
            onClick={() => onCopyName(row.original)}
          >
            <HugeiconsIcon icon={CopyIcon} strokeWidth={2} className="size-3.5" />
          </Button>
          <Button
            variant="ghost"
            size="icon-sm"
            title={translate(fieldDictCopy, 'insertIntoQuery')}
            aria-label={translate(fieldDictCopy, 'insertIntoQuery')}
            onClick={() => onInsert(row.original)}
          >
            <HugeiconsIcon icon={SendIcon} strokeWidth={2} className="size-3.5" />
          </Button>
        </div>
      ),
    },
  ]
}

function CardinalityCell({ value, max }: { value: number | null; max: number }) {
  if (value === null || value === undefined) {
    return <span className="font-mono text-xs text-muted-foreground">—</span>
  }
  // 至少 2%：0 宽的条读起来像「没数据」，而不是「这个字段几乎只有一个值」。
  const pct = max > 0 ? Math.max(2, Math.round((value / max) * 100)) : 0
  return (
    <div className="flex flex-col gap-1.5">
      <span className="font-mono text-xs tabular-nums">{value.toLocaleString()}</span>
      <div className="h-1 w-full max-w-[160px] overflow-hidden rounded-full bg-muted">
        <div className="h-full rounded-full bg-primary/60" style={{ width: `${pct}%` }} />
      </div>
    </div>
  )
}

function SamplesCell({ field, onCopy }: { field: FieldRow; onCopy: (f: FieldRow, v: unknown) => void }) {
  const samples = field.samples ?? []
  if (samples.length === 0) return <span className="font-mono text-xs text-muted-foreground">—</span>
  const visible = samples.slice(0, 5)
  const overflow = samples.length - visible.length
  return (
    <div className="flex flex-wrap items-center gap-1.5">
      {visible.map((s, i) => {
        const text = formatSampleValue(s.value)
        const display = text.length > 48 ? text.slice(0, 48) + '…' : text
        return (
          <button
            key={`${text}-${i}`}
            type="button"
            onClick={() => onCopy(field, s.value)}
            title={translate(fieldDictCopy, 'copySample', { text: `${field.name}:"${text}"` })}
            className="inline-flex items-center gap-1.5 rounded-full border border-border py-0.5 pl-2 pr-1 font-mono text-xs transition-colors hover:bg-accent"
          >
            <span className="break-all">{display}</span>
            <span className="inline-flex h-4 min-w-4 items-center justify-center rounded-full bg-muted px-1 font-mono text-10 tabular-nums text-muted-foreground">
              {s.count}
            </span>
          </button>
        )
      })}
      {overflow > 0 && (
        <Badge size="sm" variant="secondary" className="font-mono">+{overflow}</Badge>
      )}
    </div>
  )
}
