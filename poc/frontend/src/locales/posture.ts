import type { Bundle } from '@/lib/i18n'

/** 安全态势页。样板见 `shell.ts` 开头。 */
export type PostureKey =
  | 'title'
  | 'updatedAt'
  | 'pause'
  | 'resume'
  | 'secKpi'
  | 'kpiTotalLabel'
  | 'kpiTotalTitle'
  | 'kpiUrgentLabel'
  | 'kpiUrgentTitle'
  | 'kpiBaselineNever'
  | 'kpiBaselineLabel'
  | 'kpiBaselineTitle'
  | 'kpiPlatformLabel'
  | 'kpiPlatformTitle'
  | 'kpiUrgentBadge'
  | 'kpiClearBadge'
  | 'kpiNeedsWork'
  | 'recentSearch'
  | 'colSeverity'
  | 'colRule'
  | 'colSubject'
  | 'colTime'
  | 'secTimeline'
  | 'timelineTitle'
  | 'unitAlerts'
  | 'noAlertsInWindow'
  | 'severityMix'
  | 'secLists'
  | 'noisyTitle'
  | 'noisyMeta'
  | 'recentTitle'
  | 'goTriage'
  | 'secArchive'
  | 'archivedCount'
  | 'goArchive'

export const postureCopy = {
  zh: {
    title: '安全态势',
    updatedAt: '更新于 {time}',
    pause: '暂停刷新',
    resume: '继续刷新',

    secKpi: '关键指标',
    kpiTotalLabel: '这个时间窗内',
    kpiTotalTitle: '告警总数',
    kpiUrgentLabel: '需要先看的',
    kpiUrgentTitle: '严重 + 高危',
    kpiBaselineNever: '还没跑过巡检',
    kpiBaselineLabel: '基线检查未通过',
    kpiBaselineTitle: '基线不合规',
    kpiPlatformLabel: '体检里非通过的检查项',
    kpiPlatformTitle: '平台异常',
    kpiUrgentBadge: '需先看',
    kpiClearBadge: '无高危',
    kpiNeedsWork: '需处理',
    recentSearch: '搜规则 / 主体…',
    colSeverity: '严重度',
    colRule: '规则',
    colSubject: '主体',
    colTime: '时间',

    secTimeline: '告警时间线与严重度分布',
    timelineTitle: '告警时间线',
    unitAlerts: '条',
    noAlertsInWindow: '这个时间窗内没有告警',
    severityMix: '严重度分布',

    secLists: '告警最多的规则与最新告警',
    noisyTitle: '告警最多的规则 Top 10',
    noisyMeta: '{n} 条',
    recentTitle: '最新告警 Top 10',
    goTriage: '去处置',

    secArchive: '分析记录归档',
    archivedCount: '已归档的调查与分诊 {n} 条',
    goArchive: '去分析记录',
  },
  en: {
    title: 'Security posture',
    updatedAt: 'Updated {time}',
    pause: 'Pause refresh',
    resume: 'Resume refresh',

    secKpi: 'Key figures',
    kpiTotalLabel: 'In this window',
    kpiTotalTitle: 'Alerts',
    kpiUrgentLabel: 'Look at these first',
    kpiUrgentTitle: 'Critical + high',
    kpiBaselineNever: 'Never run',
    kpiBaselineLabel: 'Baseline checks failing',
    kpiBaselineTitle: 'Baseline drift',
    kpiPlatformLabel: 'Health checks not passing',
    kpiPlatformTitle: 'Platform issues',
    kpiUrgentBadge: 'Look first',
    kpiClearBadge: 'None urgent',
    kpiNeedsWork: 'Needs work',
    recentSearch: 'Search rule / subject…',
    colSeverity: 'Severity',
    colRule: 'Rule',
    colSubject: 'Subject',
    colTime: 'Time',

    secTimeline: 'Alert timeline and severity mix',
    timelineTitle: 'Alert timeline',
    unitAlerts: 'alerts',
    noAlertsInWindow: 'No alerts in this window',
    severityMix: 'Severity mix',

    secLists: 'Top rules by alerts, and the latest alerts',
    noisyTitle: 'Top 10 rules by alerts',
    noisyMeta: '{n} alerts',
    recentTitle: 'Latest 10 alerts',
    goTriage: 'Work it',

    secArchive: 'Analysis archive',
    archivedCount: '{n} archived investigations and triages',
    goArchive: 'Open archive',
  },
} satisfies Bundle<PostureKey>
