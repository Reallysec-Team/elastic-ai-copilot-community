import { Menu } from '@base-ui/react/menu'
import type { ReactElement, ReactNode } from 'react'
import { Link } from '@tanstack/react-router'
import { cn } from '@/lib/utils'

/*
 * Geist-skinned dropdown menu (Base UI Menu under the hood).
 *
 * Click trigger; closes on outside-click / Esc / item-click.
 *
 * Base UI notes: the positioned element is `Positioner`, so z-index and
 * align/sideOffset belong there — not on `Popup`. Links use `LinkItem`
 * (Item renders a button and would strip the anchor semantics).
 *
 * `closeOnClick` on LinkItem is load-bearing, not decoration. Base UI defaults
 * it to false there because a link normally takes the whole document with it,
 * so there is nothing left to close. These links are react-router `<Link>`s:
 * the navigation is client-side, the menu survives it, and without this the
 * menu never closed at all — it stayed `data-open` with `#root` marked
 * `data-base-ui-inert` and `body { overflow: hidden }` for the rest of the
 * session. Visible symptom: after using this menu once, the page could not be
 * scrolled and the next click on the trigger was swallowed (it closed the menu
 * everyone thought was already shut).
 */

/* 这里原本还有一个 `NavDropdownItem` 接口，字段里带 `icon?: LucideIcon` ——
   全仓没有任何地方用它，而它是产品代码里最后一处 lucide 引用（本仓在 26df721
   全仓迁到了 hugeicons）。连同那行 import 一起删掉。
   同一个文件里的 `NavDropdownItem_Link` 也没有调用方，但它是能用的组件不是
   类型残留，留给专门清死代码的那一轮。 */

/* Renders a generic dropdown for non-link content (gear menu, dialog footers).
 *
 * z-[60] is deliberate and load-bearing: the content is portalled to <body>, so
 * it competes with whatever else is stacked there. Dialog overlay is z-40 and
 * dialog content z-50 (see ui/Dialog), so a menu opened from INSIDE a dialog at
 * z-40 renders behind the dialog panel — the trigger looks dead. Keep this
 * above ui/Dialog's content. */
export function NavDropdownGeneric({
  trigger,
  children,
  align = 'end',
}: {
  trigger: ReactNode
  children: ReactNode
  align?: 'start' | 'center' | 'end'
}) {
  return (
    <Menu.Root>
      <Menu.Trigger render={trigger as ReactElement<Record<string, unknown>>} />
      <Menu.Portal>
        <Menu.Positioner align={align} sideOffset={8} className="z-[60] outline-none">
          <Menu.Popup
            className={cn(
              'min-w-[200px] rounded-lg bg-card p-1.5 outline-none',
              '[box-shadow:var(--shadow-pop)]',
              '[animation:dropdown-content-in_160ms_cubic-bezier(0.16,1,0.3,1)]',
              'motion-reduce:[animation:none]',
            )}
          >
            {children}
          </Menu.Popup>
        </Menu.Positioner>
      </Menu.Portal>
    </Menu.Root>
  )
}

export const NavDropdownItem_Link = ({
  to,
  children,
  active,
}: {
  to: string
  children: ReactNode
  active?: boolean
}) => (
  <Menu.LinkItem
    closeOnClick
    render={<Link to={to} />}
    className={cn(
      'flex items-center gap-2 rounded-md px-2.5 py-1.5 outline-none cursor-pointer',
      'transition-colors',
      // Base UI moves real DOM focus to the highlighted item and also sets
      // data-highlighted; belt and braces so the highlight can't go missing.
      active ? 'bg-secondary' : 'data-highlighted:bg-accent focus:bg-accent',
    )}
  >
    <span className={cn('text-13 text-foreground', active && 'font-semibold')}>
      {children}
    </span>
  </Menu.LinkItem>
)

/* One action row in a NavDropdownGeneric menu. Both the investigation and the
 * explain-log dialog had a byte-identical private copy of this; one is enough.
 * `onSelect` keeps the Radix-era name so the call sites read the same. */
export function NavDropdownAction({
  icon,
  label,
  onSelect,
  disabled,
  hint,
}: {
  icon: ReactNode
  label: string
  onSelect: () => void
  disabled?: boolean
  hint?: string
}) {
  return (
    <Menu.Item
      disabled={disabled}
      onClick={onSelect}
      title={hint}
      className={cn(
        'flex items-center gap-2.5 rounded-md px-2.5 py-2 outline-none cursor-pointer transition-colors',
        'text-13 text-foreground',
        'data-highlighted:bg-accent focus:bg-accent',
        'data-disabled:cursor-not-allowed data-disabled:opacity-45',
      )}
    >
      <span className="shrink-0 text-fg-muted">{icon}</span>
      {label}
    </Menu.Item>
  )
}
