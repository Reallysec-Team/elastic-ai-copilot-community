import { useEffect, useRef, useState, useSyncExternalStore } from 'react'
import { Link } from '@tanstack/react-router'
import { HugeiconsIcon } from '@hugeicons/react'
import {
  AlertCircleIcon, CheckmarkCircle02Icon, ComputerIcon, Loading03Icon, Moon02Icon,
  Settings01Icon, Sun01Icon, UserIcon,
} from '@hugeicons/core-free-icons'
import { toast } from 'sonner'

import { api, type ApiError } from '@/lib/api'
import { useMe } from '@/lib/auth'
import { ACCEPT, AvatarError, fileToAvatar } from '@/lib/avatar'
import { setLang, useLang, useT, type Lang } from '@/lib/i18n'
import { getPrefs, PREFS_EVENT, resetColumns, savePref } from '@/lib/prefs'
import { getThemeMode, setThemeMode, type ThemeMode } from '@/lib/theme'
import { useAvatar } from '@/lib/useAvatar'
import { useIsMobile } from '@/hooks/use-mobile'
import { cn } from '@/lib/utils'
import { accountCopy, type AccountKey } from '@/locales/account'
import { ROLE_HINT_KEY, ROLE_KEY, shellCopy } from '@/locales/shell'
import { SettingField } from '@/components/blocks/settings-3/components/setting-field'
import { IndexCombobox } from '@/components/IndexCombobox'
import { Alert, AlertDescription } from '@/components/reui/alert'
import { Badge } from '@/components/reui/badge'
import { SettingsCard } from '@/components/settings/settings-card'
import { PageHeader } from '@/components/shell/page-header'
import { Avatar, AvatarFallback, AvatarImage } from '@/components/ui/avatar'
import { Button } from '@/components/ui/button'
import { Input } from '@/components/ui/input'
import {
  Select, SelectContent, SelectItem, SelectTrigger, SelectValue,
} from '@/components/ui/select'
import { Tabs, TabsContent, TabsList, TabsTrigger } from '@/components/ui/tabs'
import { ToggleGroup, ToggleGroupItem } from '@/components/ui/toggle-group'

/*
 * 账号页 = 个人资料 + 偏好设置，两个路由（/profile、/preferences）共用这一页，
 * 路由就是当前页签。版式照 `@reui/profile-1`：左侧一列竖排页签（手机横排），
 * 右侧内容；每张卡是 settings-3 的 SettingField 行（本仓 `SettingsCard` 壳）。
 *
 * 个人资料原来是右上角头像下拉里的一个 Sheet（`profile-sheet.tsx`），现在按
 * 模板成了一页，改密码那块原样搬过来。偏好（语言 / 主题 / 默认索引 / 每页
 * 行数 / 记住的列集）原来散在各处的控件上，这里第一次聚到一起——它们都是
 * `lib/prefs.ts` 里那份 per-user prefs，改动即时保存、跨设备同步。
 *
 * 没照搬的：profile-1 的 Workspace / Team / Billing 三个页签这里没有对应物
 * （用户管理在 /users，产品激活在 /license）；模板表单是「改完点保存」，这里
 * 偏好即时生效——它们本来就是这么存的，多一个保存按钮只是多一步。
 */

type Tab = 'profile' | 'preferences'

const TABS: Array<{ value: Tab; label: AccountKey; href: '/profile' | '/preferences'; icon: typeof UserIcon }> = [
  { value: 'profile', label: 'tabProfile', href: '/profile', icon: UserIcon },
  { value: 'preferences', label: 'tabPreferences', href: '/preferences', icon: Settings01Icon },
]

export function AccountPage({ tab }: { tab: Tab }) {
  const t = useT(accountCopy)
  const isMobile = useIsMobile()

  return (
    <div className="@container flex w-full flex-col gap-5">
      <PageHeader title={t('title')} />

      <Tabs value={tab} orientation={isMobile ? 'horizontal' : 'vertical'} className="w-full gap-5 lg:gap-8">
        <div className={cn('min-w-0', isMobile ? 'w-full' : 'w-40 shrink-0')}>
          <TabsList
            className={cn(
              'h-auto bg-transparent p-0',
              isMobile ? 'w-max min-w-max justify-start gap-1' : 'w-full flex-col items-stretch gap-1',
            )}
          >
            {/* 页签就是路由：刷新、分享链接都落在同一个页签上。 */}
            {TABS.map((tb) => (
              <TabsTrigger
                key={tb.value}
                value={tb.value}
                render={<Link to={tb.href} />}
                className={cn(
                  'w-full justify-start gap-3 px-3 py-1.5 shadow-none',
                  tab === tb.value ? 'bg-muted!' : 'bg-transparent',
                )}
              >
                <HugeiconsIcon icon={tb.icon} strokeWidth={2} aria-hidden="true" />
                <span className="truncate">{t(tb.label)}</span>
              </TabsTrigger>
            ))}
          </TabsList>
        </div>

        <div className="min-w-0 flex-1">
          <TabsContent value="profile" className="mt-0">
            <ProfileTab />
          </TabsContent>
          <TabsContent value="preferences" className="mt-0">
            <PreferencesTab />
          </TabsContent>
        </div>
      </Tabs>
    </div>
  )
}

/* ---------- 个人资料 ---------- */

const SOURCE_KEY: Record<string, AccountKey> = {
  password: 'sourcePassword',
  sso: 'sourceSso',
  'proxy-header': 'sourceProxy',
  env: 'sourceToken',
}

function ProfileTab() {
  const t = useT(accountCopy)
  const sh = useT(shellCopy)
  const me = useMe()
  const avatar = useAvatar()
  const fileRef = useRef<HTMLInputElement>(null)
  const [avatarError, setAvatarError] = useState<string | null>(null)

  const name = me?.user?.username ?? sh('notSignedIn')
  const role = typeof me?.role === 'string' ? me.role : null
  const source = me?.user?.source ?? ''
  const canChange = source === 'password'

  async function pickAvatar(file: File | undefined) {
    if (!file) return
    setAvatarError(null)
    try {
      savePref({ avatar: await fileToAvatar(file) })
    } catch (e) {
      // 三种失败都有各自的说法：格式不对 / 打不开 / 处理完还是太大。
      const key =
        e instanceof AvatarError && e.message === 'type'
          ? 'avatarErrType'
          : e instanceof AvatarError && e.message === 'size'
            ? 'avatarErrSize'
            : 'avatarErrDecode'
      setAvatarError(sh(key))
    } finally {
      // 同一个文件连选两次也要触发 change。
      if (fileRef.current) fileRef.current.value = ''
    }
  }

  return (
    <div className="space-y-4">
      <SettingsCard
        title={t('cardProfile')}
        footer={
          avatarError ? (
            <Alert variant="destructive">
              <HugeiconsIcon icon={AlertCircleIcon} strokeWidth={2} className="size-4" />
              <AlertDescription>{avatarError}</AlertDescription>
            </Alert>
          ) : undefined
        }
      >
        <SettingField title={t('fieldAvatar')} hint={t('fieldAvatarDesc')}>
          <div className="flex grow flex-wrap items-center gap-2">
            <Avatar className="size-10 border">
              {avatar && <AvatarImage src={avatar} alt="" />}
              <AvatarFallback className="text-xs font-semibold">{name.slice(0, 2).toUpperCase()}</AvatarFallback>
            </Avatar>
            <Button type="button" variant="outline" size="sm" onClick={() => fileRef.current?.click()}>
              {sh('avatarChange')}
            </Button>
            {avatar && (
              <Button type="button" variant="outline" size="sm" onClick={() => savePref({ avatar: undefined })}>
                {sh('avatarRemove')}
              </Button>
            )}
            <input
              ref={fileRef}
              type="file"
              accept={ACCEPT}
              className="sr-only"
              tabIndex={-1}
              aria-label={sh('avatar')}
              onChange={(e) => void pickAvatar(e.target.files?.[0])}
            />
          </div>
        </SettingField>

        <SettingField title={t('fieldAccount')} hint={t('fieldAccountDesc')}>
          <span className="font-mono text-sm">{name}</span>
        </SettingField>

        <SettingField title={t('fieldRole')} hint={role && ROLE_HINT_KEY[role] ? sh(ROLE_HINT_KEY[role]) : undefined}>
          {role ? (
            <Badge size="sm" variant="secondary">{ROLE_KEY[role] ? sh(ROLE_KEY[role]) : role}</Badge>
          ) : (
            <span className="text-sm text-muted-foreground">—</span>
          )}
        </SettingField>

        <SettingField title={t('fieldSource')} last>
          <span className="text-sm">{SOURCE_KEY[source] ? t(SOURCE_KEY[source]) : source || '—'}</span>
        </SettingField>
      </SettingsCard>

      {canChange ? (
        <PasswordCard />
      ) : (
        <Alert>
          <HugeiconsIcon icon={AlertCircleIcon} strokeWidth={2} className="size-4" />
          <AlertDescription>{sh('pwSsoNotice')}</AlertDescription>
        </Alert>
      )}
    </div>
  )
}

function PasswordCard() {
  const t = useT(accountCopy)
  const sh = useT(shellCopy)
  const [current, setCurrent] = useState('')
  const [next, setNext] = useState('')
  const [confirm, setConfirm] = useState('')
  const [saving, setSaving] = useState(false)
  const [error, setError] = useState<string | null>(null)

  async function submit() {
    if (!current || !next) return setError(sh('pwErrRequired'))
    if (next.length < 8) return setError(sh('pwErrTooShort'))
    if (next !== confirm) return setError(sh('pwErrMismatch'))
    setSaving(true)
    setError(null)
    try {
      await api.changePassword({ current_password: current, new_password: next })
      setCurrent(''); setNext(''); setConfirm('')
      toast.success(sh('pwOk'))
    } catch (e) {
      setError((e as ApiError).message || sh('pwErrFailed'))
    } finally {
      setSaving(false)
    }
  }

  return (
    <SettingsCard
      title={t('cardPassword')}
      footer={
        <div className="flex w-full flex-wrap items-center gap-3">
          {error && (
            <Alert variant="destructive" className="w-full">
              <HugeiconsIcon icon={AlertCircleIcon} strokeWidth={2} className="size-4" />
              <AlertDescription>{error}</AlertDescription>
            </Alert>
          )}
          {/* 后端会踢掉这个账号的其他会话 —— 改密码就是因为怀疑别人拿到了它。 */}
          <span className="text-xs text-muted-foreground">{sh('pwOtherSessions')}</span>
          <Button className="ms-auto" size="sm" onClick={() => void submit()} disabled={saving}>
            <HugeiconsIcon icon={saving ? Loading03Icon : CheckmarkCircle02Icon} strokeWidth={2} className={cn('size-3.5', saving && 'animate-spin')} />
            {saving ? sh('pwSubmitting') : sh('pwSubmit')}
          </Button>
        </div>
      }
    >
      <SettingField title={sh('pwCurrent')} labelFor="cur-pw">
        <Input id="cur-pw" type="password" autoComplete="current-password" value={current} onChange={(e) => setCurrent(e.target.value)} disabled={saving} />
      </SettingField>
      <SettingField title={sh('pwNew')} description={sh('pwMin8')} labelFor="new-pw">
        <Input id="new-pw" type="password" autoComplete="new-password" value={next} onChange={(e) => setNext(e.target.value)} disabled={saving} />
      </SettingField>
      <SettingField title={sh('pwConfirm')} labelFor="new-pw2" last>
        <Input id="new-pw2" type="password" autoComplete="new-password" value={confirm} onChange={(e) => setConfirm(e.target.value)} disabled={saving} />
      </SettingField>
    </SettingsCard>
  )
}

/* ---------- 偏好设置 ---------- */

const PAGE_SIZES = [25, 50, 100] as const

/* `getPrefs()` 每次都从 localStorage 解析出一个新对象，直接当 useSyncExternalStore
   的快照会无限重渲染（React #185）。订阅的是一个版本号，prefs 在渲染里再读。 */
let prefsVersion = 0
function subscribePrefs(cb: () => void) {
  const h = () => { prefsVersion += 1; cb() }
  window.addEventListener(PREFS_EVENT, h)
  return () => window.removeEventListener(PREFS_EVENT, h)
}
function usePrefs() {
  useSyncExternalStore(subscribePrefs, () => prefsVersion, () => prefsVersion)
  return getPrefs()
}

function PreferencesTab() {
  const t = useT(accountCopy)
  const sh = useT(shellCopy)
  const lang = useLang()
  const prefs = usePrefs()
  const [theme, setTheme] = useState<ThemeMode>(() => getThemeMode())
  useEffect(() => {
    const sync = () => setTheme(getThemeMode())
    window.addEventListener('rst-theme-changed', sync)
    return () => window.removeEventListener('rst-theme-changed', sync)
  }, [])

  const columnIndices = Object.keys(prefs.columns ?? {}).filter((k) => k !== '__reset__').length

  return (
    <div className="space-y-4">
      <SettingsCard title={t('cardUi')}>
        <SettingField title={t('fieldLanguage')} hint={t('fieldLanguageDesc')}>
          <ToggleGroup
            multiple={false}
            value={[lang]}
            onValueChange={(v) => { if (v[0]) setLang(v[0] as Lang) }}
            variant="outline"
            size="sm"
            aria-label={t('fieldLanguage')}
          >
            <ToggleGroupItem value="zh">中文</ToggleGroupItem>
            <ToggleGroupItem value="en">English</ToggleGroupItem>
          </ToggleGroup>
        </SettingField>
        <SettingField title={t('fieldTheme')} last>
          <ToggleGroup
            multiple={false}
            value={[theme]}
            onValueChange={(v) => { if (v[0]) { setThemeMode(v[0] as ThemeMode); setTheme(v[0] as ThemeMode) } }}
            variant="outline"
            size="sm"
            aria-label={t('fieldTheme')}
          >
            <ToggleGroupItem value="light"><HugeiconsIcon icon={Sun01Icon} strokeWidth={2} className="size-3.5" aria-hidden="true" />{sh('themeLight')}</ToggleGroupItem>
            <ToggleGroupItem value="dark"><HugeiconsIcon icon={Moon02Icon} strokeWidth={2} className="size-3.5" aria-hidden="true" />{sh('themeDark')}</ToggleGroupItem>
            <ToggleGroupItem value="system"><HugeiconsIcon icon={ComputerIcon} strokeWidth={2} className="size-3.5" aria-hidden="true" />{t('themeSystem')}</ToggleGroupItem>
          </ToggleGroup>
        </SettingField>
      </SettingsCard>

      <SettingsCard
        title={t('cardQuery')}
        footer={<span className="text-xs text-muted-foreground">{t('savedHint')}</span>}
      >
        <SettingField title={t('fieldDefaultIndex')} hint={t('fieldDefaultIndexDesc')}>
          <IndexCombobox
            value={prefs.defaultIndex ?? ''}
            onChange={(v) => savePref({ defaultIndex: v || undefined })}
            allowAuto
            allowAll
            className="w-full"
          />
        </SettingField>
        <SettingField title={t('fieldPageSize')}>
          <Select
            value={String(prefs.pageSize ?? PAGE_SIZES[0])}
            onValueChange={(v) => { if (v) savePref({ pageSize: Number(v) }) }}
          >
            <SelectTrigger className="w-28" aria-label={t('fieldPageSize')}>
              <SelectValue />
            </SelectTrigger>
            <SelectContent>
              {PAGE_SIZES.map((n) => <SelectItem key={n} value={String(n)}>{n}</SelectItem>)}
            </SelectContent>
          </Select>
        </SettingField>
        <SettingField title={t('fieldColumns')} hint={t('fieldColumnsDesc')} last>
          <div className="flex items-center gap-2">
            <span className="text-sm text-muted-foreground">
              {columnIndices > 0 ? t('columnsCount', { n: columnIndices }) : t('columnsNone')}
            </span>
            {columnIndices > 0 && (
              <Button
                type="button"
                variant="outline"
                size="sm"
                onClick={() => { resetColumns(); toast.success(t('columnsResetOk')) }}
              >
                {t('columnsReset')}
              </Button>
            )}
          </div>
        </SettingField>
      </SettingsCard>
    </div>
  )
}
