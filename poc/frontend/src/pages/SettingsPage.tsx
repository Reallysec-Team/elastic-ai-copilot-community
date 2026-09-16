import { useCallback, useState } from 'react'
import { HugeiconsIcon } from '@hugeicons/react'
import { AlertCircleIcon } from '@hugeicons/core-free-icons'

import { api } from '@/lib/api'
import { useSettingsDraft } from '@/hooks/useSettingsDraft'
import {
  EsFields, EsStatusRow, EsTestNotice, hasEsNotice, useEsProbe, type EsTestState,
} from '@/components/settings/es-connection'
import { OnlineUpdateCard } from '@/components/settings/online-update-card'
import { SaveBar } from '@/components/settings/save-bar'
import { SettingsCard } from '@/components/settings/settings-card'
import { SettingField } from '@/components/blocks/settings-3/components/setting-field'
import { Alert, AlertDescription } from '@/components/reui/alert'
import { useT } from '@/lib/i18n'
import { settingsCopy, type SettingsKey } from '@/locales/settings'
import { PageHeader } from '@/components/shell/page-header'
import { AdminOnlyView, useIsAdmin } from '@/components/gated-button'
import { FieldDescription } from '@/components/ui/field'
import { Input } from '@/components/ui/input'
import { ToggleGroup, ToggleGroupItem } from '@/components/ui/toggle-group'

/*
 * Gateway settings — operational config the customer admin can flip without
 * SSH'ing into the gateway. Backed by /api/settings (writes settings.yml +
 * patches os.environ + resets affected modules).
 *
 * Only these keys are editable here:
 *   - connection:   es.url, es.user, es.password, es.verify_certs, es.ca_cert
 *   - data access:  index_whitelist, masking_mode
 *
 * 审计 + 多通道转发那六个键搬去了「对外通道」页（`components/settings/audit-card`）
 * —— 它和飞书、邮件是同一件事：有什么东西会离开这套系统。写的是差量，两个屏各管
 * 一段设置互不覆盖。
 *
 * Read-only mirrors (env-only): RAG embed model, gateway shared secret,
 * RAG embed dim. Editing those still requires .env + restart since the
 * affected clients are constructed at startup.
 *
 * 版式按 `@reui/settings-3`：每张卡是一列 `SettingField` 行，左边「这项是什么 +
 * 一句人话」，右边是这项自己的控件。原来是「一行 mono 小标题 + 右上角挤一行灰色
 * 提示 + 下面一个满宽输入框」——提示被挤成两行，读的人得在标题和提示之间来回跳。
 *
 * 两个 hand-rolled 的东西也换掉了：一排药丸按钮换成 `ToggleGroup`（脱敏模式、
 * TLS 校验），自己画的「已保存」浮条换成 sonner 的 toast。
 */

const SETTINGS_KEYS = [
  'es.url',
  'es.user',
  'es.password',
  'es.verify_certs',
  'es.ca_cert',
  'engine',
  'index_whitelist',
  'masking_mode',
] as const

type SettingsBlob = Record<(typeof SETTINGS_KEYS)[number], string>

const MASKING_MODES = ['cloud', 'private', 'airgapped'] as const

const MASKING_KEY: Record<(typeof MASKING_MODES)[number], SettingsKey> = {
  cloud: 'maskCloud',
  private: 'maskPrivate',
  airgapped: 'maskAirgapped',
}

/*
 * GET /api/settings 也要管理员（里面有 audit.webhook_url 这类 URL 即凭据的值、
 * ES 地址和用户名）。非管理员不挂载下面那个组件：挂载了只会拿一个 403 换一整页
 * 错误，而"出错了"和"你看不到"该给人两种不同的下一步。
 */
export function SettingsPage() {
  const t = useT(settingsCopy)
  const isAdmin = useIsAdmin()
  if (!isAdmin) return <AdminOnlyView title={t('title')} />
  return <SettingsView />
}

function SettingsView() {
  const t = useT(settingsCopy)
  // Read-only env mirrors
  const [maskingInfo, setMaskingInfo] = useState<{ current_mode: string; available_modes: string[] } | null>(null)

  /* 连接自检结果。`idle` 是「这套参数还没验证过」——改了任意一个 es.* 字段就回到
     idle，保存闸也跟着关上：存进一个连不上的地址，会把管理员锁在唯一能改回来的
     页面外面。 */
  const { test: esTest, setTest: setEsTest, probe: probeEs, probeDraft } = useEsProbe()

  const onLoaded = useCallback(() => {
    void api.maskingInfo().then(setMaskingInfo).catch(() => {})
    // 空 body = 用当前生效的配置探一次，页面一打开就能看到「连上没有」。
    void probeEs({})
  }, [probeEs])

  /* 保存前的闸：改了连接参数就必须先测通。这不是形式主义，理由见上面 esTest。 */
  const beforeSave = useCallback(
    (diff: Record<string, string>) =>
      Object.keys(diff).some((k) => k.startsWith('es.')) && esTest.phase !== 'ok'
        ? t('mustTestFirst')
        : null,
    [esTest.phase, t],
  )

  const {
    draft, patch: patchKey, dirty, loading, saving, error, save, revert,
  } = useSettingsDraft({ keys: SETTINGS_KEYS, beforeSave, onLoaded })

  const patch = useCallback(
    (key: keyof SettingsBlob, value: string) => {
      patchKey(key, value)
      if (key.startsWith('es.')) setEsTest({ phase: 'idle' })
    },
    [patchKey, setEsTest],
  )

  return (
    <div className="@container flex w-full flex-col gap-5">
      <PageHeader title={t('title')} />

      {error && (
        <Alert variant="destructive">
          <HugeiconsIcon icon={AlertCircleIcon} strokeWidth={2} className="size-4" />
          <AlertDescription>{error}</AlertDescription>
        </Alert>
      )}

      {/* 安装后的第一步就在这张卡里 —— 放在最上面，新装的机器打开设置页第一眼
          看到的就是「连上没有」。 */}
      <section aria-label={t('secCluster')}>
        <EsConnectionCard
          draft={draft}
          patch={patch}
          loading={loading}
          test={esTest}
          onTest={() => void probeDraft(draft)}
        />
      </section>

      <section aria-label={t('secDataAccess')}>
        <DataAccessCard
          draft={draft}
          patch={patch}
          maskingInfo={maskingInfo}
          loading={loading}
        />
      </section>

      {/* 审计 + 多通道转发、投递配置都搬去了「对外通道」页：它们回答的是同一个
          问题 —— 有什么东西会离开这套系统、走哪条路。设置页管的是这台网关本身
          怎么配。 */}

      {/* 资产/身份导入搬去了「资产与身份」页：那不是这台网关怎么配，是模型看你的
          数据时能带上什么语境 —— 和字段字典、知识库同类。 */}

      <section aria-label={t('secVersion')}>
        <OnlineUpdateCard />
      </section>

      <SaveBar dirty={dirty} saving={saving} onSave={() => void save()} onRevert={revert} />
    </div>
  )
}

/* ---------------- Elasticsearch 连接 ---------------- */

/* 字段本体在 `components/settings/es-connection` —— 首次安装的弹窗用的是同一份。
   这里只负责把它放进设置页的卡壳里。 */
function EsConnectionCard({
  draft,
  patch,
  loading,
  test,
  onTest,
}: {
  draft: SettingsBlob
  patch: (k: keyof SettingsBlob, v: string) => void
  loading: boolean
  test: EsTestState
  onTest: () => void
}) {
  const t = useT(settingsCopy)
  return (
    <SettingsCard
      title={t('cardEsTitle')}
      footer={hasEsNotice(test) ? <EsTestNotice test={test} /> : null}
    >
      <EsStatusRow url={draft['es.url']} test={test} onTest={onTest} disabled={loading} />
      <EsFields draft={draft} patch={patch} loading={loading} />
    </SettingsCard>
  )
}

/* ---------------- 数据访问 ---------------- */

function DataAccessCard({
  draft,
  patch,
  maskingInfo,
  loading,
}: {
  draft: SettingsBlob
  patch: (k: keyof SettingsBlob, v: string) => void
  maskingInfo: { current_mode: string; available_modes: string[] } | null
  loading: boolean
}) {
  const t = useT(settingsCopy)
  const licenseBlocked =
    maskingInfo != null &&
    draft.masking_mode !== '' &&
    !maskingInfo.available_modes.includes(draft.masking_mode)

  return (
    <SettingsCard title={t('cardDataTitle')}>
      <SettingField title={t('fieldWhitelist')} labelFor="index-whitelist">
        <Input
          id="index-whitelist"
          value={draft.index_whitelist}
          onChange={(e) => patch('index_whitelist', e.target.value)}
          placeholder="logs-*,metrics-*"
          disabled={loading}
          className="font-mono text-xs"
        />
      </SettingField>

      <SettingField title={t('fieldMasking')} last>
        <ToggleGroup
          multiple={false}
          value={draft.masking_mode ? [draft.masking_mode] : []}
          onValueChange={(v) => patch('masking_mode', v[0] ?? '')}
          variant="outline"
          size="sm"
          aria-label={t('fieldMasking')}
        >
          {MASKING_MODES.map((mode) => (
            <ToggleGroupItem
              key={mode}
              value={mode}
              disabled={loading || (maskingInfo ? !maskingInfo.available_modes.includes(mode) : false)}
            >
              {t(MASKING_KEY[mode])}
            </ToggleGroupItem>
          ))}
        </ToggleGroup>
        {licenseBlocked && (
          <FieldDescription className="text-destructive">
            {t('maskingBlocked', {
              mode: draft.masking_mode,
              available: maskingInfo.available_modes.join(', '),
            })}
          </FieldDescription>
        )}
      </SettingField>
    </SettingsCard>
  )
}
