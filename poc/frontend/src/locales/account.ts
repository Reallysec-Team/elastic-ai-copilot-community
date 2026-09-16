import type { Bundle } from '@/lib/i18n'

/** 个人资料 / 偏好设置页 + 侧栏底部账号菜单。样板见 `shell.ts` 开头。 */
export type AccountKey =
  | 'title'
  | 'tabProfile'
  | 'tabPreferences'
  | 'menuOpen'
  | 'themeSystem'
  | 'cardProfile'
  | 'fieldAvatar'
  | 'fieldAvatarDesc'
  | 'fieldAccount'
  | 'fieldAccountDesc'
  | 'fieldRole'
  | 'fieldSource'
  | 'sourcePassword'
  | 'sourceSso'
  | 'sourceProxy'
  | 'sourceToken'
  | 'cardPassword'
  | 'cardUi'
  | 'fieldLanguage'
  | 'fieldLanguageDesc'
  | 'fieldTheme'
  | 'cardQuery'
  | 'fieldDefaultIndex'
  | 'fieldDefaultIndexDesc'
  | 'fieldPageSize'
  | 'fieldColumns'
  | 'fieldColumnsDesc'
  | 'columnsCount'
  | 'columnsNone'
  | 'columnsReset'
  | 'columnsResetOk'
  | 'savedHint'

export const accountCopy = {
  zh: {
    title: '账号',
    tabProfile: '个人资料',
    tabPreferences: '偏好设置',
    menuOpen: '打开账号菜单',
    themeSystem: '跟随系统',

    cardProfile: '个人资料',
    fieldAvatar: '头像',
    fieldAvatarDesc: '缩成 96×96 存在你自己的偏好里。',
    fieldAccount: '账号',
    fieldAccountDesc: '登录名，由管理员分配，这里改不了。',
    fieldRole: '角色',
    fieldSource: '登录方式',
    sourcePassword: '密码登录',
    sourceSso: '单点登录',
    sourceProxy: '反向代理身份',
    sourceToken: '运维令牌',

    cardPassword: '修改密码',

    cardUi: '界面',
    fieldLanguage: '语言',
    fieldLanguageDesc: '界面文案的语言；后端返回的分析内容不受影响。',
    fieldTheme: '主题',

    cardQuery: '查询',
    fieldDefaultIndex: '默认索引',
    fieldDefaultIndexDesc: '每次进智能查询时预选的索引；「自动」由路由按问题挑。',
    fieldPageSize: '每页行数',
    fieldColumns: '记住的列集',
    fieldColumnsDesc: '结果表里你为各索引挑过的列，按索引记着。',
    columnsCount: '{n} 个索引',
    columnsNone: '还没有',
    columnsReset: '全部重置',
    columnsResetOk: '列集已重置',
    savedHint: '改动即时保存。',
  },
  en: {
    title: 'Account',
    tabProfile: 'Profile',
    tabPreferences: 'Preferences',
    menuOpen: 'Open account menu',
    themeSystem: 'System',

    cardProfile: 'Profile',
    fieldAvatar: 'Avatar',
    fieldAvatarDesc: 'Scaled to 96×96 and kept in your own preferences.',
    fieldAccount: 'Account',
    fieldAccountDesc: 'Sign-in name, assigned by an admin; not editable here.',
    fieldRole: 'Role',
    fieldSource: 'Sign-in method',
    sourcePassword: 'Password',
    sourceSso: 'Single sign-on',
    sourceProxy: 'Reverse-proxy identity',
    sourceToken: 'Ops token',

    cardPassword: 'Change password',

    cardUi: 'Interface',
    fieldLanguage: 'Language',
    fieldLanguageDesc: 'Language of the interface; analysis content from the backend is unaffected.',
    fieldTheme: 'Theme',

    cardQuery: 'Query',
    fieldDefaultIndex: 'Default index',
    fieldDefaultIndexDesc: 'Preselected when you open Ask; "auto" lets the router pick per question.',
    fieldPageSize: 'Rows per page',
    fieldColumns: 'Remembered columns',
    fieldColumnsDesc: 'The columns you picked in result tables, kept per index.',
    columnsCount: '{n} indices',
    columnsNone: 'None yet',
    columnsReset: 'Reset all',
    columnsResetOk: 'Column sets reset',
    savedHint: 'Changes are saved immediately.',
  },
} satisfies Bundle<AccountKey>
