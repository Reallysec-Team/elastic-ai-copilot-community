/*
 * Gateway settings save-diff. Only changed keys are sent, and masked mirrors
 * of already-stored secrets (rendered by the backend as `<set · N chars>`)
 * are never echoed back — posting the sentinel would overwrite the real
 * value with the placeholder.
 */
export function settingsDiff<T extends object>(draft: T, original: T): Record<string, string> {
  const prev = original as Record<string, string>
  const diff: Record<string, string> = {}
  for (const [k, v] of Object.entries(draft) as [string, string][]) {
    if (v === prev[k]) continue
    if (typeof v === 'string' && v.startsWith('<set ·')) continue
    diff[k] = v
  }
  return diff
}
