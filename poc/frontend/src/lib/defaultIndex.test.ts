import { describe, expect, it, vi, beforeEach } from 'vitest'

// Tests run in the node environment (no localStorage), so the prefs store is
// mocked rather than driven through its browser backing.
vi.mock('@/lib/api', () => ({ api: { indices: vi.fn() } }))
vi.mock('@/lib/prefs', () => ({ getPrefs: vi.fn() }))

import { api } from '@/lib/api'
import { getPrefs } from '@/lib/prefs'
import { cachedDefaultIndex, resolveDefaultIndex } from './defaultIndex'

const indices = api.indices as unknown as ReturnType<typeof vi.fn>
const prefs = getPrefs as unknown as ReturnType<typeof vi.fn>

function entry(name: string, doc_count: number) {
  return { name, kind: 'index', attributes: [], doc_count, store_size: '1b', health: 'green' }
}

describe('resolveDefaultIndex', () => {
  beforeEach(() => {
    indices.mockReset()
    prefs.mockReset()
    prefs.mockReturnValue({})
  })

  it('prefers the saved preference and never calls ES', async () => {
    prefs.mockReturnValue({ defaultIndex: 'my-logs-*' })
    expect(cachedDefaultIndex()).toBe('my-logs-*')
    await expect(resolveDefaultIndex()).resolves.toBe('my-logs-*')
    expect(indices).not.toHaveBeenCalled()
  })

  it('picks the busiest non-system index from the cluster', async () => {
    indices.mockResolvedValue({
      indices: [entry('.internal-scratch', 999), entry('tiny-index', 3), entry('customer-logs', 4000)],
    })
    await expect(resolveDefaultIndex()).resolves.toBe('customer-logs')
  })

  it('falls back to the sample index when ES is unreachable', async () => {
    indices.mockRejectedValue(new Error('ECONNREFUSED'))
    await expect(resolveDefaultIndex()).resolves.toBe('kibana_sample_data_logs')
  })

  it('returns an empty string when nothing is saved yet', () => {
    expect(cachedDefaultIndex()).toBe('')
  })
})
