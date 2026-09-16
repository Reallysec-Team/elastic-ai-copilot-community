import { type ComponentProps, type ReactNode } from "react"
import { Badge } from "@/components/reui/badge"
import { HintTip } from "@/components/hint-tip"

import { cn } from "@/lib/utils"
import {
  Field,
  FieldContent,
  FieldDescription,
  FieldLabel,
  FieldSeparator,
  FieldTitle,
} from "@/components/ui/field"

interface SettingFieldProps {
  title: string
  /** 可省：标题已经说清楚的行不要再加一句解释。只有本身就是数据 / 状态
      （「测试连接后回填」「至少 8 位」）的才留在这里。 */
  description?: string
  /** 有隐含行为要交代的说明进标题旁的小问号，不占一行。 */
  hint?: string
  badge?: {
    label: string
    variant: ComponentProps<typeof Badge>["variant"]
  }
  children: ReactNode
  last?: boolean
  labelFor?: string
  contentClassName?: string
}

// ── Setting Field ──

export function SettingField({
  title,
  description,
  hint,
  badge,
  children,
  last,
  labelFor,
  contentClassName,
}: SettingFieldProps) {
  return (
    <>
      {/* 没有说明的行要居中对齐：`responsive` 那支带着
          `has-[>[data-slot=field-content]]:items-start`，只要行里有控件列就顶对齐 ——
          有说明时对（标题+说明是一块两行的东西，该和控件顶端对齐），没说明时
          标题就孤零零吊在输入框上沿。用 `!` 是因为两条都是 items-* 工具类，
          同一层里谁在样式表后面谁赢，靠 class 顺序压不住。 */}
      <Field
        orientation="responsive"
        className={cn("gap-4 px-4 py-4", !description && "@md/field-group:items-center!")}
      >
        <div className="flex min-w-0 flex-1 flex-col gap-0.5 @md/field-group:max-w-sm">
          <div className="flex flex-wrap items-center gap-2">
            {labelFor ? (
              <FieldLabel htmlFor={labelFor}>{title}</FieldLabel>
            ) : (
              <FieldTitle>{title}</FieldTitle>
            )}

            {hint ? <HintTip text={hint} /> : null}

            {badge ? (
              // 模板标准：设置行的 Badge 一律 size="default"（h-5，12px），和页面上
              // 其他 Badge 同高；区块自己发的是 sm（h-4.5，10px）。
              <Badge variant={badge.variant} size="default">
                {badge.label}
              </Badge>
            ) : null}
          </div>

          {description ? (
            <FieldDescription className="text-xs">{description}</FieldDescription>
          ) : null}
        </div>

        <FieldContent
          className={cn("min-w-0 @md/field-group:w-78", contentClassName)}
        >
          {children}
        </FieldContent>
      </Field>

      {!last ? <FieldSeparator /> : null}
    </>
  )
}