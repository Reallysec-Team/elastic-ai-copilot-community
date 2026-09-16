import { describe, expect, it } from 'vitest'
import { mergeColumns } from './prefs'

/* 「全部重置」写的墓碑要压过别的设备上更早的列集，否则合并时会被推回来。 */
describe('mergeColumns after resetColumns', () => {
  it('drops local column sets older than the __reset__ tombstone', () => {
    const local = { columns: { 'logs-*': ['a', 'b'] }, columnsUpdatedAt: { 'logs-*': 1000 } }
    const server = { columns: {}, columnsUpdatedAt: { __reset__: 2000 } }
    expect(mergeColumns(local, server).columns).toEqual({})
  })
  it('keeps a local set picked after the reset', () => {
    const local = { columns: { 'logs-*': ['a'] }, columnsUpdatedAt: { 'logs-*': 3000 } }
    const server = { columns: {}, columnsUpdatedAt: { __reset__: 2000 } }
    expect(mergeColumns(local, server).columns).toEqual({ 'logs-*': ['a'] })
  })
  it('carries the tombstone through the merge so the next savePref does not drop it', () => {
    const local = { columns: { 'logs-*': ['a', 'b'] }, columnsUpdatedAt: { 'logs-*': 1000 } }
    const server = { columns: {}, columnsUpdatedAt: { __reset__: 2000 } }
    expect(mergeColumns(local, server).columnsUpdatedAt).toEqual({ __reset__: 2000 })
    // 本机自己刚重置、服务端还是旧的：墓碑也要留着。
    const local2 = { columns: {}, columnsUpdatedAt: { __reset__: 5000 } }
    const server2 = { columns: { 'logs-*': ['a'] }, columnsUpdatedAt: { 'logs-*': 4000 } }
    expect(mergeColumns(local2, server2)).toEqual({ columns: {}, columnsUpdatedAt: { __reset__: 5000 } })
  })
})
