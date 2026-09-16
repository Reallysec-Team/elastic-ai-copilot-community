import {
  Sidebar, SidebarContent, SidebarFooter, SidebarHeader,
} from '@/components/ui/sidebar'

import { NavMain } from './nav-main'
import { NavSecondary } from './nav-secondary'
import { NavHelp } from './nav-help'
import { SearchForm } from './search-form'
import { TrialQuotaMeter } from './trial-quota-meter'

/*
 * 侧栏，几何和插槽照 pulse-helpdesk 的 `features/app-shell/components/app-sidebar`：
 * 顶栏横贯全宽之后，侧栏从视口顶部下移到顶栏下沿（`top-(--header-height)` +
 * 相应减掉的高度），并且不再是深色 —— `--sidebar` 在 AppShell 上被指到内容区的
 * 底色，两列靠 `border-r` 分开。
 *
 * 品牌行删掉了：标志和产品名现在在顶栏里，那才是横贯全宽的那条。侧栏第一格
 * 因此回到模板的样子 —— 搜索框（命令面板入口）+ 查询历史。
 *
 * 插槽和内容没动：
 *   header   SearchForm（命令面板触发器 + 历史抽屉按钮）
 *   content  NavMain（四个业务分组）· NavSecondary（管理）· mt-auto 额度表
 *
 *   footer   NavHelp（帮助中心 / 文档两行占位链接）
 *
 * 账号块曾搬去右上角过一阵，现在按模板（app-shell-1 的 NavUser）收回左下角，
 * 顶栏右侧空出来。
 */
export function AppSidebar() {
  return (
    <Sidebar
      collapsible="icon"
      className="top-(--header-height) h-[calc(100svh-var(--header-height))]!"
    >
      <SidebarHeader className="flex flex-row items-center px-2 in-data-[state=collapsed]:flex-col in-data-[state=collapsed]:items-start in-data-[state=collapsed]:justify-center">
        <div className="w-full flex-1 pt-2">
          <SearchForm />
        </div>
      </SidebarHeader>

      <SidebarContent className="gap-2 px-2">
        <NavMain />
        <NavSecondary />

        <div className="mt-auto">
          <TrialQuotaMeter />
        </div>
      </SidebarContent>

      {/* 账号块搬去了顶栏右上角（header-controls.tsx）；这里照 efferd dashboard-2
          的左下角放帮助中心 / 文档两行。额度表不动，仍在它上面。 */}
      <SidebarFooter className="px-2 pb-2">
        <NavHelp />
      </SidebarFooter>
    </Sidebar>
  )
}
