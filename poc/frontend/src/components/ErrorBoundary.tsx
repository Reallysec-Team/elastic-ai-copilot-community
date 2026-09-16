import { Component, type ErrorInfo, type ReactNode } from 'react'
import { translate } from '@/lib/i18n'
import { componentsCopy } from '@/locales/components'

/*
 * Route-level error boundary. A render-time crash in any page shows a
 * Geist-styled recovery card instead of white-screening the whole SPA.
 *
 * `resetKey` (wire it to the current pathname) clears the error when the
 * user navigates away — so a broken page doesn't trap them.
 */

interface Props {
  children: ReactNode
  resetKey?: string
}

interface State {
  error: Error | null
}

export class ErrorBoundary extends Component<Props, State> {
  state: State = { error: null }

  static getDerivedStateFromError(error: Error): State {
    return { error }
  }

  componentDidCatch(error: Error, info: ErrorInfo): void {
    // Surface to the console for dev; a prod build could POST this to the
    // gateway's audit/error sink later.
    console.error('[ErrorBoundary]', error, info.componentStack)
  }

  componentDidUpdate(prev: Props): void {
    if (prev.resetKey !== this.props.resetKey && this.state.error) {
      this.setState({ error: null })
    }
  }

  render(): ReactNode {
    if (!this.state.error) return this.props.children
    return (
      <div className="flex min-h-[50vh] flex-col items-center justify-center gap-5 px-6">
        <div className="inline-flex items-center gap-2 rounded-full bg-destructive-subtle px-3 py-1 [box-shadow:0_0_0_1px_rgba(255,91,79,0.3)]">
          <span className="block size-1.5 rounded-full bg-destructive" aria-hidden="true" />
          <span className="label-mono text-destructive">RUNTIME ERROR</span>
        </div>
        <h2 className="text-center text-[28px] font-semibold tracking-[-1px] text-foreground">
          {translate(componentsCopy, 'boundaryTitle')}
        </h2>
        <p className="max-w-[480px] text-center text-15 leading-[1.55] text-fg-muted">
          {translate(componentsCopy, 'boundaryBody')}
        </p>
        <code className="max-w-[560px] overflow-x-auto rounded-lg bg-accent px-4 py-2.5 font-mono text-12 text-destructive-foreground [box-shadow:var(--shadow-ring-light)]">
          {this.state.error.message || String(this.state.error)}
        </code>
        <div className="flex items-center gap-3">
          <button
            onClick={() => this.setState({ error: null })}
            className="inline-flex items-center gap-1.5 rounded-full bg-foreground px-4 py-2 text-13 font-medium text-primary-foreground transition-all hover:opacity-90 active:scale-[0.97]"
          >
            {translate(componentsCopy, 'retryRender')}
          </button>
          <button
            onClick={() => window.location.reload()}
            className="inline-flex items-center gap-1.5 rounded-full bg-card px-4 py-2 text-13 font-medium text-foreground [box-shadow:var(--shadow-ring-light)] transition-all hover:[box-shadow:var(--shadow-ring)]"
          >
            {translate(componentsCopy, 'reloadPage')}
          </button>
        </div>
      </div>
    )
  }
}
