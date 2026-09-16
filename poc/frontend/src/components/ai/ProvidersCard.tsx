import { useEffect, useState } from 'react'
import { HugeiconsIcon } from '@hugeicons/react'
import {
  AiBrain01Icon, AlertCircleIcon, CheckmarkCircle02Icon, Delete02Icon,
  Loading03Icon, PlusIcon, RefreshCwIcon, Settings01Icon,
} from '@hugeicons/core-free-icons'
import { toast } from 'sonner'

import { GateNotice, GatedButton } from '@/components/gated-button'
import { api } from '@/lib/api'
import { cn } from '@/lib/utils'
import { Alert, AlertDescription } from '@/components/reui/alert'
import { Badge } from '@/components/reui/badge'
import { Frame, FrameFooter, FrameHeader, FramePanel, FrameTitle } from '@/components/reui/frame'
import { IconTile } from '@/components/reui/icon-tile'
import { Button } from '@/components/ui/button'
import { Field, FieldLabel } from '@/components/ui/field'
import { Input } from '@/components/ui/input'
import {
  Item, ItemActions, ItemContent, ItemDescription, ItemMedia, ItemTitle,
} from '@/components/ui/item'
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from '@/components/ui/select'
import { Switch } from '@/components/ui/switch'
import { useT, translate } from '@/lib/i18n'
import { aiSettingsCopy, type AiSettingsKey } from '@/locales/aiSettings'
import { HintTip } from '@/components/hint-tip'

/*
 * 模型路由 —— 一列 provider，按顺序故障转移。
 *
 * 版式按 `@reui/settings-8`（那种「一行一个端点 + 健康状态 + 开关」的设置列表）：
 * 每个 provider 收成一行 `Item`，行上只放身份（id）、状态和开关，展开才是编辑表单。
 * 原来七个字段是七个常驻的裸 `<input>`，四个 provider 就是二十八个输入框铺满一屏，
 * 谁在跑、谁挂了要从一个 2px 的色点上读。
 *
 * 顶上那排指标卡搬到了 `AiOpsOverview`（版式按 tempo 的 features/ai-ops），
 * 这张卡只管「一列可编辑的 provider」，也就是 tempo 那边的 Routing Rules。
 */

interface DraftProvider {
  id: string
  model: string
  kind: string  // 'openai' | 'azure'
  api_version: string  // azure only
  base_url: string
  enabled: boolean
  tags: string
  timeout_s: number
  reasoning: string  // auto | off | low | high
  api_key: string  // empty = keep existing
  api_key_last4?: string
  consec_failures?: number
  last_ok_at?: number | string | null
  last_error?: string | null
  // Marks new rows that need a real api_key on save.
  is_new?: boolean
}

function hasKey(d: DraftProvider): boolean {
  return d.api_key.trim() !== '' || !!d.api_key_last4
}

function isFailing(d: DraftProvider): boolean {
  return (d.consec_failures ?? 0) >= 1
}

export function ProvidersCard() {
  const t = useT(aiSettingsCopy)
  const [drafts, setDrafts] = useState<DraftProvider[] | null>(null)
  const [loading, setLoading] = useState(false)
  const [saving, setSaving] = useState(false)
  const [error, setError] = useState<string | null>(null)
  // 展开的是哪几行。新加的行默认展开 —— 它一个字段都没填。
  const [openRows, setOpenRows] = useState<Set<number>>(new Set())

  async function load() {
    setLoading(true)
    setError(null)
    try {
      const r = await api.llmProviders()
      setDrafts(
        r.providers.map((p) => ({
          id: p.id,
          model: p.model,
          kind: p.kind || 'openai',
          api_version: p.api_version || '',
          base_url: p.base_url,
          enabled: p.enabled,
          tags: (p.tags || []).join(','),
          timeout_s: p.timeout_s ?? 30,
          reasoning: p.reasoning || 'auto',
          api_key: '',
          api_key_last4: p.api_key_last4,
          consec_failures: p.consec_failures,
          last_ok_at: p.last_ok_at,
          last_error: p.last_error,
        })),
      )
      setOpenRows(new Set())
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e))
    } finally {
      setLoading(false)
    }
  }

  async function reload() {
    setLoading(true)
    setError(null)
    try {
      await api.llmReload()
      await load()
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e))
    } finally {
      setLoading(false)
    }
  }

  async function onSave() {
    if (!drafts) return
    setSaving(true)
    setError(null)
    try {
      const payload = drafts.map((d) => ({
        id: d.id.trim(),
        kind: d.kind || 'openai',
        // Only send api_version for azure; keep openai entries clean.
        ...(d.kind === 'azure' ? { api_version: d.api_version.trim() } : {}),
        base_url: d.base_url.trim(),
        api_key: d.api_key,  // empty preserved by backend if existing
        model: d.model.trim(),
        enabled: d.enabled,
        tags: d.tags.split(',').map((t) => t.trim()).filter(Boolean),
        timeout_s: Number(d.timeout_s) || 30,
        reasoning: d.reasoning || 'auto',
      }))
      await api.llmProvidersSave({ providers: payload })
      toast.success(t('prSaved'))
      await load()
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e))
    } finally {
      setSaving(false)
    }
  }

  function patch(idx: number, partial: Partial<DraftProvider>) {
    setDrafts((prev) => (prev ? prev.map((d, i) => (i === idx ? { ...d, ...partial } : d)) : prev))
  }

  function addProvider() {
    const next: DraftProvider = {
      id: '',
      model: '',
      kind: 'openai',
      api_version: '',
      base_url: '',
      enabled: true,
      tags: '',
      timeout_s: 30,
      reasoning: 'auto',
      api_key: '',
      is_new: true,
    }
    const list = [...(drafts ?? []), next]
    setDrafts(list)
    setOpenRows((prev) => new Set(prev).add(list.length - 1))
  }

  function removeProvider(idx: number) {
    if (!drafts) return
    if (!window.confirm(t('prConfirmRemove'))) return
    setDrafts(drafts.filter((_, i) => i !== idx))
    setOpenRows(new Set())
  }

  function toggleRow(idx: number) {
    setOpenRows((prev) => {
      const next = new Set(prev)
      if (next.has(idx)) next.delete(idx)
      else next.add(idx)
      return next
    })
  }

  useEffect(() => {
    // eslint-disable-next-line react-hooks/set-state-in-effect -- initial load on mount
    load()
  }, [])

  return (
    <>
      <Frame dense className="w-full min-w-0">
        {/* `flex-wrap` 是承重的：标题列是唯一能伸缩的子项，不给 wrap 窄屏下会被压扁。 */}
        <FrameHeader className="flex-row flex-wrap items-center justify-between gap-3 pb-[calc(var(--frame-panel-header-py)+2px)]">
          <FrameTitle className="flex items-center gap-1.5 text-balance">
            {t('prTitle')}
            <HintTip text={t('prDesc')} />
          </FrameTitle>
          <div className="flex shrink-0 items-center gap-3 pt-0.5">
            <GatedButton
              gate="admin"
              variant="ghost"
              size="sm"
              onClick={() => void reload()}
              disabled={loading || saving}
            >
              <HugeiconsIcon
                icon={RefreshCwIcon}
                strokeWidth={2}
                className={cn('size-3.5', loading && 'animate-spin')}
              />
              {t('prReload')}
            </GatedButton>
          </div>
        </FrameHeader>

        <FramePanel className="p-0">
          {/* 下面每一行都还能改（草稿是本地状态），但保存要管理员 —— 不在这儿
              说一句，非管理员会改完一圈才发现存不了。 */}
          <GateNotice gate="admin" className="px-4 pt-3" />
          {error && (
            <div className="p-4">
              <Alert variant="destructive">
                <HugeiconsIcon icon={AlertCircleIcon} strokeWidth={2} className="size-4" />
                <AlertDescription>{error}</AlertDescription>
              </Alert>
            </div>
          )}

          {drafts && drafts.length === 0 && (
            <div className="p-4">
              <Alert variant="warning">
                <HugeiconsIcon icon={AlertCircleIcon} strokeWidth={2} className="size-4" />
                <AlertDescription>
                  <p>
                    {t('prEmpty')}
                  </p>
                </AlertDescription>
              </Alert>
            </div>
          )}

          {drafts?.map((d, i) => (
            <ProviderRow
              key={i}
              draft={d}
              open={openRows.has(i)}
              onToggleOpen={() => toggleRow(i)}
              onPatch={(partial) => patch(i, partial)}
              onRemove={() => removeProvider(i)}
            />
          ))}
        </FramePanel>

        <FrameFooter className="flex-row flex-wrap items-center justify-between gap-3">
          <GatedButton gate="admin" variant="ghost" size="sm" onClick={addProvider} disabled={saving}>
            <HugeiconsIcon icon={PlusIcon} strokeWidth={2} className="size-3.5" />
            {t('prAdd')}
          </GatedButton>
          <GatedButton gate="admin" className="rounded-full" size="sm" onClick={() => void onSave()} disabled={saving || !drafts}>
            <HugeiconsIcon
              icon={saving ? Loading03Icon : CheckmarkCircle02Icon}
              strokeWidth={2}
              className={cn('size-3.5', saving && 'animate-spin')}
            />
            {saving ? t('prSaving') : t('prSaveReload')}
          </GatedButton>
        </FrameFooter>
      </Frame>
    </>
  )
}

/* ---------------- 一行一个 provider ---------------- */

function statusBadge(d: DraftProvider) {
  const tr = (k: AiSettingsKey, v?: Record<string, string | number>) =>
    translate(aiSettingsCopy, k, v)
  if (d.is_new) return { variant: 'primary-light' as const, label: tr('prUnsaved') }
  if (!d.enabled) return { variant: 'secondary' as const, label: tr('prDisabled') }
  if (!hasKey(d)) return { variant: 'warning-light' as const, label: tr('prNoKey') }
  if (isFailing(d))
    return {
      variant: 'destructive-light' as const,
      label: tr('prFailing', { n: d.consec_failures ?? 0 }),
    }
  return { variant: 'success-light' as const, label: tr('prOk') }
}

function ProviderRow({
  draft,
  open,
  onToggleOpen,
  onPatch,
  onRemove,
}: {
  draft: DraftProvider
  open: boolean
  onToggleOpen: () => void
  onPatch: (partial: Partial<DraftProvider>) => void
  onRemove: () => void
}) {
  const t = useT(aiSettingsCopy)
  const status = statusBadge(draft)

  // 行根自带 `@container`：行内的响应式按这张卡的宽度算，不按窗口。
  return (
    <div className="@container border-b border-border last:border-b-0">
      <Item variant="outline" className="border-0">
        <ItemMedia variant="icon" className="translate-y-0! self-center!">
          <IconTile variant="soft" size="default">
            <HugeiconsIcon icon={AiBrain01Icon} strokeWidth={2} aria-hidden="true" />
          </IconTile>
        </ItemMedia>

        <ItemContent className="min-w-0 gap-1">
          <ItemTitle className="min-w-0 gap-2">
            <span className="min-w-0 truncate font-mono">
              {draft.id || <span className="text-muted-foreground">{t('prUnnamed')}</span>}
            </span>
            <Badge size="sm" variant={status.variant}>{status.label}</Badge>
          </ItemTitle>
          <ItemDescription className="min-w-0 truncate font-mono text-xs">
            {draft.model || t('prNoModel')} · {draft.base_url || t('prNoBaseUrl')}
          </ItemDescription>
        </ItemContent>

        <ItemActions className="gap-1 self-start @md:self-center">
          <Switch
            checked={draft.enabled}
            onCheckedChange={(v) => onPatch({ enabled: v })}
            aria-label={t('prEnableAria', { name: draft.id || t('prThisProvider') })}
          />
          <Button
            variant="ghost"
            size="icon-sm"
            aria-label={open ? t('prCollapse') : t('prExpand')}
            aria-expanded={open}
            onClick={onToggleOpen}
          >
            <HugeiconsIcon icon={Settings01Icon} strokeWidth={2} className="size-3.5" />
          </Button>
          <Button
            variant="ghost"
            size="icon-sm"
            className="text-muted-foreground hover:text-destructive"
            title={t('prRemove')}
            aria-label={t('prRemoveAria', { name: draft.id || t('prThisProvider') })}
            onClick={onRemove}
          >
            <HugeiconsIcon icon={Delete02Icon} strokeWidth={2} className="size-3.5" />
          </Button>
        </ItemActions>
      </Item>

      {isFailing(draft) && draft.last_error && !open && (
        <p className="truncate px-4 pb-3 font-mono text-xs text-destructive">
          {draft.last_error}
        </p>
      )}

      {open && <ProviderEditor draft={draft} onPatch={onPatch} />}
    </div>
  )
}

function ProviderEditor({
  draft,
  onPatch,
}: {
  draft: DraftProvider
  onPatch: (partial: Partial<DraftProvider>) => void
}) {
  const t = useT(aiSettingsCopy)
  const azure = draft.kind === 'azure'
  const REASONING_LABEL: Record<string, string> = {
    auto: t('prReasoningAuto'), off: t('prReasoningOff'), low: t('prReasoningLow'), high: t('prReasoningHigh'),
  }
  return (
    <div className="grid gap-4 bg-muted/30 px-4 pb-4 pt-1 @md:grid-cols-2">
      <Field>
        <FieldLabel htmlFor={`kind-${draft.id}`}>{t('prFieldKind')}</FieldLabel>
        <Select value={draft.kind} onValueChange={(v) => onPatch({ kind: v ?? 'openai' })}>
          <SelectTrigger id={`kind-${draft.id}`} aria-label={t('prKindAria')}>
            <SelectValue>{(v) => (v === 'azure' ? 'azure' : t('prOpenaiCompatible'))}</SelectValue>
          </SelectTrigger>
          <SelectContent>
            <SelectItem value="openai">{t('prOpenaiCompatible')}</SelectItem>
            <SelectItem value="azure">azure</SelectItem>
          </SelectContent>
        </Select>
      </Field>

      <Field>
        <FieldLabel htmlFor={`id-${draft.id}`}>Provider ID</FieldLabel>
        <Input
          id={`id-${draft.id}`}
          value={draft.id}
          onChange={(e) => onPatch({ id: e.target.value })}
          placeholder="ark-primary"
          className="font-mono text-xs"
        />
      </Field>

      {azure && (
        <Field>
          <FieldLabel htmlFor={`ver-${draft.id}`}>{t('prFieldApiVersion')}</FieldLabel>
          <Input
            id={`ver-${draft.id}`}
            value={draft.api_version}
            onChange={(e) => onPatch({ api_version: e.target.value })}
            placeholder="2024-06-01"
            className="font-mono text-xs"
          />
        </Field>
      )}

      <Field className="@md:col-span-2">
        <FieldLabel htmlFor={`url-${draft.id}`}>Base URL</FieldLabel>
        <Input
          id={`url-${draft.id}`}
          value={draft.base_url}
          onChange={(e) => onPatch({ base_url: e.target.value })}
          placeholder={
            azure
              ? 'https://<资源名>.openai.azure.com'
              : 'https://ark.cn-beijing.volces.com/api/v3'
          }
          className="font-mono text-xs"
        />
      </Field>

      <Field className="@md:col-span-2">
        <FieldLabel htmlFor={`model-${draft.id}`}>
          {azure ? t('prFieldDeployment') : t('prFieldModel')}
        </FieldLabel>
        <Input
          id={`model-${draft.id}`}
          value={draft.model}
          onChange={(e) => onPatch({ model: e.target.value })}
          placeholder={azure ? t('prDeploymentPlaceholder') : t('prModelPlaceholder')}
          className="font-mono text-xs"
        />
      </Field>

      <Field className="@md:col-span-2">
        <FieldLabel htmlFor={`key-${draft.id}`}>API Key</FieldLabel>
        <Input
          id={`key-${draft.id}`}
          type="password"
          value={draft.api_key}
          onChange={(e) => onPatch({ api_key: e.target.value })}
          placeholder={
            draft.is_new
              ? t('prKeyPasteNew')
              : draft.api_key_last4
                ? t('prKeyKeep', { last4: draft.api_key_last4 })
                : t('prKeyRequired')
          }
          className="font-mono text-xs"
        />
      </Field>

      <Field>
        <FieldLabel htmlFor={`tags-${draft.id}`}>{t('prFieldTags')}</FieldLabel>
        <Input
          id={`tags-${draft.id}`}
          value={draft.tags}
          onChange={(e) => onPatch({ tags: e.target.value })}
          placeholder={t('prTagsPlaceholder')}
          className="font-mono text-xs"
        />
      </Field>

      <Field>
        <FieldLabel htmlFor={`timeout-${draft.id}`}>{t('prFieldTimeout')}</FieldLabel>
        <Input
          id={`timeout-${draft.id}`}
          type="number"
          min={1}
          max={300}
          value={draft.timeout_s}
          onChange={(e) => onPatch({ timeout_s: Number(e.target.value) || 30 })}
          className="font-mono text-xs"
        />
      </Field>

      <Field>
        <FieldLabel htmlFor={`reasoning-${draft.id}`} className="inline-flex items-center gap-1">
          {t('prFieldReasoning')}
          <HintTip text={t('prReasoningHint')} />
        </FieldLabel>
        <Select value={draft.reasoning} onValueChange={(v) => onPatch({ reasoning: v ?? 'auto' })}>
          <SelectTrigger id={`reasoning-${draft.id}`} aria-label={t('prFieldReasoning')}>
            <SelectValue>{(v) => REASONING_LABEL[String(v)] ?? t('prReasoningAuto')}</SelectValue>
          </SelectTrigger>
          <SelectContent>
            <SelectItem value="auto">{t('prReasoningAuto')}</SelectItem>
            <SelectItem value="off">{t('prReasoningOff')}</SelectItem>
            <SelectItem value="low">{t('prReasoningLow')}</SelectItem>
            <SelectItem value="high">{t('prReasoningHigh')}</SelectItem>
          </SelectContent>
        </Select>
      </Field>

      {isFailing(draft) && draft.last_error && (
        <div className="@md:col-span-2">
          <Alert variant="destructive">
            <HugeiconsIcon icon={AlertCircleIcon} strokeWidth={2} className="size-4" />
            <AlertDescription>
              <p>{t('prLastError', { err: draft.last_error })}</p>
            </AlertDescription>
          </Alert>
        </div>
      )}
    </div>
  )
}
