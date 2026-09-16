import { useState } from 'react'
import { HugeiconsIcon } from '@hugeicons/react'
import { ArrowRight01Icon, ChevronDownIcon } from '@hugeicons/core-free-icons'

import type { PlatformCheck } from '@/lib/api'
import { useT } from '@/lib/i18n'
import { cn } from '@/lib/utils'
import { platformCopy, type PlatformKey } from '@/locales/platform'
import { shellCopy } from '@/locales/shell'
import { Badge, type BadgeProps } from '@/components/reui/badge'
import { Frame, FrameHeader, FramePanel, FrameTitle } from '@/components/reui/frame'
import { Button } from '@/components/ui/button'
import { Collapsible, CollapsibleContent, CollapsibleTrigger } from '@/components/ui/collapsible'
import { Item, ItemActions, ItemContent, ItemDescription, ItemTitle } from '@/components/ui/item'
import { Separator } from '@/components/ui/separator'
import {
  Table, TableBody, TableCell, TableHead, TableHeader, TableRow,
} from '@/components/ui/table'

/*
 * 检查项分组列表，版式照 `@reui/settings-9`（折叠分组的设置行）：一组一个
 * `Frame stacked dense`，组头可折叠，组内每项一行 `Item`（标题 + 判定徽标 +
 * 一句说明），行尾再一个箭头才展开明细表和处置建议。
 *
 * 没照搬的：settings-9 每行右侧是 Select / Switch 控件，这里每行没有可改的
 * 东西（产品只读，不代客户改集群），行尾换成展开箭头；分组也不是模板的
 * General / Display，而是「需处理 / 通过 / 查不了」——需处理默认展开，因为那是
 * 打开这一页的理由，通过那组默认收起，全过时才展开。原来的判定筛选和搜索框
 * 被分组替代了：12 条检查分成三组后，每组一眼能扫完。
 */

type Verdict = 'ok' | 'warn' | 'fail' | 'unknown'

const VERDICT: Record<Verdict, { label: PlatformKey; badge: BadgeProps['variant'] }> = {
  ok: { label: 'verdictOk', badge: 'success-light' },
  warn: { label: 'verdictWarn', badge: 'warning-light' },
  fail: { label: 'verdictFail', badge: 'destructive-light' },
  // 查不了 ≠ 没问题。权限不足或 API 不可用时是这个，中性刻意区别于 warn。
  unknown: { label: 'verdictUnknown', badge: 'secondary' },
}

export function VerdictBadge({ verdict }: { verdict: string }) {
  const t = useT(platformCopy)
  const v = VERDICT[verdict as Verdict] ?? VERDICT.unknown
  return <Badge variant={v.badge} size="sm">{t(v.label)}</Badge>
}

type GroupId = 'todo' | 'ok' | 'unknown'

const GROUP_LABEL: Record<GroupId, PlatformKey> = {
  todo: 'groupTodo',
  ok: 'groupOk',
  unknown: 'groupUnknown',
}

function groupOf(c: PlatformCheck): GroupId {
  if (c.verdict === 'fail' || c.verdict === 'warn') return 'todo'
  if (c.verdict === 'ok') return 'ok'
  return 'unknown'
}

export function CheckGroups({ checks }: { checks: PlatformCheck[] }) {
  const t = useT(platformCopy)
  const groups: Record<GroupId, PlatformCheck[]> = { todo: [], ok: [], unknown: [] }
  for (const c of checks) groups[groupOf(c)].push(c)
  // 异常排在注意前面：同一组里先看最要紧的。
  groups.todo.sort((a, b) => (a.verdict === b.verdict ? 0 : a.verdict === 'fail' ? -1 : 1))
  const nothingTodo = groups.todo.length === 0 && groups.unknown.length === 0

  return (
    <div className="flex flex-col gap-3">
      {(['todo', 'unknown', 'ok'] as const).map((id) => {
        const items = groups[id]
        if (items.length === 0) return null
        return (
          <Frame key={id} stacked dense spacing="sm">
            <Collapsible defaultOpen={id !== 'ok' || nothingTodo}>
              <CollapsibleTrigger className="flex w-full">
                <FrameHeader className="flex grow flex-row items-center justify-between gap-2 px-4 py-2">
                  <FrameTitle className="flex items-center gap-2">
                    {t(GROUP_LABEL[id])}
                    <span className="font-normal text-muted-foreground tabular-nums">{items.length}</span>
                  </FrameTitle>
                  <HugeiconsIcon
                    icon={ArrowRight01Icon}
                    strokeWidth={2}
                    className="mr-2 size-4 text-muted-foreground transition-transform in-data-open:rotate-90"
                    aria-hidden="true"
                  />
                </FrameHeader>
              </CollapsibleTrigger>
              <CollapsibleContent>
                <FramePanel className="p-0!">
                  {items.map((c, i) => (
                    <div key={c.id}>
                      {i > 0 && <Separator />}
                      <CheckRow check={c} />
                    </div>
                  ))}
                </FramePanel>
              </CollapsibleContent>
            </Collapsible>
          </Frame>
        )
      })}
    </div>
  )
}

function CheckRow({ check }: { check: PlatformCheck }) {
  const sh = useT(shellCopy)
  // 异常项默认展开：需要处理的东西不该再多点一次才能看见。
  const [open, setOpen] = useState(check.verdict === 'fail')
  const hasDetail = check.detail && Object.keys(check.detail).length > 0
  const expandable = Boolean(hasDetail || check.advice)

  return (
    <Collapsible open={open} onOpenChange={setOpen}>
      <Item className="px-4">
        <ItemContent>
          <ItemTitle className="gap-2">
            {check.title}
            <VerdictBadge verdict={check.verdict} />
          </ItemTitle>
          <ItemDescription>{check.summary}</ItemDescription>
        </ItemContent>
        {expandable && (
          <ItemActions>
            <CollapsibleTrigger
              render={<Button variant="ghost" size="icon-sm" aria-label={open ? sh('collapse') : sh('expand')} />}
              className="text-muted-foreground"
            >
              <HugeiconsIcon
                icon={ChevronDownIcon}
                strokeWidth={2}
                className={cn('size-4 transition-transform', open && 'rotate-180')}
              />
            </CollapsibleTrigger>
          </ItemActions>
        )}
      </Item>
      <CollapsibleContent className="flex flex-col gap-2 px-4 pb-3">
        {check.advice && (
          <div className="rounded-lg bg-muted/50 px-3 py-2.5 text-sm leading-relaxed whitespace-pre-wrap">
            {check.advice}
          </div>
        )}
        {hasDetail && <CheckDetail detail={check.detail} />}
      </CollapsibleContent>
    </Collapsible>
  )
}

/*
 * 一条检查的证据。后端给的是 `Record<string, unknown>`，形状按检查项而定，
 * 但真正长的那些都是同一种：一个扁平对象的数组（每条数据流一行、每个节点
 * 一行）。原来整个 detail 直接 `JSON.stringify` 出来 —— 12 条数据流就是
 * 一屏花括号，读者得自己在里面找哪一条 `verdict: "fail"`。
 *
 * 数组渲染成表，标量并成一行键值，其余（嵌套对象）才落回 JSON。字段名保持
 * 原样不翻译：这些是 ES 的字段，看的人是照着它去 Kibana 里查的。
 */
function CheckDetail({ detail }: { detail: Record<string, unknown> }) {
  const rows: [string, unknown][] = Object.entries(detail)
  const tables = rows.filter(([, v]) => isRowArray(v)) as [string, Record<string, unknown>[]][]
  const scalars = rows.filter(([, v]) => v == null || typeof v !== 'object')
  const rest = rows.filter(([k]) => !tables.some(([tk]) => tk === k) && !scalars.some(([sk]) => sk === k))

  return (
    <div className="flex flex-col gap-2">
      {scalars.length > 0 && (
        <div className="flex flex-wrap gap-x-5 gap-y-1 rounded-lg bg-muted/50 px-3 py-2.5">
          {scalars.map(([k, v]) => (
            <span key={k} className="font-mono text-11 text-muted-foreground">
              {k} <span className="text-foreground">{String(v)}</span>
            </span>
          ))}
        </div>
      )}

      {tables.map(([key, items]) => {
        const cols = [...new Set(items.flatMap((it) => Object.keys(it)))]
        return (
          <div key={key} className="overflow-x-auto rounded-lg border">
            <Table>
              <TableHeader>
                <TableRow>
                  {cols.map((c) => (
                    <TableHead key={c} className="font-mono text-11">{c}</TableHead>
                  ))}
                </TableRow>
              </TableHeader>
              <TableBody>
                {items.map((it, i) => (
                  <TableRow key={i}>
                    {cols.map((c) => (
                      <TableCell key={c} className="font-mono text-11 whitespace-nowrap">
                        {it[c] == null ? '—' : String(it[c])}
                      </TableCell>
                    ))}
                  </TableRow>
                ))}
              </TableBody>
            </Table>
          </div>
        )
      })}

      {rest.length > 0 && (
        <pre className="overflow-x-auto rounded-lg bg-muted/50 px-3 py-2.5 font-mono text-11 leading-[1.5]">
          {JSON.stringify(Object.fromEntries(rest), null, 2)}
        </pre>
      )}
    </div>
  )
}

/** 一个能当表画的数组：非空，且每项都是扁平对象。 */
function isRowArray(v: unknown): v is Record<string, unknown>[] {
  return (
    Array.isArray(v) &&
    v.length > 0 &&
    v.every(
      (it) =>
        it != null &&
        typeof it === 'object' &&
        !Array.isArray(it) &&
        Object.values(it).every((cell) => cell == null || typeof cell !== 'object'),
    )
  )
}
