import { Cell, Pie, PieChart } from "recharts"
import { translate } from '@/lib/i18n'
import { componentsCopy } from '@/locales/components'
import {
  Frame,
  FrameHeader,
  FramePanel,
  FrameTitle,
} from "@/components/reui/frame"

import { cn } from "@/lib/utils"
import {
  ChartContainer,
  ChartTooltip,
  ChartTooltipContent,
} from "@/components/ui/chart"
import { Separator } from "@/components/ui/separator"
import type { ChartConfig } from "@/components/ui/chart"

/*
 * chart-13's donut and legend, taken off its seeded periods: a ring with the
 * total in the middle and a legend that spells out each slice's count and
 * share.
 *
 * The block's own period tabs are gone. Where this sits, the window is already
 * chosen once for the whole screen — a second range control on one card would
 * let two halves of the same page disagree about what "now" means.
 */
export type DonutSlice = {
  key: string
  name: string
  count: number
  /** Overrides the palette. For a vocabulary that owns its colours — severity,
      say, where "critical" is not "whatever slot it landed in". */
  color?: string
}

/*
 * Slice colours. The chart palette, in order, so the ring reads as one system
 * with the rest of the app — not per-slice literals that drift the moment a new
 * category appears. A run longer than the palette wraps.
 */
const PALETTE = [
  "var(--color-chart-1)",
  "var(--color-chart-2)",
  "var(--color-chart-3)",
  "var(--color-chart-4)",
  "var(--color-chart-5)",
]

export function MixDonut({
  title,
  centerLabel,
  slices,
  emptyText = translate(componentsCopy, 'chartEmpty'),
  className,
}: {
  title: string
  /** Small caption above the total inside the ring. */
  centerLabel: string
  slices: DonutSlice[]
  emptyText?: string
  className?: string
}) {
  const total = slices.reduce((sum, s) => sum + s.count, 0)
  const data = slices.map((s, i) => ({
    ...s,
    fill: s.color ?? PALETTE[i % PALETTE.length],
  }))
  const config = Object.fromEntries(
    data.map((s) => [s.key, { label: s.name, color: s.fill }]),
  ) satisfies ChartConfig

  return (
    <Frame dense className={cn("@container w-full min-w-0", className)}>
      <FrameHeader className="gap-0.5">
        <FrameTitle className="text-balance">{title}</FrameTitle>
      </FrameHeader>

      <FramePanel className="flex flex-1 flex-col gap-2.5">
        {total === 0 ? (
          <p className="text-muted-foreground py-10 text-center text-sm">{emptyText}</p>
        ) : (
          <div className="grid gap-6 @sm:grid-cols-[8.25rem_minmax(0,1fr)] @sm:items-center">
            <div className="relative size-[8.25rem] shrink-0">
              <ChartContainer
                aria-label={translate(componentsCopy, 'donutTotalAria', { title, total })}
                className="aspect-square size-[8.25rem]"
                config={config}
                initialDimension={{ width: 132, height: 132 }}
              >
                <PieChart margin={{ top: 2, right: 2, bottom: 2, left: 2 }}>
                  <ChartTooltip
                    cursor={false}
                    content={<ChartTooltipContent hideLabel nameKey="name" />}
                  />
                  <Pie
                    data={data}
                    dataKey="count"
                    nameKey="name"
                    endAngle={-230}
                    startAngle={130}
                    innerRadius={47}
                    outerRadius={62}
                    paddingAngle={1}
                    cornerRadius={3}
                    stroke="var(--color-background)"
                    strokeWidth={2}
                  >
                    {data.map((item) => (
                      <Cell key={item.key} fill={item.fill} />
                    ))}
                  </Pie>
                </PieChart>
              </ChartContainer>

              <div
                aria-hidden="true"
                className="pointer-events-none absolute inset-0 flex items-center justify-center"
              >
                <div className="bg-background/90 border-border/70 flex size-[5.25rem] flex-col items-center justify-center rounded-full border border-dashed">
                  <span className="text-muted-foreground/70 text-xs">{centerLabel}</span>
                  <span className="mt-0.5 text-sm font-semibold tabular-nums">
                    {total.toLocaleString()}
                  </span>
                </div>
              </div>
            </div>

            <ul className="flex min-w-0 flex-1 flex-col">
              {data.map((s, index) => (
                <li key={s.key}>
                  <div className="grid grid-cols-[minmax(0,1fr)_auto_auto] items-center gap-3 py-2">
                    <div className="flex min-w-0 items-center gap-2.5">
                      <span
                        aria-hidden="true"
                        className="border-background size-3 shrink-0 rounded-full border-2 shadow-sm"
                        style={{ backgroundColor: s.fill }}
                      />
                      <span className="truncate text-sm font-medium">{s.name}</span>
                    </div>
                    <span className="text-sm font-medium tabular-nums">
                      {s.count.toLocaleString()}
                    </span>
                    <span className="text-muted-foreground/70 w-10 text-right text-xs tabular-nums">
                      {Math.round((s.count / total) * 100)}%
                    </span>
                  </div>
                  {index < data.length - 1 ? <Separator className="w-auto" /> : null}
                </li>
              ))}
            </ul>
          </div>
        )}
      </FramePanel>
    </Frame>
  )
}
