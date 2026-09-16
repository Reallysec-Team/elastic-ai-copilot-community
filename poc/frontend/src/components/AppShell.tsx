import { Link, Outlet, useLocation } from '@tanstack/react-router'
import { useEffect, useState } from 'react'
import type { CSSProperties } from 'react'
import { HugeiconsIcon } from '@hugeicons/react'
import { ArrowRight01Icon } from '@hugeicons/core-free-icons'

import { api, LICENSE_BLOCKED_EVENT, type LicenseBlockedDetail } from '@/lib/api'
import { syncHistoryFromServer } from '@/lib/history'
import { useT } from '@/lib/i18n'
import { syncPrefsFromServer } from '@/lib/prefs'
import { isSyncDegraded, SYNC_HEALTH_EVENT, syncWarning } from '@/lib/syncHealth'
import { cn } from '@/lib/utils'
import { CommandPalette } from '@/components/CommandPalette'
import { ErrorBoundary } from '@/components/ErrorBoundary'
import { Logo } from '@/components/Logo'
import { HistoryDrawer } from '@/components/HistoryDrawer'
import { EsSetupDialog } from '@/components/settings/EsSetupDialog'
import { AppSidebar } from '@/components/shell/app-sidebar'
import { TopProgressBar } from '@/components/shell/top-progress-bar'
import { Badge } from '@/components/reui/badge'
import { Button } from '@/components/ui/button'
import {
  SidebarInset, SidebarProvider, SidebarTrigger, useSidebar,
} from '@/components/ui/sidebar'
import { Toaster } from '@/components/ui/sonner'
import { shellCopy } from '@/locales/shell'
import { HeaderUser, LanguageToggle, ThemeToggle } from '@/components/shell/header-controls'

/*
 * 应用外壳。骨架照 pulse-helpdesk 的 `features/app-shell`：
 * **顶栏横贯全宽、侧栏挂在它下面**，而不是原来那种「侧栏通高、顶栏只压着内容列」。
 *
 *   SidebarProvider(flex-col)
 *     └ header (sticky, w-full, --header-height 50px) —— 右侧是账号 / 主题 / 语言
 *     └ div(flex)
 *         ├ AppSidebar (fixed, top-(--header-height))
 *         └ SidebarInset
 *
 * 一起换掉的是配色：导航栏从深色（一整套写死的 zinc-900）变成**浅色**，
 * `--sidebar` 直接取内容区的底色，选中态用 primary 混 5%。这消掉了三样东西：
 *   - 那套绑死 `data-slot` 内部命名的 `[&_[data-slot=sidebar-menu-button]…]` 状态类；
 *   - 移动端把 token 抄到 `<body>` 上的 `useMobileBodyTheme()`（Sheet 是 portal
 *     出去的，够不到 provider 的 CSS 变量）—— 浅色之后 Sheet 本来就对；
 *   - `[&_[data-slot=sidebar-inner]]:bg-zinc-900` 那道绕过 token 的兜底。
 *
 * 保留的本产品自有件：license 横幅、ES 未配置引导、离线同步提示、命令面板、
 * 历史抽屉、额度表。顶栏本身只放产品身份和同步状态：页标题和页面操作曾经
 * portal 到这里来，现在画回正文（见 page-header）。
 */

/* 贴在导航栏外沿的折叠把手。`top` 从顶栏下沿起算（顶栏现在横贯全宽，把手不能
   再按整个视口居中，否则会压到顶栏上）。两小段刻度取 `bg-border` —— 它就长在
   分隔线上，取线本身的颜色才不像是把线戳断了。 */
function SidebarRailToggle() {
  const t = useT(shellCopy)
  const { state, toggleSidebar } = useSidebar()
  const isExpanded = state === 'expanded'
  return (
    <button
      type="button"
      aria-label={isExpanded ? t('collapseNav') : t('expandNav')}
      onClick={toggleSidebar}
      style={{ left: isExpanded ? 'var(--sidebar-width)' : 'var(--sidebar-width-icon)' }}
      className={cn(
        // 只在桌面：md 以下没有停靠的 sidebar 可以变宽，把手会浮在页面上变成
        // 一个多余的 tab 停留点。
        'group/rail fixed z-30 hidden h-12 w-7 cursor-pointer items-center pl-2 outline-none md:flex',
        'top-[calc(var(--header-height)+50%)] -translate-y-1/2',
        'focus-visible:rounded-sm focus-visible:ring-2 focus-visible:ring-ring focus-visible:ring-offset-1',
        'transition-[left] duration-200 ease-linear',
      )}
    >
      <span className="flex flex-col items-center">
        <span
          aria-hidden="true"
          className={cn(
            'block h-2 w-0.5 rounded-t-full bg-border origin-bottom transition-all duration-100 ease-linear',
            isExpanded
              ? 'group-hover/rail:rotate-40 group-hover/rail:bg-foreground/50'
              : 'group-hover/rail:-rotate-40 group-hover/rail:bg-foreground/50',
          )}
        />
        <span
          aria-hidden="true"
          className={cn(
            'block h-2 w-0.5 rounded-b-full bg-border origin-top transition-all duration-100 ease-linear',
            isExpanded
              ? 'group-hover/rail:-rotate-40 group-hover/rail:bg-foreground/50'
              : 'group-hover/rail:rotate-40 group-hover/rail:bg-foreground/50',
          )}
        />
      </span>
      <span
        className={cn(
          'absolute left-full -ml-2 rounded-md border border-border bg-foreground px-2 py-0.5 text-11 font-medium whitespace-nowrap text-background shadow-xs shadow-black/5',
          'pointer-events-none -translate-x-0.5 opacity-0 transition-all duration-200 ease-out',
          'group-hover/rail:translate-x-0 group-hover/rail:opacity-100',
        )}
      >
        {isExpanded ? t('collapse') : t('expand')}
      </span>
    </button>
  )
}

export function AppShell() {
  const t = useT(shellCopy)
  const { pathname } = useLocation()

  useEffect(() => {
    // Pull cross-device history + UI prefs from the server into the local cache.
    void syncHistoryFromServer()
    void syncPrefsFromServer()
  }, [])

  return (
    <SidebarProvider
      className={cn(
        'flex flex-col',
        // 浅色导航栏：底色就是内容区的底色，两列靠 sidebar 的 `border-r` 分开；
        // 选中行是 primary 混 5% 的一层薄底，不是另一套灰阶。
        '[--sidebar:var(--color-background)]',
        '[--sidebar-accent:color-mix(in_oklab,var(--color-primary)_5%,transparent)]',
        '[--sidebar-accent-foreground:var(--color-primary)]',
      )}
      style={{
        '--sidebar-width': '260px',
        '--sidebar-width-icon': '62px',
        '--header-height': '50px',
      } as CSSProperties}
    >
      {/* Outside the sidebar and the inset: the bar is fixed to the viewport
          and reports on the app, not on one column. */}
      <TopProgressBar />

      {/* 底边线画在 --header-height 里面（box-border）：原来 border-b 加在外层，
          顶栏实际 51px 而变量说 50px，凡是按变量算高度的页（智能查询）就多出
          1px 的整页滚动条，和聊天区自己的滚动条叠成两条。 */}
      <header className="sticky top-0 z-50 flex h-(--header-height) w-full items-center border-b bg-background">
        <div className="flex h-full w-full items-center gap-2 px-4">
          <SidebarTrigger className="-ml-1 md:hidden" aria-label={t('menu')} />
          {/* 标志在每个宽度都在。顶栏横贯全宽之后它就是产品身份的锚点，侧栏
              里那份删掉了 —— 一个 aria-label 出现两次，选择器会挑到哪个说不准。

              字标本身只画「RST」，产品名要另外写一行。这里曾经放的是当前页的
              标题（portal 进来的），于是产品名没地方待 —— 而当前在哪一页，左边
              导航栏的高亮已经说过一遍了。 */}
          <Link
            to="/"
            aria-label="RST · Elastic AI Copilot"
            className="-mx-0.5 flex min-w-0 shrink items-center gap-2 rounded-md outline-none transition-opacity hover:opacity-90 focus-visible:ring-2 focus-visible:ring-ring"
          >
            <Logo height={24} />
            {/* 窄屏收起：手机端顶栏还要放侧栏开关，字标已经够认出是哪个产品。 */}
            <span
              aria-hidden="true"
              className="hidden truncate text-13 leading-none font-medium tracking-tight text-muted-foreground sm:inline"
            >
              Elastic AI Copilot
            </span>
          </Link>

          {/* 右上角照 efferd dashboard-2：两个图标按钮（语言、明暗）+ 圆头像。
              同步告警那枚只在出事时出现的徽标排在它们前面。 */}
          <div className="ml-auto flex shrink-0 items-center gap-1">
            <SyncHealthChip />
            <LanguageToggle />
            <ThemeToggle />
            <HeaderUser />
          </div>
        </div>
      </header>

      <div className="flex min-w-0 flex-1">
        <AppSidebar />
        <SidebarRailToggle />

        {/* `min-w-0` 传进来而不是改 CLI 拥有的 `ui/sidebar.tsx`：flex 子项默认
            `min-width:auto`，宽表格会把内容列撑到比栏还宽，整页横滚。给回宽度
            控制权之后，表格在自己的滚动区里滚。 */}
        <SidebarInset className="min-w-0">
          <div className="flex min-w-0 flex-1 flex-col gap-4 p-4">
            <LicenseBlockedBanner />
            <EsUnconfiguredBanner />
            {/* The boundary sits HERE, around the outlet, not around the router.
                A fallback replaces its children, so a boundary up there blanks
                the whole shell for the length of a chunk fetch.

                包在外面的 `Suspense` 拆了：路由器自己管每条路由的 chunk 等待（见
                router.tsx 里的 `defaultPendingComponent`，同样是 null：顶部进度条
                已经在报这段等待，空列中间闪 150ms 的 loader 只像卡顿）。 */}
            <ErrorBoundary resetKey={pathname}>
              <Outlet />
            </ErrorBoundary>
          </div>
        </SidebarInset>
      </div>

      <HistoryDrawer />
      <CommandPalette />
      {/* roster mounts this at the router root; here the shell is the one place
          every signed-in screen passes through. */}
      <Toaster position="bottom-center" />
    </SidebarProvider>
  )
}

/*
 * License hard-fail notice, rendered in the content area — at the feature the
 * operator was trying to use, not in the nav. Fires when any /api/* call is
 * 403'd by the license gate (invalid / expired / revoked / heartbeat_lost).
 * The activation page carries the full explanation; this is the pointer to it.
 */
function LicenseBlockedBanner() {
  const t = useT(shellCopy)
  const loc = useLocation()
  const [blocked, setBlocked] = useState<LicenseBlockedDetail | null>(null)

  useEffect(() => {
    const h = (e: Event) => setBlocked((e as CustomEvent<LicenseBlockedDetail>).detail)
    window.addEventListener(LICENSE_BLOCKED_EVENT, h)
    return () => window.removeEventListener(LICENSE_BLOCKED_EVENT, h)
  }, [])

  // A fresh page gets a fresh chance to succeed; the banner returns if it 403s again.
  useEffect(() => {
    // eslint-disable-next-line react-hooks/set-state-in-effect -- clear on route change
    setBlocked(null)
  }, [loc.pathname])

  if (!blocked) return null
  return (
    <div
      role="alert"
      className="flex flex-wrap items-center gap-3 rounded-lg border border-destructive/30 bg-destructive/5 px-4 py-3"
    >
      <span className="block size-1.5 shrink-0 rounded-full bg-destructive" aria-hidden="true" />
      <p className="flex-1 text-13 leading-[1.6] text-destructive">{blocked.detail}</p>
      <Button variant="outline" size="sm" render={<Link to="/license" />}>
        {t('goActivate')}
        <HugeiconsIcon icon={ArrowRight01Icon} strokeWidth={2} className="size-3" />
      </Button>
    </div>
  )
}

/*
 * 首次安装引导。ES 连不上时，产品里几乎每个页面都会空着或报错，而原因只有一个
 * 且只有一个地方能改 —— 与其让客户挨个页面猜，不如在壳子上直接说这一句并给出
 * 入口。`/readyz` 免鉴权免 license 闸，所以刚装完、还没激活的机器也答得出来。
 *
 * 只探一次：这是「装完还没配」的一次性状态，不是需要盯着的运行指标；配完保存
 * 后设置页会自己刷新，横幅随下一次进页面消失。
 */
function EsUnconfiguredBanner() {
  const t = useT(shellCopy)
  const loc = useLocation()
  const [notReady, setNotReady] = useState(false)
  /* 从没配过 = 新装的机器 → 直接弹配置框，那是使用前的必答题。
     配过但此刻不通 → 只挂横幅：客户在弹框里也修不好 ES，却会被挡住去激活页。 */
  const [setupOpen, setSetupOpen] = useState(false)
  const [dismissed, setDismissed] = useState(false)

  useEffect(() => {
    let alive = true
    void api
      .ready()
      .then((r) => {
        if (!alive) return
        setNotReady(!r.ready)
        setSetupOpen(!r.ready && !r.configured)
      })
      /* `/readyz` 这个请求本身失败 = 网关没起来，不是 ES 连不上；下面那条横幅只讲
         后者，套上去会把人指去改集群地址。这里只吞掉这个 rejection（不加 catch 会
         是一条未处理的 Promise 拒绝），什么都不显示。 */
      .catch(() => {})
    return () => {
      alive = false
    }
  }, [])

  if (setupOpen && !dismissed) {
    return (
      <EsSetupDialog
        open
        onClose={() => {
          setSetupOpen(false)
          setDismissed(true)
        }}
      />
    )
  }

  // 设置页上不显示 —— 人已经站在能修的地方了，再挂一条横幅只是占地方。
  if (!notReady || loc.pathname.startsWith('/settings')) return null
  return (
    <div
      role="alert"
      className="flex flex-wrap items-center gap-3 rounded-lg border border-warning/30 bg-warning/5 px-4 py-3"
    >
      <span className="block size-1.5 shrink-0 rounded-full bg-warning" aria-hidden="true" />
      <p className="flex-1 text-13 leading-[1.6] text-warning-foreground">{t('esNotReady')}</p>
      <Button variant="outline" size="sm" render={<Link to="/settings" />}>
        {t('goConfigure')}
        <HugeiconsIcon icon={ArrowRight01Icon} strokeWidth={2} className="size-3" />
      </Button>
    </div>
  )
}

/* Offline-sync degradation. Stays in the header rather than moving to the rail
 * with the quota meter: it is a transient condition about the request you just
 * made, not a standing budget. */
function SyncHealthChip() {
  const t = useT(shellCopy)
  const [degraded, setDegraded] = useState(isSyncDegraded())
  useEffect(() => {
    const h = () => setDegraded(isSyncDegraded())
    window.addEventListener(SYNC_HEALTH_EVENT, h)
    return () => window.removeEventListener(SYNC_HEALTH_EVENT, h)
  }, [])
  if (!degraded) return null
  return (
    <Badge
      variant="warning-light"
      className="hidden sm:inline-flex"
      title={syncWarning(t('syncScope'))}
    >
      <span className="block size-1.5 rounded-full bg-current" aria-hidden="true" />
      {t('notSynced')}
    </Badge>
  )
}
