import type { Bundle } from '@/lib/i18n'

/** 批量分诊页。处置状态（未处置 / 已处置 / 误报 / 升级）不在这里，它在
    `common.ts` —— 这一页、深入调查弹窗、实时告警三处共用。 */
export type TriageKey =
  | 'title'
  | 'syncScopeStatus'
  | 'confirmEscalate'
  | 'okDispatched'
  | 'warnNoChannel'
  | 'errEscalate'
  | 'handoffReceived'
  | 'truncateNote'
  | 'errIndexRequired'
  | 'errQueryJson'
  | 'errRequest'
  | 'promptSaveNote'
  | 'okSaved'
  | 'errSave'
  | 'secSubmit'
  | 'cardSubmitTitle'
  | 'switchToEs'
  | 'fieldIndex'
  | 'fieldQuery'
  | 'fieldWindow'
  | 'windowHintHandoff'
  | 'windowHintEs'
  | 'fieldMaxAlerts'
  | 'fieldMaxClusters'
  | 'start'
  | 'running'
  | 'secResult'
  | 'ragUsed'
  | 'degradedFallback'
  | 'truncatedClusters'
  | 'sevMix'
  | 'centerClusters'
  | 'sevMixEmpty'
  | 'saveRun'
  | 'exportCsv'
  | 'countAll'
  | 'countFiltered'
  | 'filterBySeverity'
  | 'sevAll'
  | 'sevOption'
  | 'filterByStatus'
  | 'statusAll'
  | 'noMatchingClusters'
  | 'kpiTotalLabel'
  | 'kpiTotal'
  | 'kpiScoredLabel'
  | 'kpiScored'
  | 'kpiUrgentLabel'
  | 'kpiUrgent'
  | 'likelyFp'
  | 'dispositionLabel'
  | 'colSeverity'
  | 'colIntent'
  | 'colSubject'
  | 'colCount'
  | 'colSpan'
  | 'colActions'
  | 'queueTitle'
  | 'queueDesc'
  | 'bulkSelected'
  | 'bulkHint'
  | 'clearSelection'
  | 'recommendation'
  | 'alertIdsLabel'
  | 'showAlertIds'
  | 'addToCompareTitle'
  | 'inCompare'
  | 'compare'
  | 'investigateTitle'
  | 'investigate'
  | 'loadingLine'
  | 'loadingSlowHint'
  | 'secCompare'
  | 'compareHeading'
  | 'clearCompare'
  | 'removeFromCompare'
  | 'pastRuns'
  | 'errLoadRuns'
  | 'loadFailed'
  | 'noSavedRuns'
  | 'noNote'

export const triageCopy = {
  zh: {
    title: '批量分诊',
    syncScopeStatus: '处置状态',
    confirmEscalate: '已标记为升级。是否推送给值班 / 飞书群？',
    okDispatched: '已推送给 {n} 个值班渠道',
    warnNoChannel: '未配置匹配的值班渠道，未推送（可在「对外通道」里配置飞书目标）',
    errEscalate: '升级推送失败：{err}',
    handoffReceived: '已接收 {n} 条告警',
    truncateNote: '收到 {got} 条，超出上限 {max}，仅分诊前 {max} 条。',
    errIndexRequired: '请填好索引名',
    errQueryJson: '查询 JSON 解析失败：{err}',
    errRequest: '请求失败',
    promptSaveNote: '给这次分诊加个备注（可选）',
    okSaved: '已保存到服务端 · 全队可见',
    errSave: '保存失败',

    secSubmit: '提交告警',
    cardSubmitTitle: '提交告警',
    switchToEs: '改为从 ES 拉取',
    fieldIndex: '索引',
    fieldQuery: '查询（可选）',
    fieldWindow: '时间窗（分钟）',
    windowHintHandoff: '「深入调查」围绕主体拉取上下文的时间窗。',
    windowHintEs: '从 ES 拉取告警的时间窗，同时用于「深入调查」。',
    fieldMaxAlerts: '最多分诊条数',
    fieldMaxClusters: '送模型评分的聚类上限',
    start: '开始分诊',
    running: '分诊中…',

    secResult: '分诊结果',
    ragUsed: '评分参考了 {n} 篇知识库文档',
    degradedFallback: 'AI 评分未完成，以下为按告警数量排序的聚类（未含严重度/建议）。可稍后重试评分。',
    truncatedClusters: '有 {n} 个聚类分组超出单批打分上限（{max}），可调高上方的单批聚类上限后重新提交。',
    sevMix: '聚类严重度',
    centerClusters: '聚类',
    sevMixEmpty: '这次分诊没有评出严重度',
    saveRun: '保存此次分诊',
    exportCsv: '导出 CSV',
    countAll: '{n} 个聚类，按优先级排序',
    countFiltered: '{shown} / {total} 个聚类',
    filterBySeverity: '按严重度筛选',
    sevAll: '严重度：全部 {n}',
    sevOption: '{name} {n}',
    filterByStatus: '按处置状态筛选',
    statusAll: '处置：全部',
    noMatchingClusters: '没有符合条件的聚类。',

    kpiTotalLabel: '聚成 {n} 组',
    kpiTotal: '告警总数',
    kpiScoredLabel: '共 {n} 组',
    kpiScored: '已评分',
    kpiUrgentLabel: '共 {n} 组',
    kpiUrgent: '高危及以上',

    likelyFp: '疑似误报',
    dispositionLabel: '处置',
    colSeverity: '严重度',
    colIntent: '攻击意图 / 主体',
    colSubject: '主体',
    colCount: '告警数',
    colSpan: '时间跨度',
    colActions: '操作',
    queueTitle: '分诊队列',
    queueDesc: '{n} 个聚类，按优先级排序；点行看建议和告警 ID',
    bulkSelected: '已选 {n} 个聚类',
    bulkHint: '一次改它们的处置状态',
    clearSelection: '清除选择',
    recommendation: '处置建议',
    alertIdsLabel: '告警 ID（{n}）',
    showAlertIds: '查看 alert ID 列表（{n}）',
    addToCompareTitle: '加入底部并排对比',
    inCompare: '已加入对比',
    compare: '对比',
    investigateTitle: '围绕该主体拉取上下文做深入调查',
    investigate: '深入调查',
    loadingLine: 'AI 正在分诊… 已运行 {secs}s',
    loadingSlowHint: ' · 聚类较多时偏慢，可减少单批聚类上限',

    secCompare: '并排对比',
    compareHeading: '并排对比 · {n}',
    clearCompare: '清空对比',
    removeFromCompare: '移出对比',

    pastRuns: '历史分诊',
    errLoadRuns: '加载失败',
    loadFailed: '加载失败：{err}',
    noSavedRuns: '还没有保存的分诊',
    noNote: '（无备注）',
  },
  en: {
    title: 'Triage',
    syncScopeStatus: 'Disposition',
    confirmEscalate: 'Marked as escalated. Push it to the on-call channel?',
    okDispatched: 'Pushed to {n} on-call channels',
    warnNoChannel: 'No matching on-call channel is configured, so nothing was pushed (set one up under Notifications)',
    errEscalate: 'Escalation push failed: {err}',
    handoffReceived: 'Received {n} alerts',
    truncateNote: 'Received {got}, over the cap of {max} — triaging the first {max}.',
    errIndexRequired: 'Enter an index name',
    errQueryJson: 'Could not parse the query JSON: {err}',
    errRequest: 'Request failed',
    promptSaveNote: 'Add a note for this run (optional)',
    okSaved: 'Saved on the server · visible to the whole team',
    errSave: 'Save failed',

    secSubmit: 'Submit alerts',
    cardSubmitTitle: 'Submit alerts',
    switchToEs: 'Pull from Elasticsearch instead',
    fieldIndex: 'Index',
    fieldQuery: 'Query (optional)',
    fieldWindow: 'Time window (minutes)',
    windowHintHandoff: 'The window an investigation uses to gather context around the subject.',
    windowHintEs: 'The window alerts are pulled from, and the one an investigation uses for context.',
    fieldMaxAlerts: 'Maximum alerts',
    fieldMaxClusters: 'Maximum clusters sent to the model',
    start: 'Start triage',
    running: 'Triaging…',

    secResult: 'Triage result',
    ragUsed: 'Scoring used {n} runbook documents',
    degradedFallback:
      'Scoring did not complete. The clusters below are ordered by alert count only, with no severity or recommendation. You can retry scoring later.',
    truncatedClusters:
      '{n} clusters were over the per-batch scoring cap ({max}). Raise the cap above and submit again.',
    sevMix: 'Cluster severity',
    centerClusters: 'clusters',
    sevMixEmpty: 'This run produced no severities',
    saveRun: 'Save this run',
    exportCsv: 'Export CSV',
    countAll: '{n} clusters, highest priority first',
    countFiltered: '{shown} of {total} clusters',
    filterBySeverity: 'Filter by severity',
    sevAll: 'Severity: all {n}',
    sevOption: '{name} {n}',
    filterByStatus: 'Filter by disposition',
    statusAll: 'Disposition: all',
    noMatchingClusters: 'No cluster matches.',

    kpiTotalLabel: 'in {n} clusters',
    kpiTotal: 'Alerts',
    kpiScoredLabel: 'of {n} clusters',
    kpiScored: 'Scored',
    kpiUrgentLabel: 'of {n} clusters',
    kpiUrgent: 'High and above',

    likelyFp: 'Likely false positive',
    dispositionLabel: 'Disposition',
    colSeverity: 'Severity',
    colIntent: 'Attack intent / subject',
    colSubject: 'Subject',
    colCount: 'Alerts',
    colSpan: 'Time span',
    colActions: 'Actions',
    queueTitle: 'Triage queue',
    queueDesc: '{n} clusters by priority; click a row for the recommendation and alert IDs',
    bulkSelected: '{n} clusters selected',
    bulkHint: 'Set their disposition in one step',
    clearSelection: 'Clear selection',
    recommendation: 'Recommendation',
    alertIdsLabel: 'Alert IDs ({n})',
    showAlertIds: 'Show alert IDs ({n})',
    addToCompareTitle: 'Add to the side-by-side comparison below',
    inCompare: 'In comparison',
    compare: 'Compare',
    investigateTitle: 'Pull context around this subject and investigate',
    investigate: 'Investigate',
    loadingLine: 'Triaging… {secs}s elapsed',
    loadingSlowHint: ' · many clusters run slower; lower the per-batch cluster cap',

    secCompare: 'Side-by-side comparison',
    compareHeading: 'Side by side · {n}',
    clearCompare: 'Clear',
    removeFromCompare: 'Remove from the comparison',

    pastRuns: 'Past runs',
    errLoadRuns: 'Could not load',
    loadFailed: 'Could not load: {err}',
    noSavedRuns: 'No saved runs yet',
    noNote: '(no note)',
  },
} satisfies Bundle<TriageKey>
