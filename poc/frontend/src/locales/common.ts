import type { Bundle } from '@/lib/i18n'

/*
 * 全站共用的短文案：严重度档位，以及那些在十几个页面里字面重复的动词和状态词
 * （刷新 / 取消 / 保存 / 加载中 / 暂无数据）。
 *
 * 按页分文件是为了让改不同页的人不打架（见 `shell.ts` 开头那四条），但「刷新」
 * 这种词分到十九个文件里就变成了十九份要同步的同义词表。判据是**改一处该不该
 * 影响所有页**：是 → 放这里；不是 → 放页自己的文件。
 */

export type CommonKey =
  // 严重度（后端返回的枚举，见 lib/severity.ts）
  | 'sevInfo'
  | 'sevLow'
  | 'sevMedium'
  | 'sevHigh'
  | 'sevCritical'
  // 基线判定（见 components/baseline/verdictStyle.ts）
  | 'verdictPass'
  | 'verdictFail'
  | 'verdictError'
  | 'verdictManualReview'
  | 'verdictStale'
  // 处置状态（见 lib/triageStatus.ts）——分诊页、深入调查弹窗、实时告警共用
  | 'stOpen'
  | 'stHandled'
  | 'stFp'
  | 'stEscalated'
  // 同步降级
  | 'syncWarning'
  // 相对时间（查询历史、处置手册两处共用）
  | 'justNow'
  | 'minutesAgo'
  | 'hoursAgo'
  | 'daysAgo'
  // 动作
  | 'refresh'
  | 'retry'
  | 'cancel'
  | 'save'
  | 'saving'
  | 'saved'
  | 'close'
  | 'delete'
  | 'edit'
  | 'copy'
  | 'copied'
  | 'export'
  | 'search'
  | 'view'
  // 状态
  | 'loading'
  | 'empty'
  | 'failed'
  | 'unknown'
  | 'enabled'
  | 'disabled'
  | 'no'
  // 只读角色（viewer）：写操作在界面上是禁用的，这是解释为什么
  | 'readOnlyRole'
  // 需要管理员的操作（后端那条路由挂了 require_admin）
  | 'adminOnlyAction'
  // 整页 / 整块只有管理员看得到：说"你看不到"，而不是让它看起来像空的或坏的
  | 'adminOnlyView'
  | 'adminOnlyViewHint'
  // 塞进 pill / 徽标那种只有几个字的位置
  | 'adminOnlyShort'
  // 「深度思考」开关（components/ThinkingToggle.tsx）：智能查询 / 研判 / 规则 / 调查共用
  | 'thinkingToggle'
  | 'thinkingOnHint'
  | 'thinkingOffHint'

export const commonCopy = {
  zh: {
    sevInfo: '提示',
    sevLow: '低',
    sevMedium: '中',
    sevHigh: '高',
    sevCritical: '严重',

    verdictPass: '通过',
    verdictFail: '不合规',
    verdictError: '异常',
    verdictManualReview: '待人工',
    verdictStale: '数据过期',

    stOpen: '未处置',
    stHandled: '已处置',
    stFp: '误报',
    stEscalated: '升级',

    syncWarning:
      '{what}未能同步到服务端，当前仅本机可见，团队其他成员看不到。请检查网关 / ES 写权限 / 是否已登录。',

    justNow: '刚刚',
    minutesAgo: '{n} 分钟前',
    hoursAgo: '{n} 小时前',
    daysAgo: '{n} 天前',

    refresh: '刷新',
    retry: '重试',
    cancel: '取消',
    save: '保存',
    saving: '保存中',
    saved: '已保存',
    close: '关闭',
    delete: '删除',
    edit: '编辑',
    copy: '复制',
    copied: '已复制',
    export: '导出',
    search: '搜索',
    view: '查看',

    loading: '加载中',
    empty: '暂无数据',
    failed: '失败',
    unknown: '未知',
    enabled: '已启用',
    disabled: '已停用',
    readOnlyRole: '当前账号是只读角色，不能修改',
    adminOnlyAction: '这项操作需要管理员权限，当前账号没有',
    adminOnlyView: '这些内容只有管理员看得到',
    adminOnlyViewHint: '当前账号不是管理员，所以这里没有内容可显示。需要的话，请管理员为你开通。',
    adminOnlyShort: '仅管理员可见',
    thinkingToggle: '深度思考',
    thinkingOnHint: '已开启：模型充分推理后再作答，更准，但可能要等 1–2 分钟',
    thinkingOffHint: '已关闭：不推理，几秒出结果。复杂问题可开启',
    no: '否',
  },
  en: {
    sevInfo: 'Info',
    sevLow: 'Low',
    sevMedium: 'Medium',
    sevHigh: 'High',
    sevCritical: 'Critical',

    verdictPass: 'Pass',
    verdictFail: 'Fail',
    verdictError: 'Error',
    verdictManualReview: 'Manual review',
    verdictStale: 'Stale',

    stOpen: 'Open',
    stHandled: 'Handled',
    stFp: 'False positive',
    stEscalated: 'Escalated',

    syncWarning:
      '{what} could not be synced to the server. It is visible on this machine only — the rest of the team cannot see it. Check the gateway, the ES write permission, and whether you are signed in.',

    justNow: 'just now',
    minutesAgo: '{n} min ago',
    hoursAgo: '{n} h ago',
    daysAgo: '{n} d ago',

    refresh: 'Refresh',
    retry: 'Retry',
    cancel: 'Cancel',
    save: 'Save',
    saving: 'Saving',
    saved: 'Saved',
    close: 'Close',
    delete: 'Delete',
    edit: 'Edit',
    copy: 'Copy',
    copied: 'Copied',
    export: 'Export',
    search: 'Search',
    view: 'View',

    loading: 'Loading',
    empty: 'No data',
    failed: 'Failed',
    unknown: 'Unknown',
    enabled: 'Enabled',
    disabled: 'Disabled',
    readOnlyRole: 'This account is read-only and cannot make changes',
    adminOnlyAction: 'This action needs an administrator; this account is not one',
    adminOnlyView: 'Only administrators can see this',
    adminOnlyViewHint:
      'This account is not an administrator, so there is nothing to show here. Ask an administrator if you need access.',
    adminOnlyShort: 'Admin only',
    thinkingToggle: 'Deep thinking',
    thinkingOnHint: 'On: the model reasons before answering — more accurate, may take 1–2 minutes',
    thinkingOffHint: 'Off: no reasoning, answers in seconds. Turn on for hard questions',
    no: 'No',
  },
} satisfies Bundle<CommonKey>
