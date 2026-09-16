import { useState } from 'react'
import { HugeiconsIcon } from '@hugeicons/react'
import {
  AlertCircleIcon, Database02Icon, Loading03Icon, PlugSocketIcon,
} from '@hugeicons/core-free-icons'

import { GatedButton } from '@/components/gated-button'
import { api } from '@/lib/api'
import { SettingField } from '@/components/blocks/settings-3/components/setting-field'
import { Alert, AlertDescription } from '@/components/reui/alert'
import { Badge } from '@/components/reui/badge'
import { IconTile } from '@/components/reui/icon-tile'
import { Input } from '@/components/ui/input'
import {
  Item, ItemActions, ItemContent, ItemDescription, ItemMedia, ItemTitle,
} from '@/components/ui/item'
import { Switch } from '@/components/ui/switch'
import { useT, translate } from '@/lib/i18n'
import { settingsCopy } from '@/locales/settings'

/*
 * ES 连接的表单本体 —— 设置页的卡和首次安装的弹窗共用这一份。
 *
 * 两个入口的外壳不同（一个是页面上的一张卡，一个是登录后弹出来的框），但字段、
 * 校验、探活状态机完全一样。抄两遍的下场是有一天只改一边。
 *
 * 键名用后端 /api/settings 的扁平写法（`es.url`…），这样两个调用方都能把 draft
 * 直接 POST 出去，中间不需要一层映射。
 */

export const ES_KEYS = ['es.url', 'es.user', 'es.password', 'es.verify_certs', 'es.ca_cert'] as const

export type EsKey = (typeof ES_KEYS)[number]
export type EsSettings = Record<EsKey, string>

export const EMPTY_ES: EsSettings = {
  'es.url': '',
  'es.user': '',
  'es.password': '',
  'es.verify_certs': '',
  'es.ca_cert': '',
}

/* `idle` 不等于「连不上」——它是「这套参数还没验证过」。两者在界面上长得完全
   不同，混成一个 boolean 会让新装的机器一打开就红一片。 */
export type EsTestState =
  | { phase: 'idle' }
  | { phase: 'testing' }
  | { phase: 'ok'; cluster_name?: string; version?: string; can_list_indices?: boolean }
  | { phase: 'failed'; error: string }

export function useEsProbe() {
  const [test, setTest] = useState<EsTestState>({ phase: 'idle' })

  async function probe(req: Parameters<typeof api.testEsConnection>[0]) {
    setTest({ phase: 'testing' })
    try {
      const r = await api.testEsConnection(req)
      setTest(r.ok ? { phase: 'ok', ...r } : { phase: 'failed', error: r.error ?? translate(settingsCopy, 'errConnect') })
    } catch (e) {
      // 探活本身失败（网关不可达 / 无管理员权限）跟「集群连不上」是两回事，
      // 但对操作者是同一句话：这套参数现在不能用。
      setTest({ phase: 'failed', error: e instanceof Error ? e.message : String(e) })
    }
  }

  /** 用当前 draft 探一次。 */
  function probeDraft(draft: EsSettings) {
    return probe({
      url: draft['es.url'],
      user: draft['es.user'],
      password: draft['es.password'],
      verify_certs: draft['es.verify_certs'].toLowerCase() === 'true',
      ca_cert: draft['es.ca_cert'],
    })
  }

  return { test, setTest, probe, probeDraft }
}

/*
 * 状态行的版式取自 `@reui/settings-16` 的 integration row：左边一个图标砖 + 名称，
 * 中间一枚状态 Badge，右边一个动作按钮。那个块是给「已接入的第三方应用列表」用的，
 * 这里只有一条连接，所以留下同样的行、去掉列表外壳。
 */
export function EsStatusRow({
  url,
  test,
  onTest,
  disabled,
}: {
  url: string
  test: EsTestState
  onTest: () => void
  disabled?: boolean
}) {
  const t = useT(settingsCopy)
  // 后端按 method 默认拒写，viewer 点了只会拿 403 —— 在按钮上就挡住，
  // 两个入口（设置页的卡、首装弹窗）共用这一行，各挡各的会漏一边。
  const status =
    test.phase === 'ok'
      ? { variant: 'success-light' as const, label: t('connOk') }
      : test.phase === 'failed'
        ? { variant: 'destructive-light' as const, label: t('connFail') }
        : test.phase === 'testing'
          ? { variant: 'secondary' as const, label: t('connTesting') }
          : { variant: 'warning-light' as const, label: t('connUnverified') }

  return (
    <Item className="items-center px-4 py-3">
      <ItemMedia className="translate-y-0! self-center!">
        <IconTile variant="soft" size="sm">
          <HugeiconsIcon icon={Database02Icon} strokeWidth={2} className="size-4" />
        </IconTile>
      </ItemMedia>
      <ItemContent className="min-w-0 gap-0">
        <ItemTitle className="w-full min-w-0 gap-2">
          <span className="truncate">
            {test.phase === 'ok' && test.cluster_name ? test.cluster_name : 'Elasticsearch'}
          </span>
          <Badge size="sm" variant={status.variant}>{status.label}</Badge>
        </ItemTitle>
        <ItemDescription className="line-clamp-1 font-mono text-xs">
          {url.trim() || t('noUrlYet')}
          {test.phase === 'ok' && test.version ? ` · v${test.version}` : ''}
        </ItemDescription>
      </ItemContent>
      <ItemActions className="ml-auto shrink-0 justify-end">
        <GatedButton
          gate="write"
          variant="outline"
          size="sm"
          onClick={onTest}
          disabled={disabled || test.phase === 'testing'}
        >
          <HugeiconsIcon
            icon={test.phase === 'testing' ? Loading03Icon : PlugSocketIcon}
            strokeWidth={2}
            className={test.phase === 'testing' ? 'size-3.5 animate-spin' : 'size-3.5'}
          />
          {test.phase === 'testing' ? t('testing') : t('testConnection')}
        </GatedButton>
      </ItemActions>
    </Item>
  )
}

/** 地址 / 账号 / 密码（+ https 才出现的 TLS 两行）。 */
export function EsFields({
  draft,
  patch,
  loading,
}: {
  draft: EsSettings
  patch: (k: EsKey, v: string) => void
  loading?: boolean
}) {
  const t = useT(settingsCopy)
  const verify = draft['es.verify_certs'].toLowerCase() === 'true'
  const isHttps = draft['es.url'].trim().toLowerCase().startsWith('https://')

  return (
    <>
      <SettingField title={t('fieldClusterUrl')} labelFor="es-url">
        <Input
          id="es-url"
          value={draft['es.url']}
          onChange={(e) => patch('es.url', e.target.value)}
          placeholder="http://localhost:9200"
          disabled={loading}
          className="font-mono text-xs"
        />
      </SettingField>

      <SettingField title={t('fieldUser')} labelFor="es-user">
        <Input
          id="es-user"
          value={draft['es.user']}
          onChange={(e) => patch('es.user', e.target.value)}
          /* 说明搬进占位符：这一行的说明是「不填会怎样」，写在输入框里读的人
             正好在看输入框，写在标签下面则是先读一遍再回到框上。 */
          placeholder={t('userPlaceholder')}
          disabled={loading}
          autoComplete="off"
        />
      </SettingField>

      <SettingField
        title={t('fieldPassword')}
        labelFor="es-password"
        last={!isHttps}
      >
        <Input
          id="es-password"
          type="password"
          value={draft['es.password']}
          onChange={(e) => patch('es.password', e.target.value)}
          disabled={loading}
          autoComplete="new-password"
        />
      </SettingField>

      {/* TLS 两行只在 https 地址下出现 —— http 集群上它们无处生效，摆在那里
          只会让人以为自己漏配了什么。 */}
      {isHttps && (
        <>
          <SettingField
            title={t('fieldVerifyCerts')}
            hint={t('verifyCertsDesc')}
            labelFor="es-verify"
            contentClassName="@md/field-group:w-auto"
          >
            <div className="flex @md/field-group:justify-end">
              <Switch
                id="es-verify"
                checked={verify}
                onCheckedChange={(v) => patch('es.verify_certs', v ? 'true' : 'false')}
                disabled={loading}
              />
            </div>
          </SettingField>

          <SettingField
            title={t('fieldCaPath')}
            hint={t('caPathDesc')}
            labelFor="es-ca"
            last
          >
            <Input
              id="es-ca"
              value={draft['es.ca_cert']}
              onChange={(e) => patch('es.ca_cert', e.target.value)}
              placeholder="/certs/ca.pem"
              disabled={loading}
              className="font-mono text-xs"
            />
          </SettingField>
        </>
      )}
    </>
  )
}

/* 调用方要先问「有没有话要说」再决定给不给容器 —— `<EsTestNotice/>` 这个元素
   本身永远是真值，直接塞进条件里会画出一条空面板。 */
export function hasEsNotice(test: EsTestState): boolean {
  return test.phase === 'failed' || (test.phase === 'ok' && test.can_list_indices === false)
}

/** 探活结果的解释 —— 失败原因，或「连上了但读不到索引」这种权限半通状态。 */
export function EsTestNotice({ test }: { test: EsTestState }) {
  const t = useT(settingsCopy)
  if (test.phase === 'failed') {
    return (
      <Alert variant="destructive">
        <HugeiconsIcon icon={AlertCircleIcon} strokeWidth={2} className="size-4" />
        <AlertDescription>{test.error}</AlertDescription>
      </Alert>
    )
  }
  /* 连得上但读不到索引，是权限问题不是网络问题 —— 这两种「半通」状态如果只显示
     一个绿勾，客户会在后面每一个空页面上重新排查一遍。 */
  if (test.phase === 'ok' && test.can_list_indices === false) {
    return (
      <Alert variant="warning">
        <HugeiconsIcon icon={AlertCircleIcon} strokeWidth={2} className="size-4" />
        <AlertDescription>
          {t('noListPerm')}
        </AlertDescription>
      </Alert>
    )
  }
  return null
}
