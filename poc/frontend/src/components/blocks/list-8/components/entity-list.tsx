import type { ReactNode } from "react"
import {
  Frame,
  FrameDescription,
  FrameFooter,
  FrameHeader,
  FramePanel,
  FrameTitle,
} from "@/components/reui/frame"

import { cn } from "@/lib/utils"
import { Separator } from "@/components/ui/separator"
import { HintTip } from "@/components/hint-tip"

/*
 * list-8 的「一张 Frame 装一列条目」：卡头、条目、可选卡脚，条目之间是虚线分隔。
 * 壳子按全站卡片规范走 `Frame dense` + `FrameHeader` / `FramePanel` /
 * `FrameFooter`，区块原来那三格自己画内边距的 panel 不再用。
 *
 * 和区块的两处不同。它的 `INTEGRATION_ITEMS` 假数据删了，条目从 prop 进；行的
 * 内容也从写死的「logo + 名字 + 描述 + Connect 按钮」拆成插槽，因为同一个列表
 * 在知识库里要装两种东西：文档条目（标题 + 元信息 + 元数据药丸 + 删除）和检索
 * 命中（标题 + 分数 + 可展开的正文）。
 *
 * 区块的 `max-w-md` 也去掉了 —— 那是它 demo 的宽度，容器宽度交给外壳。
 */
export type EntityRow = {
  id: string
  /** 行首的图标 / 图标砖。 */
  icon?: ReactNode
  title: ReactNode
  /** 标题下面那行小字：id、片段数、时间之类。 */
  meta?: ReactNode
  /** 行尾：按钮、Badge。 */
  action?: ReactNode
  /** 整行之下的一块内容：药丸、可展开正文。 */
  body?: ReactNode
}

export function EntityList({
  title,
  description,
  hint,
  rows,
  footer,
  className,
}: {
  title?: ReactNode
  description?: ReactNode
  /** 标题旁的小问号。 */
  hint?: string
  rows: EntityRow[]
  footer?: ReactNode
  className?: string
}) {
  return (
    <Frame dense className={cn("@container w-full", className)}>
      {(title || description || hint) && (
        <FrameHeader className="gap-0.5">
          {title && (
            <FrameTitle className="flex items-center gap-1.5 text-balance">
              {title}
              {hint ? <HintTip text={hint} /> : null}
            </FrameTitle>
          )}
          {description && (
            <FrameDescription className="text-xs text-pretty">
              {description}
            </FrameDescription>
          )}
        </FrameHeader>
      )}

      <FramePanel className="flex flex-1 flex-col gap-2.5">
        <ul className="flex flex-col">
          {rows.map((row, index) => (
            <li key={row.id}>
              <div className="flex items-start gap-2.5">
                {row.icon}
                <div className="min-w-0 flex-1 space-y-1">
                  <div className="text-foreground text-sm font-medium">{row.title}</div>
                  {row.meta && (
                    <div className="text-muted-foreground text-xs">{row.meta}</div>
                  )}
                </div>
                {row.action}
              </div>
              {row.body && <div className="mt-3">{row.body}</div>}
              {index < rows.length - 1 ? (
                <Separator className="my-3.5 w-auto border-t border-dashed bg-transparent" />
              ) : null}
            </li>
          ))}
        </ul>
      </FramePanel>

      {footer && <FrameFooter>{footer}</FrameFooter>}
    </Frame>
  )
}
