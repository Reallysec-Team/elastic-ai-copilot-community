import { useState } from 'react'
import { format, subMonths } from 'date-fns'
import type { DateRange } from 'react-day-picker'
import { HugeiconsIcon } from '@hugeicons/react'
import { Calendar03Icon } from '@hugeicons/core-free-icons'

import { cn } from '@/lib/utils'
import { Calendar } from '@/components/ui/calendar'
import { Button } from '@/components/ui/button'
import { Field, FieldGroup, FieldLabel } from '@/components/ui/field'
import { Input } from '@/components/ui/input'
import { Popover, PopoverContent, PopoverTrigger } from '@/components/ui/popover'
import { Separator } from '@/components/ui/separator'

/*
 * 时间范围选择器 —— 预设 + 精确到分钟的自定义区间。
 *
 * 版式取自 `@reui/c-calendar-30`（日历 + 起止两个 time 输入放在一个 Popover 里），
 * 左边加一列预设：安全排查九成时间用的是「近 1 小时」这种，剩下一成是「昨晚
 * 21:47 到 22:15」那种精确窗口，两种都得快。
 *
 * 预设存的是 key 不是算好的时间戳：`近 24 小时` 必须跟着当前时间滑动，存成一对
 * 固定的 ISO，页面开着不动半小时后看到的就是半小时前的「近 24 小时」。自定义
 * 区间反过来存绝对值 —— 那正是它的意义。
 */

/** 预设的键就是时长本身（`15m` / `6h` / `7d`），不是一张枚举表。
 *  各页的预设清单不一样（告警要 5 分钟，审计不需要），而键能自解析就不必为此
 *  维护一张全集 —— 也让告警页里已经存下来的视图（`5m` / `6h` / `12h`）继续有效。 */
import { useT, translate } from '@/lib/i18n'
import { commonCopy } from '@/locales/common'
import { componentsCopy } from '@/locales/components'

export type PresetKey = string

export const DEFAULT_PRESETS: PresetKey[] = ['15m', '1h', '24h', '7d', '30d']

const _UNIT_MS: Record<string, number> = { m: 60_000, h: 3_600_000, d: 86_400_000 }
const _UNIT_KEY = { m: 'unitMinute', h: 'unitHour', d: 'unitDay' } as const

export function presetMs(key: string): number | null {
  const m = /^(\d+)([mhd])$/.exec(key.trim())
  return m ? Number(m[1]) * _UNIT_MS[m[2]] : null
}

export function presetLabel(key: string): string {
  const m = /^(\d+)([mhd])$/.exec(key.trim())
  if (!m) return key
  return translate(componentsCopy, 'recentN', {
    n: m[1],
    unit: translate(componentsCopy, _UNIT_KEY[m[2] as 'm' | 'h' | 'd']),
  })
}

export type TimeRange =
  | { kind: 'all' }
  | { kind: 'preset'; preset: PresetKey }
  /** 绝对区间，ISO 字符串。`until` 可缺省表示「到现在」。 */
  | { kind: 'custom'; since: string; until?: string }

/* 序列化成一个字符串。已存的视图、URL 参数、偏好里放的都是它 —— 预设原样是
   `6h`，所以老数据不用迁移；自定义是 `custom:<since>..<until>`。 */
export function serializeRange(v: TimeRange): string {
  if (v.kind === 'all') return ''
  if (v.kind === 'preset') return v.preset
  return `custom:${v.since}..${v.until ?? ''}`
}

export function parseRange(raw: string | null | undefined): TimeRange {
  const s = (raw ?? '').trim()
  if (!s) return { kind: 'all' }
  if (s.startsWith('custom:')) {
    const [since, until] = s.slice('custom:'.length).split('..')
    return since ? { kind: 'custom', since, until: until || undefined } : { kind: 'all' }
  }
  return presetMs(s) ? { kind: 'preset', preset: s } : { kind: 'all' }
}

export const ALL_TIME: TimeRange = { kind: 'all' }

/** 把选择解析成查询用的 since/until。预设在这里才算成时间戳，所以每次调用都是新的。 */
export function resolveRange(v: TimeRange): { since?: string; until?: string } {
  if (v.kind === 'all') return {}
  if (v.kind === 'preset') {
    const ms = presetMs(v.preset)
    return ms ? { since: new Date(Date.now() - ms).toISOString() } : {}
  }
  return { since: v.since, until: v.until }
}

export function rangeLabel(v: TimeRange): string {
  if (v.kind === 'all') return translate(componentsCopy, 'allTime')
  if (v.kind === 'preset') return presetLabel(v.preset)
  const from = new Date(v.since)
  const to = v.until ? new Date(v.until) : null
  return `${format(from, 'MM-dd HH:mm')} → ${to ? format(to, 'MM-dd HH:mm') : translate(componentsCopy, 'now')}`
}

function toTimeInput(d: Date): string {
  return format(d, 'HH:mm')
}

function withTime(day: Date, hhmm: string): Date {
  const [h, m] = hhmm.split(':').map((x) => Number(x) || 0)
  const out = new Date(day)
  out.setHours(h, m, 0, 0)
  return out
}

export function TimeRangePicker({
  value,
  onChange,
  presets = DEFAULT_PRESETS,
  allowAll = true,
  className,
}: {
  value: TimeRange
  onChange: (v: TimeRange) => void
  /** 这一页要给的快捷档。告警要 5 分钟，审计不需要。 */
  presets?: PresetKey[]
  /** 关掉「全部时间」—— 报告这类场景没有「不限时间」这个选项。 */
  allowAll?: boolean
  className?: string
}) {
  const t = useT(componentsCopy)
  const c = useT(commonCopy)
  const [open, setOpen] = useState(false)

  // 打开时用当前值做草稿：自定义区间接着改，预设则以它换算出的窗口为起点 ——
  // 从「近 24 小时」微调到「近 24 小时里的某两小时」是最常见的下一步。
  const resolved = resolveRange(value)
  const initialFrom = resolved.since ? new Date(resolved.since) : new Date(Date.now() - 3600_000)
  const initialTo = resolved.until ? new Date(resolved.until) : new Date()

  const [range, setRange] = useState<DateRange | undefined>({
    from: initialFrom,
    to: initialTo,
  })
  const [fromTime, setFromTime] = useState(toTimeInput(initialFrom))
  const [toTime, setToTime] = useState(toTimeInput(initialTo))
  const [err, setErr] = useState<string | null>(null)
  /* 两个 time 输入不套 InputGroup：`type="time"` 的显示格式由浏览器语言决定
     （zh-CN 24 小时制，en-US 还要多放一个 AM/PM），加一个时钟图标后两列的最小
     宽度就超过了面板，图标和数字叠在一起。标签已经写着「开始/结束时间」，
     图标本来就是多余的。 */

  function pickPreset(key: PresetKey | 'all') {
    onChange(key === 'all' ? { kind: 'all' } : { kind: 'preset', preset: key })
    setOpen(false)
  }

  const draftLabel = (() => {
    if (!range?.from) return t('pickOnCalendar')
    const a = withTime(range.from, fromTime)
    const b = withTime(range.to ?? range.from, toTime)
    return `${format(a, 'yyyy-MM-dd HH:mm')} → ${format(b, 'yyyy-MM-dd HH:mm')}`
  })()

  function apply() {
    if (!range?.from) return setErr(t('errPickDay'))
    const since = withTime(range.from, fromTime)
    // 只点了一天 = 那一天之内的一段（起止同日），这是按分钟排查时最常见的情形。
    const until = withTime(range.to ?? range.from, toTime)
    if (until <= since) return setErr(t('errEndBeforeStart'))
    setErr(null)
    onChange({ kind: 'custom', since: since.toISOString(), until: until.toISOString() })
    setOpen(false)
  }

  return (
    <Popover open={open} onOpenChange={setOpen}>
      <PopoverTrigger
        render={
          <Button variant="outline" size="sm" className={cn('justify-between gap-2', className)}>
            <HugeiconsIcon icon={Calendar03Icon} strokeWidth={2} className="size-3.5 shrink-0" />
            <span className="truncate">{rangeLabel(value)}</span>
          </Button>
        }
      />
      {/* `PopoverContent` 自带 `w-72 flex-col p-2.5` —— 不覆盖方向的话预设列和日历
          会上下叠成一条窄柱，日历被压到只剩半个月宽。 */}
      <PopoverContent align="start" className="w-auto max-w-[calc(100vw-2rem)] flex-row gap-0 p-0">
        <div className="flex w-36 shrink-0 flex-col gap-0.5 border-r border-border p-2">
          <span className="px-2 pt-1 pb-1.5 text-11 font-medium tracking-wide text-muted-foreground">
            {t('presets')}
          </span>
          {allowAll && (
            <PresetButton
              active={value.kind === 'all'}
              onClick={() => pickPreset('all')}
              label={t('allTime')}
            />
          )}
          {presets.map((key) => (
            <PresetButton
              key={key}
              active={value.kind === 'preset' && value.preset === key}
              onClick={() => pickPreset(key)}
              label={presetLabel(key)}
            />
          ))}
        </div>

        <div className="flex flex-col">
          {/* 两个月并排：跨天的区间（「上周五晚上到周六早上」）在单月视图里要翻页，
              翻页就看不见已经选中的那一端了。窄屏退回单月。 */}
          <Calendar
            mode="range"
            selected={range}
            onSelect={setRange}
            numberOfMonths={2}
            // 默认停在「上个月 + 本月」而不是「本月 + 下个月」：日志在过去，
            // 右边那一整列未来日期是全灰的，白占半个面板。
            defaultMonth={subMonths(new Date(), 1)}
            showOutsideDays={false}
            // 未来没有日志。放开只会让人选出一个必然空的窗口，再去排查「为什么没数据」。
            disabled={{ after: new Date() }}
            className="p-3 max-sm:[&_.rdp-months]:flex-col"
          />

          <Separator />

          <div className="flex flex-wrap items-end justify-between gap-3 p-3">
            <FieldGroup className="flex w-auto flex-row gap-3">
              <Field className="w-32 gap-1.5">
                <FieldLabel htmlFor="range-from-time">{t('startTime')}</FieldLabel>
                <Input
                  id="range-from-time"
                  type="time"
                  value={fromTime}
                  onChange={(e) => setFromTime(e.target.value)}
                  className="h-9 w-full"
                />
              </Field>
              <Field className="w-32 gap-1.5">
                <FieldLabel htmlFor="range-to-time">{t('endTime')}</FieldLabel>
                <Input
                  id="range-to-time"
                  type="time"
                  value={toTime}
                  onChange={(e) => setToTime(e.target.value)}
                  className="h-9 w-full"
                />
              </Field>
            </FieldGroup>

            <div className="flex items-center gap-2">
              <Button variant="ghost" size="sm" onClick={() => setOpen(false)}>
                {c('cancel')}
              </Button>
              <Button size="sm" onClick={apply}>
                {t('apply')}
              </Button>
            </div>
          </div>

          {/* 应用之前先把结果写出来 —— 日历上两个高亮的格子加两个时间框，脑子里
              拼出「9月5日 21:47 到 9月6日 02:15」是要费一秒的。 */}
          <div className="border-t border-border px-3 py-2 text-12 text-muted-foreground">
            {err ? (
              <span className="text-destructive">{err}</span>
            ) : (
              <span className="font-mono">{draftLabel}</span>
            )}
          </div>
        </div>
      </PopoverContent>
    </Popover>
  )
}

function PresetButton({
  active,
  onClick,
  label,
}: {
  active: boolean
  onClick: () => void
  label: string
}) {
  return (
    <button
      type="button"
      onClick={onClick}
      className={cn(
        'rounded-md px-2 py-1.5 text-left text-13 transition-colors',
        active ? 'bg-accent font-medium text-accent-foreground' : 'hover:bg-accent/60',
      )}
    >
      {label}
    </button>
  )
}
