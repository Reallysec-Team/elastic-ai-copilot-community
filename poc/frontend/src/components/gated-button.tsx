/*
 * 因为权限而按不动的控件，长什么样、怎么说明原因。
 *
 * 两件事以前都没做对：
 *
 * 1. **级别只有一档。** `useCanWrite()` 是「不是 viewer」，也就是 analyst 恒为真；
 *    而后端有 39 条路由要的是 admin（`require_admin`）。于是 analyst 看到一整排
 *    亮着的、按下去必然 403 的按钮 —— 正是「能点、点了报错」那个早就否决过的形态。
 *    这里把级别显式化：`gate="admin"` 读 `/api/me` 的 `is_admin`，`gate="write"`
 *    仍是「不是 viewer」。
 *
 * 2. **禁用了但不说为什么，而且说了也传不到。** 全站三十处按角色禁用的按钮里只有
 *    一处带 `title`。更要命的是 `disabled` 的按钮**不可聚焦**，键盘和读屏用户根本
 *    走不到它，`title` 也不会被朗读 —— 补 `title` 解决不了这一半。所以这里不用
 *    `disabled`：用 `aria-disabled` 保持可聚焦，点击吞掉，原因同时挂在 `title`
 *    （鼠标）和一段 `sr-only` + `aria-describedby`（读屏）上。
 *
 * 用 `title` 而不是 Tooltip 组件：那个要在每个调用点套一层 Provider/Trigger，
 * 三十处各套一遍的收益抵不过它的风险（浮层定位、e2e 里的时序）。原因文本本身
 * 由 `aria-describedby` 那份保证可访问性，`title` 只是鼠标用户的顺手。
 */

import { useId, type ComponentProps, type ReactNode } from 'react'

import { Button } from '@/components/ui/button'
import { PageHeader } from '@/components/shell/page-header'
import { useMe, type MeResponse } from '@/lib/auth'
import { useT } from '@/lib/i18n'
import { commonCopy } from '@/locales/common'
import { cn } from 'cn'

/** `write` = 不是只读账号；`admin` = 后端那条路由挂了 require_admin。 */
export type GateLevel = 'write' | 'admin'

export interface GateState {
  allowed: boolean
  /** 不允许时给人看的那句话；允许时是空串。 */
  reason: string
}

/**
 * 这个账号能不能做这一档的操作。
 *
 * 两种「先放行」是刻意的，和 `useCanWrite` 一致：
 * - `/api/me` 还没回来（`me == null`）—— 否则每次进页面按钮都要先灰一下再亮。
 * - `role === null`，即这套部署对这个调用者没有角色意见（ops token、代理头身份）。
 *   那是「按角色出现之前的行为放行，由后端答复」，不是一个角色。
 */
export function gateFor(
  me: Pick<MeResponse, 'role' | 'is_admin'> | null,
  level: GateLevel,
): { allowed: boolean; reasonKey: 'readOnlyRole' | 'adminOnlyAction' | null } {
  if (!me || me.role === null) return { allowed: true, reasonKey: null }
  if (level === 'admin') {
    return me.is_admin
      ? { allowed: true, reasonKey: null }
      : { allowed: false, reasonKey: 'adminOnlyAction' }
  }
  return me.role !== 'viewer'
    ? { allowed: true, reasonKey: null }
    : { allowed: false, reasonKey: 'readOnlyRole' }
}

export function useGate(level: GateLevel): GateState {
  const me = useMe()
  const c = useT(commonCopy)
  const { allowed, reasonKey } = gateFor(me, level)
  return { allowed, reason: reasonKey ? c(reasonKey) : '' }
}

/** 这个账号是不是管理员。等价于 `useGate('admin').allowed`，给需要整块隐藏/说明的地方用。 */
export function useIsAdmin(): boolean {
  return useGate('admin').allowed
}

type GatedButtonProps = ComponentProps<typeof Button> & {
  /** 这个动作要哪一档权限。默认 `write`。 */
  gate?: GateLevel
}

/**
 * 和 `Button` 一样用，多一个 `gate`。权限不够时按钮仍然可聚焦、可读屏，只是
 * 点不动，并且说得出为什么。`disabled` 照旧传（加载中 / 表单没填完那一类），
 * 两者互不干扰。
 */
export function GatedButton({ gate = 'write', className, onClick, ...props }: GatedButtonProps) {
  const { allowed, reason } = useGate(gate)
  const hintId = useId()

  if (allowed) return <Button className={className} onClick={onClick} {...props} />

  return (
    <>
      <Button
        {...props}
        aria-disabled="true"
        aria-describedby={hintId}
        title={reason}
        data-gated={gate}
        // `disabled:` 那套样式对 aria-disabled 不生效，这里补等价的观感；
        // pointer-events 不能关，关了鼠标 hover 就看不到 title。
        className={cn('aria-disabled:opacity-50 aria-disabled:cursor-not-allowed', className)}
        onClick={(e) => {
          e.preventDefault()
          e.stopPropagation()
        }}
      />
      <span id={hintId} className="sr-only">
        {reason}
      </span>
    </>
  )
}

/**
 * 一整块因为权限而只读的区域，在开头说一句为什么。
 *
 * 表单控件（输入框、开关、文件选择）保持 `disabled` —— 那是这类控件的惯例，
 * 也不会像按钮那样让人以为「点了会有事发生」。但整块灰掉必须有一处文字解释，
 * 而且要在 DOM 里读得到，不能只靠控件自己的样式。
 */
/**
 * 整页 / 整块因为不是管理员而没有内容可看时，说清楚是「你看不到」。
 *
 * 后端有一批 GET 挂着 `require_admin`（审计事件、设置、用户表、巡检报告归档）。
 * 非管理员打开这些页面，以前拿到的是一整页错误 —— 而「出错了」和「你没有权限」
 * 对用户是两件完全不同的事：前者会让人去刷新、去找运维查网关，后者只需要去要
 * 权限。更坏的一种是那条报告归档：`.catch(() => setItems([]))` 把 403 变成了
 * 「暂无巡检报告」，界面在说一句不真的话。
 *
 * 侧栏入口保留 —— 藏起来会让「这个功能存在吗」变成一个要去问人的问题，而深链
 * 分享出去照样会走到这里。
 *
 * @param title 传了就自己画页头（整页用）；不传就只出说明块（嵌在卡片里用）。
 */
export function AdminOnlyView({ title, className }: { title?: ReactNode; className?: string }) {
  const c = useT(commonCopy)
  const notice = (
    <div
      role="note"
      className={cn('flex flex-col items-center gap-1.5 px-6 py-14 text-center', className)}
    >
      <p className="text-14 font-medium text-foreground">{c('adminOnlyView')}</p>
      <p className="max-w-[46ch] text-13 leading-[1.7] text-muted-foreground">
        {c('adminOnlyViewHint')}
      </p>
    </div>
  )
  if (!title) return notice
  // 整页那一档自己带页头和外层容器，跟这些页面正常渲染时是同一个壳 —— 否则
  // "没权限" 会长得像另一个产品。
  return (
    <div className="@container flex w-full flex-col gap-5">
      <PageHeader title={title} />
      {notice}
    </div>
  )
}

export function GateNotice({ gate = 'write', className }: { gate?: GateLevel; className?: string }) {
  const { allowed, reason } = useGate(gate)
  if (allowed) return null
  return (
    <p role="note" className={cn('text-12 leading-[1.6] text-muted-foreground', className)}>
      {reason}
    </p>
  )
}
