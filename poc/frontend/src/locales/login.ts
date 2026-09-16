/*
 * 登录页的文案。
 *
 * 这一屏在 AppShell 之外（还没登录，拿不到 per-user prefs），语言按
 * `lib/i18n` 的回落走 —— 在这里切成英文，进去之后整站都是英文。
 *
 * 原先这张表内联在 LoginPage 里，早于 `lib/i18n` 存在；形状本来就是一个
 * Bundle，只是没走 useT。搬过来之后全站文案只有 locales/ 一个去处。
 */
import type { Bundle } from '@/lib/i18n'

export type LoginKey =
  | 'language'
  | 'title'
  | 'username'
  | 'password'
  | 'submit'
  | 'validation'
  | 'failed'
  | 'forgot'
  | 'resetTitle'
  | 'resetBody1'
  | 'resetBody2'
  | 'resetBody3'
  | 'resetBody4'
  | 'close'

export const loginCopy: Bundle<LoginKey> = {
  zh: {

    language: '切换到英文',
    title: '登录 Elastic AI Copilot',
    username: '账号',
    password: '密码',
    submit: '登录',
    validation: '请填写账号和密码。',
    failed: '登录失败，请重试。',
    forgot: '忘记密码？',
    resetTitle: '找回密码',
    resetBody1: '本产品部署在你自己的服务器上，没有找回密码用的邮箱通道，所以密码只能由人来重置：',
    resetBody2: '① 多账号部署：请管理员在「系统设置 → 用户」里给你重置密码。',
    resetBody3: '② 单账号部署（只有 admin）：需要运维在网关主机上改登录密码的环境变量并重启网关，具体见 docs/DEPLOYMENT.md。',
    resetBody4: '登录之后可以在账号菜单里自己改密码。',
    close: '知道了',
  },
  en: {

    language: 'Switch to Chinese',
    title: 'Sign in to Elastic AI Copilot',
    username: 'Account',
    password: 'Password',
    submit: 'Sign in',
    validation: 'Enter both account and password.',
    failed: 'Sign-in failed, try again.',
    forgot: 'Forgot password?',
    resetTitle: 'Password reset',
    resetBody1: 'This product runs on your own servers and has no email channel for resets, so a password can only be reset by a person:',
    resetBody2: '① Multi-account deployment: ask an administrator to reset it under Settings → Users.',
    resetBody3: '② Single-account deployment (admin only): ops changes the login password environment variable on the gateway host and restarts it; see docs/DEPLOYMENT.md.',
    resetBody4: 'Once signed in you can change your own password from the account menu.',
    close: 'Got it',
  },
}
