import { useEffect, useState, type ReactNode } from "react"
import { translate } from '@/lib/i18n'
import { componentsCopy } from '@/locales/components'
import {
  Frame,
  FrameHeader,
  FramePanel,
  FrameTitle,
} from "@/components/reui/frame"
import { Area, AreaChart, XAxis, YAxis } from "recharts"

import { cn } from "@/lib/utils"
import { ChartContainer, ChartTooltip } from "@/components/ui/chart"
import { Item, ItemMedia } from "@/components/ui/item"
import { Tabs, TabsList, TabsTrigger } from "@/components/ui/tabs"
import type { ChartConfig } from "@/components/ui/chart"

/*
 * chart-18, with its data taken out: period tabs, a row of stat tiles, and an
 * area chart that reveals from zero on mount.
 *
 * The block's tabs switched between four canned datasets. Here they are the
 * host's own control — on 调用审计 they ARE the time-range filter, so the range
 * is picked once, above the chart it redraws, instead of in a select the chart
 * knows nothing about.
 *
 * The stat row lost its coloured delta (`+4 tasks`): a delta needs a previous
 * window to compare against, and these surfaces report one window at a time.
 * `note` takes the slot for a plain qualifier.
 */
export type TrendStat = {
  id: string
  label: string
  value: string
  note?: string
  tone?: "default" | "destructive"
  icon: ReactNode
}

export type TrendPoint = { period: string; value: number }

const REVEAL_MS = 850

function TooltipBody({
  active,
  payload,
  label,
  valueLabel,
}: {
  active?: boolean
  payload?: { value: number }[]
  label?: string
  valueLabel: string
}) {
  if (!active || !payload?.length) return null
  return (
    <div className="bg-popover text-popover-foreground rounded-lg border px-3 py-2 shadow-md">
      <div className="text-muted-foreground text-xs">{label}</div>
      <div className="text-sm font-medium tabular-nums">
        {payload[0].value.toLocaleString()} {valueLabel}
      </div>
    </div>
  )
}

function RevealArea({
  points,
  valueLabel,
  config,
}: {
  points: TrendPoint[]
  valueLabel: string
  config: ChartConfig
}) {
  // Mount flat, then hand recharts the real series on the next frame — the
  // line grows out of the axis instead of appearing already drawn.
  const [data, setData] = useState<TrendPoint[]>(() =>
    points.map((p) => ({ ...p, value: 0 })),
  )

  useEffect(() => {
    setData(points.map((p) => ({ ...p, value: 0 })))
    const frame = window.requestAnimationFrame(() => setData(points))
    return () => window.cancelAnimationFrame(frame)
  }, [points])

  return (
    <ChartContainer config={config} className="h-[220px] w-full">
      <AreaChart data={data} margin={{ top: 5, right: 5, left: 5, bottom: 5 }}>
        <defs>
          <linearGradient id="trendCardGradient" x1="0" y1="0" x2="0" y2="1">
            <stop offset="0%" stopColor="var(--color-value)" stopOpacity={0.3} />
            <stop offset="100%" stopColor="var(--color-value)" stopOpacity={0.05} />
          </linearGradient>
        </defs>
        <XAxis
          dataKey="period"
          axisLine={false}
          tickLine={false}
          tick={{ fontSize: 12, fill: "var(--color-muted-foreground)" }}
          tickMargin={8}
          minTickGap={24}
        />
        <YAxis hide />
        <ChartTooltip content={<TooltipBody valueLabel={valueLabel} />} />
        <Area
          type="monotone"
          dataKey="value"
          stroke="var(--color-value)"
          strokeWidth={2}
          fill="url(#trendCardGradient)"
          isAnimationActive
          animationBegin={0}
          animationDuration={REVEAL_MS}
          animationEasing="ease-out"
          dot={false}
          activeDot={{ r: 5, fill: "var(--color-value)", stroke: "var(--color-background)", strokeWidth: 2 }}
        />
      </AreaChart>
    </ChartContainer>
  )
}

export function TrendCard({
  title,
  tabs,
  activeTab,
  onTabChange,
  stats,
  points,
  valueLabel,
  empty,
  className,
}: {
  title: string
  tabs?: { value: string; label: string }[]
  activeTab?: string
  onTabChange?: (value: string) => void
  /** Omitted where the numbers already sit somewhere else on the screen. */
  stats?: TrendStat[]
  points: TrendPoint[]
  /** Unit shown after the number in the tooltip. */
  valueLabel: string
  /** Shown in place of the chart when the window holds nothing. */
  empty?: ReactNode
  className?: string
}) {
  const config = {
    value: { label: valueLabel, color: "var(--color-primary)" },
  } satisfies ChartConfig

  const hasTabs = Boolean(tabs && tabs.length > 0)

  return (
    /* min-w-0：grid/flex 子项默认最小宽度是内容宽度，390 宽的手机上这张卡会被
       里面那排时间窗 tab 顶到 441px，超出的部分被父级裁掉（页面本身不横滚，所以
       是直接看不见）。 */
    <Frame dense className={cn("w-full min-w-0", className)}>
      {/* 有 tab 时是「带动作」那版卡头：flex-wrap 承重（窄卡里标题不该被 tab 挤成
          min-content），pb 补 2px 拉平卡头下面那条边线带来的不对称。没有 tab 时退回
          只有标题的那版。 */}
      <FrameHeader
        className={cn(
          "gap-0.5",
          hasTabs &&
            "flex-row flex-wrap items-center justify-between gap-3 pb-[calc(var(--frame-panel-header-py)+2px)]",
        )}
      >
        <div className="flex flex-col gap-0.5">
          <FrameTitle className="text-balance">{title}</FrameTitle>
        </div>
        {tabs && tabs.length > 0 && (
          <div className="flex shrink-0 items-center gap-3 pt-0.5">
            <Tabs value={activeTab} onValueChange={(v) => onTabChange?.(String(v))}>
              <TabsList>
                {tabs.map((t) => (
                  <TabsTrigger key={t.value} value={t.value} className="px-3.5">
                    {t.label}
                  </TabsTrigger>
                ))}
              </TabsList>
            </Tabs>
          </div>
        )}
      </FrameHeader>

      <FramePanel className="flex flex-1 flex-col gap-2.5">
        {stats && stats.length > 0 && (
        <div className="flex flex-wrap items-center gap-x-10 gap-y-4">
          {stats.map((stat) => (
            <div key={stat.id} className="flex items-center gap-3">
              <Item className="border-background bg-muted [&_svg]:text-accent-foreground flex size-10.5 items-center justify-center border-2 p-0 shadow-[0_1px_3px_0_rgba(0,0,0,0.14)] dark:border [&_svg]:size-5">
                <ItemMedia variant="icon" className="size-auto">
                  {stat.icon}
                </ItemMedia>
              </Item>
              <div className="space-y-px">
                <div className="text-muted-foreground text-sm">{stat.label}</div>
                <div className="flex items-center gap-2">
                  <span
                    className={cn(
                      "text-base font-semibold tabular-nums",
                      stat.tone === "destructive" && "text-destructive",
                    )}
                  >
                    {stat.value}
                  </span>
                  {stat.note && (
                    <span className="text-muted-foreground text-sm">{stat.note}</span>
                  )}
                </div>
              </div>
            </div>
          ))}
        </div>
        )}

        {points.length === 0 ? (
          <div className="text-muted-foreground flex h-[220px] items-center justify-center text-sm">
            {empty ?? translate(componentsCopy, 'chartEmpty')}
          </div>
        ) : (
          <RevealArea points={points} valueLabel={valueLabel} config={config} />
        )}
      </FramePanel>
    </Frame>
  )
}
