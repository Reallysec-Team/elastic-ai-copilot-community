import { translate } from '@/lib/i18n'
import { analysisCopy } from '@/locales/analysis'
import { libCopy } from '@/locales/lib'

/**
 * 从一条归档记录接出一个能直接问的问题。
 *
 * `subject` 是 `{type, value}`：调查记录里是受影响资产（host / ip / user…），
 * 结果解读记录里是当初那句问题，分诊记录里是「N clusters」—— 最后这种接不出
 * 问题，返回 null，按钮就不显示。
 */
export function followUpQuestion(rec: { kind: string; subject?: { type?: string; value?: string } }): string | null {
  const type = rec.subject?.type ?? ''
  const value = (rec.subject?.value ?? '').trim()
  if (!value) return null
  if (type === 'triage') return null
  if (type === 'query') return value
  return translate(libCopy, 'afSubjectQuestion', { value })
}

/**
 * 归档记录的标题。
 *
 * 后端从模型输出里取 `alert_type`，取不到就写字符串 "unknown" —— 归档里于是躺着
 * 一批标题就是 unknown 的记录（实测：ES 里查不到对应原始事件时模型会略过这个
 * 字段）。这些记录已经写进索引了，改后端也追不回来，所以在渲染这一层兜：能用
 * 主体就用主体，再不行按类型说一句中文。
 */
export function recordTitle(rec: {
  kind?: string
  title?: string
  subject?: { type?: string; value?: string }
}): string {
  const t = (rec.title ?? '').trim()
  if (t && t.toLowerCase() !== 'unknown') return t
  const value = (rec.subject?.value ?? '').trim()
  if (value && (rec.subject?.type ?? '') !== 'triage') return value
  return translate(analysisCopy, rec.kind === 'triage' ? 'detailTriage' : 'detailInvestigation')
}
