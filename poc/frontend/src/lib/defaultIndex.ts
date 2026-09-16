/*
 * Which index a fresh install should start on.
 *
 * Every surface used to hardcode `kibana_sample_data_logs`. Customers bring
 * their own ELK and never have that index, so the very first query of a new
 * deployment failed with index_not_found_exception — the worst possible first
 * impression. Resolve it from the cluster instead, and keep the sample name
 * only as the last-resort literal (the dev stack does seed it).
 */

import { api } from '@/lib/api'
import { getPrefs } from '@/lib/prefs'

const FALLBACK = 'kibana_sample_data_logs'

/** Synchronous best guess for the first paint: the user's saved default, else ''. */
export function cachedDefaultIndex(): string {
  return getPrefs().defaultIndex || ''
}

/**
 * Resolve the index to preselect. The saved preference always wins; otherwise
 * ask ES and take the busiest non-system index — the customer's real log store,
 * not an empty scratch index that happens to sort first.
 */
export async function resolveDefaultIndex(): Promise<string> {
  const pref = getPrefs().defaultIndex
  if (pref) return pref
  try {
    const { indices } = await api.indices()
    const usable = indices
      .filter((i) => !i.name.startsWith('.'))
      .sort((a, b) => (b.doc_count ?? 0) - (a.doc_count ?? 0))
    if (usable[0]) return usable[0].name
  } catch {
    /* ES unreachable / not configured — the picker stays on the fallback and
       the readiness banner is what tells the operator why. */
  }
  return FALLBACK
}
