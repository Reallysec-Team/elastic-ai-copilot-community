import { useEffect, useState } from 'react'
import { HugeiconsIcon } from '@hugeicons/react'
import { AlertCircleIcon, Delete02Icon, PencilIcon, PlusIcon } from '@hugeicons/core-free-icons'
import { GatedButton } from '@/components/gated-button'
import { api, type ApiError, type BaselineRuleDoc } from '@/lib/api'
import { Button } from '@/components/ui/button'
import { Frame, FramePanel } from '@/components/reui/frame'
import { Dialog, DialogContent, DialogFooter, DialogHeader, DialogTitle } from '@/components/ui/dialog'
import {
  Select as UiSelect,
  SelectContent as UiSelectContent,
  SelectItem as UiSelectItem,
  SelectTrigger as UiSelectTrigger,
  SelectValue as UiSelectValue,
} from '@/components/ui/select'
import { Input } from '@/components/ui/input'
import { Textarea } from '@/components/ui/textarea'
import { Label } from '@/components/ui/label'
import { Checkbox } from '@/components/ui/checkbox'
import { cn } from '@/lib/utils'
import { useT } from '@/lib/i18n'
import { baselineCopy } from '@/locales/baseline'
import { commonCopy } from '@/locales/common'
import { severityLabel } from '@/lib/severity'
import { BlockError, BlockLoading } from '@/components/shared/block-states'

const OPERATORS = [
  'expect_empty',
  'expect_nonempty',
  'equals',
  'not_equals',
  'gte',
  'lte',
  'manual_review',
  'eol',
] as const

type Operator = (typeof OPERATORS)[number]

const SEVERITIES = ['low', 'medium', 'high', 'critical'] as const

const ON_MISSING = ['pass', 'fail', 'error'] as const

/** equals / not_equals / gte / lte / expect_empty / expect_nonempty compare a field. */
function operatorNeedsField(op: string): boolean {
  return ['equals', 'not_equals', 'gte', 'lte', 'expect_empty', 'expect_nonempty'].includes(op)
}
/** equals / not_equals / gte / lte also need an expected value. */
function operatorNeedsExpected(op: string): boolean {
  return ['equals', 'not_equals', 'gte', 'lte'].includes(op)
}
/** Every operator except manual_review requires a collect query. */
function operatorNeedsQuery(op: string): boolean {
  return op !== 'manual_review'
}

export function BaselineRulesTab() {
  const t = useT(baselineCopy)
  const c = useT(commonCopy)
  const [rules, setRules] = useState<BaselineRuleDoc[]>([])
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)
  const [editing, setEditing] = useState<{ rule: BaselineRuleDoc | null; creating: boolean } | null>(null)
  const [confirmDelete, setConfirmDelete] = useState<string | null>(null)
  /* 内置规则库 127 条，一路滚到底才能找到某一条。过滤在前端做 —— 整份规则本来
     就已经全量取回来了，加一次请求没有意义。 */
  const [q, setQ] = useState('')

  async function load() {
    setLoading(true)
    setError(null)
    try {
      const r = await api.baselineRules()
      setRules(r.rules)
    } catch (e) {
      setError((e as ApiError).message || t('errLoadRules'))
    } finally {
      setLoading(false)
    }
  }

  useEffect(() => {
    void load()
  }, [])

  async function handleDelete(ruleId: string) {
    setError(null)
    try {
      await api.baselineDeleteRule(ruleId)
      setConfirmDelete(null)
      await load()
    } catch (e) {
      setError((e as ApiError).message || t('errDelete'))
    }
  }

  const needle = q.trim().toLowerCase()
  const shown = needle
    ? rules.filter((r) =>
        `${r.rule_id} ${r.title} ${r.category} ${r.platform ?? ''}`.toLowerCase().includes(needle),
      )
    : rules

  return (
    <div>
      <div className="mb-3 flex flex-wrap items-center justify-between gap-2">
        <div className="flex min-w-0 items-center gap-3">
          <span className="shrink-0 text-xs text-muted-foreground">
            {q.trim()
              ? t('rulesCountFiltered', { shown: shown.length, total: rules.length })
              : t('rulesCountAll', { n: rules.length })}
          </span>
          <Input
            value={q}
            onChange={(e) => setQ(e.target.value)}
            placeholder={t('rulesFilterPlaceholder')}
            aria-label={t('rulesFilterAria')}
            className="h-8 w-64"
          />
        </div>
        <GatedButton
          gate="admin"
          variant="default" className="rounded-full"
          size="sm"
          onClick={() => setEditing({ rule: null, creating: true })}
        >
          <HugeiconsIcon icon={PlusIcon} strokeWidth={2} className="size-4" /> {t('newRule')}
        </GatedButton>
      </div>

      {error && <BlockError message={error} className="mb-4" />}

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
                    <th scope="col" className="px-3 py-2 font-medium">{t('colRuleId')}</th>
                    <th scope="col" className="px-3 py-2 font-medium">{t('colTitle')}</th>
                    <th scope="col" className="px-3 py-2 font-medium">{t('colCategory')}</th>
                    <th scope="col" className="px-3 py-2 font-medium">{t('colPlatform')}</th>
                    <th scope="col" className="px-3 py-2 font-medium">{t('colSeverity')}</th>
                    <th scope="col" className="px-3 py-2 font-medium">{t('colJudgeOp')}</th>
                    <th scope="col" className="px-3 py-2 font-medium">{t('colEnabled')}</th>
                    <th scope="col" className="px-3 py-2 font-medium">{t('colSource')}</th>
                    <th scope="col" className="px-3 py-2 font-medium text-right">{t('colActions')}</th>
                  </tr>
                </thead>
                <tbody>
                  {shown.map((rule) => (
                    <tr key={rule.rule_id} className="border-b border-border hover:bg-muted/50">
                      <td className="px-3 py-2 font-mono text-xs">{rule.rule_id}</td>
                      <td className="px-3 py-2">{rule.title}</td>
                      <td className="px-3 py-2 text-xs text-muted-foreground">{rule.category}</td>
                      <td className="px-3 py-2 text-xs text-muted-foreground">{rule.platform || '—'}</td>
                      <td className="px-3 py-2 text-xs">{severityLabel(rule.severity)}</td>
                      <td className="px-3 py-2 font-mono text-xs">{rule.judge.operator}</td>
                      <td className="px-3 py-2">
                        <span
                          className={cn(
                            'rounded-full px-2 py-0.5 text-xs font-medium',
                            rule.enabled === false
                              ? 'bg-secondary text-muted-foreground'
                              : 'bg-success/12 text-success',
                          )}
                        >
                          {rule.enabled === false ? t('ruleDisabled') : t('ruleEnabled')}
                        </span>
                      </td>
                      <td className="px-3 py-2 text-xs text-muted-foreground">
                        {rule.source === 'custom' ? t('srcCustom') : t('srcBuiltin')}
                      </td>
                      <td className="px-3 py-2">
                        <div className="flex items-center justify-end gap-1">
                          <GatedButton
                            gate="admin"
                            variant="ghost"
                            size="sm"
                            onClick={() => setEditing({ rule, creating: false })}
                          >
                            <HugeiconsIcon icon={PencilIcon} strokeWidth={2} className="size-3.5" /> {c('edit')}
                          </GatedButton>
                          {confirmDelete === rule.rule_id ? (
                            <button
                              onClick={() => handleDelete(rule.rule_id)}
                              className="rounded-full bg-destructive/12 px-3 py-1 text-xs font-medium text-destructive transition hover:opacity-80"
                            >
                              {t('confirmDelete')}
                            </button>
                          ) : (
                            <GatedButton
                              gate="admin"
                              variant="ghost"
                              size="sm"
                              onClick={() => setConfirmDelete(rule.rule_id)}
                            >
                              <HugeiconsIcon icon={Delete02Icon} strokeWidth={2} className="size-3.5" /> {c('delete')}
                            </GatedButton>
                          )}
                        </div>
                      </td>
                    </tr>
                  ))}
                  {rules.length === 0 && (
                    <tr>
                      <td colSpan={9} className="px-3 py-10 text-center text-sm text-muted-foreground">
                        {t('rulesEmpty')}
                      </td>
                    </tr>
                  )}
                </tbody>
              </table>
            </div>
          </FramePanel>
        </Frame>
      )}

      {editing && (
        <RuleEditorDialog
          creating={editing.creating}
          initial={editing.rule}
          onClose={() => setEditing(null)}
          onSaved={() => {
            setEditing(null)
            void load()
          }}
        />
      )}
    </div>
  )
}

type Draft = {
  rule_id: string
  title: string
  category: string
  platform: string
  severity: (typeof SEVERITIES)[number]
  operator: Operator
  field: string
  expected: string
  on_missing: (typeof ON_MISSING)[number]
  query: string
  remediation_template: string
  standard_refs: string
  enabled: boolean
}

function draftFromRule(rule: BaselineRuleDoc | null): Draft {
  return {
    rule_id: rule?.rule_id ?? '',
    title: rule?.title ?? '',
    category: rule?.category ?? '',
    platform: rule?.platform ?? '',
    severity: rule?.severity ?? 'medium',
    operator: (rule?.judge.operator as Operator) ?? 'expect_empty',
    field: rule?.judge.field ?? '',
    expected: rule?.judge.expected ?? '',
    on_missing: rule?.judge.on_missing ?? 'error',
    query: rule?.collect?.query ?? '',
    remediation_template: rule?.remediation_template ?? '',
    standard_refs: (rule?.standard_refs ?? []).join(', '),
    enabled: rule?.enabled !== false,
  }
}

function RuleEditorDialog({
  creating,
  initial,
  onClose,
  onSaved,
}: {
  creating: boolean
  initial: BaselineRuleDoc | null
  onClose: () => void
  onSaved: () => void
}) {
  const t = useT(baselineCopy)
  const c = useT(commonCopy)
  const [draft, setDraft] = useState<Draft>(() => draftFromRule(initial))
  const [err, setErr] = useState<string | null>(null)
  const [saving, setSaving] = useState(false)

  function patch(partial: Partial<Draft>) {
    setDraft((d) => ({ ...d, ...partial }))
  }

  const op = draft.operator
  const showField = operatorNeedsField(op)
  const showExpected = operatorNeedsExpected(op)
  const showQuery = operatorNeedsQuery(op)

  /** Lightweight client hint; the backend 400 remains authoritative. */
  function clientHint(): string | null {
    if (!draft.rule_id.trim()) return t('errRuleIdRequired')
    if (!draft.title.trim()) return t('errTitleRequired')
    if (showField && !draft.field.trim()) return t('errNeedsField', { op })
    if (showExpected && !draft.expected.trim()) return t('errNeedsExpected', { op })
    if (showQuery && !draft.query.trim()) return t('errNeedsQuery', { op })
    return null
  }

  async function handleSave() {
    setErr(null)
    const hint = clientHint()
    if (hint) {
      setErr(hint)
      return
    }
    const refs = draft.standard_refs
      .split(',')
      .map((s) => s.trim())
      .filter(Boolean)
    const rule: BaselineRuleDoc = {
      rule_id: draft.rule_id.trim(),
      title: draft.title.trim(),
      category: draft.category.trim(),
      platform: draft.platform.trim(),
      severity: draft.severity,
      judge: {
        operator: op,
        ...(showField ? { field: draft.field.trim() } : {}),
        ...(showExpected ? { expected: draft.expected.trim() } : {}),
        on_missing: draft.on_missing,
      },
      ...(showQuery ? { collect: { query: draft.query } } : {}),
      standard_refs: refs,
      remediation_template: draft.remediation_template,
      enabled: draft.enabled,
    }
    setSaving(true)
    try {
      await api.baselineUpsertRule(rule)
      onSaved()
    } catch (e) {
      setErr((e as ApiError).message || t('errSave'))
    } finally {
      setSaving(false)
    }
  }

  return (
    <Dialog open onOpenChange={(v) => !v && onClose()}>
      <DialogContent className="flex flex-col gap-0 overflow-hidden p-0 sm:max-w-[720px] max-h-[86vh]">
        {/* 原来是 `<DialogHeader title=... />` —— 这个 DialogHeader 不认 title 这个
            prop，于是弹窗根本没有标题（也没有可访问名），第一行直接是「规则 ID」
            那个字段标签。 */}
        <DialogHeader className="border-b px-6 pt-5 pb-4">
          <DialogTitle>{creating ? t('dlgCreateRule') : t('dlgEditRule')}</DialogTitle>
        </DialogHeader>
        <div className="flex-1 min-h-0 space-y-4 overflow-auto px-6 py-5">
          <Field label={t('fieldRuleId')}>
            <Input
              value={draft.rule_id}
              onChange={(e) => patch({ rule_id: e.target.value })}
              placeholder="linux.ssh.root_login"
              className="font-mono text-12"
              disabled={!creating}
            />
          </Field>

          <Field label={t('fieldTitle')}>
            <Input value={draft.title} onChange={(e) => patch({ title: e.target.value })} placeholder={t('titlePlaceholder')} />
          </Field>

          <div className="grid grid-cols-2 gap-3">
            <Field label={t('colCategory')}>
              <Input value={draft.category} onChange={(e) => patch({ category: e.target.value })} placeholder="access-control" />
            </Field>
            <Field label={t('fieldPlatform')}>
              <Input value={draft.platform} onChange={(e) => patch({ platform: e.target.value })} placeholder="linux" />
            </Field>
          </div>

          <div className="grid grid-cols-2 gap-3">
            <Field label={t('colSeverity')}>
              <Select value={draft.severity} onChange={(v) => patch({ severity: v as Draft['severity'] })} options={SEVERITIES} />
            </Field>
            <Field label={t('fieldJudgeOp')}>
              <Select value={draft.operator} onChange={(v) => patch({ operator: v as Operator })} options={OPERATORS} />
            </Field>
          </div>

          {(showField || showExpected) && (
            <div className="grid grid-cols-2 gap-3">
              {showField && (
                <Field label={t('fieldJudgeField')}>
                  <Input value={draft.field} onChange={(e) => patch({ field: e.target.value })} placeholder="value" className="font-mono text-12" />
                </Field>
              )}
              {showExpected && (
                <Field label={t('fieldExpectedInput')}>
                  <Input value={draft.expected} onChange={(e) => patch({ expected: e.target.value })} placeholder="no" className="font-mono text-12" />
                </Field>
              )}
            </div>
          )}

          <Field label={t('fieldOnMissing')}>
            <Select value={draft.on_missing} onChange={(v) => patch({ on_missing: v as Draft['on_missing'] })} options={ON_MISSING} />
          </Field>

          {showQuery && (
            <Field label={t('fieldCollectQuery')}>
              <Textarea
                value={draft.query}
                onChange={(e) => patch({ query: e.target.value })}
                spellCheck={false}
                className="min-h-[110px] font-mono text-12"
                placeholder="SELECT value FROM ..."
              />
            </Field>
          )}

          <Field label={t('fieldRemediationTpl')}>
            <Textarea
              value={draft.remediation_template}
              onChange={(e) => patch({ remediation_template: e.target.value })}
              className="min-h-[70px]"
              placeholder={t('remediationPlaceholder')}
            />
          </Field>

          <Field label={t('fieldStandardRefsInput')}>
            <Input
              value={draft.standard_refs}
              onChange={(e) => patch({ standard_refs: e.target.value })}
              placeholder={t('standardRefsPlaceholder')}
              className="font-mono text-12"
            />
          </Field>

          <div className="flex items-center gap-2 text-sm text-foreground">
            <Checkbox id="rule-enabled" checked={draft.enabled} onCheckedChange={(v) => patch({ enabled: v })} />
            <Label htmlFor="rule-enabled">{t('enableThisRule')}</Label>
          </div>

          {err && (
            <div className="flex items-start gap-2 rounded-md bg-destructive/10 px-3 py-2">
              <HugeiconsIcon icon={AlertCircleIcon} strokeWidth={2} className="mt-0.5 size-3.5 shrink-0 text-destructive" />
              <span className="text-xs text-destructive">{err}</span>
            </div>
          )}
        </div>
        <DialogFooter className="mx-0 mb-0 px-6 py-4">
          <Button variant="outline" onClick={onClose} disabled={saving}>
            {c('cancel')}
          </Button>
          <Button variant="default" className="rounded-full" onClick={handleSave} disabled={saving}>
            {saving ? `${c('saving')}…` : c('save')}
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  )
}

function Field({ label, children }: { label: string; children: React.ReactNode }) {
  return (
    <label className="block space-y-1.5">
      <Label className="font-mono text-xs text-muted-foreground">{label}</Label>
      {children}
    </label>
  )
}

function Select({
  value,
  onChange,
  options,
}: {
  value: string
  onChange: (v: string) => void
  options: readonly string[]
}) {
  /* 这三个下拉原来是原生 <select>：字号、圆角、箭头都和全站其它下拉不是一套，
     深色模式下还会露出系统配色。换成和检测规则页同一个 Select 原语。 */
  return (
    <UiSelect value={value} onValueChange={(v) => onChange(String(v ?? value))}>
      <UiSelectTrigger className="w-full">
        <UiSelectValue>{(v) => String(v)}</UiSelectValue>
      </UiSelectTrigger>
      <UiSelectContent>
        {options.map((o) => (
          <UiSelectItem key={o} value={o}>{o}</UiSelectItem>
        ))}
      </UiSelectContent>
    </UiSelect>
  )
}
