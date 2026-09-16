import { useCallback, useSyncExternalStore } from 'react'

import { getPrefs, savePref } from '@/lib/prefs'

/*
 * 界面语言。
 *
 * 为什么不上 i18n 库：这个产品的文案是中文优先写的，键值对加插值就够了，
 * react-i18next 那套（命名空间、懒加载、复数规则、后备链）解决的问题这里一个都没有，
 * 而它会把「这句话在哪」从一次跳转变成一次全局搜索。真需要复数或日期本地化时，
 * Intl 已经在浏览器里。
 *
 * 语言存在 **per-user prefs**（`lib/prefs`），不是 settings.yml：后者是全局的，一个
 * 管理员切成英文会把所有人的界面一起切掉。prefs 本地即时生效、跨设备同步，和主题、
 * 默认索引是同一套机制。
 *
 * 文案按页/按块放在 `src/locales/<名字>.ts`，一个 Bundle 就是 { zh, en } 两张同构的
 * 表。分文件不是为了懒加载，是为了让两个人（或两个 agent）改不同的页时不会打架。
 *
 * 用法：
 *   const t = useT(alertsCopy)
 *   <h1>{t('title')}</h1>
 *   <p>{t('matched', { n: 12 })}</p>      // 文案里写 "命中 {n} 条"
 */

export type Lang = 'zh' | 'en'

/** 一块文案：两张同构的表。en 缺键时回落到 zh，界面上不会出现空白或裸键。 */
export interface Bundle<K extends string = string> {
  zh: Record<K, string>
  en: Partial<Record<K, string>>
}

const EVENT = 'rst-lang-changed'

function fromNavigator(): Lang {
  try {
    return navigator.language.toLowerCase().startsWith('zh') ? 'zh' : 'en'
  } catch {
    return 'zh'
  }
}

function read(): Lang {
  const saved = getPrefs().lang
  if (saved === 'zh' || saved === 'en') return saved
  return fromNavigator()
}

// 同步快照：首帧就要拿到语言，不能等一次 effect 翻转，否则整屏文字会闪一下。
let current: Lang = read()

export function getLang(): Lang {
  return current
}

export function setLang(next: Lang): void {
  if (next === current) return
  current = next
  savePref({ lang: next })
  try {
    document.documentElement.lang = next === 'zh' ? 'zh-CN' : 'en'
    // 广播和上面那行一起进 try：没有 document 的环境（node 环境的单测）同样没有
    // window，而 `current` 已经改完了 —— 通知不出去不该让整个调用抛出来。
    window.dispatchEvent(new CustomEvent(EVENT))
  } catch {
    /* 服务端渲染或测试环境里没有 document / window */
  }
}

function subscribe(cb: () => void): () => void {
  window.addEventListener(EVENT, cb)
  return () => window.removeEventListener(EVENT, cb)
}

export function useLang(): Lang {
  return useSyncExternalStore(subscribe, getLang, getLang)
}

/** 把 "命中 {n} 条" 里的占位符换掉。没给的占位符原样留着，方便一眼看出漏了什么。 */
function interpolate(s: string, vars?: Record<string, string | number>): string {
  if (!vars) return s
  return s.replace(/\{(\w+)\}/g, (m, k: string) => (k in vars ? String(vars[k]) : m))
}

export type Translate<K extends string> = (
  key: K,
  vars?: Record<string, string | number>,
) => string

export function useT<K extends string>(bundle: Bundle<K>): Translate<K> {
  const lang = useLang()
  return useCallback(
    (key, vars) => interpolate(bundle[lang][key] ?? bundle.zh[key] ?? key, vars),
    [bundle, lang],
  )
}

/** 组件外（工具函数、事件处理里攒的字符串）用这个；它不订阅，读的是当下的语言。 */
export function translate<K extends string>(
  bundle: Bundle<K>,
  key: K,
  vars?: Record<string, string | number>,
): string {
  return interpolate(bundle[current][key] ?? bundle.zh[key] ?? key, vars)
}
