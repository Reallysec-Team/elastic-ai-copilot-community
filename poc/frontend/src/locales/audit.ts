import type { Bundle } from '@/lib/i18n'

/** 调用审计页。样板见 `shell.ts` 开头。 */
export type AuditKey =
  | 'title'
  | 'descCount'
  | 'range1h'
  | 'range24h'
  | 'range7d'
  | 'kpiCalls'
  | 'kpiCallsUnit'
  | 'kpiFailed'
  | 'kpiLatency'
  | 'secOverview'
  | 'chartVolume'
  | 'unitCalls'
  | 'auditOff'
  | 'noCallsInWindow'
  | 'actionMix'
  | 'centerCalls'
  | 'secEvents'
  | 'gridEmptyOff'
  | 'gridEmptyOn'
  | 'cardEventsTitle'
  | 'auditOffTitle'
  | 'auditOffBodyPrefix'
  | 'auditOffLink'
  | 'auditOffBodySuffix'
  | 'paginationInfo'
  | 'colTime'
  | 'viewDetail'
  | 'actionAll'
  | 'outcomeAll'
  | 'userPlaceholder'
  | 'filters'
  | 'clearFilters'
  | 'filterAction'
  | 'filterOutcome'
  | 'filterUser'
  | 'filterIndex'
  | 'exportCsv'
  | 'userAria'
  | 'clearUser'
  | 'indexPlaceholder'
  | 'querying'
  | 'query'
  | 'detailTitle'
  | 'hideRawJson'
  | 'showRawJson'
  | 'copyJson'
  // 后端 action 名的页面说法
  | 'actGenerate'
  | 'actLogin'
  | 'actLogout'
  | 'actExecute'
  | 'actExplain'
  | 'actExplainLog'
  | 'actExplainResult'
  | 'actInvestigate'
  | 'actInvestigateAlert'
  | 'actTriage'
  | 'actTriageBatch'
  | 'actDetectionRule'
  | 'actDetectionRuleGenerate'
  | 'actDetectionRuleCopilot'
  | 'actBaseline'
  | 'actPlatformCheckup'
  | 'actPlatformInterpret'
  | 'actFieldDict'
  | 'actKibanaLink'
  | 'actIncidentReport'
  | 'actReport'
  | 'actContentApply'
  | 'actContentRollback'
  | 'actReleaseStaged'
  | 'actFeedback'

export const auditCopy = {
  zh: {
    title: '调用审计',
    descCount: '{n} 条 · 索引 {index}',

    range1h: '1 小时',
    range24h: '24 小时',
    range7d: '7 天',

    kpiCalls: '调用',
    kpiCallsUnit: '次',
    kpiFailed: '失败',
    kpiLatency: '耗时 P50 / P95',

    secOverview: '调用概览',
    chartVolume: '调用量',
    unitCalls: '次',
    auditOff: '审计未启用',
    noCallsInWindow: '这个时间窗里没有调用',
    actionMix: '动作分布',
    centerCalls: '调用',

    secEvents: '事件列表',
    gridEmptyOff: '审计未启用。去「系统设置 → 审计」开启。',
    gridEmptyOn: '审计已启用，但当前时间窗内没有事件。',
    cardEventsTitle: '事件列表',
    auditOffTitle: '审计未启用',
    auditOffBodyPrefix: '前往',
    auditOffLink: '系统设置 → 审计',
    auditOffBodySuffix: '开启。',
    paginationInfo: '{from} - {to} / 共 {count} 条',

    colTime: '时间',
    viewDetail: '查看详情',
    actionAll: 'action：全部',
    outcomeAll: 'outcome：全部',
    userPlaceholder: 'user（精确）',
    filters: '筛选',
    clearFilters: '清除',
    filterAction: '动作',
    filterOutcome: '结果',
    filterUser: '用户',
    filterIndex: '索引',
    exportCsv: '导出 CSV',
    userAria: '按 user 过滤',
    clearUser: '清空 user',
    indexPlaceholder: 'index（全部）',
    querying: '查询中',
    query: '查询',

    detailTitle: '审计事件详情',
    hideRawJson: '收起完整 JSON',
    showRawJson: '查看完整 JSON',
    copyJson: '复制 JSON',

    actGenerate: '生成查询',
    actLogin: '登录',
    actLogout: '退出登录',
    actExecute: '执行查询',
    actExplain: '解读',
    actExplainLog: '日志解读',
    actExplainResult: '结果解读',
    actInvestigate: '调查',
    actInvestigateAlert: '告警调查',
    actTriage: '分诊',
    actTriageBatch: '批量分诊',
    actDetectionRule: '检测规则',
    actDetectionRuleGenerate: '生成检测规则',
    actDetectionRuleCopilot: '检测规则助手',
    actBaseline: '基线巡检',
    actPlatformCheckup: '平台体检',
    actPlatformInterpret: '体检解读',
    actFieldDict: '字段字典',
    actKibanaLink: 'Kibana 跳转',
    actIncidentReport: '事件报告',
    actReport: '运营报告',
    actContentApply: '内容包生效',
    actContentRollback: '内容包回滚',
    actReleaseStaged: '版本暂存',
    actFeedback: '反馈',
  },
  en: {
    title: 'Audit log',
    descCount: '{n} events · index {index}',

    range1h: '1 hour',
    range24h: '24 hours',
    range7d: '7 days',

    kpiCalls: 'Calls',
    kpiCallsUnit: 'calls',
    kpiFailed: 'Failed',
    kpiLatency: 'Latency P50 / P95',

    secOverview: 'Call overview',
    chartVolume: 'Call volume',
    unitCalls: 'calls',
    auditOff: 'Auditing is off',
    noCallsInWindow: 'No calls in this window',
    actionMix: 'By action',
    centerCalls: 'calls',

    secEvents: 'Events',
    gridEmptyOff: 'Auditing is off. Turn it on under Settings → Audit.',
    gridEmptyOn: 'Auditing is on, but there are no events in this window.',
    cardEventsTitle: 'Events',
    auditOffTitle: 'Auditing is off',
    auditOffBodyPrefix: 'Turn it on under',
    auditOffLink: 'Settings → Audit',
    auditOffBodySuffix: '.',
    paginationInfo: '{from} - {to} of {count}',

    colTime: 'Time',
    viewDetail: 'View details',
    actionAll: 'action: all',
    outcomeAll: 'outcome: all',
    userPlaceholder: 'user (exact)',
    filters: 'Filters',
    clearFilters: 'Clear',
    filterAction: 'Action',
    filterOutcome: 'Outcome',
    filterUser: 'User',
    filterIndex: 'Index',
    exportCsv: 'Export CSV',
    userAria: 'Filter by user',
    clearUser: 'Clear the user filter',
    indexPlaceholder: 'index (all)',
    querying: 'Querying',
    query: 'Query',

    detailTitle: 'Audit event',
    hideRawJson: 'Hide the raw JSON',
    showRawJson: 'Show the raw JSON',
    copyJson: 'Copy JSON',

    actGenerate: 'Generate query',
    actLogin: 'Sign in',
    actLogout: 'Sign out',
    actExecute: 'Run query',
    actExplain: 'Explain',
    actExplainLog: 'Explain a log',
    actExplainResult: 'Explain a result',
    actInvestigate: 'Investigate',
    actInvestigateAlert: 'Investigate an alert',
    actTriage: 'Triage',
    actTriageBatch: 'Bulk triage',
    actDetectionRule: 'Detection rule',
    actDetectionRuleGenerate: 'Generate a detection rule',
    actDetectionRuleCopilot: 'Detection rule copilot',
    actBaseline: 'Baseline run',
    actPlatformCheckup: 'Platform checkup',
    actPlatformInterpret: 'Checkup readout',
    actFieldDict: 'Field dictionary',
    actKibanaLink: 'Kibana hand-off',
    actIncidentReport: 'Incident report',
    actReport: 'Operations report',
    actContentApply: 'Content pack applied',
    actContentRollback: 'Content pack rolled back',
    actReleaseStaged: 'Release staged',
    actFeedback: 'Feedback',
  },
} satisfies Bundle<AuditKey>

/** 后端 `audit.write_event(...)` 的第一个实参 → 文案键。缺的按原样显示。 */
export const ACTION_KEY: Record<string, AuditKey> = {
  login: 'actLogin',
  logout: 'actLogout',
  generate: 'actGenerate',
  execute: 'actExecute',
  explain: 'actExplain',
  explain_log: 'actExplainLog',
  explain_result: 'actExplainResult',
  investigate: 'actInvestigate',
  investigate_alert: 'actInvestigateAlert',
  triage: 'actTriage',
  triage_batch: 'actTriageBatch',
  detection_rule: 'actDetectionRule',
  detection_rule_generate: 'actDetectionRuleGenerate',
  detection_rule_copilot: 'actDetectionRuleCopilot',
  baseline: 'actBaseline',
  platform_checkup: 'actPlatformCheckup',
  platform_interpret: 'actPlatformInterpret',
  field_dict: 'actFieldDict',
  kibana_link: 'actKibanaLink',
  incident_report: 'actIncidentReport',
  report: 'actReport',
  content_apply: 'actContentApply',
  content_rollback: 'actContentRollback',
  release_staged: 'actReleaseStaged',
  feedback: 'actFeedback',
}
