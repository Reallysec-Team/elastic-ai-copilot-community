import { useCallback, useEffect, useState } from 'react'
import { toast } from 'sonner'

import { api } from '@/lib/api'
import { settingsDiff } from '@/lib/settingsDiff'
import { translate } from '@/lib/i18n'
import { libCopy } from '@/locales/lib'

/*
 * 网关设置的一份草稿 —— 但只管你声明的那几个键。
 *
 * `/api/settings` 一直是「读全量、写差量」（`settingsDiff` 只发改过的键），所以
 * 同一份设置本来就可以由几个屏各管一段。挡路的从来不是接口，是页面把所有键塞在
 * 一个 state 里、共用一条「有未保存的更改」浮条 —— 于是审计转发想搬去「对外通道」
 * 页就搬不动。
 *
 * 声明式地圈一批键之后：脏值判断、保存、保存后回填都只看这批键，两个屏各有各的
 * 浮条，互不干扰。它们也不会打架 —— 写的是差量，没碰的键服务端原样留着。
 */

export interface SettingsDraft<K extends string> {
  draft: Record<K, string>
  original: Record<K, string>
  patch: (key: K, value: string) => void
  /** 这批键里有没有改动。 */
  dirty: boolean
  loading: boolean
  saving: boolean
  error: string | null
  save: () => Promise<void>
  /** 丢弃改动，回到服务端那一份。 */
  revert: () => void
  reload: () => Promise<void>
}

export interface SettingsDraftOptions<K extends string> {
  keys: readonly K[]
  /**
   * 保存前的闸。返回一句话就中止保存并把它 toast 出来，返回 null 放行。
   * 设置页用它拦「改了 es.* 但没测通」—— 存进一个连不上的地址，会把管理员锁在
   * 唯一能改回来的页面外面。
   */
  beforeSave?: (diff: Record<string, string>) => string | null
  /** 首次加载完成后的回调（读只读镜像、探活之类）。 */
  onLoaded?: () => void
}

function pick<K extends string>(
  src: Partial<Record<string, unknown>>, keys: readonly K[],
): Record<K, string> {
  const out = {} as Record<K, string>
  for (const k of keys) {
    const v = src[k]
    out[k] = typeof v === 'string' ? v : ''
  }
  return out
}

export function useSettingsDraft<K extends string>({
  keys, beforeSave, onLoaded,
}: SettingsDraftOptions<K>): SettingsDraft<K> {
  const empty = pick<K>({}, keys)
  const [original, setOriginal] = useState<Record<K, string>>(empty)
  const [draft, setDraft] = useState<Record<K, string>>(empty)
  const [loading, setLoading] = useState(false)
  const [saving, setSaving] = useState(false)
  const [error, setError] = useState<string | null>(null)

  const reload = useCallback(async () => {
    setLoading(true)
    setError(null)
    try {
      const s = await api.getSettings().then((r) => r.settings)
      const next = pick<K>(s as Record<string, unknown>, keys)
      setOriginal(next)
      setDraft(next)
      onLoaded?.()
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e))
    } finally {
      setLoading(false)
    }
    // keys / onLoaded 由调用方以模块常量或稳定引用传入；放进依赖里会让这个
    // effect 每渲染重跑一次，等于每帧拉一次设置。
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [])

  useEffect(() => {
    // eslint-disable-next-line react-hooks/set-state-in-effect -- initial load on mount
    void reload()
  }, [reload])

  const patch = useCallback((key: K, value: string) => {
    setDraft((d) => ({ ...d, [key]: value }))
  }, [])

  const save = useCallback(async () => {
    setSaving(true)
    setError(null)
    try {
      // 只发改过、且不是「已存密文」占位的键 —— 把占位回传会用它覆盖掉真值。
      const diff = settingsDiff(draft, original)
      if (Object.keys(diff).length === 0) {
        setSaving(false)
        return
      }
      const blocked = beforeSave?.(diff) ?? null
      if (blocked) {
        setSaving(false)
        toast.error(blocked)
        return
      }
      const r = await api.saveSettings(diff)
      const next = pick<K>(r.settings as Record<string, unknown>, keys)
      setOriginal(next)
      setDraft(next)
      toast.success(translate(libCopy, 'settingsSavedReloaded'))
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e))
    } finally {
      setSaving(false)
    }
    // 同上：keys 是模块常量，beforeSave 由调用方保证稳定。
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [draft, original, beforeSave])

  const revert = useCallback(() => setDraft(original), [original])

  const dirty = keys.some((k) => draft[k] !== original[k])

  return { draft, original, patch, dirty, loading, saving, error, save, revert, reload }
}
