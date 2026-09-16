import { useEffect, useRef, useState } from 'react'
import { HugeiconsIcon } from '@hugeicons/react'
import {
  AlertCircleIcon, ArrowRight01Icon, Calendar03Icon, CheckmarkCircle02Icon, CopyIcon,
  Key01Icon, LicenseIcon, Loading03Icon, Activity01Icon, Upload01Icon,
} from '@hugeicons/core-free-icons'
import { toast } from 'sonner'
import { api } from '@/lib/api'
import { Alert, AlertDescription } from '@/components/reui/alert'
import { Badge } from '@/components/reui/badge'
import { Frame, FrameFooter, FrameHeader, FramePanel, FrameTitle } from '@/components/reui/frame'
import { IconTile } from '@/components/reui/icon-tile'
import { PageHeader } from '@/components/shell/page-header'
import { useGate } from '@/components/gated-button'
import { Button } from '@/components/ui/button'
import { Textarea } from '@/components/ui/textarea'
import { Tabs, TabsList, TabsTrigger } from '@/components/ui/tabs'
import { useT, translate, type Translate } from '@/lib/i18n'
import { extractToken } from '@/lib/licenseToken'
import { commonCopy } from '@/locales/common'
import { licenseCopy, type LicenseKey } from '@/locales/license'
import { cn } from '@/lib/utils'
import { apiErrorMessage } from '@/locales/errors'

type Status = 'unactivated' | 'valid' | 'expiring' | 'grace' | 'expired' | 'revoked' | 'invalid' | 'heartbeat_lost' | 'unknown'

/* 状态码是给日志看的，页面上要说人话。存的是文案键 —— 这张表在四个地方渲染。 */
const STATUS_KEY: Record<string, LicenseKey> = {
  unactivated: 'stUnactivated',
  valid: 'stValid',
  expiring: 'stExpiring',
  grace: 'stGrace',
  expired: 'stExpired',
  revoked: 'stRevoked',
  invalid: 'stInvalid',
  heartbeat_lost: 'stHeartbeatLost',
  unknown: 'stUnknown',
}

function statusLabel(status: string): string {
  const key = STATUS_KEY[status]
  return key ? translate(licenseCopy, key) : status
}

/* 收费能力的 id → 人话。id 和后端 feature_unlock.py 的四把锁一一对应；许可里
   出现没见过的 id 就原样显示，别把它藏掉——那是排「为什么这功能没解锁」时的线索。 */
const FEATURE_KEY: Record<string, LicenseKey> = {
  detection_rule_copilot: 'featDetectionRule',
  alert_triage: 'featAlertTriage',
  alert_investigation: 'featAlertInvestigation',
  platform_ops_copilot: 'featPlatformOps',
}

function featureLabel(id: string): string {
  const key = FEATURE_KEY[id]
  return key ? translate(licenseCopy, key) : id
}

interface LicenseState {
  status: Status
  license_id?: string | null
  license_type?: string | null
  email?: string | null
  expiry_date?: string | null
  features?: string[]
  loaded_at?: string | null
  last_heartbeat_ok_at?: string | null
}

export function LicensePage() {
  const t = useT(licenseCopy)
  const [state, setState] = useState<LicenseState | null>(null)
  const [keyText, setKeyText] = useState('')
  const [submitting, setSubmitting] = useState(false)
  const [confirmDeact, setConfirmDeact] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const [hostFingerprint, setHostFingerprint] = useState<string | null>(null)
  const [hostFpErr, setHostFpErr] = useState<string | null>(null)
  const [mode, setMode] = useState<'online' | 'offline'>('online')
  // /api/license/host-fingerprint 是 require_admin 的；非管理员别去发这条
  // 注定 403 的请求（控制台一条噪音），直接把原因写进指纹卡。
  const fpGate = useGate('admin')

  async function refresh() {
    try {
      const r = await fetch('/api/license/status')
      if (!r.ok) {
        // A 4xx/5xx body is a {detail} error or an HTML error page, not a
        // LicenseState — casting it would leave status undefined and silently
        // render the activate card. Surface a real diagnostic instead.
        let detail = `HTTP ${r.status}`
        try {
          detail = apiErrorMessage(await r.json(), detail)
        } catch { /* non-JSON error body */ }
        setError(t('errStatus', { detail }))
        return
      }
      const d = (await r.json()) as LicenseState
      setState(d)
    } catch (e) {
      setError(String(e))
    }
  }

  async function loadFingerprint() {
    try {
      const r = await fetch('/api/license/host-fingerprint')
      if (!r.ok) {
        // Surface the 503 (hardware unreadable) / 403 (not admin) instead of
        // leaving the card stuck on "加载中…" forever.
        setHostFpErr(await fetchErrDetail(r))
        return
      }
      const d = await r.json()
      setHostFingerprint(d.host_fingerprint ?? null)
    } catch (e) {
      setHostFpErr(String(e))
    }
  }

  useEffect(() => {
    // eslint-disable-next-line react-hooks/set-state-in-effect -- initial load on mount
    refresh()
    if (fpGate.allowed) loadFingerprint()
    else setHostFpErr(fpGate.reason)
  }, [])

  async function onActivate() {
    if (!keyText.trim()) {
      setError(t('errPasteKey'))
      return
    }
    setSubmitting(true)
    setError(null)
    try {
      const r = await fetch('/api/license/activate', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ license_key: keyText.trim() }),
      })
      if (!r.ok) {
        const d = await r.json().catch(() => ({}))
        throw new Error(apiErrorMessage(d, `HTTP ${r.status}`))
      }
      await refresh()
      setKeyText('')
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e))
    } finally {
      setSubmitting(false)
    }
  }

  async function onDeactivate() {
    setSubmitting(true)
    setError(null)
    try {
      const r = await fetch('/api/license/deactivate', { method: 'POST' })
      if (!r.ok) {
        const d = await r.json().catch(() => ({}))
        throw new Error(apiErrorMessage(d, `HTTP ${r.status}`))
      }
      await refresh()
      setConfirmDeact(false)
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e))
    } finally {
      setSubmitting(false)
    }
  }

  const status = state?.status ?? 'unknown'
  const isActivated = status === 'valid' || status === 'expiring' || status === 'grace'
  const notice = statusNotice(t, status)

  function onUpload(file: File) {
    setError(null)
    // A license token is ~1-2 KB of text; anything large is the wrong file.
    // Guard before reading it all into memory.
    if (file.size > 256 * 1024) {
      setError(t('errFileTooLarge'))
      return
    }
    const reader = new FileReader()
    reader.onload = () => {
      const token = extractToken(String(reader.result ?? ''))
      if (!token) {
        setError(t('errNoToken'))
        return
      }
      setKeyText(token)
    }
    reader.onerror = () => setError(t('errReadFile'))
    reader.readAsText(file)
  }

  const activateCard = (
    <ActivateCard
      keyText={keyText}
      setKeyText={setKeyText}
      onActivate={onActivate}
      onUpload={onUpload}
      submitting={submitting}
      error={error}
      mode={mode}
    />
  )

  // Both modes bind to the SAME host fingerprint — online activation
  // auto-binds it on the first /activate call (nothing to send anyone),
  // offline bakes it into the token at issue time. Show the one identifier
  // in either mode; the copy differs by mode.
  const bindingCard = (
    <HostFingerprintCard fingerprint={hostFingerprint} error={hostFpErr} mode={mode} />
  )

  return (
    <div className="@container flex w-full flex-col gap-5">
      {/* 未激活时这页原来只有一个粘贴框，「现在到底激活没有」得去侧栏底部那条
          进度条上看。状态是这页的第一句话。 */}
      <PageHeader title={t('title')} />

      <section aria-label={t('secMode')}>
        <ModeToggle mode={mode} setMode={setMode} />
      </section>

      {isActivated ? (
        <>
          <ActivatedCard
            state={state!}
            deactivate={{
              confirming: confirmDeact,
              busy: submitting,
              onConfirm: onDeactivate,
              onToggle: setConfirmDeact,
            }}
          />
          {/* Already-activated hosts can still paste a NEW key to swap or renew
              (renewal = the license server signs a longer-dated token; the
              client just re-activates it). Expiry is never extended locally. */}
          <section aria-label={t('secSwap')}>{activateCard}</section>
        </>
      ) : notice ? (
        <>
          <section aria-label={t('secStatus')}>
            <StatusNoticeCard notice={notice} state={state} />
          </section>
          {/* heartbeat_lost is still in-period — re-pasting a key won't help,
              so only offer re-activation for expired/revoked/invalid. */}
          {notice.allowReactivate && <section aria-label={t('secReactivate')}>{activateCard}</section>}
        </>
      ) : (
        <section aria-label={t('secActivate')} className="flex flex-col gap-2">
          {/* 「当前状态 / 激活后解除额度限制」是激活这件事的说明，挂在激活卡上，
              不挂在大标题下面。 */}
          <p className="text-xs text-muted-foreground">
            {t('descUnactivated', { status: statusLabel(status) })}
          </p>
          {activateCard}
        </section>
      )}

      {mode === 'offline' && <section aria-label={t('secBinding')}>{bindingCard}</section>}
    </div>
  )
}

/** Best-effort, user-facing detail for a failed license fetch. */
async function fetchErrDetail(r: Response): Promise<string> {
  if (r.status === 401 || r.status === 403) return translate(licenseCopy, 'errNeedAdmin')
  try {
    return apiErrorMessage(await r.json(), `HTTP ${r.status}`)
  } catch {
    /* non-JSON body */
  }
  return `HTTP ${r.status}`
}

function ModeToggle({
  mode,
  setMode,
}: {
  mode: 'online' | 'offline'
  setMode: (m: 'online' | 'offline') => void
}) {
  const t = useT(licenseCopy)
  const opts: Array<{ id: 'online' | 'offline'; label: string }> = [
    { id: 'online', label: t('modeOnline') },
    { id: 'offline', label: t('modeOffline') },
  ]
  // Tabs 用原语自己的样子。原来这里用一串字面色把它重画成一个分段控件，
  // 和知识库那三个 tab 又长得不一样 —— 同一个产品里两套 tab 是两套语言。
  // 面板在 tablist 之外，所以只用到 Root + List + Trigger。
  return (
    <Tabs value={mode} onValueChange={(v) => setMode(v as 'online' | 'offline')}>
      <TabsList>
        {opts.map((o) => (
          <TabsTrigger key={o.id} value={o.id}>
            {o.label}
          </TabsTrigger>
        ))}
      </TabsList>
    </Tabs>
  )
}

interface StatusNotice {
  title: string
  desc: string
  allowReactivate: boolean
}

/** Maps the abnormal-but-not-unactivated statuses to a user-facing notice.
 * Returns null for unactivated/unknown (→ plain activate flow) and for the
 * activated states (handled separately). */
function statusNotice(t: Translate<LicenseKey>, status: Status): StatusNotice | null {
  switch (status) {
    case 'heartbeat_lost':
      return {
        title: t('noticeHeartbeatTitle'),
        desc: t('noticeHeartbeatDesc'),
        allowReactivate: false,
      }
    case 'expired':
      return { title: t('noticeExpiredTitle'), desc: t('noticeExpiredDesc'), allowReactivate: true }
    case 'revoked':
      return { title: t('noticeRevokedTitle'), desc: t('noticeRevokedDesc'), allowReactivate: true }
    case 'invalid':
      return { title: t('noticeInvalidTitle'), desc: t('noticeInvalidDesc'), allowReactivate: true }
    default:
      return null
  }
}

function StatusNoticeCard({ notice, state }: { notice: StatusNotice; state: LicenseState | null }) {
  const t = useT(licenseCopy)
  return (
    <Frame dense spacing="sm" className="flex w-full min-w-0 flex-col [--frame-panel-header-py-adjust:2px]">
      <FrameHeader className="flex-row items-center justify-between gap-4">
        <div className="flex items-center gap-2.5">
            <HugeiconsIcon icon={AlertCircleIcon} strokeWidth={2} className="size-5 text-destructive" />
          <FrameTitle>{notice.title}</FrameTitle>
        </div>
        {state?.status && (
          <Badge size="sm" variant="destructive-light">{statusLabel(state.status)}</Badge>
        )}
      </FrameHeader>
      <FramePanel className="space-y-4 bg-card py-5 shadow-none!">
        <p className="text-sm leading-relaxed text-muted-foreground">{notice.desc}</p>
        {state?.license_id && (
          <div className="space-y-3 border-t border-border pt-4">
            <Field label={t('fieldLicenseId')} value={state.license_id ?? '—'} mono />
            <Field label={t('fieldType')} value={state.license_type ?? '—'} mono />
            <Field label={t('fieldExpiry')} value={state.expiry_date ?? '—'} mono />
            {state.last_heartbeat_ok_at && (
              <Field label={t('fieldLastHeartbeat')} value={state.last_heartbeat_ok_at} mono />
            )}
          </div>
        )}
      </FramePanel>
    </Frame>
  )
}



/* 到期还剩几天。已经过期就是负数，调用方按「已过期 N 天」渲染。 */
function daysLeft(expiry: string | null | undefined): number | null {
  if (!expiry) return null
  const t = Date.parse(expiry)
  if (Number.isNaN(t)) return null
  return Math.ceil((t - Date.now()) / 86_400_000)
}

/*
 * 已激活的那一屏，版式照 `@reui/profile-8`（计划摘要 + 三栏用量 + 明细行），
 * 容器全换成 Frame：
 *
 * 1. 摘要：图标格 + 许可类型 + 状态徽标 + 邮箱，右侧三条事实（到期 / 剩余天数 /
 *    上次心跳）；脚注放撤销激活——模板脚注是「换套餐」，这里最接近的动作就是它。
 * 2. 三栏用量：今日额度（/api/license/quota）、已解锁功能数、上次心跳。
 * 3. 明细：许可证 ID / 类型 / 邮箱 / 到期 / 功能徽标（中文名，不再是 feature id）。
 *
 * 「还剩几天」原来要自己拿到期日去减今天——而这页存在的意义就是回答「我还能用
 * 多久」。剩 30 天以内标黄，那是该联系续期的时候。
 *
 * 没照搬的：模板的 invoice history 表和 tooltip 提示这里没有对应物；模板的用量
 * 卡脚注 + 「升级」按钮也不要——试用额度的说明已经在侧栏那条进度条上。
 */
interface DeactivateControl {
  confirming: boolean
  busy: boolean
  onConfirm: () => void
  onToggle: (v: boolean) => void
}

function ActivatedCard({ state, deactivate }: { state: LicenseState; deactivate: DeactivateControl }) {
  const t = useT(licenseCopy)
  const c = useT(commonCopy)
  const left = daysLeft(state.expiry_date)
  const features = state.features ?? []
  const wildcard = features.includes('*')
  const renewSoon = left != null && left <= 30
  const [quota, setQuota] = useState<{ remaining: number; limit: number; active: boolean } | null>(null)

  useEffect(() => {
    api.licenseQuota().then(setQuota).catch(() => setQuota(null))
  }, [])

  const leftText =
    left == null ? '—' : left < 0 ? t('expiredDays', { n: -left }) : t('daysLeft', { n: left })
  const heartbeat = state.last_heartbeat_ok_at ? formatTs(state.last_heartbeat_ok_at) : '—'

  const facts: Array<{ id: string; label: string; value: string; warn?: boolean }> = [
    { id: 'expiry', label: t('kpiExpiry'), value: state.expiry_date || t('kpiNoExpiry') },
    { id: 'left', label: t('factDaysLeft'), value: leftText, warn: renewSoon },
    { id: 'hb', label: t('fieldLastHeartbeat'), value: heartbeat },
  ]

  const metrics = [
    {
      id: 'quota',
      icon: Activity01Icon,
      title: t('metricQuota'),
      // 取不到（非管理员 403 / 网络抖）显示「—」，不能当成不限次。
      desc: quota == null ? '—' : quota.active ? t('metricQuotaTrial') : t('metricQuotaOff'),
      value: quota == null ? '—' : quota.active ? `${quota.remaining} / ${quota.limit}` : '∞',
    },
    {
      id: 'features',
      icon: Key01Icon,
      title: t('kpiFeatures'),
      desc: wildcard ? t('featuresWildcardLabel') : t('featuresPerIdLabel'),
      value: wildcard ? t('featuresAll') : String(features.length),
    },
    {
      id: 'heartbeat',
      icon: Calendar03Icon,
      title: t('fieldLastHeartbeat'),
      desc: t('metricHeartbeatDesc'),
      value: heartbeat,
    },
  ]

  return (
    <>
      <section aria-label={t('secOverview')}>
        <Frame dense spacing="sm" className="flex w-full min-w-0 flex-col">
          <FramePanel className="px-5 py-5">
            <div className="grid items-start gap-6 md:grid-cols-[minmax(0,1fr)_minmax(12rem,16rem)]">
              <div className="flex min-w-0 gap-4">
                <IconTile variant="elevated" size="default">
                  <HugeiconsIcon icon={LicenseIcon} strokeWidth={2} aria-hidden="true" />
                </IconTile>
                <div className="min-w-0 space-y-2">
                  <div className="flex flex-wrap items-center gap-2">
                    <FrameTitle>{state.license_type || t('kpiNoType')}</FrameTitle>
                    <Badge size="sm" variant={state.status === 'valid' ? 'success-light' : 'warning-light'}>
                      {statusLabel(state.status)}
                    </Badge>
                  </div>
                  {state.email && <p className="text-sm text-muted-foreground">{state.email}</p>}
                  <p className="font-mono text-xs text-muted-foreground break-all">{state.license_id ?? '—'}</p>
                </div>
              </div>
              <dl className="grid gap-3 md:pl-4">
                {facts.map((f) => (
                  <div key={f.id} className="space-y-0.5">
                    <dt className="text-xs font-medium tracking-wide text-muted-foreground uppercase">{f.label}</dt>
                    <dd className={cn('text-sm font-medium tabular-nums', f.warn && 'text-warning')}>
                      {f.value}
                      {f.warn && <span className="ml-2 font-normal text-muted-foreground">{t('renewSoon')}</span>}
                    </dd>
                  </div>
                ))}
              </dl>
            </div>
          </FramePanel>
          <FrameFooter className="flex flex-col items-start justify-between gap-2 border-t px-5 py-3 sm:flex-row sm:items-center">
            <p className="max-w-xl text-sm text-muted-foreground">{t('deactivateHint')}</p>
            {deactivate.confirming ? (
              <div className="flex items-center gap-2">
                <Button variant="destructive" size="sm" onClick={deactivate.onConfirm} disabled={deactivate.busy}>
                  {t('confirmDeactivate')}
                </Button>
                <Button variant="ghost" size="sm" onClick={() => deactivate.onToggle(false)} disabled={deactivate.busy}>
                  {c('cancel')}
                </Button>
              </div>
            ) : (
              <Button variant="outline" size="sm" className="shrink-0" onClick={() => deactivate.onToggle(true)}>
                {t('deactivate')}
              </Button>
            )}
          </FrameFooter>
        </Frame>
      </section>

      <section aria-label={t('secUsage')}>
        <Frame dense spacing="sm" className="flex w-full min-w-0 flex-col">
          <FramePanel className="grid gap-0 p-0! sm:grid-cols-3 sm:divide-x">
            {metrics.map((m) => (
              <div key={m.id} className="flex min-h-28 flex-col justify-between gap-4 px-5 py-5">
                <div className="flex items-center gap-3">
                  <IconTile variant="elevated" size="sm">
                    <HugeiconsIcon icon={m.icon} strokeWidth={2} aria-hidden="true" />
                  </IconTile>
                  <div className="min-w-0">
                    <p className="text-sm font-medium">{m.title}</p>
                    <p className="text-sm text-muted-foreground">{m.desc}</p>
                  </div>
                </div>
                <p className="text-lg font-semibold tracking-tight tabular-nums">{m.value}</p>
              </div>
            ))}
          </FramePanel>
        </Frame>
      </section>

      <section aria-label={t('secDetail')}>
      <Frame dense spacing="sm" className="flex w-full min-w-0 flex-col [--frame-panel-header-py-adjust:2px]">
        <FrameHeader className="flex-row items-center justify-between gap-4">
          <div className="flex items-center gap-2.5">
            <HugeiconsIcon icon={CheckmarkCircle02Icon} strokeWidth={2} className="size-5 text-success" />
            <FrameTitle>{t('detailTitle')}</FrameTitle>
          </div>
          <Badge size="sm" variant={state.status === 'valid' ? 'success-light' : 'warning-light'}>{statusLabel(state.status)}</Badge>
        </FrameHeader>
        <FramePanel className="space-y-3 bg-card py-5 shadow-none!">
          <Field label={t('fieldLicenseId')} value={state.license_id ?? '—'} mono />
          <Field label={t('fieldType')} value={state.license_type ?? '—'} mono />
          <Field label={t('fieldEmail')} value={state.email ?? '—'} />
          <Field label={t('fieldExpiry')} value={state.expiry_date ?? '—'} mono />
          {features.length > 0 && (
            <div className="flex items-baseline justify-between gap-4">
              <span className="text-sm text-muted-foreground">{t('fieldFeatures')}</span>
              <div className="flex flex-wrap justify-end gap-1.5">
                {features.map((f) => (
                  <Badge
                    key={f}
                    size="sm"
                    variant={f === '*' ? 'primary-light' : 'secondary'}
                    title={f === '*' ? t('featureWildcardTitle') : f}
                  >
                    {f === '*' ? t('featureAllBadge') : featureLabel(f)}
                  </Badge>
                ))}
              </div>
            </div>
          )}
        </FramePanel>
      </Frame>
      </section>
    </>
  )
}

/** ISO → 本地「月-日 时:分」；心跳时间只要看得出是不是今天。 */
function formatTs(iso: string): string {
  const d = new Date(iso)
  if (Number.isNaN(d.getTime())) return iso
  const p = (n: number) => String(n).padStart(2, '0')
  return `${p(d.getMonth() + 1)}-${p(d.getDate())} ${p(d.getHours())}:${p(d.getMinutes())}`
}

function ActivateCard({
  keyText,
  setKeyText,
  onActivate,
  onUpload,
  submitting,
  error,
  mode,
}: {
  keyText: string
  setKeyText: (v: string) => void
  onActivate: () => void
  onUpload: (file: File) => void
  submitting: boolean
  error: string | null
  mode: 'online' | 'offline'
}) {
  const t = useT(licenseCopy)
  const fileRef = useRef<HTMLInputElement>(null)
  const offline = mode === 'offline'
  return (
    <Frame dense spacing="sm" className="flex w-full min-w-0 flex-col [--frame-panel-header-py-adjust:2px]">
      <FrameHeader className="flex-row items-center justify-between gap-4">
        <FrameTitle>{offline ? t('cardUploadTitle') : t('cardPasteTitle')}</FrameTitle>
        <Badge size="sm" variant="secondary">{offline ? t('badgeOffline') : t('badgeOnline')}</Badge>
      </FrameHeader>
      <FramePanel className="space-y-4 py-5 bg-card shadow-none!">
        {/* Offline / air-gapped delivery often arrives as a file — let ops upload
            it directly instead of pasting. Online keys can still be pasted. */}
        <div className="flex items-center gap-3">
          <input
            ref={fileRef}
            type="file"
            accept=".lic,.txt,.json,.key,text/plain,application/json"
            className="hidden"
            onChange={(e) => {
              const f = e.target.files?.[0]
              if (f) onUpload(f)
              e.target.value = ''  // allow re-selecting the same file
            }}
          />
          <Button variant={offline ? 'default' : 'ghost'} className="rounded-full" size="sm" onClick={() => fileRef.current?.click()}>
            <HugeiconsIcon icon={Upload01Icon} strokeWidth={2} className="size-3.5" />
            {t('uploadFile')}
          </Button>
        </div>
        <Textarea
          value={keyText}
          onChange={(e) => setKeyText(e.target.value)}
          placeholder={t('keyPlaceholder')}
          className="min-h-[140px] font-mono text-12"
          spellCheck={false}
        />
        {error && (
          <Alert variant="destructive">
            <HugeiconsIcon icon={AlertCircleIcon} strokeWidth={2} className="size-4" />
            <AlertDescription>{error}</AlertDescription>
          </Alert>
        )}
        <div className="flex items-center gap-3">
          <Button
            variant="default" className="rounded-full"
            onClick={onActivate}
            disabled={submitting || !keyText.trim()}
          >
            {submitting ? (
              <>
                <HugeiconsIcon icon={Loading03Icon} strokeWidth={2} className="size-4 animate-spin" />
                {t('activating')}
              </>
            ) : (
              <>
                {t('activate')}
                <HugeiconsIcon icon={ArrowRight01Icon} strokeWidth={2} className="size-3.5" />
              </>
            )}
          </Button>
        </div>
      </FramePanel>
    </Frame>
  )
}

function HostFingerprintCard({
  fingerprint,
  error,
  mode,
}: {
  fingerprint: string | null
  error: string | null
  mode: 'online' | 'offline'
}) {
  const t = useT(licenseCopy)
  const c = useT(commonCopy)
  const online = mode === 'online'
  return (
    <Frame dense spacing="sm" className="flex w-full min-w-0 flex-col [--frame-panel-header-py-adjust:2px]">
      <FrameHeader className="flex-row items-center justify-between gap-4">
        <FrameTitle>{t('fingerprintTitle')}</FrameTitle>
        {online ? (
          <Badge size="sm" variant="secondary">{t('fingerprintBadge')}</Badge>
        ) : null}
      </FrameHeader>
      <FramePanel className="space-y-2 bg-card py-5 shadow-none!">
        <div className="flex items-start gap-2">
          <code
            className={cn(
              'block flex-1 break-all rounded-md border border-border bg-muted/50 px-3 py-2 font-mono text-xs',
              error ? 'text-destructive' : 'text-foreground',
            )}
          >
            {fingerprint ?? error ?? `${c('loading')}…`}
          </code>
          <Button
            variant="outline"
            size="icon-sm"
            className="shrink-0"
            title={t('copyFingerprint')}
            aria-label={t('copyFingerprint')}
            disabled={!fingerprint}
            onClick={() => {
              if (!fingerprint) return
              void navigator.clipboard
                .writeText(fingerprint)
                .then(() => toast.success(t('okCopiedFingerprint')))
                .catch(() => toast.error(t('errCopyFingerprint')))
            }}
          >
            <HugeiconsIcon icon={CopyIcon} strokeWidth={2} className="size-3.5" />
          </Button>
        </div>
        {online ? (
          <p className="text-xs leading-relaxed text-muted-foreground">
            {t('fingerprintOnlineNote')}
          </p>
        ) : null}
      </FramePanel>
    </Frame>
  )
}

function Field({ label, value, mono }: { label: string; value: string; mono?: boolean }) {
  return (
    <div className="flex items-baseline justify-between gap-4">
      <span className="text-sm text-muted-foreground">{label}</span>
      <span className={cn('text-right text-sm break-all', mono && 'font-mono text-xs')}>
        {value}
      </span>
    </div>
  )
}

