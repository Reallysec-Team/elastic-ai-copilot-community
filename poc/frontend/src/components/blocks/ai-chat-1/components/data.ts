import type { ReactNode } from "react"

/*
 * Types only.
 *
 * The block shipped ~1.2k lines of seeded demo data here (four threads, their
 * transcripts, a reply library and a `draftReply()` that faked the model).
 * Everything that renders now comes from the host through props — see
 * `routes/ChatPage.tsx`, which drives this surface off `/api/generate`,
 * `/api/execute` and `/api/conversations`.
 */

/** Shown as the accessible name of an assistant turn. */
export const ASSISTANT_NAME = "Copilot"

/** The id the surface uses for a chat that has not been sent yet. */
export const NEW_THREAD_ID = "th_new"

export type ModelRecord = {
  id: string
  name: string
  provider: string
  /** Context window label; contextTokens is the same number for the math. */
  context: string
  contextTokens: number
  capability: string
  /** Called out in the picker as the default for most work. */
  recommended?: boolean
}

export type PersonRecord = {
  name: string
  initials: string
  avatar: string
}

/** Context accounting for the open thread, when the host can report it. */
export type UsageRecord = {
  used: number
  costLabel: string
}

export type StarterCategory = {
  id: string
  label: string
  /** Rail glyph. Passed in, because the block has no vocabulary of its own. */
  icon?: ReactNode
  prompts: StarterPrompt[]
}

/** 本仓改动：一张示例卡 = 小白会问的那句（label）+ 它实际去查什么（hint）+
    真正发出去的问句（text）。以前只有一个字符串，卡上写什么就发什么。 */
export type StarterPrompt = {
  label: string
  hint?: string
  text: string
  /** 有这个就不直接发：点卡展开一组具体的问法让人挑，或自己写。 */
  options?: StarterOption[]
  /** 「让 AI 再想几个角度」：问句一条条回调、追加到选项后面，整个流完了才 resolve。
      没有就不画那一行。 */
  moreAngles?: (existing: string[], onAngle: (text: string) => void) => Promise<void>
}

export type StarterOption = {
  label: string
  /** 真正发出去的问句。 */
  text: string
  /** 这条会查哪类数据（给人看的，例如 `logs-linux.auth-*`）。 */
  scope?: string
}

export type ThreadRecord = {
  id: string
  title: string
  updatedLabel: string
  /** Recency section the switcher files this thread under. */
  recency: "today" | "earlier"
  pinned: boolean
  /** File the thread produced or reads, shown as meta on its switcher row. */
  artifact?: string
}

/*
 * `dsl` and `result` are this product's own parts. The block shipped prose,
 * code, images and files; an answer here is a generated Elasticsearch query and
 * the rows it returned, and both stay interactive after they land — the DSL is
 * expandable, editable and re-runnable, which is the product's whole claim.
 *
 * They carry a turn id rather than the payload: the query engine owns that
 * state and keeps mutating it (a sort, a size change, a re-run all patch the
 * same turn), so a part that copied it would render a stale snapshot. The
 * renderer reads the live turn out of `TurnContext`.
 */
export type MessagePart =
  | { kind: "text"; text: string }
  | { kind: "code"; language: string; code: string; filename?: string }
  | { kind: "image"; src: string; alt: string; caption: string }
  | { kind: "file"; name: string; meta: string }
  | { kind: "dsl"; turnId: string }
  | { kind: "result"; turnId: string }

export type ChatMessageRecord = {
  id: string
  role: "user" | "assistant"
  /** Null on assistant turns: the assistant is not a human author record. */
  author: PersonRecord | null
  parts: MessagePart[]
  at: string
  /** Emoji already left on this turn by teammates in the thread. */
  reactions?: string[]
}

export type TranscriptRecord = {
  /** Turns already committed to the thread. */
  messages: ChatMessageRecord[]
  /** Set only on a thread whose reply is still arriving. */
  pending?: {
    activityLabel: string
    parts: MessagePart[]
    at: string
    /** Appended when the run finishes on its own; withheld when stopped. */
    rest?: string
  }
  /** Shown above the first turn when earlier context was compacted away. */
  compacted?: string
  /** Date separator above the scrollback when it spans a day boundary. */
  dateLabel?: string
}
