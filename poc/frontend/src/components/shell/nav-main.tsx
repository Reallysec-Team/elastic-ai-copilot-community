import { Link, useLocation } from '@tanstack/react-router'

import {
  SidebarGroup, SidebarGroupContent, SidebarGroupLabel, SidebarMenu,
  SidebarMenuButton, SidebarMenuItem,
} from '@/components/ui/sidebar'

import { useT } from '@/lib/i18n'
import { shellCopy } from '@/locales/shell'

import { NAV_GROUPS, type NavItem } from './data'

/*
 * roster's NavMain (`app/layouts/nav-main.tsx`), minus its collapsible sub-menu
 * branch: no destination in this product has children, and a branch with no
 * data is code someone has to read and rule out later.
 *
 * roster renders one group under a "Workspace" label; this product has four,
 * and the same component draws them all — the shape was already there.
 *
 * The active row's raised-white treatment is not here: it is declared once on
 * the SidebarProvider in AppShell, the way roster's app-shell-3 does it.
 */

/** Active when the pathname matches the href (exact for "/", prefix otherwise). */
export function isNavActive(pathname: string, item: NavItem) {
  if (item.exact) return pathname === item.href
  return pathname === item.href || pathname.startsWith(item.href + '/')
}

function LeafNavItem({ item }: { item: NavItem }) {
  const t = useT(shellCopy)
  const { pathname } = useLocation()
  return (
    <SidebarMenuItem>
      <SidebarMenuButton
        tooltip={t(item.label)}
        isActive={isNavActive(pathname, item)}
        render={<Link to={item.href as never} />}
      >
        {item.icon}
        <span>{t(item.label)}</span>
      </SidebarMenuButton>
    </SidebarMenuItem>
  )
}

export function NavMain() {
  const t = useT(shellCopy)
  return (
    <>
      {NAV_GROUPS.map((group) => (
        <SidebarGroup key={group.id}>
          {/* Hidden on the collapsed rail, where a group label would render
              as two clipped characters above a column of icons. */}
          {group.label && (
            <SidebarGroupLabel className="in-data-[state=collapsed]:hidden">
              {t(group.label)}
            </SidebarGroupLabel>
          )}
          <SidebarGroupContent>
            <SidebarMenu>
              {group.items.map((item) => (
                <LeafNavItem key={item.id} item={item} />
              ))}
            </SidebarMenu>
          </SidebarGroupContent>
        </SidebarGroup>
      ))}
    </>
  )
}
