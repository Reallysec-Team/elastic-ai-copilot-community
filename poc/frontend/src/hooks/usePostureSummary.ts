import { useCallback, useEffect, useRef, useState } from 'react'

import { api, type ApiError, type RealtimeAlert } from '@/lib/api'
import { parseRange, resolveRange } from '@/components/shared/time-range-picker'
import { translate } from '@/lib/i18n'
import { libCopy } from '@/locales/lib'

/*
 * 「此刻在烧什么」的那几个数，一份口径。
 *
 * 这些数字有两个消费者：安全态势整页，和首页空态上的四格入口。它们原来各写各的
 * ——同样四个端点算两遍，阈值（哪些算高危、哪些检查项算异常）和「取不到怎么写」
 * 的规矩分别写在两个文件里。数字对不上的时候没人说得清哪个是对的。
 *
 * 所以搬到这里：**态势盘和首页读的是同一段代码**，改口径只改这一处。
 *
 * 两条贯穿的规矩：
 *   - 每一格各取各的，各失败各的。一个端点挂了不该把另外三个数一起抹掉。
 *   - 取不到写「读不出来」，绝不写 0。「今天没有待处置告警」和「查不到告警」是
 *     两个答案，后者写成 0 会让人以为今天很太平。同理，一轮基线巡检都没跑过不是
 *     「0 条不合规」，是「还没检查过」—— 用 null 表达。
 */

export interface Stats {
  total: number
  by_severity: Array<{ key: string; count: number }>
  by_rule: Array<{ key: string; count: number }>
  over_time: Array<{ ts: string; count: number }>
}

export interface Loadable<T> {
  data: T | null
  error: string | null
}

function empty<T>(): Loadable<T> {
  return { data: null, error: null }
}

/** 需要先看的：严重 + 高危。这条线两个页面共用。 */
export function urgentCount(byS: Stats['by_severity'] | undefined): number {
  return (byS ?? [])
    .filter((b) => b.key === 'high' || b.key === 'critical')
    .reduce((n, b) => n + b.count, 0)
}

export interface PostureSummary {
  stats: Loadable<Stats>
  urgent: number
  /** null = 一轮巡检都没跑过。 */
  baselineFail: Loadable<number | null>
  baselineScore: number | null
  platformBad: Loadable<number>
  analyses: Loadable<number>
  recent: Loadable<RealtimeAlert[]>
  lastAt: number | null
  refreshing: boolean
  reload: () => Promise<void>
}

export interface PostureOptions {
  /** 时间范围键或序列化字符串（'24h'、'6h'…）。 */
  range: string
  /** 自动刷新间隔，毫秒；不给就不自动刷新。 */
  refreshMs?: number
  /** 要几条最近告警；0（默认）= 这个消费者不需要，不发这个请求。 */
  recentLimit?: number
}

export function usePostureSummary({
  range, refreshMs, recentLimit = 0,
}: PostureOptions): PostureSummary {
  const [stats, setStats] = useState<Loadable<Stats>>(empty())
  const [baselineFail, setBaselineFail] = useState<Loadable<number | null>>(empty())
  const [baselineScore, setBaselineScore] = useState<number | null>(null)
  const [platformBad, setPlatformBad] = useState<Loadable<number>>(empty())
  const [analyses, setAnalyses] = useState<Loadable<number>>(empty())
  const [recent, setRecent] = useState<Loadable<RealtimeAlert[]>>(empty())
  const [refreshing, setRefreshing] = useState(false)
  const [lastAt, setLastAt] = useState<number | null>(null)

  // 拉取要读最新的时间范围，但不该因为范围变化就重建定时器 —— 那会让自动刷新的
  // 节奏跟着用户点选一起抖。
  const rangeRef = useRef(range)
  useEffect(() => {
    rangeRef.current = range
  }, [range])

  const limitRef = useRef(recentLimit)
  useEffect(() => {
    limitRef.current = recentLimit
  }, [recentLimit])

  /* 代次守卫：30 秒自动刷新（PosturePage 的 refreshMs）和用户切时间范围会同时在飞，
     先发的慢请求后回来会把新范围的数字盖掉 —— 标签写「7 天」、数字是「24 小时」。
     只认最后一次 reload 的结果。 */
  const reqRef = useRef(0)

  const reload = useCallback(async () => {
    const reqId = ++reqRef.current
    const fresh = () => reqId === reqRef.current
    setRefreshing(true)
    const { since, until } = resolveRange(parseRange(rangeRef.current))
    const settle = <T,>(p: Promise<T>, set: (v: Loadable<T>) => void) =>
      p.then((d) => { if (fresh()) set({ data: d, error: null }) })
        .catch((e) => { if (fresh()) set({ data: null, error: (e as ApiError).message || translate(libCopy, 'loadFailed') }) })

    const limit = limitRef.current
    await Promise.all([
      settle(api.alertsStats({ since, until }), setStats),
      settle(
        api.baselineSummary().then((r) => {
          if (fresh()) setBaselineScore(r.run?.score ?? null)
          return r.run ? r.run.fail : null
        }),
        setBaselineFail,
      ),
      settle(
        api.platformCheckup().then(
          (r) => r.checks.filter((c) => c.verdict === 'fail' || c.verdict === 'warn').length,
        ),
        setPlatformBad,
      ),
      settle(api.analysisList({ limit: 1 }).then((r) => r.total), setAnalyses),
      limit > 0
        ? settle(api.alertsList({ limit, since, until }).then((r) => r.alerts), setRecent)
        : Promise.resolve(),
    ])
    if (!fresh()) return
    setLastAt(Date.now())
    setRefreshing(false)
  }, [])

  useEffect(() => {
    void reload()
  }, [reload, range])

  useEffect(() => {
    if (!refreshMs) return
    const t = setInterval(() => void reload(), refreshMs)
    return () => clearInterval(t)
  }, [refreshMs, reload])

  return {
    stats,
    urgent: urgentCount(stats.data?.by_severity),
    baselineFail,
    baselineScore,
    platformBad,
    analyses,
    recent,
    lastAt,
    refreshing,
    reload,
  }
}
