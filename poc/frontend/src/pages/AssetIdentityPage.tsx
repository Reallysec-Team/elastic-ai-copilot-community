import { useCallback, useEffect, useRef, useState } from 'react'
import { HugeiconsIcon } from '@hugeicons/react'
import {
  AlertCircleIcon, Loading03Icon, Search01Icon, ServerStack01Icon,
} from '@hugeicons/core-free-icons'

import { api, type ApiError, type EnrichmentEntry, type EnrichmentSummary } from '@/lib/api'
import { useT } from '@/lib/i18n'
import { assetIdentityCopy, type AssetIdentityKey } from '@/locales/assetIdentity'
import { commonCopy } from '@/locales/common'
import { AssetCsvCard } from '@/components/enrich/AssetCsvCard'
import { StatCards } from '@/components/blocks/dashboard-1/components/stat-cards'
import { Alert, AlertDescription } from '@/components/reui/alert'
import { Frame, FramePanel } from '@/components/reui/frame'
import { PageHeader } from '@/components/shell/page-header'
import { AdminOnlyView, useIsAdmin } from '@/components/gated-button'
import { Button } from '@/components/ui/button'
import { Empty, EmptyDescription, EmptyHeader, EmptyMedia, EmptyTitle } from '@/components/ui/empty'
import { InputGroup, InputGroupAddon, InputGroupInput } from '@/components/ui/input-group'
import { Pill } from '@/components/ui/Pill'
import {
  Table, TableBody, TableCell, TableHead, TableHeader, TableRow,
} from '@/components/ui/table'
import { Tabs, TabsList, TabsTrigger } from '@/components/ui/tabs'

/*
 * 资产台账 —— 让模型看懂「203.0.113.5 是财务库、svc_backup 是备份服务账号」。
 *
 * 这页原来只是系统设置里的一张 CSV 上传卡。上传是能上传，但**没有任何地方能看出
 * 导进去了什么、有没有被用上** —— 列写错、主机名带了域名后缀、IP 是动态的，都会让
 * 匹配全部落空，而界面上一切正常。所以这页的第一块是覆盖率，不是导入。
 *
 * 覆盖率的分母只算「有主体的告警」：没有主体的告警本来就无从匹配，算进去会把比例
 * 压成一个改不动的数字，看的人会以为是自己的表没导好。抽样没有带主体的告警时写
 * 「说不上」而不是 0% —— 后者读起来像导入失败。
 *
 * 后端在 `enrich/inventory.py`，**只读**：解析那条路（`enrich/resolver.py`）在请求
 * 路径上，每加一个功能就多一分把调查拖慢的风险，而这两个查询是偶尔打开一次的。
 */

const PAGE = 50

type Kind = 'assets' | 'identities'

const KIND_TABS: Array<{ id: Kind; label: AssetIdentityKey }> = [
  { id: 'assets', label: 'tabAssets' },
  { id: 'identities', label: 'tabIdentities' },
]

const CRIT_TONE: Record<string, 'gray' | 'sev-medium' | 'sev-high' | 'sev-critical'> = {
  low: 'gray', medium: 'sev-medium', high: 'sev-high', critical: 'sev-critical',
}

/*
 * 这一页的数据全部来自 /api/admin/enrichment/*，整组都要管理员（覆盖率、条目
 * 列表、CSV 导入）。非管理员进来时不挂载下面那个组件：三条请求全 403，页面会
 * 显示成"没有资产数据"，而真相是"你看不到"。
 */
export function AssetIdentityPage() {
  const t = useT(assetIdentityCopy)
  const isAdmin = useIsAdmin()
  if (!isAdmin) return <AdminOnlyView title={t('title')} />
  return <AssetIdentityView />
}

function AssetIdentityView() {
  const t = useT(assetIdentityCopy)
  const c = useT(commonCopy)
  const [summary, setSummary] = useState<EnrichmentSummary | null>(null)
  const [kind, setKind] = useState<Kind>('assets')
  const [term, setTerm] = useState('')
  const [q, setQ] = useState('')
  const [rows, setRows] = useState<EnrichmentEntry[]>([])
  const [total, setTotal] = useState(0)
  const [next, setNext] = useState<number | null>(null)
  const [loading, setLoading] = useState(false)
  const [loadingMore, setLoadingMore] = useState(false)
  const [error, setError] = useState<string | null>(null)

  // 和分析记录同一个做法：输入框里的字和真正发出去的关键词隔一层 300ms 防抖。
  useEffect(() => {
    const t = setTimeout(() => setQ(term.trim()), 300)
    return () => clearTimeout(t)
  }, [term])

  const loadSummary = useCallback(async () => {
    try {
      setSummary(await api.enrichmentSummary())
    } catch {
      // 覆盖率读不出来不该挡住列表 —— 那一行不显示就是了。
      setSummary(null)
    }
  }, [])

  /* 代次守卫，load 和 loadMore 共用一个计数：防抖搜索连打关键词时两次查询同时在飞，
     先发的慢请求后回来会盖掉新关键词的结果；翻页在飞时切「资产／身份」或改关键词，
     回来的那一页会被 append 到新筛选的表尾。只认最后一次发出的请求。 */
  const reqRef = useRef(0)

  const load = useCallback(async () => {
    const reqId = ++reqRef.current
    setLoading(true)
    setError(null)
    try {
      const r = await api.enrichmentEntries({ kind, q: q || undefined, limit: PAGE })
      if (reqId !== reqRef.current) return
      setRows(r.rows)
      setTotal(r.total)
      setNext(r.next)
    } catch (e) {
      if (reqId !== reqRef.current) return
      setError((e as ApiError).message || t('errLoad'))
    } finally {
      setLoading(false)
    }
  }, [kind, q, t])

  useEffect(() => {
    // eslint-disable-next-line react-hooks/set-state-in-effect -- initial load
    load()
  }, [load])

  useEffect(() => {
    void loadSummary()
  }, [loadSummary])

  const loadMore = async () => {
    if (next == null) return
    const reqId = ++reqRef.current
    setLoadingMore(true)
    try {
      const r = await api.enrichmentEntries({ kind, q: q || undefined, limit: PAGE, after: next })
      if (reqId !== reqRef.current) return
      setRows((prev) => [...prev, ...r.rows])
      setTotal(r.total)
      setNext(r.next)
    } catch (e) {
      if (reqId !== reqRef.current) return
      setError((e as ApiError).message || t('errLoad'))
    } finally {
      setLoadingMore(false)
    }
  }

  /* 导入完刷新：不刷的话刚导的行不在列表里，看上去像没导进去。 */
  const afterImport = () => {
    void load()
    void loadSummary()
  }

  const cov = summary?.coverage

  return (
    <div className="@container flex w-full flex-col gap-5">
      <PageHeader title={t('title')} />

      <section aria-label={t('secCoverage')} className="flex min-w-0 flex-col gap-3">
        <h2 className="text-base font-medium text-foreground">{t('coverageHeading')}</h2>
        <StatCards
          cards={[
            {
              title: t('kpiCoverage'),
              value: cov
                ? cov.ratio == null
                  ? t('coverageUnknown')
                  : `${Math.round(cov.ratio * 100)}%`
                : '—',
              label:
                cov && cov.ratio != null
                  ? t('coverageDetail', {
                      sampled: cov.sampled,
                      withSubject: cov.with_subject,
                      matched: cov.matched,
                    })
                  : t('coverageNoSubject'),
            },
            {
              title: t('kpiAssets'),
              value: summary ? String(summary.counts.assets) : '—',
              label: t('importedRows'),
            },
            {
              title: t('kpiIdentities'),
              value: summary ? String(summary.counts.identities) : '—',
              label: t('importedRows'),
            },
          ]}
        />
      </section>

      <section aria-label={t('secFilter')} className="flex flex-wrap items-center gap-3">
        <Tabs value={kind} onValueChange={(v) => setKind(v as Kind)}>
          <TabsList>
            {KIND_TABS.map((tab) => (
              <TabsTrigger key={tab.id} value={tab.id}>{t(tab.label)}</TabsTrigger>
            ))}
          </TabsList>
        </Tabs>

        <InputGroup className="w-full sm:w-80">
          <InputGroupAddon align="inline-start">
            <HugeiconsIcon icon={Search01Icon} strokeWidth={2} aria-hidden="true" className="size-4" />
          </InputGroupAddon>
          <InputGroupInput
            type="search"
            placeholder={t('searchPlaceholder')}
            aria-label={t('searchAria')}
            value={term}
            onChange={(e) => setTerm(e.target.value)}
          />
        </InputGroup>

        <span className="font-mono text-xs text-muted-foreground">
          {q ? t('countMatched', { n: total }) : t('countTotal', { n: total })}
        </span>
      </section>

      {error && (
        <Alert variant="destructive">
          <HugeiconsIcon icon={AlertCircleIcon} strokeWidth={2} className="size-4" />
          <AlertDescription>{error}</AlertDescription>
        </Alert>
      )}

      <section aria-label={t('secList')} className="flex min-w-0 flex-col gap-5">
        <Frame className="w-full min-w-0">
          <FramePanel className="p-0!">
            {loading ? (
              <p className="py-6 text-center text-13 text-muted-foreground">{c('loading')}…</p>
            ) : rows.length === 0 ? (
              <Empty>
                <EmptyHeader>
                  <EmptyMedia variant="icon">
                    <HugeiconsIcon icon={ServerStack01Icon} strokeWidth={2} />
                  </EmptyMedia>
                  <EmptyTitle>{q ? t('emptyFilteredTitle') : t('emptyTitle')}</EmptyTitle>
                  <EmptyDescription>
                    {q ? t('emptyFilteredDesc') : t('emptyDesc')}
                  </EmptyDescription>
                </EmptyHeader>
              </Empty>
            ) : (
              <Table>
                <TableHeader>
                  <TableRow>
                    <TableHead>{t('colName')}</TableHead>
                    <TableHead>{kind === 'assets' ? t('colHostIp') : t('colAccount')}</TableHead>
                    <TableHead className="w-[110px]">{t('colCriticality')}</TableHead>
                    <TableHead className="w-[120px]">{t('colCategory')}</TableHead>
                    <TableHead className="w-[120px]">{t('colOwner')}</TableHead>
                    <TableHead className="w-[140px]">{t('colDepartment')}</TableHead>
                  </TableRow>
                </TableHeader>
                <TableBody>
                  {rows.map((r) => (
                    <TableRow key={r.id}>
                      <TableCell className="font-medium">{r.name || '—'}</TableCell>
                      <TableCell className="font-mono text-xs">
                        {kind === 'assets'
                          ? [(r.keys ?? []).join(' / '), r.ip].filter(Boolean).join(' · ') || '—'
                          : r.user_key || '—'}
                      </TableCell>
                      <TableCell>
                        {r.criticality
                          ? <Pill tone={CRIT_TONE[r.criticality] ?? 'gray'}>{r.criticality}</Pill>
                          : '—'}
                      </TableCell>
                      <TableCell>{r.category || '—'}</TableCell>
                      <TableCell>{r.owner || '—'}</TableCell>
                      <TableCell>{r.department || '—'}</TableCell>
                    </TableRow>
                  ))}
                </TableBody>
              </Table>
            )}
          </FramePanel>
        </Frame>

        {next != null && (
          <Button
            variant="outline"
            className="self-center"
            disabled={loadingMore}
            onClick={() => void loadMore()}
          >
            {loadingMore && (
              <HugeiconsIcon icon={Loading03Icon} strokeWidth={2} className="size-4 animate-spin" />
            )}
            {t('loadMore', { n: total - rows.length })}
          </Button>
        )}
      </section>

      {/* 导入沉到最下面：它是一次性动作，上面那两块才是天天要看的。 */}
      <section aria-label={t('secImport')}>
        <AssetCsvCard onImported={afterImport} />
      </section>
    </div>
  )
}

export default AssetIdentityPage
