import { subAggValue } from '@/lib/subAgg'

/*
 * Tiny client-side CSV exporter.
 * - Walks each hit's _source recursively to build a column union (top-level keys
 *   plus 1 level of nested fields).
 * - Quotes values that contain commas, quotes, or newlines per RFC 4180.
 * - Stringifies arrays / objects via JSON.
 * - Prepends a UTF-8 BOM so Excel opens it without mojibake on Chinese strings.
 */

interface ESHit {
  _id?: string
  _source?: Record<string, unknown>
}

export function escapeCell(v: unknown): string {
  if (v === null || v === undefined) return ''
  let s: string
  if (typeof v === 'string') {
    s = v
    // Formula-injection neutralization: if a string cell starts with a char a
    // spreadsheet treats as a formula/command (= + - @, leading Tab or CR),
    // prefix a single quote so Excel/WPS/LibreOffice render it as literal text
    // instead of executing it. Only applies to string values.
    if (/^[=+\-@\t\r]/.test(s)) s = "'" + s
  } else if (typeof v === 'number' || typeof v === 'boolean') s = String(v)
  else s = JSON.stringify(v)
  if (/[",\n\r]/.test(s)) {
    return '"' + s.replace(/"/g, '""') + '"'
  }
  return s
}

function getNested(obj: Record<string, unknown>, path: string): unknown {
  const parts = path.split('.')
  let cur: unknown = obj
  for (const p of parts) {
    if (cur && typeof cur === 'object' && p in (cur as object)) {
      cur = (cur as Record<string, unknown>)[p]
    } else {
      return undefined
    }
  }
  return cur
}

function collectColumns(hits: ESHit[]): string[] {
  const seen = new Set<string>()
  const order: string[] = []
  for (const h of hits) {
    const src = h._source ?? {}
    walk(src, '', seen, order, 0)
  }
  return order.slice(0, 40)
}

function walk(
  obj: Record<string, unknown>,
  prefix: string,
  seen: Set<string>,
  order: string[],
  depth: number,
) {
  if (depth > 2) return
  for (const [k, v] of Object.entries(obj)) {
    const path = prefix ? `${prefix}.${k}` : k
    if (v && typeof v === 'object' && !Array.isArray(v) && depth < 2) {
      walk(v as Record<string, unknown>, path, seen, order, depth + 1)
    } else {
      if (!seen.has(path)) {
        seen.add(path)
        order.push(path)
      }
    }
  }
}

export function hitsToCsv(hits: ESHit[]): string {
  if (hits.length === 0) return '﻿_id\n'
  const cols = ['_id', ...collectColumns(hits)]
  const lines: string[] = []
  lines.push(cols.map(escapeCell).join(','))
  for (const h of hits) {
    const src = h._source ?? {}
    const row = cols.map((c) => {
      if (c === '_id') return escapeCell(h._id ?? '')
      return escapeCell(getNested(src, c))
    })
    lines.push(row.join(','))
  }
  return '﻿' + lines.join('\n') + '\n'
}

/** Flatten a bucketed aggregation (terms / date_histogram) to CSV: one row per
 * bucket with key, doc_count, and any numeric sub-aggregation columns. Lets an
 * analyst export aggregation results — the plain-hits exporter can't (there are
 * no _source docs). */
export function aggBucketsToCsv(
  buckets: Record<string, unknown>[],
  subCols: string[],
): string {
  const cols = ['key', 'doc_count', ...subCols]
  const lines = [cols.map(escapeCell).join(',')]
  for (const b of buckets) {
    const row = [
      escapeCell(b.key_as_string ?? b.key),
      escapeCell(b.doc_count),
      ...subCols.map((c) => escapeCell(subAggValue(b[c]))),
    ]
    lines.push(row.join(','))
  }
  return '﻿' + lines.join('\n') + '\n'
}

export function downloadCsv(filename: string, csv: string): void {
  const blob = new Blob([csv], { type: 'text/csv;charset=utf-8' })
  const url = URL.createObjectURL(blob)
  const a = document.createElement('a')
  a.href = url
  a.download = filename
  document.body.appendChild(a)
  a.click()
  document.body.removeChild(a)
  setTimeout(() => URL.revokeObjectURL(url), 1000)
}
