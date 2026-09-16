import { HugeiconsIcon } from '@hugeicons/react'
import { Search01Icon } from '@hugeicons/core-free-icons'

import { useT } from '@/lib/i18n'
import { modKeyCombo } from '@/lib/platformKey'
import { shellCopy } from '@/locales/shell'
import { Button } from '@/components/ui/button'
import { HistoryButton } from '@/components/shell/history-button'
import { Kbd } from '@/components/ui/kbd'
import { SidebarGroup, SidebarGroupContent } from '@/components/ui/sidebar'

/*
 * roster's SearchForm slot, at the top of the rail. roster's own version owns a
 * dialog; ours opens the CommandPalette that is already mounted in the shell —
 * two search dialogs would be two front doors to one room.
 *
 * It replaces the ⌘K button that sat in the top bar. The button is the only
 * discoverable affordance for the palette, and the rail is where a reader looks
 * for "find something" in every app roster is modelled on.
 *
 * Two of the block's class-list oddities are kept because they are load-bearing
 * on the collapsed rail:
 *   `overflow-hidden` — only the width transitions on collapse, so without it
 *   the label spills out of the 32px rail for the ~100ms the width takes.
 *   `!` on `text-transparent` — the `in-*` variant compiles its ancestor test
 *   inside `:where()`, which contributes no specificity, so the outline
 *   variant's own `hover:text-foreground` beat it and hovering the collapsed
 *   icon repainted the label.
 */
export function SearchForm() {
  const t = useT(shellCopy)
  const openPalette = () => {
    // The palette listens for the hotkey on window; synthesizing it keeps one
    // open path rather than adding a second (an event, a context, a store).
    window.dispatchEvent(new KeyboardEvent('keydown', { key: 'k', metaKey: true }))
  }

  return (
    <SidebarGroup className="py-0">
      {/* 搜索框 + 查询历史一行：一个是「按名字找」，一个是「按时间找」。
          收起时改成竖排 —— 32px 的轨道并排放不下两个，藏掉其中一个等于把
          历史抽屉从收起态里删掉。 */}
      <SidebarGroupContent className="flex items-center gap-1 in-data-[state=collapsed]:flex-col in-data-[state=collapsed]:gap-1">
        {/* 搜索框自带一层 relative：放大镜和快捷键标签是相对它定位的，不能相对
            外面那一行 —— 收起时那一行变成两格高的竖排，`top-1/2` 会把图标丢到
            两个按钮中间的缝里。 */}
        <div className="relative min-w-0 flex-1 in-data-[state=collapsed]:flex-none">
          <Button
            type="button"
            variant="outline"
            aria-label={t('commandPalette')}
            aria-keyshortcuts="Meta+K Control+K"
            onClick={openPalette}
            className="h-8 w-full justify-start overflow-hidden pl-7 font-normal transition-[width] duration-200 ease-linear hover:bg-background in-data-[state=collapsed]:w-8! in-data-[state=collapsed]:pl-4! in-data-[state=collapsed]:text-transparent!"
          >
            {t('searchPlaceholder')}
          </Button>
          {/* `left-2` = 8px，`size-4` 的图标中心落在 16px —— 收起时导航项的图标
              也在这一列上。 */}
          <HugeiconsIcon
            icon={Search01Icon}
            strokeWidth={2}
            aria-hidden="true"
            className="pointer-events-none absolute top-1/2 left-2 size-4 -translate-y-1/2 opacity-50 select-none"
          />
          <Kbd className="absolute top-1/2 right-2 -translate-y-1/2 in-data-[state=collapsed]:hidden">
            {modKeyCombo('K')}
          </Kbd>
        </div>
        <HistoryButton />
      </SidebarGroupContent>
    </SidebarGroup>
  )
}
