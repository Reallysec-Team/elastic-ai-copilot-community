import { useEffect, useState } from 'react'
import { HugeiconsIcon } from '@hugeicons/react'
import {
  AlertCircleIcon, CheckmarkCircle02Icon, Download01Icon, Loading03Icon,
} from '@hugeicons/core-free-icons'
import { toast } from 'sonner'

import { GatedButton } from '@/components/gated-button'
import { api } from '@/lib/api'
import { SettingField } from '@/components/blocks/settings-3/components/setting-field'
import { Alert, AlertDescription } from '@/components/reui/alert'
import { Badge } from '@/components/reui/badge'
import { SettingsCard } from '@/components/settings/settings-card'
import { useT } from '@/lib/i18n'
import { settingsCopy } from '@/locales/settings'

/* ---------------- 在线更新 ---------------- */

/*
 * Online image update. Read-only mirror of the release pipeline: the container
 * only downloads + verifies + stages a newer image; the actual install
 * (docker load / retag / health-gate / rollback) is the host-side
 * deploy/rst-update.sh — a container can't run docker. So this card gets the
 * operator to "staged & ready" and then tells them to run ./rst-update.sh.
 * Backend endpoints (both X-RST-Admin-Token gated):
 *   GET  /api/admin/release/status    → running/staged version + available offer
 *   POST /api/admin/release/download  → download + verify + stage, returns status
 */
export function OnlineUpdateCard() {
  const t = useT(settingsCopy)
  const [status, setStatus] = useState<Awaited<ReturnType<typeof api.releaseStatus>> | null>(null)
  const [loading, setLoading] = useState(false)
  const [downloading, setDownloading] = useState(false)
  const [err, setErr] = useState<string | null>(null)

  async function load() {
    setLoading(true)
    setErr(null)
    try {
      setStatus(await api.releaseStatus())
    } catch (e) {
      setErr(e instanceof Error ? e.message : String(e))
    } finally {
      setLoading(false)
    }
  }

  useEffect(() => {
    // eslint-disable-next-line react-hooks/set-state-in-effect -- initial load on mount
    load()
  }, [])

  async function download() {
    setDownloading(true)
    setErr(null)
    try {
      await api.releaseDownload()
      await load() // refresh running/staged/available from the source of truth
      toast.success(t('updateStaged'))
    } catch (e) {
      // Backend returns a Chinese detail (「当前没有可下载的新版本」/「下载/暂存失败：…」);
      // pass it straight through.
      setErr(e instanceof Error ? e.message : String(e))
    } finally {
      setDownloading(false)
    }
  }

  const available = status?.available ?? null
  const staged = status?.staged_version ?? null
  // Backend only ever offers a version strictly newer than running, so "有 offer
  // 且尚未暂存该版本" = 可下载。已暂存该版本 = 就绪、按钮禁用。
  const canDownload = !!available && available.version !== staged
  // 「已暂存但还没装」不能写成「已是最新」—— 那会让人以为没事可做，而实际上
  // 还差宿主机上的一条命令。
  const stagedReady = !!available && available.version === staged
  // 一次都没和更新源（许可服务器心跳）通过话：不知道有没有新版，不能说「已是最新」。
  const unchecked = !loading && status != null && status.checked === false && !available && !staged

  return (
    <SettingsCard
      title={t('updateCardTitle')}
      footer={
        err || staged ? (
          /* `FrameFooter` 自己就是 flex-col，这里不用再套一层间距容器。 */
          <>
            {err && (
              <Alert variant="destructive">
                <HugeiconsIcon icon={AlertCircleIcon} strokeWidth={2} className="size-4" />
                <AlertDescription>{err}</AlertDescription>
              </Alert>
            )}
            {staged && (
              <Alert variant="success">
                <HugeiconsIcon icon={CheckmarkCircle02Icon} strokeWidth={2} className="size-4" />
                <AlertDescription>
                  {/* `AlertDescription` 是 grid，直接子节点各占一行 —— 整句要包在
                      一个 p 里，否则版本号和命令会各占一行。 */}
                  <p>
                    {t('updateReady', { version: staged })}
                  </p>
                </AlertDescription>
              </Alert>
            )}
          </>
        ) : null
      }
    >
      <SettingField
        title={t('updateCurrentVersion')}
      >
        <div className="flex flex-wrap items-center gap-2 @md/field-group:justify-end">
          <code className="font-mono text-sm">{loading ? '…' : status?.running_version ?? '—'}</code>
          {!loading && (
            <Badge
              size="sm"
              variant={canDownload ? 'primary-light' : stagedReady ? 'success-light' : 'secondary'}
            >
              {canDownload
                ? t('updateFound', { version: available.version })
                : stagedReady
                  ? t('updateStagedPending', { version: staged })
                  : unchecked
                    ? t('updateUnchecked')
                    : t('updateLatest')}
            </Badge>
          )}
        </div>
      </SettingField>

      <SettingField title={t('updateDownloadTitle')} last>
        <div className="flex @md/field-group:justify-end">
          <GatedButton
            gate="admin"
            className="rounded-full"
            size="sm"
            onClick={() => void download()}
            disabled={loading || downloading || !canDownload}
          >
            <HugeiconsIcon
              icon={downloading ? Loading03Icon : Download01Icon}
              strokeWidth={2}
              className={downloading ? 'size-3.5 animate-spin' : 'size-3.5'}
            />
            {downloading
              ? t('updateDownloading')
              : canDownload
                ? t('updateDownload')
                : stagedReady
                  ? t('updateStagedShort')
                  : unchecked
                    ? t('updateUncheckedShort')
                    : t('updateLatest')}
          </GatedButton>
        </div>
      </SettingField>
    </SettingsCard>
  )
}
