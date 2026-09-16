import { useCallback, useEffect, useMemo, useState } from 'react'
import { HugeiconsIcon } from '@hugeicons/react'
import {
  CheckmarkCircle02Icon, HelpCircleIcon, Loading03Icon, RefreshCwIcon,
  SparklesIcon, TriangleAlertIcon,
} from '@hugeicons/core-free-icons'

import {
  api,
  type ApiError,
  type PlatformInterpretation,
  type PlatformReport,
} from '@/lib/api'
import { useT } from '@/lib/i18n'
import { cn } from '@/lib/utils'
import { platformCopy, type PlatformKey } from '@/locales/platform'
import { MetricGrid, type MetricCardData } from '@/components/blocks/dashboard-7/components/metric-panel'
import { CheckGroups } from '@/components/platform/CheckGroups'
import { Alert, AlertDescription } from '@/components/reui/alert'
import { Frame, FrameHeader, FramePanel, FrameTitle } from '@/components/reui/frame'
import { PageHeader } from '@/components/shell/page-header'
import { Button } from '@/components/ui/button'

/*
 * 平台体检 —— ELK 自己健不健康，尤其"日志还进得来吗"。
 *
 * 判定全在后端，是确定性规则、不调 LLM，所以这页进来就跑，不用等用户点。
 * 每条给出结论 + 可粘贴的处置建议：我们不代客户改集群，那需要写权限，而这
 * 个产品的前提是只读。
 *
 * 版式：顶上三张 dashboard-7 的指标卡（`MetricGrid`），下面检查项按
 * settings-9 的折叠分组排（`CheckGroups`：需处理 / 查不了 / 通过），"今天要
 * 处理哪几项"和"这项本来就正常"不再混在同一根列表里。
 */

type Verdict = 'ok' | 'warn' | 'fail' | 'unknown'

const OVERALL_KEY: Record<Verdict, PlatformKey> = {
  ok: 'overallOk',
  warn: 'overallWarn',
  fail: 'overallFail',
  unknown: 'overallUnknown',
}

/** 后端给的是 ISO 串；这一格只用得上时分。 */
function formatTime(iso: string) {
  const d = new Date(iso)
  return Number.isNaN(d.getTime())
    ? '—'
    : `${String(d.getHours()).padStart(2, '0')}:${String(d.getMinutes()).padStart(2, '0')}`
}

export function PlatformOpsPage() {
  const t = useT(platformCopy)
  const [report, setReport] = useState<PlatformReport | null>(null)
  const [reading, setReading] = useState<PlatformInterpretation | null>(null)
  const [loading, setLoading] = useState(true)
  const [explaining, setExplaining] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const [readError, setReadError] = useState<string | null>(null)

  const explain = useCallback(async () => {
    setExplaining(true)
    setReadError(null)
    try {
      const r = await api.platformInterpret()
      setReport(r.report)
      setReading(r.interpretation)
    } catch (e) {
      setReadError((e as ApiError)?.message ?? t('errInterpret'))
    } finally {
      setExplaining(false)
    }
  }, [t])

  const load = useCallback(async () => {
    setLoading(true)
    setError(null)
    setReading(null)
    setReadError(null)
    try {
      const r = await api.platformCheckup()
      setReport(r)
      // 有真异常时不等用户点。健康的集群不烧 token，坏掉的集群不该还要多点一下
      // 才看得到该先做什么。
      // 但解读是收费能力：没许可时自动点只会换来一块红字（还扣试用额度）——
      // 那种情况让按钮留在那，点了再说需要许可。
      if (r.verdict === 'fail') {
        const lic = await api.licenseStatus().catch(() => null)
        const unlocked = ['valid', 'expiring', 'grace'].includes(lic?.status ?? '') && (lic?.features ?? []).includes('platform_ops_copilot')
        if (unlocked) void explain()
      }
    } catch (e) {
      setError((e as ApiError)?.message ?? t('errCheckup'))
    } finally {
      setLoading(false)
    }
  }, [explain, t])

  useEffect(() => {
    void load()
  }, [load])

  const overall = (report?.verdict ?? 'unknown') as Verdict

  /* 通过 / 需处理（fail+warn）/ 查不了 / 体检时间。fail 和 warn 合成一格：
   * 分开会让"今天要做几件事"变成两个数字相加，而这正是这一屏要回答的问题。
   * 严重程度没丢——每条自己的判定就在下面的列表里，也能直接筛。 */
  const cards = useMemo<MetricCardData[]>(() => {
    if (!report) return []
    const c = report.counts ?? {}
    const total = report.checks.length
    const todo = (c.fail ?? 0) + (c.warn ?? 0)
    return [
      {
        id: 'ok',
        title: t('kpiOk'),
        detail: t('kpiOkLabel', { n: total }),
        value: String(c.ok ?? 0),
        tone: 'success',
        icon: <HugeiconsIcon icon={CheckmarkCircle02Icon} strokeWidth={2} aria-hidden="true" />,
      },
      {
        id: 'todo',
        title: t('kpiTodo'),
        detail: t('kpiTodoLabel', { fail: c.fail ?? 0, warn: c.warn ?? 0 }),
        value: String(todo),
        tone: (c.fail ?? 0) > 0 ? 'destructive' : 'warning',
        badge:
          (c.fail ?? 0) > 0
            ? { label: t('verdictFail'), tone: 'destructive' }
            : todo > 0
              ? { label: t('verdictWarn'), tone: 'warning' }
              : undefined,
        icon: <HugeiconsIcon icon={TriangleAlertIcon} strokeWidth={2} aria-hidden="true" />,
      },
      {
        id: 'unknown',
        title: t('kpiUnknown'),
        detail: t('kpiUnknownLabel'),
        value: String(c.unknown ?? 0),
        icon: <HugeiconsIcon icon={HelpCircleIcon} strokeWidth={2} aria-hidden="true" />,
      },
    ]
  }, [report, t])

  return (
    <div className="@container flex w-full flex-col gap-5">
      <PageHeader
        title={t('title')}
        actions={
          <div className="flex items-center gap-2">
            {report && report.verdict !== 'ok' && !reading && (
              <Button variant="outline" onClick={() => void explain()} disabled={explaining}>
                <HugeiconsIcon
                  icon={explaining ? Loading03Icon : SparklesIcon}
                  strokeWidth={2}
                  className={cn('size-4', explaining && 'animate-spin')}
                />
                {explaining ? t('aiReading') : t('aiRead')}
              </Button>
            )}
            <Button onClick={() => void load()} disabled={loading || explaining}>
              <HugeiconsIcon
                icon={loading ? Loading03Icon : RefreshCwIcon}
                strokeWidth={2}
                className={cn('size-4', loading && 'animate-spin')}
              />
              {loading ? t('checking') : t('recheck')}
            </Button>
          </div>
        }
      />

      {error && (
        <Alert variant="destructive">
          <HugeiconsIcon icon={TriangleAlertIcon} strokeWidth={2} className="size-4" />
          <AlertDescription>{error}</AlertDescription>
        </Alert>
      )}

      {report && (
        <>
          {/* 「结论 · 本次体检完成于 hh:mm」是这批数据的时间戳，不是页面的介绍：
              跟着体检结果走，不挂在大标题下面。 */}
          <p className="-mb-2 text-xs text-muted-foreground">
            {t('descDone', {
              overall: t(OVERALL_KEY[overall]),
              time: formatTime(report.generated_at),
            })}
          </p>
          <section aria-label={t('secOverview')}>
            <MetricGrid cards={cards} className="@3xl:grid-cols-3 @5xl:grid-cols-3" />
          </section>

          {(reading || explaining || readError) && (
            <section aria-label={t('secAiRead')}>
              <ReadingCard reading={reading} busy={explaining} error={readError} />
            </section>
          )}

          <section aria-label={t('secChecks')}>
            <CheckGroups checks={report.checks} />
          </section>
        </>
      )}

      {!report && loading && (
        <Frame spacing="sm">
          <FramePanel className="flex items-center gap-2 text-sm text-muted-foreground">
            <HugeiconsIcon icon={Loading03Icon} strokeWidth={2} className="size-4 animate-spin" />
            {t('checkingCluster')}
          </FramePanel>
        </Frame>
      )}

    </div>
  )
}

function ReadingCard({
  reading,
  busy,
  error,
}: {
  reading: PlatformInterpretation | null
  busy: boolean
  error: string | null
}) {
  const t = useT(platformCopy)
  return (
    <Frame spacing="sm">
      <FrameHeader>
        <FrameTitle className="flex items-center gap-2 text-xs">
          <HugeiconsIcon icon={SparklesIcon} strokeWidth={2} className="size-3.5" />
          {t('aiRead')}
          {reading && reading.rag_chunks_used > 0 && (
            <span className="font-normal text-muted-foreground">
              {t('aiRagUsed', { n: reading.rag_chunks_used })}
            </span>
          )}
          {reading?.degraded && (
            <span className="font-normal text-muted-foreground">{t('aiDegraded')}</span>
          )}
        </FrameTitle>
      </FrameHeader>
      <FramePanel className="flex flex-col gap-3">
        {busy && !reading && (
          <div className="flex items-center gap-2 text-sm text-muted-foreground">
            <HugeiconsIcon icon={Loading03Icon} strokeWidth={2} className="size-4 animate-spin" />
            {t('aiThinking')}
          </div>
        )}
        {error && <div className="text-sm text-destructive">{error}</div>}

        {reading && (
          <>
            <p className="text-sm leading-relaxed">{reading.conclusion}</p>
            {reading.actions.length > 0 && (
              <ol className="flex flex-col gap-2.5">
                {reading.actions.map((a, i) => (
                  <li key={i} className="flex gap-2.5">
                    <span className="mt-0.5 flex size-5 shrink-0 items-center justify-center rounded-full bg-primary font-mono text-11 text-primary-foreground">
                      {i + 1}
                    </span>
                    <div className="flex min-w-0 flex-col gap-1">
                      <div className="text-sm font-medium">{a.title}</div>
                      {a.why && (
                        <p className="text-sm leading-relaxed text-muted-foreground">{a.why}</p>
                      )}
                      {a.how && (
                        <pre className="overflow-x-auto rounded-lg bg-muted/50 px-3 py-2 font-mono text-11 leading-[1.5] whitespace-pre-wrap">
                          {a.how}
                        </pre>
                      )}
                    </div>
                  </li>
                ))}
              </ol>
            )}
          </>
        )}
      </FramePanel>
    </Frame>
  )
}
