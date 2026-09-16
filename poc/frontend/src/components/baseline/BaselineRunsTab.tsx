import { useEffect, useState } from 'react'
import { HugeiconsIcon } from '@hugeicons/react'
import { ArrowLeft01Icon, ChevronRightIcon } from '@hugeicons/core-free-icons'
import { api, type ApiError, type BaselineResult, type BaselineRunSummary } from '@/lib/api'
import { Frame, FramePanel } from '@/components/reui/frame'
import { BaselineResultsTable } from './BaselineResultsTable'
import { useT } from '@/lib/i18n'
import { baselineCopy } from '@/locales/baseline'
import { BlockError, BlockLoading } from '@/components/shared/block-states'

function formatTs(ts: string): string {
  if (!ts) return '—'
  const d = new Date(ts)
  if (Number.isNaN(d.getTime())) return ts
  return d.toLocaleString()
}

export function BaselineRunsTab() {
  const t = useT(baselineCopy)
  const [runs, setRuns] = useState<BaselineRunSummary[]>([])
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)

  // Drill-down state
  const [selected, setSelected] = useState<BaselineRunSummary | null>(null)
  const [results, setResults] = useState<BaselineResult[]>([])
  const [loadingResults, setLoadingResults] = useState(false)

  async function loadRuns() {
    setLoading(true)
    setError(null)
    try {
      const r = await api.baselineRuns(50)
      setRuns(r.runs)
    } catch (e) {
      setError((e as ApiError).message || t('errLoadRuns'))
    } finally {
      setLoading(false)
    }
  }

  useEffect(() => {
    void loadRuns()
  }, [])

  async function openRun(run: BaselineRunSummary) {
    setSelected(run)
    setLoadingResults(true)
    setError(null)
    try {
      const r = await api.baselineResults({ run_id: run.run_id, size: 2000 })
      setResults(r.results)
    } catch (e) {
      setError((e as ApiError).message || t('errLoadResults'))
    } finally {
      setLoadingResults(false)
    }
  }

  /* The error banner is rendered ALONGSIDE the view, never instead of it. It used
   * to replace the whole tab: a failed drill-down threw away the 返回轮次列表
   * button too, so the only way out of the error was to switch tabs and come
   * back. Now it sits above whatever is on screen and carries its own retry. */
  const banner = error ? (
    <BlockError
      message={error}
      className="mb-4"
      onRetry={() => (selected ? void openRun(selected) : void loadRuns())}
      onDismiss={() => setError(null)}
    />
  ) : null

  if (selected) {
    return (
      <div>
        {banner}
        <div className="mb-3 flex flex-wrap items-center gap-2 text-sm">
          <button
            onClick={() => {
              setSelected(null)
              setResults([])
            }}
            className="inline-flex items-center gap-1 rounded-full bg-muted px-3 py-1 text-xs text-muted-foreground transition hover:opacity-80"
          >
            <HugeiconsIcon icon={ArrowLeft01Icon} strokeWidth={2} className="size-3.5" /> {t('backToRuns')}
          </button>
          <span className="font-mono text-xs text-muted-foreground">{selected.run_id}</span>
          <span className="ml-auto text-xs text-muted-foreground">
            {t('runSummary', {
              score: selected.score ?? t('notScored'),
              pass: selected.pass,
              fail: selected.fail,
              results: results.length,
            })}
          </span>
        </div>
        {loadingResults ? (
          <BlockLoading />
        ) : (
          <BaselineResultsTable results={results} />
        )}
      </div>
    )
  }

  return (
    <div>
      {banner}
      {loading ? (
        <BlockLoading />
      ) : (
        <Frame dense spacing="sm" className="overflow-hidden">
          {/* 表格自己画内边距，panel 再来一层就是双层内边距 —— p-0 + shadow-none。 */}
          <FramePanel className="p-0 shadow-none">
            <div className="overflow-x-auto">
              <table className="w-full text-left text-sm">
                <thead className="border-b border-border text-xs text-muted-foreground">
                  <tr>
                    <th scope="col" className="px-3 py-2 font-medium">{t('colFinishedAt')}</th>
                    <th scope="col" className="px-3 py-2 font-medium">{t('colRunId')}</th>
                    <th scope="col" className="px-3 py-2 font-medium">{t('colScore')}</th>
                    <th scope="col" className="px-3 py-2 font-medium">{t('colPassFail')}</th>
                    <th scope="col" className="px-3 py-2 font-medium">{t('colHostsRules')}</th>
                    <th scope="col" className="w-8 px-2 py-2" />
                  </tr>
                </thead>
                <tbody>
                  {runs.map((run) => (
                    <tr
                      key={run.run_id}
                      onClick={() => openRun(run)}
                      className="cursor-pointer border-b border-border hover:bg-muted/50"
                    >
                      <td className="px-3 py-2 text-xs">{formatTs(run.finished_at)}</td>
                      <td className="px-3 py-2 font-mono text-10 text-muted-foreground">{run.run_id}</td>
                      <td className="px-3 py-2 font-semibold text-info">{run.score ?? t('notScored')}</td>
                      <td className="px-3 py-2 text-xs">
                        <span className="text-success">{run.pass}</span>
                        {' / '}
                        <span className="text-destructive">{run.fail}</span>
                      </td>
                      <td className="px-3 py-2 text-xs text-muted-foreground">
                        {run.host_count} × {run.rule_count}
                      </td>
                      <td className="px-2 py-2 text-muted-foreground">
                        <HugeiconsIcon icon={ChevronRightIcon} strokeWidth={2} className="size-4" />
                      </td>
                    </tr>
                  ))}
                  {runs.length === 0 && (
                    <tr>
                      <td colSpan={6} className="px-3 py-10 text-center text-sm text-muted-foreground">
                        {t('runsEmpty')}
                      </td>
                    </tr>
                  )}
                </tbody>
              </table>
            </div>
          </FramePanel>
        </Frame>
      )}
    </div>
  )
}
