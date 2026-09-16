import { HugeiconsIcon } from '@hugeicons/react'
import { AlertCircleIcon } from '@hugeicons/core-free-icons'

import { useSettingsDraft } from '@/hooks/useSettingsDraft'
import { SettingsCard } from '@/components/settings/settings-card'
import { SaveBar } from '@/components/settings/save-bar'
import { SettingField } from '@/components/blocks/settings-3/components/setting-field'
import { Alert, AlertDescription } from '@/components/reui/alert'
import { FieldDescription } from '@/components/ui/field'
import { Input } from '@/components/ui/input'
import { Switch } from '@/components/ui/switch'
import { Textarea } from '@/components/ui/textarea'
import { ToggleGroup, ToggleGroupItem } from '@/components/ui/toggle-group'
import { useT } from '@/lib/i18n'
import { settingsCopy } from '@/locales/settings'

/*
 * 审计 + 多通道转发。
 *
 * 原来是系统设置页里的一张卡。搬到「对外通道」页的理由：它和飞书、邮件、webhook
 * 是同一件事 —— **有什么东西会离开这套系统，走哪条路**。留在系统设置里的时候，
 * 找它的人得先想到「转发算不算设置」。
 *
 * 它自带一份草稿（只管这六个键）和自己的保存浮条：`/api/settings` 写的是差量，
 * 没碰的键服务端原样留着，所以同一份设置由两个屏各管一段是安全的。
 */

const AUDIT_KEYS = [
  'audit.enabled',
  'audit.index',
  'audit.syslog_url',
  'audit.webhook_url',
  'audit.webhook_headers',
  'audit.tls_verify',
] as const

export function AuditCard() {
  const t = useT(settingsCopy)
  const { draft, patch, dirty, loading, saving, error, save, revert } =
    useSettingsDraft({ keys: AUDIT_KEYS })

  const enabled = draft['audit.enabled'].toLowerCase() === 'true'

  return (
    <div className="flex w-full min-w-0 flex-col gap-4">
      {error && (
        <Alert variant="destructive">
          <HugeiconsIcon icon={AlertCircleIcon} strokeWidth={2} className="size-4" />
          <AlertDescription>{error}</AlertDescription>
        </Alert>
      )}

      <SettingsCard title={t('auditCardTitle')}>
        <SettingField
          title={t('auditEnable')}
          labelFor="audit-enabled"
          contentClassName="@md/field-group:w-auto"
          last={!enabled}
        >
          <div className="flex @md/field-group:justify-end">
            <Switch
              id="audit-enabled"
              checked={enabled}
              onCheckedChange={(v) => patch('audit.enabled', v ? 'true' : 'false')}
              disabled={loading}
            />
          </div>
        </SettingField>

        {enabled && (
          <>
            <SettingField
              title={t('auditIndex')}
              labelFor="audit-index"
            >
              <Input
                id="audit-index"
                value={draft['audit.index']}
                onChange={(e) => patch('audit.index', e.target.value)}
                placeholder=".rst_copilot_audit"
                disabled={loading}
                className="font-mono text-xs"
              />
            </SettingField>

            <SettingField
              title="Syslog URL"
              hint={t('syslogDesc')}
              labelFor="audit-syslog"
            >
              <Input
                id="audit-syslog"
                value={draft['audit.syslog_url']}
                onChange={(e) => patch('audit.syslog_url', e.target.value)}
                placeholder="udp://syslog.local:514"
                disabled={loading}
                className="font-mono text-xs"
              />
            </SettingField>

            <SettingField
              title="Webhook URL"
              hint={t('webhookDesc')}
              labelFor="audit-webhook"
            >
              <Input
                id="audit-webhook"
                value={draft['audit.webhook_url']}
                onChange={(e) => patch('audit.webhook_url', e.target.value)}
                placeholder="https://soar.customer.local/ingest"
                disabled={loading}
                className="font-mono text-xs"
              />
            </SettingField>

            <SettingField
              title="Webhook headers"
              description="K1:V1;K2:V2"
              labelFor="audit-headers"
            >
              <Textarea
                id="audit-headers"
                value={draft['audit.webhook_headers']}
                onChange={(e) => patch('audit.webhook_headers', e.target.value)}
                placeholder="Authorization:Bearer xxx;X-Source:rst-copilot"
                disabled={loading}
                className="min-h-[60px] font-mono text-xs"
              />
              <FieldDescription>{t('keepCurrent')}</FieldDescription>
            </SettingField>

            <SettingField
              title={t('tlsVerify')}
              hint={t('tlsVerifyDesc')}
              last
            >
              <ToggleGroup
                multiple={false}
                value={[draft['audit.tls_verify'] || '__default__']}
                onValueChange={(v) => patch('audit.tls_verify', v[0] === '__default__' ? '' : (v[0] ?? ''))}
                variant="outline"
                size="sm"
                aria-label={t('tlsVerify')}
              >
                {/* 空串不能当 ToggleGroupItem 的 value（选中态判定会把它当成「没选」），
                    用哨兵值表示「跟服务端默认」。 */}
                <ToggleGroupItem value="__default__" disabled={loading}>{t('tlsDefault')}</ToggleGroupItem>
                <ToggleGroupItem value="true" disabled={loading}>{t('tlsOn')}</ToggleGroupItem>
                <ToggleGroupItem value="false" disabled={loading}>{t('tlsOff')}</ToggleGroupItem>
              </ToggleGroup>
            </SettingField>
          </>
        )}
      </SettingsCard>

      <SaveBar dirty={dirty} saving={saving} onSave={() => void save()} onRevert={revert} />
    </div>
  )
}
