import {
  Frame, FrameDescription, FrameFooter, FrameHeader, FramePanel, FrameTitle,
} from '@/components/reui/frame'
import { FieldGroup } from '@/components/ui/field'
import { HintTip } from '@/components/hint-tip'

/*
 * 一张卡 = 一组设置行。`FieldGroup` 是 `SettingField` 的响应式断点容器
 * （`@md/field-group`），必须包着行；`gap-0` 是因为行自己带 padding 和
 * `FieldSeparator`，再叠一层 gap 会让分隔线浮在半空。
 */
export function SettingsCard({
  title,
  description,
  hint,
  children,
  footer,
}: {
  title: string
  description?: string
  /** 标题旁的小问号（见 hint-tip.tsx）。 */
  hint?: string
  children: React.ReactNode
  /** 整卡宽的收尾内容。横幅放这里而不是放进某一行的控件列 —— 控件列只有
      19.5rem 宽，一句话会被折成五行，图标孤零零挂在中间。 */
  footer?: React.ReactNode
}) {
  return (
    /* `dense` + 卡头 `gap-0.5`、说明 12px：和模板 settings-3 的那张卡同一个壳。 */
    <Frame dense className="w-full min-w-0">
      <FrameHeader className="gap-0.5">
        <FrameTitle className="flex items-center gap-1.5 text-balance">
          {title}
          {hint ? <HintTip text={hint} /> : null}
        </FrameTitle>
        {description ? (
          <FrameDescription className="text-xs text-pretty">{description}</FrameDescription>
        ) : null}
      </FrameHeader>
      <FramePanel className="p-0!">
        <FieldGroup className="gap-0">{children}</FieldGroup>
      </FramePanel>
      {/* 卡脚，不是第二块面板：收尾内容跟着卡走，不该再画一圈自己的框和阴影。 */}
      {footer && <FrameFooter className="gap-2.5">{footer}</FrameFooter>}
    </Frame>
  )
}
