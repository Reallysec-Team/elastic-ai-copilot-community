import type { Bundle } from '@/lib/i18n'

/*
 * 跨页共用的部件文案：时间区间选择器、结果表、索引选择器、查询历史抽屉、
 * 命令面板、DSL 预览、错误边界。
 *
 * 它们跟页面不是一对一的（时间选择器在四个页面上、结果表在两个），所以不跟着
 * 任何一页的文件走；但也不属于 `common.ts` —— 那里放的是「改一处该影响所有页」
 * 的词，这里是具体部件自己的说法。
 */
export type ComponentsKey =
  // 时间区间选择器
  | 'unitMinute'
  | 'unitHour'
  | 'unitDay'
  | 'recentN'
  | 'allTime'
  | 'now'
  | 'pickOnCalendar'
  | 'errPickDay'
  | 'errEndBeforeStart'
  | 'presets'
  | 'startTime'
  | 'endTime'
  | 'apply'
  // 结果表
  | 'copyFailed'
  | 'noDocs'
  | 'noDocsHint'
  | 'selectedRows'
  | 'copyJson'
  | 'exportCsv'
  | 'clear'
  | 'selectAllOnPage'
  | 'clickToSort'
  | 'notSortable'
  | 'colActions'
  | 'selectRow'
  | 'explainWithAi'
  | 'explain'
  | 'investigateAsAlert'
  | 'investigate'
  | 'columnsCount'
  | 'filterFields'
  | 'noMatchingField'
  | 'selectAll'
  | 'restoreDefault'
  | 'perPage'
  | 'prevPage'
  | 'nextPage'
  | 'paginationInfo'
  | 'collapse'
  | 'drillHint'
  | 'exportBucketsTitle'
  | 'aggGroup'
  | 'aggCount'
  | 'drillTitle'
  | 'bucketsHidden'
  | 'nestedAggNote'
  // 索引选择器
  | 'indexPlaceholder'
  | 'filterPlaceholder'
  | 'refreshFromEs'
  | 'loadingIndices'
  | 'noIndices'
  | 'noMatchingIndex'
  | 'autoPick'
  | 'autoPickDesc'
  | 'allLogs'
  | 'allLogsDesc'
  | 'nIndices'
  | 'asWildcard'
  | 'dataRangeTitle'
  | 'nTargets'
  // 查询历史
  | 'recentLocal'
  | 'queryHistory'
  | 'confirmClearHistory'
  | 'clearHistory'
  | 'emptyShort'
  | 'historyEmpty'
  | 'confidence'
  | 'confHigh'
  | 'confMedium'
  | 'confLow'
  | 'replay'
  | 'replayTitle'
  // 命令面板
  | 'newThread'
  | 'newThreadHint'
  | 'palettePlaceholder'
  | 'paletteSearchAria'
  | 'commandsAria'
  | 'noMatchingCommand'
  | 'hintMove'
  | 'hintRun'
  | 'hintClose'
  | 'nItems'
  // DSL 预览
  | 'errEmpty'
  | 'errJsonParse'
  | 'errNotObject'
  | 'editDslTitle'
  | 'edit'
  | 'saveTitleInvalid'
  | 'saveTitleValid'
  | 'expandAll'
  | 'jsonValid'
  | 'saveHint'
  // 首页运营概览
  | 'ovAlerts'
  | 'ovUrgent'
  | 'ovNoUrgent'
  | 'ovAlertsSummary'
  | 'ovBaseline'
  | 'ovNotScored'
  | 'ovScore'
  | 'ovNeverRan'
  | 'ovBaselineSummary'
  | 'ovPlatform'
  | 'ovAllPass'
  | 'ovNeedsWork'
  | 'ovPlatformSummary'
  | 'ovAnalysis'
  | 'ovReplayable'
  | 'ovAnalysisSummary'
  | 'ovSeeAll'
  | 'ovUnreadable'
  // 图表块
  | 'chartEmpty'
  | 'donutTotalAria'
  // 会话列表 / 输入框
  | 'threadAll'
  | 'threadPinned'
  | 'threadToday'
  | 'threadEarlier'
  | 'newThreadAria'
  | 'noThreads'
  | 'inProgress'
  | 'recentThreads'
  | 'deleteThreadAria'
  | 'starterOptionsTitle'
  | 'starterOptionsClose'
  | 'starterOptionsCustom'
  | 'starterMoreAngles'
  | 'starterMoreAnglesBusy'
  | 'starterMoreAnglesNone'
  | 'starterAngleJoin'
  | 'askCopilot'
  | 'stopGenerating'
  | 'send'
  // 首屏搜索框
  | 'heroIndexLabel'
  | 'heroIndexPlaceholder'
  | 'heroQuestionPlaceholder'
  | 'heroGenerating'
  | 'heroGenerate'
  // 错误边界
  | 'boundaryTitle'
  | 'boundaryBody'
  | 'retryRender'
  | 'reloadPage'

export const componentsCopy = {
  zh: {
    unitMinute: '分钟',
    unitHour: '小时',
    unitDay: '天',
    recentN: '近 {n} {unit}',
    allTime: '全部时间',
    now: '现在',
    pickOnCalendar: '在日历上点一天，或点两天选一段',
    errPickDay: '请先在日历上选一天',
    errEndBeforeStart: '结束时间要晚于开始时间',
    presets: '快捷',
    startTime: '开始时间',
    endTime: '结束时间',
    apply: '应用',

    copyFailed: '复制失败',
    noDocs: '没有匹配的文档',
    noDocsHint:
      '没命中不一定是出错。可试：放宽时间窗（如 now-24h → now-7d）、放松过滤条件、换一个索引，或换个问法后重新生成 DSL。',
    selectedRows: '已选 {n} 行',
    copyJson: '复制 JSON',
    exportCsv: '导出 CSV',
    clear: '清除',
    selectAllOnPage: '选择本页全部',
    clickToSort: '点击排序',
    notSortable: '该字段不支持排序',
    colActions: '操作',
    selectRow: '选择此行',
    explainWithAi: '用 AI 解释这条日志',
    explain: '解释',
    investigateAsAlert: '把这条当作告警调查',
    investigate: '调查',
    columnsCount: '列 {shown}/{total}',
    filterFields: '过滤字段…',
    noMatchingField: '无匹配字段',
    selectAll: '全选',
    restoreDefault: '恢复默认',
    perPage: '每页',
    prevPage: '上一页',
    nextPage: '下一页',
    paginationInfo: '{from} - {to} / 共 {count} 条',
    collapse: '收起',
    drillHint: '点击任意行下钻查看原始日志',
    exportBucketsTitle: '导出该聚合的全部桶为 CSV',
    aggGroup: '分组',
    aggCount: '条数',
    drillTitle: '下钻：按这个值拉取原始日志',
    bucketsHidden: '+{n} 个桶未显示',
    nestedAggNote: '子聚合 {names} 是嵌套分桶（不是单个数值），这里放不进一列，请在原始 JSON 里查看。',

    indexPlaceholder: '索引名（支持 * 通配）',
    filterPlaceholder: '过滤…',
    refreshFromEs: '从 ES 刷新',
    loadingIndices: '正在拉取索引列表…',
    noIndices: '没有可用索引，请检查数据源连接与索引白名单配置。',
    noMatchingIndex: '没有匹配 "{q}" 的索引',
    autoPick: '自动选择',
    autoPickDesc: '按问题挑索引，答完会告诉你查的是哪个',
    allLogs: '全部日志',
    allLogsDesc: '不确定在哪个索引就选这个，命中后会告诉你数据在哪',
    nIndices: '{n} 个',
    asWildcard: '作为通配符',
    dataRangeTitle: '最早 / 最新一条数据的时间 · {size}',
    nTargets: '{n} 个目标',

    recentLocal: '本机最近 {n} 条',
    queryHistory: '查询历史',
    confirmClearHistory: '清空所有历史？',
    clearHistory: '清空',
    emptyShort: '空',
    historyEmpty: '历史是空的。运行一次查询后，问题、索引和 DSL 会自动落到这里，方便你回放。',
    confidence: '置信度 {level}',
    confHigh: '高',
    confMedium: '中',
    confLow: '低',
    replay: '重放',
    replayTitle: '把这条问题填回查询页',

    newThread: '新建会话',
    newThreadHint: '清空并回到智能查询',
    palettePlaceholder: '跳转页面或执行操作…',
    paletteSearchAria: '命令面板搜索',
    commandsAria: '命令',
    noMatchingCommand: '没有匹配 “{q}” 的命令',
    hintMove: '移动',
    hintRun: '执行',
    hintClose: '关闭',
    nItems: '{n} 项',

    errEmpty: '不能为空',
    errJsonParse: 'JSON 解析失败',
    errNotObject: 'DSL 必须是 JSON 对象（不能是数组或基本类型）',
    editDslTitle: '手动编辑 DSL',
    edit: '编辑',
    saveTitleInvalid: '修正 JSON 后才能保存',
    saveTitleValid: '保存并替换当前查询语句',
    expandAll: '展开全部 · {n} 行',
    jsonValid: 'JSON 合法，可保存',
    saveHint: '保存后执行你修改的版本。',

    ovAlerts: '待处置告警',
    ovUrgent: '{n} 条高危以上',
    ovNoUrgent: '无高危',
    ovAlertsSummary: '过去 24 小时进来的',
    ovBaseline: '基线不合规',
    ovNotScored: '未评分',
    ovScore: '合规 {score}',
    ovNeverRan: '还没跑过巡检',
    ovBaselineSummary: '最近一轮巡检的结果',
    ovPlatform: '平台异常',
    ovAllPass: '全部通过',
    ovNeedsWork: '需要处理',
    ovPlatformSummary: '体检里非通过的检查项',
    ovAnalysis: '分析记录',
    ovReplayable: '可回看',
    ovAnalysisSummary: '已归档的调查与分诊',
    ovSeeAll: '查看全部问题',
    ovUnreadable: '读不出来',

    chartEmpty: '这个时间窗里没有记录',
    donutTotalAria: '{title}：共 {total}',

    threadAll: '全部',
    threadPinned: '已置顶',
    threadToday: '今天',
    threadEarlier: '更早',
    newThreadAria: '新会话',
    noThreads: '还没有会话',
    inProgress: '进行中',
    recentThreads: '最近的会话',
    deleteThreadAria: '删除会话「{title}」',
    starterOptionsTitle: '{question} 可以从这几个角度看：',
    starterOptionsClose: '收起',
    starterOptionsCustom: '都不是我想问的，自己写一句…',
    starterMoreAngles: '让 AI 再想几个角度',
    starterMoreAnglesBusy: '在想…',
    starterMoreAnglesNone: '没想出新的了',
    starterAngleJoin: '',
    askCopilot: '向 Copilot 提问',
    stopGenerating: '停止生成',
    send: '发送',

    heroIndexLabel: '索引',
    heroIndexPlaceholder: '选索引',
    heroQuestionPlaceholder: '用一句话问，比如：近 1 小时各 response 状态码计数',
    heroGenerating: '生成中',
    heroGenerate: '生成 DSL',

    boundaryTitle: '这个页面出了点问题',
    boundaryBody: '页面在渲染时抛了异常。其他页面不受影响，可以切换导航继续使用，或重载本页。',
    retryRender: '重试渲染',
    reloadPage: '重载整页',
  },
  en: {
    unitMinute: 'min',
    unitHour: 'h',
    unitDay: 'd',
    recentN: 'Last {n}{unit}',
    allTime: 'All time',
    now: 'now',
    pickOnCalendar: 'Click a day, or two days for a range',
    errPickDay: 'Pick a day on the calendar first',
    errEndBeforeStart: 'The end has to be after the start',
    presets: 'Presets',
    startTime: 'Start',
    endTime: 'End',
    apply: 'Apply',

    copyFailed: 'Could not copy',
    noDocs: 'No matching documents',
    noDocsHint:
      'No hits does not mean something broke. Try widening the window (now-24h → now-7d), relaxing a filter, switching index, or rephrasing the question so the DSL is regenerated.',
    selectedRows: '{n} rows selected',
    copyJson: 'Copy JSON',
    exportCsv: 'Export CSV',
    clear: 'Clear',
    selectAllOnPage: 'Select every row on this page',
    clickToSort: 'Click to sort',
    notSortable: 'This field cannot be sorted on',
    colActions: 'Actions',
    selectRow: 'Select this row',
    explainWithAi: 'Explain this log with AI',
    explain: 'Explain',
    investigateAsAlert: 'Investigate this as an alert',
    investigate: 'Investigate',
    columnsCount: 'Columns {shown}/{total}',
    filterFields: 'Filter fields…',
    noMatchingField: 'No field matches',
    selectAll: 'Select all',
    restoreDefault: 'Restore defaults',
    perPage: 'per page',
    prevPage: 'Previous page',
    nextPage: 'Next page',
    paginationInfo: '{from} - {to} of {count} rows',
    collapse: 'Collapse',
    drillHint: 'Click any row to drill into the raw logs',
    exportBucketsTitle: 'Export every bucket of this aggregation as CSV',
    aggGroup: 'Group',
    aggCount: 'Count',
    drillTitle: 'Drill in: pull the raw logs for this value',
    bucketsHidden: '+{n} buckets not shown',
    nestedAggNote:
      'The sub-aggregations {names} are nested buckets rather than single values, so they do not fit in a column — look at the raw JSON.',

    indexPlaceholder: 'Index name (* wildcards allowed)',
    filterPlaceholder: 'Filter…',
    refreshFromEs: 'Refresh from Elasticsearch',
    loadingIndices: 'Fetching the index list…',
    noIndices: 'No index available. Check the data-source connection and the index allowlist.',
    noMatchingIndex: 'No index matches "{q}"',
    autoPick: 'Auto',
    autoPickDesc: 'The gateway picks an index from the question and tells you which one it used',
    allLogs: 'All logs',
    allLogsDesc: 'Pick this when you are not sure which index; the answer says where the data was',
    nIndices: '{n}',
    asWildcard: 'as a wildcard',
    dataRangeTitle: 'Oldest / newest document · {size}',
    nTargets: '{n} targets',

    recentLocal: 'Last {n} on this machine',
    queryHistory: 'Query history',
    confirmClearHistory: 'Clear the whole history?',
    clearHistory: 'Clear',
    emptyShort: 'empty',
    historyEmpty:
      'The history is empty. Run a query and its question, index and DSL land here for replay.',
    confidence: 'Confidence: {level}',
    confHigh: 'high',
    confMedium: 'medium',
    confLow: 'low',
    replay: 'Replay',
    replayTitle: 'Put this question back in the query box',

    newThread: 'New conversation',
    newThreadHint: 'Clear and go back to Ask',
    palettePlaceholder: 'Go to a page or run an action…',
    paletteSearchAria: 'Command palette search',
    commandsAria: 'Commands',
    noMatchingCommand: 'No command matches "{q}"',
    hintMove: 'move',
    hintRun: 'run',
    hintClose: 'close',
    nItems: '{n} items',

    errEmpty: 'Cannot be empty',
    errJsonParse: 'The JSON does not parse',
    errNotObject: 'The DSL has to be a JSON object (not an array or a primitive)',
    editDslTitle: 'Edit the DSL by hand',
    edit: 'Edit',
    saveTitleInvalid: 'Fix the JSON before saving',
    saveTitleValid: 'Save and replace the current query',
    expandAll: 'Expand · {n} lines',
    jsonValid: 'Valid JSON — ready to save',
    saveHint: 'Saving runs your edited version.',

    ovAlerts: 'Alerts to work',
    ovUrgent: '{n} high and above',
    ovNoUrgent: 'none urgent',
    ovAlertsSummary: 'arrived in the last 24 hours',
    ovBaseline: 'Baseline drift',
    ovNotScored: 'not scored',
    ovScore: 'score {score}',
    ovNeverRan: 'never run',
    ovBaselineSummary: 'from the latest run',
    ovPlatform: 'Platform issues',
    ovAllPass: 'all passing',
    ovNeedsWork: 'needs work',
    ovPlatformSummary: 'health checks not passing',
    ovAnalysis: 'Investigations',
    ovReplayable: 'replayable',
    ovAnalysisSummary: 'archived investigations and triages',
    ovSeeAll: 'See everything',
    ovUnreadable: 'unreadable',

    chartEmpty: 'Nothing in this window',
    donutTotalAria: '{title}: {total} total',

    threadAll: 'All',
    threadPinned: 'Pinned',
    threadToday: 'Today',
    threadEarlier: 'Earlier',
    newThreadAria: 'New conversation',
    noThreads: 'No conversations yet',
    inProgress: 'In progress',
    recentThreads: 'Recent conversations',
    deleteThreadAria: 'Delete conversation “{title}”',
    starterOptionsTitle: '{question} A few ways to look at it:',
    starterOptionsClose: 'Close',
    starterOptionsCustom: 'None of these. Let me write my own…',
    starterMoreAngles: 'Ask AI for a few more angles',
    starterMoreAnglesBusy: 'Thinking…',
    starterMoreAnglesNone: 'Nothing new came up',
    starterAngleJoin: ' ',
    askCopilot: 'Ask the copilot',
    stopGenerating: 'Stop',
    send: 'Send',

    boundaryTitle: 'This page hit a problem',
    heroIndexLabel: 'Index',
    heroIndexPlaceholder: 'Pick an index',
    heroQuestionPlaceholder: 'Ask in one sentence — e.g. count by response status over the last hour',
    heroGenerating: 'Generating',
    heroGenerate: 'Generate DSL',

    boundaryBody:
      'The page threw while rendering. Other pages are unaffected — navigate away and keep working, or reload this one.',
    retryRender: 'Render again',
    reloadPage: 'Reload the page',
  },
} satisfies Bundle<ComponentsKey>
