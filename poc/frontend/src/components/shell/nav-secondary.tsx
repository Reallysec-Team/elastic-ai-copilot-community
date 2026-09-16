import { Link, useLocation } from '@tanstack/react-router'

import {
  SidebarGroup, SidebarGroupLabel, SidebarMenu, SidebarMenuButton, SidebarMenuItem,
} from '@/components/ui/sidebar'

import { isNavActive } from './nav-main'
import { useT } from '@/lib/i18n'
import { shellCopy } from '@/locales/shell'

import { NAV_SECONDARY, type NavItem } from './data'

/*
 * roster's NavProjects slot: a second group under the main nav, holding the
 * four administrative destinations — things an operator visits occasionally,
 * not the ones they work in.
 *
 * Same row and icon size as NavMain. roster's second group is the default
 * `SidebarMenuButton` too; shrinking these rows made one rail carry two type
 * scales, and the group label above them already says what they are.
 */

function SecondaryNavItem({ item }: { item: NavItem }) {
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

export function NavSecondary() {
  const t = useT(shellCopy)
  return (
    <SidebarGroup>
      {/* 这条组标题原来是写死的中文，切英文时侧栏会变成「三个英文分组 + 一个中文分组」。 */}
      <SidebarGroupLabel className="in-data-[state=collapsed]:hidden">{t('groupAdmin')}</SidebarGroupLabel>
      <SidebarMenu>
        {NAV_SECONDARY.map((item) => (
          <SecondaryNavItem key={item.id} item={item} />
        ))}
      </SidebarMenu>
    </SidebarGroup>
  )
}
