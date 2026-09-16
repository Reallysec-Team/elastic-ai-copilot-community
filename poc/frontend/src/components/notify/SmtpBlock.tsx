import { useState } from 'react'
import { HugeiconsIcon } from '@hugeicons/react'
import { AlertCircleIcon, CheckmarkCircle02Icon, Loading03Icon } from '@hugeicons/core-free-icons'
import { toast } from 'sonner'

import { GatedButton } from '@/components/gated-button'
import { api, type ApiError, type NotifyConfig } from '@/lib/api'
import { SettingField } from '@/components/blocks/settings-3/components/setting-field'
import { Alert, AlertDescription } from '@/components/reui/alert'
import { FieldGroup } from '@/components/ui/field'
import { Input } from '@/components/ui/input'
import { ToggleGroup, ToggleGroupItem } from '@/components/ui/toggle-group'
import { useT, translate } from '@/lib/i18n'
import { commonCopy } from '@/locales/common'
import { notifyCopy } from '@/locales/notify'
import { apiErrorMessage } from '@/locales/errors'

/*
 * 发件服务器 —— 全局一份，不跟着目标走。客户改一次邮箱密码就要改 N 个目标，是
 * 每个做过这块的人都后悔过的设计。
 *
 * 密码沿用目标密钥那套 Fernet 加密存在 ES 里，读回来只有 `password_set: boolean`，
 * 界面永远拿不到明文；留空 = 不改。
 */

const SECURITY: Array<{ value: 'starttls' | 'ssl' | 'none'; label: string; port: number }> = [
  { value: 'starttls', label: 'STARTTLS', port: 587 },
  { value: 'ssl', label: 'SSL/TLS', port: 465 },
  { value: 'none', label: translate(notifyCopy, 'encNone'), port: 25 },
]

export function SmtpBlock({
  config,
  onSaved,
}: {
  config: NotifyConfig
  onSaved: (c: NotifyConfig) => void
}) {
  const t = useT(notifyCopy)
  const c = useT(commonCopy)
  const smtp = config.smtp ?? {}
  const [host, setHost] = useState(smtp.host ?? '')
  const [port, setPort] = useState(String(smtp.port ?? 587))
  const [security, setSecurity] = useState<'starttls' | 'ssl' | 'none'>(smtp.security ?? 'starttls')
  const [username, setUsername] = useState(smtp.username ?? '')
  const [password, setPassword] = useState('')
  const [fromAddr, setFromAddr] = useState(smtp.from_addr ?? '')
  const [fromName, setFromName] = useState(smtp.from_name ?? '')
  const [saving, setSaving] = useState(false)
  const [err, setErr] = useState<string | null>(null)

  const configured = !!smtp.host && !!smtp.from_addr

  function pickSecurity(v: 'starttls' | 'ssl' | 'none') {
    setSecurity(v)
    // 端口跟着加密方式走 —— 三种组合是有标准端口的，让人自己记 465 还是 587
    // 是没必要的一道题。已经改过端口的不动。
    const known = SECURITY.map((s) => String(s.port))
    if (known.includes(port)) setPort(String(SECURITY.find((s) => s.value === v)!.port))
  }

  async function save() {
    setErr(null)
    setSaving(true)
    try {
      const c = await api.notifySaveSmtp({
        host: host.trim(),
        port: Number(port) || 0,
        security,
        username: username.trim(),
        ...(password ? { password } : {}),
        from_addr: fromAddr.trim(),
        from_name: fromName.trim(),
      })
      onSaved(c)
      setPassword('')
      toast.success(t('smtpSaved'))
    } catch (e) {
      const ex = e as ApiError
      const detail = apiErrorMessage(ex.body, ex.message)
      setErr(detail || t('errSave'))
    } finally {
      setSaving(false)
    }
  }

  return (
    <div className="flex flex-col gap-2.5">
      {!configured && (
        <Alert variant="warning">
          <HugeiconsIcon icon={AlertCircleIcon} strokeWidth={2} className="size-4" />
          <AlertDescription>
            {t('smtpUnset')}
          </AlertDescription>
        </Alert>
      )}
      {err && (
        <Alert variant="destructive">
          <HugeiconsIcon icon={AlertCircleIcon} strokeWidth={2} className="size-4" />
          <AlertDescription>{err}</AlertDescription>
        </Alert>
      )}

      <FieldGroup className="gap-0">
        <SettingField title={t('smtpHost')} labelFor="smtp-host">
          <Input
            id="smtp-host"
            value={host}
            onChange={(e) => setHost(e.target.value)}
            placeholder="smtp.corp.example"
            className="font-mono text-xs"
          />
        </SettingField>

        <SettingField title={t('smtpEncryption')} hint={t('smtpEncryptionDesc')}>
          <ToggleGroup
            multiple={false}
            value={[security]}
            onValueChange={(v) => pickSecurity((v[0] as typeof security) ?? 'starttls')}
            variant="outline"
            size="sm"
            aria-label={t('smtpEncryption')}
          >
            {SECURITY.map((s) => (
              <ToggleGroupItem key={s.value} value={s.value}>
                {s.label}
              </ToggleGroupItem>
            ))}
          </ToggleGroup>
        </SettingField>

        <SettingField title={t('smtpPort')} labelFor="smtp-port">
          <Input
            id="smtp-port"
            value={port}
            onChange={(e) => setPort(e.target.value.replace(/\D/g, ''))}
            inputMode="numeric"
            className="font-mono text-xs"
          />
        </SettingField>

        <SettingField title={t('smtpUser')} hint={t('smtpUserDesc')} labelFor="smtp-user">
          <Input
            id="smtp-user"
            value={username}
            onChange={(e) => setUsername(e.target.value)}
            placeholder="copilot@corp.example"
            autoComplete="off"
          />
        </SettingField>

        <SettingField
          title={t('smtpPassword')}
          description={smtp.password_stale ? t('smtpPasswordStale') : smtp.password_set ? t('smtpPasswordSet') : t('smtpPasswordUnset')}
          labelFor="smtp-pass"
        >
          <Input
            id="smtp-pass"
            type="password"
            value={password}
            onChange={(e) => setPassword(e.target.value)}
            autoComplete="new-password"
          />
        </SettingField>

        <SettingField title={t('smtpFrom')} labelFor="smtp-from">
          <Input
            id="smtp-from"
            value={fromAddr}
            onChange={(e) => setFromAddr(e.target.value)}
            placeholder="copilot@corp.example"
            className="font-mono text-xs"
          />
        </SettingField>

        <SettingField title={t('smtpFromName')} labelFor="smtp-fromname" last>
          <Input
            id="smtp-fromname"
            value={fromName}
            onChange={(e) => setFromName(e.target.value)}
            placeholder="RST Elastic AI Copilot"
          />
        </SettingField>
      </FieldGroup>

      <div className="flex flex-row justify-end gap-3">
        <GatedButton gate="admin" className="rounded-full" size="sm" onClick={() => void save()} disabled={saving}>
          <HugeiconsIcon
            icon={saving ? Loading03Icon : CheckmarkCircle02Icon}
            strokeWidth={2}
            className={saving ? 'size-3.5 animate-spin' : 'size-3.5'}
          />
          {saving ? c('saving') : c('save')}
        </GatedButton>
      </div>

      <p className="text-xs text-pretty text-muted-foreground">
        {t('smtpFooter')}
      </p>
    </div>
  )
}
