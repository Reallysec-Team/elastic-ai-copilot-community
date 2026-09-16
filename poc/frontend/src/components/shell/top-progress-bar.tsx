import * as React from 'react'
import { useLocation } from '@tanstack/react-router'

/*
 * roster's TopProgressBar (`app/layouts/top-progress-bar.tsx`), verbatim in
 * behaviour.
 *
 * It replaces the centred `RouteFallback` pill this app showed while a lazy
 * route chunk loaded: a spinner in the middle of an empty content column reads
 * as "the page is broken" for the ~150ms it is usually up, while a 2px bar at
 * the top of the viewport reads as "the thing you clicked is coming".
 *
 * A capture-phase click listener starts the ramp — react-router gives no
 * navigation-start event, and by the time `useLocation` changes the fetch is
 * already done. The bar is mounted outside the Suspense boundary, or it would
 * unmount at the exact moment the page it reports on arrives.
 */

const TAU_MS = 1100 // ramp time-constant: lower = reaches CAP faster
const CAP = 90 // ramp asymptote (%) while waiting for the route
const MIN_VISIBLE_MS = 150 // minimum on-screen time before finishing
const FILL_MS = 180 // smooth glide to 100%
const FADE_MS = 200 // gentle fade after the fill
const SAFETY_MS = 12_000 // a click that never navigates must still clear

type Phase = 'idle' | 'loading' | 'filling' | 'fading'

export function TopProgressBar() {
  /* `searchStr` 而不是 `search`：TanStack 的 `search` 是解好的对象，
     拼进模板串会变成 `[object Object]`，所有路由的 key 就一样了。 */
  const { pathname, searchStr } = useLocation()
  const routeKey = `${pathname}${searchStr}`

  const [phase, setPhase] = React.useState<Phase>('idle')
  const [progress, setProgress] = React.useState(0)

  // Mirrors `phase` for the callbacks below: they run from rAF and timeouts,
  // which close over the render they were created in.
  const phaseRef = React.useRef<Phase>('idle')
  const startedAtRef = React.useRef(0)
  const rafRef = React.useRef<number | null>(null)
  const timersRef = React.useRef<number[]>([])
  const prevKeyRef = React.useRef(routeKey)

  const applyPhase = (next: Phase) => {
    phaseRef.current = next
    setPhase(next)
  }

  const cancelRaf = () => {
    if (rafRef.current != null) {
      window.cancelAnimationFrame(rafRef.current)
      rafRef.current = null
    }
  }

  const clearTimers = () => {
    timersRef.current.forEach((id) => window.clearTimeout(id))
    timersRef.current = []
  }

  const later = (fn: () => void, ms: number) => {
    timersRef.current.push(window.setTimeout(fn, ms))
  }

  const tick = React.useCallback(() => {
    const elapsed = performance.now() - startedAtRef.current
    setProgress(CAP * (1 - Math.exp(-elapsed / TAU_MS)))
    rafRef.current = window.requestAnimationFrame(tick)
  }, [])

  const finish = React.useCallback(() => {
    cancelRaf()
    applyPhase('filling')
    setProgress(100)
    later(() => {
      applyPhase('fading')
      later(() => {
        applyPhase('idle')
        setProgress(0)
      }, FADE_MS)
    }, FILL_MS)
  }, [])

  const done = React.useCallback(() => {
    if (phaseRef.current !== 'loading') return
    clearTimers() // drop the safety timeout
    const elapsed = performance.now() - startedAtRef.current
    later(finish, Math.max(0, MIN_VISIBLE_MS - elapsed))
  }, [finish])

  const start = React.useCallback(() => {
    if (phaseRef.current === 'loading') return
    cancelRaf()
    clearTimers()
    startedAtRef.current = performance.now()
    applyPhase('loading')
    setProgress(0)
    rafRef.current = window.requestAnimationFrame(tick)
    later(done, SAFETY_MS)
  }, [done, tick])

  React.useEffect(() => {
    const onClick = (e: MouseEvent) => {
      if (
        e.defaultPrevented ||
        e.button !== 0 ||
        e.metaKey ||
        e.ctrlKey ||
        e.shiftKey ||
        e.altKey
      ) {
        return
      }
      const anchor = (e.target as Element | null)?.closest('a')
      if (!anchor) return
      const target = anchor.getAttribute('target')
      if (target && target !== '_self') return
      if (anchor.hasAttribute('download')) return
      const rawHref = anchor.getAttribute('href')
      if (!rawHref || rawHref.startsWith('#')) return
      let url: URL
      try {
        url = new URL(anchor.href, window.location.href)
      } catch {
        return
      }
      if (url.origin !== window.location.origin) return
      if (url.pathname.startsWith('/api/')) return
      // Same page: react-router will not fetch anything, so nothing to report.
      if (
        url.pathname === window.location.pathname &&
        url.search === window.location.search
      ) {
        return
      }
      start()
    }
    document.addEventListener('click', onClick, true)
    return () => document.removeEventListener('click', onClick, true)
  }, [start])

  React.useEffect(() => {
    if (prevKeyRef.current !== routeKey) {
      prevKeyRef.current = routeKey
      done()
    }
  }, [routeKey, done])

  React.useEffect(() => () => {
    cancelRaf()
    clearTimers()
  }, [])

  if (phase === 'idle') return null

  const barStyle: React.CSSProperties =
    phase === 'loading'
      ? { width: `${progress}%`, opacity: 1, transition: 'width 0s' }
      : phase === 'filling'
        ? {
            width: '100%',
            opacity: 1,
            transition: `width ${FILL_MS}ms cubic-bezier(0.22, 1, 0.36, 1)`,
          }
        : {
            width: '100%',
            opacity: 0,
            transition: `opacity ${FADE_MS}ms ease-out`,
          }

  return (
    <div
      aria-hidden="true"
      className="pointer-events-none fixed inset-x-0 top-0 z-[100] h-0.5"
    >
      <div
        className="h-full origin-left bg-primary will-change-[width,opacity]"
        style={barStyle}
      />
    </div>
  )
}
