import { useState } from 'react'
import { HugeiconsIcon } from '@hugeicons/react'
import { CheckmarkCircle02Icon, Loading03Icon } from '@hugeicons/core-free-icons'
import { toast } from 'sonner'

import { GatedButton } from '@/components/gated-button'
import { api } from '@/lib/api'
import {
  EMPTY_ES, EsFields, EsStatusRow, EsTestNotice, hasEsNotice, useEsProbe,
  type EsKey, type EsSettings,
} from '@/components/settings/es-connection'
import { Frame, FramePanel } from '@/components/reui/frame'
import { Button } from '@/components/ui/button'
import {
  Dialog, DialogContent, DialogDescription, DialogFooter, DialogHeader, DialogTitle,
} from '@/components/ui/dialog'
import { FieldGroup } from '@/components/ui/field'
import { useT } from '@/lib/i18n'
import { settingsCopy } from '@/locales/settings'

/*
 * 首次安装引导 —— 只在「这台机器从来没配过 ES」时弹（`/readyz` 的 es_configured
 * 为 false）。不填这一项，产品里没有任何一个页面有内容，所以它不是一条提示而是
 * 一个必答题；让客户自己去设置页在五张卡里找，是把必答题伪装成可选项。
 *
 * 边界：配过、但此刻连不上 —— 不弹。那不是安装问题，而且客户在这个框里也修不好，
 * 却会被挡住去激活页或历史记录。那种情况留给 AppShell 顶部那条横幅。
 *
 * 可关闭（「稍后配置」）：客户想先看看产品长什么样、先激活 license，都不该被卡在
 * 第一屏。关掉退回横幅，下次登录再弹。
 *
 * 表单本体与设置页共用 `es-connection`，不是抄一份。
 */
export function EsSetupDialog({ open, onClose }: { open: boolean; onClose: () => void }) {
  const t = useT(settingsCopy)
  const [draft, setDraft] = useState<EsSettings>(EMPTY_ES)
  const [saving, setSaving] = useState(false)
  const { test, setTest, probeDraft } = useEsProbe()

  function patch(key: EsKey, value: string) {
    setDraft((d) => ({ ...d, [key]: value }))
    setTest({ phase: 'idle' })
  }

  async function saveAndConnect() {
    setSaving(true)
    try {
      await api.saveSettings(draft)
      toast.success(t('setupOk'))
      // 整页重载而不是逐个刷新：这一步之前每个页面拿到的都是「没有数据源」的
      // 空结果，重载是最省事也最不会漏的一种失效方式。
      window.location.reload()
    } catch (e) {
      toast.error(e instanceof Error ? e.message : String(e))
      setSaving(false)
    }
  }

  return (
    <Dialog open={open} onOpenChange={(v) => !v && onClose()}>
      <DialogContent className="sm:max-w-2xl">
        <DialogHeader>
          <DialogTitle>{t('setupTitle')}</DialogTitle>
          <DialogDescription>
            {t('setupDesc')}
          </DialogDescription>
        </DialogHeader>

        <div className="flex flex-col gap-2.5">
          {/* 和设置页那张卡同一个壳（`Frame dense` + 贴边的 `FramePanel`），
              而不是自己画一圈圆角边框 —— 同一份表单在两个入口里长得一样。 */}
          <Frame dense className="w-full min-w-0">
            <FramePanel className="p-0!">
              <EsStatusRow
                url={draft['es.url']}
                test={test}
                onTest={() => void probeDraft(draft)}
                disabled={saving}
              />
              <FieldGroup className="gap-0 border-t border-border">
                <EsFields draft={draft} patch={patch} loading={saving} />
              </FieldGroup>
            </FramePanel>
          </Frame>
          {hasEsNotice(test) ? <EsTestNotice test={test} /> : null}
        </div>

        <DialogFooter>
          <Button variant="ghost" onClick={onClose} disabled={saving}>
            {t('setupLater')}
          </Button>
          {/* 没测通不给存 —— 存进一个连不上的地址，客户下一步会在一个个空页面上
              找原因，而问题在这里。 */}
          <GatedButton gate="admin" onClick={() => void saveAndConnect()} disabled={saving || test.phase !== 'ok'}>
            <HugeiconsIcon
              icon={saving ? Loading03Icon : CheckmarkCircle02Icon}
              strokeWidth={2}
              className={saving ? 'size-3.5 animate-spin' : 'size-3.5'}
            />
            {saving ? t('setupSaving') : t('setupSave')}
          </GatedButton>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  )
}
