"use client"

import { Tabs as TabsPrimitive } from "@base-ui/react/tabs"
import { cva, type VariantProps } from "class-variance-authority"
import { cn } from "cn"

function Tabs({
  className,
  orientation = "horizontal",
  ...props
}: TabsPrimitive.Root.Props) {
  return (
    <TabsPrimitive.Root
      data-slot="tabs"
      data-orientation={orientation}
      className={cn(
        // 同样是 `data-orientation`，不是字面 `data-horizontal`：这条一直没生效，
        // 今天没后果只是因为有 TabsContent 的页面都手写了 flex-col。
        "group/tabs flex gap-2 data-[orientation=horizontal]:flex-col",
        className
      )}
      {...props}
    />
  )
}

const tabsListVariants = cva(
  // 横排时用等宽格子而不是 inline-flex：`auto-cols-fr` 让每一格都取最宽那格的
  // 宽度，于是「全部」和「结果解读」一样长，而整条仍然只占内容宽度（`w-fit`）。
  // 轨道最小值取 max-content 而不是 `auto-cols-fr` 的 0：宽度不够时（窄屏、
  // 英文长标签）1fr 会把格子压到比 `whitespace-nowrap` 的文字还窄，选中态的
  // 药丸盖不住自己的字。取 max-content 之后有余量仍等宽，没余量就横向滚。
  // 用 `w-full` 会把标签拉满整页，比字数不齐更难看。TabsTrigger 上本来就有的
  // flex-1 在 inline-flex + w-fit 下是空转的 —— 容器宽度等于内容之和，没有余量
  // 可分。竖排那支保持 flex-col 不动。
  //
  // 选择器写的是 `group-data-[orientation=horizontal]` 而不是
  // `group-data-horizontal`：base-ui 的 Tabs.Root 出的是
  // `data-orientation="horizontal"`，而 Tailwind 把 `data-horizontal:` 编成
  // `[data-horizontal]`（一个字面属性名）—— 两者对不上，整条变体静默不生效，
  // 看起来和写对了一模一样。这次等宽第一版就是这么"改完没变化"的。
  // 等宽只给 default 档。line 档的下划线是 `after:inset-x-0`，铺满整条轨道 ——
  // 拉等宽之后四条下划线首尾相连成一条通条，而下划线页签的惯例是贴着字走。
  // 注意：这是 registry 拉下来的原语，重拉会盖掉这几个类。
  "group/tabs-list w-fit items-center justify-center rounded-lg p-[3px] text-muted-foreground group-data-[orientation=horizontal]/tabs:grid group-data-[orientation=horizontal]/tabs:h-8 group-data-[orientation=horizontal]/tabs:data-[variant=default]:[grid-auto-columns:minmax(max-content,1fr)] group-data-[orientation=horizontal]/tabs:data-[variant=line]:[grid-auto-columns:max-content] group-data-[orientation=horizontal]/tabs:grid-flow-col group-data-[orientation=vertical]/tabs:inline-flex group-data-[orientation=vertical]/tabs:h-fit group-data-[orientation=vertical]/tabs:flex-col data-[variant=line]:rounded-none",
  {
    variants: {
      variant: {
        default: "bg-muted",
        line: "gap-1 bg-transparent",
      },
    },
    defaultVariants: {
      variant: "default",
    },
  }
)

function TabsList({
  className,
  variant = "default",
  ...props
}: TabsPrimitive.List.Props & VariantProps<typeof tabsListVariants>) {
  return (
    <TabsPrimitive.List
      data-slot="tabs-list"
      data-variant={variant}
      className={cn(tabsListVariants({ variant }), className)}
      {...props}
    />
  )
}

function TabsTrigger({ className, ...props }: TabsPrimitive.Tab.Props) {
  return (
    <TabsPrimitive.Tab
      data-slot="tabs-trigger"
      className={cn(
        "relative inline-flex h-[calc(100%-1px)] flex-1 items-center justify-center gap-1.5 rounded-md border border-transparent px-1.5 py-0.5 text-sm font-medium whitespace-nowrap text-foreground/60 transition-all group-data-vertical/tabs:w-full group-data-vertical/tabs:justify-start hover:text-foreground focus-visible:border-ring focus-visible:ring-[3px] focus-visible:ring-ring/50 focus-visible:outline-1 focus-visible:outline-ring disabled:pointer-events-none disabled:opacity-50 has-data-[icon=inline-end]:pr-1 has-data-[icon=inline-start]:pl-1 aria-disabled:pointer-events-none aria-disabled:opacity-50 dark:text-muted-foreground dark:hover:text-foreground group-data-[variant=default]/tabs-list:data-active:shadow-sm group-data-[variant=line]/tabs-list:data-active:shadow-none [&_svg]:pointer-events-none [&_svg]:shrink-0 [&_svg:not([class*='size-'])]:size-4",
        "group-data-[variant=line]/tabs-list:bg-transparent group-data-[variant=line]/tabs-list:data-active:bg-transparent dark:group-data-[variant=line]/tabs-list:data-active:border-transparent dark:group-data-[variant=line]/tabs-list:data-active:bg-transparent",
        "data-active:bg-background data-active:text-foreground dark:data-active:border-input dark:data-active:bg-input/30 dark:data-active:text-foreground",
        "after:absolute after:bg-foreground after:opacity-0 after:transition-opacity group-data-horizontal/tabs:after:inset-x-0 group-data-horizontal/tabs:after:bottom-[-5px] group-data-horizontal/tabs:after:h-0.5 group-data-vertical/tabs:after:inset-y-0 group-data-vertical/tabs:after:-right-1 group-data-vertical/tabs:after:w-0.5 group-data-[variant=line]/tabs-list:data-active:after:opacity-100",
        className
      )}
      {...props}
    />
  )
}

function TabsContent({ className, ...props }: TabsPrimitive.Panel.Props) {
  return (
    <TabsPrimitive.Panel
      data-slot="tabs-content"
      className={cn("flex-1 text-sm outline-none", className)}
      {...props}
    />
  )
}

export { Tabs, TabsList, TabsTrigger, TabsContent, tabsListVariants }
