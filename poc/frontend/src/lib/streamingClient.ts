/*
 * SSE client for /api/generate/stream.
 *
 * Browsers don't expose EventSource for POST requests with bodies, so we hand-
 * roll the parser on top of `fetch` + a `ReadableStream`. The server side emits
 * `data: <json>\n\n` frames; we split on the blank-line separator and dispatch.
 *
 * Returns an `AbortController` so callers can cancel mid-stream.
 */

import type { AppliedTimeWindow } from '@/lib/api'
import { emitLicenseBlocked, type InvestigateResponse } from '@/lib/api'
import { translate } from '@/lib/i18n'
import { libCopy } from '@/locales/lib'
import { apiErrorMessage } from '@/locales/errors'

/** 这次查询的索引是怎么定下来的（backend/index_router.py）。 */
export interface IndexRouting {
  /** 'given' 用户自己指定 · 'conversation' 追问沿用上一轮 · 'name' 名字匹配 · 'model' 模型挑 · 'scope' 全部日志兜底 */
  source: 'given' | 'conversation' | 'name' | 'model' | 'scope'
  reason: string
  considered?: string[]
}

export interface StreamMetaEvent {
  type: 'meta'
  conversation_id?: string | null
  prompt_version?: string | null
  /** 网关最终用的 index 串。请求没带 index 时由它挑，执行必须用这个值。 */
  index?: string | null
  routing?: IndexRouting | null
}

export interface StreamChunkEvent {
  type: 'chunk'
  text: string
  provider?: string
}

/** 模型的推理增量（豆包 / DeepSeek / Qwen 会吐）。有就转发，界面折叠着显示。 */
export interface StreamThinkingEvent {
  type: 'thinking'
  text: string
}

export interface TokenUsage {
  prompt_tokens?: number | null
  completion_tokens?: number | null
  total_tokens?: number | null
}

export interface StreamDoneEvent {
  type: 'done'
  dsl: Record<string, unknown> | null
  explanation: string
  confidence: 'low' | 'medium' | 'high'
  confidence_reason?: string | null
  validation_error?: string | null
  duration_ms?: number
  output_chars?: number
  usage?: TokenUsage | null
  conversation_id?: string | null
  /** 后端实际套上去的时间窗；界面据此显示那枚 chip。 */
  time_window?: AppliedTimeWindow | null
}

export interface StreamErrorEvent {
  type: 'error'
  message: string
  /** 后端错误码（同 REST 的 code/params），有码的走 apiErrorMessage 翻译。 */
  code?: string
  params?: Record<string, unknown>
}

export type StreamEvent =
  | StreamMetaEvent
  | StreamChunkEvent
  | StreamThinkingEvent
  | StreamDoneEvent
  | StreamErrorEvent

export interface StreamGenerateRequest {
  /** 留空 = 让网关按问题自己挑索引。 */
  index?: string
  question: string
  conversation_id?: string | null
  /** 界面选的时间范围（ISO）。都不给 = 全部时间 = 后端什么都不改。 */
  since?: string
  until?: string
  /** 用户的「深度思考」开关；不传 = 后端默认档。 */
  reasoning?: 'on' | 'off'
}

export interface StreamCallbacks {
  onMeta?: (e: StreamMetaEvent) => void
  onChunk?: (e: StreamChunkEvent) => void
  onThinking?: (e: StreamThinkingEvent) => void
  onDone?: (e: StreamDoneEvent) => void
  onError?: (message: string, code?: string) => void
}

/**
 * Start a streaming generate. Returns an AbortController; call .abort() to
 * cancel the request and stop reading frames.
 */
export function streamGenerate(
  req: StreamGenerateRequest,
  cb: StreamCallbacks,
): AbortController {
  const ctrl = new AbortController()
  void runStream(req, cb, ctrl).catch((e: unknown) => {
    if ((e as { name?: string })?.name === 'AbortError') return
    cb.onError?.(e instanceof Error ? e.message : String(e))
  })
  return ctrl
}

async function runStream(
  req: StreamGenerateRequest,
  cb: StreamCallbacks,
  ctrl: AbortController,
): Promise<void> {
  const r = await fetch('/api/generate/stream', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(req),
    signal: ctrl.signal,
  })
  if (!r.ok) {
    let detail = `HTTP ${r.status}`
    let body: unknown
    try {
      body = await r.json()
      detail = apiErrorMessage(body, detail)
    } catch {
      // ignore
    }
    // This path bypasses api.ts's request(), so surface license hard-fails here
    // too — and blank the message, since AppShell's banner carries the text.
    if (emitLicenseBlocked(r.status, body, detail)) {
      cb.onError?.('')
      return
    }
    cb.onError?.(detail)
    return
  }
  if (!r.body) {
    cb.onError?.('response has no body')
    return
  }

  const reader = r.body.getReader()
  const decoder = new TextDecoder('utf-8')
  let buffer = ''
  let sawDone = false
  // 终帧（done | error）到底有没有交到调用方手上。
  const settled = { done: false }
  while (true) {
    const { done, value } = await reader.read()
    if (done) break
    buffer += decoder.decode(value, { stream: true })
    // Normalize CRLF → LF so frames split on the blank line regardless of the
    // server's / an intermediary proxy's line endings (a `\r\n\r\n`-delimited
    // frame contains no adjacent `\n\n` and would otherwise never split).
    // Re-running over the whole buffer also fixes a `\r` left dangling at a
    // chunk boundary once its `\n` arrives in the next read.
    if (buffer.includes('\r')) buffer = buffer.replace(/\r\n/g, '\n')

    // SSE frames are separated by a blank line — `\n\n` in our case.
    let sep: number
    while ((sep = buffer.indexOf('\n\n')) >= 0) {
      const block = buffer.slice(0, sep)
      buffer = buffer.slice(sep + 2)
      if (dispatchBlock(block, cb, false, settled)) sawDone = true
    }
  }
  // Trailing residue after the stream closes. If we already delivered a `done`
  // event, the leftover is just a frame fragment — ignore it so it can't clobber
  // an already-successful result with a bogus "unparseable SSE frame" error.
  // When no `done` was seen we still try to parse it, but tolerantly: a garbled
  // tail frame is warned, not surfaced as an error.
  if (buffer.trim().length > 0) {
    if (sawDone) {
      console.warn('streamGenerate: ignoring trailing SSE frame after done:', buffer.slice(0, 120))
    } else {
      dispatchBlock(buffer, cb, true, settled)
    }
  }
  // 流可以在没有终帧的情况下结束：网关崩了，或者反向代理掐断了空闲连接。
  // 那种情况 onDone/onError 都不触发，调用方这一轮永远停在 generating、
  // busy 恒真，界面上只剩「停止」按钮。同 runInvestigateStream 的兜底。
  if (!settled.done) cb.onError?.(translate(libCopy, 'scBrokenGenerate'))
}

// ── Investigate (alert調査) staged-progress SSE ─────────────────────────────
// Consumes /api/investigate-alert/stream: `stage` markers between pipeline steps
// then one `result` frame. Same fetch+frame machinery as streamGenerate above
// (browsers can't EventSource a POST body), different event shape.

export interface InvestigateStageEvent {
  type: 'stage'
  key: string
  label: string
  status: 'active' | 'done'
  detail?: string
}

export interface InvestigateStreamCallbacks {
  onStage?: (e: InvestigateStageEvent) => void
  onResult?: (r: InvestigateResponse) => void
  onError?: (message: string) => void
}

export interface InvestigateStreamRequest {
  index: string
  alert: Record<string, unknown>
  window_minutes?: number
  reasoning?: 'on' | 'off'
}

export function streamInvestigate(
  req: InvestigateStreamRequest,
  cb: InvestigateStreamCallbacks,
): AbortController {
  const ctrl = new AbortController()
  void runInvestigateStream(req, cb, ctrl).catch((e: unknown) => {
    if ((e as { name?: string })?.name === 'AbortError') return
    cb.onError?.(e instanceof Error ? e.message : String(e))
  })
  return ctrl
}

async function runInvestigateStream(
  req: InvestigateStreamRequest,
  cb: InvestigateStreamCallbacks,
  ctrl: AbortController,
): Promise<void> {
  const r = await fetch('/api/investigate-alert/stream', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(req),
    signal: ctrl.signal,
  })
  if (!r.ok) {
    let detail = `HTTP ${r.status}`
    let body: unknown
    try {
      body = await r.json()
      detail = apiErrorMessage(body, detail)
    } catch {
      // ignore
    }
    if (emitLicenseBlocked(r.status, body, detail)) {
      cb.onError?.('')
      return
    }
    cb.onError?.(detail)
    return
  }
  if (!r.body) {
    cb.onError?.('response has no body')
    return
  }

  const reader = r.body.getReader()
  const decoder = new TextDecoder('utf-8')
  let buffer = ''
  // Did a terminal frame (result | error) actually reach the caller?
  const settled = { done: false }
  const drain = () => {
    let sep: number
    while ((sep = buffer.indexOf('\n\n')) >= 0) {
      const block = buffer.slice(0, sep)
      buffer = buffer.slice(sep + 2)
      dispatchInvestigateBlock(block, cb, settled)
    }
  }
  while (true) {
    const { done, value } = await reader.read()
    if (done) break
    buffer += decoder.decode(value, { stream: true })
    if (buffer.includes('\r')) buffer = buffer.replace(/\r\n/g, '\n')
    drain()
  }
  // A stream can end without a terminal frame: the gateway crashes, or a proxy
  // times out an idle connection — and investigate legitimately runs 30-60s.
  // Without this the caller's `finally` never runs, so the dialog spins forever
  // with no error and (having no 停止 button) no way back, indistinguishable
  // from a slow model.
  if (!settled.done) cb.onError?.(translate(libCopy, 'scBrokenInvestigate'))
}

function dispatchInvestigateBlock(
  block: string,
  cb: InvestigateStreamCallbacks,
  settled?: { done: boolean },
): void {
  const dataLines: string[] = []
  for (const line of block.split('\n')) {
    if (line.startsWith('data: ')) dataLines.push(line.slice(6))
    else if (line.startsWith('data:')) dataLines.push(line.slice(5))
  }
  if (dataLines.length === 0) return // `:`-comment keep-alive frame
  let event: InvestigateStageEvent | { type: 'result'; result: InvestigateResponse } | { type: 'error'; message: string }
  try {
    event = JSON.parse(dataLines.join('\n'))
  } catch {
    console.warn('streamInvestigate: ignoring unparseable SSE frame')
    return
  }
  if (event.type === 'stage') cb.onStage?.(event)
  else if (event.type === 'result') {
    if (settled) settled.done = true
    cb.onResult?.(event.result)
  } else if (event.type === 'error') {
    if (settled) settled.done = true
    cb.onError?.(event.message)
  }
}

/** Returns true when a `done` event was dispatched, so the caller can suppress
 *  trailing-frame handling. `tolerant` downgrades parse failures to warnings. */
function dispatchBlock(
  block: string,
  cb: StreamCallbacks,
  tolerant = false,
  settled?: { done: boolean },
): boolean {
  // A block can contain multiple `data:` lines; concatenate them per spec.
  const dataLines: string[] = []
  for (const line of block.split('\n')) {
    if (line.startsWith('data: ')) dataLines.push(line.slice(6))
    else if (line.startsWith('data:')) dataLines.push(line.slice(5))
  }
  if (dataLines.length === 0) return false
  const json = dataLines.join('\n')
  let event: StreamEvent
  try {
    event = JSON.parse(json) as StreamEvent
  } catch {
    if (tolerant) {
      console.warn(`streamGenerate: ignoring unparseable trailing SSE frame: ${json.slice(0, 120)}`)
    } else {
      if (settled) settled.done = true
      cb.onError?.(`unparseable SSE frame: ${json.slice(0, 120)}`)
    }
    return false
  }
  switch (event.type) {
    case 'meta':
      cb.onMeta?.(event)
      break
    case 'chunk':
      cb.onChunk?.(event)
      break
    case 'thinking':
      cb.onThinking?.(event)
      break
    case 'done':
      if (settled) settled.done = true
      cb.onDone?.(event)
      return true
    case 'error':
      if (settled) settled.done = true
      // 带码的错误和 REST 一样走翻译表：英文界面下拿英文，中文照用后端的 detail。
      cb.onError?.(
        event.code
          ? apiErrorMessage({ detail: event.message, code: event.code, params: event.params }, event.message)
          : event.message,
        event.code,
      )
      break
  }
  return false
}

// ─────────────── /api/suggest-angles（首页示例卡「让 AI 再想几个角度」）───────────────

export interface SuggestAnglesRequest {
  question: string
  indices?: string[]
  existing?: string[]
  lang?: string
}

/**
 * 一条一条回调，整个流结束（done / error / 断流）后 resolve；error 帧和 HTTP
 * 错误都变成 reject，调用方一处 catch。逐条出是因为本机这种慢模型一次要 60 秒，
 * 攒成一包等于让人盯着转圈一分钟。
 */
export async function streamSuggestAngles(
  req: SuggestAnglesRequest,
  onAngle: (text: string) => void,
  signal?: AbortSignal,
): Promise<void> {
  const r = await fetch('/api/suggest-angles', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(req),
    signal,
  })
  if (!r.ok) {
    let detail = `HTTP ${r.status}`
    let body: unknown
    try {
      body = await r.json()
      detail = apiErrorMessage(body, detail)
    } catch {
      // 非 JSON 错误体
    }
    if (emitLicenseBlocked(r.status, body, detail)) throw new Error('')
    throw new Error(detail)
  }
  if (!r.body) throw new Error('response has no body')

  const reader = r.body.getReader()
  const decoder = new TextDecoder('utf-8')
  let buffer = ''
  let settled = false
  const handle = (block: string) => {
    const data = block
      .split('\n')
      .filter((l) => l.startsWith('data:'))
      .map((l) => l.replace(/^data: ?/, ''))
      .join('\n')
    if (!data) return
    let evt: { type: string; text?: string; message?: string }
    try {
      evt = JSON.parse(data)
    } catch {
      return
    }
    if (evt.type === 'angle' && evt.text) onAngle(evt.text)
    else if (evt.type === 'done') settled = true
    else if (evt.type === 'error') {
      settled = true
      throw new Error(evt.message || 'error')
    }
  }
  while (true) {
    const { done, value } = await reader.read()
    if (done) break
    buffer += decoder.decode(value, { stream: true })
    if (buffer.includes('\r')) buffer = buffer.replace(/\r\n/g, '\n')
    let sep: number
    while ((sep = buffer.indexOf('\n\n')) >= 0) {
      const block = buffer.slice(0, sep)
      buffer = buffer.slice(sep + 2)
      handle(block)
    }
  }
  if (!settled) throw new Error(translate(libCopy, 'scBrokenInvestigate'))
}
