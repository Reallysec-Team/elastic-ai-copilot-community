import type { HTMLAttributes } from 'react'
import { cn } from '@/lib/utils'
import { Badge } from '@/components/reui/badge'

/*
 * `Pill` is now a semantic alias over ReUI's `Badge`: it maps this product's
 * severity vocabulary onto the donor's variants and renders the donor's
 * component. It is not a second badge — there is one implementation, and this
 * is the table that says what "sev-high" looks like.
 *
 * Keeping the name is what let 51 call sites across 14 files change appearance
 * without being touched. Renaming them would have been a rename, not a
 * redesign, and every one of them would have had to re-derive the same mapping
 * at the call site.
 *
 * The `.pill` / `.sev-*` CSS this used to render is gone. It drew a 10px-padded
 * full-radius chip off the Geist palette; the donor's badge is smaller, squarer
 * and takes its colour from the same tokens as everything else on the page,
 * which is the point.
 */

type Tone =
  | 'blue'
  | 'gray'
  | 'sev-info'
  | 'sev-low'
  | 'sev-medium'
  | 'sev-high'
  | 'sev-critical'

/*
 * Severity climbs info → low → medium → high → critical. The donor's `-light`
 * variants are the tinted chips this product already used; `invert` (a solid
 * near-black) is the top step, matching the black `sev-critical` chip that
 * deliberately broke out of the colour ramp so a critical never reads as "one
 * more red thing".
 */
const TONE_VARIANT: Record<Tone, React.ComponentProps<typeof Badge>['variant']> = {
  blue: 'info-light',
  gray: 'secondary',
  'sev-info': 'info-light',
  'sev-low': 'secondary',
  'sev-medium': 'warning-light',
  'sev-high': 'destructive-light',
  'sev-critical': 'invert',
}

export function Pill({
  className,
  tone = 'blue',
  children,
  ...rest
}: HTMLAttributes<HTMLSpanElement> & { tone?: Tone }) {
  return (
    <Badge variant={TONE_VARIANT[tone]} radius="full" className={className} {...rest}>
      {children}
    </Badge>
  )
}

/*
 * Small technical label — section eyebrows ("PROMPT VERSION", "INDEX") and the
 * captions above form fields.
 *
 * It used to be uppercase Geist Mono at 12px, which is a strong voice and the
 * loudest remaining trace of the old design: every form in the product was
 * captioned in monospace. The donor labels fields in the body face at `text-xs`
 * muted, so that is what this is now. The component stays because 61 call sites
 * mean it, and because "this is a label" is worth keeping named.
 */
export function LabelMono({
  className,
  children,
  ...rest
}: HTMLAttributes<HTMLSpanElement>) {
  return (
    <span
      className={cn('text-xs leading-none font-medium text-muted-foreground', className)}
      {...rest}
    >
      {children}
    </span>
  )
}
