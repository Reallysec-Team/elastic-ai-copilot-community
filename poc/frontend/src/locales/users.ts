import type { Bundle } from '@/lib/i18n'

/** 用户与角色页。角色名和角色说明不在这里 —— 它们是 `shell.ts` 的（账号菜单、
    个人资料抽屉都在用同一份），见 ROLE_KEY / ROLE_HINT_KEY。 */
export type UsersKey =
  | 'title'
  | 'newUser'
  | 'errLoad'
  | 'errAction'
  | 'singleUserNotice'
  | 'secList'
  | 'cardTitle'
  | 'cardDesc'
  | 'emptyTitle'
  | 'emptyDesc'
  | 'colAccount'
  | 'colRole'
  | 'colStatus'
  | 'colActions'
  | 'okRole'
  | 'okEnabled'
  | 'okDisabled'
  | 'okDeleted'
  | 'okCreated'
  | 'okReset'
  | 'currentSession'
  | 'roleOf'
  | 'statusDisabled'
  | 'statusOk'
  | 'resetPassword'
  | 'enable'
  | 'disable'
  | 'deleteUser'
  | 'dlgAddTitle'
  | 'fieldAccount'
  | 'fieldInitialPassword'
  | 'fieldRole'
  | 'minChars'
  | 'errUsernameRequired'
  | 'errPasswordShort'
  | 'errCreate'
  | 'create'
  | 'dlgResetTitle'
  | 'fieldNewPassword'
  | 'resetNotice'
  | 'errReset'
  | 'reset'
  | 'delete'
  | 'actionsOf'
  | 'searchPlaceholder'
  | 'countLine'
  | 'noMatch'
  | 'deleteConfirmBody'

export const usersCopy = {
  zh: {
    title: '用户',
    newUser: '新建用户',
    errLoad: '读取失败',
    errAction: '操作失败',
    singleUserNotice:
      '这个部署没有配独立用户表，只有 .env 里的那一个管理员账号，加不了人。要多账号：给网关配上 RST_USER_DB_URL 指向一个 Postgres，重启后这一页就能用。',
    secList: '账号列表',
    cardTitle: '账号',
    cardDesc:
      '三档角色：管理员改配置，分析员做调查，只读只能看。改角色立即生效，不用重新登录；停用和重置密码会把这个账号已经登录的会话全部踢掉。',
    emptyTitle: '还没有账号',
    emptyDesc: '新建一个，或检查用户表是否配好。',
    colAccount: '账号',
    colRole: '角色',
    colStatus: '状态',
    colActions: '操作',
    okRole: '角色已更新',
    okEnabled: '已启用',
    okDisabled: '已停用',
    okDeleted: '账号已删除',
    okCreated: '账号已创建',
    okReset: '密码已重置，该账号的登录会话已全部失效',
    currentSession: '当前登录',
    roleOf: '{name} 的角色',
    statusDisabled: '已停用',
    statusOk: '正常',
    resetPassword: '重置密码',
    enable: '启用',
    disable: '停用',
    deleteUser: '删除 {name}',
    delete: '删除',
    actionsOf: '{name} 的操作',
    searchPlaceholder: '搜账号或角色…',
    countLine: '共 {n} 个账号',
    noMatch: '没有匹配的账号',
    deleteConfirmBody: '删除后这个账号立刻登不进来，已登录的会话全部失效。不可恢复。',
    dlgAddTitle: '新建用户',
    fieldAccount: '账号',
    fieldInitialPassword: '初始密码',
    fieldRole: '角色',
    minChars: '至少 {n} 位',
    errUsernameRequired: '账号不能为空。',
    errPasswordShort: '密码至少 {n} 位。',
    errCreate: '创建失败',
    create: '创建',
    dlgResetTitle: '重置 {name} 的密码',
    fieldNewPassword: '新密码',
    resetNotice: '重置之后这个账号已经登录的会话会全部失效，需要用新密码重新登录。',
    errReset: '重置失败',
    reset: '重置',
  },
  en: {
    title: 'Users',
    newUser: 'New user',
    errLoad: 'Could not load users',
    errAction: 'Action failed',
    singleUserNotice:
      'This deployment has no separate user table — only the single administrator account from .env, so no one can be added. For multiple accounts, point RST_USER_DB_URL at a Postgres and restart the gateway; this page works after that.',
    secList: 'Accounts',
    cardTitle: 'Accounts',
    cardDesc:
      'Three roles: administrators change configuration, analysts investigate, read-only can only look. A role change takes effect immediately with no re-login; disabling an account or resetting its password signs it out everywhere.',
    emptyTitle: 'No accounts yet',
    emptyDesc: 'Create one, or check that the user table is configured.',
    colAccount: 'Account',
    colRole: 'Role',
    colStatus: 'Status',
    colActions: 'Actions',
    okRole: 'Role updated',
    okEnabled: 'Enabled',
    okDisabled: 'Disabled',
    okDeleted: 'Account deleted',
    okCreated: 'Account created',
    okReset: 'Password reset. Every session for this account has been signed out.',
    currentSession: 'You',
    roleOf: "Role for {name}",
    statusDisabled: 'Disabled',
    statusOk: 'Active',
    resetPassword: 'Reset password',
    enable: 'Enable',
    disable: 'Disable',
    deleteUser: 'Delete {name}',
    delete: 'Delete',
    actionsOf: 'Actions for {name}',
    searchPlaceholder: 'Search account or role…',
    countLine: '{n} accounts',
    noMatch: 'No matching accounts',
    deleteConfirmBody: 'The account can no longer sign in and every active session ends immediately. This cannot be undone.',
    dlgAddTitle: 'New user',
    fieldAccount: 'Account',
    fieldInitialPassword: 'Initial password',
    fieldRole: 'Role',
    minChars: 'At least {n} characters',
    errUsernameRequired: 'The account name cannot be empty.',
    errPasswordShort: 'The password must be at least {n} characters.',
    errCreate: 'Could not create the account',
    create: 'Create',
    dlgResetTitle: "Reset {name}'s password",
    fieldNewPassword: 'New password',
    resetNotice:
      'After the reset, every session for this account is signed out and has to sign in again with the new password.',
    errReset: 'Could not reset the password',
    reset: 'Reset',
  },
} satisfies Bundle<UsersKey>
