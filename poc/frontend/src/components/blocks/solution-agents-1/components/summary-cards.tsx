import type { ReactNode } from 'react'

import { Frame, FramePanel } from '@/components/reui/frame'
import { cn } from '@/lib/utils'
import { Item, ItemMedia } from '@/components/ui/item'

/*
 * `@reui/solution-agents-1` 第一行的四张摘要卡（它自己是从 card-3 抄的）：一张 Frame
 * 切成四格，每格一个带色的图标盒 + 标题 + 一句说明。模板里数据写死在 data.tsx，
 * 这里改成 props；标题可以是链接（Link render），也可以是纯文字。
 */

export interface SummaryCardData {
  id: string
  title: ReactNode
  description: ReactNode
  icon: ReactNode
  /** 图标盒底色，如 `bg-primary` `bg-destructive` `bg-success` `bg-warning` */
  iconBg: string
}

function CardItem({ card }: { card: SummaryCardData }) {
  return (
    <FramePanel>
      <Item
        className={cn(
          'p-0',
          'mb-3.5 flex size-9 items-center justify-center border-2 border-background shadow-[0_1px_3px_0_rgba(0,0,0,0.14)] dark:border [&_svg]:size-4.5 [&_svg]:text-white',
          card.iconBg,
        )}
      >
        <ItemMedia variant="icon" className="size-auto">
          {card.icon}
        </ItemMedia>
      </Item>
      <div className="text-sm leading-tight font-medium">{card.title}</div>
      <p className="mt-1.5 text-xs leading-relaxed text-muted-foreground">{card.description}</p>
    </FramePanel>
  )
}

export function SummaryCards({ cards, className }: { cards: SummaryCardData[]; className?: string }) {
  return (
    <Frame className={cn('@container w-full', className)}>
      <div className="grid gap-1 @2xl:grid-cols-2 @4xl:grid-cols-4">
        {cards.map((card) => (
          <CardItem key={card.id} card={card} />
        ))}
      </div>
    </Frame>
  )
}
