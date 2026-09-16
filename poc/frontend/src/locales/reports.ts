import type { Bundle } from '@/lib/i18n'

/** 运营报告页。样板见 `shell.ts` 开头。 */
export type ReportsKey =
  | 'title'
  | 'secPeriod'
  | 'periodDaily'
  | 'periodDailyHint'
  | 'periodWeekly'
  | 'periodWeeklyHint'
  | 'periodMonthly'
  | 'periodMonthlyHint'
  | 'selected'
  | 'regenerate'
  | 'emptyPick'
  | 'generating'
  | 'secPatrol'
  | 'patrolTitle'
  | 'patrolEmpty'
  | 'noBody'
  | 'downloadMd'
  | 'healthTitle'
  | 'healthWriteOk'
  | 'healthWriteFail'
  | 'healthAuditOn'
  | 'healthAuditOff'
  | 'triageTitle'
  | 'triageSummary'
  | 'triageHigh'
  | 'legacyPill'
  | 'legacyBody'
  | 'reportRange'
  | 'secExec'
  | 'secTimeline'
  | 'timelineTitle'
  | 'unitAlerts'
  | 'noAlertsInPeriod'
  | 'severityMix'
  | 'centerAlerts'
  | 'secTopRulesEntities'
  | 'topRules'
  | 'topEntities'
  | 'secBaseline'
  | 'baselineTitle'
  | 'baselineEmpty'
  | 'passRate'
  | 'lastRun'
  | 'secByAction'
  | 'byActionTitle'
  | 'noActionData'
  | 'secTopIndexUser'
  | 'topIndexes'
  | 'successRate'
  | 'topUsers'
  | 'secProviders'
  | 'providersTitle'
  | 'providersEmpty'
  | 'colStatus'
  | 'secFullReport'
  | 'markdownTitle'
  | 'noData'
  | 'kpiTotalLabel'
  | 'kpiTotal'
  | 'kpiUrgentLabel'
  | 'kpiUrgent'
  | 'kpiEntitiesLabel'
  | 'kpiEntities'
  | 'kpiAnalyzedLabel'
  | 'kpiAnalyzed'
  | 'chartCount'

export const reportsCopy = {
  zh: {
    title: '运营报告',
    secPeriod: '报告周期与时间区间',
    periodDaily: '日报',
    periodDailyHint: '过去 24 小时',
    periodWeekly: '周报',
    periodWeeklyHint: '过去 7 天',
    periodMonthly: '月报',
    periodMonthlyHint: '过去 30 天',
    selected: '选中',
    regenerate: '重新生成',
    emptyPick: '选一个周期，生成本期安全运营报告',
    generating: '正在汇总告警态势与合规数据…',

    secPatrol: '自动巡检归档',
    patrolTitle: '自动巡检历史',
    patrolEmpty:
      '还没有自动巡检报告。设置 RST_REPORT_SCHEDULE=daily,weekly,monthly 自动生成归档；可选 RST_REPORT_WEBHOOK_URL 投递、RST_REPORT_TRIAGE_INDEX 开启分诊。',
    noBody: '（无正文）',
    downloadMd: '下载 .md',
    healthTitle: '系统健康巡检',
    healthWriteOk: '写入正常',
    healthWriteFail: '写入失败',
    healthAuditOn: '审计已开',
    healthAuditOff: '审计未开',
    triageTitle: '告警分诊巡检',
    triageSummary: '分诊 {n} 簇',
    triageHigh: ' · 高危 {n}',

    legacyPill: '旧格式报告',
    legacyBody: '此报告为旧版结构，无法显示分层卡片。若刚更新后端，请重启网关进程后重新生成。',
    reportRange: '{start} → {end} · 生成于 {generated}',

    secExec: '执行摘要',
    secTimeline: '告警时间线与严重度分布',
    timelineTitle: '告警时间线',
    unitAlerts: '条',
    noAlertsInPeriod: '这个周期没有告警',
    severityMix: '严重度分布',
    centerAlerts: '告警',

    secTopRulesEntities: 'Top 规则与 Top 实体',
    topRules: 'Top 规则',
    topEntities: 'Top 实体',

    secBaseline: '基线巡检',
    baselineTitle: '基线',
    baselineEmpty: '周期内无基线巡检',
    passRate: '通过率',
    lastRun: '最近一次运行 {time}',

    secByAction: '调用按动作分布',
    byActionTitle: '按动作分布',
    noActionData: '无 action 数据',

    secTopIndexUser: 'Top 索引与 Top 用户',
    topIndexes: 'Top 索引',
    successRate: '调用成功率 {rate}%',
    topUsers: 'Top 用户',

    secProviders: '模型服务健康',
    providersTitle: 'Provider 健康',
    providersEmpty: '暂无可用的模型服务',
    colStatus: '状态',

    secFullReport: '报告全文',
    markdownTitle: 'Markdown 全文',
    noData: '无数据',

    kpiTotalLabel: '这个周期',
    kpiTotal: '告警总数',
    kpiUrgentLabel: '需要先看的',
    kpiUrgent: '严重 + 高危',
    kpiEntitiesLabel: '涉及主机 / 账号 / IP',
    kpiEntities: '受影响实体',
    kpiAnalyzedLabel: '走过调查或分诊',
    kpiAnalyzed: '已分析',
    chartCount: '次数',
  },
  en: {
    title: 'Reports',
    secPeriod: 'Reporting period',
    periodDaily: 'Daily',
    periodDailyHint: 'Last 24 hours',
    periodWeekly: 'Weekly',
    periodWeeklyHint: 'Last 7 days',
    periodMonthly: 'Monthly',
    periodMonthlyHint: 'Last 30 days',
    selected: 'Selected',
    regenerate: 'Regenerate',
    emptyPick: 'Pick a period to generate its security operations report',
    generating: 'Aggregating alert posture and compliance data…',

    secPatrol: 'Scheduled report archive',
    patrolTitle: 'Scheduled reports',
    patrolEmpty:
      'No scheduled reports yet. Set RST_REPORT_SCHEDULE=daily,weekly,monthly to generate and archive them; RST_REPORT_WEBHOOK_URL delivers them and RST_REPORT_TRIAGE_INDEX turns on triage.',
    noBody: '(no body)',
    downloadMd: 'Download .md',
    healthTitle: 'System health check',
    healthWriteOk: 'ES write OK',
    healthWriteFail: 'ES write failed',
    healthAuditOn: 'Audit on',
    healthAuditOff: 'Audit off',
    triageTitle: 'Alert triage sweep',
    triageSummary: '{n} triage clusters',
    triageHigh: ' · {n} high',

    legacyPill: 'Legacy format',
    legacyBody:
      'This report uses the old structure and cannot be shown as tiered cards. If you just updated the backend, restart the gateway process and regenerate it.',
    reportRange: '{start} → {end} · generated {generated}',

    secExec: 'Executive summary',
    secTimeline: 'Alert timeline and severity mix',
    timelineTitle: 'Alert timeline',
    unitAlerts: 'alerts',
    noAlertsInPeriod: 'No alerts in this period',
    severityMix: 'Severity mix',
    centerAlerts: 'alerts',

    secTopRulesEntities: 'Top rules and top entities',
    topRules: 'Top rules',
    topEntities: 'Top entities',

    secBaseline: 'Baseline checks',
    baselineTitle: 'Baseline',
    baselineEmpty: 'No baseline run in this period',
    passRate: 'Pass rate',
    lastRun: 'Last run {time}',

    secByAction: 'Calls by action',
    byActionTitle: 'By action',
    noActionData: 'No action data',

    secTopIndexUser: 'Top indices and top users',
    topIndexes: 'Top indices',
    successRate: '{rate}% of calls succeeded',
    topUsers: 'Top users',

    secProviders: 'Model provider health',
    providersTitle: 'Provider health',
    providersEmpty: 'No model provider available',
    colStatus: 'Status',

    secFullReport: 'Full report',
    markdownTitle: 'Markdown source',
    noData: 'No data',

    kpiTotalLabel: 'This period',
    kpiTotal: 'Alerts',
    kpiUrgentLabel: 'Look at these first',
    kpiUrgent: 'Critical + high',
    kpiEntitiesLabel: 'Hosts / accounts / IPs involved',
    kpiEntities: 'Entities affected',
    kpiAnalyzedLabel: 'Went through investigation or triage',
    kpiAnalyzed: 'Analysed',
    chartCount: 'Calls',
  },
} satisfies Bundle<ReportsKey>
