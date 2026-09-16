import { HugeiconsIcon } from '@hugeicons/react'
import { CheckmarkCircle02Icon, Loading03Icon } from '@hugeicons/core-free-icons'

import { GatedButton } from '@/components/gated-button'
import { Button } from '@/components/ui/button'
import { useT } from '@/lib/i18n'
import { commonCopy } from '@/locales/common'
import { settingsCopy } from '@/locales/settings'

/*
 * 「有未保存的更改」浮条。
 *
 * 从设置页里抽出来的：审计转发搬去「对外通道」页之后，两个屏各管一段设置，各自
 * 要有一条自己的浮条。
 *
 * 位置上的一个坑（原样保留）：`left-1/2 + -translate-x-1/2` 会把可用宽度限成视口
 * 的一半，375 宽下这条浮条被挤成一个圆、字一列一个。所以是整宽容器里居中。
 */
export function SaveBar({
  dirty, saving, onSave, onRevert,
}: {
  dirty: boolean
  saving: boolean
  onSave: () => void
  onRevert: () => void
}) {
  const t = useT(settingsCopy)
  const c = useT(commonCopy)
  if (!dirty) return null

  return (
    <div className="pointer-events-none fixed inset-x-0 bottom-24 z-30 flex justify-center px-3">
      <div className="pointer-events-auto flex items-center gap-3 rounded-full border border-border bg-popover px-3 py-2 shadow-lg">
        <span className="block size-1.5 rounded-full bg-primary" aria-hidden="true" />
        <span className="text-sm font-medium">{t('unsavedChanges')}</span>
        <Button variant="ghost" size="sm" onClick={onRevert} disabled={saving}>
          {t('discard')}
        </Button>
        <GatedButton
          gate="admin"
          className="rounded-full"
          size="sm"
          onClick={onSave}
          disabled={saving}
        >
          <HugeiconsIcon
            icon={saving ? Loading03Icon : CheckmarkCircle02Icon}
            strokeWidth={2}
            className={saving ? 'size-3.5 animate-spin' : 'size-3.5'}
          />
          {saving ? `${c('saving')}` : t('saveAndApply')}
        </GatedButton>
      </div>
    </div>
  )
}
