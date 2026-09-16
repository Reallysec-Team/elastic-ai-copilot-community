import { Badge, type BadgeProps } from '@/components/reui/badge'
import { severityBadgeVariant, severityLabel } from '@/lib/severity'

/*
 * 严重度徽标，全站一份。全部用 `-light` 淡底——和模板里其他状态徽标同一种质感；
 * 「严重」不再用实底（红的、黑的都试过，放进一排淡底徽标里像贴错了地方），
 * 改用淡红底 + 一枚实心红点 + 加粗（settings-4 的 ConnectionStatus 那种圆点
 * 写法）来跳出「高」。
 */
export function SeverityBadge({ severity, size = 'sm', className }: { severity: string | null | undefined; size?: BadgeProps['size']; className?: string }) {
  const sev = (severity ?? '').toLowerCase()
  return (
    <Badge size={size} variant={severityBadgeVariant(sev)} className={sev === 'critical' ? `font-semibold ${className ?? ''}` : className}>
      {sev === 'critical' && <span className="size-1.5 rounded-full bg-destructive" aria-hidden="true" />}
      {severityLabel(sev)}
    </Badge>
  )
}
