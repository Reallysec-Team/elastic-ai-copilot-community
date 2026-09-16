import type { Bundle } from '@/lib/i18n'

/*
 * 两个 AI 弹窗：事件解读（解释日志 / 解读结果）和深入调查。
 *
 * 合成一份是因为它们的下半截是同一套：导出 / 分享那一组按钮、飞书发送、降级
 * 提示、重试。上半截各说各的，键前缀分开（`ex` / `inv`）。
 */
export type DialogsKey =
  // 共用
  | 'confidence'
  | 'exportShare'
  | 'copyMarkdown'
  | 'copied'
  | 'copyFailed'
  | 'clipboardUnsupported'
  | 'exportMarkdownFile'
  | 'sendToFeishu'
  | 'sentToFeishu'
  | 'sendFailedRetry'
  | 'feishuHint'
  | 'degradedTitle'
  | 'retry'
  // 事件解读
  | 'exErrExplain'
  | 'exHeadingResult'
  | 'exHeadingLog'
  | 'exTitleResult'
  | 'exTitleLog'
  | 'exWhatResult'
  | 'exWhatLog'
  | 'exReanalyseTitle'
  | 'exReanalyse'
  | 'exOpenInInvestigation'
  | 'exMdSeverity'
  | 'exMdConfidence'
  | 'exMdKeyFields'
  | 'exMdIndicators'
  | 'exMdInvestigation'
  | 'exRagUsed'
  | 'exSecKeyFields'
  | 'exSecIndicators'
  | 'exSecInvestigation'
  | 'exSecInvestigationClickable'
  | 'exUseSuggestionTitle'
  | 'exDegradedBody'
  | 'exAnalysing'
  // 深入调查
  | 'invTitle'
  | 'invErrInvestigate'
  | 'invSubjectHint'
  | 'invDetectionQuestion'
  | 'invNotifyPushed'
  | 'invNotifyNoChannel'
  | 'invNotifyFailed'
  | 'invConfirmEscalate'
  | 'invReportTitle'
  | 'invFeishuDoc'
  | 'invFeishuAnnounced'
  | 'invFeishuSubmitted'
  | 'invFeishuFailed'
  | 'invErrExport'
  | 'invLikelyFp'
  | 'invAgenticRounds'
  | 'invRounds'
  | 'invContextCount'
  | 'invRagCount'
  | 'invGeneratingReport'
  | 'invDownloaded'
  | 'invExportReport'
  | 'invDisposition'
  | 'invToDetectionRuleTitle'
  | 'invToDetectionRule'
  | 'invNotifyTitle'
  | 'invNotified'
  | 'invNotify'
  | 'invSecFp'
  | 'invSecTimeline'
  | 'invSecKillChain'
  | 'invColTechnique'
  | 'invColEvidence'
  | 'invSecAssets'
  | 'invSecRecommendation'
  | 'invSecAgentic'
  | 'invStepFailed'
  | 'invStepHits'
  | 'invTraceOk'
  | 'invTraceFailed'
  | 'invStepArgs'
  | 'invDegradedBody'
  | 'invAnalysing'

export const dialogsCopy = {
  zh: {
    confidence: '置信度',
    exportShare: '导出 / 分享',
    copyMarkdown: '复制 Markdown',
    copied: '已复制',
    copyFailed: '复制失败',
    clipboardUnsupported: '当前环境不支持剪贴板，请改用「导出」',
    exportMarkdownFile: '导出 Markdown 文件',
    sendToFeishu: '发送到飞书',
    sentToFeishu: '已发送到飞书',
    sendFailedRetry: '发送失败，重试',
    feishuHint: '生成飞书云文档并通告到群。发过即锁，避免刷屏。',
    degradedTitle: 'AI 结果降级',
    retry: '重试',

    exErrExplain: '解释失败',
    exHeadingResult: '解读结果',
    exHeadingLog: '解释日志',
    exTitleResult: '查询结果解读',
    exTitleLog: '日志解释',
    exWhatResult: '这批查询结果',
    exWhatLog: '这条日志',
    exReanalyseTitle: '忽略缓存，重新让 AI 分析一次',
    exReanalyse: '重新分析',
    exOpenInInvestigation: '在告警调查中打开',
    exMdSeverity: '- 严重度：{v}',
    exMdConfidence: '- 置信度：{v}',
    exMdKeyFields: '## 关键字段',
    exMdIndicators: '## 关注点',
    exMdInvestigation: '## 排查建议',
    exRagUsed: '参考了 {n} 篇知识库文档',
    exSecKeyFields: '关键字段',
    exSecIndicators: '关注点',
    exSecInvestigation: '排查建议',
    exSecInvestigationClickable: '排查建议 · 点击任意一条按它重新查询',
    exUseSuggestionTitle: '按这条建议重新生成查询',
    exDegradedBody: '模型本次返回无法解析，下方为安全占位结果。请稍后重试，或换一条日志再试。',
    exAnalysing: 'AI 正在分析{what}…',

    invTitle: '告警调查',
    invErrInvestigate: '调查失败',
    invSubjectHint: '（重点主体 {type}:{id}）',
    invDetectionQuestion: '检测并告警：{alertType}{subjectHint}。{summary}',
    invNotifyPushed: '已推送 {n} 个渠道',
    invNotifyNoChannel: '无匹配渠道：未配置飞书目标，或严重度未达其阈值（在「对外通道」里配置）',
    invNotifyFailed: '推送失败',
    invConfirmEscalate: '已标记为升级。是否推送给值班 / 飞书群？',
    invReportTitle: '安全调查报告 · {alertType}',
    invFeishuDoc: '云文档：{url}',
    invFeishuAnnounced: '已通告 {n} 个飞书群',
    invFeishuSubmitted: '已提交',
    invFeishuFailed: '发送失败',
    invErrExport: '导出失败',
    invLikelyFp: '疑似误报',
    invAgenticRounds: '自主调查',
    invRounds: '{n} 轮',
    invContextCount: '上下文 {n} 条',
    invRagCount: '知识库 {n} 篇',
    invGeneratingReport: '正在生成报告…',
    invDownloaded: '已下载 {size}',
    invExportReport: '导出事件报告 (Markdown)',
    invDisposition: '处置',
    invToDetectionRuleTitle: '把确认的威胁转成 Kibana 检测规则，挡下次',
    invToDetectionRule: '转成检测规则',
    invNotifyTitle: '把这条调查结论推送到已配置的飞书渠道',
    invNotified: '已推送',
    invNotify: '推送结论',
    invSecFp: '误报判定',
    invSecTimeline: '时间线',
    invSecKillChain: '攻击链',
    invColTechnique: '技术名',
    invColEvidence: '证据',
    invSecAssets: '受影响资产',
    invSecRecommendation: '处置建议',
    invSecAgentic: '检索过程 (agentic)',
    invStepFailed: '失败',
    invStepHits: '命中 {n} 条',
    invTraceOk: '{n} 步，全部成功',
    invTraceFailed: '{n} 步，{f} 步失败',
    invStepArgs: '调用参数',
    invDegradedBody: '模型本次返回无法解析，下方为安全占位结果。请稍后重试，或换一条告警再试。',
    invAnalysing: 'AI 正在分析告警 + 拉取上下文（可能要 30-60 秒）…',
  },
  en: {
    confidence: 'Confidence',
    exportShare: 'Export / share',
    copyMarkdown: 'Copy Markdown',
    copied: 'Copied',
    copyFailed: 'Could not copy',
    clipboardUnsupported: 'The clipboard is unavailable here — use Export instead',
    exportMarkdownFile: 'Export a Markdown file',
    sendToFeishu: 'Send to Feishu',
    sentToFeishu: 'Sent to Feishu',
    sendFailedRetry: 'Send failed — retry',
    feishuHint: 'Creates a Feishu doc and announces it to the group. Locked after one send so it cannot spam.',
    degradedTitle: 'Degraded AI result',
    retry: 'Retry',

    exErrExplain: 'Could not explain',
    exHeadingResult: 'Result readout',
    exHeadingLog: 'Log explanation',
    exTitleResult: 'Query result readout',
    exTitleLog: 'Log explanation',
    exWhatResult: 'these results',
    exWhatLog: 'this log line',
    exReanalyseTitle: 'Ignore the cache and have the AI analyse it again',
    exReanalyse: 'Analyse again',
    exOpenInInvestigation: 'Open as an investigation',
    exMdSeverity: '- Severity: {v}',
    exMdConfidence: '- Confidence: {v}',
    exMdKeyFields: '## Key fields',
    exMdIndicators: '## What to watch',
    exMdInvestigation: '## Next steps',
    exRagUsed: 'Used {n} runbook documents',
    exSecKeyFields: 'Key fields',
    exSecIndicators: 'What to watch',
    exSecInvestigation: 'Next steps',
    exSecInvestigationClickable: 'Next steps · click one to re-query with it',
    exUseSuggestionTitle: 'Regenerate the query from this suggestion',
    exDegradedBody:
      'The model returned something unparseable, so a safe placeholder is shown below. Try again shortly, or with a different log line.',
    exAnalysing: 'Analysing {what}…',

    invTitle: 'Alert investigation',
    invErrInvestigate: 'Investigation failed',
    invSubjectHint: ' (focus subject {type}:{id})',
    invDetectionQuestion: 'Detect and alert: {alertType}{subjectHint}. {summary}',
    invNotifyPushed: 'Pushed to {n} channels',
    invNotifyNoChannel:
      'No matching channel: no Feishu destination is configured, or the severity is below its threshold (set it up under Notifications)',
    invNotifyFailed: 'Push failed',
    invConfirmEscalate: 'Marked as escalated. Push it to the on-call channel?',
    invReportTitle: 'Security investigation report · {alertType}',
    invFeishuDoc: 'Doc: {url}',
    invFeishuAnnounced: 'Announced to {n} Feishu groups',
    invFeishuSubmitted: 'Submitted',
    invFeishuFailed: 'Send failed',
    invErrExport: 'Export failed',
    invLikelyFp: 'Likely false positive',
    invAgenticRounds: 'Agentic',
    invRounds: '{n} rounds',
    invContextCount: '{n} context docs',
    invRagCount: '{n} runbook passages',
    invGeneratingReport: 'Generating the report…',
    invDownloaded: 'Downloaded {size}',
    invExportReport: 'Export the incident report (Markdown)',
    invDisposition: 'Disposition',
    invToDetectionRuleTitle: 'Turn a confirmed threat into a Kibana detection rule so it is caught next time',
    invToDetectionRule: 'Make a detection rule',
    invNotifyTitle: 'Push this conclusion to the configured Feishu channels',
    invNotified: 'Pushed',
    invNotify: 'Push the conclusion',
    invSecFp: 'False-positive assessment',
    invSecTimeline: 'Timeline',
    invSecKillChain: 'Kill chain',
    invColTechnique: 'Technique',
    invColEvidence: 'Evidence',
    invSecAssets: 'Affected assets',
    invSecRecommendation: 'Recommended action',
    invSecAgentic: 'Retrieval trace (agentic)',
    invStepFailed: 'failed',
    invStepHits: '{n} hits',
    invTraceOk: '{n} steps, all succeeded',
    invTraceFailed: '{n} steps, {f} failed',
    invStepArgs: 'Call arguments',
    invDegradedBody:
      'The model returned something unparseable, so a safe placeholder is shown below. Try again shortly, or with a different alert.',
    invAnalysing: 'Analysing the alert and pulling context (this can take 30–60 seconds)…',
  },
} satisfies Bundle<DialogsKey>
