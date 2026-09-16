import { HugeiconsIcon } from '@hugeicons/react'
import { HistoryIcon } from '@hugeicons/core-free-icons'

import { useT } from '@/lib/i18n'
import { OPEN_HISTORY_EVENT } from '@/components/HistoryDrawer'
import { shellCopy } from '@/locales/shell'
import { Button } from '@/components/ui/button'

/*
 * The history drawer's opener, in the slot roster gives its notifications bell.
 * Same variant and size the rail header's two buttons take, so the pair reads
 * as one control group.
 *
 * It used to live in the top bar; before that it was a floating pill in the
 * bottom-right corner, which on narrow screens had to dodge the composer to
 * avoid covering 发送.
 */
export function HistoryButton() {
  const t = useT(shellCopy)
  return (
    <Button
      type="button"
      variant="ghost"
      size="icon-sm"
      title={t('queryHistory')}
      aria-label={t('queryHistory')}
      onClick={() => window.dispatchEvent(new Event(OPEN_HISTORY_EVENT))}
      className="size-8 opacity-60 hover:opacity-100"
    >
      <HugeiconsIcon icon={HistoryIcon} strokeWidth={2} className="size-4" aria-hidden="true" />
    </Button>
  )
}
