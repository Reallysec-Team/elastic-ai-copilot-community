import type { Bundle } from '@/lib/i18n'

/** 智能查询页。样板见 `shell.ts` 开头。 */
export type ChatKey =
  | 'srTitle'
  | 'viewerName'
  | 'opener1'
  | 'opener1Opt1'
  | 'opener1Opt2'
  | 'opener1Opt3'
  | 'opener1Opt4'
  | 'opener2'
  | 'opener2Opt1'
  | 'opener2Opt2'
  | 'opener2Opt3'
  | 'opener2Opt4'
  | 'opener3'
  | 'opener3Opt1'
  | 'opener3Opt2'
  | 'opener3Opt3'
  | 'opener3Opt4'
  | 'opener4'
  | 'opener4Opt1'
  | 'opener4Opt2'
  | 'opener4Opt3'
  | 'opener4Opt4'
  | 'opener5'
  | 'opener5Opt1'
  | 'opener5Opt2'
  | 'opener5Opt3'
  | 'opener5Opt4'
  | 'opener6'
  | 'opener6Opt1'
  | 'opener6Opt2'
  | 'opener6Opt3'
  | 'opener6Opt4'
  | 'openerJoin'
  | 'heading'
  | 'subheading'
  | 'composerPlaceholder'
  | 'indexAuto'
  | 'starterSaved'
  | 'starterSamples'
  | 'emptyThreadTitle'
  | 'currentThread'
  | 'newThread'
  | 'turnCount'
  | 'interrupted'
  | 'stopped'
  | 'errNoDsl'
  | 'errGenerate'
  | 'errDrillNotBucketed'
  | 'promptSaveName'
  | 'okSavedQuery'
  | 'errFeedback'
  | 'triageSourceNote'
  | 'triageTruncated'
  | 'errNoReplayableQuery'
  | 'turnFailedReplay'
  | 'turnAbortedReplay'
  | 'turnPendingReplay'
  | 'threadLastFailed'
  | 'threadLastAborted'
  | 'threadLastPending'
  | 'errOpenThread'
  | 'activityGenerating'
  | 'activityExecuting'
  | 'stageUnderstand'
  | 'stageWrite'
  | 'stageRun'
  | 'stageRunPlain'
  | 'stageThinkingLabel'
  | 'stageThinkingShow'
  | 'stageThinkingHide'
  | 'stageProgressAria'
  | 'activityIdle'
  | 'askWithDataWindow'
  | 'phaseGenerating'
  | 'phaseExecuting'
  | 'phaseDone'
  | 'phaseError'
  | 'replay'
  | 'autoPickedIndex'
  | 'inheritedIndex'
  | 'genCostTitle'
  | 'confidenceTitle'
  | 'confidence'
  | 'confLow'
  | 'confMedium'
  | 'confHigh'
  | 'runQuery'
  | 'gotIt'
  | 'drilledTo'
  | 'backToStats'
  | 'aggGroups'
  | 'hitCount'
  | 'breakdownAggregated'
  | 'breakdownFrom'
  | 'deadSourcesOne'
  | 'deadSourcesN'
  | 'deadSourcesTail'
  | 'tryThis'
  | 'deadHint'
  | 'explainResults'
  | 'sendToTriage'
  | 'staleFutureLead'
  | 'staleFutureLatest'
  | 'staleFutureCause'
  | 'staleWindow'
  | 'staleDataRange'
  | 'staleBaselineHint'
  | 'askDataRange'
  | 'relaxedLead'
  | 'relaxedDrop'
  | 'relaxedThenHas'
  | 'relaxedCount'
  | 'relaxedHint'
  | 'rescueProbing'
  | 'rescueLead'
  | 'rescueCount'
  | 'rescueNoneLead'
  | 'regenerateAllLogs'
  | 'showGeneratedQuery'
  | 'handEdited'
  | 'openInKibana'
  | 'saveAsQuery'
  | 'takeFirst'
  | 'sizeTitle'
  | 'unitRows'
  | 'errKibanaLink'
  | 'noDateFieldTitle'
  | 'noDateField'
  | 'windowQuestionText'
  | 'windowSynced'
  | 'windowReplaced'
  | 'windowIntersected'
  | 'windowFieldTitle'
  | 'rerunOnIndex'
  | 'pickIndexHint'
  | 'retry'
  | 'repairWithError'
  | 'regenerateAllLogsError'
  | 'feedbackUpDone'
  | 'feedbackDownDone'
  | 'feedbackUpTitle'
  | 'feedbackDownTitle'
  | 'errBadJson'
  | 'negHeading'
  | 'negCommentPlaceholder'
  | 'negDslPlaceholder'
  | 'submitFeedback'

export const chatCopy = {
  zh: {
    srTitle: '智能查询',
    /* 头像里那两个字：这个产品的账号是管理员建的，没有头像图，缩写就是全部。 */
    viewerName: '我',
    opener1: '有人在攻击我们吗？',
    opener1Opt1: '看看最近 24 小时登录失败最多的来源 IP',
    opener1Opt2: '看看最近 24 小时反复访问 /wp-login.php、/admin 这类登录页最多的 IP',
    opener1Opt3: '看看最近 1 小时请求次数最多的 IP',
    opener1Opt4: '看看最近 24 小时的高危告警，按规则名数一下',
    opener2: '现在环境有没有异常？',
    opener2Opt1: '看看过去 1 小时哪个服务报错最多',
    opener2Opt2: '看看最近 6 小时每小时错误日志各有多少',
    opener2Opt3: '看看最近 1 小时返回 5xx 最多的接口',
    opener2Opt4: '看看最近 1 小时哪些容器重启或异常退出过',
    opener3: '资产有没有潜在威胁？',
    opener3Opt1: '看看最近 24 小时的高危告警，按规则名数一下',
    opener3Opt2: '看看最近 24 小时告警最多的主机',
    opener3Opt3: '看看最近 24 小时登录失败次数最多的账号',
    opener3Opt4: '看看最近 7 天 Windows 安全日志里失败次数最多的事件类型',
    opener4: '网站是不是出问题了？',
    opener4Opt1: '看看昨天返回 5xx 错误最多的接口',
    opener4Opt2: '看看最近 1 小时各状态码各有多少次',
    opener4Opt3: '看看最近 1 小时 404 最多的路径',
    opener4Opt4: '看看最近 1 小时 nginx 错误日志里最常见的错误',
    opener5: '有没有人半夜偷偷登录？',
    opener5Opt1: '看看最近 7 天 0 点到 6 点成功登录过的账号',
    opener5Opt2: '看看最近 7 天用 root 直接登录成功的来源 IP',
    opener5Opt3: '看看最近 7 天周末登录过的账号',
    opener5Opt4: '看看最近 24 小时从没见过的新 IP 登录成功的记录',
    opener6: '有主机快撑不住了吗？',
    opener6Opt1: '看看最近 1 小时 CPU 占用最高的 5 台主机',
    opener6Opt2: '看看最近 1 小时内存占用最高的 5 台主机',
    opener6Opt3: '看看最近 1 小时磁盘使用率最高的 5 台主机',
    opener6Opt4: '看看最近 1 小时 MySQL 慢查询最多的语句',
    openerJoin: '',
    heading: '想查什么，直接问',
    subheading: '一句话说清你要看什么，查询过程和结果一起给你。',
    composerPlaceholder: '用一句话问，比如：最近 24 小时登录失败次数最多的 10 个源 IP',
    indexAuto: '索引：自动',

    starterSaved: '我的常用',
    starterSamples: '不知道从哪问起？点一张试试',
    emptyThreadTitle: '(空会话)',
    currentThread: '当前会话',
    newThread: '新会话',
    turnCount: '{n} 轮',

    interrupted: '已被新的提问打断',
    stopped: '已停止',
    errNoDsl: '模型没有给出可执行的查询，换个说法再试试。',
    errGenerate: '生成失败',
    errDrillNotBucketed: '聚合「{agg}」不是按字段分桶，无法下钻。',
    promptSaveName: '给这个查询起个名字',
    okSavedQuery: '已存为快捷查询「{name}」，新会话的起始页里一键复用',
    errFeedback: '反馈提交失败',
    triageSourceNote: '来自查询「{question}」· {index}{truncated}',
    triageTruncated: ' · 仅取前 {max}/{total} 条',
    errNoReplayableQuery: '这一轮没有留下可重跑的查询。',
    turnFailedReplay: '这一轮生成失败：{msg}',
    turnAbortedReplay: '这一轮被中断了，没有生成查询。',
    turnPendingReplay: '这一轮没有完成（网关可能在生成时重启了）。',
    threadLastFailed: '上次失败',
    threadLastAborted: '已中断',
    threadLastPending: '生成中',
    errOpenThread: '打开会话失败',

    activityGenerating: '正在把这句话翻译成查询…',
    activityExecuting: '正在 {scope} 上执行…',
    stageUnderstand: '理解问题',
    stageWrite: '生成查询',
    stageRun: '在 {scope} 上执行',
    stageRunPlain: '执行查询',
    stageThinkingLabel: 'AI 在想',
    stageThinkingShow: '展开',
    stageThinkingHide: '收起',
    stageProgressAria: '生成进度',
    activityIdle: '等待提问',
    askWithDataWindow: '{question}（时间范围改为 {lo} 到 {hi}）',

    phaseGenerating: '生成中',
    phaseExecuting: '执行中',
    phaseDone: '回答',
    phaseError: '失败',
    replay: '历史回放',
    autoPickedIndex: '自动选的索引',
    inheritedIndex: '沿用上一轮的索引',
    genCostTitle: '本次生成成本：耗时 / token（或输出字符数）',
    confidenceTitle: '模型对这条查询是否问对了的自评：高 可直接用，中 建议展开核对查询，低 多半要换个说法',
    confidence: '可信度 {level}',
    confLow: '低',
    confMedium: '中',
    confHigh: '高',
    runQuery: '运行这条查询',
    gotIt: '知道了',

    drilledTo: '已下钻到 {label} 的原始文档',
    backToStats: '返回统计',
    aggGroups: '{n} 组统计结果',
    hitCount: '命中 {n} 条',
    breakdownAggregated: '这个统计汇总自',
    breakdownFrom: '这批结果来自',

    deadSourcesOne: '一个',
    deadSourcesN: ' {n} 个',
    deadSourcesTail: '数据源一条都没匹配上，这半边问题其实没答上：',
    tryThis: '试试',
    deadHint:
      '多半是字段值的写法对不上（比如那个索引只写 “ERROR”，查的是 “error”），或者关键词挂在了这个索引很少写的字段上。也可以直接展开下面的查询自己改。',

    explainResults: '解读这批结果',
    sendToTriage: '送去分诊',

    staleFutureLead: '没查到，但问题不在你的问法：{scope} 里有「未来」的日志。',
    staleFutureLatest: '最新一条是 {hi}，比现在还晚 {hours} 小时。',
    staleFutureCause: '多半是采集端把本地时间当 UTC 写入了（也可能是数据源主机时钟快了）。',
    staleWindow: '没查到，是时间窗的问题：你问的是 {start} 之后，但 {scope} 最新一条数据是 {hi}。',
    staleDataRange: '这个索引的数据范围：{range}',
    staleBaselineHint: ' · 平台体检的「时间基线」里有更完整的判断',
    askDataRange: '改查 {range}',

    relaxedLead: '查不到不代表没发生，是下面这个条件卡住了：',
    relaxedDrop: '去掉',
    relaxedThenHas: '后有',
    relaxedCount: '{n} 条',
    relaxedHint:
      '点一条就按放宽后的条件重跑。日志里的原文和你说的词不一定一样（比如日志写的是 “Out of memory”，不是 “OOM”）。',

    rescueProbing: '这个索引里没有，正在其他索引里找…',
    rescueLead: '{scope} 里没有，但同样的条件在别处有命中：',
    rescueCount: '{n} 条',
    rescueNoneLead:
      '同样的条件在其他索引里也没有匹配。可能是查询条件（时间窗、字段值）需要放宽；也可能这条查询本来就是照着 {scope} 的字段写的，换个索引得连查询一起重写。',
    regenerateAllLogs: '在全部日志里重新生成',

    showGeneratedQuery: '查看生成的查询',
    handEdited: '已手改',
    openInKibana: '在 Kibana 中打开',
    saveAsQuery: '存为快捷查询',
    takeFirst: '取前',
    sizeTitle: '取多少条命中。改动会立即重新执行',
    unitRows: '条',
    errKibanaLink: 'Kibana 链接生成失败：{err}',

    noDateFieldTitle: 'mapping 里找不到 date 类型的字段',
    noDateField: '该索引没有时间字段 · 范围未生效',
    windowQuestionText: ' · 问题里说的「{text}」',
    windowSynced: ' · 筛选器已同步',
    windowReplaced: ' · 已覆盖问题里的时间条件',
    windowIntersected: ' · 在问题的时间条件之内',
    windowFieldTitle: '按 {field} 过滤',

    rerunOnIndex: '只在 {index} 上重跑这条查询',
    pickIndexHint: '点索引名可只查它',

    retry: '重试',
    repairWithError: '让 AI 带着报错重修',
    regenerateAllLogsError: '换成全部日志重新生成',

    feedbackUpDone: '已记录',
    feedbackDownDone: '反馈已记录',
    feedbackUpTitle: '查询是对的',
    feedbackDownTitle: '查询有问题',
    errBadJson: '这段 JSON 解析不了，改好再提交；或者清空它，只提交文字说明。',
    negHeading: '哪里有问题（可选）',
    negCommentPlaceholder: '说明哪里不对。例：转账失败要看 event_type=7，不是 status=fail',
    negDslPlaceholder: '可选：粘贴正确的查询（JSON）',
    submitFeedback: '提交反馈',
  },
  en: {
    srTitle: 'Ask AI',
    viewerName: 'Me',
    opener1: 'Is someone attacking us?',
    opener1Opt1: 'Show the source IPs with the most failed logins in the last 24 hours',
    opener1Opt2: 'Show the IPs that hit login pages like /wp-login.php or /admin the most in the last 24 hours',
    opener1Opt3: 'Show the IPs with the most requests in the last hour',
    opener1Opt4: 'Show high-severity alerts in the last 24 hours, counted by rule',
    opener2: 'Is anything wrong right now?',
    opener2Opt1: 'Show which service threw the most errors in the past hour',
    opener2Opt2: 'Show how many error logs there were per hour over the last 6 hours',
    opener2Opt3: 'Show the endpoints that returned the most 5xx errors in the last hour',
    opener2Opt4: 'Show which containers restarted or exited abnormally in the last hour',
    opener3: 'Are our assets under threat?',
    opener3Opt1: 'Show high-severity alerts in the last 24 hours, counted by rule',
    opener3Opt2: 'Show the hosts with the most alerts in the last 24 hours',
    opener3Opt3: 'Show the accounts with the most failed logins in the last 24 hours',
    opener3Opt4: 'Show the most frequent failure event types in Windows security logs over the last 7 days',
    opener4: 'Is the website broken?',
    opener4Opt1: 'Show the endpoints that returned the most 5xx errors yesterday',
    opener4Opt2: 'Show how many responses there were per status code in the last hour',
    opener4Opt3: 'Show the paths with the most 404s in the last hour',
    opener4Opt4: 'Show the most common errors in the nginx error log over the last hour',
    opener5: 'Did anyone log in in the middle of the night?',
    opener5Opt1: 'Show accounts that signed in between midnight and 6am over the last 7 days',
    opener5Opt2: 'Show the source IPs that logged in directly as root over the last 7 days',
    opener5Opt3: 'Show accounts that signed in on weekends over the last 7 days',
    opener5Opt4: 'Show successful logins from IPs never seen before in the last 24 hours',
    opener6: 'Is any host about to fall over?',
    opener6Opt1: 'Show the top 5 hosts by CPU usage in the last hour',
    opener6Opt2: 'Show the top 5 hosts by memory usage in the last hour',
    opener6Opt3: 'Show the top 5 hosts by disk usage in the last hour',
    opener6Opt4: 'Show the MySQL statements with the most slow-query entries in the last hour',
    openerJoin: ' ',
    heading: 'Just ask',
    subheading: 'Say what you want to see. You get the query and the results together.',
    composerPlaceholder:
      'Ask in one sentence — for example: top 10 source IPs by failed logins in the last 24 hours',
    indexAuto: 'Index: auto',

    starterSaved: 'Saved',
    starterSamples: 'Not sure where to start? Pick one',
    emptyThreadTitle: '(empty conversation)',
    currentThread: 'This conversation',
    newThread: 'New conversation',
    turnCount: '{n} turns',

    interrupted: 'Interrupted by a new question',
    stopped: 'Stopped',
    errNoDsl: 'The model did not produce a runnable query. Try asking differently.',
    errGenerate: 'Generation failed',
    errDrillNotBucketed: 'The aggregation "{agg}" is not bucketed by a field, so it cannot be drilled into.',
    promptSaveName: 'Name this query',
    okSavedQuery: 'Saved as "{name}" — reuse it in one click from any new conversation',
    errFeedback: 'Could not submit the feedback',
    triageSourceNote: 'From the query "{question}" · {index}{truncated}',
    triageTruncated: ' · first {max} of {total}',
    errNoReplayableQuery: 'This turn left no query to re-run.',
    turnFailedReplay: 'Generation failed on this turn: {msg}',
    turnAbortedReplay: 'This turn was interrupted; no query was generated.',
    turnPendingReplay: 'This turn never finished (the gateway may have restarted mid-generation).',
    threadLastFailed: 'last failed',
    threadLastAborted: 'interrupted',
    threadLastPending: 'generating',
    errOpenThread: 'Could not open the conversation',

    activityGenerating: 'Translating this into a query…',
    activityExecuting: 'Running it against {scope}…',
    stageUnderstand: 'Understanding the question',
    stageWrite: 'Writing the query',
    stageRun: 'Running against {scope}',
    stageRunPlain: 'Running the query',
    stageThinkingLabel: 'AI is thinking',
    stageThinkingShow: 'Show',
    stageThinkingHide: 'Hide',
    stageProgressAria: 'Generation progress',
    activityIdle: 'Waiting for a question',
    askWithDataWindow: '{question} (change the time range to {lo} – {hi})',

    phaseGenerating: 'Generating',
    phaseExecuting: 'Running',
    phaseDone: 'Answer',
    phaseError: 'Failed',
    replay: 'Replay',
    autoPickedIndex: 'index picked automatically',
    inheritedIndex: 'same index as last turn',
    genCostTitle: 'Cost of this generation: elapsed time / tokens (or output characters)',
    confidenceTitle:
      "The model's own read on whether it understood the question: high — use it; medium — expand and check the query; low — probably rephrase",
    confidence: 'Confidence: {level}',
    confLow: 'low',
    confMedium: 'medium',
    confHigh: 'high',
    runQuery: 'Run this query',
    gotIt: 'Got it',

    drilledTo: 'Drilled into the raw documents for {label}',
    backToStats: 'Back to the aggregate',
    aggGroups: '{n} aggregation buckets',
    hitCount: '{n} hits',
    breakdownAggregated: 'Aggregated from',
    breakdownFrom: 'Results from',

    deadSourcesOne: 'one',
    deadSourcesN: ' {n}',
    deadSourcesTail: ' data source matched nothing at all, so half the question went unanswered:',
    tryThis: 'Try',
    deadHint:
      'Usually the field values are written differently (that index writes “ERROR” while the query looks for “error”), or the keyword lives in a field that index rarely fills. You can also expand the query below and edit it yourself.',

    explainResults: 'Explain these results',
    sendToTriage: 'Send to triage',

    staleFutureLead: 'Nothing matched, but not because of how you asked: {scope} contains logs from the future.',
    staleFutureLatest: 'The newest is {hi}, {hours} hours ahead of now.',
    staleFutureCause:
      'Most likely the shipper wrote local time as UTC (or the source host’s clock is fast).',
    staleWindow:
      'Nothing matched because of the time window: you asked for after {start}, but the newest data in {scope} is {hi}.',
    staleDataRange: 'This index covers: {range}',
    staleBaselineHint: ' · the platform checkup’s time-baseline check says more',
    askDataRange: 'Ask for {range} instead',

    relaxedLead: 'Nothing matched, but that does not mean it did not happen — this clause blocked it:',
    relaxedDrop: 'Drop',
    relaxedThenHas: 'and you get',
    relaxedCount: '{n} hits',
    relaxedHint:
      'Click one to re-run with the clause relaxed. The wording in the logs need not match yours (they may say “Out of memory”, not “OOM”).',

    rescueProbing: 'Nothing in this index — checking the others…',
    rescueLead: 'Nothing in {scope}, but the same conditions match elsewhere:',
    rescueCount: '{n} hits',
    rescueNoneLead:
      'The same conditions match nothing in any other index either. The query may need relaxing (time window, field values) — or it was written against {scope}’s fields, in which case another index needs the query rewritten too.',
    regenerateAllLogs: 'Regenerate against all logs',

    showGeneratedQuery: 'Show the generated query',
    handEdited: 'edited',
    openInKibana: 'Open in Kibana',
    saveAsQuery: 'Save as a query',
    takeFirst: 'size',
    sizeTitle: 'How many hits to take. Changing it re-runs the query immediately.',
    unitRows: 'rows',
    errKibanaLink: 'Could not build the Kibana link: {err}',

    noDateFieldTitle: 'No date-typed field in the mapping',
    noDateField: 'This index has no time field · the range did not apply',
    windowQuestionText: ' · the question said "{text}"',
    windowSynced: ' · filter synced',
    windowReplaced: ' · overrode the time in the question',
    windowIntersected: ' · within the time the question asked for',
    windowFieldTitle: 'Filtered on {field}',

    rerunOnIndex: 'Re-run this query on {index} only',
    pickIndexHint: 'Click an index name to query only that one',

    retry: 'Retry',
    repairWithError: 'Let the AI fix it with the error',
    regenerateAllLogsError: 'Regenerate against all logs',

    feedbackUpDone: 'Recorded',
    feedbackDownDone: 'Feedback recorded',
    feedbackUpTitle: 'The query is right',
    feedbackDownTitle: 'Something is wrong with the query',
    errBadJson: 'That JSON does not parse. Fix it and submit again, or clear it and send just the note.',
    negHeading: 'What is wrong (optional)',
    negCommentPlaceholder:
      'Say what is wrong. Example: failed transfers are event_type=7, not status=fail',
    negDslPlaceholder: 'Optional: paste the correct query (JSON)',
    submitFeedback: 'Submit',
  },
} satisfies Bundle<ChatKey>
