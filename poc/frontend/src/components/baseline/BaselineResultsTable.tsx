import { useState } from 'react'
import { HugeiconsIcon } from '@hugeicons/react'
import { ChevronDownIcon, ChevronRightIcon, Wrench01Icon } from '@hugeicons/core-free-icons'
import type { BaselineResult } from '@/lib/api'
import { Frame, FramePanel } from '@/components/reui/frame'
import { cn } from '@/lib/utils'
import { Badge } from '@/components/reui/badge'
import { VERDICT_STYLE, verdictLabel } from '@/components/baseline/verdictStyle'
import { useT, translate } from '@/lib/i18n'
import { baselineCopy } from '@/locales/baseline'

/**
 * Shared baseline results table with expandable 不合规原因 detail rows.
 * Both the 巡检结果 tab and the 历史轮次 drill-down render identical rows via this.
 */
export function BaselineResultsTable({ results }: { results: BaselineResult[] }) {
  const t = useT(baselineCopy)
  // Row expansion — reveals the 不合规原因 detail (期望 vs 实测 + 整改 + 标准引用).
  const [expanded, setExpanded] = useState<string | null>(null)
  return (
    <Frame dense spacing="sm" className="overflow-hidden">
      {/* 表格自己画内边距，panel 再来一层就是双层内边距 —— p-0 + shadow-none。 */}
      <FramePanel className="p-0 shadow-none">
        <div className="overflow-x-auto">
          <table className="w-full text-left text-sm">
            <thead className="border-b border-border text-xs text-muted-foreground">
              <tr>
                <th scope="col" className="w-8 px-2 py-2" />
                <th scope="col" className="px-3 py-2 font-medium">{t('colHost')}</th>
                <th scope="col" className="px-3 py-2 font-medium">{t('colRule')}</th>
                <th scope="col" className="px-3 py-2 font-medium">{t('colCategory')}</th>
                <th scope="col" className="px-3 py-2 font-medium">{t('colSeverity')}</th>
                <th scope="col" className="px-3 py-2 font-medium">{t('colVerdict')}</th>
                <th scope="col" className="px-3 py-2 font-medium">{t('colActual')}</th>
              </tr>
            </thead>
            <tbody>
              {results.map((r) => {
                const st = VERDICT_STYLE[r.verdict] ?? VERDICT_STYLE.error
                const key = `${r.host}:${r.rule_id}`
                const open = expanded === key
                return (
                  <FragmentRow
                    key={key}
                    r={r}
                    st={st}
                    open={open}
                    onToggle={() => setExpanded(open ? null : key)}
                  />
                )
              })}
            </tbody>
          </table>
        </div>
      </FramePanel>
    </Frame>
  )
}

/** One result row + its expandable 不合规原因 detail (期望 vs 实测 + 整改 + 标准引用). */
function FragmentRow({
  r,
  st,
  open,
  onToggle,
}: {
  r: BaselineResult
  st: (typeof VERDICT_STYLE)[string]
  open: boolean
  onToggle: () => void
}) {
  const hasDetail = !!(r.expected || r.remediation || (r.standard_refs && r.standard_refs.length))
  return (
    <>
      <tr
        className={cn(
          'border-b border-border hover:bg-muted/50',
          hasDetail && 'cursor-pointer',
          open && 'bg-muted/50',
        )}
        onClick={hasDetail ? onToggle : undefined}
      >
        <td className="px-2 py-2 text-muted-foreground">
          {hasDetail &&
            (open ? <HugeiconsIcon icon={ChevronDownIcon} strokeWidth={2} className="size-4" /> : <HugeiconsIcon icon={ChevronRightIcon} strokeWidth={2} className="size-4" />)}
        </td>
        <td className="px-3 py-2 font-mono text-xs">{r.host}</td>
        <td className="px-3 py-2">
          <div className="font-medium">{r.title}</div>
          <div className="font-mono text-10 text-muted-foreground">{r.rule_id}</div>
        </td>
        <td className="px-3 py-2 text-xs text-muted-foreground">{r.category}</td>
        <td className="px-3 py-2 text-xs">{r.severity}</td>
        <td className="px-3 py-2">
          <Badge size="sm" variant={st.variant}>{verdictLabel(r.verdict)}</Badge>
        </td>
        <td className="px-3 py-2 font-mono text-xs text-muted-foreground">{r.actual}</td>
      </tr>
      {open && hasDetail && (
        <tr className="border-b border-border bg-muted/50">
          <td />
          {/* 这一格自己开容器：@ 变体要按详情区自己的宽度断，不是按窗口。 */}
          <td colSpan={6} className="@container px-3 pb-4 pt-1">
            <div className="grid gap-3 @md:grid-cols-2">
              <ReasonField label={translate(baselineCopy, 'fieldExpected')} value={r.expected} mono />
              <ReasonField label={translate(baselineCopy, 'fieldActual')} value={r.actual} mono danger={r.verdict === 'fail'} />
            </div>
            {r.remediation && (
              <div className="mt-3 flex items-start gap-2 rounded-lg bg-background px-3 py-2">
                <HugeiconsIcon icon={Wrench01Icon} strokeWidth={2} className="mt-0.5 size-4 shrink-0 text-info" />
                <div>
                  <div className="text-xs font-medium text-info">{translate(baselineCopy, 'fieldRemediation')}</div>
                  <div className="mt-0.5 whitespace-pre-wrap text-xs text-foreground">{r.remediation}</div>
                </div>
              </div>
            )}
            {r.standard_refs && r.standard_refs.length > 0 && (
              <div className="mt-3 flex flex-wrap items-center gap-1.5">
                <span className="text-xs text-muted-foreground">{translate(baselineCopy, 'fieldStandardRefs')}</span>
                {r.standard_refs.map((ref) => (
                  <span
                    key={ref}
                    className="rounded bg-secondary px-1.5 py-0.5 font-mono text-10 text-muted-foreground"
                  >
                    {ref}
                  </span>
                ))}
              </div>
            )}
          </td>
        </tr>
      )}
    </>
  )
}

function ReasonField({ label, value, mono, danger }: { label: string; value: string; mono?: boolean; danger?: boolean }) {
  return (
    <div>
      <div className="text-xs text-muted-foreground">{label}</div>
      <div className={cn('mt-0.5 break-words text-xs', mono && 'font-mono', danger ? 'text-destructive' : 'text-foreground')}>
        {value || '—'}
      </div>
    </div>
  )
}
