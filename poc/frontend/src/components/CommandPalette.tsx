import { useCallback, useEffect, useMemo, useRef, useState } from 'react'
import { useNavigate } from '@tanstack/react-router'
import { HugeiconsIcon, type IconSvgElement } from '@hugeicons/react'
import { ArrowRight01Icon, CornerDownLeftIcon, Search01Icon } from '@hugeicons/core-free-icons'
import { Dialog, DialogContent } from '@/components/ui/dialog'
import { useT } from '@/lib/i18n'
import { shellCopy } from '@/locales/shell'
import { ALL_NAV } from '@/components/shell/data'
import { requestNewQuery } from '@/lib/history'
import { cn } from '@/lib/utils'
import { componentsCopy } from '@/locales/components'

/*
 * Global ⌘K / Ctrl+K command palette.
 *
 * Searches across every route + a few quick actions. Pure keyboard:
 * up/down to move, Enter to run, Esc to close. Fuzzy-ish match — a
 * lowercase substring test over label + keywords (good enough for ~15
 * entries; no need for a fuzzy lib).
 *
 * Mounted once in AppShell. Listens for the keydown on window.
 */

interface Command {
  id: string
  label: string
  hint?: string
  keywords: string
  icon?: IconSvgElement
  workflow?: 'develop' | 'preview' | 'ship'
  run: (nav: ReturnType<typeof useNavigate>) => void
}

/** Match every whitespace-separated term against label + keywords + hint.
 *  Exported (and tested) because it is the only non-obvious logic in here. */
export function filterCommands<T extends { label: string; keywords: string; hint?: string }>(
  commands: readonly T[],
  query: string,
): T[] {
  const q = query.trim().toLowerCase()
  if (!q) return [...commands]
  const terms = q.split(/\s+/)
  return commands.filter((c) => {
    const hay = `${c.label} ${c.keywords} ${c.hint ?? ''}`.toLowerCase()
    return terms.every((term) => hay.includes(term))
  })
}

/*
 * 面板里的目的地 = 侧栏里的目的地，同一份 `ALL_NAV`，同一个顺序。
 *
 * 原来这里自己抄了一份 12 条的表，于是两边慢慢对不上：面板里写「查询」「报告」
 * 「审计日志」「AI 配置管理」，侧栏写「智能查询」「运营报告」「调用审计」
 * 「AI 配置」；平台体检和分析记录压根没进面板。名字只在 data.tsx 里写一次。
 *
 * 这里只补一样东西：搜索用的关键词（拼音/英文/同义词），按路径挂。
 */
const KEYWORDS: Record<string, string> = {
  '/': 'query chaxun nl dsl search 自然语言 智能查询',
  '/analysis': 'analysis jilu 分析记录 归档 调查 分诊',
  '/alerts': 'alerts realtime shishi gaojing webhook',
  '/triage': 'triage fenzhen alert 告警 批量',
  '/detection-rules': 'detection rule jiance guize kibana',
  '/field-dictionary': 'field dict ziduan schema mapping',
  '/knowledge-base': 'kb knowledge rag zhishiku runbook',
  '/baseline': 'baseline jixian osquery compliance 合规 等保 cis',
  '/reports': 'report baogao daily weekly 日报 周报 月报',
  '/platform': 'platform checkup tijian 体检 集群 健康 运维 在线更新 升级',
  '/users': 'users yonghu 用户 账号 角色 权限 admin analyst viewer',
  '/asset-identity': 'asset identity zichan shenfen 资产 身份 csv 导入 语境 归属 责任人',
  '/notify': 'notify feishu email smtp slack teams 投递 通知 渠道 对外通道 webhook',
  '/ai-settings': 'ai settings provider llm 模型 配置 embedding',
  '/audit': 'audit shenji log 日志 调用',
  '/settings': 'settings shezhi config gateway engine 平台 系统 索引白名单 脱敏',
  '/license': 'license activate jihuo 授权 产品激活',
}

/** 工作流色点，按路径挂 —— 原来跟着那份重复的表走。 */
const WORKFLOW: Record<string, 'develop' | 'preview' | 'ship'> = {
  '/triage': 'ship',
  '/detection-rules': 'preview',
  '/baseline': 'preview',
}

export function CommandPalette() {
  const t = useT(componentsCopy)
  /* 导航项的名字归外壳那份文案（侧栏、面包屑、命令面板三处同名），这一页自己
     的说法归 components。 */
  const sh = useT(shellCopy)
  const [open, setOpen] = useState(false)
  const [query, setQuery] = useState('')
  const [cursor, setCursor] = useState(0)
  const navigate = useNavigate()
  const inputRef = useRef<HTMLInputElement>(null)
  const listRef = useRef<HTMLDivElement>(null)


  // Build the command list. Routes + a couple of quick actions.
  const commands = useMemo<Command[]>(() => {
    const routeCmds: Command[] = ALL_NAV.map((item) => ({
      id: `route:${item.href}`,
      label: sh(item.label),
      hint: item.href,
      keywords: KEYWORDS[item.href] ?? '',
      icon: ArrowRight01Icon,
      workflow: WORKFLOW[item.href],
      run: (nav) => nav({ to: item.href }),
    }))
    const actions: Command[] = [
      {
        id: 'action:new-query',
        label: t('newThread'),
        hint: t('newThreadHint'),
        keywords: 'new query xinjian 新建 会话',
        icon: Search01Icon,
        run: (nav) => {
          nav({ to: '/' })
          // Navigating to `/` only resets when 查询页 (ChatPage) actually remounts. Fired
          // from the query page itself — the common case — the route is already
          // `/`, so the command did nothing at all. The event resets a page that
          // is already mounted; a fresh mount ignores it and starts clean anyway.
          requestNewQuery()
        },
      },
    ]
    return [...routeCmds, ...actions]
  }, [t])

  const filtered = useMemo(() => filterCommands(commands, query), [commands, query])

  // Global hotkey.
  useEffect(() => {
    function onKey(e: KeyboardEvent) {
      if ((e.metaKey || e.ctrlKey) && (e.key === 'k' || e.key === 'K')) {
        e.preventDefault()
        setOpen((v) => !v)
      }
    }
    window.addEventListener('keydown', onKey)
    return () => window.removeEventListener('keydown', onKey)
  }, [])

  // Reset state each time it opens.
  useEffect(() => {
    if (open) {
      // eslint-disable-next-line react-hooks/set-state-in-effect -- one-shot reset when the palette opens
      setQuery('')
      setCursor(0)
      setTimeout(() => inputRef.current?.focus(), 40)
    }
  }, [open])

  // Clamp the cursor to the current list during render instead of in an
  // effect — avoids a cascading re-render when `filtered` shrinks.
  const safeCursor = Math.min(cursor, Math.max(0, filtered.length - 1))

  const runAt = useCallback(
    (idx: number) => {
      const cmd = filtered[idx]
      if (!cmd) return
      setOpen(false)
      cmd.run(navigate)
    },
    [filtered, navigate],
  )

  function onInputKeyDown(e: React.KeyboardEvent<HTMLInputElement>) {
    if (e.key === 'ArrowDown') {
      e.preventDefault()
      setCursor(Math.min(filtered.length - 1, safeCursor + 1))
    } else if (e.key === 'ArrowUp') {
      e.preventDefault()
      setCursor(Math.max(0, safeCursor - 1))
    } else if (e.key === 'Enter') {
      e.preventDefault()
      runAt(safeCursor)
    }
  }

  // Scroll the active row into view.
  useEffect(() => {
    const el = listRef.current?.querySelector<HTMLElement>(`[data-idx="${safeCursor}"]`)
    el?.scrollIntoView({ block: 'nearest' })
  }, [safeCursor])

  return (
    <Dialog open={open} onOpenChange={setOpen}>
      <DialogContent showCloseButton={false} className="flex flex-col gap-0 overflow-hidden p-0 sm:max-w-[560px] max-h-[70vh] !p-0">
        <div className="flex items-center gap-3 px-4 py-3 [box-shadow:0_1px_0_var(--color-line)_inset]">
          <HugeiconsIcon icon={Search01Icon} strokeWidth={2} className="size-4 shrink-0 text-fg-faint" />
          <input
            ref={inputRef}
            value={query}
            onChange={(e) => {
              setQuery(e.target.value)
              setCursor(0)
            }}
            onKeyDown={onInputKeyDown}
            placeholder={t('palettePlaceholder')}
            aria-label={t('paletteSearchAria')}
            role="combobox"
            aria-expanded
            aria-controls="cmdk-list"
            aria-autocomplete="list"
            aria-activedescendant={filtered.length ? `cmdk-opt-${safeCursor}` : undefined}
            className="flex-1 bg-transparent text-15 text-foreground outline-none placeholder:text-fg-faint"
          />
          <kbd className="rounded bg-secondary px-1.5 py-0.5 font-mono text-11 text-muted-foreground">
            ESC
          </kbd>
        </div>

        <div
          ref={listRef}
          id="cmdk-list"
          role="listbox"
          aria-label={t('commandsAria')}
          className="max-h-[calc(70vh-110px)] overflow-y-auto p-1.5"
        >
          {filtered.length === 0 ? (
            <div role="status" className="px-3 py-8 text-center text-13 text-fg-faint">
              {t('noMatchingCommand', { q: query })}
            </div>
          ) : (
            filtered.map((c, i) => (
              <button
                key={c.id}
                id={`cmdk-opt-${i}`}
                role="option"
                aria-selected={i === safeCursor}
                tabIndex={-1}
                data-idx={i}
                onMouseEnter={() => setCursor(i)}
                onClick={() => runAt(i)}
                className={cn(
                  'flex w-full items-center gap-3 rounded-md px-3 py-2 text-left',
                  'transition-colors',
                  i === safeCursor ? 'bg-secondary' : 'hover:bg-accent',
                )}
              >
                <DotOrIcon cmd={c} />
                <span className="flex-1 text-14 font-medium text-foreground">
                  {c.label}
                </span>
                {c.hint && (
                  <span className="font-mono text-11 text-fg-faint">{c.hint}</span>
                )}
                {i === safeCursor && (
                  <HugeiconsIcon icon={CornerDownLeftIcon} strokeWidth={2} className="size-3.5 text-muted-foreground" />
                )}
              </button>
            ))
          )}
        </div>

        <div className="flex items-center gap-4 px-4 py-2.5 [box-shadow:0_-1px_0_var(--color-line)_inset]">
          <Hint k="↑↓" label={t('hintMove')} />
          <Hint k="↵" label={t('hintRun')} />
          <Hint k="esc" label={t('hintClose')} />
          <span className="ml-auto font-mono text-11 text-fg-faint">
            {t('nItems', { n: filtered.length })}
          </span>
        </div>
      </DialogContent>
    </Dialog>
  )
}

function DotOrIcon({ cmd }: { cmd: Command }) {
  if (cmd.workflow) {
    return (
      <span
        className={cn(
          'block size-1.5 rounded-full shrink-0',
          cmd.workflow === 'develop' && 'bg-info',
          cmd.workflow === 'preview' && 'bg-preview',
          cmd.workflow === 'ship' && 'bg-destructive',
        )} aria-hidden="true"
      />
    )
  }
  return cmd.icon ? (
    <HugeiconsIcon
      icon={cmd.icon}
      strokeWidth={2}
      className="size-3.5 shrink-0 text-muted-foreground"
    />
  ) : (
    <span className="size-3.5" />
  )
}

function Hint({ k, label }: { k: string; label: string }) {
  return (
    <span className="flex items-center gap-1.5">
      <kbd className="rounded bg-secondary px-1.5 py-0.5 font-mono text-10 text-muted-foreground">
        {k}
      </kbd>
      <span className="text-11 text-fg-faint">{label}</span>
    </span>
  )
}
