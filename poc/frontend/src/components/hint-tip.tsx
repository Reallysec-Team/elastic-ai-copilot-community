/*
 * 标题旁的小问号：鼠标悬停 / 键盘聚焦时说这一块是干什么的。
 *
 * 以前这些说明全写在副标题里，每张卡、每一行下面都吊着一句。对第一次用的人
 * 是帮助，对天天用的人是噪音——他本来就知道「每页行数」是什么。所以说明分三档：
 *   - 标题已经说清的（「智能查询页的默认值」）：删掉；
 *   - 有隐含行为要交代的（「改完会踢掉其他会话」「留空表示不要求认证」）：进问号；
 *   - 本身就是数据或状态的（「共 12 条」「测试连接后回填」）：留在原处。
 *
 * 问号本身是个可聚焦的按钮，aria-label 就是那句说明，读屏和键盘都能拿到；
 * 自带一层 TooltipProvider，页面不用另外包。
 */
import { HugeiconsIcon } from '@hugeicons/react'
import { HelpCircleIcon } from '@hugeicons/core-free-icons'

import { Tooltip, TooltipContent, TooltipProvider, TooltipTrigger } from '@/components/ui/tooltip'
import { cn } from '@/lib/utils'

export function HintTip({ text, className }: { text: string; className?: string }) {
  return (
    <TooltipProvider delay={150}>
      <Tooltip>
        <TooltipTrigger
          render={
            <button
              type="button"
              aria-label={text}
              className={cn(
                'inline-flex size-4 shrink-0 items-center justify-center rounded-full text-muted-foreground/70 outline-none transition-colors hover:text-foreground focus-visible:text-foreground focus-visible:ring-2 focus-visible:ring-ring/50',
                className,
              )}
            />
          }
        >
          <HugeiconsIcon icon={HelpCircleIcon} strokeWidth={2} className="size-3.5" aria-hidden="true" />
        </TooltipTrigger>
        <TooltipContent side="top" className="max-w-72 text-pretty">
          {text}
        </TooltipContent>
      </Tooltip>
    </TooltipProvider>
  )
}
