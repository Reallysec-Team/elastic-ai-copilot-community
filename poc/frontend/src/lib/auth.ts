/*
 * Password login client.
 *
 * Deliberately plain fetch instead of lib/api.ts's request(): that helper
 * treats a 401 as "admin token missing" and pops a window.prompt for it. On
 * the login path a 401 means "wrong password", and prompting for an admin
 * token there would be nonsense.
 */

import { useEffect, useState } from 'react'
import { apiErrorMessage } from '@/locales/errors'

export interface MeResponse {
  authenticated: boolean
  /** False when the deployment runs SSO / Basic Auth / demo — no login page then. */
  login_enabled: boolean
  sso_enabled: boolean
  is_admin: boolean
  /**
   * Live role: "admin" | "analyst" | "viewer", or null when the deployment has
   * no role opinion about this caller (ops token, or a proxy-header identity
   * with no account). Null is not a role — treat it as "show it and let the
   * backend answer", which is what the UI did before roles existed.
   */
  role: string | null
  /** True when the gateway is backed by a user table (RST_USER_DB_URL is set). */
  multi_user: boolean
  user: { username: string; roles: string[]; source: string } | null
}

/** 最近一次解析出来的身份。见 `useMe`。登入 / 登出时作废（`forgetMe`）。 */
let _meValue: MeResponse | null = null

export async function fetchMe(): Promise<MeResponse> {
  const r = await fetch('/api/me', { credentials: 'same-origin' })
  if (!r.ok) throw new Error(`/api/me ${r.status}`)
  const me: MeResponse = await r.json()
  // 记下已解析的那一份，`useMe` 拿它当初值。壳的 beforeLoad 在渲染任何一页
  // 之前就 await 过这个函数，所以到这里时它几乎总是已经有值的。
  _meValue = me
  return me
}

export class LoginError extends Error {
  status: number

  constructor(status: number, message: string) {
    super(message)
    this.status = status
  }
}

export async function login(username: string, password: string): Promise<void> {
  forgetMe()
  const r = await fetch('/api/auth/login', {
    method: 'POST',
    credentials: 'same-origin',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ username, password }),
  })
  if (r.ok) return
  // The gateway already writes the user-facing reason (wrong password vs
  // throttled) — surface it rather than inventing a generic one, because
  // "too many attempts" and "wrong password" need different reactions.
  let detail = ''
  try {
    detail = apiErrorMessage(await r.json())
  } catch {
    // non-JSON error body — fall through to the status-based default
  }
  throw new LoginError(r.status, detail)
}

export async function logout(): Promise<void> {
  forgetMe()
  await fetch('/api/auth/logout', { method: 'POST', credentials: 'same-origin' })
}

// 身份在一次会话里不会自己变，而 useCanWrite 会在十几个组件里各用一次 —— 缓存
// 这个 promise，别让每个按钮都去打一次 /api/me。登入登出时作废。
let _me: Promise<MeResponse> | null = null

function cachedMe(): Promise<MeResponse> {
  if (!_me) _me = fetchMe()
  return _me
}

function forgetMe(): void {
  _me = null
  _meValue = null
}

/** Fetch the current identity once. Returns null until it resolves (or on
 * failure — a down gateway must not render a misleading "logged out" state). */
export function useMe(): MeResponse | null {
  /*
   * 初值取已经解析出来的那一份，而不是无条件 `null`。
   *
   * 以前第一帧一律是 null，而 null 在所有闸里都按"先放行"处理（那是为了不让
   * 按钮每次进页面先灰一下）。结果是：非管理员打开管理员页面时，第一帧照样
   * 把整页挂载起来、发出注定 403 的请求，然后才换成"你没权限"。装在 `[]`
   * 依赖里的那些一次性加载更糟 —— 它们不会重跑，那条 403 的错误提示就永远
   * 留在界面上了。
   *
   * 壳的 `beforeLoad` 在渲染任何一页之前就 await 过 `fetchMe()`，所以这里
   * 基本总能拿到值；拿不到时行为跟以前完全一样。
   */
  const [me, setMe] = useState<MeResponse | null>(_meValue)
  useEffect(() => {
    if (_meValue) return
    let live = true
    cachedMe()
      .then((m) => { if (live) setMe(m) })
      .catch(() => {})
    return () => { live = false }
  }, [])
  return me
}

/**
 * 这个账号能不能改东西。viewer 不能 —— 后端的只读闸按 HTTP 方法拦，界面上再
 * 拦一道，免得写操作变成「按钮能点、点了报错」。
 *
 * role 为 null 是「这套部署对这个调用者没有角色意见」（ops token、代理头身份），
 * 不是一个角色 —— 按角色出现之前的行为放行，由后端答复。
 */
export function useCanWrite(): boolean {
  const me = useMe()
  return me?.role !== 'viewer'
}
