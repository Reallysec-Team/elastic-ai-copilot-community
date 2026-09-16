import { useState } from 'react'
import { useLocation, useNavigate } from '@tanstack/react-router'
import { HugeiconsIcon } from '@hugeicons/react'
import {
  LanguagesIcon, Loading03Icon, LogInIcon, MoonStarIcon, Sun03Icon, ViewIcon,
  ViewOffSlashIcon,
} from '@hugeicons/core-free-icons'

import { login, LoginError } from '@/lib/auth'
import { setLang, useLang, useT } from '@/lib/i18n'
import { loginCopy } from '@/locales/login'
import { getThemeMode, resolvedTheme, setThemeMode } from '@/lib/theme'
import { Logo } from '@/components/Logo'
import { Frame, FramePanel, FrameTitle } from '@/components/reui/frame'
import { Alert, AlertDescription } from '@/components/reui/alert'
import { Button } from '@/components/ui/button'
import {
  Dialog, DialogContent, DialogHeader, DialogTitle,
} from '@/components/ui/dialog'
import { Field, FieldGroup, FieldLabel } from '@/components/ui/field'
import { Input } from '@/components/ui/input'
import {
  InputGroup, InputGroupAddon, InputGroupButton, InputGroupInput,
} from '@/components/ui/input-group'

/*
 * 登录页，版式照 `@reui/auth-4`：整屏三段（页眉 / 居中一张 Frame 卡 / 页脚），
 * 噪点背景，卡里是标志 + 标题 + 字段，「忘记密码」贴在密码标签右侧。
 * 上一版照 auth-16 把字段直接落在背景上；换回卡片是 2026-09-12 拍板的
 * 「手写区块统一换 ReUI block」，字段原语（Field / InputGroup）一个没动。
 *
 * auth-4 里有两块**没有照搬**，都是照搬就会说假话的：
 *   - Google / Apple / GitHub 三个第三方登录按钮：这个产品只有账号密码一条路，
 *     摆三个按不动的按钮不如不摆（真接了 SSO 再按 /api/me 的能力位加回来）。
 *   - 「Need an account? Sign up」：不提供自助注册，同一个槽位放的就是这件事本身。
 *
 * 保留的自有件：中英切换、主题切换、条款勾选闸、找回密码与法律文本弹窗；错误仍
 * 然内联在表单下面（这一屏在 AppShell 之外，Toaster 挂在 shell 里，到不了这里）。
 */


// Registered legal entity — not translated, and not part of the copy table for that reason.
const COPYRIGHT_HOLDER = '安徽斯普朗克信息技术有限公司'



export default function LoginPage() {
  const [username, setUsername] = useState('')
  const [password, setPassword] = useState('')
  const [showPassword, setShowPassword] = useState(false)
  const [isLoading, setIsLoading] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const lang = useLang()
  // 同意过一次就记住 —— 这台机器上的同一个人每天要登好几次，每次重勾一遍是噪音。
  const [resetOpen, setResetOpen] = useState(false)
  const [dark, setDark] = useState(() => resolvedTheme() === 'dark')
  const navigate = useNavigate()
  const location = useLocation()
  const t = useT(loginCopy)

  const toggleTheme = () => {
    const next = resolvedTheme(getThemeMode()) === 'dark' ? 'light' : 'dark'
    setThemeMode(next)
    setDark(next === 'dark')
  }

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault()
    if (!username || !password) {
      setError(t('validation'))
      return
    }
    setIsLoading(true)
    setError(null)
    try {
      await login(username, password)
      // Back to whatever the guard interrupted. `from` can only be set by an
      // in-app redirect, but validate it anyway: a value like `//evil.com` is a
      // protocol-relative URL the browser resolves off-site.
      const from = (location.state as { from?: string } | undefined)?.from
      const target = from && from.startsWith('/') && !from.startsWith('//') ? from : '/'
      /* `to` 是运行时拼出来的路径，给不了 TanStack 要的字面量类型；
         合法性上一行已经验过了。 */
      void navigate({ to: target as never, replace: true })
    } catch (err) {
      // The gateway distinguishes wrong-password from rate-limited; showing
      // its message is the difference between "try again" and "wait 5 minutes".
      setError((err instanceof LoginError && err.message) || t('failed'))
    } finally {
      setIsLoading(false)
    }
  }

  // 版式取 auth-20：素底、一张 26rem 的卡、标题区与表单区分开留白。
  // 页眉 / 页脚是本产品自己的（字标、语言 / 主题、版权行）。
  return (
    <div className="relative flex min-h-svh w-full flex-col overflow-hidden bg-background">
      <header className="relative z-10 flex items-center justify-between gap-4 px-6 py-5 sm:px-8 sm:py-6 lg:px-10">
        {/* The component, not public/wordmark.svg — the "RST" letters in it are
            filled with var(--t-fg), so they survive the dark theme. */}
        {/* 页眉只放字标；产品名在登录卡的标题里。 */}
        <Logo height={26} />
        <div className="flex items-center gap-1">
          <Button
            variant="ghost"
            size="icon-sm"
            aria-label={t('language')}
            className="text-muted-foreground hover:text-foreground"
            onClick={() => setLang(lang === 'zh' ? 'en' : 'zh')}
          >
            <HugeiconsIcon icon={LanguagesIcon} strokeWidth={2} className="size-4" />
          </Button>
          <Button
            variant="ghost"
            size="icon-sm"
            aria-label={dark ? 'light' : 'dark'}
            className="text-muted-foreground hover:text-foreground"
            onClick={toggleTheme}
          >
            {/* 同顶栏的一对图标：MoonIcon 太素，一眼看不出是主题开关。 */}
            <HugeiconsIcon icon={dark ? Sun03Icon : MoonStarIcon} strokeWidth={2} className="size-4" />
          </Button>
        </div>
      </header>

      <main className="relative z-10 flex flex-1 items-center justify-center px-4 py-6 sm:px-8 sm:py-10 lg:px-10">
        <div className="mx-auto flex w-full max-w-[26rem] flex-col gap-5">
          <Frame spacing="lg" className="w-full shadow-sm">
            <FramePanel className="flex flex-col gap-6 px-6 pt-8 pb-6 sm:px-8 sm:pt-9 sm:pb-8">
              <div className="flex flex-col items-center gap-4 text-center">
                {/* 同 PageHeader 的标题刻度（text-xl / medium）：登录卡是这个产品的
                    第一个「页面标题」，不该比里面任何一页的标题都大、都粗。 */}
                <FrameTitle className="text-xl leading-tight font-medium tracking-tight text-balance">
                  {t('title')}
                </FrameTitle>
              </div>

              <form className="flex flex-col gap-5" onSubmit={handleSubmit}>
                <FieldGroup className="gap-4">
                  <Field className="gap-2">
                    <FieldLabel htmlFor="username">{t('username')}</FieldLabel>
                    {/* `required` so an empty submit is caught by the browser as
                        well as by the check in handleSubmit. */}
                    <Input
                      id="username"
                      type="text"
                      required
                      autoComplete="username"
                      placeholder="admin"
                      value={username}
                      onChange={(e) => setUsername(e.target.value)}
                    />
                  </Field>

                  <Field className="gap-2">
                    <div className="flex items-center justify-between gap-3">
                      <FieldLabel htmlFor="password">{t('password')}</FieldLabel>
                      <Button
                        type="button"
                        variant="link"
                        className="h-auto p-0 text-xs font-normal text-muted-foreground hover:text-foreground"
                        onClick={() => setResetOpen(true)}
                      >
                        {t('forgot')}
                      </Button>
                    </div>
                    <InputGroup className="w-full">
                      <InputGroupInput
                        id="password"
                        type={showPassword ? 'text' : 'password'}
                        required
                        autoComplete="current-password"
                        placeholder="••••••••"
                        value={password}
                        onChange={(e) => setPassword(e.target.value)}
                      />
                      <InputGroupAddon align="inline-end">
                        <InputGroupButton
                          type="button"
                          size="icon-xs"
                          className="text-muted-foreground hover:text-foreground"
                          aria-label={showPassword ? 'hide' : 'show'}
                          aria-pressed={showPassword}
                          onClick={() => setShowPassword((v) => !v)}
                        >
                          <HugeiconsIcon
                            icon={showPassword ? ViewOffSlashIcon : ViewIcon}
                            strokeWidth={2}
                            aria-hidden="true"
                            className="size-4"
                          />
                        </InputGroupButton>
                      </InputGroupAddon>
                    </InputGroup>
                  </Field>
                </FieldGroup>

                {error && (
                  <Alert variant="destructive" role="alert">
                    <AlertDescription>{error}</AlertDescription>
                  </Alert>
                )}

                <Button type="submit" className="w-full" disabled={isLoading}>
                  <HugeiconsIcon
                    icon={isLoading ? Loading03Icon : LogInIcon}
                    strokeWidth={2}
                    className={isLoading ? 'size-4 animate-spin' : 'size-4'}
                  />
                  {t('submit')}
                </Button>
              </form>
            </FramePanel>
          </Frame>
        </div>
      </main>

      {/* auth-4 的页脚导航槽位 —— 换成法人实体版权行。 */}
      <footer className="relative z-10 flex flex-col items-center gap-6 px-6 py-8 text-xs text-muted-foreground sm:px-8 sm:py-10">
        Copyright © {new Date().getFullYear()} {COPYRIGHT_HOLDER}
      </footer>

      <Dialog open={resetOpen} onOpenChange={setResetOpen}>
        <DialogContent className="sm:max-w-lg">
          <DialogHeader>
            <DialogTitle>{t('resetTitle')}</DialogTitle>
          </DialogHeader>
          <div className="flex flex-col gap-3 px-6 pb-6 text-sm leading-relaxed text-muted-foreground">
            {(['resetBody1', 'resetBody2', 'resetBody3', 'resetBody4'] as const).map((k) => (
              <p key={k}>{t(k)}</p>
            ))}
          </div>
        </DialogContent>
      </Dialog>
    </div>
  )
}
