import type { Bundle } from '@/lib/i18n'

/** 实时告警页。严重度和处置状态不在这里 —— 它们在 `common.ts`。 */
export type AlertsKey =
  | 'title'
  | 'originPoll'
  | 'originWebhook'
  | 'range1h'
  | 'range6h'
  | 'range24h'
  | 'range7d'
  | 'errLoad'
  | 'errLoadMore'
  | 'syncScopeStatus'
  | 'markedToast'
  | 'undo'
  | 'secOverview'
  | 'chartRate'
  | 'unitAlerts'
  | 'statsError'
  | 'noAlertsInWindow'
  | 'statsErrorDonut'
  | 'severityMix'
  | 'centerAlerts'
  | 'kpiAlerts'
  | 'kpiAlertsUnit'
  | 'kpiUrgent'
  | 'kpiNoisiest'
  | 'secFeed'
  | 'feedTitle'
  | 'secSummary'
  | 'sumTotalDesc'
  | 'sumUrgentDesc'
  | 'sumClosedDesc'
  | 'sumStreamLive'
  | 'sumStreamPaused'
  | 'sumStreamDown'
  | 'showClosed'
  | 'hiddenClosed'
  | 'picked'
  | 'markHandled'
  | 'markFp'
  | 'markOpen'
  | 'clearSelection'
  | 'allClosed'
  | 'loadingMoreInline'
  | 'fetchingOlder'
  | 'loadMore'
  | 'noAlertsYet'
  | 'newAlerts'
  | 'noMore'
  | 'secIngest'
  | 'filterSeverity'
  | 'filterAll'
  | 'sevWithCode'
  | 'rulePlaceholder'
  | 'views'
  | 'deleteView'
  | 'viewNamePlaceholder'
  | 'saveView'
  | 'countAlerts'
  | 'group'
  | 'paused'
  | 'pausedOffTop'
  | 'live'
  | 'resume'
  | 'pause'
  | 'sseConnected'
  | 'sseDisconnected'
  | 'liveShort'
  | 'reconnecting'
  | 'selectAlert'
  | 'collapseGroup'
  | 'expandGroup'
  | 'dispoAria'
  | 'errLoadIngest'
  | 'errSave'
  | 'ingestTitle'
  | 'pollTitle'
  | 'pollDesc'
  | 'fieldAlertIndex'
  | 'fieldPollInterval'
  | 'webhookTitle'
  | 'webhookDesc'
  | 'fieldSecret'
  | 'secretSetPlaceholder'
  | 'secretUnsetPlaceholder'
  | 'clearSecret'
  | 'cursor'
  | 'pillPoll'
  | 'pillEnabled'
  | 'pillNotConfigured'
  | 'pillNotWhitelisted'
  | 'pillWebhook'
  | 'pillWebhookOn'
  | 'pillWebhookOff'
  | 'discoverOriginIgnored'
  | 'pillSummarySkipped'
  | 'pillSummarySkippedHint'
  | 'rowSummarySkipped'
  | 'rowSummary'
  | 'rowRule'
  | 'rowRuleId'
  | 'rowSubject'
  | 'rowSubjectField'
  | 'rowTime'
  | 'rowOrigin'
  | 'rowSourceIndex'
  | 'rowSourceId'
  | 'rowIngestedAt'
  | 'assetContext'
  | 'confidence'
  | 'candidates'
  | 'resolving'
  | 'assetBusinessName'
  | 'assetCriticality'
  | 'assetCategory'
  | 'assetOwner'
  | 'assetDepartment'
  | 'assetNote'
  | 'assetNoteDrift'
  | 'noAssetContext'
  | 'rawJson'
  | 'discoverUnavailable'
  | 'investigateTitle'
  | 'investigate'
  | 'sendToTriageTitle'
  | 'sendToTriage'
  | 'triageSourceNote'
  | 'copyDocId'

export const alertsCopy = {
  zh: {
    title: '实时告警',
    originPoll: '定时拉取',
    originWebhook: 'Webhook 推送',

    range1h: '1 小时',
    range6h: '6 小时',
    range24h: '24 小时',
    range7d: '7 天',

    errLoad: '加载告警失败',
    errLoadMore: '加载更多告警失败',
    syncScopeStatus: '处置状态',
    markedToast: '已标记 {n} 条为「{status}」',
    undo: '撤销',

    secOverview: '告警概览',
    chartRate: '告警速率',
    unitAlerts: '条',
    statsError: '概览算不出来：{err}',
    noAlertsInWindow: '这个时间窗里没有告警',
    statsErrorDonut: '概览算不出来，下面的告警流不受影响',
    severityMix: '严重度分布',
    centerAlerts: '告警',
    kpiAlerts: '告警',
    kpiAlertsUnit: '条',
    kpiUrgent: '高危以上',
    kpiNoisiest: '告警最多的规则',

    secFeed: '告警流',
    feedTitle: '告警流',
    secSummary: '摘要',
    sumTotalDesc: '{range}内进来的告警',
    sumUrgentDesc: '严重 + 高危，先看这些',
    sumClosedDesc: '已处置 / 误报（这条流共 {n} 条）',
    sumStreamLive: '实时推送中，新告警自动进流',
    sumStreamPaused: '已手动暂停，新告警先攒着',
    sumStreamDown: '连接断开，正在重连',
    showClosed: '显示已处置 / 误报',
    hiddenClosed: '已隐藏 {n} 条已处置 / 误报',
    picked: '已选 {n} 条',
    markHandled: '标记已处置',
    markFp: '标记误报',
    markOpen: '恢复未处置',
    clearSelection: '清除选择',
    allClosed: '已加载的 {n} 条告警都已处置 / 标记误报。',
    loadingMoreInline: '正在加载更多…',
    fetchingOlder: '正在拉取更早的告警…',
    loadMore: '加载更多',
    noAlertsYet: '未收到告警。轮询拉取需在上方配置告警索引；Webhook 推送需 Kibana 指向 /api/alerts/ingest。',
    newAlerts: '{n} 条新告警',
    noMore: '没有更多了',
    secIngest: '告警摄取配置',

    filterSeverity: '严重度',
    filterAll: '全部',
    sevWithCode: '{name}（{code}）',
    rulePlaceholder: '规则名/ID…',
    views: '视图',
    deleteView: '删除视图 {name}',
    viewNamePlaceholder: '视图名…',
    saveView: '保存当前',
    countAlerts: '共 {n} 条',
    group: '分组',
    paused: '已暂停',
    pausedOffTop: '离顶暂停中',
    live: '实时',
    resume: '继续',
    pause: '暂停',
    sseConnected: 'SSE 已连接',
    sseDisconnected: 'SSE 断开，自动重连中',
    liveShort: '实时',
    reconnecting: '断开重连中',
    selectAlert: '选择此告警',
    collapseGroup: '收起分组',
    expandGroup: '展开分组',
    dispoAria: '处置状态（团队共享）',

    errLoadIngest: '加载摄取配置失败',
    errSave: '保存失败',
    ingestTitle: '摄取配置',
    pollTitle: '轮询拉取',
    pollDesc: '网关按间隔查询告警索引尾部，延迟≈轮询间隔。留空则关闭。',
    fieldAlertIndex: '告警索引',
    fieldPollInterval: '轮询间隔（秒）',
    webhookTitle: 'Webhook 推送',
    webhookDesc: 'Kibana 检测规则触发即回调网关，零延迟。设密钥后启用。',
    fieldSecret: '鉴权密钥',
    secretSetPlaceholder: '已设置，留空不改',
    secretUnsetPlaceholder: '设置后 Kibana 才能推送',
    clearSecret: '清除已设置的密钥',
    cursor: '游标：{ts}',
    pillPoll: '轮询拉取',
    pillEnabled: '启用',
    pillNotConfigured: '未配置',
    pillNotWhitelisted: '索引不在白名单 RST_INDEX_WHITELIST',
    pillWebhook: 'Webhook 推送',
    pillWebhookOn: '已启用',
    pillWebhookOff: '未启用',
    discoverOriginIgnored:
      '深链用的是网关内部配置的 Kibana 地址：你访问网关用的域名不在 RST_CORS_ORIGINS 里，出于安全不拿它来拼地址。链接可能在你的浏览器里打不开 —— 让管理员设置 KIBANA_PUBLIC_URL，或把这个域名加进 RST_CORS_ORIGINS。',
    pillSummarySkipped: '{n} 条未生成摘要',
    pillSummarySkippedHint:
      '最近一小时内，有告警因为超出单次推送的摘要时间预算（{budget}s）而没生成摘要。告警本身已入库，只是没有那一句 AI 概括。',
    rowSummarySkipped: '未生成（超出摘要时间预算）',

    rowSummary: 'AI 摘要',
    rowRule: '规则',
    rowRuleId: '规则 ID',
    rowSubject: '主体',
    rowSubjectField: '主体 · {field}',
    rowTime: '发生时间',
    rowOrigin: '来源',
    rowSourceIndex: '来源索引',
    rowSourceId: '来源文档 ID',
    rowIngestedAt: '入库时间',

    assetContext: '资产语境',
    confidence: '置信 {level}',
    candidates: '{n} 个候选',
    resolving: '解析中…',
    assetBusinessName: '业务名',
    assetCriticality: '重要度',
    assetCategory: '类别',
    assetOwner: '负责人',
    assetDepartment: '部门',
    assetNote: '备注',
    assetNoteDrift: '当前值，可能漂移',
    noAssetContext: '无资产语境（未匹配到资产表/身份表）',
    rawJson: '原始 JSON',
    discoverUnavailable: 'Discover 不可用：',
    investigateTitle: '围绕该告警主体拉取上下文做深入调查',
    investigate: '深入调查',
    sendToTriageTitle: '把该告警送去批量分诊排优先级',
    sendToTriage: '送去分诊',
    triageSourceNote: '来自实时告警「{name}」',
    copyDocId: '复制文档 ID',
  },
  en: {
    title: 'Alerts',
    originPoll: 'Polled',
    originWebhook: 'Webhook',

    range1h: '1 hour',
    range6h: '6 hours',
    range24h: '24 hours',
    range7d: '7 days',

    errLoad: 'Could not load alerts',
    errLoadMore: 'Could not load more alerts',
    syncScopeStatus: 'Disposition',
    markedToast: 'Marked {n} as "{status}"',
    undo: 'Undo',

    secOverview: 'Alert overview',
    chartRate: 'Alert rate',
    unitAlerts: 'alerts',
    statsError: 'Overview could not be computed: {err}',
    noAlertsInWindow: 'No alerts in this window',
    statsErrorDonut: 'The overview could not be computed; the feed below is unaffected',
    severityMix: 'Severity mix',
    centerAlerts: 'alerts',
    kpiAlerts: 'Alerts',
    kpiAlertsUnit: 'alerts',
    kpiUrgent: 'High and above',
    kpiNoisiest: 'Noisiest rule',

    secFeed: 'Alert feed',
    feedTitle: 'Alert feed',
    secSummary: 'Summary',
    sumTotalDesc: 'alerts in the {range}',
    sumUrgentDesc: 'critical + high, look at these first',
    sumClosedDesc: 'handled / false positive (of {n} in the stream)',
    sumStreamLive: 'live, new alerts flow in automatically',
    sumStreamPaused: 'paused by you, new alerts are buffered',
    sumStreamDown: 'disconnected, reconnecting',
    showClosed: 'Show handled / false positives',
    hiddenClosed: '{n} handled / false positives hidden',
    picked: '{n} selected',
    markHandled: 'Mark handled',
    markFp: 'Mark false positive',
    markOpen: 'Reopen',
    clearSelection: 'Clear selection',
    allClosed: 'All {n} loaded alerts are handled or marked false positive.',
    loadingMoreInline: 'Loading more…',
    fetchingOlder: 'Fetching older alerts…',
    loadMore: 'Load more',
    noAlertsYet:
      'No alerts received. Polling needs an alert index configured above; the webhook needs Kibana pointed at /api/alerts/ingest.',
    newAlerts: '{n} new alerts',
    noMore: 'Nothing older',
    secIngest: 'Alert ingest configuration',

    filterSeverity: 'Severity',
    filterAll: 'All',
    sevWithCode: '{name} ({code})',
    rulePlaceholder: 'Rule name / ID…',
    views: 'Views',
    deleteView: 'Delete the view {name}',
    viewNamePlaceholder: 'View name…',
    saveView: 'Save current',
    countAlerts: '{n} loaded',
    group: 'Group',
    paused: 'Paused',
    pausedOffTop: 'Paused (scrolled away from the top)',
    live: 'Live',
    resume: 'Resume',
    pause: 'Pause',
    sseConnected: 'SSE connected',
    sseDisconnected: 'SSE disconnected, reconnecting',
    liveShort: 'Live',
    reconnecting: 'Reconnecting',
    selectAlert: 'Select this alert',
    collapseGroup: 'Collapse the group',
    expandGroup: 'Expand the group',
    dispoAria: 'Disposition (shared with the team)',

    errLoadIngest: 'Could not load the ingest configuration',
    errSave: 'Save failed',
    ingestTitle: 'Ingest configuration',
    pollTitle: 'Polling',
    pollDesc:
      'The gateway tails the alert index on an interval; the delay is roughly the interval. Leave it empty to turn polling off.',
    fieldAlertIndex: 'Alert index',
    fieldPollInterval: 'Poll interval (seconds)',
    webhookTitle: 'Webhook',
    webhookDesc:
      'A Kibana detection rule calls the gateway the moment it fires — no delay. Set a secret to enable it.',
    fieldSecret: 'Auth secret',
    secretSetPlaceholder: 'Set — leave empty to keep it',
    secretUnsetPlaceholder: 'Kibana can only push once this is set',
    clearSecret: 'Clear the stored secret',
    cursor: 'Cursor: {ts}',
    pillPoll: 'Polling',
    pillEnabled: 'on',
    pillNotConfigured: 'not configured',
    pillNotWhitelisted: 'Index is not in RST_INDEX_WHITELIST',
    pillWebhook: 'Webhook',
    pillWebhookOn: 'on',
    pillWebhookOff: 'off',
    discoverOriginIgnored:
      'The deep link uses the gateway’s configured Kibana address: the host you reached the gateway on is not in RST_CORS_ORIGINS, so it is not trusted to build URLs from. The link may not open in your browser — ask an administrator to set KIBANA_PUBLIC_URL, or add this host to RST_CORS_ORIGINS.',
    pillSummarySkipped: '{n} without a summary',
    pillSummarySkippedHint:
      'In the last hour some alerts arrived past the per-push summary budget ({budget}s), so no summary was generated. The alerts themselves are stored.',
    rowSummarySkipped: 'not generated (past the summary time budget)',

    rowSummary: 'AI summary',
    rowRule: 'Rule',
    rowRuleId: 'Rule ID',
    rowSubject: 'Subject',
    rowSubjectField: 'Subject · {field}',
    rowTime: 'Occurred',
    rowOrigin: 'Origin',
    rowSourceIndex: 'Source index',
    rowSourceId: 'Source document ID',
    rowIngestedAt: 'Ingested',

    assetContext: 'Asset context',
    confidence: 'Confidence: {level}',
    candidates: '{n} candidates',
    resolving: 'Resolving…',
    assetBusinessName: 'Business name',
    assetCriticality: 'Criticality',
    assetCategory: 'Category',
    assetOwner: 'Owner',
    assetDepartment: 'Department',
    assetNote: 'Note',
    assetNoteDrift: 'Current value — it may have drifted',
    noAssetContext: 'No asset context (no match in the asset or identity table)',
    rawJson: 'Raw JSON',
    discoverUnavailable: 'Discover unavailable: ',
    investigateTitle: 'Pull context around this alert’s subject and investigate',
    investigate: 'Investigate',
    sendToTriageTitle: 'Send this alert to bulk triage for prioritisation',
    sendToTriage: 'Send to triage',
    triageSourceNote: 'From the alert "{name}"',
    copyDocId: 'Copy the document ID',
  },
} satisfies Bundle<AlertsKey>
