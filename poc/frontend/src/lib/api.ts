import { translate } from '@/lib/i18n'
import { libCopy } from '@/locales/lib'
import { apiErrorMessage } from '@/locales/errors'

/*
 * Typed API client for the RST Elastic AI Copilot gateway.
 * Paths are absolute — Vite dev server proxies /api/* to :8000;
 * in prod the gateway serves both /api and /v2 from the same origin.
 */

/** 界面选的时间范围（ISO）。两个都不给 = 全部时间 = 后端什么都不改。 */
export interface TimeWindowParams {
  since?: string
  until?: string
}

/** 后端实际套上去的时间窗，界面据此显示那枚 chip。 */
export interface AppliedTimeWindow {
  since?: string | null
  until?: string | null
  field?: string | null
  /**
   * 对原有时间条件做了什么：
   *   added        原来没有时间条件
   *   replaced     换掉了原来那个窗口
   *   intersected  原条件是个形状（「每天凌晨」这类多段 should），只能再 AND 一层
   *   question_wins 问题里明确说了时间 —— 它赢，筛选器同步成这一段
   */
  mode?: 'added' | 'replaced' | 'intersected' | 'question_wins'
  /** 问题里表示时间的原话（「23号」「昨天下午」），question_wins 时给出 */
  question_text?: string | null
  /** 这个索引没有时间字段，范围没生效 */
  unsupported?: boolean
}

export interface GenerateRequest extends TimeWindowParams {
  question: string
  index: string
  conversation_id?: string | null
  /** 用户的「深度思考」开关；不传 = 后端这一步的默认档。 */
  reasoning?: 'on' | 'off'
}

export interface GenerateResponse {
  dsl: Record<string, unknown> | null
  explanation: string
  confidence: 'low' | 'medium' | 'high'
  confidence_reason?: string | null
  prompt_version: string
  conversation_id?: string | null
  time_window?: AppliedTimeWindow | null
}

export interface PlatformCheck {
  id: string
  title: string
  verdict: 'ok' | 'warn' | 'fail' | 'unknown'
  summary: string
  detail: Record<string, unknown>
  advice: string
}

export interface PlatformReport {
  generated_at: string
  verdict: 'ok' | 'warn' | 'fail' | 'unknown'
  counts: Record<string, number>
  checks: PlatformCheck[]
}

export interface PlatformAction {
  title: string
  why: string
  how: string
}

export interface PlatformInterpretation {
  conclusion: string
  actions: PlatformAction[]
  degraded: boolean
  rag_chunks_used: number
}

export interface PlatformInterpretResponse {
  report: PlatformReport
  interpretation: PlatformInterpretation
}

export interface ExecuteRequest extends TimeWindowParams {
  index: string
  dsl: Record<string, unknown>
  /**
   * The natural-language question this DSL was generated from. Optional, and
   * sent only on an answer's FIRST execution: the backend records a
   * question -> DSL pair that returned hits as a worked example for later
   * questions. A re-run after a sort, a drill-down or a history replay is the
   * same question with a different DSL, so those leave it off.
   */
  question?: string
}

export interface ExecuteResponse {
  hits?: {
    total?: { value?: number; relation?: string } | number
    hits?: Array<{ _id?: string; _index?: string; _source?: Record<string, unknown> }>
  }
  aggregations?: Record<string, unknown>
  took?: number
  time_window?: AppliedTimeWindow
  [k: string]: unknown
}

export interface BaselineRunSummary {
  run_id: string
  trigger: string
  rule_count: number
  host_count: number
  pass: number
  fail: number
  error: number
  manual_review: number
  score: number
  started_at: string
  finished_at: string
}

/** Judge spec inside a baseline rule (nested). */
export interface BaselineJudge {
  operator: string
  field?: string
  expected?: string
  on_missing?: 'pass' | 'fail' | 'error'
}

/** Collector spec inside a baseline rule (nested). */
export interface BaselineCollect {
  query: string
  query_name?: string
}

/** Full baseline rule document — POST body and GET items share this shape. */
export interface BaselineRuleDoc {
  rule_id: string
  title: string
  category: string
  platform: string
  severity: 'low' | 'medium' | 'high' | 'critical'
  judge: BaselineJudge
  collect?: BaselineCollect
  standard_refs?: string[]
  remediation_template?: string
  depends_on?: string | null
  enabled?: boolean
  source?: string
}

export interface BaselineResult {
  run_id: string
  rule_id: string
  title: string
  category: string
  severity: string
  standard_refs?: string[]
  host: string
  verdict: 'pass' | 'fail' | 'error' | 'manual_review' | 'stale'
  actual: string
  expected: string
  remediation?: string
  checked_at: string
}

export interface InvestigateRequest {
  index: string
  alert: Record<string, unknown>
  window_minutes?: number
  reasoning?: 'on' | 'off'
}

export interface InvestigateResponse {
  summary: string
  alert_type: string
  severity: 'info' | 'low' | 'medium' | 'high' | 'critical'
  is_likely_false_positive: boolean
  false_positive_reason: string
  timeline: { time: string; event: string }[]
  attack_chain: { phase: string; evidence: string }[]
  mitre_techniques: { id: string; name: string; evidence: string }[]
  affected_assets: { type: string; id: string }[]
  recommended_actions: string[]
  confidence: 'low' | 'medium' | 'high'
  context_count: number
  rag_chunks_used?: number
  /** True when the LLM output couldn't be parsed and a safe placeholder was returned. */
  degraded?: boolean
  /** True when the agentic tool-use loop produced this result (RST_AGENTIC_INVESTIGATE). */
  agentic?: boolean
  /** Number of es_search rounds the agentic loop ran. */
  agentic_steps?: number
  /** Per-round agentic tool calls (index/query/hit-count/error) for transparency. */
  tool_trace?: { tool: string; args: string; hit_count: number; error?: string | null }[]
}

export interface AnalysisSubject {
  type: string
  value: string
}

export interface EnrichmentEntry {
  id: string
  name?: string
  criticality?: string
  category?: string
  owner?: string
  department?: string
  /** 资产：归一化后的主机键。 */
  keys?: string[]
  /** 资产：归一化后的 IP。 */
  ip?: string
  /** 身份：归一化后的用户名。 */
  user_key?: string
}

export interface EnrichmentSummary {
  counts: { assets: number; identities: number }
  coverage: {
    sampled: number
    with_subject: number
    matched: number
    /** null = 抽样里没有带主体的告警，说不上覆盖率（不是 0%）。 */
    ratio: number | null
  }
}

export type UserRole = 'admin' | 'analyst' | 'viewer'

export interface UserAccount {
  username: string
  role: UserRole
  disabled: boolean
}

/** 四个用户接口返回的都是这同一份全量快照 —— 改完不用再拉一次。 */
export interface UsersPayload {
  users: UserAccount[]
  roles: UserRole[]
  /** 独立用户表没配（没有 Postgres）时为 false：这时只有 .env 里那个 admin。 */
  multi_user: boolean
}

export interface AnalysisSummary {
  id: string
  kind: 'investigation' | 'triage' | 'result_explain'
  created_at: number
  title: string
  summary: string
  severity: 'info' | 'low' | 'medium' | 'high' | 'critical'
  subject: AnalysisSubject
}

export interface AnalysisRecord extends AnalysisSummary {
  owner: string | null
  masking_mode: string
  degraded: boolean
  payload: Record<string, unknown>
}

export interface ApiError extends Error {
  status: number
  body?: unknown
  /** Set when the license gate hard-failed the call; AppShell's banner explains it. */
  licenseBlocked?: boolean
}

// ── Admin token (X-RST-Admin-Token) ─────────────────────────────────────
/*
 * Admin operations (LLM provider save / settings save / LLM reload) require the
 * admin token unless SSO+RBAC grants the user admin server-side. It is sent only
 * on admin-flagged calls; the first one with no token (or a rejected one) opens a
 * prompt, and the answer is reused for the rest of the tab's life.
 *
 * 只驻内存，不进 localStorage。会话 cookie 是 HttpOnly，页面上的脚本读不到它；
 * 而 SSO 关闭时 `RST_ADMIN_TOKEN` 等价于 admin，把它放进 localStorage 等于给
 * 这个源上任何一段 JS（依赖、扩展、一次 XSS）留了一份可长期读取的管理员凭据，
 * 而 cookie 那一半明明已经防住了。
 *
 * 代价是刷新页面要重输一次。管理操作是「装完配一次、之后偶尔改一次」的频率，
 * 这个代价换掉的是一份能被读走的常驻凭据。
 */
const ADMIN_TOKEN_HEADER = 'X-RST-Admin-Token'

let adminTokenInMemory = ''

function getAdminToken(): string {
  return adminTokenInMemory
}
function setAdminToken(t: string): void {
  adminTokenInMemory = t
}
function clearAdminToken(): void {
  adminTokenInMemory = ''
}
type RequestOptions = RequestInit & { admin?: boolean }

/*
 * License hard-fail surfacing. The gateway 403s every non-allowlisted /api/*
 * when the license is invalid / expired / revoked / heartbeat-lost, returning
 * `{ detail, license_status }`. Without this the page just shows a generic
 * component error and the operator never learns it's a licensing problem.
 * We re-broadcast it so AppShell can render one banner in the content area —
 * i.e. at the feature the operator was actually trying to use.
 */
export const LICENSE_BLOCKED_EVENT = 'rst:license-blocked'

/*
 * 一次可能花掉试用额度的调用结束了 —— 侧栏那个额度条据此重新拉一次。
 *
 * 它以前只在挂载时拉一次：跑几条查询之后，界面上的「今日剩余」还停在进页面那一刻的
 * 数字，而这个数字存在的意义正是让人知道还剩多少。哪些路由真的扣额度由后端决定
 * （llm_cost 的登记表），前端按「往 /api/ 发的写请求」近似 —— 多拉几次的代价是一个
 * 极小的 GET，而且只有未激活模式下这个条才渲染。
 */
export const QUOTA_MAYBE_SPENT_EVENT = 'rst:quota-maybe-spent'

function noteQuotaMaybeSpent(path: string, method: string): void {
  if (typeof window === 'undefined') return
  if (method.toUpperCase() !== 'POST') return
  if (!path.startsWith('/api/') || path.startsWith('/api/license/') || path.startsWith('/api/state/')) return
  window.dispatchEvent(new CustomEvent(QUOTA_MAYBE_SPENT_EVENT))
}

const LICENSE_HARD_FAIL = new Set(['invalid', 'expired', 'revoked', 'heartbeat_lost'])

export interface LicenseBlockedDetail {
  status: string
  detail: string
}

/** Returns true when this response is a license hard-fail (and broadcasts it). */
export function emitLicenseBlocked(status: number, body: unknown, detail: string): boolean {
  if (status !== 403) return false
  if (typeof body !== 'object' || !body || !('license_status' in body)) return false
  const ls = String((body as { license_status: unknown }).license_status)
  if (!LICENSE_HARD_FAIL.has(ls)) return false
  if (typeof window !== 'undefined') {
    window.dispatchEvent(
      new CustomEvent<LicenseBlockedDetail>(LICENSE_BLOCKED_EVENT, {
        // 走文案表：这条横幅是整个产品被锁住时唯一的提示，英文界面上不该是中文。
        // 后端的 detail 仍然是兜底（老网关不带 code）。
        detail: { status: ls, detail: apiErrorMessage(body, detail) },
      }),
    )
  }
  return true
}

async function request<T>(path: string, init?: RequestOptions): Promise<T> {
  const wantAdmin = init?.admin === true

  const doFetch = (token: string) =>
    fetch(path, {
      ...init,
      headers: {
        'Content-Type': 'application/json',
        ...(token ? { [ADMIN_TOKEN_HEADER]: token } : {}),
        ...(init?.headers || {}),
      },
    })

  let r = await doFetch(wantAdmin ? getAdminToken() : '')

  // Admin retry: if server says we need an admin token, prompt + retry once.
  if (wantAdmin && r.status === 403) {
    const peek = await r
      .clone()
      .json()
      .catch(() => null as unknown as { detail?: string; code?: string } | null)
    // 认码不认字：以前匹配的是 detail 里有没有 "RST_ADMIN_TOKEN" 这几个字，
    // 后端换一版文案这条重试就悄悄失效了。code 是契约的一部分。
    const detail = typeof peek?.detail === 'string' ? peek.detail : ''
    if (peek?.code === 'admin_session_or_token_required' || detail.includes('RST_ADMIN_TOKEN')) {
      clearAdminToken() // any stored token was rejected
      const fresh =
        typeof window !== 'undefined'
          ? window.prompt(
              translate(libCopy, 'adminTokenPrompt'),
            )
          : null
      if (fresh && fresh.trim()) {
        setAdminToken(fresh.trim())
        r = await doFetch(fresh.trim())
      }
    }
  }

  if (!r.ok) {
    let body: unknown = undefined
    try {
      body = await r.json()
    } catch {
      try {
        body = await r.text()
      } catch {
        // ignore
      }
    }
    // Session expired mid-session. The middleware answers 401 {code:"login_required"}
    // (backend/auth.py). RequireAuth only re-probes /api/me on route change, so an
    // analyst sitting on one page would otherwise see every button fail with no way
    // back to the login form. Bounce to it, carrying nothing — a fresh login lands
    // on `/`. Skip when already on the login page (a failed login isn't this case).
    if (
      r.status === 401 &&
      typeof body === 'object' && body && 'code' in body &&
      (body as { code?: unknown }).code === 'login_required' &&
      typeof window !== 'undefined' &&
      !window.location.pathname.endsWith('/login')
    ) {
      window.location.assign('/v2/login')
    }
    // 英文界面下按 code 取英文文案；中文（和没带码的老错误）用后端的 detail 原文。
    const detail = apiErrorMessage(
      body,
      typeof body === 'string' && body ? body : `HTTP ${r.status}`,
    )
    // The license banner owns this message. Blank it so each page falls back to
    // its own short failure copy instead of echoing the same licence essay
    // inline — one explanation per screen, not two.
    const licenseBlocked = emitLicenseBlocked(r.status, body, detail)
    const err = new Error(licenseBlocked ? '' : detail) as ApiError
    err.status = r.status
    err.body = body
    if (licenseBlocked) err.licenseBlocked = true
    // 402（额度用完）也走这里 —— 那正是最该让侧栏立刻更新的一刻。
    noteQuotaMaybeSpent(path, init?.method ?? 'GET')
    throw err
  }
  noteQuotaMaybeSpent(path, init?.method ?? 'GET')
  return (await r.json()) as T
}

// ---- Notify / real-time alert types ----
export type NotifyChannel = 'feishu' | 'dingtalk' | 'wecom' | 'teams' | 'slack' | 'email'

export interface NotifyTarget {
  id: string
  /** 老目标没有这个字段，后端读的时候按 feishu 兜底。 */
  channel: NotifyChannel
  name: string
  /* webhook URL 不出接口：企业微信 / Slack / Teams 的鉴权就是 URL 里那个 key，
     它和签名密钥是同一档东西。界面要的只是「这条发去哪个平台」和「设没设」。 */
  /** channel≠email 才有：webhook 的主机名，仅供辨认。 */
  webhook_host?: string
  /** channel≠email 才有：这条目标存没存过 webhook URL。 */
  webhook_set?: boolean
  /** channel=email 才有 */
  recipients?: string[]
  periods: string[]
  alert_severity_threshold: string
  enabled: boolean
  secret_set: boolean
  /** 密文在、这台网关解不开（重装 / 换了 state 卷）：要重填。 */
  secret_stale?: boolean
  created_at?: string
  updated_at?: string
}

export interface NotifyTargetInput {
  id?: string
  channel: NotifyChannel
  name: string
  webhook_url?: string
  recipients?: string[]
  secret?: string
  clear_secret?: boolean
  periods: string[]
  alert_severity_threshold: string
  enabled: boolean
}

export interface NotifySmtp {
  host?: string
  port?: number
  security?: 'none' | 'starttls' | 'ssl'
  username?: string
  from_addr?: string
  from_name?: string
  /** 密码从不回传，只回传「设没设过」。 */
  password_set?: boolean
  password_stale?: boolean
}

export interface NotifySmtpInput {
  host: string
  port: number
  security: 'none' | 'starttls' | 'ssl'
  username?: string
  password?: string
  clear_password?: boolean
  from_addr: string
  from_name?: string
}

export interface NotifyConfig {
  schedule: { periods: string[]; hour: number; tz: string }
  alert_severity_threshold: string
  targets: NotifyTarget[]
  /** SMTP 是全局一份，不跟着目标走 —— 改邮箱密码不该改 N 个目标。 */
  smtp?: NotifySmtp
}

export interface NotifyDelivery {
  /** ES 文档 id —— 重投按它定位。 */
  id: string
  /** 生产者，不是渠道。 */
  kind: 'report' | 'alert'
  channel?: NotifyChannel
  ref: string
  target_id: string
  target_name?: string
  status: 'queued' | 'sending' | 'sent' | 'failed' | 'dead'
  attempts: number
  last_error?: string
  updated_at?: string
  sent_at?: string
}

export interface RealtimeAlert {
  alert_id: string
  rule_id: string
  rule_name: string
  severity: string
  '@timestamp': string
  subject_field?: string | null
  subject_value?: string | null
  origin: string
  summary?: string
  /** 因为超出摘要预算而没生成摘要 —— 和「关掉了」「生成失败」要能分开。 */
  summary_skipped?: boolean
  source_index?: string
  source_id?: string
  ingested_at?: string
}

export interface AlertDetail extends RealtimeAlert {
  raw?: Record<string, unknown>
}

export interface AlertKibanaLink {
  discover_url: string | null
  discover_error: string | null
  /**
   * 请求带的 Origin 不是这个网关认识的地址，深链于是落在内部主机名上（KIBANA_URL），
   * 浏览器多半打不开。链接照给，界面上要说得出原因。老网关不回这个字段。
   */
  origin_ignored?: boolean
  security_url: string
  source_index: string
  source_id: string
}

export interface AlertIngestStatus {
  index: string
  interval: number
  enabled: boolean
  whitelisted: boolean
  webhook_enabled: boolean
  cursor_ts: string | null
  /** 最近一小时因为超出摘要预算而没生成摘要的条数（老网关不回，按 0 处理）。 */
  summary_skipped_recent?: number
  summary_budget_s?: number
  summary_concurrency?: number
}

export interface AssetContext {
  business_name?: string | null
  criticality?: string | null
  category?: string | null
  owner?: string | null
  department?: string | null
  source: string
  confidence: string
  candidates: number
}

export const api = {
  health: () => request<{ status: string }>('/healthz'),

  /* ES 就绪与否。`/readyz` 免鉴权、免 license 闸，所以新装一台还没配连接的机器
     也答得出来 —— 那正是要用它的时候。ES 不通时后端返回 503，这里收成
     `ready: false` 而不是抛，调用方要的是一个状态不是一次失败。 */
  ready: async (): Promise<{ ready: boolean; configured: boolean }> => {
    try {
      const r = await request<{ status: string; es_configured?: boolean }>('/readyz')
      return { ready: true, configured: r.es_configured !== false }
    } catch (e) {
      /* 503 的 detail 里带着 es_configured —— 「从没配过」和「配过但现在不通」
         对界面是两回事：前者弹配置框，后者只挂一条横幅。拿不到就按「配过」算，
         宁可少弹一个框，也不要对着一台正常机器弹安装向导。 */
      const body = (e as ApiError | null)?.body as
        | { detail?: { es_configured?: boolean } }
        | undefined
      return { ready: false, configured: body?.detail?.es_configured !== false }
    }
  },

  /* 改自己的密码。后端要验当前密码，新密码至少 8 位，改完会踢掉这个账号的
     其他会话（改密码就是因为怀疑别人拿到了它），当前这一个换发新 cookie。 */
  changePassword: (body: { current_password: string; new_password: string }) =>
    request<{ ok: boolean }>('/api/auth/password', {
      method: 'POST',
      body: JSON.stringify(body),
    }),

  // SSO identity — who is logged in (from the forward-auth proxy) and whether
  // SSO is enabled for this deployment.
  me: () =>
    request<{
      authenticated: boolean
      user: { username?: string; roles?: string[]; source?: string } | null
      sso_enabled: boolean
      is_admin: boolean
      logout_url: string
    }>('/api/me'),

  licenseStatus: () =>
    request<{ status: string; features?: string[]; license_type?: string }>(
      '/api/license/status'
    ),

  generate: (req: GenerateRequest) =>
    request<GenerateResponse>('/api/generate', {
      method: 'POST',
      body: JSON.stringify(req),
    }),

  platformCheckup: () => request<PlatformReport>('/api/platform/checkup'),

  platformInterpret: () =>
    request<PlatformInterpretResponse>('/api/platform/interpret', { method: 'POST' }),

  execute: (req: ExecuteRequest, signal?: AbortSignal) =>
    request<ExecuteResponse>('/api/execute', {
      method: 'POST',
      body: JSON.stringify(req),
      signal,
    }),

  // ── 安全基线巡检 ──
  baselineRun: (hosts?: string[] | null) =>
    request<BaselineRunSummary>('/api/baseline/run', {
      method: 'POST',
      body: JSON.stringify({ hosts: hosts ?? null }),
    }),

  baselineResults: (params?: { run_id?: string; host?: string; verdict?: string; size?: number }) => {
    const q = new URLSearchParams()
    if (params?.run_id) q.set('run_id', params.run_id)
    if (params?.host) q.set('host', params.host)
    if (params?.verdict) q.set('verdict', params.verdict)
    if (params?.size) q.set('size', String(params.size))
    const qs = q.toString()
    return request<{ count: number; results: BaselineResult[] }>(
      `/api/baseline/results${qs ? `?${qs}` : ''}`,
    )
  },

  baselineSummary: () => request<{ run: BaselineRunSummary | null }>('/api/baseline/summary'),

  baselineHosts: () => request<{ count: number; hosts: string[] }>('/api/baseline/hosts'),

  baselineFieldMap: () =>
    request<{ host_field: string; query_field: string; col_prefix: string; source: string; confident: boolean }>(
      '/api/baseline/field-map',
    ),

  // Rule library — list / create-or-update / delete
  baselineRules: (platform?: string) => {
    const qs = platform ? `?platform=${encodeURIComponent(platform)}` : ''
    return request<{ count: number; rules: BaselineRuleDoc[] }>(`/api/baseline/rules${qs}`)
  },

  baselineRuns: (size?: number) => {
    const qs = size ? `?size=${size}` : ''
    return request<{ count: number; runs: BaselineRunSummary[] }>(`/api/baseline/runs${qs}`)
  },

  baselineUpsertRule: (rule: BaselineRuleDoc) =>
    request<{ ok: boolean; rule_id: string }>('/api/baseline/rules', {
      method: 'POST',
      body: JSON.stringify(rule),
    }),

  baselineDeleteRule: (ruleId: string) =>
    request<{ ok: boolean; rule_id: string }>(
      `/api/baseline/rules/${encodeURIComponent(ruleId)}`,
      { method: 'DELETE' },
    ),

  investigate: (req: InvestigateRequest, signal?: AbortSignal) =>
    request<InvestigateResponse>('/api/investigate-alert', {
      method: 'POST',
      body: JSON.stringify(req),
      signal,
    }),

  // Push an investigation conclusion to configured Feishu targets. `dispatched`
  // = targets reached (0 = none configured / none meet the severity threshold).
  investigateNotify: (investigation: Record<string, unknown>) =>
    request<{ dispatched: number }>('/api/investigate-alert/notify', {
      method: 'POST',
      body: JSON.stringify({ investigation }),
    }),

  // Notify on-call that a triage cluster was escalated (升级). `dispatched` =
  // Feishu targets reached (0 = none configured / none meet the severity threshold).
  triageEscalate: (cluster: Record<string, unknown>) =>
    request<{ dispatched: number }>('/api/triage/escalate', {
      method: 'POST',
      body: JSON.stringify({ cluster }),
    }),

  explainLog: (req: { index?: string; doc: Record<string, unknown> }, signal?: AbortSignal) =>
    request<Record<string, unknown>>('/api/explain-log', {
      method: 'POST',
      body: JSON.stringify(req),
      signal,
    }),

  // Interpret a whole result set (aggregations + a few sample hits) rather than
  // one document — the way out of a bare `size:0` aggregation table. Returns the
  // same shape as explainLog, so one dialog renders both.
  explainResult: (
    req: {
      index?: string
      question?: string
      dsl: Record<string, unknown>
      aggregations?: Record<string, unknown> | null
      sample_hits?: Record<string, unknown>[]
      total?: number | null
    },
    signal?: AbortSignal,
  ) =>
    request<Record<string, unknown>>('/api/explain-result', {
      method: 'POST',
      body: JSON.stringify(req),
      signal,
    }),

  // v1.0.3 — incident report
  reportIncident: (req: {
    index: string
    alert?: Record<string, unknown>
    alert_id?: string
    investigation?: Record<string, unknown>
    window_minutes?: number
    include_evidence?: boolean
    evidence_limit?: number
  }) =>
    request<{
      title: string
      generated_at: string
      markdown: string
      exec_summary: string
      investigation: Record<string, unknown>
      evidence_count: number
      metadata: Record<string, unknown>
      rag_chunks_used?: number
    }>('/api/report/incident', {
      method: 'POST',
      body: JSON.stringify(req),
    }),

  // Forward an investigation report to Feishu (cloud doc + group card).
  reportToFeishu: (req: { title: string; markdown: string; severity?: string; to_doc?: boolean; to_group?: boolean }) =>
    request<{ doc_url: string | null; dispatched: number; errors: string[] }>('/api/report/to-feishu', {
      method: 'POST',
      body: JSON.stringify(req),
    }),

  // v1.0.4 — detection rule
  detectionRule: (req: {
    index: string
    question: string
    rule_type_hint?: string
    reasoning?: 'on' | 'off'
  }) =>
    request<{
      rule: Record<string, unknown> | null
      explanation: string
      confidence: string
      confidence_reason?: string
      rule_type: string | null
      rag_chunks_used?: number
    }>('/api/detection-rule/generate', {
      method: 'POST',
      body: JSON.stringify(req),
    }),

  // Kibana Discover deep link
  kibanaLink: (req: { index: string; dsl: Record<string, unknown> }) =>
    request<{ url: string; data_view_id?: string | null }>('/api/kibana-link', {
      method: 'POST',
      body: JSON.stringify(req),
    }),

  // Feedback (👍 / 👎 / corrected DSL)
  feedback: (req: {
    question: string
    index: string
    dsl?: Record<string, unknown> | null
    correct: boolean
    comment?: string | null
    suggested_dsl?: Record<string, unknown> | null
    prompt_version?: string | null
    dsl_was_edited?: boolean | null
  }) =>
    request<{ status: string }>('/api/feedback', {
      method: 'POST',
      body: JSON.stringify(req),
    }),

  // Conversation history (multi-turn)
  conversation: (id: string) =>
    request<{
      id: string
      created_at: string
      updated_at: string
      turns: Array<{
        turn_id?: string
        question: string
        dsl?: Record<string, unknown> | null
        explanation?: string
        /** pending | done | failed | aborted；老记录没有，按 done。 */
        status?: 'pending' | 'done' | 'failed' | 'aborted'
        error?: { code?: string; message?: string } | null
      }>
    }>(`/api/conversations/${encodeURIComponent(id)}`),

  conversationDelete: (id: string) =>
    request<{ ok: boolean }>(`/api/conversations/${encodeURIComponent(id)}`, {
      method: 'DELETE',
    }),

  // Field masking mode info
  maskingInfo: () =>
    request<{
      current_mode: string
      available_modes: string[]
    }>('/api/masking/info'),

  // LLM router status / reload / save
  llmProviders: () =>
    request<{
      strategy?: string
      providers: Array<{
        id: string
        model: string
        kind?: string
        api_version?: string
        base_url: string
        enabled: boolean
        tags: string[]
        api_key_last4?: string
        timeout_s?: number
        /** auto | off | low | high — 推理强度覆盖（backend/llm_reasoning.py）。 */
        reasoning?: string
        consec_failures?: number
        /** epoch 秒（后端 time.time()），不是 ISO 串；用 toMs() 归一。 */
        last_ok_at?: number | string | null
        last_fail_at?: number | string | null
        last_error?: string | null
      }>
    }>('/api/llm/providers'),

  llmReload: () =>
    request<{
      providers: Array<{ id: string; model: string; base_url: string; enabled: boolean }>
    }>('/api/llm/reload', { method: 'POST', admin: true }),

  llmProvidersSave: (req: {
    providers: Array<{
      id: string
      kind?: string
      api_version?: string
      base_url: string
      api_key: string  // empty = keep existing
      model: string
      enabled: boolean
      tags: string[]
      timeout_s: number
      reasoning?: string
    }>
  }) =>
    request<{
      providers: Array<{
        id: string
        model: string
        base_url: string
        enabled: boolean
        api_key_last4?: string
      }>
    }>('/api/llm/providers/save', {
      method: 'POST',
      body: JSON.stringify(req),
      admin: true,
    }),

  // Embedding (RAG vector model) GUI config
  embeddingConfig: () =>
    request<{
      model: string
      base_url: string
      api_key_set: boolean
      api_key_last4: string
      dims: number
      enabled: boolean
      status: 'enabled' | 'disabled' | 'misconfigured'
      kb_index_dims: number | null
    }>('/api/embedding/config'),

  embeddingTest: (body: { model: string; base_url: string; api_key: string; dims?: number }) =>
    request<{ ok: boolean; dims?: number; error?: string }>('/api/embedding/test', {
      method: 'POST',
      body: JSON.stringify(body),
      admin: true,
    }),

  embeddingSave: (body: {
    model: string
    base_url: string
    api_key: string
    dims: number
    enabled: boolean
  }) =>
    request<{ ok: boolean; dims: number; status: string }>('/api/embedding/save', {
      method: 'POST',
      body: JSON.stringify(body),
      admin: true,
    }),

  // Audit log viewer (Round 6)
  auditEvents: (params?: {
    from_ts?: string
    to_ts?: string
    action?: string
    user?: string
    target_index?: string
    outcome?: string
    size?: number
    offset?: number
  }) => {
    const qs = new URLSearchParams()
    if (params) {
      for (const [k, v] of Object.entries(params)) {
        if (v !== undefined && v !== null && v !== '') qs.set(k, String(v))
      }
    }
    const suffix = qs.toString() ? `?${qs}` : ''
    return request<{
      total: number
      audit_index: string
      audit_enabled?: boolean
      /** Aggregations over the whole filtered window, not the page of events. */
      summary?: {
        over_time: Array<{ ts: string; count: number; failed: number }>
        by_action: Array<{ key: string; count: number }>
        by_outcome: Array<{ key: string; count: number }>
        by_user: Array<{ key: string; count: number }>
        /** Null when nothing in the window carried a duration. */
        duration_p50_ms: number | null
        duration_p95_ms: number | null
      }
      events: Array<{
        '@timestamp'?: string
        action?: string
        user?: { username?: string; roles?: string[] } | null
        index?: string
        license_status?: string
        prompt_version?: string | null
        duration_ms?: number
        outcome?: string
        error?: string
        extra?: Record<string, unknown>
      }>
    }>(`/api/audit/events${suffix}`, { admin: true })
  },

  // Server-side conversations list (Round 6)
  conversationsList: (params?: { limit?: number; offset?: number }) => {
    const qs = new URLSearchParams()
    if (params?.limit) qs.set('limit', String(params.limit))
    if (params?.offset) qs.set('offset', String(params.offset))
    const suffix = qs.toString() ? `?${qs}` : ''
    return request<{
      total: number
      conversations: Array<{
        id: string
        created_at: number
        last_at: number
        turn_count: number
        first_question: string | null
        /** 最后一轮的状态；列表上据此给个「上次失败 / 已中断」的角标。 */
        last_status?: 'pending' | 'done' | 'failed' | 'aborted' | null
      }>
    }>(`/api/conversations${suffix}`)
  },

  // Analysis archive (investigation + triage results)
  analysisList: (params?: {
    kind?: string
    limit?: number
    before?: number
    q?: string
    since?: number
  }) => {
    const qs = new URLSearchParams()
    if (params?.kind) qs.set('kind', params.kind)
    if (params?.limit) qs.set('limit', String(params.limit))
    if (params?.before) qs.set('before', String(params.before))
    if (params?.q) qs.set('q', params.q)
    if (params?.since) qs.set('since', String(params.since))
    const suffix = qs.toString() ? `?${qs}` : ''
    return request<{ total: number; records: AnalysisSummary[] }>(
      `/api/analysis${suffix}`,
    )
  },

  analysisDetail: (id: string) =>
    request<AnalysisRecord>(`/api/analysis/${encodeURIComponent(id)}`),

  // 资产 / 身份表的只读一面
  enrichmentSummary: () => request<EnrichmentSummary>('/api/admin/enrichment/summary'),

  enrichmentEntries: (params: {
    kind: 'assets' | 'identities'
    q?: string
    limit?: number
    after?: number
  }) => {
    const qs = new URLSearchParams({ kind: params.kind })
    if (params.q) qs.set('q', params.q)
    if (params.limit) qs.set('limit', String(params.limit))
    if (params.after) qs.set('after', String(params.after))
    return request<{ total: number; rows: EnrichmentEntry[]; next: number | null }>(
      `/api/admin/enrichment/entries?${qs}`,
    )
  },

  // 用户与角色（后端 Phase 03 就有了，界面一直没接）
  usersList: () => request<UsersPayload>('/api/users'),

  userCreate: (body: { username: string; password: string; role: UserRole }) =>
    request<UsersPayload>('/api/users', { method: 'POST', body: JSON.stringify(body) }),

  /** 只发要改的字段：后端按「给了才改」处理。 */
  userUpdate: (
    username: string,
    body: { password?: string; role?: UserRole; disabled?: boolean },
  ) =>
    request<UsersPayload>(`/api/users/${encodeURIComponent(username)}`, {
      method: 'PATCH',
      body: JSON.stringify(body),
    }),

  userDelete: (username: string) =>
    request<UsersPayload>(`/api/users/${encodeURIComponent(username)}`, {
      method: 'DELETE',
    }),

  // Failed cases / negative feedback (Round 6)
  failedCases: (params?: { limit?: number; offset?: number }) => {
    const qs = new URLSearchParams()
    if (params?.limit) qs.set('limit', String(params.limit))
    if (params?.offset) qs.set('offset', String(params.offset))
    const suffix = qs.toString() ? `?${qs}` : ''
    return request<{
      total: number
      cases: Array<{
        timestamp?: string
        question?: string
        index?: string
        dsl?: Record<string, unknown> | null
        correct?: boolean
        comment?: string | null
        suggested_dsl?: Record<string, unknown> | null
        prompt_version?: string | null
        dsl_was_edited?: boolean | null
      }>
    }>(`/api/feedback/failed-cases${suffix}`, { admin: true })
  },

  failedCaseDelete: (idx: number) =>
    request<{ ok: boolean; remaining: number }>(`/api/feedback/failed-cases/${idx}`, {
      method: 'DELETE',
      admin: true,
    }),

  // Fetch ALL failed cases by paging through the offset endpoint (the per-call
  // limit only returns one page). Bounded by `max` so a huge eval set can't
  // OOM the browser; the caller surfaces the cap to the user.
  failedCasesAll: async (opts?: { pageSize?: number; max?: number }) => {
    const pageSize = opts?.pageSize ?? 200
    const max = opts?.max ?? 5000
    const first = await api.failedCases({ limit: pageSize, offset: 0 })
    const total = first.total
    const cases = [...first.cases]
    let offset = pageSize
    while (cases.length < total && cases.length < max && offset < total) {
      const r = await api.failedCases({ limit: pageSize, offset })
      cases.push(...r.cases)
      if (r.cases.length < pageSize) break
      offset += pageSize
    }
    // Compute `capped` against what we actually return (post-slice): the paging
    // loop can overshoot `max` by up to a page, so comparing `total` to the
    // un-sliced length could report capped:false while silently dropping rows.
    const returned = cases.slice(0, max)
    return { total, cases: returned, capped: total > returned.length }
  },

  // Dashboards (Round 6)
  dashboardsList: () =>
    request<{
      panels: Array<{
        id: string
        title: string
        description?: string
        index: string
        type: 'count' | 'agg-bar' | 'table'
        dsl: Record<string, unknown>
        auto_refresh_seconds: number
        agg_path?: string
      }>
    }>('/api/dashboards'),

  dashboardsSave: (panels: Array<{
    id: string
    title: string
    description?: string
    index: string
    type: 'count' | 'agg-bar' | 'table'
    dsl: Record<string, unknown>
    auto_refresh_seconds?: number
    agg_path?: string
  }>) =>
    request<{ panels: Array<unknown> }>('/api/dashboards', {
      method: 'POST',
      body: JSON.stringify({ panels }),
      admin: true,
    }),

  // Reports (Round 6)
  /* `range` 给了就按自定义区间取窗口，period 退化成只决定分桶粒度。 */
  reportGenerate: (
    period: 'daily' | 'weekly' | 'monthly',
    range?: { since?: string; until?: string },
  ) =>
    request<{
      period: string
      label: string
      generated_at: string
      start_at: string
      end_at: string
      markdown: string
      summary: {
        total: number
        success: number
        fail: number
        success_rate: number
        unique_users: number
        unique_indexes: number
        avg_duration_ms: number | null
        by_action: Array<{ action: string; count: number; success: number; fail: number }>
        top_indexes: Array<{ index: string; count: number }>
        top_users: Array<{ user: string; count: number }>
      }
      license_status?: string
    }>('/api/reports/generate', {
      method: 'POST',
      body: JSON.stringify({
        period,
        ...(range?.since ? { start: range.since, end: range.until } : {}),
      }),
    }),

  // Automated patrol report archive (Wave / 巡检)
  reportsHistory: (params?: { period?: string; limit?: number }) => {
    const qs = new URLSearchParams()
    if (params?.period) qs.set('period', params.period)
    if (params?.limit) qs.set('limit', String(params.limit))
    const suffix = qs.toString() ? `?${qs}` : ''
    return request<{
      reports: Array<{
        period: string
        boundary_key: string
        generated_at: string
        start_at: string
        end_at: string
        license_status?: string | null
        summary?: { total?: number; success_rate?: number } & Record<string, unknown>
        health?: {
          es_reachable?: boolean
          es_write?: string
          license_status?: string
          audit_enabled?: boolean
          sso?: string
          providers?: Array<{ id: string; enabled: boolean; total_failures?: number }>
        } | null
        security_triage?: {
          index?: string
          window_minutes?: number
          total_alerts?: number
          total_clusters?: number
          scored_clusters?: number
          severity_counts?: Record<string, number>
          likely_fp?: number
        } | null
        markdown?: string
      }>
    }>(`/api/reports/history${suffix}`)
  },

  // ---- Notify: Feishu report/alert forwarding config + delivery status ----
  notifyConfig: () =>
    request<NotifyConfig>('/api/notify/config'),

  notifySaveSchedule: (schedule: {
    periods: string[]
    hour: number
    tz?: string
    alert_severity_threshold?: string
  }) =>
    request<NotifyConfig>('/api/notify/schedule', {
      method: 'PUT',
      body: JSON.stringify(schedule),
      admin: true,
    }),

  notifyUpsertTarget: (target: NotifyTargetInput) =>
    request<NotifyConfig>('/api/notify/targets', {
      method: 'POST',
      body: JSON.stringify(target),
      admin: true,
    }),

  notifyDeleteTarget: (id: string) =>
    request<NotifyConfig>(`/api/notify/targets/${encodeURIComponent(id)}`, {
      method: 'DELETE',
      admin: true,
    }),

  notifyTestTarget: (id: string) =>
    request<{ ok: boolean; error?: string }>(
      `/api/notify/targets/${encodeURIComponent(id)}/test`,
      { method: 'POST', admin: true },
    ),

  notifySaveSmtp: (smtp: NotifySmtpInput) =>
    request<NotifyConfig>('/api/notify/smtp', {
      method: 'PUT',
      body: JSON.stringify(smtp),
      admin: true,
    }),

  /* 重投一条投递。死信是它存在的理由 —— webhook 被撤销、SMTP 密码改了，修好
     之后那几条报告不该只能靠客户自己补。 */
  notifyRetryDelivery: (id: string) =>
    request<{ ok: boolean }>(
      `/api/notify/deliveries/${encodeURIComponent(id)}/retry`,
      { method: 'POST', admin: true },
    ),

  notifyDeliveries: (params?: { kind?: string; status?: string; limit?: number }) => {
    const qs = new URLSearchParams()
    if (params?.kind) qs.set('kind', params.kind)
    if (params?.status) qs.set('status', params.status)
    if (params?.limit) qs.set('limit', String(params.limit))
    const suffix = qs.toString() ? `?${qs}` : ''
    return request<{ deliveries: NotifyDelivery[] }>(`/api/notify/deliveries${suffix}`)
  },

  // ---- Real-time alerts ----
  // `before` = strict upper-bound @timestamp cursor for infinite scroll; `rule`
  // = phrase-prefix on rule_name/rule_id; `since`/`until` = @timestamp range.
  alertsList: (params?: {
    limit?: number
    severity?: string
    before?: string
    rule?: string
    since?: string
    until?: string
  }) => {
    const qs = new URLSearchParams()
    if (params?.limit) qs.set('limit', String(params.limit))
    if (params?.severity) qs.set('severity', params.severity)
    if (params?.before) qs.set('before', params.before)
    if (params?.rule) qs.set('rule', params.rule)
    if (params?.since) qs.set('since', params.since)
    if (params?.until) qs.set('until', params.until)
    const suffix = qs.toString() ? `?${qs}` : ''
    return request<{ alerts: RealtimeAlert[] }>(`/api/alerts${suffix}`)
  },

  alertDetail: (id: string) =>
    request<AlertDetail>(`/api/alerts/${encodeURIComponent(id)}`),

  alertKibanaLink: (id: string) =>
    request<AlertKibanaLink>(`/api/alerts/${encodeURIComponent(id)}/kibana-link`),

  alertEnrichment: (id: string) =>
    request<{ enrichment: AssetContext | null }>(
      `/api/alerts/${encodeURIComponent(id)}/enrichment`
    ),

  enrichmentUploadAssets: (csv: string) =>
    request<{ indexed: number; index: string }>('/api/admin/enrichment/assets', {
      method: 'POST',
      body: JSON.stringify({ csv }),
      admin: true,
    }),

  enrichmentUploadIdentities: (csv: string) =>
    request<{ indexed: number; index: string }>('/api/admin/enrichment/identities', {
      method: 'POST',
      body: JSON.stringify({ csv }),
      admin: true,
    }),

  enrichmentStatus: () =>
    request<{ sources: Record<string, boolean> }>('/api/admin/enrichment/status', {
      admin: true,
    }),

  /** Overview counts for the alert feed. Severity is deliberately not a
      parameter — the severity mix is what this draws. */
  alertsStats: (params?: { rule?: string; since?: string; until?: string }) => {
    const qs = new URLSearchParams()
    for (const [k, v] of Object.entries(params ?? {})) if (v) qs.set(k, v)
    const suffix = qs.toString() ? `?${qs}` : ''
    return request<{
      total: number
      by_severity: Array<{ key: string; count: number }>
      by_rule: Array<{ key: string; count: number }>
      over_time: Array<{ ts: string; count: number }>
    }>(`/api/alerts/stats${suffix}`)
  },

  alertIngestStatus: () =>
    request<AlertIngestStatus>('/api/alerts/ingest/status'),

  // Trial daily quota (Round 5)
  licenseQuota: () =>
    request<{
      used: number
      limit: number
      remaining: number
      /** UTC 挂钟上的换日时刻，跟着部署时区走（+08:00 的部署是 16:00）。 */
      reset_at_utc: string
      /** 部署所在时区的换日时刻，恒为 00:00 —— 界面说的就是这个。 */
      reset_at_local?: string
      timezone?: string
      active: boolean
    }>('/api/license/quota'),

  // Online image update — container downloads + verifies + stages a newer
  // release; the actual docker load / retag / health-gate / rollback is the
  // host-side rst-update.sh (containers can't run docker). Both admin-gated.
  releaseStatus: () =>
    request<{
      running_version: string
      updater_version: number
      staged_version: string | null
      artifacts: Array<{ kind?: string; sha256?: string; size?: number }>
      staged_at: string | null
      min_updater_version?: number
      // What the license server last offered via heartbeat (null = no update).
      available: { version: string; manifest_url?: string; artifacts?: unknown[] } | null
      /** false = 一次心跳都没成功，还没问过更新源，「已是最新」无从谈起。 */
      checked?: boolean
    }>('/api/admin/release/status', { admin: true }),

  releaseDownload: () =>
    request<{
      running_version: string
      updater_version: number
      staged_version: string | null
      artifacts: Array<{ kind?: string; sha256?: string; size?: number }>
      staged_at: string | null
    }>('/api/admin/release/download', { method: 'POST', admin: true }),

  // Gateway settings — flat keys + sensitive sentinel pattern (Round 5)
  getSettings: () =>
    request<{ settings: Record<string, string> }>('/api/settings'),

  saveSettings: (req: Record<string, string | boolean>) =>
    request<{ settings: Record<string, string> }>('/api/settings', {
      method: 'POST',
      body: JSON.stringify(req),
      admin: true,
    }),

  /* Dial a candidate ES cluster without saving it. Sending `{}` re-tests
     whatever is configured now, which is how the settings page shows its
     status line on load. Never throws on a bad cluster — an unreachable host
     is an expected answer here, so it comes back as `ok: false` + a message
     to render, not an exception to catch. */
  testEsConnection: (req: {
    url?: string
    user?: string
    password?: string
    verify_certs?: boolean
    ca_cert?: string
  }) =>
    request<{
      ok: boolean
      cluster_name?: string
      version?: string
      can_list_indices?: boolean
      error?: string
    }>('/api/settings/es/test', {
      method: 'POST',
      body: JSON.stringify(req),
    }),

  // ES indices listing (resolve data streams + aliases + indices)
  indices: (params?: { pattern?: string; include_system?: boolean }) => {
    const qs = new URLSearchParams()
    if (params?.pattern) qs.set('pattern', params.pattern)
    if (params?.include_system) qs.set('include_system', 'true')
    const suffix = qs.toString() ? `?${qs}` : ''
    return request<{
      total: number
      indices: Array<{
        name: string
        kind: 'index' | 'alias' | 'data_stream'
        attributes: string[]
        health: string
        status: string
        doc_count: number
        store_size: string
        backing_indices: string[]
      }>
    }>(`/api/indices${suffix}`)
  },

  // Field dictionary
  fieldDict: (req: { index: string }) =>
    request<{
      index: string
      doc_count: number
      total_fields_in_mapping: number
      truncated: boolean
      fields: Array<{
        name: string
        type: string
        cardinality_approx: number | null
        samples: Array<{ value: unknown; count: number }>
      }>
    }>('/api/field-dict', {
      method: 'POST',
      body: JSON.stringify(req),
    }),

  // RAG knowledge base (v1.0.2)
  kbUpload: (req: { title: string; content: string; metadata?: Record<string, unknown> }) =>
    request<{ doc_id: string; chunk_count: number; total_chars: number }>(
      '/api/kb/upload',
      { method: 'POST', body: JSON.stringify(req) },
    ),

  kbDocuments: () =>
    request<
      Array<{
        doc_id: string | null
        title: string | null
        chunk_count: number
        first_indexed_at: string | null
        metadata: Record<string, unknown>
      }>
    >('/api/kb/documents'),

  kbSearch: (req: { query: string; top_k?: number; doc_ids?: string[] }) =>
    request<
      Array<{
        doc_id: string | null
        chunk_id: string | null
        title: string | null
        content: string | null
        score: number | null
      }>
    >('/api/kb/search', { method: 'POST', body: JSON.stringify(req) }),

  kbDelete: (docId: string) =>
    request<{ deleted: number }>(`/api/kb/${encodeURIComponent(docId)}`, {
      method: 'DELETE',
    }),

  // Per-owner server state (Wave 2) — durable cross-device / team-shared store.
  // Falls back to localStorage in callers when these fail (no ES write / no SSO).
  stateList: <T = unknown>(kind: string) =>
    request<{
      items: Array<{ key: string; value: T; updated_at: string | null; updated_by: string | null }>
    }>(`/api/state/${encodeURIComponent(kind)}`),

  stateGet: <T = unknown>(kind: string, key: string) =>
    request<{ key: string; value: T | null }>(
      `/api/state/${encodeURIComponent(kind)}/${encodeURIComponent(key)}`,
    ),

  statePut: (kind: string, key: string, value: unknown) =>
    request<{ ok: boolean }>(
      `/api/state/${encodeURIComponent(kind)}/${encodeURIComponent(key)}`,
      { method: 'PUT', body: JSON.stringify(value) },
    ),

  stateDelete: (kind: string, key: string) =>
    request<{ ok: boolean }>(
      `/api/state/${encodeURIComponent(kind)}/${encodeURIComponent(key)}`,
      { method: 'DELETE' },
    ),

  // v1.0.5 — batch triage
  triageBatch: (req: {
    alerts?: Record<string, unknown>[]
    index?: string
    query?: Record<string, unknown>
    window_minutes?: number
    max_alerts?: number
    max_clusters_to_llm?: number
    reasoning?: 'on' | 'off'
  }) =>
    request<{
      total_alerts: number
      total_clusters: number
      scored_clusters: number
      truncated: boolean
      clusters: Array<{
        cluster_id: string
        rule_id: string
        subject_field: string
        subject_value: string
        count: number
        alert_ids: string[]
        first_seen: string | null
        last_seen: string | null
        severity: string
        priority_rank: number
        recommendation: string
        is_likely_fp: boolean
        fp_reason: string
        attack_intent: string
      }>
      skipped_clusters?: Array<{ cluster_id: string; count: number; reason: string }>
      rag_chunks_used?: number
    }>('/api/triage/batch', {
      method: 'POST',
      body: JSON.stringify(req),
    }),
}
