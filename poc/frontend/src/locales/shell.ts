import type { Bundle } from '@/lib/i18n'

/*
 * 外壳文案：侧栏分组名、导航项、账号菜单、顶栏、试用额度表、个人资料抽屉。
 *
 * 这一份是全站 i18n 的样板，其它页照它写：
 *   1. 一个页/一块一个文件，导出 `xxxCopy`，形状是 { zh: {...}, en: {...} }；
 *   2. 键用「说这句话在干什么」命名（navAlerts、logout），不要用中文原文当键 ——
 *      文案一改键就失效；
 *   3. en 缺键会回落到 zh，界面上不会出现裸键，所以可以分批补；
 *   4. 带变量的写 `{n}` 占位，调用处 t('matched', { n }).
 *
 * 导航项的英文**不是直译**。中文那栏是四字词，直译过去长度从 3 到 18 个字符不等，
 * 排在一条 260px 的轨道上像一把没剪齐的刘海；而且直译出来的词（"Security posture"
 * / "Bulk triage" / "Call audit"）在英文安全产品里不是这么叫的。取的是同类产品里
 * 那个位置惯用的名字，一律收到一到两个词。
 */

export type ShellKey =
  | 'groupOps'
  | 'groupReference'
  | 'groupAdmin'
  | 'navPosture'
  | 'navChat'
  | 'navAnalysis'
  | 'navTriage'
  | 'navRules'
  | 'navFields'
  | 'navKb'
  | 'navBaseline'
  | 'navAssets'
  | 'navPlatform'
  | 'navSettings'
  | 'navAlerts'
  | 'navReports'
  | 'navUsers'
  | 'navAi'
  | 'navLicense'
  | 'navAudit'
  | 'navNotify'
  | 'account'
  | 'language'
  | 'logout'
  // 顶栏 / 导航栏控件
  | 'menu'
  | 'collapseNav'
  | 'expandNav'
  | 'collapse'
  | 'expand'
  | 'searchPlaceholder'
  | 'commandPalette'
  | 'queryHistory'
  | 'inPageNav'
  | 'notSynced'
  | 'syncScope'
  // 横幅
  | 'goActivate'
  | 'esNotReady'
  | 'goConfigure'
  // 主题三档
  | 'themeLight'
  | 'themeDark'
  // 角色
  | 'roleAdmin'
  | 'roleAnalyst'
  | 'roleViewer'
  | 'langSwitchTo'
  | 'themeSwitchTo'
  | 'helpCenter'
  | 'documentation'
  | 'avatar'
  | 'avatarChange'
  | 'avatarRemove'
  | 'avatarHint'
  | 'avatarErrType'
  | 'avatarErrDecode'
  | 'avatarErrSize'
  | 'roleHintAdmin'
  | 'roleHintAnalyst'
  | 'roleHintViewer'
  // 试用额度
  | 'quotaTitle'
  | 'quotaRemaining'
  | 'quotaUsed'
  | 'quotaLeft'
  // 个人资料
  | 'profile'
  | 'profileDesc'
  | 'notSignedIn'
  | 'fieldAccount'
  | 'fieldRole'
  | 'pwSsoNotice'
  | 'pwCurrent'
  | 'pwNew'
  | 'pwConfirm'
  | 'pwMin8'
  | 'pwOtherSessions'
  | 'pwSubmit'
  | 'pwSubmitting'
  | 'pwErrRequired'
  | 'pwErrTooShort'
  | 'pwErrMismatch'
  | 'pwErrFailed'
  | 'pwOk'

export const shellCopy = {
  zh: {
    groupOps: '安全运营',
    groupReference: '基础数据',
    groupAdmin: '管理',
    navPosture: '安全态势',
    navChat: '智能查询',
    navAnalysis: '分析记录',
    navTriage: '批量分诊',
    navRules: '检测规则',
    navFields: '字段字典',
    navKb: '处置手册',
    navBaseline: '基线巡检',
    navAssets: '资产台账',
    navPlatform: '平台健康',
    navSettings: '系统设置',
    navAlerts: '实时告警',
    navReports: '运营报告',
    navUsers: '用户',
    navAi: 'AI 配置',
    navLicense: '产品激活',
    navAudit: '调用审计',
    navNotify: '对外通道',
    account: '账号菜单',
    language: '语言',
    logout: '退出登录',

    menu: '菜单',
    collapseNav: '收起导航栏',
    expandNav: '展开导航栏',
    collapse: '收起',
    expand: '展开',
    searchPlaceholder: '搜索…',
    commandPalette: '命令面板',
    queryHistory: '查询历史',
    inPageNav: '页面内导航',
    notSynced: '未同步',
    syncScope: '部分历史 / 偏好 / 快捷查询 / 分诊状态',

    goActivate: '去激活',
    esNotReady:
      '尚未连接到 Elasticsearch。请先在系统设置里填写集群地址并测试连接，否则查询、告警、分析都没有数据来源。',
    goConfigure: '去配置',

    themeLight: '浅色',
    themeDark: '深色',

    roleAdmin: '管理员',
    roleAnalyst: '分析员',
    roleViewer: '只读',
    langSwitchTo: '切换到{lang}',
    themeSwitchTo: '切换到{theme}',
    helpCenter: '帮助中心',
    documentation: '文档',
    avatar: '头像',
    avatarChange: '换一张',
    avatarRemove: '移除',
    avatarHint: '会缩成 96×96 存在你自己的偏好里，跟着账号走。',
    avatarErrType: '只支持位图图片（png / jpeg / webp / gif / bmp）。',
    avatarErrDecode: '这张图打不开，换一张试试。',
    avatarErrSize: '这张图处理完还是太大，换一张试试。',
    roleHintAdmin: '可以改配置、管账号',
    roleHintAnalyst: '可以查、可以处置，改不了网关配置',
    roleHintViewer: '只读：可以查询、检索、看解读，改不了任何东西',

    quotaTitle: '试用额度',
    quotaRemaining: '今日剩余 {remaining} / {limit} 次，每天 {reset}（{tz}）重置。',
    quotaUsed: '已用',
    quotaLeft: '剩余 {pct}%',

    profile: '个人资料',
    profileDesc: '账号信息与密码',
    notSignedIn: '未登录',
    fieldAccount: '账号',
    fieldRole: '角色',
    pwSsoNotice:
      '这个账号不是用密码登录的（SSO 或反向代理身份），密码不由网关保管，改密码请到你们的身份系统里做。',
    pwCurrent: '当前密码',
    pwNew: '新密码',
    pwConfirm: '确认新密码',
    pwMin8: '至少 8 位',
    pwOtherSessions: '改完之后，这个账号在其他设备上的登录会全部失效，当前这台不受影响。',
    pwSubmit: '修改密码',
    pwSubmitting: '修改中',
    pwErrRequired: '请填写当前密码和新密码。',
    pwErrTooShort: '新密码至少 8 位。',
    pwErrMismatch: '两次输入的新密码不一致。',
    pwErrFailed: '修改失败',
    pwOk: '密码已修改，其他设备上的会话已退出',
  },
  en: {
    groupOps: 'Operations',
    groupReference: 'Reference',
    groupAdmin: 'Admin',
    navPosture: 'Security posture',
    navChat: 'Ask AI',
    navAnalysis: 'Investigations',
    navTriage: 'Triage',
    navRules: 'Detection rules',
    navFields: 'Field dictionary',
    navKb: 'Runbooks',
    navBaseline: 'Baseline checks',
    navAssets: 'Asset inventory',
    navPlatform: 'Platform health',
    navSettings: 'Settings',
    navAlerts: 'Alerts',
    navReports: 'Reports',
    navUsers: 'Users',
    navAi: 'AI settings',
    navLicense: 'License',
    navAudit: 'Audit log',
    navNotify: 'Outbound channels',
    account: 'Account menu',
    language: 'Language',
    logout: 'Sign out',

    menu: 'Menu',
    collapseNav: 'Collapse sidebar',
    expandNav: 'Expand sidebar',
    collapse: 'Collapse',
    expand: 'Expand',
    searchPlaceholder: 'Search…',
    commandPalette: 'Command palette',
    queryHistory: 'Query history',
    inPageNav: 'Section navigation',
    notSynced: 'Not synced',
    syncScope: 'some history / preferences / saved queries / triage state',

    goActivate: 'Activate',
    esNotReady:
      'Not connected to Elasticsearch yet. Set the cluster URL in Settings and test the connection — until then queries, alerts and analysis have no data source.',
    goConfigure: 'Configure',

    themeLight: 'Light',
    themeDark: 'Dark',

    roleAdmin: 'Administrator',
    roleAnalyst: 'Analyst',
    roleViewer: 'Read-only',
    langSwitchTo: 'Switch to {lang}',
    themeSwitchTo: 'Switch to {theme}',
    helpCenter: 'Help center',
    documentation: 'Documentation',
    avatar: 'Avatar',
    avatarChange: 'Change',
    avatarRemove: 'Remove',
    avatarHint: 'Scaled to 96×96 and kept in your own preferences, so it follows the account.',
    avatarErrType: 'Only raster images are supported (png / jpeg / webp / gif / bmp).',
    avatarErrDecode: 'That image could not be opened. Try another one.',
    avatarErrSize: 'That image is still too large after processing. Try another one.',
    roleHintAdmin: 'Can change configuration and manage accounts',
    roleHintAnalyst: 'Can query and act on findings, but not change gateway configuration',
    roleHintViewer: 'Read-only: can query, search and read explanations, but change nothing',

    quotaTitle: 'Trial quota',
    quotaRemaining: '{remaining} of {limit} calls left today, resets daily at {reset} ({tz}).',
    quotaUsed: 'used',
    quotaLeft: '{pct}% left',

    profile: 'Profile',
    profileDesc: 'Account details and password',
    notSignedIn: 'Not signed in',
    fieldAccount: 'Account',
    fieldRole: 'Role',
    pwSsoNotice:
      'This account does not sign in with a password (SSO or reverse-proxy identity). The gateway does not hold its credentials — change the password in your identity provider.',
    pwCurrent: 'Current password',
    pwNew: 'New password',
    pwConfirm: 'Confirm new password',
    pwMin8: 'At least 8 characters',
    pwOtherSessions:
      'Changing it signs this account out on every other device. This one stays signed in.',
    pwSubmit: 'Change password',
    pwSubmitting: 'Changing',
    pwErrRequired: 'Enter your current password and a new one.',
    pwErrTooShort: 'The new password must be at least 8 characters.',
    pwErrMismatch: 'The two new passwords do not match.',
    pwErrFailed: 'Could not change the password',
    pwOk: 'Password changed. Sessions on other devices have been signed out.',
  },
} satisfies Bundle<ShellKey>

/** 后端返回的角色名 → 文案键。角色是闭集，映射写死在这里比在四个组件里各写一份好。 */
export const ROLE_KEY: Record<string, ShellKey> = {
  admin: 'roleAdmin',
  analyst: 'roleAnalyst',
  viewer: 'roleViewer',
}

export const ROLE_HINT_KEY: Record<string, ShellKey> = {
  admin: 'roleHintAdmin',
  analyst: 'roleHintAnalyst',
  viewer: 'roleHintViewer',
}
