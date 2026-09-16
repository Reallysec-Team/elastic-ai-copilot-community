import { useMemo, useState } from 'react'
import { useNavigate } from '@tanstack/react-router'
import { HugeiconsIcon } from '@hugeicons/react'
import { Cancel01Icon, Search01Icon } from '@hugeicons/core-free-icons'
import { useTable, type ColumnDef } from '@tanstack/react-table'

import type { RealtimeAlert } from '@/lib/api'
import { SeverityBadge } from '@/components/severity-badge'
import { useT } from '@/lib/i18n'
import { postureCopy } from '@/locales/posture'
import { DataGrid, dataGridFeatures, type DataGridFeatures } from '@/components/reui/data-grid/data-grid'
import { DataGridColumnHeader } from '@/components/reui/data-grid/data-grid-column-header'
import { DataGridScrollArea } from '@/components/reui/data-grid/data-grid-scroll-area'
import { DataGridTable } from '@/components/reui/data-grid/data-grid-table'
import { Frame, FrameDescription, FrameHeader, FramePanel, FrameTitle } from '@/components/reui/frame'
import { InputGroup, InputGroupAddon, InputGroupButton, InputGroupInput } from '@/components/ui/input-group'

/*
 * 「最新告警」照 `@reui/dashboard-7` 的 Order Queue：Frame 卡头带搜索框，面板里一张
 * 紧凑 DataGrid，每行一个直达动作。原来是 list-8 的两行文字列表，看不出主体和时间。
 * 数据就是态势页已经拉的那 10 条，客户端搜索，不分页。
 */

export function RecentAlertsGrid({
  title, alerts, emptyText, actionLabel,
}: {
  title: string
  alerts: RealtimeAlert[]
  emptyText: string
  actionLabel: string
}) {
  const t = useT(postureCopy)
  const navigate = useNavigate()
  const [query, setQuery] = useState('')

  const rows = useMemo(() => {
    const q = query.trim().toLowerCase()
    if (!q) return alerts
    return alerts.filter((a) =>
      (a.rule_name || a.rule_id).toLowerCase().includes(q)
      || (a.subject_value ?? '').toLowerCase().includes(q),
    )
  }, [alerts, query])

  const columns = useMemo<ColumnDef<DataGridFeatures, RealtimeAlert>[]>(() => [
    {
      accessorKey: 'severity',
      id: 'severity',
      header: ({ column }) => <DataGridColumnHeader title={t('colSeverity')} column={column} />,
      cell: ({ row }) => (
        <SeverityBadge severity={row.original.severity} />
      ),
      size: 88,
      enableSorting: false,
      meta: { headerTitle: t('colSeverity') },
    },
    {
      accessorKey: 'rule_name',
      id: 'rule',
      header: ({ column }) => <DataGridColumnHeader title={t('colRule')} column={column} />,
      cell: ({ row }) => (
        <span className="block truncate font-medium" title={row.original.rule_name || row.original.rule_id}>
          {row.original.rule_name || row.original.rule_id}
        </span>
      ),
      minSize: 160,
      enableSorting: false,
      meta: { headerTitle: t('colRule'), autoSize: true },
    },
    {
      accessorKey: 'subject_value',
      id: 'subject',
      header: ({ column }) => <DataGridColumnHeader title={t('colSubject')} column={column} />,
      cell: ({ row }) => (
        <span className="block truncate font-mono text-xs text-muted-foreground">
          {row.original.subject_value ?? '—'}
        </span>
      ),
      size: 120,
      enableSorting: false,
      meta: { headerTitle: t('colSubject') },
    },
    {
      accessorKey: '@timestamp',
      id: 'time',
      header: ({ column }) => <DataGridColumnHeader title={t('colTime')} column={column} />,
      cell: ({ row }) => (
        <span className="whitespace-nowrap font-mono text-xs tabular-nums text-muted-foreground">
          {new Date(row.original['@timestamp']).toLocaleString(undefined, {
            month: '2-digit', day: '2-digit', hour: '2-digit', minute: '2-digit', hour12: false,
          })}
        </span>
      ),
      size: 112,
      enableSorting: false,
      meta: { headerTitle: t('colTime') },
    },
  ], [t])

  const table = useTable({
    features: dataGridFeatures,
    columns,
    data: rows,
    getRowId: (r) => r.alert_id,
  })

  return (
    <DataGrid
      table={table}
      recordCount={rows.length}
      emptyMessage={emptyText}
      // 整行可点直达这一条告警 —— 半宽卡里放不下第五列「去处置」。
      onRowClick={(r) => void navigate({ to: '/alerts', search: { alert: r.alert_id } })}
      tableLayout={{ dense: true, rowBorder: true, headerSticky: false, columnsVisibility: false, columnsResizable: false, columnsMovable: false }}
      tableClassNames={{
        bodyRow: '[&>td]:h-11',
        edgeCell: 'first:ps-(--frame-panel-header-px) last:pe-(--frame-panel-header-px)',
      }}
    >
      <Frame dense className="flex h-full min-w-0 flex-col">
        <FrameHeader className="flex-col gap-2 @md:flex-row @md:items-center @md:justify-between">
          <div className="flex flex-col gap-px">
            <FrameTitle>{title}</FrameTitle>
            <FrameDescription className="text-xs">{rows.length} / {alerts.length} · {actionLabel}</FrameDescription>
          </div>
          <InputGroup className="w-full @md:w-56">
            <InputGroupAddon>
              <HugeiconsIcon icon={Search01Icon} strokeWidth={2} aria-hidden="true" />
            </InputGroupAddon>
            <InputGroupInput
              value={query}
              onChange={(e) => setQuery(e.target.value)}
              placeholder={t('recentSearch')}
              aria-label={t('recentSearch')}
            />
            {query.length > 0 && (
              <InputGroupAddon align="inline-end">
                <InputGroupButton size="icon-xs" aria-label="clear" onClick={() => setQuery('')}>
                  <HugeiconsIcon icon={Cancel01Icon} strokeWidth={2} aria-hidden="true" />
                </InputGroupButton>
              </InputGroupAddon>
            )}
          </InputGroup>
        </FrameHeader>
        <FramePanel className="min-h-0 flex-1 p-0!">
          <DataGridScrollArea>
            <DataGridTable />
          </DataGridScrollArea>
        </FramePanel>
      </Frame>
    </DataGrid>
  )
}
