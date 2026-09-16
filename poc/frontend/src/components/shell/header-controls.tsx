/*
 * 顶栏右上角的三样：语言、明暗、头像（版式照 efferd dashboard-2 的右上角：两个
 * 图标按钮 + 一个圆头像）。
 *
 * 语言和明暗都是一键切换，不弹菜单——两档的东西用分段控件是浪费一次点击。
 * 明暗只在亮 / 暗之间切；「跟随系统」留在偏好设置页，切一次等于明确选了一档。
 * 头像点开只剩身份 / 个人资料 / 偏好设置 / 退出：语言主题已经在旁边了，菜单里
 * 不再重复。侧栏左下角原来的账号块（nav-user.tsx）随之删掉，位置让给帮助链接。
 */
import { useEffect, useState } from 'react'
import { Link } from '@tanstack/react-router'
import { HugeiconsIcon } from '@hugeicons/react'
import {
  LanguagesIcon, LogoutSquare01Icon, MoonStarIcon, Settings01Icon, Sun03Icon, UserIcon,
} from '@hugeicons/core-free-icons'

import { logout, useMe } from '@/lib/auth'
import { setLang, useLang, useT } from '@/lib/i18n'
import { getThemeMode, resolvedTheme, setThemeMode } from '@/lib/theme'
import { useAvatar } from '@/lib/useAvatar'
import { accountCopy } from '@/locales/account'
import { ROLE_KEY, shellCopy } from '@/locales/shell'
import { Avatar, AvatarFallback, AvatarImage } from '@/components/ui/avatar'
import { Button } from '@/components/ui/button'
import {
  DropdownMenu, DropdownMenuContent, DropdownMenuGroup, DropdownMenuItem,
  DropdownMenuLabel, DropdownMenuSeparator, DropdownMenuTrigger,
} from '@/components/ui/dropdown-menu'

function useResolvedTheme(): 'light' | 'dark' {
  const [mode, setMode] = useState(() => resolvedTheme(getThemeMode()))
  useEffect(() => {
    const sync = () => setMode(resolvedTheme(getThemeMode()))
    window.addEventListener('rst-theme-changed', sync)
    const mq = window.matchMedia('(prefers-color-scheme: dark)')
    mq.addEventListener('change', sync)
    return () => {
      window.removeEventListener('rst-theme-changed', sync)
      mq.removeEventListener('change', sync)
    }
  }, [])
  return mode
}

export function LanguageToggle() {
  const sh = useT(shellCopy)
  const lang = useLang()
  const next = lang === 'zh' ? 'en' : 'zh'
  const nextLabel = next === 'zh' ? '中文' : 'English'
  return (
    <Button
      variant="ghost"
      size="icon-sm"
      aria-label={sh('langSwitchTo', { lang: nextLabel })}
      title={sh('langSwitchTo', { lang: nextLabel })}
      onClick={() => setLang(next)}
    >
      <HugeiconsIcon icon={LanguagesIcon} strokeWidth={2} className="size-4" aria-hidden="true" />
    </Button>
  )
}

export function ThemeToggle() {
  const sh = useT(shellCopy)
  const current = useResolvedTheme()
  const next = current === 'dark' ? 'light' : 'dark'
  const label = sh('themeSwitchTo', { theme: next === 'dark' ? sh('themeDark') : sh('themeLight') })
  return (
    <Button variant="ghost" size="icon-sm" aria-label={label} title={label} onClick={() => setThemeMode(next)}>
      <HugeiconsIcon
        icon={current === 'dark' ? Sun03Icon : MoonStarIcon}
        strokeWidth={2}
        className="size-4"
        aria-hidden="true"
      />
    </Button>
  )
}

async function doLogout() {
  try {
    await logout()
  } finally {
    // Full reload to /login so all in-memory state (and the SPA's cached
    // /api/me) is dropped — the session cookie is already cleared server-side.
    window.location.assign('/v2/login')
  }
}

export function HeaderUser() {
  const t = useT(accountCopy)
  const sh = useT(shellCopy)
  const me = useMe()
  const avatar = useAvatar()
  const name = me?.user?.username ?? sh('notSignedIn')
  const role = typeof me?.role === 'string' ? (ROLE_KEY[me.role] ? sh(ROLE_KEY[me.role]) : me.role) : '—'
  const initials = name.slice(0, 2).toUpperCase()
  const showLogout = !!(me?.login_enabled && me.authenticated)

  return (
    <DropdownMenu>
      <DropdownMenuTrigger
        render={
          <Button
            variant="ghost"
            size="icon-sm"
            aria-label={t('menuOpen')}
            className="ml-1 rounded-full"
          />
        }
      >
        <Avatar className="size-7">
          {avatar && <AvatarImage src={avatar} alt="" />}
          <AvatarFallback className="text-10 font-semibold">{initials}</AvatarFallback>
        </Avatar>
      </DropdownMenuTrigger>
      <DropdownMenuContent side="bottom" align="end" sideOffset={8} className="w-56">
        <DropdownMenuGroup>
          {/* Base UI 1.7 里 GroupLabel 必须待在 Group 内，不然抛 #31。 */}
          <DropdownMenuLabel className="flex items-center gap-2.5 py-2">
            <Avatar className="size-8 rounded-md">
              {avatar && <AvatarImage src={avatar} alt="" className="rounded-md!" />}
              <AvatarFallback>{initials}</AvatarFallback>
            </Avatar>
            <div className="flex min-w-0 flex-col">
              <span className="truncate text-sm font-semibold text-foreground">{name}</span>
              <span className="truncate text-xs font-normal text-muted-foreground">{role}</span>
            </div>
          </DropdownMenuLabel>
          <DropdownMenuSeparator />
          <DropdownMenuItem render={<Link to="/profile" />}>
            <HugeiconsIcon icon={UserIcon} strokeWidth={2} aria-hidden="true" />
            {t('tabProfile')}
          </DropdownMenuItem>
          <DropdownMenuItem render={<Link to="/preferences" />}>
            <HugeiconsIcon icon={Settings01Icon} strokeWidth={2} aria-hidden="true" />
            {t('tabPreferences')}
          </DropdownMenuItem>
          {showLogout && (
            <>
              <DropdownMenuSeparator />
              <DropdownMenuItem onClick={() => void doLogout()}>
                <HugeiconsIcon icon={LogoutSquare01Icon} strokeWidth={2} aria-hidden="true" />
                {sh('logout')}
              </DropdownMenuItem>
            </>
          )}
        </DropdownMenuGroup>
      </DropdownMenuContent>
    </DropdownMenu>
  )
}
