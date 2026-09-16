import {
  useEffect,
  useRef,
  useState,
  type FormEvent,
  type KeyboardEvent,
  type ReactNode,
} from "react"
import {
  Frame,
  FrameHeader,
  FramePanel,
} from "@/components/reui/frame"

import { FieldLabel } from "@/components/ui/field"
import {
  InputGroup,
  InputGroupAddon,
  InputGroupButton,
  InputGroupTextarea,
} from "@/components/ui/input-group"
import { Kbd } from "@/components/ui/kbd"
import {
  Tooltip,
  TooltipContent,
  TooltipTrigger,
} from "@/components/ui/tooltip"
import { HugeiconsIcon } from '@hugeicons/react'
import { ArrowUp01Icon } from '@hugeicons/core-free-icons'
import { translate } from '@/lib/i18n'
import { componentsCopy } from '@/locales/components'

/*
 * The block's composer, minus the affordances that only had demo behaviour
 * behind them: an attach menu that dropped a hard-coded `churn-q3.csv` chip, a
 * dictation button whose "recording" was a 5s timer, Think / Search toggles
 * wired to nothing, and a context meter reading a frozen token count.
 *
 * What is left is the part that does work — the growing field, Enter to send
 * with IME-safe handling, and the one primary slot where Stop replaces Send —
 * plus a `tools` slot, because in this product the thing that belongs beside
 * the field is the index the question runs against.
 */
export function Composer({
  streaming,
  placeholder = translate(componentsCopy, 'askCopilot'),
  disclaimer,
  tools,
  seed,
  onSend,
  onStop,
}: {
  streaming: boolean
  /** 外面往输入框里放一句草稿（示例卡的「自己写一句」）。nonce 变了才生效，
      同一句放两次也要触发。 */
  seed?: { text: string; nonce: number }
  placeholder?: string
  /** Small print under the field. Omitted when the host has nothing to say. */
  disclaimer?: ReactNode
  /** Controls seated on the field's bottom row, before the send button. */
  tools?: ReactNode
  onSend: (text: string) => void
  onStop: () => void
}) {
  const [value, setValue] = useState("")
  const field = useRef<HTMLTextAreaElement>(null)

  const canSend = value.trim().length > 0
  useEffect(() => {
    if (!seed) return
    // eslint-disable-next-line react-hooks/set-state-in-effect -- 外部草稿落进受控输入框
    setValue(seed.text)
    const el = field.current
    if (el) {
      el.focus()
      el.setSelectionRange(seed.text.length, seed.text.length)
    }
  }, [seed])
  function send() {
    if (!canSend) return
    const text = value.trim()
    setValue("")
    onSend(text)
    // Clicking the button takes focus off the field. The composer never locks
    // during a reply, so the caret belongs straight back in it.
    field.current?.focus()
  }

  function submit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault()
    send()
  }

  function handleKeyDown(event: KeyboardEvent<HTMLTextAreaElement>) {
    // Enter sends, Shift+Enter breaks the line. An IME candidate window also
    // fires Enter, and committing a word there must not post the message.
    if (
      event.key !== "Enter" ||
      event.shiftKey ||
      event.nativeEvent.isComposing
    )
      return
    event.preventDefault()
    send()
  }

  return (
    // 和对话列同宽（6xl）；空态里它套在 ThreadStart 的窄列里，自然跟着窄。
    <div className="mx-auto flex w-full max-w-6xl flex-col gap-2">
      {/* 范围带下面那块面板的上角抹方（和回答卡同一条规则）：圆角外会露出
          frame 的灰底，看着像边框在范围带那一段断了。 */}
      <Frame dense spacing="sm" className="w-full dark:border-white/15 [&_[data-slot=frame-panel-header]+[data-slot=frame-panel]]:rounded-t-none">
        {/* 范围带（照 ai-chat-10 的 composer）：索引 / 时间范围这些「问在什么范围上」
            的设置放在输入框上方的一条浅色带里，读起来是提问的前提，不是和发送键
            挤在一起的又一个按钮。 */}
        {tools ? (
          <FrameHeader className="flex-row flex-wrap items-center gap-1 bg-muted/50 py-1.5">
            {tools}
          </FrameHeader>
        ) : null}
        <FramePanel className="p-0">
          <form onSubmit={submit} className="relative">
            <FieldLabel className="sr-only" htmlFor="copilot-composer">
              {translate(componentsCopy, 'askCopilot')}
            </FieldLabel>

            {/* 焦点环关掉：这个 InputGroup 套在 FramePanel 里，panel 上角是方的、
                InputGroup 自己是圆角，聚焦时环从两个上角外侧露出来一小块蓝。焦点
                状态由光标本身表示，frame 不需要再画一圈。 */}
            <InputGroup className="border-0 bg-transparent shadow-none has-[[data-slot=input-group-control]:focus-visible]:border-transparent has-[[data-slot=input-group-control]:focus-visible]:ring-0">
              <InputGroupTextarea
                id="copilot-composer"
                ref={field}
                value={value}
                onChange={(event) => setValue(event.target.value)}
                onKeyDown={handleKeyDown}
                placeholder={placeholder}
                // Starts one line and grows with the text, capped so the
                // transcript never loses the screen.
                className="field-sizing-content max-h-48 min-h-16"
              />

              <InputGroupAddon align="block-end" className="gap-1">
                <div className="ms-auto flex items-center gap-1">
                  {/* One primary slot: Stop replaces Send while the reply
                      streams, and sending again settles the one in flight. */}
                  {streaming ? (
                    <Tooltip>
                      <TooltipTrigger
                        render={
                          <InputGroupButton
                            size="icon-sm"
                            variant="outline"
                            onClick={onStop}
                            aria-label={translate(componentsCopy, 'stopGenerating')}
                          />
                        }
                      >
                        {/* A filled square is the stop glyph everywhere, and
                            it costs no icon mapping to draw. */}
                        <span
                          aria-hidden="true"
                          className="bg-foreground size-2.5 rounded-xs"
                        />
                      </TooltipTrigger>
                      <TooltipContent>{translate(componentsCopy, 'stopGenerating')}</TooltipContent>
                    </Tooltip>
                  ) : (
                    <Tooltip>
                      <TooltipTrigger
                        render={
                          <InputGroupButton
                            type="submit"
                            size="icon-sm"
                            variant="default"
                            // `send()` 已经挡了空输入，但按钮照样亮着 —— 点下去
                            // 什么也不发生，读起来像坏了。这里只是把已有的判断
                            // 画出来。
                            disabled={!canSend}
                            aria-label={translate(componentsCopy, 'send')}
                          />
                        }
                      >
                        <HugeiconsIcon icon={ArrowUp01Icon} strokeWidth={2} aria-hidden="true" />
                      </TooltipTrigger>
                      <TooltipContent className="flex items-center gap-1.5">
                        {translate(componentsCopy, 'send')}
                        <Kbd>Enter</Kbd>
                      </TooltipContent>
                    </Tooltip>
                  )}
                </div>
              </InputGroupAddon>
            </InputGroup>
          </form>
        </FramePanel>
      </Frame>

      {disclaimer ? (
        <p className="text-muted-foreground text-center text-xs">{disclaimer}</p>
      ) : null}
    </div>
  )
}
