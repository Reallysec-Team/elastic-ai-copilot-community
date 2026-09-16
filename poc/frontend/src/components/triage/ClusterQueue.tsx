import { useMemo, useState, type ReactNode } from 'react'
import { HugeiconsIcon } from '@hugeicons/react'
import {
  Cancel01Icon, Clock01Icon, CopyIcon, LayoutThreeColumnIcon, SparklesIcon, Tick02Icon,
} from '@hugeicons/core-free-icons'
import { useTable, type ColumnDef, type RowSelectionState } from '@tanstack/react-table'

import { cn } from '@/lib/utils'
import { useT } from '@/lib/i18n'
import { SeverityBadge } from '@/components/severity-badge'
import type { Severity } from '@/lib/severity'
import { STATUS_ORDER, statusLabel, type TriageStatus } from '@/lib/triageStatus'
import { triageCopy } from '@/locales/triage'
import { Badge, type BadgeProps } from '@/components/reui/badge'
import { DataGrid, dataGridFeatures, type DataGridFeatures } from '@/components/reui/data-grid/data-grid'
import { DataGridColumnHeader } from '@/components/reui/data-grid/data-grid-column-header'
import { DataGridScrollArea } from '@/components/reui/data-grid/data-grid-scroll-area'
import {
  DataGridTable, DataGridTableRowSelect, DataGridTableRowSelectAll,
} from '@/components/reui/data-grid/data-grid-table'
import { Frame, FrameDescription, FrameHeader, FramePanel, FrameTitle } from '@/components/reui/frame'
import { Button } from '@/components/ui/button'
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from '@/components/ui/select'
import { Separator } from '@/components/ui/separator'
import {
  Sheet, SheetClose, SheetContent, SheetDescription, SheetFooter, SheetHeader, SheetTitle,
} from '@/components/ui/sheet'

/*
 * 分诊结果队列 —— 照 `@reui/solution-agents-5`（Agent Action Approval Inbox）：
 * 风险分档的队列表 + 勾选后出现的批量处置条 + 点行打开的详情 Sheet。
 * 原来是一摞卡片（每个聚类一张，处置按钮、对比、调查、告警 ID 都摊在卡上），
 * 30 个聚类要滚三屏才看全；现在一屏一张表，细节收进右侧抽屉。
 *
 * 那个 block 是 Card 面，这里全部换成 Frame（全站只用一种面）。
 * 「批准 / 拒绝」对应到这里是「已处置 / 误报 / 升级 / 打开」四档处置。
 */

export type QueueCluster = {
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

const STATUS_VARIANT: Record<TriageStatus, BadgeProps['variant']> = {
  open: 'outline',
  handled: 'success-light',
  fp: 'secondary',
  escalated: 'destructive-light',
}

function normalizeSev(s: string): Severity {
  return (['critical', 'high', 'medium', 'low', 'info'] as const).includes(s as Severity) ? (s as Severity) : 'info'
}

function fmtTime(s: string | null): string {
  if (!s) return '—'
  const d = new Date(s)
  return Number.isNaN(d.getTime()) ? s : d.toLocaleString(undefined, { month: '2-digit', day: '2-digit', hour: '2-digit', minute: '2-digit', hour12: false })
}

export function ClusterQueue({
  clusters, statuses, compareIds, onChangeStatus, onToggleCompare, onInvestigate, emptyText,
}: {
  clusters: QueueCluster[]
  statuses: Record<string, TriageStatus>
  compareIds: string[]
  onChangeStatus: (c: QueueCluster, next: TriageStatus) => void
  onToggleCompare: (id: string) => void
  onInvestigate: (c: QueueCluster) => void
  emptyText: string
}) {
  const t = useT(triageCopy)
  const [rowSelection, setRowSelection] = useState<RowSelectionState>({})
  const [active, setActive] = useState<QueueCluster | null>(null)

  const columns = useMemo<ColumnDef<DataGridFeatures, QueueCluster>[]>(() => [
    {
      id: 'select',
      header: () => <DataGridTableRowSelectAll />,
      cell: ({ row }) => <DataGridTableRowSelect row={row} />,
      enableSorting: false,
      enableResizing: false,
      size: 40,
      meta: { cellClassName: '', headerClassName: '' },
    },
    {
      accessorKey: 'priority_rank',
      id: 'rank',
      header: ({ column }) => <DataGridColumnHeader title="#" column={column} />,
      cell: ({ row }) => <span className="font-semibold tabular-nums">#{row.original.priority_rank}</span>,
      size: 56,
      enableSorting: true,
      meta: { headerTitle: '#' },
    },
    {
      accessorKey: 'severity',
      id: 'severity',
      header: ({ column }) => <DataGridColumnHeader title={t('colSeverity')} column={column} />,
      cell: ({ row }) => {
        const sev = normalizeSev(row.original.severity)
        return <SeverityBadge severity={sev} />
      },
      size: 96,
      enableSorting: true,
      meta: { headerTitle: t('colSeverity') },
    },
    {
      accessorKey: 'attack_intent',
      id: 'intent',
      header: ({ column }) => <DataGridColumnHeader title={t('colIntent')} column={column} />,
      cell: ({ row }) => (
        <div className="flex min-w-0 flex-col gap-0.5">
          <span className="truncate font-medium">{row.original.attack_intent || row.original.rule_id}</span>
          <code className="truncate font-mono text-11 text-muted-foreground">
            {row.original.subject_field}={row.original.subject_value}
          </code>
        </div>
      ),
      minSize: 220,
      enableSorting: false,
      meta: { headerTitle: t('colIntent'), autoSize: true },
    },
    {
      accessorKey: 'count',
      id: 'count',
      header: ({ column }) => <DataGridColumnHeader title={t('colCount')} column={column} />,
      cell: ({ row }) => <span className="tabular-nums">{row.original.count}</span>,
      size: 72,
      enableSorting: true,
      meta: { headerTitle: t('colCount') },
    },
    {
      accessorKey: 'last_seen',
      id: 'span',
      header: ({ column }) => <DataGridColumnHeader title={t('colSpan')} column={column} />,
      cell: ({ row }) => (
        <span className="inline-flex items-center gap-1 whitespace-nowrap font-mono text-11 text-muted-foreground">
          <HugeiconsIcon icon={Clock01Icon} strokeWidth={2} className="size-3" />
          {fmtTime(row.original.first_seen)} → {fmtTime(row.original.last_seen)}
        </span>
      ),
      size: 200,
      enableSorting: true,
      meta: { headerTitle: t('colSpan') },
    },
    {
      id: 'status',
      header: ({ column }) => <DataGridColumnHeader title={t('dispositionLabel')} column={column} />,
      cell: ({ row }) => {
        const c = row.original
        const st = statuses[c.cluster_id] ?? 'open'
        return (
          <div onClick={(e) => e.stopPropagation()} onPointerDown={(e) => e.stopPropagation()}>
            <Select value={st} onValueChange={(v) => onChangeStatus(c, (v ?? st) as TriageStatus)}>
              <SelectTrigger size="sm" className="h-7! w-28" aria-label={t('dispositionLabel')}>
                <SelectValue>{(v) => <Badge size="sm" variant={STATUS_VARIANT[String(v) as TriageStatus]}>{statusLabel(String(v) as TriageStatus)}</Badge>}</SelectValue>
              </SelectTrigger>
              <SelectContent>
                {STATUS_ORDER.map((s) => <SelectItem key={s} value={s}>{statusLabel(s)}</SelectItem>)}
              </SelectContent>
            </Select>
          </div>
        )
      },
      size: 130,
      enableSorting: false,
      meta: { headerTitle: t('dispositionLabel') },
    },
    {
      id: 'actions',
      header: () => <span className="sr-only">{t('colActions')}</span>,
      cell: ({ row }) => {
        const c = row.original
        const inCompare = compareIds.includes(c.cluster_id)
        return (
          <div className="flex items-center justify-end gap-1" onClick={(e) => e.stopPropagation()} onPointerDown={(e) => e.stopPropagation()}>
            <Button
              variant={inCompare ? 'secondary' : 'ghost'}
              size="icon-sm"
              aria-pressed={inCompare}
              aria-label={t('compare')}
              title={t('addToCompareTitle')}
              onClick={() => onToggleCompare(c.cluster_id)}
            >
              <HugeiconsIcon icon={LayoutThreeColumnIcon} strokeWidth={2} className="size-3.5" />
            </Button>
            <Button variant="ghost" size="sm" onClick={() => onInvestigate(c)} title={t('investigateTitle')}>
              <HugeiconsIcon icon={SparklesIcon} strokeWidth={2} className="size-3.5" />
              {t('investigate')}
            </Button>
          </div>
        )
      },
      size: 130,
      enableSorting: false,
      enableResizing: false,
    },
  ], [t, statuses, compareIds, onChangeStatus, onToggleCompare, onInvestigate])

  const table = useTable({
    features: dataGridFeatures,
    columns,
    data: clusters,
    getRowId: (r) => r.cluster_id,
    state: { rowSelection },
    enableRowSelection: true,
    onRowSelectionChange: setRowSelection,
  })
  const selected = table.getSelectedRowModel().rows.map((r) => r.original)

  const bulk = (next: TriageStatus) => {
    for (const c of selected) onChangeStatus(c, next)
    setRowSelection({})
  }

  return (
    <>
      <DataGrid
        table={table}
        recordCount={clusters.length}
        emptyMessage={emptyText}
        onRowClick={(c) => setActive(c)}
        tableLayout={{ dense: true, rowBorder: true, headerSticky: true, columnsResizable: false, columnsMovable: false }}
        tableClassNames={{
          bodyRow: '[&>td]:h-14',
          edgeCell: 'first:ps-(--frame-panel-header-px) last:pe-(--frame-panel-header-px)',
        }}
      >
        <Frame dense spacing="sm" className="w-full min-w-0">
          <FrameHeader className="flex-row items-center justify-between gap-3">
            <div className="flex flex-col gap-px">
              <FrameTitle className="text-balance">{t('queueTitle')}</FrameTitle>
              <FrameDescription className="text-xs text-pretty">{t('queueDesc', { n: clusters.length })}</FrameDescription>
            </div>
          </FrameHeader>
          <FramePanel className="p-0! shadow-none!">
            {selected.length > 0 && (
              <>
                {/* 批量处置条：solution-agents-5 的 DecisionBar，批准/拒绝换成四档处置。 */}
                <div className="flex flex-col gap-3 bg-muted/25 px-(--frame-panel-header-px) py-3 lg:flex-row lg:items-center lg:justify-between">
                  <div className="flex min-w-0 flex-col gap-0.5">
                    <span className="text-sm font-medium">{t('bulkSelected', { n: selected.length })}</span>
                    <span className="text-xs text-muted-foreground">{t('bulkHint')}</span>
                  </div>
                  <div className="flex flex-wrap items-center gap-2">
                    <Button size="sm" onClick={() => bulk('handled')}>
                      <HugeiconsIcon icon={Tick02Icon} strokeWidth={2} className="size-3.5" />
                      {statusLabel('handled')}
                    </Button>
                    <Button size="sm" variant="outline" onClick={() => bulk('fp')}>{statusLabel('fp')}</Button>
                    <Button size="sm" variant="outline" onClick={() => bulk('escalated')}>{statusLabel('escalated')}</Button>
                    <Button size="sm" variant="outline" onClick={() => bulk('open')}>{statusLabel('open')}</Button>
                    <Button size="sm" variant="ghost" onClick={() => setRowSelection({})}>
                      <HugeiconsIcon icon={Cancel01Icon} strokeWidth={2} className="size-3.5" />
                      {t('clearSelection')}
                    </Button>
                  </div>
                </div>
                <Separator />
              </>
            )}
            <DataGridScrollArea>
              <DataGridTable />
            </DataGridScrollArea>
          </FramePanel>
        </Frame>
      </DataGrid>

      <ClusterDetailSheet
        cluster={active}
        status={active ? statuses[active.cluster_id] ?? 'open' : 'open'}
        onOpenChange={(v) => !v && setActive(null)}
        onChangeStatus={onChangeStatus}
        onInvestigate={onInvestigate}
      />
    </>
  )
}

/* ---------------- 详情抽屉 ---------------- */

function Row({ label, children }: { label: string; children: ReactNode }) {
  return (
    <div className="flex flex-col gap-1">
      <span className="text-11 font-medium uppercase tracking-wide text-muted-foreground">{label}</span>
      <div className="text-sm leading-relaxed">{children}</div>
    </div>
  )
}

function ClusterDetailSheet({
  cluster, status, onOpenChange, onChangeStatus, onInvestigate,
}: {
  cluster: QueueCluster | null
  status: TriageStatus
  onOpenChange: (v: boolean) => void
  onChangeStatus: (c: QueueCluster, next: TriageStatus) => void
  onInvestigate: (c: QueueCluster) => void
}) {
  const t = useT(triageCopy)
  const [copied, setCopied] = useState(false)
  const sev = cluster ? normalizeSev(cluster.severity) : 'info'

  return (
    <Sheet open={cluster !== null} onOpenChange={onOpenChange}>
      <SheetContent side="right" variant="inset" showCloseButton={false} className="flex flex-col gap-0 p-0">
        {cluster && (
          <>
            <SheetHeader className="shrink-0 gap-2 border-b px-5 pt-5 pb-4">
              <div className="flex items-start justify-between gap-3">
                <div className="flex min-w-0 flex-col gap-1.5">
                  <div className="flex flex-wrap items-center gap-2">
                    <span className="text-lg font-semibold tabular-nums">#{cluster.priority_rank}</span>
                    <SeverityBadge severity={sev} />
                    <Badge size="sm" variant={STATUS_VARIANT[status]}>{statusLabel(status)}</Badge>
                    {cluster.is_likely_fp && <Badge size="sm" variant="secondary">{t('likelyFp')}</Badge>}
                  </div>
                  <SheetTitle className="text-base">{cluster.attack_intent || cluster.rule_id}</SheetTitle>
                  <SheetDescription className="font-mono text-xs">
                    {cluster.count} alerts · {fmtTime(cluster.first_seen)} → {fmtTime(cluster.last_seen)}
                  </SheetDescription>
                </div>
                <SheetClose render={<Button variant="ghost" size="icon-sm" aria-label="close" className="-me-1.5 -mt-1.5" />}>
                  <HugeiconsIcon icon={Cancel01Icon} strokeWidth={2} className="size-4" />
                </SheetClose>
              </div>
            </SheetHeader>

            <div className="flex min-h-0 flex-1 flex-col gap-5 overflow-y-auto px-5 py-4">
              <Row label={t('colSubject')}>
                <div className="flex items-center justify-between gap-3 rounded-md bg-accent px-3 py-2 [box-shadow:var(--shadow-ring-light)]">
                  <code className="break-all font-mono text-12">
                    {cluster.subject_field}=<span className="text-code-blue">{cluster.subject_value}</span>
                  </code>
                  <Button
                    variant="ghost"
                    size="icon-xs"
                    aria-label="copy"
                    onClick={() => {
                      void navigator.clipboard?.writeText(cluster.subject_value)
                      setCopied(true)
                      window.setTimeout(() => setCopied(false), 1200)
                    }}
                  >
                    <HugeiconsIcon icon={copied ? Tick02Icon : CopyIcon} strokeWidth={2} className={cn('size-3.5', copied && 'text-success')} />
                  </Button>
                </div>
              </Row>
              <Row label={t('recommendation')}>
                <p className="text-fg-strong">{cluster.recommendation || '—'}</p>
              </Row>
              {cluster.is_likely_fp && cluster.fp_reason && (
                <Row label={t('likelyFp')}>
                  <p className="text-muted-foreground">{cluster.fp_reason}</p>
                </Row>
              )}
              <Row label={t('dispositionLabel')}>
                <div className="flex flex-wrap gap-1.5">
                  {STATUS_ORDER.map((s) => (
                    <Button
                      key={s}
                      size="sm"
                      variant={status === s ? 'default' : 'outline'}
                      aria-pressed={status === s}
                      onClick={() => onChangeStatus(cluster, s)}
                    >
                      {statusLabel(s)}
                    </Button>
                  ))}
                </div>
              </Row>
              <Row label={t('alertIdsLabel', { n: cluster.alert_ids.length })}>
                <div className="flex flex-wrap gap-1.5">
                  {cluster.alert_ids.slice(0, 40).map((id) => (
                    <code key={id} className="rounded-full bg-accent px-2 py-0.5 font-mono text-11 [box-shadow:var(--shadow-ring-light)]">{id}</code>
                  ))}
                  {cluster.alert_ids.length > 40 && (
                    <span className="font-mono text-11 text-muted-foreground">+{cluster.alert_ids.length - 40}</span>
                  )}
                </div>
              </Row>
            </div>

            <SheetFooter className="shrink-0 flex-row justify-end gap-2 border-t px-5 py-3">
              <Button onClick={() => onInvestigate(cluster)}>
                <HugeiconsIcon icon={SparklesIcon} strokeWidth={2} className="size-3.5" />
                {t('investigate')}
              </Button>
            </SheetFooter>
          </>
        )}
      </SheetContent>
    </Sheet>
  )
}
