import { type ReactNode } from "react"

import { cn } from "@/lib/utils"
import { Item, ItemMedia } from "@/components/ui/item"

// Shared Card 2-style icon tile for the KPI metric panels.
function iconContainerClassName(size: "default" | "sm" = "default") {
  return cn(
    "border-background bg-muted [&_svg]:text-accent-foreground flex shrink-0 items-center justify-center border-2 p-0 shadow-[0_1px_3px_0_rgba(0,0,0,0.14)] dark:border",
    size === "sm" ? "size-8 [&_svg]:size-3.5" : "size-9 [&_svg]:size-4"
  )
}

export function IconContainer({
  icon,
  size = "default",
}: {
  icon: ReactNode
  size?: "default" | "sm"
}) {
  return (
    <Item className={iconContainerClassName(size)}>
      <ItemMedia variant="icon" className="size-auto">
        {icon}
      </ItemMedia>
    </Item>
  )
}