import type { ReactNode } from "react"
import {
  Frame,
  FrameHeader,
  FramePanel,
  FrameTitle,
} from "@/components/reui/frame"

import { cn } from "@/lib/utils"
import { Separator } from "@/components/ui/separator"

/*
 * 全站的 KPI 指标卡。八个页面共用（基线巡检 / 字段字典 / 处置手册 / 产品激活 /
 * 平台体检 / 安全态势 / 运营报告 / 批量分诊），所以它长什么样就是这个产品的
 * 指标卡长什么样。
 *
 * 阶段 4 把结构换成了 pulse-helpdesk 的
 * `features/dashboard/components/ticket-metric-cards.tsx`：
 *
 *   之前  一张 Frame 内部切成 N 个格子，每格是「彩色圆角图标砖 + 小标签 +
 *         标题 + 提示 + text-xl 数值」。
 *   现在  N 张独立的 `Frame dense`，卡头是标题 + 一枚灰度图标，卡身是
 *         text-2xl 的数值、一条 Separator、两行说明。
 *
 * 换掉彩色图标砖是这次改动里最实的一处：那块砖自带径向渐变和投影，是全站唯一
 * 用饱和色块当装饰的地方，和模板那套无色相的灰阶撞得最厉害。改完之后指标卡和
 * 页面上别的卡片是同一种材质。
 *
 * 量出来、别改的几个数：卡之间 `gap-6`（比区块之间的 gap-5 大一档）；卡标题
 * `text-foreground/70` —— 要比同页正式卡片的标题弱一档，又不能弱到和正文说明
 * 同级；数值 `text-2xl font-medium tracking-tight`；`FrameHeader` 上那个
 * `flex-wrap` 是承重的，标题列是唯一能伸缩的子项，不给 wrap 的话窄屏下说明会
 * 被压成三行。
 */
export type StatCard = {
  /** Small line above the title: what this cell counts. */
  label: string
  title: string
  value: string
  /** Supporting line under the value. */
  hint?: string
  /** 可选：没有天然图标的指标（覆盖率、计数）不要为了卡头对齐去编一个。 */
  icon?: ReactNode
  /**
   * 这一格现在该不该被看到。不是装饰 —— 「严重+高危 > 0」、「基线/平台异常 > 0」
   * 这类条件就是运维要先看哪一格的信息。只给图标着色，不画色块：
   * 一整块色底会把卡片从模板那套无色相灰阶里拽出去，而一枚红图标已经够了。
   */
  tone?: 'destructive' | 'warning'
}

function CardItem({ card }: { card: StatCard }) {
  return (
    <Frame dense className="h-full min-w-0">
      <FrameHeader className="flex-row flex-wrap items-center justify-between gap-3 pb-[calc(var(--frame-panel-header-py)+2px)]">
        <FrameTitle className="text-sm font-medium text-foreground/70">
          {card.title}
        </FrameTitle>
        {card.icon ? (
          <div
            className={cn(
              '[&_svg]:size-4',
              card.tone === 'destructive'
                ? '[&_svg]:text-destructive'
                : card.tone === 'warning'
                  ? '[&_svg]:text-warning'
                  : '[&_svg]:text-muted-foreground',
            )}
          >
            {card.icon}
          </div>
        ) : null}
      </FrameHeader>
      <FramePanel className="flex flex-1 flex-col gap-2.5">
        <span className="text-2xl font-medium tracking-tight tabular-nums text-foreground">
          {card.value}
        </span>
        <Separator />
        {/* 两行说明，和模板的 description / comparison 两行对位。`label` 说这一格
            数的是什么，`hint` 是补充；没有 hint 时不占位，卡片自己收短。 */}
        <div className="space-y-1">
          <div className="text-xs text-muted-foreground">{card.label}</div>
          {card.hint ? (
            <div className="text-xs text-muted-foreground">{card.hint}</div>
          ) : null}
        </div>
      </FramePanel>
    </Frame>
  )
}

/*
 * Columns follow the number of cells. The block hard-coded a four-up grid,
 * which lands three cards as 2 + 1 the moment the row sits in anything
 * narrower than the full page — a lone cell under two reads as a fourth
 * metric that failed to load.
 */
const COLUMNS: Record<number, string> = {
  1: "",
  2: "@2xl:grid-cols-2",
  3: "@md:grid-cols-2 @xl:grid-cols-3",
  4: "@2xl:grid-cols-2 @4xl:grid-cols-4",
}

export function StatCards({ cards, className }: { cards: StatCard[]; className?: string }) {
  const columns = COLUMNS[Math.min(cards.length, 4)] ?? COLUMNS[4]
  return (
    /* `@container` 留在这里：列数用的是容器查询，而页根那层容器管的是整页宽度，
       这一排卡片自己也可能被放进更窄的一栏里。 */
    <div
      className={cn(
        "@container grid w-full auto-rows-fr items-stretch gap-6",
        columns,
        className,
      )}
    >
      {cards.map((card) => (
        <CardItem key={card.title} card={card} />
      ))}
    </div>
  )
}
