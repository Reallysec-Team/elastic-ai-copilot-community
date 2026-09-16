"use client"

import {
  createContext,
  memo,
  useContext,
  useEffect,
  useRef,
  useState,
  type ReactNode,
} from "react"
import { Badge } from "@/components/reui/badge"
import { Frame, FrameHeader, FramePanel, FrameTitle } from "@/components/reui/frame"
import {
  CodeBlock,
  CodeBlockContent,
  CodeBlockCopyButton,
  CodeBlockDownloadButton,
  CodeBlockHeader,
  CodeBlockTitle,
  type CodeBlockFoldRegion,
} from "@/components/reui/code-block/code-block"
import { highlightCode } from "@/components/reui/code-block/code-block-highlight"
import { toast } from "sonner"

import { cn } from "@/lib/utils"
import {
  Attachment,
  AttachmentAction,
  AttachmentActions,
  AttachmentContent,
  AttachmentDescription,
  AttachmentMedia,
  AttachmentTitle,
} from "@/components/ui/attachment"
import {
  Avatar,
  AvatarFallback,
  AvatarImage,
} from "@/components/ui/avatar"
import {
  Bubble,
  BubbleContent,
  BubbleGroup,
  BubbleReactions,
} from "@/components/ui/bubble"
import { Button } from "@/components/ui/button"
import { Item } from "@/components/ui/item"
import { Marker, MarkerContent } from "@/components/ui/marker"
import {
  Message,
  MessageAvatar,
  MessageContent,
  MessageFooter,
} from "@/components/ui/message"
import {
  MessageScroller,
  MessageScrollerContent,
  MessageScrollerItem,
  MessageScrollerProvider,
  MessageScrollerViewport,
} from "@/components/ui/message-scroller"
import { ScrollArea, ScrollBar } from "@/components/ui/scroll-area"
import {
  Tooltip,
  TooltipContent,
  TooltipTrigger,
} from "@/components/ui/tooltip"
import {
  ASSISTANT_NAME,
  type ChatMessageRecord,
  type MessagePart,
  type StarterCategory,
  type StarterPrompt,
  type ThreadRecord,
  type TranscriptRecord,
} from "./data"
import { HugeiconsIcon } from '@hugeicons/react'
import { ArrowDown01Icon, Cancel01Icon, CopyIcon, Loading03Icon, CornerDownLeftIcon, Delete02Icon, Download01Icon, FileTextIcon, MessageSquareIcon, PinIcon, SparklesIcon, ThumbsDownIcon, ThumbsUpIcon } from '@hugeicons/core-free-icons'
import { translate } from '@/lib/i18n'
import { componentsCopy } from '@/locales/components'
import { commonCopy } from '@/locales/common'
/** A region's end grows with the stream while its folded state is keyed on the
    start line, so a fold taken mid arrival would swallow every line after it. */
const NO_FOLD_REGIONS: CodeBlockFoldRegion[] = []

function CodeArtifact({
  part,
  streaming = false,
}: {
  part: Extract<MessagePart, { kind: "code" }>
  streaming?: boolean
}) {
  return (
    // w-full so the block fills the thread column instead of the w-fit bubble
    // sizing itself to the widest code line.
    <CodeBlock
      code={part.code}
      language={part.language}
      showLineNumbers
      foldable
      foldRegions={streaming ? NO_FOLD_REGIONS : undefined}
      streaming={streaming}
      className="w-full min-w-0"
    >
      {part.filename ? (
        <CodeBlockHeader>
          <CodeBlockTitle>{part.filename}</CodeBlockTitle>
          <div className="ms-auto flex items-center gap-1">
            {/* The tooltip rides a wrapper: rendered AS the button it
                overwrites the primitive own onClick and the control dies. */}
            <Tooltip>
              <TooltipTrigger render={<span className="inline-flex" />}>
                {/* A titled snippet in a transcript IS a file, so disk is the
                    next step. Terminal falls back to the language stem. */}
                <CodeBlockDownloadButton
                  label="Download file"
                  filename={
                    part.filename.includes(".") ? part.filename : undefined
                  }
                  onDownload={(name) => toast(`Downloading ${name}`)}
                />
              </TooltipTrigger>
              <TooltipContent>Download file</TooltipContent>
            </Tooltip>
            <Tooltip>
              <TooltipTrigger render={<span className="inline-flex" />}>
                <CodeBlockCopyButton />
              </TooltipTrigger>
              <TooltipContent>Copy code</TooltipContent>
            </Tooltip>
          </div>
        </CodeBlockHeader>
      ) : (
        // Headerless: the button pins over the surface, so it needs its own
        // backdrop, and a tooltip wrapper would take a line box here.
        <CodeBlockCopyButton
          variant="outline"
          size="icon-sm"
          className="bg-card hover:bg-muted"
        />
      )}
      <ScrollArea
        // Capped on the block's own line grid rather than a round number, so a
        // snippet that outgrows the box is cut between lines instead of through
        // one. Sixteen lines fits every snippet in the demo whole.
        // The block-scoped rule is inert in base; in the radix twin the
        // viewport wraps children in display:table, which breaks code width.
        className="rounded-(--code-block-radius) **:data-[slot=scroll-area-viewport]:max-h-[calc(16*var(--code-block-line-height)+var(--code-block-padding))] [&>[data-slot=scroll-area-viewport]>div]:block!"
      >
        <CodeBlockContent />
        <ScrollBar orientation="horizontal" />
      </ScrollArea>
    </CodeBlock>
  )
}

/**
 * One reveal tick. Everything below is expressed in ticks, not milliseconds.
 * 50ms rather than a frame: every tick grows the transcript, and growth costs a
 * resize observation, an autoscroll to the new bottom and a relayout of the
 * column. Measured at 30ms that work took about 37 percent of the main thread
 * and the reveal ran at two thirds of its own clock. Half the updates carrying
 * twice the text keeps the same pace and leaves the frame budget alone.
 */
const TICK_MS = 50
/** A part with nothing to type still holds the stream for a beat. */
const SILENT_TICKS = 8
/** Pause between parts, so they land one at a time instead of running on. */
const GAP_TICKS = 3

/** Code lands faster than prose, the way a real model emits it, and it costs
    the reveal less since every line boundary re-tokenizes the snippet. */
const CODE_SPEEDUP = 2

/**
 * How many visible steps a snippet arrives in, whatever its length: a line at a
 * time until a snippet runs long, which is what reads best. Highlighted rows
 * are the one costly thing a reveal paints, and the cost tracks the total rows
 * rather than how they are grouped, so this is a taste knob, not a speed one.
 */
const CODE_PASSES = 24

/** Reveal units a part contributes; an attachment costs a beat instead. */
function partCost(part: MessagePart, rate: number) {
  if (part.kind === "text") return part.text.length
  if (part.kind === "code") return Math.ceil(part.code.length / CODE_SPEEDUP)
  return rate * SILENT_TICKS
}

/** Reading pace, and the floor and cap on how long a reply may take. */
const CHARS_PER_TICK = 27
const MIN_TICKS = 29
const MAX_TICKS = 108

/**
 * One character rate for the whole reply, so a long answer takes longer than a
 * short one without ever dragging: about 1.5s at the floor, 5.4s at the cap.
 */
function revealRate(parts: MessagePart[]) {
  const typed = parts.reduce(
    (total, part) =>
      total +
      (part.kind === "text"
        ? part.text.length
        : part.kind === "code"
          ? Math.ceil(part.code.length / CODE_SPEEDUP)
          : 0),
    0
  )
  const ticks = Math.min(
    MAX_TICKS,
    Math.max(MIN_TICKS, Math.round(typed / CHARS_PER_TICK))
  )
  return Math.max(2, Math.ceil(typed / ticks))
}

type RevealedPart = {
  part: MessagePart
  /** Trails the live text, so the reader can see where the reply is. */
  caret: boolean
  /** Hands a growing snippet to the code block's own streaming treatment. */
  streaming: boolean
}

/** Walks the reply and cuts it at the revealed character. */
function sliceReply(
  parts: MessagePart[],
  revealed: number,
  rate: number
): RevealedPart[] {
  const gap = rate * GAP_TICKS
  const shown: RevealedPart[] = []
  let start = 0

  for (const part of parts) {
    const local = revealed - start
    if (local <= 0) break

    const cost = partCost(part, rate)
    if (local >= cost) {
      shown.push({ part, caret: false, streaming: false })
      start += cost + gap
      continue
    }

    if (part.kind === "text") {
      shown.push({
        part: { ...part, text: part.text.slice(0, local) },
        caret: true,
        streaming: false,
      })
    } else if (part.kind === "code") {
      // Code lands a line at a time. There is no incremental tokenizer, so a
      // character level slice re-highlights the whole snippet 33 times a
      // second and the reveal falls behind its own clock; on a line boundary
      // the source is unchanged between ticks and the pass is skipped. The
      // first line still types, where the document is one line long.
      const chars = local * CODE_SPEEDUP
      const lines = part.code.split("\n")
      const step = Math.max(1, Math.ceil(lines.length / CODE_PASSES))
      const reached = Math.floor((chars / part.code.length) * lines.length)
      const settled = Math.floor(reached / step) * step
      shown.push({
        part: {
          ...part,
          // Before the first group lands the opening line types, so the block
          // never sits there as an empty box.
          code: settled
            ? lines.slice(0, settled).join("\n") + "\n"
            : part.code.slice(0, chars),
        },
        caret: false,
        streaming: true,
      })
    } else {
      shown.push({ part, caret: false, streaming: false })
    }
    return shown
  }

  // Between parts the caret rides the last text line so the reply still reads
  // as running; a caret left on a finished reply reads as a stream that hung.
  const last = shown[shown.length - 1]
  if (shown.length < parts.length && last?.part.kind === "text")
    last.caret = true
  return shown
}

/**
 * Streams a reply in: parts land in order, text types itself out, and a code
 * snippet grows line by line under the code block's own streaming treatment.
 * Instant under reduced motion. `frozen` keeps whatever a Stop already showed,
 * so pressing Stop does not hand back the rest of the answer.
 */
function useRevealedReply(
  parts: MessagePart[],
  {
    active,
    frozen,
    onDone,
  }: { active: boolean; frozen: boolean; onDone?: () => void }
) {
  const rate = revealRate(parts)
  const gap = rate * GAP_TICKS
  const total = parts.reduce(
    (sum, part, index) =>
      sum + partCost(part, rate) + (index < parts.length - 1 ? gap : 0),
    0
  )

  const [revealed, setRevealed] = useState(active ? rate : total)
  // The parent re-creates this on every render; an effect must not restart on it.
  const doneRef = useRef(onDone)
  doneRef.current = onDone

  useEffect(() => {
    if (frozen) return
    if (!active) {
      setRevealed(total)
      return
    }
    if (window.matchMedia("(prefers-reduced-motion: reduce)").matches) {
      setRevealed(total)
      return
    }
    // Starts on the first chunk rather than on nothing, so a reply never opens
    // with an empty bubble.
    setRevealed(rate)
    const timer = window.setInterval(() => {
      setRevealed((current) => Math.min(total, current + rate))
    }, TICK_MS)
    return () => window.clearInterval(timer)
  }, [active, frozen, rate, total])

  // Reported rather than timed: only the reveal knows when the last chunk lands.
  useEffect(() => {
    if (!active || frozen || revealed < total) return
    doneRef.current?.()
  }, [active, frozen, revealed, total])

  return sliceReply(parts, revealed, rate)
}

/** True when a re-render would draw exactly what is already on screen. */
function samePart(a: MessagePart, b: MessagePart) {
  if (a.kind !== b.kind) return false
  if (a.kind === "text") return a.text === (b as typeof a).text
  if (a.kind === "code") return a.code === (b as typeof a).code
  if (a.kind === "image") return a.src === (b as typeof a).src
  // `dsl` and `result` carry only a turn id: the live state lives in the query
  // engine, and the part that renders it subscribes there itself.
  if (a.kind === "dsl" || a.kind === "result")
    return a.turnId === (b as typeof a).turnId
  return a.name === (b as typeof a).name
}

/*
 * How the host draws its own part kinds. The block knows the shape of a part,
 * never what this product puts inside one — a generated query and the rows it
 * returned are the query surface's business, not the transcript's.
 *
 * It must return an element rather than markup computed here: `PartBody` is
 * memoized on part content, and a `dsl` part's content never changes while the
 * turn behind it does. An element re-renders on its own context; a computed
 * tree would freeze at the first paint.
 */
const CustomPartContext = createContext<
  ((part: MessagePart) => ReactNode) | null
>(null)

export function CustomPartProvider({
  render,
  children,
}: {
  render: (part: MessagePart) => ReactNode
  children: ReactNode
}) {
  return (
    <CustomPartContext value={render}>{children}</CustomPartContext>
  )
}

/**
 * Compared by content, not by identity, and that is the whole performance story
 * of this block. The reveal hands every part a fresh object on every tick, so a
 * referential memo never hits: each tick re-rendered the streaming code block,
 * and each of those renders walked the ancestor chain through getComputedStyle
 * to find its scroller. Profiled at a quarter of the main thread, with typing
 * in the composer landing 340ms after the key. Slicing to the same string now
 * costs nothing.
 */
const PartBody = memo(
  function PartBody({
    part,
    caret,
    streaming,
  }: {
    part: MessagePart
    caret?: boolean
    streaming?: boolean
  }) {
    const renderCustom = useContext(CustomPartContext)
    if (part.kind === "dsl" || part.kind === "result")
      return renderCustom ? renderCustom(part) : null

    if (part.kind === "code")
      return <CodeArtifact part={part} streaming={streaming} />

    if (part.kind === "image") {
      return (
        <Attachment orientation="vertical" className="w-full max-w-xs">
          <AttachmentMedia variant="image">
            <img src={part.src} alt={part.alt} />
          </AttachmentMedia>
          <AttachmentContent>
            <AttachmentTitle>{part.caption}</AttachmentTitle>
          </AttachmentContent>
        </Attachment>
      )
    }

    if (part.kind === "file") {
      return (
        <Attachment className="w-full max-w-xs">
          <AttachmentMedia>
            <HugeiconsIcon icon={FileTextIcon} strokeWidth={2} aria-hidden="true" />
          </AttachmentMedia>
          <AttachmentContent>
            <AttachmentTitle>{part.name}</AttachmentTitle>
            <AttachmentDescription>{part.meta}</AttachmentDescription>
          </AttachmentContent>
          <AttachmentActions>
            <AttachmentAction
              type="button"
              size="icon-sm"
              variant="secondary"
              aria-label={`Download ${part.name}`}
              onClick={() => toast(`Downloading ${part.name}`)}
            >
              <HugeiconsIcon icon={Download01Icon} strokeWidth={2} aria-hidden="true" />
            </AttachmentAction>
          </AttachmentActions>
        </Attachment>
      )
    }

    // Split on backticks rather than match a closed pair: mid type the closer
    // has not arrived yet, and a lone backtick must never render as text.
    const segments = part.text.split("`")

    return (
      <p className="whitespace-pre-wrap">
        {segments.map((segment, index) =>
          index % 2 === 1 ? (
            <code
              key={index}
              className="bg-muted rounded-sm px-1 py-0.5 font-mono text-[0.85em]"
            >
              {segment}
            </code>
          ) : (
            segment
          )
        )}
        {/* The caret rides inside the last paragraph so it trails the final word
          instead of blocking onto its own line. */}
        {caret ? (
          <span
            className="bg-foreground ms-0.5 inline-block h-[1em] w-0.5 translate-y-0.5"
            aria-hidden="true"
          />
        ) : null}
      </p>
    )
  },
  (previous, next) =>
    previous.caret === next.caret &&
    previous.streaming === next.streaming &&
    samePart(previous.part, next.part)
)

/** Static icon nodes: the shadcn CLI cannot resolve icon names from props. */
const ICON_COPY = (
  <HugeiconsIcon icon={CopyIcon} strokeWidth={2} aria-hidden="true" />
)

const ICON_LIKE = (
  <HugeiconsIcon icon={ThumbsUpIcon} strokeWidth={2} aria-hidden="true" />
)

const ICON_DISLIKE = (
  <HugeiconsIcon icon={ThumbsDownIcon} strokeWidth={2} aria-hidden="true" />
)

const ICON_PIN = (
  <HugeiconsIcon icon={PinIcon} strokeWidth={2} aria-hidden="true" />
)

const ICON_THREAD = (
  <HugeiconsIcon icon={MessageSquareIcon} strokeWidth={2} aria-hidden="true" />
)

/*
 * 窗口级跟随底部。消息区不再是自己的滚动容器（整页滚），MessageScroller 的
 * autoScroll 推的是视口 scrollTop、在这里无效。规则和它一样：读者本来就在底部
 * 附近才跟；往上翻了就不打扰。新一轮开始（消息数变化）时无条件到底。
 */
function useWindowFollow(messageCount: number) {
  const stick = useRef(true)
  useEffect(() => {
    const onScroll = () => {
      const doc = document.documentElement
      stick.current = window.innerHeight + window.scrollY >= doc.scrollHeight - 160
    }
    window.addEventListener("scroll", onScroll, { passive: true })
    return () => window.removeEventListener("scroll", onScroll)
  }, [])
  // 空态（0 条消息）不跟：概览 + 示例在矮屏上会溢出，进来就被推到底、标题
  // 反而看不见。
  useEffect(() => {
    if (messageCount === 0) return
    stick.current = true
    window.scrollTo({ top: document.documentElement.scrollHeight })
  }, [messageCount])
  // 没有依赖数组：流式 token、执行结果、展开的表——只要还贴着底部，每次
  // 渲染都推到底。
  useEffect(() => {
    if (messageCount > 0 && stick.current) window.scrollTo({ top: document.documentElement.scrollHeight })
  })
}

/** Flattens a turn to the text a paste should carry: prose plus raw code. */
function turnText(messages: { parts: MessagePart[] }[]) {
  return messages
    .flatMap((message) =>
      message.parts.map((part) =>
        part.kind === "text"
          ? part.text
          : part.kind === "code"
            ? part.code
            : part.kind === "file"
              ? part.name
              : part.kind === "image"
                ? part.caption
                : ""
      )
    )
    .filter(Boolean)
    .join("\n\n")
}

function copyTurn(messages: { parts: MessagePart[] }[]) {
  navigator.clipboard
    .writeText(turnText(messages))
    .then(() => toast("Copied to clipboard"))
    .catch(() => toast.error("Copy failed"))
}

function TurnAction({
  label,
  icon,
  active = false,
  pressed = false,
  onClick,
}: {
  label: string
  icon: ReactNode
  active?: boolean
  /** Toggles carry aria-pressed; one-shot actions like Copy must not. */
  pressed?: boolean
  onClick?: () => void
}) {
  return (
    <Button
      variant="ghost"
      size="icon-xs"
      aria-label={label}
      aria-pressed={pressed ? active : undefined}
      onClick={onClick}
      className={active ? "text-primary" : undefined}
    >
      {icon}
    </Button>
  )
}

/** One reply. Owns its own reveal, so only the arriving bubble animates. */
function ReplyBubble({
  parts,
  streaming,
  frozen,
  onDone,
  children,
}: {
  parts: MessagePart[]
  streaming: boolean
  frozen: boolean
  onDone?: () => void
  children?: ReactNode
}) {
  const shown = useRevealedReply(parts, { active: streaming, frozen, onDone })

  return (
    <Bubble variant="ghost" className="w-full min-w-0">
      {/* 本仓改动：BubbleContent 自带 overflow-hidden + 1px 透明边框，ghost 变体
          没有内边距，回答卡的边线正好压在裁剪边上，1x 屏上下边框被裁成半透明
          一条。这里放开裁剪；ghost 气泡没有背景，也没东西需要裁。 */}
      <BubbleContent className="min-w-0 space-y-3 overflow-visible">
        {shown.map((item, index) => (
          <PartBody
            key={index}
            part={item.part}
            caret={item.caret}
            streaming={item.streaming}
          />
        ))}
      </BubbleContent>
      {children}
    </Bubble>
  )
}

function AssistantTurn({
  messages,
  streaming = false,
  stopped = false,
  onDone,
}: {
  messages: {
    id: string
    parts: MessagePart[]
    at: string
    reactions?: string[]
  }[]
  streaming?: boolean
  stopped?: boolean
  onDone?: () => void
}) {
  const [vote, setVote] = useState<"up" | "down" | null>(null)
  const last = messages[messages.length - 1]
  // A liked reply carries the reaction on the bubble, the way a teammate's
  // would, so the signal lives with the message and not just in the toolbar.
  const reactions = Array.from(
    new Set([
      ...(last.reactions ?? []),
      ...(vote === "up" ? ["\u{1F44D}"] : []),
    ])
  )

  return (
    <Message role="group" aria-label={ASSISTANT_NAME} className="group/turn">
      {/* The primitive bottom aligns the avatar, which reads wrong beside the
          long ghost turns this block is built on. */}
      <MessageAvatar className="translate-y-0! self-start">
        <Avatar>
          <AvatarFallback className="bg-primary/10 text-primary text-xs">
            <HugeiconsIcon icon={SparklesIcon} strokeWidth={2} className="size-3.5" aria-hidden="true" />
          </AvatarFallback>
        </Avatar>
      </MessageAvatar>

      {/* No top padding: both roles share one spine, so a reply and a send
          start on the same line as their avatar. */}
      <MessageContent className="min-w-0 gap-1">
        <BubbleGroup className="gap-5">
          {messages.map((message, index) => {
            const isLast = index === messages.length - 1
            return (
              <ReplyBubble
                key={message.id}
                parts={message.parts}
                streaming={streaming && isLast}
                frozen={stopped && isLast}
                onDone={isLast ? onDone : undefined}
              >
                {isLast && reactions.length ? (
                  <BubbleReactions
                    side="bottom"
                    align="start"
                    role="img"
                    aria-label={`Reactions: ${reactions.join(", ")}`}
                  >
                    {reactions.map((emoji, index) => (
                      <span key={index}>{emoji}</span>
                    ))}
                  </BubbleReactions>
                ) : null}
              </ReplyBubble>
            )
          })}
        </BubbleGroup>

        {streaming ? null : (
          <MessageFooter
            className={reactions.length ? "mt-4 gap-0.5" : "gap-0.5"}
          >
            {stopped ? (
              <span className="text-muted-foreground pe-1 text-xs">
                Stopped by you
              </span>
            ) : null}
            {/* Time and actions share one reveal, and the row keeps its space
                so nothing shifts when it fades in. */}
            <span className="pointer-events-none flex items-center gap-0.5 opacity-0 transition-opacity group-hover/turn:pointer-events-auto group-hover/turn:opacity-100 focus-within:pointer-events-auto focus-within:opacity-100 max-md:pointer-events-auto max-md:opacity-100">
              <span className="text-muted-foreground pe-1 text-xs tabular-nums">
                {last.at}
              </span>
              <TurnAction
                label="Copy reply"
                icon={ICON_COPY}
                onClick={() => copyTurn(messages)}
              />
              <TurnAction
                label={vote === "up" ? "Remove like" : "Like reply"}
                icon={ICON_LIKE}
                active={vote === "up"}
                pressed
                onClick={() => setVote(vote === "up" ? null : "up")}
              />
              <TurnAction
                label={vote === "down" ? "Remove dislike" : "Dislike reply"}
                icon={ICON_DISLIKE}
                active={vote === "down"}
                pressed
                onClick={() => setVote(vote === "down" ? null : "down")}
              />
            </span>
          </MessageFooter>
        )}
      </MessageContent>
    </Message>
  )
}

function UserTurn({ messages }: { messages: ChatMessageRecord[] }) {
  // User turns always carry their author; a null author is an assistant turn.
  const person = messages[0].author
  const last = messages[messages.length - 1]
  if (!person) return null

  return (
    <Message
      align="end"
      className="group/turn"
      role="group"
      aria-label={person.name}
    >
      <MessageAvatar>
        <Avatar>
          <AvatarImage src={person.avatar} alt="" />
          <AvatarFallback className="text-xs">{person.initials}</AvatarFallback>
        </Avatar>
      </MessageAvatar>
      <MessageContent className="min-w-0 gap-1">
        {/* Consecutive sends stack under one avatar, the way a real thread
            reads, instead of repeating the identity on every line. */}
        <BubbleGroup className="w-full items-end gap-3">
          {messages.map((message) => (
            <Bubble key={message.id} variant="muted" align="end">
              <BubbleContent className="space-y-2">
                {message.parts.map((part, index) => (
                  <PartBody key={index} part={part} />
                ))}
              </BubbleContent>
            </Bubble>
          ))}
        </BubbleGroup>

        {/* Your own turns keep a quiet row: the actions only appear on hover or
            keyboard focus, so the transcript stays the content. */}
        <MessageFooter className="gap-0.5 pe-0">
          {/* pointer-events-none so the hidden row is not tappable, and always
              shown below md where there is no hover to reveal it. */}
          <span className="pointer-events-none flex items-center gap-0.5 opacity-0 transition-opacity group-hover/turn:pointer-events-auto group-hover/turn:opacity-100 focus-within:pointer-events-auto focus-within:opacity-100 max-md:pointer-events-auto max-md:opacity-100">
            <span className="text-muted-foreground pe-1 text-xs tabular-nums">
              {last.at}
            </span>
            <TurnAction
              label="Copy message"
              icon={ICON_COPY}
              onClick={() => copyTurn(messages)}
            />
          </span>
        </MessageFooter>
      </MessageContent>
    </Message>
  )
}

/** How many recent chats the starter offers. Kept short so the composer stays
    the focus; the header switcher owns the full history. */
const SHORTCUT_LIMIT = 4

function ThreadStart({
  heading,
  subheading,
  emptyExtra,
  composer,
  starters,
  threads,
  onStart,
  onSelectThread,
  onDeleteThread,
  onDraft,
}: {
  heading: string
  subheading: string
  /** 空态里插在标题和示例问题之间的东西（本产品放「今天要处理的」四格）。
      和 `composerTools` 一样是产品部件的插槽，块自己不知道里面是什么。 */
  emptyExtra?: React.ReactNode
  /** 空态里的 ask box（照 ai-chat-10 的欢迎页放在标题正下方）。 */
  composer?: React.ReactNode
  /** Suggested questions, grouped by the rail above them. */
  starters: StarterCategory[]
  /** Doubles as the nav for this block: it ships without a thread sidebar. */
  threads: ThreadRecord[]
  onStart: (text: string) => void
  onSelectThread: (id: string) => void
  onDeleteThread?: (id: string) => void
  /** 把一句草稿放进输入框（示例卡的「自己写一句」）。 */
  onDraft?: (text: string) => void
}) {
  const [categoryId, setCategoryId] = useState(starters[0]?.id ?? "")
  // 展开了哪张示例卡的选项。切栏就收起。
  const [openPrompt, setOpenPrompt] = useState<string | null>(null)
  // 「让 AI 再想几个角度」追加的问句，按卡记；同一张卡再点一次接着追加。
  const [extraAngles, setExtraAngles] = useState<Record<string, string[]>>({})
  const [angleBusy, setAngleBusy] = useState<string | null>(null)
  const [angleError, setAngleError] = useState<string | null>(null)

  async function askMoreAngles(prompt: StarterPrompt) {
    if (!prompt.moreAngles || angleBusy) return
    setAngleBusy(prompt.text)
    setAngleError(null)
    try {
      const have = [...(prompt.options ?? []).map((o) => o.label), ...(extraAngles[prompt.text] ?? [])]
      let got = 0
      await prompt.moreAngles(have, (text) => {
        got += 1
        setExtraAngles((cur) => ({ ...cur, [prompt.text]: [...(cur[prompt.text] ?? []), text] }))
      })
      if (got === 0) setAngleError(translate(componentsCopy, 'starterMoreAnglesNone'))
    } catch (e) {
      setAngleError(e instanceof Error ? e.message : String(e))
    } finally {
      setAngleBusy(null)
    }
  }
  const category =
    starters.find((item) => item.id === categoryId) ?? starters[0]
  const shortcuts = [
    ...threads.filter((thread) => thread.pinned),
    ...threads.filter((thread) => !thread.pinned),
  ].slice(0, SHORTCUT_LIMIT)

  return (
    <div className="mx-auto flex min-h-full w-full max-w-2xl flex-col justify-center px-4 py-6 sm:px-6">
      {/* 本仓改动：`emptyExtra`（今天有什么要处理的四张卡）排在标题上面。
          打开产品第一眼该看到的是「有 8 条待处置告警」，不是产品自己的自我介绍；
          标题往下挪一格，正好挨着下面的提示词和输入框，读起来是同一件事的开头。 */}
      {emptyExtra && <div className="mb-5">{emptyExtra}</div>}

      {/* 照 ai-chat-10 的 WelcomeHero：一行标题、一个焦点，居中压在 ask box 的中轴上。 */}
      <div className="flex flex-col items-center gap-1.5 text-center">
        <h2 className="text-2xl font-semibold tracking-tight text-balance">{heading}</h2>
        <p className="text-muted-foreground text-sm">{subheading}</p>
      </div>

      {composer && <div className="mt-5">{composer}</div>}

      {/* Category rail: picking one swaps the suggestions below it.
          本仓改动：只有一栏时不画分段控件（一个孤零零的胶囊靠左很怪），把那栏的
          名字当一句居中的小标题。 */}
      {starters.length === 1 ? (
        <p className="text-muted-foreground mt-6 text-center text-xs">{starters[0].label}</p>
      ) : null}
      <div className={cn("mt-5 flex flex-wrap gap-2", starters.length === 1 && "hidden")}>
        {starters.map((item) => {
          const selected = item.id === categoryId
          return (
            <Button
              key={item.id}
              variant="outline"
              size="sm"
              aria-pressed={selected}
              onClick={() => { setCategoryId(item.id); setOpenPrompt(null) }}
              className={cn(
                "rounded-full font-normal transition-colors [&_svg]:size-3.5",
                selected
                  ? "border-foreground/20 bg-foreground/8 text-foreground font-medium"
                  : "text-muted-foreground hover:text-foreground hover:bg-foreground/5"
              )}
            >
              {item.icon}
              {item.label}
            </Button>
          )
        })}
      </div>

      {/* 示例问题照 ai-chat-10 的 StarterCards：三列描边卡，整卡可点。原来是一列
          分隔线行，五条排成一竖条，看不出是「点一下就问」。 */}
      {/* 本仓改动：示例卡比上面的输入框那一列宽一截（lg 起两侧各溢出 8rem）。
          只有三张时两侧留白太大、卡又挤；现在六张三列两行，卡有呼吸的空间。 */}
      <div className={cn("grid gap-3 sm:grid-cols-3 lg:-mx-32", starters.length === 1 ? "mt-3" : "mt-5")}>
        {category?.prompts.map((prompt) => (
          <Item
            key={prompt.text}
            variant="outline"
            render={<button type="button" />}
            aria-expanded={prompt.options ? openPrompt === prompt.text : undefined}
            onClick={() =>
              prompt.options
                ? setOpenPrompt((cur) => (cur === prompt.text ? null : prompt.text))
                : onStart(prompt.text)
            }
            className={cn(
              "group/prompt h-full items-start p-3 text-start hover:bg-accent/50",
              openPrompt === prompt.text && "border-foreground/30 bg-accent/50",
            )}
          >
            {/* 大字是小白会问的那句，小字说它实际会去查什么 —— 问得傻没关系，
                但要让人看见「傻问题」是怎么落成一条具体查询的。 */}
            <span className="flex min-w-0 flex-1 flex-col gap-1">
              <span className="text-sm/5 font-medium text-foreground">{prompt.label}</span>
              {prompt.hint ? (
                <span className="text-xs/4 text-muted-foreground">{prompt.hint}</span>
              ) : null}
            </span>
            {/* 带选项的卡点了是展开，不是发送 —— 角标别用回车。 */}
            <HugeiconsIcon
              icon={prompt.options ? ArrowDown01Icon : CornerDownLeftIcon}
              strokeWidth={2}
              className={cn(
                "mt-0.5 size-4 shrink-0 opacity-40 transition-all group-hover/prompt:opacity-100",
                prompt.options && openPrompt === prompt.text && "rotate-180 opacity-100",
              )}
              aria-hidden="true"
            />
          </Item>
        ))}
      </div>

      {/* 本仓改动：点了带选项的卡，卡下面展开一组具体问法。傻问题有很多种具体
          查法，替人挑一种等于替人下结论；列出来让他挑，挑不到就自己写。 */}
      {(() => {
        const active = category?.prompts.find((p) => p.text === openPrompt)
        if (!active?.options) return null
        return (
          <Frame dense spacing="sm" className="mt-3 w-full lg:-mx-32 lg:w-auto">
            <FrameHeader className="flex-row items-center justify-between gap-3 py-2">
              <FrameTitle className="text-sm">
                {translate(componentsCopy, 'starterOptionsTitle', { question: active.label })}
              </FrameTitle>
              <Button
                variant="ghost"
                size="icon-sm"
                aria-label={translate(componentsCopy, 'starterOptionsClose')}
                onClick={() => setOpenPrompt(null)}
              >
                <HugeiconsIcon icon={Cancel01Icon} strokeWidth={2} className="size-3.5" aria-hidden="true" />
              </Button>
            </FrameHeader>
            <FramePanel className="p-0">
              <ul className="divide-y divide-border">
                {active.options.map((opt) => (
                  <li key={opt.text}>
                    <button
                      type="button"
                      onClick={() => onStart(opt.text)}
                      className="group/opt flex w-full items-center gap-3 px-3 py-2.5 text-start text-sm hover:bg-accent/50"
                    >
                      <span className="min-w-0 flex-1 text-foreground">{opt.label}</span>
                      {opt.scope ? (
                        <span className="hidden shrink-0 font-mono text-11 text-muted-foreground sm:inline">{opt.scope}</span>
                      ) : null}
                      <HugeiconsIcon icon={CornerDownLeftIcon} strokeWidth={2} className="size-4 shrink-0 opacity-40 transition-opacity group-hover/opt:opacity-100" aria-hidden="true" />
                    </button>
                  </li>
                ))}
                {(extraAngles[active.text] ?? []).map((text) => (
                  <li key={text}>
                    <button
                      type="button"
                      onClick={() => onStart(`${active.label}${translate(componentsCopy, 'starterAngleJoin')}${text}`)}
                      className="group/opt flex w-full items-center gap-3 px-3 py-2.5 text-start text-sm hover:bg-accent/50"
                    >
                      <span className="min-w-0 flex-1 text-foreground">{text}</span>
                      <Badge variant="info-light" size="xs">AI</Badge>
                      <HugeiconsIcon icon={CornerDownLeftIcon} strokeWidth={2} className="size-4 shrink-0 opacity-40 transition-opacity group-hover/opt:opacity-100" aria-hidden="true" />
                    </button>
                  </li>
                ))}
                {active.moreAngles ? (
                  <li>
                    <button
                      type="button"
                      disabled={angleBusy === active.text}
                      onClick={() => void askMoreAngles(active)}
                      className="flex w-full items-center gap-2 px-3 py-2.5 text-start text-sm text-muted-foreground hover:bg-accent/50 hover:text-foreground disabled:opacity-60"
                    >
                      <HugeiconsIcon
                        icon={angleBusy === active.text ? Loading03Icon : SparklesIcon}
                        strokeWidth={2}
                        className={cn("size-3.5 shrink-0", angleBusy === active.text && "animate-spin")}
                        aria-hidden="true"
                      />
                      <span className="min-w-0 flex-1">
                        {angleBusy === active.text
                          ? translate(componentsCopy, 'starterMoreAnglesBusy')
                          : translate(componentsCopy, 'starterMoreAngles')}
                      </span>
                      {angleError ? <span className="text-xs text-destructive">{angleError}</span> : null}
                    </button>
                  </li>
                ) : null}
                {onDraft ? (
                  <li>
                    <button
                      type="button"
                      onClick={() => { onDraft(active.label); setOpenPrompt(null) }}
                      className="flex w-full items-center gap-3 px-3 py-2.5 text-start text-sm text-muted-foreground hover:bg-accent/50 hover:text-foreground"
                    >
                      <span className="min-w-0 flex-1">{translate(componentsCopy, 'starterOptionsCustom')}</span>
                    </button>
                  </li>
                ) : null}
              </ul>
            </FramePanel>
          </Frame>
        )
      })()}

      {/* Shortcuts back into the existing threads, pinned ones first. One
          column at every width, so the times read as a real column. */}
      {shortcuts.length > 0 ? (
        <div className="-mx-2 mt-6 flex flex-col gap-1.5">
          <h3 className="text-muted-foreground px-2 text-xs font-medium">
            {translate(componentsCopy, 'recentThreads')}
          </h3>
          {/* Dense on purpose: rows touch on one tight rhythm, and only the
              meta recedes, so the titles stay at full reading contrast. */}
          <div className="flex flex-col">
            {shortcuts.map((thread) => (
              // 本仓改动：行右边挂一个删除；按钮不能套在按钮里，所以行是 div，
              // 主体和删除各自是按钮。删除 hover / 聚焦时才显形。
              <div key={thread.id} className="group/thread flex items-center gap-1">
              <Button
                variant="ghost"
                onClick={() => onSelectThread(thread.id)}
                className="[&_svg]:text-muted-foreground h-8 min-w-0 flex-1 justify-start gap-2.5 px-2 font-normal [&_svg]:size-3.5"
              >
                {thread.pinned ? ICON_PIN : ICON_THREAD}
                <span className="min-w-0 flex-1 truncate text-start">
                  {thread.title}
                </span>
                {/* Same outline chip the header switcher gives an artifact, so
                    the two surfaces speak one language. */}
                {thread.artifact ? (
                  <Badge
                    variant="outline"
                    size="sm"
                    className="text-muted-foreground max-w-32 min-w-0 font-mono font-normal"
                  >
                    <span className="min-w-0 truncate">{thread.artifact}</span>
                  </Badge>
                ) : null}
                <span className="text-muted-foreground w-14 shrink-0 text-end text-xs tabular-nums">
                  {thread.updatedLabel}
                </span>
              </Button>
              {onDeleteThread ? (
                <Button
                  variant="ghost"
                  size="icon-sm"
                  aria-label={translate(componentsCopy, 'deleteThreadAria', { title: thread.title })}
                  title={translate(commonCopy, 'delete')}
                  onClick={() => onDeleteThread(thread.id)}
                  className="text-muted-foreground opacity-0 transition-opacity group-focus-within/thread:opacity-100 group-hover/thread:opacity-100 focus-visible:opacity-100 hover:text-destructive"
                >
                  <HugeiconsIcon icon={Delete02Icon} strokeWidth={2} className="size-3.5" aria-hidden="true" />
                </Button>
              ) : null}
              </div>
            ))}
          </div>
        </div>
      ) : null}
    </div>
  )
}

/** Consecutive turns from the same speaker render under one avatar. */
function groupTurns(messages: ChatMessageRecord[]) {
  const groups: ChatMessageRecord[][] = []
  for (const message of messages) {
    const last = groups[groups.length - 1]
    if (
      last &&
      last[0].role === message.role &&
      last[0].author?.name === message.author?.name
    ) {
      last.push(message)
      continue
    }
    groups.push([message])
  }
  return groups
}

export function ChatThread({
  transcript,
  title,
  streaming,
  stopped,
  arrivingId,
  stoppedIds,
  threads,
  starters,
  heading,
  subheading,
  emptyExtra,
  composer,
  activityLabel,
  onStart,
  onSelectThread,
  onDeleteThread,
  onDraft,
  onArrived,
}: {
  transcript: TranscriptRecord
  title: string
  streaming: boolean
  stopped: boolean
  arrivingId: string | null
  /** Replies a Stop cut short, which must stay cut short from then on. */
  stoppedIds: string[]
  /** Offered as shortcuts on the starter view, newest and pinned first. */
  threads: ThreadRecord[]
  /** Zero-state copy and suggestions, both this product's own. */
  starters: StarterCategory[]
  heading: string
  subheading: string
  /** 空态里插在标题和示例问题之间的东西（本产品放「今天要处理的」四格）。
      和 `composerTools` 一样是产品部件的插槽，块自己不知道里面是什么。 */
  emptyExtra?: React.ReactNode
  composer?: React.ReactNode
  /** Step shown while a live send waits. */
  activityLabel: string
  onStart: (text: string) => void
  onSelectThread: (id: string) => void
  onDeleteThread?: (id: string) => void
  onDraft?: (text: string) => void
  onArrived: () => void
}) {
  const { compacted, dateLabel, messages, pending } = transcript

  // Warms Shiki early, or the first streamed snippet renders plain the whole
  // way and only colours at the end.
  useEffect(() => {
    void highlightCode("const ready = true", { language: "typescript" })
  }, [])

  // A run that finished delivers its closing clause; a stopped one keeps only
  // the text it had already produced.
  useWindowFollow(messages.length)

  const tail =
    pending && !streaming && !stopped && pending.rest
      ? pending.parts.map((part, index) =>
          index === pending.parts.length - 1 && part.kind === "text"
            ? { ...part, text: part.text + pending.rest }
            : part
        )
      : pending?.parts

  // The starter runs taller than the transcript column on a short viewport, so
  // it owns the scroll and centres only while it fits.
  if (messages.length === 0 && !pending) {
    return (
      <div className="flex min-h-0 flex-1 flex-col">
        <ThreadStart
          heading={heading}
          subheading={subheading}
          emptyExtra={emptyExtra}
          composer={composer}
          starters={starters}
          threads={threads}
          onStart={onStart}
          onSelectThread={onSelectThread}
          onDeleteThread={onDeleteThread}
          onDraft={onDraft}
        />
      </div>
    )
  }

  return (
    // Bottom following, with no anchored item anywhere in the transcript: the
    // peek prop only reads on a scrollAnchor element, so it would be inert here.
    // 整页滚（产品决定：输入框跟着内容走，滚动条只有外壳那一条）：MessageScroller
    // 的视口不再自己滚——overflow / contain / 等待首滚时的 invisible 全部覆盖掉，
    // 结构和 Item 的 scrollAnchor 语义保留。跟随底部改成窗口级，见 useWindowFollow。
    <MessageScrollerProvider autoScroll>
      <MessageScroller className="h-auto min-h-0 flex-1 overflow-visible">
        <MessageScrollerViewport className="h-auto overflow-visible contain-none data-pending-scroll:visible">
          {/* 本仓改动：对话列从 max-w-3xl 放宽到 6xl。回答里是结果表，768px 的
              列宽下八列就得横向拖；放宽后「我」的气泡贴右、回答贴左，中间是表格
              该有的空间。空态（ThreadStart）仍是窄列，那里只有输入框和示例。 */}
          <MessageScrollerContent
            aria-busy={streaming}
            className="mx-auto flex w-full max-w-6xl min-w-0 flex-col gap-6 px-4 py-6 sm:px-6"
          >
            {/* The header has no room for this below md, so it leads the
                transcript instead and scrolls away with it. */}
            <MessageScrollerItem
              scrollAnchor={false}
              className="[content-visibility:visible]"
            >
              <div className="flex items-center gap-2 md:hidden">
                <h1 className="min-w-0 flex-1 truncate text-base font-semibold tracking-tight">
                  {title}
                </h1>
                {streaming ? (
                  <Badge variant="primary-light" size="sm">
                    Working
                  </Badge>
                ) : null}
              </div>
            </MessageScrollerItem>

            {dateLabel ? (
              <MessageScrollerItem
                scrollAnchor={false}
                className="[content-visibility:visible]"
              >
                <Marker variant="separator">
                  <MarkerContent>{dateLabel}</MarkerContent>
                </Marker>
              </MessageScrollerItem>
            ) : null}

            {compacted ? (
              <MessageScrollerItem
                scrollAnchor={false}
                className="[content-visibility:visible]"
              >
                <Marker variant="separator">
                  <MarkerContent>{compacted}</MarkerContent>
                </Marker>
              </MessageScrollerItem>
            ) : null}

            {/* Unanchored on purpose: top anchoring never opens the spacer
                under variable-height groups, typing replies below the fold. */}
            {groupTurns(messages).map((group) => {
              const arriving = group.some(
                (message) => message.id === arrivingId
              )
              return (
                <MessageScrollerItem
                  key={group[0].id}
                  messageId={group[group.length - 1].id}
                  // Opacity-only entrance: a transform here mismeasures the
                  // item's extent and breaks bottom-following.
                  className="animate-in fade-in-0 duration-300 ease-out [content-visibility:visible] motion-reduce:animate-none"
                >
                  {group[0].role === "user" ? (
                    <UserTurn messages={group} />
                  ) : (
                    <AssistantTurn
                      messages={group}
                      streaming={arriving}
                      stopped={stoppedIds.includes(group[group.length - 1].id)}
                      onDone={arriving ? onArrived : undefined}
                    />
                  )}
                </MessageScrollerItem>
              )
            })}

            {pending ? (
              <MessageScrollerItem
                scrollAnchor={false}
                className="[content-visibility:visible]"
              >
                <AssistantTurn
                  messages={[
                    { id: "pending", ...pending, parts: tail ?? pending.parts },
                  ]}
                  streaming={streaming}
                  stopped={stopped}
                  onDone={onArrived}
                />
              </MessageScrollerItem>
            ) : null}

            {/* 本仓改动：块原来在这里画一条「等待中」的 Marker（spinner + 活动
                文案）。这个产品一发问回答卡就已经在屏上了，卡的 chrome 条写着
                阶段、正文里还有同一句进度 —— 卡下面再来一条就是三处说同一件事。
                删掉；读屏那份 role=status 留在下面。 */}
          </MessageScrollerContent>
        </MessageScrollerViewport>

        {/* aria-busy silences the log, so the in-flight step is announced from
            outside it rather than not at all. */}
        <p role="status" aria-live="polite" className="sr-only">
          {streaming ? (pending?.activityLabel ?? activityLabel) : ""}
        </p>

      </MessageScroller>
    </MessageScrollerProvider>
  )
}