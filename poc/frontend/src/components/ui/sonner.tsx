import { useEffect, useState } from 'react'
import { Toaster as Sonner, type ToasterProps } from 'sonner'
import { HugeiconsIcon } from '@hugeicons/react'
import {
  Alert02Icon, CheckmarkCircle02Icon, InformationCircleIcon, Loading03Icon,
  MultiplicationSignCircleIcon,
} from '@hugeicons/core-free-icons'

import { getThemeMode, resolvedTheme } from '@/lib/theme'

/*
 * roster's `components/ui/sonner.tsx`, with one adaptation: roster reads the
 * theme from `next-themes`, this app has its own controller in `lib/theme` and
 * broadcasts `rst-theme-changed` when it flips. Everything else — the icon set,
 * the token-backed CSS variables, `cn-toast` — is the template's.
 *
 * It is mounted once, in AppShell. Before it existed the `sonner` toasts the
 * ai-chat block fires (copy, retry, errors) went nowhere: the package was a
 * dependency, the Toaster was never rendered.
 */
const Toaster = (props: ToasterProps) => {
  const [theme, setTheme] = useState<'light' | 'dark'>(() => resolvedTheme())

  useEffect(() => {
    const sync = () => setTheme(resolvedTheme(getThemeMode()))
    window.addEventListener('rst-theme-changed', sync)
    // 'system' mode has no event of its own — the OS switch is what moves it.
    const mq = window.matchMedia('(prefers-color-scheme: dark)')
    mq.addEventListener('change', sync)
    return () => {
      window.removeEventListener('rst-theme-changed', sync)
      mq.removeEventListener('change', sync)
    }
  }, [])

  return (
    <Sonner
      theme={theme}
      className="toaster group"
      icons={{
        success: <HugeiconsIcon icon={CheckmarkCircle02Icon} strokeWidth={2} className="size-4" />,
        info: <HugeiconsIcon icon={InformationCircleIcon} strokeWidth={2} className="size-4" />,
        warning: <HugeiconsIcon icon={Alert02Icon} strokeWidth={2} className="size-4" />,
        error: <HugeiconsIcon icon={MultiplicationSignCircleIcon} strokeWidth={2} className="size-4" />,
        loading: <HugeiconsIcon icon={Loading03Icon} strokeWidth={2} className="size-4 animate-spin" />,
      }}
      style={
        {
          '--normal-bg': 'var(--popover)',
          '--normal-text': 'var(--popover-foreground)',
          '--normal-border': 'var(--border)',
          '--border-radius': 'var(--radius)',
        } as React.CSSProperties
      }
      toastOptions={{ classNames: { toast: 'cn-toast' } }}
      {...props}
    />
  )
}

export { Toaster }
