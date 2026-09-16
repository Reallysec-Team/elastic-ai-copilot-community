// poc/frontend/src/components/ai/EmbeddingCard.tsx
import { useEffect, useState } from 'react'
import { HugeiconsIcon } from '@hugeicons/react'
import {
  AlertCircleIcon, CheckmarkCircle02Icon, Loading03Icon, PlugZapIcon,
} from '@hugeicons/core-free-icons'

import { GatedButton } from '@/components/gated-button'
import { api } from '@/lib/api'
import { cn } from '@/lib/utils'
import { SettingField } from '@/components/blocks/settings-3/components/setting-field'
import { Alert, AlertDescription } from '@/components/reui/alert'
import { Badge } from '@/components/reui/badge'
import { Frame, FrameFooter, FrameHeader, FramePanel, FrameTitle } from '@/components/reui/frame'
import { FieldGroup } from '@/components/ui/field'
import { Input } from '@/components/ui/input'
import { Switch } from '@/components/ui/switch'
import { useT } from '@/lib/i18n'
import { aiSettingsCopy, type AiSettingsKey } from '@/locales/aiSettings'
import { commonCopy } from '@/locales/common'
import { HintTip } from '@/components/hint-tip'

/*
 * 知识库向量模型。版式跟系统设置同一套：一列 `SettingField`（`@reui/settings-3`），
 * 左边说这项是什么，右边是控件；横幅和按钮放整卡宽的页脚。
 *
 * 原来的字段是「一个 mono 全大写小标题 + 一个裸 input」，维度那格还是只读的 ——
 * 读起来像四个一样的输入框，看不出哪个必填、哪个是回填的。
 */

interface Form {
  model: string
  base_url: string
  api_key: string      // empty = keep stored / reuse chat provider
  dims: number
  enabled: boolean
}

const STATUS: Record<string, { label: string; variant: 'success-light' | 'destructive-light' | 'secondary' }> = {
  enabled: { label: 'emEnabled', variant: 'success-light' },
  disabled: { label: 'emDisabled', variant: 'secondary' },
  misconfigured: { label: 'emMisconfigured', variant: 'destructive-light' },
}

export function EmbeddingCard() {
  const t = useT(aiSettingsCopy)
  const c = useT(commonCopy)
  const [form, setForm] = useState<Form | null>(null)
  const [status, setStatus] = useState<string>('disabled')
  const [keySet, setKeySet] = useState(false)
  const [keyLast4, setKeyLast4] = useState('')
  const [kbIndexDims, setKbIndexDims] = useState<number | null>(null)
  const [loading, setLoading] = useState(false)
  const [testing, setTesting] = useState(false)
  const [saving, setSaving] = useState(false)
  const [testOk, setTestOk] = useState(false)   // save gated on this
  const [error, setError] = useState<string | null>(null)
  const [notice, setNotice] = useState<string | null>(null)

  async function load() {
    setLoading(true)
    setError(null)
    try {
      const r = await api.embeddingConfig()
      setForm({ model: r.model, base_url: r.base_url, api_key: '', dims: r.dims, enabled: r.enabled })
      setStatus(r.status)
      setKeySet(r.api_key_set)
      setKeyLast4(r.api_key_last4)
      setKbIndexDims(r.kb_index_dims)
      setTestOk(false)
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e))
    } finally {
      setLoading(false)
    }
  }

  useEffect(() => {
    // eslint-disable-next-line react-hooks/set-state-in-effect -- initial load on mount
    load()
  }, [])

  function patch(partial: Partial<Form>) {
    if (!form) return
    setForm({ ...form, ...partial })
    setTestOk(false)   // any field edit invalidates the last successful test
    setNotice(null)
  }

  async function onTest() {
    if (!form) return
    setTesting(true)
    setError(null)
    setNotice(null)
    try {
      const r = await api.embeddingTest({ model: form.model.trim(), base_url: form.base_url.trim(), api_key: form.api_key })
      if (r.ok && r.dims) {
        setForm({ ...form, dims: r.dims })
        setTestOk(true)
        setNotice(t('emOkDims', { dims: r.dims }))
      } else {
        setTestOk(false)
        setError(r.error || t('emErrTest'))
      }
    } catch (e) {
      setTestOk(false)
      setError(e instanceof Error ? e.message : String(e))
    } finally {
      setTesting(false)
    }
  }

  async function onSave() {
    if (!form) return
    setSaving(true)
    setError(null)
    try {
      const r = await api.embeddingSave({
        model: form.model.trim(),
        base_url: form.base_url.trim(),
        api_key: form.api_key,
        dims: form.dims,
        enabled: form.enabled,
      })
      setNotice(t('emSavedDims', { dims: r.dims }))
      await load()
    } catch (e) {
      // 409 dimension conflict surfaces here as the backend detail string.
      setError(e instanceof Error ? e.message : String(e))
    } finally {
      setSaving(false)
    }
  }

  const st = STATUS[status] ?? { label: status, variant: 'secondary' as const }
  const dimsConflict = kbIndexDims != null && (form?.dims ?? 0) > 0 && kbIndexDims !== form!.dims

  return (
    <Frame dense className="w-full min-w-0">
      {/* `flex-wrap` 是承重的：标题列是唯一能伸缩的子项，不给 wrap 窄屏下会被压扁。 */}
      <FrameHeader className="flex-row flex-wrap items-center justify-between gap-3 pb-[calc(var(--frame-panel-header-py)+2px)]">
        <FrameTitle className="flex items-center gap-1.5 text-balance">
          {t('emTitle')}
          <HintTip text={t('emDesc')} />
        </FrameTitle>
        <div className="flex shrink-0 items-center gap-3 pt-0.5">
          <Badge size="sm" variant={st.variant}>{t(st.label as AiSettingsKey)}</Badge>
        </div>
      </FrameHeader>

      {form && (
        <FramePanel className="p-0">
          <FieldGroup className="gap-0">
            <SettingField
              title={t('emFieldModelId')}
              labelFor="embed-model"
            >
              <Input
                id="embed-model"
                value={form.model}
                onChange={(e) => patch({ model: e.target.value })}
                placeholder="doubao-embedding-large-text-240915"
                className="font-mono text-xs"
              />
            </SettingField>

            <SettingField
              title="Base URL"
              hint={t('emReuseChatEndpoint')}
              labelFor="embed-url"
            >
              <Input
                id="embed-url"
                value={form.base_url}
                onChange={(e) => patch({ base_url: e.target.value })}
                placeholder={t('emReuseChatEndpoint')}
                className="font-mono text-xs"
              />
            </SettingField>

            <SettingField
              title="API Key"
              description={keySet ? t('emKeyKeep') : t('emKeyReuse')}
              labelFor="embed-key"
            >
              <Input
                id="embed-key"
                type="password"
                value={form.api_key}
                onChange={(e) => patch({ api_key: e.target.value })}
                placeholder={keySet ? t('emKeyKeepWithTail', { last4: keyLast4 }) : t('emKeyReuse')}
                className="font-mono text-xs"
              />
            </SettingField>

            <SettingField
              title={t('emFieldDims')}
              description={t('emDimsDesc')}
              labelFor="embed-dims"
            >
              <Input
                id="embed-dims"
                value={form.dims || ''}
                readOnly
                placeholder={t('emDimsPlaceholder')}
                className="font-mono text-xs text-muted-foreground"
              />
            </SettingField>

            <SettingField
              title={t('emFieldEnable')}
              labelFor="embed-enabled"
              contentClassName="@md/field-group:w-auto"
              last
            >
              <div className="flex @md/field-group:justify-end">
                <Switch
                  id="embed-enabled"
                  checked={form.enabled}
                  onCheckedChange={(v) => patch({ enabled: v })}
                />
              </div>
            </SettingField>
          </FieldGroup>
        </FramePanel>
      )}

      <FrameFooter className="gap-2.5">
        {error && (
          <Alert variant="destructive">
            <HugeiconsIcon icon={AlertCircleIcon} strokeWidth={2} className="size-4" />
            <AlertDescription>{error}</AlertDescription>
          </Alert>
        )}

        {notice && !error && (
          <Alert variant="success">
            <HugeiconsIcon icon={CheckmarkCircle02Icon} strokeWidth={2} className="size-4" />
            <AlertDescription>{notice}</AlertDescription>
          </Alert>
        )}

        {dimsConflict && (
          <Alert variant="warning">
            <HugeiconsIcon icon={AlertCircleIcon} strokeWidth={2} className="size-4" />
            <AlertDescription>
              <p>
                {t('emDimsMismatch', { kbDims: kbIndexDims, dims: form?.dims ?? '' })}
              </p>
            </AlertDescription>
          </Alert>
        )}

        <div className="flex flex-wrap items-center justify-end gap-3">
          {!testOk && (
            <span className="text-xs text-muted-foreground">{t('emCannotSaveYet')}</span>
          )}
          <GatedButton
            gate="admin"
            variant="ghost"
            size="sm"
            onClick={() => void onTest()}
            disabled={testing || saving || loading || !form?.model.trim()}
          >
            <HugeiconsIcon
              icon={testing ? Loading03Icon : PlugZapIcon}
              strokeWidth={2}
              className={cn('size-3.5', testing && 'animate-spin')}
            />
            {t('emTestConnection')}
          </GatedButton>
          <GatedButton
            gate="admin"
            className="rounded-full"
            size="sm"
            onClick={() => void onSave()}
            disabled={!testOk || saving || loading}
          >
            <HugeiconsIcon
              icon={saving ? Loading03Icon : CheckmarkCircle02Icon}
              strokeWidth={2}
              className={cn('size-3.5', saving && 'animate-spin')}
            />
            {c('save')}
          </GatedButton>
        </div>
      </FrameFooter>
    </Frame>
  )
}
