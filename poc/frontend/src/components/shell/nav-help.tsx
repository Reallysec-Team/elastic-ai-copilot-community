/*
 * 侧栏最底下的两行：帮助中心 / 文档（版式照 efferd dashboard-2 的左下角）。
 * 账号块搬去了顶栏右上角，这个位置让给它们。
 *
 * 两条都指向官网文档站的产品根目录（帮助中心 = 文档，暂无独立的帮助中心页）。
 */
import { HugeiconsIcon } from '@hugeicons/react'
import { BookOpen01Icon, HelpCircleIcon } from '@hugeicons/core-free-icons'

import { useT } from '@/lib/i18n'
import { shellCopy, type ShellKey } from '@/locales/shell'
import { SidebarMenu, SidebarMenuButton, SidebarMenuItem } from '@/components/ui/sidebar'

const DOCS_URL = 'https://reallysec.com/docs/elastic-ai-copilot'
const HELP_LINKS: Array<{ key: ShellKey; href: string; icon: typeof HelpCircleIcon }> = [
  { key: 'helpCenter', href: DOCS_URL, icon: HelpCircleIcon },
  { key: 'documentation', href: DOCS_URL, icon: BookOpen01Icon },
]

export function NavHelp() {
  const t = useT(shellCopy)
  return (
    <SidebarMenu>
      {HELP_LINKS.map((l) => (
        <SidebarMenuItem key={l.key}>
          <SidebarMenuButton
            size="sm"
            tooltip={t(l.key)}
            className="text-muted-foreground hover:text-foreground"
            render={<a href={l.href} target="_blank" rel="noreferrer" />}
          >
            <HugeiconsIcon icon={l.icon} strokeWidth={2} aria-hidden="true" />
            <span>{t(l.key)}</span>
          </SidebarMenuButton>
        </SidebarMenuItem>
      ))}
    </SidebarMenu>
  )
}
