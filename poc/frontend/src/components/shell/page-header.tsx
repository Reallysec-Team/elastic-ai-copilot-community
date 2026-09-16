import type { ReactNode } from 'react'

import { cn } from '@/lib/utils'
import { PageTabs } from '@/components/shell/page-tabs'

/*
 * roster's PageHeader (`app/layouts/page-header.tsx`): the title block every
 * screen opens with, so the size and weight cannot drift page to page.
 *
 * `text-xl font-medium`, not the app's global `h1` rule — index.css gives every
 * `h1` the 48px display size, written for the page heroes this shell replaced,
 * and it would take over any new heading. The size is re-stated here so the
 * rule cannot reach it.
 *
 * 标题就是标题，没有副标题这一档：一级页面的大标题下面挂一行说明既不好看，
 * 也总在重复正文几个像素之下就要说的话（条数、时间戳、结论）。这些东西属于
 * 它们各自的卡片或表格，不属于页头。所以这里干脆不收 `description` —— 想加的
 * 人会在编译期被挡住，而不是靠约定。
 *
 * 桌面端曾经把标题 portal 进顶栏，理由是那条栏几乎总是空的。代价是顶栏变成了
 * 「当前在哪一页」的回声 —— 而左边导航栏已经把当前项高亮出来了，同一件事说两遍，
 * 顶栏却因此没有地方放产品名。现在标题一律画在正文里，顶栏还给产品身份。
 */
export function PageHeader({
  title,
  actions,
  className,
}: {
  title: ReactNode
  actions?: ReactNode
  className?: string
}) {
  return (
    <div className="flex flex-col gap-3">
      {/* 单行标题跟按钮居中对齐。以前有说明时是底对齐（两行的一块底边对齐按钮
          底边），副标题去掉之后那一档就没有了。 */}
      <div
        className={cn('flex flex-wrap items-center justify-between gap-3', className)}
      >
        <div className="flex min-w-0 flex-col gap-1">
          <h1 className="text-xl leading-tight font-medium tracking-tight text-foreground">
            {title}
          </h1>
        </div>
        {actions}
      </div>
      <PageTabs />
    </div>
  )
}
