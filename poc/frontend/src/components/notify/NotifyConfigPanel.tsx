import { useEffect, useState } from 'react'
import { HugeiconsIcon } from '@hugeicons/react'
import {
  AlertCircleIcon, BubbleChatIcon, Cancel01Icon, CheckIcon, Comment01Icon, Delete02Icon,
  Loading03Icon, Mail01Icon, MicrosoftIcon, MoreVerticalIcon, PencilIcon, PlusIcon,
  RefreshCwIcon, SendIcon, SlackIcon, WechatIcon,
} from '@hugeicons/core-free-icons'
import type { IconSvgElement } from '@hugeicons/react'
import { GatedButton, useGate } from '@/components/gated-button'
import { api, type ApiError, type NotifyChannel, type NotifyConfig, type NotifyDelivery, type NotifyTarget } from '@/lib/api'
import { Alert, AlertDescription } from '@/components/reui/alert'
import { Badge } from '@/components/reui/badge'
import { IconTile } from '@/components/reui/icon-tile'
import {
  AlertDialog, AlertDialogAction, AlertDialogCancel, AlertDialogContent, AlertDialogDescription,
  AlertDialogFooter, AlertDialogHeader, AlertDialogTitle,
} from '@/components/ui/alert-dialog'
import {
  DropdownMenu, DropdownMenuContent, DropdownMenuGroup, DropdownMenuItem,
  DropdownMenuSeparator, DropdownMenuTrigger,
} from '@/components/ui/dropdown-menu'
import { Item, ItemActions, ItemContent, ItemDescription, ItemMedia, ItemTitle } from '@/components/ui/item'
import { Button } from '@/components/ui/button'
import { Checkbox } from '@/components/ui/checkbox'
import { Dialog, DialogContent, DialogFooter, DialogHeader, DialogTitle } from '@/components/ui/dialog'
import { Input } from '@/components/ui/input'
import { Label } from '@/components/ui/label'
import { Pill } from '@/components/ui/Pill'
import { Textarea } from '@/components/ui/textarea'
import { ToggleGroup, ToggleGroupItem } from '@/components/ui/toggle-group'
import {
  SelectContent, SelectItem, Select as SelectRoot, SelectTrigger, SelectValue,
} from '@/components/ui/select'
import { cn } from '@/lib/utils'
import { useT, translate } from '@/lib/i18n'
import { severityLabel } from '@/lib/severity'
import { commonCopy } from '@/locales/common'
import { notifyCopy, type NotifyKey } from '@/locales/notify'
import { apiErrorMessage } from '@/locales/errors'

/*
 * 报告与告警的对外投递 —— 排期 + 目标（飞书 / 邮件）+ 投递记录。三个块由
 * `routes/NotifyPage` 组装（曾经是运营报告页的一节，后来是系统设置页尾的一张卡）。
 *
 * 写操作走 api 客户端的 admin 通道，需要时会要 RST_ADMIN_TOKEN。密钥只写不读：
 * 界面永远拿不到明文，只有 secret_set / webhook_set 为真时显示「已设置」。webhook
 * URL 和签名密钥同档：企业微信 / Slack / Teams 的鉴权就是 URL 里那个 key，所以
 * 它也不出接口，列表上只显示主机名（后端给的 webhook_host）。
 */

const PERIODS: Array<{ key: string; label: NotifyKey }> = [
  { key: 'daily', label: 'periodDaily' },
  { key: 'weekly', label: 'periodWeekly' },
  { key: 'monthly', label: 'periodMonthly' },
]

const SEVERITIES = ['info', 'low', 'medium', 'high', 'critical'] as const

const HOURS = Array.from({ length: 24 }, (_, i) => i)

function periodLabel(k: string): string {
  const p = PERIODS.find((x) => x.key === k)
  return p ? translate(notifyCopy, p.label) : k
}

/* 渠道的中文名与形态。`signed` 决定要不要显示「签名密钥」那一行：企业微信没有
   签名，它的鉴权就是 webhook URL 里那个 key —— 摆一个填不了的框只会让人以为
   自己漏配了什么。后端 channels.supports_signature 是同一件事的另一半。 */
const CHANNELS: Array<{
  value: NotifyChannel
  label: string
  signed: boolean
  placeholder: string
}> = [
  { value: 'feishu', label: 'chFeishu', signed: true,
    placeholder: 'https://open.feishu.cn/open-apis/bot/v2/hook/…' },
  { value: 'dingtalk', label: 'chDingtalk', signed: true,
    placeholder: 'https://oapi.dingtalk.com/robot/send?access_token=…' },
  { value: 'wecom', label: 'chWecom', signed: false,
    placeholder: 'https://qyapi.weixin.qq.com/cgi-bin/webhook/send?key=…' },
  { value: 'teams', label: 'Teams' as const, signed: false,
    placeholder: 'https://…logic.azure.com/workflows/… 或 …webhook.office.com/…' },
  { value: 'slack', label: 'Slack' as const, signed: false,
    placeholder: 'https://hooks.slack.com/services/T…/B…/…' },
  { value: 'email', label: 'chEmail', signed: false, placeholder: '' },
]

/* 渠道名里只有三个需要翻（飞书 / 钉钉 / 企业微信 / 邮件），Teams 和 Slack 是
   产品名本身。存的是「文案键或原样字符串」，`channelLabel` 分两种取。 */
const CHANNEL_KEY: Record<NotifyChannel, string> = {
  feishu: 'chFeishu', dingtalk: 'chDingtalk', wecom: 'chWecom',
  teams: 'Teams', slack: 'Slack', email: 'chEmail',
}

function channelLabel(kind: NotifyChannel | string): string {
  const k = CHANNEL_KEY[kind as NotifyChannel] ?? kind
  return k.startsWith('ch') ? translate(notifyCopy, k as NotifyKey) : k
}

function channelMeta(kind: NotifyChannel) {
  return CHANNELS.find((c) => c.value === kind) ?? CHANNELS[0]
}

/* 行首的渠道图标。hugeicons 免费包里只有 Slack / 微信 / 微软三个品牌图，飞书和
   钉钉没有，用两个不同的聊天气泡区分——同一组里反正只有一种渠道。 */
const CHANNEL_ICON: Record<NotifyChannel, IconSvgElement> = {
  feishu: BubbleChatIcon, dingtalk: Comment01Icon, wecom: WechatIcon,
  teams: MicrosoftIcon, slack: SlackIcon, email: Mail01Icon,
}

/*
 * 「报告投递（飞书）」这块原来是系统设置页尾的一张卡。渠道多起来之后它自己成了
 * 一屏（目标、记录、发件服务器），搬到了独立页面 `routes/NotifyPage`；这里只留
 * 三个可组合的块，页面负责加载配置和刷新。
 */
export function useNotifyConfig() {
  const [config, setConfig] = useState<NotifyConfig | null>(null)
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)

  async function load() {
    setLoading(true)
    setError(null)
    try {
      setConfig(await api.notifyConfig())
    } catch (e) {
      setError((e as ApiError).message || translate(notifyCopy, 'errLoadConfig'))
    } finally {
      setLoading(false)
    }
  }

  useEffect(() => {
    void load()
  }, [])

  return { config, setConfig, loading, error }
}

/* ----- Schedule ----- */

export function ScheduleBlock({ config, onSaved }: { config: NotifyConfig; onSaved: (c: NotifyConfig) => void }) {
  const t = useT(notifyCopy)
  const [periods, setPeriods] = useState<string[]>(config.schedule.periods)
  const [hour, setHour] = useState<number>(config.schedule.hour)
  const [tz, setTz] = useState<string>(config.schedule.tz || 'Asia/Shanghai')
  const [threshold, setThreshold] = useState<string>(config.alert_severity_threshold)
  const [saving, setSaving] = useState(false)
  const [err, setErr] = useState<string | null>(null)
  const [saved, setSaved] = useState(false)

  function togglePeriod(k: string) {
    setPeriods((ps) => (ps.includes(k) ? ps.filter((p) => p !== k) : [...ps, k]))
  }

  async function save() {
    setErr(null)
    setSaving(true)
    try {
      const c = await api.notifySaveSchedule({ periods, hour, tz: tz.trim(), alert_severity_threshold: threshold })
      onSaved(c)
      setSaved(true)
      setTimeout(() => setSaved(false), 1500)
    } catch (e) {
      setErr((e as ApiError).message || t('errSave'))
    } finally {
      setSaving(false)
    }
  }

  return (
    <div className="flex flex-col gap-2.5">
      <div className="flex items-baseline justify-between">
        <Label className="text-xs text-muted-foreground">{t('schedTitle')}</Label>
      </div>
      <p className="text-13 leading-[1.6] text-muted-foreground">
        {t('schedDesc')}
      </p>

      <div className="space-y-1.5">
        <Label className="font-mono text-xs text-muted-foreground">{t('fieldPeriods')}</Label>
        <div className="flex flex-wrap gap-4">
          {PERIODS.map((p) => (
            <label key={p.key} className="flex items-center gap-2 text-14 text-foreground">
              <Checkbox checked={periods.includes(p.key)} onCheckedChange={() => togglePeriod(p.key)} />
              {t(p.label)}
            </label>
          ))}
        </div>
      </div>

      <div className="grid grid-cols-1 gap-3 @2xl:grid-cols-3">
        <label className="block space-y-1.5">
          <Label className="font-mono text-xs text-muted-foreground">{t('fieldHour')}</Label>
          <Select value={String(hour)} onChange={(v) => setHour(Number(v))} options={HOURS.map(String)} />
        </label>
        <label className="block space-y-1.5">
          <Label className="font-mono text-xs text-muted-foreground">{t('fieldTimezone')}</Label>
          <Input value={tz} onChange={(e) => setTz(e.target.value)} placeholder="Asia/Shanghai" className="font-mono text-12" />
        </label>
        <label className="block space-y-1.5">
          <Label className="font-mono text-xs text-muted-foreground">{t('fieldThreshold')}</Label>
          <Select
            value={threshold}
            onChange={setThreshold}
            options={SEVERITIES}
            render={(o) => `${severityLabel(o)} (${o})`}
          />
        </label>
      </div>

      {err && (
        <Alert variant="destructive">
          <HugeiconsIcon icon={AlertCircleIcon} strokeWidth={2} className="size-4" />
          <AlertDescription>{err}</AlertDescription>
        </Alert>
      )}

      <div className="flex justify-end">
        <GatedButton gate="admin" variant="default" className="rounded-full" size="sm" onClick={save} disabled={saving}>
          {saved ? <HugeiconsIcon icon={CheckIcon} strokeWidth={2} className="size-3.5" /> : null}
          {saving ? t('savingDots') : saved ? t('saved') : t('saveSchedule')}
        </GatedButton>
      </div>
    </div>
  )
}

/* ----- Targets ----- */

export function TargetsBlock({ config, onChanged }: { config: NotifyConfig; onChanged: (c: NotifyConfig) => void }) {
  const t = useT(notifyCopy)
  const c = useT(commonCopy)
  const [editing, setEditing] = useState<{ target: NotifyTarget | null } | null>(null)
  const [confirmDelete, setConfirmDelete] = useState<string | null>(null)
  const [testResult, setTestResult] = useState<Record<string, { ok: boolean; error?: string } | 'pending'>>({})
  const [err, setErr] = useState<string | null>(null)

  // 先关弹窗再发请求（先例 UsersPage）：失败的 Alert 画在列表上方，不会被
  // 模态挡住；`deleting` 置空也挡住了双击发两次。
  async function handleDelete(id: string) {
    setConfirmDelete(null)
    setErr(null)
    try {
      onChanged(await api.notifyDeleteTarget(id))
    } catch (e) {
      setErr((e as ApiError).message || t('errDelete'))
    }
  }

  async function handleTest(id: string) {
    setTestResult((m) => ({ ...m, [id]: 'pending' }))
    try {
      const r = await api.notifyTestTarget(id)
      setTestResult((m) => ({ ...m, [id]: r }))
    } catch (e) {
      setTestResult((m) => ({ ...m, [id]: { ok: false, error: (e as ApiError).message || t('errTest') } }))
    }
  }

  const gate = useGate('admin')
  const deleting = config.targets.find((r) => r.id === confirmDelete) ?? null
  // 按渠道分组，组的顺序按 CHANNELS（飞书 / 钉钉 / 企微 / Teams / Slack / 邮件），空组不画。
  const groups = CHANNELS
    .map((ch) => ({ ch, rows: config.targets.filter((r) => (r.channel ?? 'feishu') === ch.value) }))
    .filter((g) => g.rows.length > 0)

  return (
    <div className="flex flex-col gap-2.5">
      <div className="flex items-center justify-between">
        <Label className="text-xs text-muted-foreground">{t('targetsLabel')}</Label>
        <GatedButton
          gate="admin"
          variant="default"
          className="rounded-full"
          size="sm"
          onClick={() => setEditing({ target: null })}
        >
          <HugeiconsIcon icon={PlusIcon} strokeWidth={2} className="size-4" /> {t('addTarget')}
        </GatedButton>
      </div>

      {err && (
        <Alert variant="destructive">
          <HugeiconsIcon icon={AlertCircleIcon} strokeWidth={2} className="size-4" />
          <AlertDescription>{err}</AlertDescription>
        </Alert>
      )}

      {config.targets.length === 0 ? (
        <p className="py-3 text-13 text-muted-foreground">{t('noTargets')}</p>
      ) : (
        /* 版式照 `@reui/settings-4`（分组集成行）：一组一个渠道，组头「渠道名 +
           数量」，组内每行 logo 格 + 名称 + 去向 + 状态徽标 + 行尾「…」菜单。
           没照搬的：模板的品牌 SVG 换成 hugeicons（仓库只用这一套图标）；模板每行
           一个 outline 徽标加圆点，这里按状态分色（密钥失效红、已设置绿、停用灰）
           ——secret_stale 是重装网关后最常见的坏状态，得一眼看见；模板的行操作
           是假的，这里接测试发送 / 编辑 / 删除，删除走 AlertDialog（先例 UsersPage）
           而不是原来那个点两次的按钮。 */
        <div className="flex flex-col gap-4">
          {groups.map(({ ch, rows }) => (
            <div key={ch.value}>
              <div className="flex items-baseline gap-2">
                <h3 className="text-sm font-semibold">{channelLabel(ch.value)}</h3>
                <span className="text-xs text-muted-foreground">{t('groupCount', { n: rows.length })}</span>
              </div>
              <div>
                {rows.map((row) => {
                  const res = testResult[row.id]
                  const dest =
                    row.channel === 'email'
                      ? (row.recipients ?? []).join('、')
                      : row.webhook_host
                  return (
                    <Item
                      key={row.id}
                      size="sm"
                      className="border-input border-0 border-b border-dashed px-0 py-3 last:border-b-0"
                    >
                      <ItemMedia className="translate-y-0! self-center!">
                        <IconTile variant="elevated" size="default">
                          <HugeiconsIcon icon={CHANNEL_ICON[row.channel] ?? BubbleChatIcon} strokeWidth={2} aria-hidden="true" />
                        </IconTile>
                      </ItemMedia>
                      <ItemContent>
                        <ItemTitle className="gap-2">
                          {row.name}
                          {row.periods.length > 0 ? (
                            row.periods.map((p) => (
                              <Badge key={p} variant="info-light" size="xs">{periodLabel(p)}</Badge>
                            ))
                          ) : (
                            <span className="text-11 font-normal text-muted-foreground">{t('noPeriods')}</span>
                          )}
                          <Badge variant="secondary" size="xs">
                            {t('thresholdIs', { level: severityLabel(row.alert_severity_threshold) })}
                          </Badge>
                        </ItemTitle>
                        {dest && <ItemDescription className="font-mono text-11">{dest}</ItemDescription>}
                        {row.secret_stale && (
                          <ItemDescription className="text-destructive">{t('secretStale')}</ItemDescription>
                        )}
                        {res === 'pending' && (
                          <ItemDescription className="inline-flex items-center gap-1.5">
                            <HugeiconsIcon icon={Loading03Icon} strokeWidth={2} className="size-3.5 animate-spin" /> {t('sending')}
                          </ItemDescription>
                        )}
                        {res && res !== 'pending' && (
                          <ItemDescription className={cn('inline-flex items-center gap-1.5', res.ok ? 'text-success' : 'text-destructive')}>
                            <HugeiconsIcon icon={res.ok ? CheckIcon : Cancel01Icon} strokeWidth={2} className="size-3.5" />
                            {res.ok ? t('testOk') : t('testFailed', { err: res.error ?? c('unknown') })}
                          </ItemDescription>
                        )}
                      </ItemContent>
                      <ItemActions className="gap-2">
                        <TargetStatus row={row} />
                        <DropdownMenu>
                          <DropdownMenuTrigger
                            render={
                              <Button
                                type="button"
                                variant="outline"
                                size="icon-xs"
                                aria-label={t('rowActions', { name: row.name })}
                                aria-disabled={!gate.allowed || undefined}
                                title={gate.reason || undefined}
                                onClick={(e) => { if (!gate.allowed) e.preventDefault() }}
                              >
                                <HugeiconsIcon icon={MoreVerticalIcon} strokeWidth={2} aria-hidden="true" />
                              </Button>
                            }
                          />
                          {gate.allowed && (
                            <DropdownMenuContent align="end" className="min-w-40">
                              <DropdownMenuGroup>
                                <DropdownMenuItem onClick={() => handleTest(row.id)} disabled={res === 'pending'}>
                                  <HugeiconsIcon icon={SendIcon} strokeWidth={2} aria-hidden="true" />
                                  {t('testSend')}
                                </DropdownMenuItem>
                                <DropdownMenuItem onClick={() => setEditing({ target: row })}>
                                  <HugeiconsIcon icon={PencilIcon} strokeWidth={2} aria-hidden="true" />
                                  {c('edit')}
                                </DropdownMenuItem>
                                <DropdownMenuSeparator />
                                <DropdownMenuItem variant="destructive" onClick={() => setConfirmDelete(row.id)}>
                                  <HugeiconsIcon icon={Delete02Icon} strokeWidth={2} aria-hidden="true" />
                                  {c('delete')}
                                </DropdownMenuItem>
                              </DropdownMenuGroup>
                            </DropdownMenuContent>
                          )}
                        </DropdownMenu>
                      </ItemActions>
                    </Item>
                  )
                })}
              </div>
            </div>
          ))}
        </div>
      )}

      <AlertDialog open={deleting !== null} onOpenChange={(v) => !v && setConfirmDelete(null)}>
        <AlertDialogContent>
          <AlertDialogHeader>
            <AlertDialogTitle>{t('deleteTarget', { name: deleting?.name ?? '' })}</AlertDialogTitle>
            <AlertDialogDescription>{t('deleteTargetBody')}</AlertDialogDescription>
          </AlertDialogHeader>
          <AlertDialogFooter>
            <AlertDialogCancel>{c('cancel')}</AlertDialogCancel>
            <AlertDialogAction variant="destructive" onClick={() => { if (deleting) void handleDelete(deleting.id) }}>
              {c('delete')}
            </AlertDialogAction>
          </AlertDialogFooter>
        </AlertDialogContent>
      </AlertDialog>

      {editing && (
        <TargetEditorDialog
          initial={editing.target}
          onClose={() => setEditing(null)}
          onSaved={(c) => {
            setEditing(null)
            onChanged(c)
          }}
        />
      )}
    </div>
  )
}

/* 一行一个状态徽标，优先级：密钥失效 > 已停用 > 已设置（聊天渠道）/ 收件人数（邮件）。 */
function TargetStatus({ row }: { row: NotifyTarget }) {
  const t = useT(notifyCopy)
  if (row.secret_stale) return <Badge variant="destructive-light">{t('badgeStale')}</Badge>
  if (!row.enabled) return <Badge variant="secondary">{t('targetDisabled')}</Badge>
  if (row.channel === 'email') {
    return <Badge variant="info-light">{t('badgeRecipients', { n: (row.recipients ?? []).length })}</Badge>
  }
  const set = channelMeta(row.channel).signed ? row.secret_set : row.webhook_set
  return set
    ? <Badge variant="success-light">{t('secretSet')}</Badge>
    : <Badge variant="warning-light">{t('badgeNoSecret')}</Badge>
}

type TargetDraft = {
  channel: NotifyChannel
  name: string
  webhook_url: string
  recipients: string
  secret: string
  clearSecret: boolean
  periods: string[]
  alert_severity_threshold: string
  enabled: boolean
}

function TargetEditorDialog({
  initial,
  onClose,
  onSaved,
}: {
  initial: NotifyTarget | null
  onClose: () => void
  onSaved: (c: NotifyConfig) => void
}) {
  const t = useT(notifyCopy)
  const c = useT(commonCopy)
  const creating = initial === null
  const [draft, setDraft] = useState<TargetDraft>(() => ({
    channel: initial?.channel ?? 'feishu',
    name: initial?.name ?? '',
    /* 编辑既有目标时这里是空的 —— 明文读不回来，留空 = 沿用已存的那条。 */
    webhook_url: '',
    // 收件人在界面上是一行文本：人是从通讯录里粘一串进来的，不是一个个填。
    recipients: (initial?.recipients ?? []).join(', '),
    secret: '',
    clearSecret: false,
    periods: initial?.periods ?? [],
    alert_severity_threshold: initial?.alert_severity_threshold ?? 'high',
    enabled: initial?.enabled ?? true,
  }))
  const [err, setErr] = useState<string | null>(null)
  const [saving, setSaving] = useState(false)

  function patch(p: Partial<TargetDraft>) {
    setDraft((d) => ({ ...d, ...p }))
  }
  function togglePeriod(k: string) {
    patch({ periods: draft.periods.includes(k) ? draft.periods.filter((p) => p !== k) : [...draft.periods, k] })
  }

  async function save() {
    setErr(null)
    if (!draft.name.trim()) return setErr(t('errNameRequired'))
    if (draft.channel === 'email') {
      if (!draft.recipients.trim()) return setErr(t('errRecipientsRequired'))
    } else if (!draft.webhook_url.trim() && !initial?.webhook_set) {
      return setErr(t('errWebhookRequired'))
    }
    setSaving(true)
    try {
      const c = await api.notifyUpsertTarget({
        ...(initial ? { id: initial.id } : {}),
        channel: draft.channel,
        name: draft.name.trim(),
        ...(draft.channel === 'email'
          ? { recipients: draft.recipients.split(/[,;\s]+/).filter(Boolean) }
          : draft.webhook_url.trim()
            ? { webhook_url: draft.webhook_url.trim() }
            : {}),
        ...(draft.clearSecret
          ? { clear_secret: true }
          : draft.secret.trim()
            ? { secret: draft.secret.trim() }
            : {}),
        periods: draft.periods,
        alert_severity_threshold: draft.alert_severity_threshold,
        enabled: draft.enabled,
      })
      onSaved(c)
    } catch (e) {
      const ex = e as ApiError
      const detail = apiErrorMessage(ex.body, ex.message)
      setErr(detail || t('errSave'))
    } finally {
      setSaving(false)
    }
  }

  return (
    <Dialog open onOpenChange={(v) => !v && onClose()}>
      <DialogContent className="flex flex-col gap-0 overflow-hidden p-0 sm:max-w-[560px] max-h-[86vh]">
        {/* DialogHeader 不认 title 这个 prop（那只是 HTML 的 tooltip），弹窗原来
            根本没有标题，也没有可访问名。 */}
        <DialogHeader className="border-b px-6 pt-5 pb-4">
          <DialogTitle>{creating ? t('dlgCreate') : t('dlgEdit')}</DialogTitle>
        </DialogHeader>
        <div className="flex-1 min-h-0 space-y-4 overflow-auto px-6 py-5">
          {/* 渠道只在新建时可选：改渠道等于换一个目标（webhook 和收件人不是一回事），
              留着可改会让「这条历史投递属于谁」变得说不清。 */}
          <div className="space-y-1.5">
            <Label className="font-mono text-xs text-muted-foreground">{t('fieldChannel')}</Label>
            <ToggleGroup
              multiple={false}
              value={[draft.channel]}
              onValueChange={(v) => patch({ channel: (v[0] as NotifyChannel) ?? 'feishu' })}
              variant="outline"
              size="sm"
              aria-label={t('channelAria')}
            >
              {/* `c` 在这个组件里是 commonCopy 的取名函数，所以列表项另起名。 */}
              {CHANNELS.map((ch) => (
                <ToggleGroupItem key={ch.value} value={ch.value} disabled={!creating}>
                  {channelLabel(ch.value)}
                </ToggleGroupItem>
              ))}
            </ToggleGroup>
          </div>

          <label className="block space-y-1.5">
            <Label className="font-mono text-xs text-muted-foreground">{t('fieldName')}</Label>
            <Input
              value={draft.name}
              onChange={(e) => patch({ name: e.target.value })}
              placeholder={draft.channel === 'email' ? t('namePlaceholderEmail') : t('namePlaceholderChat')}
            />
          </label>

          {draft.channel === 'email' ? (
            <label className="block space-y-1.5">
              <Label className="font-mono text-xs text-muted-foreground">{t('fieldRecipients')}</Label>
              <Textarea
                value={draft.recipients}
                onChange={(e) => patch({ recipients: e.target.value })}
                placeholder="soc@corp.example, ciso@corp.example"
                className="min-h-[72px] font-mono text-12"
              />
              <p className="text-12 text-muted-foreground">
                {t('recipientsHint')}
              </p>
            </label>
          ) : (
            <label className="block space-y-1.5">
              <Label className="font-mono text-xs text-muted-foreground">Webhook URL</Label>
              <Input
                value={draft.webhook_url}
                onChange={(e) => patch({ webhook_url: e.target.value })}
                placeholder={
                  initial?.webhook_set
                    ? t('webhookPlaceholderSet', { host: initial.webhook_host || '' })
                    : channelMeta(draft.channel).placeholder
                }
                className="font-mono text-12"
              />
            </label>
          )}

          <label className={cn('block space-y-1.5', !channelMeta(draft.channel).signed && 'hidden')}>
            <Label className="font-mono text-xs text-muted-foreground">{t('fieldSecret')}</Label>
            <Input
              type="password"
              autoComplete="new-password"
              value={draft.secret}
              onChange={(e) => patch({ secret: e.target.value })}
              disabled={draft.clearSecret}
              placeholder={initial?.secret_set ? t('secretPlaceholderSet') : t('secretPlaceholderUnset')}
              className="font-mono text-12"
            />
            {initial?.secret_set && (
              <label className="flex items-center gap-2 text-12 text-muted-foreground">
                <Checkbox
                  checked={draft.clearSecret}
                  onCheckedChange={(v) => patch({ clearSecret: v, secret: '' })}
                />
                {t('clearSecret')}
              </label>
            )}
          </label>

          <div className="space-y-1.5">
            <Label className="font-mono text-xs text-muted-foreground">{t('fieldBindPeriods')}</Label>
            <div className="flex flex-wrap gap-4">
              {PERIODS.map((p) => (
                <label key={p.key} className="flex items-center gap-2 text-14 text-foreground">
                  <Checkbox checked={draft.periods.includes(p.key)} onCheckedChange={() => togglePeriod(p.key)} />
                  {t(p.label)}
                </label>
              ))}
            </div>
          </div>

          <label className="block space-y-1.5">
            <Label className="font-mono text-xs text-muted-foreground">{t('fieldThreshold')}</Label>
            <Select
              value={draft.alert_severity_threshold}
              onChange={(v) => patch({ alert_severity_threshold: v })}
              options={SEVERITIES}
              render={(o) => `${severityLabel(o)} (${o})`}
            />
          </label>

          <label className="flex items-center gap-2 text-sm text-foreground">
            <Checkbox checked={draft.enabled} onCheckedChange={(v) => patch({ enabled: v })} />
            {t('enableTarget')}
          </label>

          {err && (
            <Alert variant="destructive">
              <HugeiconsIcon icon={AlertCircleIcon} strokeWidth={2} className="size-4" />
              <AlertDescription>{err}</AlertDescription>
            </Alert>
          )}
        </div>
        {/* DialogFooter 自带 -mx-4 -mb-4，是配 DialogContent 默认 p-4 的；这个弹窗
            content 是 p-0，负边距会把按钮顶到边框上。 */}
        <DialogFooter className="mx-0 mb-0 px-6 py-4">
          <Button variant="outline" onClick={onClose} disabled={saving}>
            {c('cancel')}
          </Button>
          <GatedButton gate="admin" variant="default" className="rounded-full" onClick={save} disabled={saving}>
            {saving ? t('savingDots') : c('save')}
          </GatedButton>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  )
}

/* ----- Deliveries ----- */

/* 状态原来直接把英文枚举打在界面上（sent / dead）。`dead` 尤其要说人话 ——
   它的意思是「重试到头了，除非有人来管，这条永远发不出去」。 */
const DELIVERY_KEY: Record<NotifyDelivery['status'], NotifyKey> = {
  queued: 'dvQueued',
  sending: 'dvSending',
  sent: 'dvSent',
  failed: 'dvFailed',
  dead: 'dvDead',
}

const DELIVERY_TONE: Record<NotifyDelivery['status'], 'blue' | 'gray' | 'sev-high' | 'sev-critical'> = {
  queued: 'gray',
  sending: 'blue',
  sent: 'blue',
  failed: 'sev-high',
  dead: 'sev-critical',
}

export function DeliveriesBlock() {
  const t = useT(notifyCopy)
  const c = useT(commonCopy)
  const [items, setItems] = useState<NotifyDelivery[] | null>(null)
  const [loading, setLoading] = useState(true)
  const [status, setStatus] = useState<string>('')
  const [retrying, setRetrying] = useState<string | null>(null)
  const [err, setErr] = useState<string | null>(null)

  async function load(next = status) {
    setLoading(true)
    try {
      const r = await api.notifyDeliveries({ limit: 100, ...(next ? { status: next } : {}) })
      setItems(r.deliveries)
    } catch {
      setItems([])
    } finally {
      setLoading(false)
    }
  }

  async function retry(id: string) {
    setRetrying(id)
    setErr(null)
    try {
      await api.notifyRetryDelivery(id)
      await load()
    } catch (e) {
      setErr((e as ApiError).message || t('errResend'))
    } finally {
      setRetrying(null)
    }
  }

  useEffect(() => {
    void load('')
  }, [])

  const dead = (items ?? []).filter((d) => d.status === 'dead').length

  return (
    <div className="flex flex-col gap-2.5">
      {/* 外面的 FramePanel 是 p-0（表格自己画边线），这一行工具条要自己留内边距，
          不然「N 条已放弃」和筛选 / 刷新都贴在边框上。 */}
      <div className="flex flex-wrap items-center gap-2 px-4 pt-3">
        {dead > 0 && <Pill tone="sev-critical">{t('deadCount', { n: dead })}</Pill>}
        <div className="ml-auto flex items-center gap-2">
          <Select
            value={status}
            onChange={(v) => {
              setStatus(v)
              void load(v)
            }}
            options={['', 'dead', 'failed', 'queued', 'sending', 'sent']}
            render={(v) => (v ? t(DELIVERY_KEY[v as NotifyDelivery['status']]) : t('allStatuses'))}
          />
          <Button variant="outline" className="rounded-full" size="sm" onClick={() => void load()} disabled={loading}>
            <HugeiconsIcon icon={RefreshCwIcon} strokeWidth={2} className={cn('size-3.5', loading && 'animate-spin')} /> {c('refresh')}
          </Button>
        </div>
      </div>

      {err && (
        <Alert variant="destructive">
          <HugeiconsIcon icon={AlertCircleIcon} strokeWidth={2} className="size-4" />
          <AlertDescription>{err}</AlertDescription>
        </Alert>
      )}

      {loading ? (
        <div className="py-6 text-center text-13 text-muted-foreground">{c('loading')}…</div>
      ) : !items || items.length === 0 ? (
        <p className="py-3 text-13 text-muted-foreground">
          {status ? t('noRecordsForStatus') : t('noRecords')}
        </p>
      ) : (
        <div className="overflow-x-auto">
          <table className="w-full border-collapse text-13">
            <thead>
              <tr className="[box-shadow:0_-1px_0_var(--color-line)_inset]">
                {[
                  t('colKind'),
                  t('colChannel'),
                  t('colTarget'),
                  t('colStatus'),
                  t('colAttempts'),
                  t('colLastError'),
                  t('colUpdatedAt'),
                  '',
                ].map((h, i) => (
                  <th scope="col" key={h || `act-${i}`} className="px-3 py-2 text-left font-mono text-11 font-medium uppercase tracking-wide text-muted-foreground">
                    {h}
                  </th>
                ))}
              </tr>
            </thead>
            <tbody>
              {items.map((d, i) => (
                <tr key={d.id ?? `${d.ref}-${d.target_id}-${i}`} className="[box-shadow:0_-1px_0_var(--color-line)_inset]">
                  <td className="px-3 py-2 text-12 text-muted-foreground">{d.kind === 'report' ? t('kindReport') : t('kindAlert')}</td>
                  <td className="px-3 py-2 text-12 text-muted-foreground">{channelLabel(d.channel ?? 'feishu')}</td>
                  <td className="px-3 py-2 text-12 text-foreground">{d.target_name ?? d.target_id}</td>
                  <td className="px-3 py-2">
                    <Pill tone={DELIVERY_TONE[d.status]}>{DELIVERY_KEY[d.status] ? t(DELIVERY_KEY[d.status]) : d.status}</Pill>
                  </td>
                  <td className="px-3 py-2 font-mono text-12 tabular-nums text-foreground">{d.attempts}</td>
                  <td className="px-3 py-2 text-11 text-destructive">
                    <span className="block max-w-[280px] truncate" title={d.last_error ?? ''}>
                      {d.last_error ?? '—'}
                    </span>
                  </td>
                  <td className="px-3 py-2 font-mono text-11 text-muted-foreground">{formatTs(d.updated_at)}</td>
                  <td className="px-3 py-2 text-right">
                    {/* 排队中和发送中不给重投：前者本来就在队里，后者正被 worker
                        持有，动它会撞上租约的 CAS。 */}
                    {d.id && d.status !== 'queued' && d.status !== 'sending' && (
                      <GatedButton
                        gate="admin"
                        variant="ghost"
                        size="sm"
                        onClick={() => void retry(d.id)}
                        disabled={retrying === d.id}
                      >
                        <HugeiconsIcon
                          icon={RefreshCwIcon}
                          strokeWidth={2}
                          className={cn('size-3.5', retrying === d.id && 'animate-spin')}
                        />
                        {t('resend')}
                      </GatedButton>
                    )}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </div>
  )
}

/* ----- shared bits ----- */

/* The page's own thin wrapper over the Select primitive: every use here is the
 * same shape — a list of plain string options with an optional label mapper. */
function Select({
  value,
  onChange,
  options,
  render,
}: {
  value: string
  onChange: (v: string) => void
  options: readonly string[]
  render?: (o: string) => string
}) {
  return (
    <SelectRoot value={value} onValueChange={(v) => onChange(String(v))}>
      <SelectTrigger className="w-full">
        <SelectValue>{(v) => (render ? render(String(v)) : String(v))}</SelectValue>
      </SelectTrigger>
      <SelectContent>
        {options.map((o) => (
          <SelectItem key={o} value={o}>
            {render ? render(o) : o}
          </SelectItem>
        ))}
      </SelectContent>
    </SelectRoot>
  )
}

function formatTs(s?: string): string {
  if (!s) return '—'
  try {
    const d = new Date(s)
    if (isNaN(d.getTime())) return s
    return d.toLocaleString()
  } catch {
    return s
  }
}
