import { Link, useLocation } from '@tanstack/react-router'

import { useT } from '@/lib/i18n'
import { shellCopy } from '@/locales/shell'
import { NAV_TABS } from '@/components/shell/data'
import { cn } from '@/lib/utils'

/*
 * 页面顶部的横向标签栏 —— 侧栏减负的另一半。
 *
 * 样式跟全站已有的页内页签**同一档**：知识库、基线巡检、投递与通知用的都是
 * `TabsList` 的默认档（灰底药丸组，选中项翻成背景色 + 一点投影），所以这里照抄那
 * 一档的类，而不是 `variant="line"` 的下划线 —— 同一个产品里两种页签长相是最容易
 * 让人以为「这是两个不同的东西」的地方。
 *
 * 但**不是** `@/components/ui/tabs`：那套是 base-ui 的 Tabs，页签是同一页里的几块
 * 内容。这里每个标签是一条独立路由，套上去要写成「受控 value + render={<Link/>}」，
 * 实测直接 React error #185（Maximum update depth exceeded）—— 受控值和 base-ui 自
 * 己的激活状态互相打，整族页面白屏。
 *
 * 一排链接本来也不需要 Tabs 的键盘漫游和面板管理：`<nav>` + 当前项 `aria-current`
 * 就是它的语义。类是从 `ui/tabs.tsx` 默认档逐条抄过来的，视觉上认不出区别。
 *
 * 挂在 PageHeader 里而不是外壳里：桌面端标题被 portal 进顶栏了，正文的第一个元素
 * 就是这条栏；手机端标题留在正文，标签自然排在标题下面。挂在外壳的 <Outlet> 上面
 * 的话，手机端就成了「标签在上、标题在下」。
 *
 * 不属于任何族的页面（智能查询、分析记录、字段字典……）渲染 null，一行不占。
 */
export function PageTabs() {
  const t = useT(shellCopy)
  const { pathname } = useLocation()
  const family = NAV_TABS.find((g) => g.items.some((i) => i.href === pathname))
  if (!family) return null

  return (
    <nav
      aria-label={t('inPageNav')}
      data-slot="tabs-list"
      // 标签多了在窄屏上排不下：整条横向滚动，不换行 —— 换行会把标题和正文之间
      // 撑开两行，而这条栏本身不是内容。
      className="grid h-8 w-fit max-w-full grid-flow-col [grid-auto-columns:minmax(max-content,1fr)] items-center justify-center overflow-x-auto rounded-lg bg-muted p-[3px] text-muted-foreground"
    >
      {family.items.map((item) => {
        const active = item.href === pathname
        return (
          <Link
            key={item.href}
            to={item.href as never}
            aria-current={active ? 'page' : undefined}
            data-active={active ? '' : undefined}
            className={cn(
              'relative inline-flex h-[calc(100%-1px)] shrink-0 items-center justify-center gap-1.5 rounded-md border border-transparent px-2 py-0.5 text-sm font-medium whitespace-nowrap transition-all',
              'focus-visible:border-ring focus-visible:ring-[3px] focus-visible:ring-ring/50 focus-visible:outline-1 focus-visible:outline-ring',
              active
                ? 'bg-background text-foreground shadow-sm dark:border-input dark:bg-input/30'
                : 'text-foreground/60 hover:text-foreground dark:text-muted-foreground dark:hover:text-foreground',
            )}
          >
            {t(item.label)}
          </Link>
        )
      })}
    </nav>
  )
}
