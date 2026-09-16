import { useEffect, useState } from 'react'
import { HugeiconsIcon, type IconSvgElement } from '@hugeicons/react'
import {
  AlertCircleIcon, BookOpen02Icon, Calendar03Icon, Cancel01Icon,
  CheckmarkCircle02Icon, Delete02Icon, FileTextIcon, Layers01Icon, Loading03Icon,
  PlusIcon, RefreshCwIcon, Search01Icon, SparklesIcon, Upload01Icon,
} from '@hugeicons/core-free-icons'
import { toast } from 'sonner'

import { GatedButton } from '@/components/gated-button'
import { api, type ApiError } from '@/lib/api'
import { cn } from '@/lib/utils'
import { EntityList, type EntityRow } from '@/components/blocks/list-8/components/entity-list'
import { StatCards, type StatCard } from '@/components/blocks/dashboard-1/components/stat-cards'
import { Alert, AlertDescription } from '@/components/reui/alert'
import { Badge } from '@/components/reui/badge'
import { Frame, FramePanel } from '@/components/reui/frame'
import { IconTile } from '@/components/reui/icon-tile'
import { useT, translate, type Translate } from '@/lib/i18n'
import { commonCopy } from '@/locales/common'
import { kbCopy, type KbKey } from '@/locales/kb'
import { shellCopy } from '@/locales/shell'
import { PageHeader } from '@/components/shell/page-header'
import { Button } from '@/components/ui/button'
import { Empty, EmptyDescription, EmptyHeader, EmptyMedia, EmptyTitle } from '@/components/ui/empty'
import { Field, FieldDescription, FieldLabel } from '@/components/ui/field'
import { Input } from '@/components/ui/input'
import {
  InputGroup, InputGroupAddon, InputGroupButton, InputGroupInput,
} from '@/components/ui/input-group'
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from '@/components/ui/select'
import { Skeleton } from '@/components/ui/skeleton'
import { Dialog, DialogContent, DialogHeader, DialogTitle } from '@/components/ui/dialog'
import { Tabs, TabsContent, TabsList, TabsTrigger } from '@/components/ui/tabs'
import { Textarea } from '@/components/ui/textarea'

/*
  * 处置手册 —— 上传 Runbook / SOP，切块嵌入，解释与调查时按语义命中并注入。
 *
 * 这一版把三个 tab 都搬到了原语和区块上：
 *   - 文档条目和检索命中共用 `@reui/list-8` 改出来的 `EntityList`（一张 Frame
 *     装一列条目，虚线分隔）。两边本来是两套手写卡片，长得还不一样。
 *   - 文档库顶上加了一排 `@reui/dashboard-1` 的 `StatCards`：篇数 / 片段数 /
 *     最近入库。前两个原来是一行 12px 的小字，第三个原来根本没有 —— 而「知识库
 *     是不是已经半年没更新了」恰恰是这页最该先回答的问题。
 *   - 手写的错误块 / 成功块换成 `Alert` 的 destructive / success，手写的搜索框
 *     换成 `InputGroup`，TOP_K 的数字输入框换成 `Select`（1–20 里真正有意义的
 *     就那几档），表单换成 `Field`。
 *   - 满屏的字面色（`--t-fg-muted` / `--t-s2` / `--color-develop` / `--t-err-bg`）
 *     全部换成语义 token。
 *
 * 检索命中的分数不用 `Pill` —— `Pill` 是严重度那套词汇的出处，相似度不是严重度。
 */

type Tab = 'docs' | 'upload' | 'search'

type KbDoc = {
  doc_id: string | null
  title: string | null
  chunk_count: number
  first_indexed_at: string | null
  metadata: Record<string, unknown>
}

type KbHit = {
  doc_id: string | null
  chunk_id: string | null
  title: string | null
  content: string | null
  score: number | null
}

type MetaRow = { key: string; value: string }

/* 后端这条错误是英文的技术描述（"embed model not configured"），对着操作的人
   要换成「谁能修、去哪修」。 */
function embedNotConfiguredHint(): string {
  return translate(kbCopy, 'embedNotConfigured')
}

function isEmbedNotConfigured(msg: string | null | undefined): boolean {
  if (!msg) return false
  const m = msg.toLowerCase()
  return (
    m.includes('embed model not configured') ||
    m.includes('embed_model not configured') ||
    m.includes('rst_embed_model')
  )
}

export function KbPage() {
  const t = useT(kbCopy)
  const [tab, setTab] = useState<Tab>('docs')
  const [uploadOpen, setUploadOpen] = useState(false)

  // Cross-tab cached docs
  const [docs, setDocs] = useState<KbDoc[] | null>(null)
  const [docsLoading, setDocsLoading] = useState(false)
  const [docsError, setDocsError] = useState<string | null>(null)

  async function refreshDocs() {
    setDocsLoading(true)
    setDocsError(null)
    try {
      const r = await api.kbDocuments()
      setDocs(r)
    } catch (e) {
      const err = e as ApiError
      setDocsError(err.message)
    } finally {
      setDocsLoading(false)
    }
  }

  // Initial load — only fetch if we haven't already.
  useEffect(() => {
    if (docs === null && !docsLoading && !docsError) {
      // eslint-disable-next-line react-hooks/set-state-in-effect -- one-shot initial fetch
      refreshDocs()
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [])

  return (
    <div className="@container flex w-full flex-col gap-5">
      {/* 「上传」原来是三个 tab 里的一个 —— 两个名词中间夹一个动词，而且上传完
          还要自己切回文档库。改成页头一个按钮 + 弹窗，空态那个「上传第一篇」
          按的是同一个。 */}
      <PageHeader
        title={t('title')}
        actions={
          <GatedButton gate="admin" onClick={() => setUploadOpen(true)}>
            <HugeiconsIcon icon={Upload01Icon} strokeWidth={2} className="size-4" />
            {t('upload')}
          </GatedButton>
        }
      />

      <Dialog open={uploadOpen} onOpenChange={setUploadOpen}>
        <DialogContent className="max-h-[85vh] overflow-y-auto sm:max-w-2xl">
          <DialogHeader>
            <DialogTitle>{t('uploadDialogTitle')}</DialogTitle>
          </DialogHeader>
          <UploadTab
            onUploaded={() => {
              refreshDocs()
              setTimeout(() => setUploadOpen(false), 1200)
            }}
          />
        </DialogContent>
      </Dialog>

      <Tabs
        value={tab}
        onValueChange={(v) => setTab(v as Tab)}
        className="w-full flex-col gap-5"
      >
        <TabsList>
          {TAB_ITEMS.map((it) => (
            <TabsTrigger key={it.id} value={it.id}>
              <HugeiconsIcon icon={it.icon} strokeWidth={2} className="size-3.5" />
              {t(it.label)}
            </TabsTrigger>
          ))}
        </TabsList>

        <TabsContent value="docs" className={TAB_PANEL_CLS}>
          <DocsTab
            docs={docs}
            loading={docsLoading}
            error={docsError}
            onRefresh={refreshDocs}
            onGoUpload={() => setUploadOpen(true)}
            onDeleteOptimistic={(docId) => {
              setDocs((prev) =>
                prev ? prev.filter((d) => d.doc_id !== docId) : prev,
              )
            }}
            onAfterDelete={refreshDocs}
          />
        </TabsContent>

        <TabsContent value="search" className={TAB_PANEL_CLS}>
          <SearchTab />
        </TabsContent>
      </Tabs>
    </div>
  )
}


/* ---------- Tab strip ---------- */

const TAB_ITEMS: { id: Tab; label: KbKey; icon: IconSvgElement }[] = [
  { id: 'docs', label: 'tabDocs', icon: BookOpen02Icon },
  { id: 'search', label: 'tabSearch', icon: Search01Icon },
]

/* Tabs 用原语自己的样子：原来那三个常量把它重画成一排药丸，且 `Tabs` 根节点
 * 不给方向时是 flex-row，tab 条会被挤成左边一列。 */
const TAB_PANEL_CLS = 'w-full min-w-0'

/* ---------- Docs tab ---------- */

function DocsTab({
  docs,
  loading,
  error,
  onRefresh,
  onGoUpload,
  onDeleteOptimistic,
  onAfterDelete,
}: {
  docs: KbDoc[] | null
  loading: boolean
  error: string | null
  onRefresh: () => void
  onGoUpload: () => void
  onDeleteOptimistic: (docId: string) => void
  onAfterDelete: () => void
}) {
  const t = useT(kbCopy)
  const c = useT(commonCopy)
  const embedMissing = isEmbedNotConfigured(error)

  async function handleDelete(doc: KbDoc) {

    if (!doc.doc_id) return
    const ok = window.confirm(
      t('confirmDelete', { name: doc.title ?? doc.doc_id, n: doc.chunk_count }),
    )
    if (!ok) return
    onDeleteOptimistic(doc.doc_id)
    try {
      await api.kbDelete(doc.doc_id)
      toast.success(t('okDeleted', { name: doc.title ?? doc.doc_id ?? '' }))
    } catch (e) {
      // 原来这里是静默 catch，删除失败时列表会先少一条、刷新后又冒出来，
      // 看起来像页面自己抽风。失败就说一声，刷新负责把真相摆回来。
      toast.error((e as ApiError).message || t('errDelete'))
    }
    onAfterDelete()
  }

  const rows: EntityRow[] = (docs ?? []).map((d, i) => ({
    id: d.doc_id ?? `kb-${i}`,
    icon: (
      <IconTile variant="soft" size="sm" className="mt-0.5 shrink-0">
        <HugeiconsIcon icon={FileTextIcon} strokeWidth={2} aria-hidden="true" />
      </IconTile>
    ),
    title: d.title || <span className="text-muted-foreground">{t('untitled')}</span>,
    meta: (
      <span className="flex flex-wrap items-center gap-x-2 gap-y-1 font-mono text-xs">
        <code className="text-foreground">{d.doc_id ?? '—'}</code>
        <span aria-hidden="true">·</span>
        <span className="tabular-nums">{t('chunkCount', { n: d.chunk_count })}</span>
        <span aria-hidden="true">·</span>
        <span>{formatRelativeOrIso(d.first_indexed_at)}</span>
      </span>
    ),
    action: (
      <GatedButton
        gate="admin"
        variant="ghost"
        size="icon-sm"
        title={c('delete')}
        aria-label={t('deleteDoc', { name: d.title ?? d.doc_id ?? '' })}
        className="shrink-0 text-muted-foreground hover:text-destructive"
        onClick={() => void handleDelete(d)}
      >
        <HugeiconsIcon icon={Delete02Icon} strokeWidth={2} className="size-3.5" />
      </GatedButton>
    ),
    body: <MetaBadges metadata={d.metadata} />,
  }))

  return (
    <div className="flex flex-col gap-5">
      {error && (
        <ErrorBanner message={embedMissing ? embedNotConfiguredHint() : error} />
      )}

      {loading && docs === null && <SkeletonList />}

      {!loading && !error && docs !== null && docs.length === 0 && (
        <EmptyState onGoUpload={onGoUpload} />
      )}

      {docs !== null && docs.length > 0 && (
        <>
          <section aria-label={t('secDocsOverview')}>
            <StatCards cards={docsCards(t, docs)} />
          </section>
          <section aria-label={t('secDocsList')}>
            <EntityList
              title={t('docsListTitle')}
              rows={rows}
              footer={
                <Button
                  variant="outline"
                  size="lg"
                  className="w-full"
                  onClick={onRefresh}
                  disabled={loading}
                >
                  <HugeiconsIcon
                    icon={RefreshCwIcon}
                    strokeWidth={2}
                    aria-hidden="true"
                    className={cn('opacity-50', loading && 'animate-spin')}
                  />
                  {c('refresh')}
                </Button>
              }
            />
          </section>
        </>
      )}
    </div>
  )
}

function docsCards(t: Translate<KbKey>, docs: KbDoc[]): StatCard[] {
  const chunks = docs.reduce((sum, d) => sum + (d.chunk_count || 0), 0)
  // 最近一篇的入库时间。知识库最容易出的问题不是空，是旧 —— 半年没进新东西的
  // Runbook 还在被当成权威注入给模型。
  const newest = docs
    .map((d) => (d.first_indexed_at ? Date.parse(d.first_indexed_at) : NaN))
    .filter((t) => !Number.isNaN(t))
    .reduce((max, t) => (t > max ? t : max), 0)

  return [
    {
      label: t('kpiDocsLabel'),
      title: t('kpiDocs'),
      value: docs.length.toLocaleString(),
      icon: <HugeiconsIcon icon={BookOpen02Icon} strokeWidth={2} aria-hidden="true" />,
    },
    {
      label: t('kpiChunksLabel'),
      title: t('kpiChunks'),
      value: chunks.toLocaleString(),
      icon: <HugeiconsIcon icon={Layers01Icon} strokeWidth={2} aria-hidden="true" />,
    },
    {
      label: newest > 0 ? new Date(newest).toISOString().slice(0, 10) : t('kpiNewestNoTs'),
      title: t('kpiNewest'),
      value: newest > 0 ? formatRelativeOrIso(new Date(newest).toISOString()) : '—',
      icon: <HugeiconsIcon icon={Calendar03Icon} strokeWidth={2} aria-hidden="true" />,
    },
  ]
}

function MetaBadges({ metadata }: { metadata: Record<string, unknown> }) {
  const meta = metadata && typeof metadata === 'object' ? metadata : {}
  const entries = Object.entries(meta).filter(
    ([, v]) => v !== null && v !== undefined && v !== '',
  )
  if (entries.length === 0) return null
  return (
    <div className="flex flex-wrap gap-1.5 ps-[2.625rem]">
      {entries.map(([k, v]) => (
        <Badge key={k} size="sm" variant="secondary" className="font-mono">
          {k}={typeof v === 'string' ? v : JSON.stringify(v)}
        </Badge>
      ))}
    </div>
  )
}

function SkeletonList() {
  return (
    <Frame stacked className="w-full">
      <FramePanel className="space-y-3.5 p-5!">
        {[0, 1, 2].map((i) => (
          <div key={i} className="space-y-2">
            <Skeleton className="h-4 w-2/3" />
            <Skeleton className="h-3 w-1/3" />
          </div>
        ))}
      </FramePanel>
    </Frame>
  )
}

function EmptyState({ onGoUpload }: { onGoUpload: () => void }) {
  const t = useT(kbCopy)
  return (
    <Empty>
      <EmptyHeader>
        <EmptyMedia variant="icon">
          <HugeiconsIcon icon={FileTextIcon} strokeWidth={2} />
        </EmptyMedia>
        <EmptyTitle>{t('emptyTitle')}</EmptyTitle>
        <EmptyDescription>{t('emptyDesc')}</EmptyDescription>
      </EmptyHeader>
      <GatedButton gate="admin" onClick={onGoUpload}>
        <HugeiconsIcon icon={Upload01Icon} strokeWidth={2} className="size-3.5" />
        {t('uploadFirst')}
      </GatedButton>
    </Empty>
  )
}

/* ---------- Upload tab ---------- */

function UploadTab({ onUploaded }: { onUploaded: () => void }) {
  const t = useT(kbCopy)
  const [title, setTitle] = useState('')
  const [content, setContent] = useState('')
  const [metaRows, setMetaRows] = useState<MetaRow[]>([{ key: '', value: '' }])
  const [submitting, setSubmitting] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const [success, setSuccess] = useState<{ chunk_count: number; doc_id: string } | null>(
    null,
  )

  const chunksEst = Math.max(1, Math.ceil((content.length || 0) / 800))

  function setMetaAt(idx: number, patch: Partial<MetaRow>) {
    setMetaRows((rows) => rows.map((r, i) => (i === idx ? { ...r, ...patch } : r)))
  }
  function removeMetaAt(idx: number) {
    setMetaRows((rows) => rows.filter((_, i) => i !== idx))
  }
  function addMetaRow() {
    setMetaRows((rows) => (rows.length >= 6 ? rows : [...rows, { key: '', value: '' }]))
  }

  function buildMetadata(): Record<string, unknown> | undefined {
    const out: Record<string, unknown> = {}
    for (const r of metaRows) {
      const k = r.key.trim()
      const v = r.value.trim()
      if (k && v) out[k] = v
    }
    return Object.keys(out).length > 0 ? out : undefined
  }

  async function onSubmit() {
    if (!title.trim() || !content.trim()) {
      setError(t('errTitleBodyRequired'))
      return
    }
    setSubmitting(true)
    setError(null)
    setSuccess(null)
    try {
      const r = await api.kbUpload({
        title: title.trim(),
        content: content,
        metadata: buildMetadata(),
      })
      setSuccess({ chunk_count: r.chunk_count, doc_id: r.doc_id })
      setTitle('')
      setContent('')
      setMetaRows([{ key: '', value: '' }])
      onUploaded()
    } catch (e) {
      const err = e as ApiError
      setError(err.message)
    } finally {
      setSubmitting(false)
    }
  }

  const embedMissing = isEmbedNotConfigured(error)

  return (
    <div className="space-y-5">
        <Field>
          <FieldLabel htmlFor="kb-title">{t('fieldTitle')}</FieldLabel>
          <Input
            id="kb-title"
            value={title}
            onChange={(e) => setTitle(e.target.value)}
            placeholder={t('titlePlaceholder')}
            disabled={submitting}
          />
        </Field>

        <Field>
          <FieldLabel htmlFor="kb-content">{t('fieldBody')}</FieldLabel>
          <Textarea
            id="kb-content"
            value={content}
            onChange={(e) => setContent(e.target.value)}
            placeholder={t('bodyPlaceholder')}
            disabled={submitting}
            className="min-h-[280px] text-sm leading-relaxed"
          />
          <FieldDescription className="tabular-nums">
            {t('chunkEstimate', { chunks: chunksEst, chars: content.length })}
          </FieldDescription>
        </Field>

        <Field>
          <FieldLabel>{t('fieldMetadata')}</FieldLabel>
          <FieldDescription>{t('metadataDesc', { n: metaRows.length })}</FieldDescription>
          <div className="space-y-2">
            {metaRows.map((row, i) => (
              <div key={i} className="flex items-center gap-2">
                <Input
                  value={row.key}
                  onChange={(e) => setMetaAt(i, { key: e.target.value })}
                  placeholder={t('metaKeyPlaceholder')}
                  aria-label={t('metaKeyAria', { i: i + 1 })}
                  disabled={submitting}
                  className="flex-1 font-mono text-xs"
                />
                <Input
                  value={row.value}
                  onChange={(e) => setMetaAt(i, { value: e.target.value })}
                  placeholder={t('metaValuePlaceholder')}
                  aria-label={t('metaValueAria', { i: i + 1 })}
                  disabled={submitting}
                  className="flex-1 font-mono text-xs"
                />
                {metaRows.length > 1 && (
                  <Button
                    variant="ghost"
                    size="icon"
                    title={t('metaRemove')}
                    aria-label={t('metaRemoveAria', { i: i + 1 })}
                    className="shrink-0 text-muted-foreground hover:text-destructive"
                    disabled={submitting}
                    onClick={() => removeMetaAt(i)}
                  >
                    <HugeiconsIcon icon={Cancel01Icon} strokeWidth={2} className="size-3.5" />
                  </Button>
                )}
              </div>
            ))}
          </div>
          {/* `Field` 的 vertical 变体给每个直接子节点加了 `*:w-full`，
              不用 `!` 压住的话这个按钮会被拉满一行、字挤在正中间。 */}
          {metaRows.length < 6 && (
            <Button variant="ghost" size="sm" className="w-fit!" onClick={addMetaRow} disabled={submitting}>
              <HugeiconsIcon icon={PlusIcon} strokeWidth={2} className="size-3.5" />
              {t('addField')}
            </Button>
          )}
        </Field>

        {error && (
          <ErrorBanner message={embedMissing ? embedNotConfiguredHint() : error} />
        )}

        {success && (
          <Alert variant="success">
            <HugeiconsIcon icon={CheckmarkCircle02Icon} strokeWidth={2} className="size-4" />
            <AlertDescription>
              {/* `AlertDescription` 是 grid，直接子节点各占一行。整句必须包在
                  一个节点里，否则「已上传」「42」「个片段…」会被拆成三行。 */}
              <p>{t('uploadedChunks', { n: success.chunk_count })}</p>
            </AlertDescription>
          </Alert>
        )}

        <div className="flex items-center gap-3 pt-1">
          <Button
            onClick={() => void onSubmit()}
            disabled={submitting || !title.trim() || !content.trim()}
          >
            <HugeiconsIcon
              icon={submitting ? Loading03Icon : SparklesIcon}
              strokeWidth={2}
              className={cn('size-3.5', submitting && 'animate-spin')}
            />
            {submitting ? 'Embedding…' : t('submitEmbedding')}
          </Button>
        </div>
    </div>
  )
}

/* ---------- Search tab ---------- */

/* 1–20 里真正有人会选的就这几档。原来是个 number 输入框，配一行「范围 1–20」的
 * 说明 —— 一个只有四种合理答案的旋钮不该做成自由输入。 */
const TOP_K_OPTIONS = [3, 5, 10, 20]

function SearchTab() {
  const t = useT(kbCopy)
  const [query, setQuery] = useState('')
  const [topK, setTopK] = useState(5)
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const [hits, setHits] = useState<KbHit[] | null>(null)

  async function onSubmit() {
    if (!query.trim()) return
    setLoading(true)
    setError(null)
    setHits(null)
    try {
      const r = await api.kbSearch({ query: query.trim(), top_k: topK })
      setHits(r)
    } catch (e) {
      const err = e as ApiError
      setError(err.message)
    } finally {
      setLoading(false)
    }
  }

  const embedMissing = isEmbedNotConfigured(error)

  const rows: EntityRow[] = (hits ?? []).map((h, i) => {
    // Always suffix the row index so duplicate chunk_id/doc_id across hits
    // can't make two rows expand together.
    const id = `${h.chunk_id ?? h.doc_id}-${i}`
    return {
      id,
      icon: (
        <IconTile variant="soft" size="sm" className="mt-0.5 shrink-0">
          <HugeiconsIcon icon={FileTextIcon} strokeWidth={2} aria-hidden="true" />
        </IconTile>
      ),
      title: h.title || t('untitled'),
      meta: <code className="font-mono text-xs">{h.doc_id ?? '—'}</code>,
      action: (
        <Badge size="sm" variant={scoreVariant(h.score)} className="shrink-0 font-mono tabular-nums">
          {t('similarity', { score: h.score === null ? '—' : h.score.toFixed(3) })}
        </Badge>
      ),
      body: <HitBody text={h.content ?? ''} />,
    }
  })

  return (
    <div className="flex flex-col gap-5">
      <section aria-label={t('secSearchForm')}>
        <Frame className="w-full">
          <FramePanel className="flex flex-wrap items-center gap-2 p-4!">
            <InputGroup className="min-w-56 flex-1">
              <InputGroupAddon align="inline-start">
                <HugeiconsIcon icon={Search01Icon} strokeWidth={2} aria-hidden="true" />
              </InputGroupAddon>
              <InputGroupInput
                value={query}
                onChange={(e) => setQuery(e.target.value)}
                onKeyDown={(e) => {
                  if (e.key === 'Enter') {
                    e.preventDefault()
                    void onSubmit()
                  }
                }}
                placeholder={t('searchPlaceholder')}
                aria-label={t('searchAria')}
              />
              {query.length > 0 && (
                <InputGroupAddon align="inline-end">
                  <InputGroupButton aria-label={t('clear')} size="icon-xs" onClick={() => setQuery('')}>
                    <HugeiconsIcon icon={Cancel01Icon} strokeWidth={2} aria-hidden="true" />
                  </InputGroupButton>
                </InputGroupAddon>
              )}
            </InputGroup>

            <Select value={String(topK)} onValueChange={(v) => setTopK(Number(v))}>
              <SelectTrigger className="w-[130px]" aria-label={t('topKAria')}>
                <SelectValue>{(v) => t('topK', { n: String(v) })}</SelectValue>
              </SelectTrigger>
              <SelectContent>
                {TOP_K_OPTIONS.map((k) => (
                  <SelectItem key={k} value={String(k)}>{t('topK', { n: k })}</SelectItem>
                ))}
              </SelectContent>
            </Select>

            <Button onClick={() => void onSubmit()} disabled={loading || !query.trim()}>
              <HugeiconsIcon
                icon={loading ? Loading03Icon : SparklesIcon}
                strokeWidth={2}
                className={cn('size-3.5', loading && 'animate-spin')}
              />
              {loading ? t('searching') : t('searchAction')}
            </Button>
          </FramePanel>
        </Frame>
      </section>

      {error && (
        <ErrorBanner message={embedMissing ? embedNotConfiguredHint() : error} />
      )}

      {hits !== null && hits.length === 0 && !error && (
        <Empty>
          <EmptyHeader>
            <EmptyMedia variant="icon">
              <HugeiconsIcon icon={Search01Icon} strokeWidth={2} />
            </EmptyMedia>
            <EmptyTitle>{t('noHitsTitle')}</EmptyTitle>
            <EmptyDescription>{t('noHitsDesc')}</EmptyDescription>
          </EmptyHeader>
        </Empty>
      )}

      {hits !== null && hits.length > 0 && (
        <section aria-label={t('secHits')}>
          <EntityList
            title={t('hitsTitle')}
            description={t('hitsDesc', { n: hits.length })}
            rows={rows}
          />
        </section>
      )}
    </div>
  )
}

const TRUNCATE_AT = 400

/* 长片段先截到 400 字，点一下展开。用局部 state 而不是 `Collapsible` —— 这里没有
 * 折叠动画，也没有第二个触发点，一个 open 布尔就够了。 */
function HitBody({ text }: { text: string }) {
  const t = useT(kbCopy)
  const sh = useT(shellCopy)
  const [open, setOpen] = useState(false)
  const truncated = text.length > TRUNCATE_AT
  const display = open || !truncated ? text : text.slice(0, TRUNCATE_AT) + '…'
  return (
    <div className="ps-[2.625rem]">
      <div className="rounded-md bg-muted/50 px-3 py-2.5 text-sm leading-relaxed whitespace-pre-wrap">
        {display}
      </div>
      {truncated && (
        <Button
          variant="link"
          size="sm"
          className="mt-1 h-auto p-0 text-xs"
          onClick={() => setOpen((v) => !v)}
        >
          {open ? sh('collapse') : t('expandFull')}
        </Button>
      )}
    </div>
  )
}

/* ---------- Shared bits ---------- */

function ErrorBanner({ message }: { message: string }) {
  return (
    <Alert variant="destructive">
      <HugeiconsIcon icon={AlertCircleIcon} strokeWidth={2} className="size-4" />
      <AlertDescription>{message}</AlertDescription>
    </Alert>
  )
}

/* 相似度只有三档读法：稳、还行、勉强。数字本身也在药丸里，颜色只是让人不用去
 * 比较 0.78 和 0.83。 */
function scoreVariant(score: number | null): 'success-light' | 'primary-light' | 'secondary' {
  if (score === null) return 'secondary'
  if (score >= 0.85) return 'success-light'
  if (score >= 0.75) return 'primary-light'
  return 'secondary'
}

/* 「刚刚 / N 分钟前」那四档走 common.ts —— 查询历史（lib/history.ts）用的是同
   一批词。这里比它多一档「N 个月前」，超过一年直接写日期。 */
function formatRelativeOrIso(iso: string | null): string {
  if (!iso) return translate(kbCopy, 'timeUnknown')
  const ts = Date.parse(iso)
  if (Number.isNaN(ts)) return iso
  const diff = Date.now() - ts
  const sec = Math.floor(diff / 1000)
  if (sec < 60) return translate(commonCopy, 'justNow')
  const min = Math.floor(sec / 60)
  if (min < 60) return translate(commonCopy, 'minutesAgo', { n: min })
  const hr = Math.floor(min / 60)
  if (hr < 24) return translate(commonCopy, 'hoursAgo', { n: hr })
  const day = Math.floor(hr / 24)
  if (day < 30) return translate(commonCopy, 'daysAgo', { n: day })
  const mo = Math.floor(day / 30)
  if (mo < 12) return translate(kbCopy, 'monthsAgo', { n: mo })
  return iso.slice(0, 10)
}
