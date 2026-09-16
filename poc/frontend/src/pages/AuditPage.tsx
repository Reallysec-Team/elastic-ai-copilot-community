import { useCallback, useEffect, useMemo, useRef, useState } from 'react'
import { Link } from '@tanstack/react-router'
import { HugeiconsIcon } from '@hugeicons/react'
import {
  Activity02Icon, ClipboardCopyIcon, Clock01Icon, Download01Icon, EyeIcon, FilterIcon,
  FilterRemoveIcon, Loading03Icon, ScrollTextIcon, Search01Icon, TriangleAlertIcon,
} from '@hugeicons/core-free-icons'
import {
  useTable,
  type ColumnDef,
  type PaginationState,
} from '@tanstack/react-table'

import { api } from '@/lib/api'
import {
  buildAuditFilters,
  type AuditFilterParams,
  type AuditRange,
} from '@/lib/auditFilters'
import { relativeTime } from '@/lib/history'
import { cn } from '@/lib/utils'
import { Alert, AlertDescription } from '@/components/reui/alert'
import { Badge } from '@/components/reui/badge'
import { Filters } from '@/components/reui/filters/filters'
import {
  createFilterQuery, flattenFilterConditions, type FilterCondition,
} from '@/components/reui/filters/filters-query'
import type { FilterField, FilterQuery } from '@/components/reui/filters/filters-types'
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
import { MixDonut, type DonutSlice } from '@/components/blocks/chart-13/components/mix-donut'
import { TrendCard, type TrendStat } from '@/components/blocks/chart-18/components/trend-card'
import { useLang, useT, translate } from '@/lib/i18n'
import { filterLabelsFor, filterOperatorsFor } from '@/lib/filtersI18n'
import { ACTION_KEY, auditCopy, type AuditKey } from '@/locales/audit'
import { commonCopy } from '@/locales/common'
import { PageHeader } from '@/components/shell/page-header'
import { AdminOnlyView, useIsAdmin } from '@/components/gated-button'
import { Button } from '@/components/ui/button'
import { Collapsible, CollapsibleContent, CollapsibleTrigger } from '@/components/ui/collapsible'
import { Dialog, DialogContent, DialogFooter, DialogHeader, DialogTitle } from '@/components/ui/dialog'
import { Separator } from '@/components/ui/separator'
import { TimeRangePicker, type TimeRange } from '@/components/shared/time-range-picker'

/*
 * /v2/audit — read-only viewer over the gateway audit log
 * (.rst_copilot_audit by default). Filters delegate to the
 * GET /api/audit/events query string; pagination is offset based
 * with a fixed page size.
 *
 * 版式按 roster 的 `features/approvals`：一张 Frame 卡，头是标题 + 索引，
 * 身体是工具条 + data-grid，脚是分页。手写的 `<table>` 换成 ReUI 的
 * data-grid（TanStack table 9）——列宽、排序表头、列显隐、分页都由它给，
 * 不再自己写 `<Th>` / `<Row>` / 上一页下一页两个按钮。
 *
 * 分页是 manual 的：这张表是服务端 offset/size 分页，total 由后端给，所以
 * grid 只拿当前这一页的行，`pageCount` 和 `recordCount` 由 total 算出来。
 * 让 grid 客户端切片会把「第 3 页」切成「50 行里的第 3 页」，也就是空。
 *
 * 三行筛选胶囊（时间 / action / outcome 各一行）压成 roster 的一行工具条：
 * 十个 action 胶囊自己就占掉一整行竖向空间，而这一屏真正的主体是下面的表。
 */

const PAGE_SIZE = 50

/** 工具条上的快捷档。审计不需要 5 分钟这种粒度 —— 它看的是趋势不是值班。 */
const AUDIT_PRESETS = ['1h', '24h', '7d', '30d']

/* datetime-local 的值是本地时间的 `YYYY-MM-DDTHH:mm`，而选择器和后端说的都是
   ISO。auditFilters 那套（含既有测试）仍按 datetime-local 存，所以在边界上换一次。 */
function isoToLocal(iso: string): string {
  const d = new Date(iso)
  const pad = (n: number) => String(n).padStart(2, '0')
  return `${d.getFullYear()}-${pad(d.getMonth() + 1)}-${pad(d.getDate())}T${pad(d.getHours())}:${pad(d.getMinutes())}`
}

function localToIso(local: string): string {
  return local ? new Date(local).toISOString() : new Date().toISOString()
}

/* 图上的时间范围。`custom` 不在这里 —— 自定义区间是工具条里那个选择器的事，
   放进 tab 会让点一下就跳出一个空窗口、图当场变空。 */
const RANGE_TABS: { value: string; label: AuditKey }[] = [
  { value: '1h', label: 'range1h' },
  { value: '24h', label: 'range24h' },
  { value: '7d', label: 'range7d' },
]

/*
 * 后端写审计时用的 action 名，逐个翻成页面上的说法。映射表在 `locales/audit.ts`
 * （ACTION_KEY）——那张表原来只覆盖一半，剩下的（field_dict、triage_batch、
 * platform_interpret…）就以 `key` 原样落到饼图和表格里，同一个图例里一半中文
 * 一半英文。名字以后端 `audit.write_event(...)` 的第一个实参为准。
 */
function actionLabel(action: string): string {
  const key = ACTION_KEY[action]
  return key ? translate(auditCopy, key) : action
}

/** 桶的横轴标签。同一天内只写时分，跨天才带上日期。 */
function formatBucket(ts: string) {
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

/** 毫秒读数。超过一秒换成秒 —— 四位数毫秒没人在心里除。 */
const CSV_COLUMNS = ['@timestamp', 'action', 'outcome', 'user', 'target_index', 'duration_ms', 'tokens_in', 'tokens_out', 'model', 'request_id'] as const

function exportCsv(rows: AuditEvent[]) {
  const esc = (v: unknown) => {
    const str = v == null ? '' : String(v)
    return /[",\n]/.test(str) ? `"${str.replace(/"/g, '""')}"` : str
  }
  const lines = [CSV_COLUMNS.join(','), ...rows.map((r) => CSV_COLUMNS.map((k) => esc((r as Record<string, unknown>)[k])).join(','))]
  // BOM：Excel 打开中文 CSV 不带它就是乱码。
  const blob = new Blob(['\ufeff' + lines.join('\n')], { type: 'text/csv;charset=utf-8' })
  const a = document.createElement('a')
  a.href = URL.createObjectURL(blob)
  a.download = `audit-${new Date().toISOString().slice(0, 19).replace(/[:T]/g, '-')}.csv`
  a.click()
  URL.revokeObjectURL(a.href)
}

function fmtMs(ms: number | null | undefined) {
  if (ms == null) return '—'
  return ms >= 1000 ? `${(ms / 1000).toFixed(1)}s` : `${Math.round(ms)}ms`
}

const ACTION_OPTIONS = [
  '',
  'generate',
  'execute',
  'explain_log',
  'investigate_alert',
  'detection_rule_generate',
  'triage_batch',
  'incident_report',
  'field_dict',
  'kibana_link',
  'feedback',
] as const

type Action = (typeof ACTION_OPTIONS)[number]

const OUTCOME_OPTIONS = ['', 'success', 'fail'] as const
type Outcome = (typeof OUTCOME_OPTIONS)[number]


interface AuditEvent {
  '@timestamp'?: string
  action?: string
  user?: { username?: string; roles?: string[] } | null
  index?: string
  license_status?: string
  prompt_version?: string | null
  duration_ms?: number
  outcome?: string
  error?: string
  extra?: Record<string, unknown>
}

interface AuditSummary {
  over_time: { ts: string; count: number; failed: number }[]
  by_action: { key: string; count: number }[]
  by_outcome: { key: string; count: number }[]
  by_user: { key: string; count: number }[]
  duration_p50_ms: number | null
  duration_p95_ms: number | null
}

interface AuditResponse {
  total: number
  audit_index: string
  audit_enabled?: boolean
  summary?: AuditSummary
  events: AuditEvent[]
}

/*
 * GET /api/audit/events 是管理员接口。非管理员进来时不挂载下面那个组件 ——
 * 让它挂载等于发一次注定 403 的请求，然后把「你没权限」显示成一整页错误。
 */
export function AuditPage() {
  const t = useT(auditCopy)
  const isAdmin = useIsAdmin()
  if (!isAdmin) return <AdminOnlyView title={t('title')} />
  return <AuditView />
}

function AuditView() {
  const t = useT(auditCopy)
  // Filter state
  const [range, setRange] = useState<AuditRange>('24h')
  const [customFrom, setCustomFrom] = useState('')
  const [customTo, setCustomTo] = useState('')
  const [action, setAction] = useState<Action>('')
  const [outcome, setOutcome] = useState<Outcome>('')
  const [user, setUser] = useState('')
  const [targetIndex, setTargetIndex] = useState('')

  // Result state
  const [pagination, setPagination] = useState<PaginationState>({ pageIndex: 0, pageSize: PAGE_SIZE })
  const [loading, setLoading] = useState(false)
  const [errorMsg, setErrorMsg] = useState<string | null>(null)
  const [data, setData] = useState<AuditResponse | null>(null)

  // Detail dialog
  const [detail, setDetail] = useState<AuditEvent | null>(null)

  // Committed filter snapshot — what was active the last time the user pressed
  // 查询. Pagination reuses this snapshot (live filter edits don't take effect
  // until the next 查询), so we never mix a new filter with a stale offset/total.
  const committedRef = useRef<AuditFilterParams | null>(null)
  // Race token: drop out-of-order responses (slow page overwriting a newer one).
  const reqIdRef = useRef(0)

  const fetchPage = useCallback(async (pageIndex: number) => {
    const snapshot = committedRef.current ?? {}
    const myId = ++reqIdRef.current
    setLoading(true)
    setErrorMsg(null)
    try {
      const r = await api.auditEvents({
        size: PAGE_SIZE,
        offset: pageIndex * PAGE_SIZE,
        ...snapshot,
      })
      if (myId !== reqIdRef.current) return // stale response — discard
      setData(r)
      setPagination((p) => ({ ...p, pageIndex }))
    } catch (e) {
      if (myId !== reqIdRef.current) return
      setErrorMsg(e instanceof Error ? e.message : String(e))
      setData(null)
    } finally {
      if (myId === reqIdRef.current) setLoading(false)
    }
  }, [])

  // New query from current filters: validate, commit the snapshot, fetch page 0.
  const runQuery = useCallback(async () => {
    const built = buildAuditFilters({ range, customFrom, customTo, action, outcome, user, targetIndex })
    if (built.error) {
      setErrorMsg(built.error)
      return
    }
    committedRef.current = built.params ?? {}
    await fetchPage(0)
  }, [range, customFrom, customTo, action, outcome, user, targetIndex, fetchPage])

  // Initial fetch.
  useEffect(() => {
    // eslint-disable-next-line react-hooks/set-state-in-effect -- initial fetch on mount
    void runQuery()
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [])

  /* 图上的时间范围 tab 直接重查，不等「查询」按钮。它换的是这一屏"现在"指的
     是哪一段 —— 图和表都跟着它走；下面工具条里那些筛选（动作/结果/用户/索引）
     才是要按「查询」提交的那一组。 */
  const pickRange = useCallback(
    (next: AuditRange) => {
      setRange(next)
      const built = buildAuditFilters({
        range: next, customFrom, customTo, action, outcome, user, targetIndex,
      })
      if (built.error) {
        setErrorMsg(built.error)
        return
      }
      committedRef.current = built.params ?? {}
      void fetchPage(0)
    },
    [action, customFrom, customTo, fetchPage, outcome, targetIndex, user],
  )

  const total = data?.total ?? 0
  const events = useMemo(() => data?.events ?? [], [data])
  const summary = data?.summary

  const points = useMemo(
    () =>
      (summary?.over_time ?? []).map((p) => ({
        period: formatBucket(p.ts),
        value: p.count,
      })),
    [summary],
  )

  const failed = useMemo(
    () => (summary?.by_outcome ?? []).find((o) => o.key === 'error')?.count ?? 0,
    [summary],
  )

  const trendStats = useMemo<TrendStat[]>(() => {
    const p50 = summary?.duration_p50_ms
    const p95 = summary?.duration_p95_ms
    return [
      {
        id: 'total',
        label: t('kpiCalls'),
        value: total.toLocaleString(),
        note: t('kpiCallsUnit'),
        icon: <HugeiconsIcon icon={Activity02Icon} strokeWidth={2} aria-hidden="true" />,
      },
      {
        id: 'failed',
        label: t('kpiFailed'),
        value: failed.toLocaleString(),
        note: total > 0 ? `${((failed / total) * 100).toFixed(1)}%` : undefined,
        tone: failed > 0 ? 'destructive' : 'default',
        icon: <HugeiconsIcon icon={TriangleAlertIcon} strokeWidth={2} aria-hidden="true" />,
      },
      {
        id: 'latency',
        // 没有计时记录和"耗时 0 毫秒"是两个答案，所以 null 画成 —— 而不是 0。
        label: t('kpiLatency'),
        value: p50 == null && p95 == null ? '—' : `${fmtMs(p50)} / ${fmtMs(p95)}`,
        icon: <HugeiconsIcon icon={Clock01Icon} strokeWidth={2} aria-hidden="true" />,
      },
    ]
  }, [failed, summary, t, total])

  const actionSlices = useMemo<DonutSlice[]>(
    () =>
      (summary?.by_action ?? []).map((a) => ({
        key: a.key,
        name: actionLabel(a.key),
        count: a.count,
      })),
    [summary],
  )
  const pageCount = Math.max(1, Math.ceil(total / PAGE_SIZE))

  const columns = useMemo<ColumnDef<DataGridFeatures, AuditEvent>[]>(
    () => auditColumns((e) => setDetail(e)),
    [],
  )

  const table = useTable({
    features: dataGridFeatures,
    columns,
    data: events,
    pageCount,
    // 服务端分页：grid 只拿到当前这一页，不能再自己切片。
    manualPagination: true,
    autoResetPageIndex: false,
    state: { pagination },
    onPaginationChange: (updater) => {
      const next = typeof updater === 'function' ? updater(pagination) : updater
      if (next.pageIndex !== pagination.pageIndex) void fetchPage(next.pageIndex)
    },
  })

  const auditOff = data?.audit_enabled === false

  return (
    <div className="@container flex w-full flex-col gap-5">
      <PageHeader title={t('title')} />

      {errorMsg && (
        <Alert variant="destructive">
          <HugeiconsIcon icon={TriangleAlertIcon} strokeWidth={2} className="size-4" />
          <AlertDescription>{errorMsg}</AlertDescription>
        </Alert>
      )}

      {/* 概览：左边是这一段时间里调用怎么走的，右边是这些调用花在哪个动作上。
          两张卡读的是同一次查询的聚合，所以跟下面那张表说的是同一批事件。 */}
      <section
        aria-label={t('secOverview')}
        className="grid auto-rows-fr items-stretch gap-5 @4xl:grid-cols-3"
      >
        <TrendCard
          className="h-full min-w-0 @4xl:col-span-2"
          title={t('chartVolume')}
          tabs={RANGE_TABS.map((r) => ({ value: r.value, label: t(r.label) }))}
          activeTab={range}
          onTabChange={(v) => pickRange(v as AuditRange)}
          stats={trendStats}
          points={points}
          valueLabel={t('unitCalls')}
          empty={auditOff ? t('auditOff') : t('noCallsInWindow')}
        />
        <MixDonut
          className="h-full"
          title={t('actionMix')}
          centerLabel={t('centerCalls')}
          slices={actionSlices}
          emptyText={auditOff ? t('auditOff') : t('noCallsInWindow')}
        />
      </section>

      <section aria-label={t('secEvents')}>
        {/* 条数和索引名跟着这张表走 —— 它们说的就是表里这批事件，放在页头
            反而离得远。 */}
        {data && (
          <p className="mb-2 text-xs text-muted-foreground">
            {t('descCount', { n: total.toLocaleString(), index: data.audit_index })}
          </p>
        )}
      <DataGrid
        table={table}
        recordCount={total}
        isLoading={loading && events.length === 0}
        emptyMessage={
          auditOff ? t('gridEmptyOff') : t('gridEmptyOn')
        }
        tableLayout={{
          dense: true,
          rowBorder: true,
          columnsPinnable: true,
          columnsResizable: false,
          columnsMovable: false,
          columnsVisibility: true,
        }}
        tableClassNames={{
          bodyRow: '[&>td]:h-14',
          edgeCell: 'first:ps-(--frame-panel-header-px) last:pe-(--frame-panel-header-px)',
        }}
      >
        <Frame dense spacing="sm" className="flex w-full min-w-0 flex-col [--frame-panel-header-py-adjust:2px]">
          <FrameHeader className="flex-row items-center justify-between gap-3">
            {/* 只留标题：原来那句说的是筛选栏自己的行为（改完要按「查询」），
                而筛选栏就在下面一行；审计关着的时候有整块空态在说这件事。 */}
            <FrameTitle>{t('cardEventsTitle')}</FrameTitle>
            {/* solution-ai-ops-8 卡头右侧的 Export CSV：导当前这一页（服务端分页，
                手里只有这一页）。 */}
            <Button
              variant="outline"
              size="sm"
              disabled={auditOff || events.length === 0}
              onClick={() => exportCsv(events)}
            >
              <HugeiconsIcon icon={Download01Icon} strokeWidth={2} className="size-3.5" aria-hidden />
              {t('exportCsv')}
            </Button>
          </FrameHeader>

          <FramePanel className="min-h-0 flex-1 bg-card p-0! shadow-none!">
            <div className="px-3 py-3">
              <AuditToolbar
                range={range} setRange={setRange}
                customFrom={customFrom} setCustomFrom={setCustomFrom}
                customTo={customTo} setCustomTo={setCustomTo}
                action={action} setAction={setAction}
                outcome={outcome} setOutcome={setOutcome}
                user={user} setUser={setUser}
                targetIndex={targetIndex} setTargetIndex={setTargetIndex}
                loading={loading}
                onRun={() => void runQuery()}
              />
            </div>
            <Separator />
            {auditOff ? (
              <div className="flex flex-col items-center gap-3 py-16 text-center">
                <HugeiconsIcon icon={ScrollTextIcon} strokeWidth={2} className="size-6 text-muted-foreground" />
                <div className="text-sm font-medium">{t('auditOffTitle')}</div>
                <p className="max-w-[420px] text-sm leading-relaxed text-muted-foreground">
                  {t('auditOffBodyPrefix')}
                  <Link to="/settings" className="mx-1 underline underline-offset-2">
                    {t('auditOffLink')}
                  </Link>
                  {t('auditOffBodySuffix')}
                </p>
              </div>
            ) : (
              <DataGridScrollArea>
                <DataGridTable />
              </DataGridScrollArea>
            )}
          </FramePanel>

          {!auditOff && (
            <FrameFooter>
              <DataGridPagination sizes={[PAGE_SIZE]} info={t('paginationInfo')} className="py-0" />
            </FrameFooter>
          )}
        </Frame>
      </DataGrid>
      </section>

      <Dialog open={!!detail} onOpenChange={(v) => !v && setDetail(null)}>
        {detail && <DetailDialog event={detail} onClose={() => setDetail(null)} />}
      </Dialog>
    </div>
  )
}

/* ---------------- Columns ---------------- */

/* action 的配色沿用原来的分组：生成 / 执行 / 解释 / 调查 / 报告 是 info，
 * 检测规则是 primary，批量分诊是 warning，其余中性。颜色从字面 CSS 变量换成
 * Badge 的语义 variant，深色模式跟着主题走。 */
const ACTION_TONE: Record<string, 'info-light' | 'primary-light' | 'warning-light' | 'secondary'> = {
  generate: 'info-light',
  execute: 'info-light',
  explain_log: 'info-light',
  investigate_alert: 'info-light',
  incident_report: 'info-light',
  detection_rule_generate: 'primary-light',
  triage_batch: 'warning-light',
}

function ActionBadge({ action }: { action: string }) {
  if (!action) return <Dash />
  return (
    <Badge size="sm" variant={ACTION_TONE[action] ?? 'secondary'} className="font-mono">
      {action}
    </Badge>
  )
}

function OutcomeBadge({ outcome }: { outcome: string }) {
  const o = outcome.toLowerCase()
  if (o === 'success') return <Badge size="sm" variant="success-light">success</Badge>
  if (o === 'fail') return <Badge size="sm" variant="destructive-light">fail</Badge>
  return <Dash />
}

function Dash() {
  return <span className="font-mono text-xs text-muted-foreground">—</span>
}

function auditColumns(onOpen: (e: AuditEvent) => void): ColumnDef<DataGridFeatures, AuditEvent>[] {
  return [
    {
      id: 'timestamp',
      accessorFn: (row) => row['@timestamp'],
      header: ({ column }) => <DataGridColumnHeader title={translate(auditCopy, 'colTime')} column={column} />,
      size: 130,
      cell: ({ row }) => {
        const ts = row.original['@timestamp']
        const ms = ts ? new Date(ts).getTime() : null
        // 相对时间读起来快，绝对时间才是审计要的证据 —— 后者留在 title 里。
        return ms ? (
          <span className="font-mono text-xs tabular-nums" title={ts}>
            {relativeTime(ms)}
          </span>
        ) : (
          <Dash />
        )
      },
    },
    {
      id: 'action',
      accessorKey: 'action',
      header: ({ column }) => <DataGridColumnHeader title="action" column={column} />,
      size: 220,
      meta: { cellClassName: 'max-w-[16rem]' },
      cell: ({ row }) => {
        const e = row.original
        const isFail = (e.outcome ?? '').toLowerCase() === 'fail'
        return (
          <div className="flex min-w-0 flex-col gap-1">
            <ActionBadge action={e.action ?? ''} />
            {isFail && e.error && (
              <span className="truncate font-mono text-11 text-destructive" title={e.error}>
                {e.error}
              </span>
            )}
          </div>
        )
      },
    },
    {
      id: 'outcome',
      accessorKey: 'outcome',
      header: ({ column }) => <DataGridColumnHeader title="outcome" column={column} />,
      size: 100,
      cell: ({ row }) => <OutcomeBadge outcome={row.original.outcome ?? ''} />,
    },
    {
      id: 'user',
      accessorFn: (row) => row.user?.username,
      header: ({ column }) => <DataGridColumnHeader title="user" column={column} />,
      size: 120,
      cell: ({ row }) => {
        const u = row.original.user?.username
        return u ? <code className="font-mono text-xs">{u}</code> : <Dash />
      },
    },
    {
      id: 'index',
      accessorKey: 'index',
      header: ({ column }) => <DataGridColumnHeader title="index" column={column} />,
      size: 220,
      meta: { cellClassName: 'max-w-[16rem]' },
      cell: ({ row }) => {
        const idx = row.original.index
        return idx ? (
          <code className="block truncate font-mono text-xs" title={idx}>{idx}</code>
        ) : (
          <Dash />
        )
      },
    },
    {
      id: 'duration_ms',
      accessorKey: 'duration_ms',
      header: ({ column }) => <DataGridColumnHeader title="duration_ms" column={column} />,
      size: 110,
      meta: { headerClassName: 'justify-end', cellClassName: 'text-right' },
      cell: ({ row }) => {
        const d = row.original.duration_ms
        return typeof d === 'number' ? (
          <span className="font-mono text-xs tabular-nums">{d.toLocaleString()}</span>
        ) : (
          <Dash />
        )
      },
    },
    {
      id: 'actions',
      header: '',
      size: 56,
      enableSorting: false,
      meta: { cellClassName: 'text-right' },
      cell: ({ row }) => (
        <Button
          type="button"
          variant="ghost"
          size="icon-sm"
          title={translate(auditCopy, 'viewDetail')}
          aria-label={translate(auditCopy, 'viewDetail')}
          onClick={() => onOpen(row.original)}
        >
          <HugeiconsIcon icon={EyeIcon} strokeWidth={2} className="size-3.5" />
        </Button>
      ),
    },
  ]
}

/* ---------------- Toolbar ---------------- */

interface ToolbarProps {
  range: AuditRange
  setRange: (r: AuditRange) => void
  customFrom: string
  setCustomFrom: (v: string) => void
  customTo: string
  setCustomTo: (v: string) => void
  action: Action
  setAction: (v: Action) => void
  outcome: Outcome
  setOutcome: (v: Outcome) => void
  user: string
  setUser: (v: string) => void
  targetIndex: string
  setTargetIndex: (v: string) => void
  loading: boolean
  onRun: () => void
}

/* 四个筛选条件走 ReUI Filters（solution-ai-ops-8 的工具条）：一个「筛选」按钮
   展开成条件芯片，没选就不占地方。时间范围不放进去 —— TimeRangePicker 是和实时
   告警、运营报告共用的那一个，三页要长得一样。
   值仍然落在页面自己的四个 state 上，「查询」按钮按下才发请求，和原来一致。 */
const FILTER_FIELD_IDS = ['action', 'outcome', 'user', 'target_index'] as const

function firstValue(conds: FilterCondition[], field: string): string {
  const c = conds.find((x) => x.field === field && !x.negated && x.values.length > 0)
  const v = c?.values[0]
  return typeof v === 'string' ? v : ''
}

function AuditToolbar(p: ToolbarProps) {
  const t = useT(auditCopy)
  const lang = useLang()
  /* 后端每个参数只接一个精确值，所以运算符只留「是」/「包含」——列 27 个只会误导。 */
  const fields = useMemo<FilterField[]>(() => [
    {
      id: 'action',
      label: t('filterAction'),
      icon: <HugeiconsIcon icon={ScrollTextIcon} strokeWidth={2} className="size-3.5" aria-hidden />,
      type: 'select',
      searchable: true,
      options: ACTION_OPTIONS.filter(Boolean).map((a) => ({ value: a, label: a })),
      operators: filterOperatorsFor(lang, 'select', ['is']),
    },
    {
      id: 'outcome',
      label: t('filterOutcome'),
      icon: <HugeiconsIcon icon={TriangleAlertIcon} strokeWidth={2} className="size-3.5" aria-hidden />,
      type: 'select',
      options: OUTCOME_OPTIONS.filter(Boolean).map((o) => ({ value: o, label: o })),
      operators: filterOperatorsFor(lang, 'select', ['is']),
    },
    {
      id: 'user',
      label: t('filterUser'),
      icon: <HugeiconsIcon icon={Search01Icon} strokeWidth={2} className="size-3.5" aria-hidden />,
      type: 'text',
      placeholder: t('userPlaceholder'),
      operators: filterOperatorsFor(lang, 'text', ['is']),
    },
    {
      id: 'target_index',
      label: t('filterIndex'),
      icon: <HugeiconsIcon icon={Search01Icon} strokeWidth={2} className="size-3.5" aria-hidden />,
      type: 'text',
      placeholder: t('indexPlaceholder'),
      operators: filterOperatorsFor(lang, 'text', ['is']),
    },
  ], [t, lang])

  const [query, setQuery] = useState<FilterQuery>(() => createFilterQuery([]))
  const active = useMemo(
    () => flattenFilterConditions(query).filter((c) => FILTER_FIELD_IDS.includes(c.field as never) && c.values.some((v) => typeof v === 'string' && v.trim() !== '')),
    [query],
  )

  const onQueryChange = (next: FilterQuery) => {
    setQuery(next)
    const conds = flattenFilterConditions(next)
    p.setAction(firstValue(conds, 'action') as Action)
    p.setOutcome(firstValue(conds, 'outcome') as Outcome)
    p.setUser(firstValue(conds, 'user'))
    p.setTargetIndex(firstValue(conds, 'target_index'))
  }

  return (
    <div className="flex flex-wrap items-center gap-2">
      {/* 与实时告警、运营报告同一个组件。 */}
      <TimeRangePicker
        value={
          p.range === 'custom'
            ? { kind: 'custom', since: localToIso(p.customFrom), until: localToIso(p.customTo) }
            : { kind: 'preset', preset: p.range }
        }
        onChange={(v: TimeRange) => {
          if (v.kind === 'custom') {
            p.setRange('custom')
            p.setCustomFrom(isoToLocal(v.since))
            p.setCustomTo(v.until ? isoToLocal(v.until) : '')
          } else if (v.kind === 'preset') {
            p.setRange(v.preset as AuditRange)
          }
        }}
        presets={AUDIT_PRESETS}
        allowAll={false}
        className="h-9"
      />

      <Filters
        query={query}
        fields={fields}
        onQueryChange={onQueryChange}
        labels={filterLabelsFor(lang)}
        size="default"
        trigger={
          <Button variant="outline" aria-label={t('filters')} disabled={p.loading}>
            <HugeiconsIcon icon={FilterIcon} strokeWidth={2} aria-hidden />
            {t('filters')}
            {active.length > 0 && <Badge variant="outline" radius="full">{active.length}</Badge>}
          </Button>
        }
      />
      {active.length > 0 && (
        <Button
          variant="outline"
          disabled={p.loading}
          onClick={() => onQueryChange(createFilterQuery([]))}
        >
          <HugeiconsIcon icon={FilterRemoveIcon} strokeWidth={2} className="size-3.5" aria-hidden />
          {t('clearFilters')}
        </Button>
      )}

      <Button onClick={p.onRun} disabled={p.loading} className="ms-auto">
        <HugeiconsIcon
          icon={p.loading ? Loading03Icon : Search01Icon}
          strokeWidth={2}
          className={cn('size-3.5', p.loading && 'animate-spin')}
        />
        {p.loading ? t('querying') : t('query')}
      </Button>
    </div>
  )
}

/* ---------------- Detail dialog ---------------- */

function DetailDialog({ event, onClose }: { event: AuditEvent; onClose: () => void }) {
  const t = useT(auditCopy)
  const c = useT(commonCopy)
  const [showRaw, setShowRaw] = useState(false)
  const [copied, setCopied] = useState(false)

  const json = useMemo(() => JSON.stringify(event, null, 2), [event])

  async function copy() {
    try {
      await navigator.clipboard.writeText(json)
      setCopied(true)
      setTimeout(() => setCopied(false), 1500)
    } catch {
      // ignore
    }
  }

  const ts = event['@timestamp'] ?? ''
  const username = event.user?.username ?? null
  const roles = event.user?.roles ?? null

  return (
    <DialogContent className="flex max-h-[86vh] flex-col gap-0 overflow-hidden p-0 sm:max-w-[720px]">
      <DialogHeader className="flex-row items-center justify-between gap-4 border-b px-6 pt-5 pb-4">
        <DialogTitle className="text-base font-semibold">{t('detailTitle')}</DialogTitle>
        <div className="flex shrink-0 items-center gap-2 pr-8">
          <code className="font-mono text-11 text-muted-foreground">{ts}</code>
          <ActionBadge action={event.action ?? ''} />
        </div>
      </DialogHeader>

      <div className="flex min-h-0 flex-1 flex-col gap-4 overflow-auto px-6 py-5">
        <dl className="flex flex-col gap-2.5">
          <DRow label="@timestamp" value={ts || '—'} mono />
          <DRow label="action" value={event.action || '—'} mono />
          <DRow label="outcome" value={<OutcomeBadge outcome={event.outcome ?? ''} />} />
          <DRow
            label="user"
            value={
              username ? (
                <span className="font-mono text-xs">
                  {username}
                  {roles && roles.length > 0 && (
                    <span className="ml-2 text-muted-foreground">[{roles.join(', ')}]</span>
                  )}
                </span>
              ) : (
                '—'
              )
            }
          />
          <DRow label="index" value={event.index || '—'} mono />
          <DRow label="license_status" value={event.license_status || '—'} mono />
          <DRow label="prompt_version" value={event.prompt_version || '—'} mono />
          <DRow
            label="duration_ms"
            value={typeof event.duration_ms === 'number' ? event.duration_ms.toLocaleString() : '—'}
            mono
          />
          {event.error && (
            <DRow label="error" value={<span className="font-mono text-xs text-destructive">{event.error}</span>} />
          )}
        </dl>

        {event.extra && Object.keys(event.extra).length > 0 && (
          <div className="flex flex-col gap-1.5">
            <span className="text-xs font-medium text-muted-foreground">extra</span>
            <pre className="overflow-x-auto rounded-md bg-muted/50 p-3 font-mono text-xs leading-[1.5]">
              {JSON.stringify(event.extra, null, 2)}
            </pre>
          </div>
        )}

        {/* The raw event stays one click away — an audit row you cannot read in
            full is not an audit trail. */}
        <Collapsible open={showRaw} onOpenChange={setShowRaw}>
          <CollapsibleTrigger className="text-xs underline-offset-2 hover:underline">
            {showRaw ? t('hideRawJson') : t('showRawJson')}
          </CollapsibleTrigger>
          <CollapsibleContent
            className="mt-2 overflow-x-auto rounded-md bg-foreground p-3 font-mono text-xs leading-[1.5] text-background"
            render={<pre />}
          >
            {json}
          </CollapsibleContent>
        </Collapsible>
      </div>

      <DialogFooter className="mx-0 mb-0 px-6 py-4">
        <Button variant="outline" size="sm" onClick={() => void copy()}>
          <HugeiconsIcon icon={ClipboardCopyIcon} strokeWidth={2} className="size-3.5" />
          {copied ? c('copied') : t('copyJson')}
        </Button>
        <Button size="sm" onClick={onClose}>{c('close')}</Button>
      </DialogFooter>
    </DialogContent>
  )
}

function DRow({ label, value, mono }: { label: string; value: React.ReactNode; mono?: boolean }) {
  return (
    <div className="flex items-baseline gap-3">
      <span className="w-[140px] shrink-0 font-mono text-xs text-muted-foreground">{label}</span>
      <span className={cn('flex-1 text-sm', mono && 'font-mono text-xs')}>{value}</span>
    </div>
  )
}
