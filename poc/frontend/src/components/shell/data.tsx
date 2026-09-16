import { HugeiconsIcon } from '@hugeicons/react'
import { Activity02Icon, AiBrain01Icon, Analytics01Icon, BellRingIcon, BookOpen02Icon, CheckListIcon, DashboardSquare01Icon, LicenseIcon, ScrollTextIcon, Search02Icon, Sent02Icon, Settings01Icon, ShieldAlertIcon, ServerStack01Icon, Table01Icon, TaskDone02Icon, UserGroupIcon, WorkHistoryIcon } from '@hugeicons/core-free-icons'
import type { ReactNode } from 'react'

import type { ShellKey } from '@/locales/shell'

/*
 * Icons are picked by measured extent, not by name. hugeicons draws each glyph
 * to its own bounds inside the 24 box, and the `size-4` the rail applies scales
 * the box, not the art — so a glyph drawn 10 units tall (`TrendingUpIcon`) sits
 * beside one drawn 21 units tall (`CheckListIcon`) and the rail reads as
 * two icon sizes. Everything here measures 19–21 on both axes. Before swapping
 * one in, measure it the same way rather than trusting that two names from the
 * same set are drawn alike.
 *
 * Extent is not the whole story: stroke density counts too. Baseline used to
 * carry `ClipboardCheckIcon`, which measures in range but stacks a frame, a
 * clip and a tick inside 18px — at rail size it reads a weight heavier than
 * every icon beside it, even though all 18 are drawn at `strokeWidth={2}`.
 * `CheckListIcon` is the same height with one layer fewer.
 *
 * Navigation data, in ReUI atlas-admin's shape (`components/shell/data.tsx`):
 * flat items carrying their own icon element, grouped, plus a secondary set
 * pinned to the bottom of the rail.
 *
 * atlas ships one main group plus a "resources" group; the shape allows any
 * number, so this product's four groups render through the same component. The
 * secondary set is atlas's Team / Settings / Help slot — here it holds the
 * administrative destination, which is the same job: something an operator
 * visits occasionally, not the one they work in.
 *
 * 侧栏原来有 16 条，一屏装不下也读不完。现在**两层**：侧栏只放「一天要开几次」
 * 的入口，同一件事的其它面搬进页面顶部的横向标签（见 NAV_TABS 与 page-tabs.tsx，
 * 版式照「投递与通知」页里那三个页签）。路由一条没动，每个标签仍是自己的 URL ——
 * 深链、命令面板、e2e 都不用跟着改。
 */

export type NavItem = {
  id: string
  /** 文案键，不是文案本身。渲染的地方 t(item.label) —— 导航是全站唯一一处
      「同一个名字在四个组件里出现」的地方，存成中文就得翻四遍。 */
  label: ShellKey
  href: string
  icon: ReactNode
  /** Exact match only. Used for "/" so every route does not light it up. */
  exact?: boolean
}

export type NavGroup = { id: string; label?: ShellKey; items: NavItem[] }

/* 既进侧栏又是标签族的族长，两处引用同一个对象 —— 名字和图标只写一次。 */
const POSTURE: NavItem = { id: 'posture', label: 'navPosture', href: '/posture', icon: <HugeiconsIcon icon={DashboardSquare01Icon} strokeWidth={2} aria-hidden="true" /> }
const SETTINGS: NavItem = { id: 'settings', label: 'navSettings', href: '/settings', icon: <HugeiconsIcon icon={Settings01Icon} strokeWidth={2} aria-hidden="true" /> }
const PLATFORM: NavItem = { id: 'platform', label: 'navPlatform', href: '/platform', icon: <HugeiconsIcon icon={Activity02Icon} strokeWidth={2} aria-hidden="true" /> }

export const NAV_GROUPS: NavGroup[] = [
  {
    /*
     * 一整条值班动线，从上到下就是干活的顺序：先看此刻在烧什么（安全态势）→
     * 追一条具体的问下去（智能查询）→ 回看查过什么（分析记录）→ 一批一批地清
     * （批量分诊）→ 把结论固化成规则（检测规则）。
     *
     * 智能查询和分析记录原来单独占一个无标题组，摆在最上面。它们确实是最常开的
     * 两页，但「最常开」不等于「自成一类」—— 摆在外面反而看不出它们和告警是同
     * 一件事的两步。
     */
    id: 'alerts',
    label: 'groupOps',
    items: [
      POSTURE,
      { id: 'chat', label: 'navChat', href: '/', icon: <HugeiconsIcon icon={Search02Icon} strokeWidth={2} aria-hidden="true" />, exact: true },
      { id: 'analysis', label: 'navAnalysis', href: '/analysis', icon: <HugeiconsIcon icon={WorkHistoryIcon} strokeWidth={2} aria-hidden="true" /> },
      { id: 'triage', label: 'navTriage', href: '/triage', icon: <HugeiconsIcon icon={TaskDone02Icon} strokeWidth={2} aria-hidden="true" /> },
      { id: 'rules', label: 'navRules', href: '/detection-rules', icon: <HugeiconsIcon icon={ShieldAlertIcon} strokeWidth={2} aria-hidden="true" /> },
    ],
  },
  {
    // 「数据」和「合规」原来是两个组，各剩两条和一条 —— 一两条的组是噪音，而且
    // 这三页本来就是同一类东西：**不是今天要处置的事，是处置时要查的依据**。
    id: 'reference',
    label: 'groupReference',
    items: [
      { id: 'fields', label: 'navFields', href: '/field-dictionary', icon: <HugeiconsIcon icon={Table01Icon} strokeWidth={2} aria-hidden="true" /> },
      { id: 'kb', label: 'navKb', href: '/knowledge-base', icon: <HugeiconsIcon icon={BookOpen02Icon} strokeWidth={2} aria-hidden="true" /> },
      { id: 'assets', label: 'navAssets', href: '/asset-identity', icon: <HugeiconsIcon icon={ServerStack01Icon} strokeWidth={2} aria-hidden="true" /> },
      { id: 'baseline', label: 'navBaseline', href: '/baseline', icon: <HugeiconsIcon icon={CheckListIcon} strokeWidth={2} aria-hidden="true" /> },
    ],
  },
]

/* 平台健康在上、系统设置在下：前者是每周会开的（体检、审计、通道），后者是装完
   基本不动的。 */
export const NAV_SECONDARY: NavItem[] = [PLATFORM, SETTINGS]

/*
 * 页面顶部的横向标签族。族里第一条是族长（侧栏上露出来的那条），点进去之后整族
 * 都在顶上排开。
 *
 * 分族的依据是「同一件事的不同面」，不是「功能相近」：
 *   安全态势   值班要看的三面 —— 此刻在烧什么 / 逐条处置 / 一段时间的结论。
 *   系统设置   这套系统本身怎么配 —— 接哪个 ES、谁能进来、模型怎么调、升到哪版、
 *              授权到哪天。
 *   平台健康   这台网关跑得怎么样，以及东西怎么发出去。
 *
 * 判据是「改一次要重启容器的进配置文件，客户自己会改第二次的进界面」；进了界面
 * 之后再按上面三族分。
 */
export const NAV_TABS: NavGroup[] = [
  {
    id: 'posture',
    items: [
      POSTURE,
      { id: 'alerts', label: 'navAlerts', href: '/alerts', icon: <HugeiconsIcon icon={BellRingIcon} strokeWidth={2} aria-hidden="true" /> },
      { id: 'reports', label: 'navReports', href: '/reports', icon: <HugeiconsIcon icon={Analytics01Icon} strokeWidth={2} aria-hidden="true" /> },
    ],
  },
  {
    id: 'settings',
    items: [
      SETTINGS,
      { id: 'users', label: 'navUsers', href: '/users', icon: <HugeiconsIcon icon={UserGroupIcon} strokeWidth={2} aria-hidden="true" /> },
      { id: 'ai', label: 'navAi', href: '/ai-settings', icon: <HugeiconsIcon icon={AiBrain01Icon} strokeWidth={2} aria-hidden="true" /> },
      { id: 'license', label: 'navLicense', href: '/license', icon: <HugeiconsIcon icon={LicenseIcon} strokeWidth={2} aria-hidden="true" /> },
    ],
  },
  {
    id: 'platform',
    items: [
      PLATFORM,
      { id: 'audit', label: 'navAudit', href: '/audit', icon: <HugeiconsIcon icon={ScrollTextIcon} strokeWidth={2} aria-hidden="true" /> },
      { id: 'notify', label: 'navNotify', href: '/notify', icon: <HugeiconsIcon icon={Sent02Icon} strokeWidth={2} aria-hidden="true" /> },
    ],
  },
]

/*
 * Every destination the shell knows about —— 命令面板和面包屑都读这份。
 * 标签族里的目的地也要在册：它们不在侧栏上，⌘K 就是找到它们最快的路。
 * 族长同时出现在两处，按 href 去重。
 */
export const ALL_NAV: NavItem[] = [
  ...NAV_GROUPS.flatMap((g) => g.items),
  ...NAV_SECONDARY,
  ...NAV_TABS.flatMap((g) => g.items),
].filter((item, i, all) => all.findIndex((o) => o.href === item.href) === i)
