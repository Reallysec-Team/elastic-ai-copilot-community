import type { Bundle } from '@/lib/i18n'

/** 基线巡检页。判定名（通过 / 不合规 / …）不在这里，它在 `common.ts` —— 表格、
    环图、筛选下拉三处共用，见 `components/baseline/verdictStyle.ts`。 */
export type BaselineKey =
  | 'title'
  | 'runNow'
  | 'running'
  | 'errLoad'
  | 'errRun'
  | 'tabResults'
  | 'tabRules'
  | 'tabRuns'
  | 'fieldMapCheck'
  | 'fieldMapHost'
  | 'fieldMapRuleKey'
  | 'fieldMapPrefix'
  | 'fieldMapSource'
  | 'fieldMapLowConfidence'
  | 'secSummary'
  | 'secTrend'
  | 'trendTitle'
  | 'unitScore'
  | 'trendEmpty'
  | 'verdictMix'
  | 'unitResults'
  | 'verdictMixEmpty'
  | 'secFilter'
  | 'filterByVerdict'
  | 'verdictAll'
  | 'countHostsResults'
  | 'secResults'
  | 'secHostScores'
  | 'hostScoresTitle'
  | 'hostScoresDesc'
  | 'hostScoreMeta'
  | 'notScored'
  | 'kpiScoreLabel'
  | 'kpiScore'
  | 'kpiPassLabel'
  | 'kpiPass'
  | 'kpiFailLabel'
  | 'kpiFail'
  | 'kpiOtherLabel'
  | 'kpiOther'
  | 'onboardIntro'
  | 'onboardShow'
  | 'onboardHide'
  | 'onboardStep1'
  | 'onboardStep1Body'
  | 'onboardStep2'
  | 'onboardStep2Body'
  | 'onboardStep3'
  | 'onboardStep3Body'
  | 'onboardStep4'
  | 'onboardStep4Body'
  | 'onboardStep5'
  | 'onboardStep5Body'
  | 'onboardHint'
  // 结果表
  | 'colHost'
  | 'colRule'
  | 'colCategory'
  | 'colSeverity'
  | 'colVerdict'
  | 'colActual'
  | 'fieldExpected'
  | 'fieldActual'
  | 'fieldRemediation'
  | 'fieldStandardRefs'
  // 规则库
  | 'errLoadRules'
  | 'errDelete'
  | 'rulesCountFiltered'
  | 'rulesCountAll'
  | 'rulesFilterPlaceholder'
  | 'rulesFilterAria'
  | 'newRule'
  | 'colRuleId'
  | 'colTitle'
  | 'colPlatform'
  | 'colJudgeOp'
  | 'colEnabled'
  | 'colSource'
  | 'colActions'
  | 'ruleEnabled'
  | 'ruleDisabled'
  | 'srcCustom'
  | 'srcBuiltin'
  | 'confirmDelete'
  | 'rulesEmpty'
  | 'errRuleIdRequired'
  | 'errTitleRequired'
  | 'errNeedsField'
  | 'errNeedsExpected'
  | 'errNeedsQuery'
  | 'errSave'
  | 'dlgCreateRule'
  | 'dlgEditRule'
  | 'fieldRuleId'
  | 'fieldTitle'
  | 'fieldPlatform'
  | 'fieldJudgeOp'
  | 'fieldJudgeField'
  | 'fieldExpectedInput'
  | 'fieldOnMissing'
  | 'fieldCollectQuery'
  | 'fieldRemediationTpl'
  | 'fieldStandardRefsInput'
  | 'enableThisRule'
  | 'titlePlaceholder'
  | 'remediationPlaceholder'
  | 'standardRefsPlaceholder'
  // 历史轮次
  | 'errLoadRuns'
  | 'errLoadResults'
  | 'backToRuns'
  | 'runSummary'
  | 'colFinishedAt'
  | 'colRunId'
  | 'colScore'
  | 'colPassFail'
  | 'colHostsRules'
  | 'runsEmpty'

export const baselineCopy = {
  zh: {
    title: '基线巡检',
    runNow: '立即巡检',
    running: '巡检中…',
    errLoad: '加载失败',
    errRun: '巡检失败',
    tabResults: '巡检结果',
    tabRules: '规则库',
    tabRuns: '历史轮次',

    fieldMapCheck: 'osquery 字段自检',
    fieldMapHost: '主机',
    fieldMapRuleKey: '规则键',
    fieldMapPrefix: '列前缀',
    fieldMapSource: '来源',
    fieldMapLowConfidence: '低置信度，建议核对或用 RST_BASELINE_* 覆盖',

    secSummary: '本轮概览',
    secTrend: '评分趋势与判定分布',
    trendTitle: '历次合规评分',
    unitScore: '分',
    trendEmpty: '只有这一轮，再巡检一次就有趋势了',
    verdictMix: '判定分布',
    unitResults: '条',
    verdictMixEmpty: '这一轮没有判定结果',

    secFilter: '结果筛选',
    filterByVerdict: '按判定筛选',
    verdictAll: '判定：全部',
    countHostsResults: '{hosts} 台主机 · {results} 条结果',
    secResults: '巡检结果',
    secHostScores: '单机合规评分',
    hostScoresTitle: '单机合规评分',
    hostScoresDesc: '分母只算通过和不合规',
    hostScoreMeta: '通过 {pass} · 不合规 {fail}',
    notScored: '未评估',

    kpiScoreLabel: '{hosts} 台主机 × {rules} 条规则',
    kpiScore: '合规评分',
    kpiPassLabel: '共 {n} 条可判定',
    kpiPass: '通过',
    kpiFailLabel: '需要改配置',
    kpiFail: '不合规',
    kpiOtherLabel: '都不计入评分',
    kpiOther: '待人工 / 异常',

    onboardIntro: '尚无巡检记录。基线巡检读的是主机 osquery 的采集结果，要先让这些数据进入 Elasticsearch；只有规则库不会产生任何结果。',
    onboardShow: '查看接入步骤',
    onboardHide: '收起接入步骤',
    onboardStep1: '1 · 建索引',
    onboardStep1Body: '，创建规则 / 结果 / 轮次三索引。',
    onboardStep2: '2 · 导规则',
    onboardStep2Body: ' 导入内置规则库（右上「规则库」tab 可查看 / 增改）。',
    onboardStep3: '3 · 部署 osquery',
    onboardStep3Body:
      '在目标主机装 osquery，把「规则库」里的查询作为 pack 定时执行；用 Fleet / Filebeat / Logstash 把结果写入 ES 的 osquery 结果索引。',
    onboardStep4: '4 · 核对字段映射',
    onboardStep4Body:
      'osquery 结果的主机字段 / 规则键 / 列前缀需与上方「osquery 字段自检」一致；不一致用 RST_BASELINE_* 环境变量覆盖。',
    onboardStep5: '5 · 巡检',
    onboardStep5Body: '数据就位后回到本页点「立即巡检」，即按规则逐主机判定合规。',
    onboardHint: '提示：客户自带 ELK 环境时，索引名 / 字段前缀常与默认不同，务必核对第 4 步。',

    colHost: '主机',
    colRule: '规则',
    colCategory: '类别',
    colSeverity: '严重度',
    colVerdict: '判定',
    colActual: '实际观测',
    fieldExpected: '期望值',
    fieldActual: '实际观测',
    fieldRemediation: '整改建议',
    fieldStandardRefs: '标准引用：',

    errLoadRules: '加载规则库失败',
    errDelete: '删除失败',
    rulesCountFiltered: '{shown} / {total} 条规则',
    rulesCountAll: '共 {n} 条规则',
    rulesFilterPlaceholder: '按 ID、标题、类别过滤',
    rulesFilterAria: '过滤规则',
    newRule: '新建规则',
    colRuleId: '规则 ID',
    colTitle: '标题',
    colPlatform: '平台',
    colJudgeOp: '判定算子',
    colEnabled: '启用',
    colSource: '来源',
    colActions: '操作',
    ruleEnabled: '启用',
    ruleDisabled: '停用',
    srcCustom: '自定义',
    srcBuiltin: '内置',
    confirmDelete: '确认删除？',
    rulesEmpty: '规则库为空。点「新建规则」添加第一条。',
    errRuleIdRequired: '请填写规则 ID',
    errTitleRequired: '请填写标题',
    errNeedsField: '算子 {op} 需要 judge.field',
    errNeedsExpected: '算子 {op} 需要 judge.expected',
    errNeedsQuery: '算子 {op} 需要 collect.query',
    errSave: '保存失败',
    dlgCreateRule: '新建规则',
    dlgEditRule: '编辑规则',
    fieldRuleId: '规则 ID（3-64 字符 [A-Za-z0-9._-]）',
    fieldTitle: '标题',
    fieldPlatform: '平台（linux / windows / 留空=通用）',
    fieldJudgeOp: '判定算子',
    fieldJudgeField: '判定字段（judge.field）',
    fieldExpectedInput: '期望值（judge.expected）',
    fieldOnMissing: '字段缺失时判定（judge.on_missing）',
    fieldCollectQuery: '采集查询（osquery SQL）',
    fieldRemediationTpl: '整改模板',
    fieldStandardRefsInput: '标准引用（逗号分隔）',
    enableThisRule: '启用该规则',
    titlePlaceholder: '禁止 root 直接 SSH 登录',
    remediationPlaceholder: '编辑 /etc/ssh/sshd_config，设置 PermitRootLogin no',
    standardRefsPlaceholder: '等保2.0-8.1.4.2, CIS-5.4.1',

    errLoadRuns: '加载历史轮次失败',
    errLoadResults: '加载结果失败',
    backToRuns: '返回轮次列表',
    runSummary: '评分 {score} · 通过 {pass} · 不合规 {fail} · {results} 条结果',
    colFinishedAt: '完成时间',
    colRunId: '轮次 ID',
    colScore: '评分',
    colPassFail: '通过 / 不合规',
    colHostsRules: '主机 × 规则',
    runsEmpty: '尚无历史轮次。',
  },
  en: {
    title: 'Baseline checks',
    runNow: 'Run now',
    running: 'Running…',
    errLoad: 'Could not load',
    errRun: 'Run failed',
    tabResults: 'Results',
    tabRules: 'Rules',
    tabRuns: 'History',

    fieldMapCheck: 'osquery field check',
    fieldMapHost: 'host',
    fieldMapRuleKey: 'rule key',
    fieldMapPrefix: 'column prefix',
    fieldMapSource: 'source',
    fieldMapLowConfidence: ' · low confidence — verify it, or override with RST_BASELINE_*',

    secSummary: 'This run',
    secTrend: 'Score trend and verdict mix',
    trendTitle: 'Compliance score over time',
    unitScore: 'points',
    trendEmpty: 'Only one run so far — run it again for a trend',
    verdictMix: 'Verdict mix',
    unitResults: 'results',
    verdictMixEmpty: 'This run produced no verdicts',

    secFilter: 'Filter results',
    filterByVerdict: 'Filter by verdict',
    verdictAll: 'Verdict: all',
    countHostsResults: '{hosts} hosts · {results} results',
    secResults: 'Results',
    secHostScores: 'Per-host compliance',
    hostScoresTitle: 'Per-host compliance',
    hostScoresDesc: 'Only pass and fail count toward the denominator',
    hostScoreMeta: '{pass} pass · {fail} fail',
    notScored: 'Not scored',

    kpiScoreLabel: '{hosts} hosts × {rules} rules',
    kpiScore: 'Compliance score',
    kpiPassLabel: '{n} decidable results',
    kpiPass: 'Pass',
    kpiFailLabel: 'Configuration needs changing',
    kpiFail: 'Fail',
    kpiOtherLabel: 'Neither counts toward the score',
    kpiOther: 'Manual review / error',

    onboardIntro:
      'No runs yet. A baseline run reads osquery collection results, so those have to reach '
      + 'Elasticsearch first; the rule library on its own produces nothing.',
    onboardShow: 'Show the setup steps',
    onboardHide: 'Hide the setup steps',
    onboardStep1: '1 · Create the indices',
    onboardStep1Body: ' to create the rules / results / runs indices.',
    onboardStep2: '2 · Load the rules',
    onboardStep2Body: ' to import the built-in rule library (view and edit it under the Rules tab).',
    onboardStep3: '3 · Deploy osquery',
    onboardStep3Body:
      'Install osquery on the target hosts and schedule the queries from the rule library as a pack; ship the results into the osquery results index with Fleet / Filebeat / Logstash.',
    onboardStep4: '4 · Check the field mapping',
    onboardStep4Body:
      "The host field, rule key and column prefix in the osquery results have to match the field check above; override them with RST_BASELINE_* environment variables if they don't.",
    onboardStep5: '5 · Run it',
    onboardStep5Body: 'With the data in place, come back here and press Run now.',
    onboardHint:
      'Note: when the customer brings their own ELK, index names and field prefixes usually differ from the defaults — check step 4.',

    colHost: 'Host',
    colRule: 'Rule',
    colCategory: 'Category',
    colSeverity: 'Severity',
    colVerdict: 'Verdict',
    colActual: 'Observed',
    fieldExpected: 'Expected',
    fieldActual: 'Observed',
    fieldRemediation: 'Remediation',
    fieldStandardRefs: 'Standards: ',

    errLoadRules: 'Could not load the rule library',
    errDelete: 'Delete failed',
    rulesCountFiltered: '{shown} / {total} rules',
    rulesCountAll: '{n} rules',
    rulesFilterPlaceholder: 'Filter by ID, title or category',
    rulesFilterAria: 'Filter rules',
    newRule: 'New rule',
    colRuleId: 'Rule ID',
    colTitle: 'Title',
    colPlatform: 'Platform',
    colJudgeOp: 'Judge operator',
    colEnabled: 'Enabled',
    colSource: 'Source',
    colActions: 'Actions',
    ruleEnabled: 'on',
    ruleDisabled: 'off',
    srcCustom: 'custom',
    srcBuiltin: 'built-in',
    confirmDelete: 'Delete?',
    rulesEmpty: 'The rule library is empty. Add the first rule with New rule.',
    errRuleIdRequired: 'Enter a rule ID',
    errTitleRequired: 'Enter a title',
    errNeedsField: 'Operator {op} needs judge.field',
    errNeedsExpected: 'Operator {op} needs judge.expected',
    errNeedsQuery: 'Operator {op} needs collect.query',
    errSave: 'Save failed',
    dlgCreateRule: 'New rule',
    dlgEditRule: 'Edit rule',
    fieldRuleId: 'Rule ID (3–64 chars, [A-Za-z0-9._-])',
    fieldTitle: 'Title',
    fieldPlatform: 'Platform (linux / windows / empty = any)',
    fieldJudgeOp: 'Judge operator',
    fieldJudgeField: 'Judged field (judge.field)',
    fieldExpectedInput: 'Expected value (judge.expected)',
    fieldOnMissing: 'Verdict when the field is missing (judge.on_missing)',
    fieldCollectQuery: 'Collection query (osquery SQL)',
    fieldRemediationTpl: 'Remediation template',
    fieldStandardRefsInput: 'Standard references (comma-separated)',
    enableThisRule: 'Enable this rule',
    titlePlaceholder: 'Disallow direct root SSH login',
    remediationPlaceholder: 'Edit /etc/ssh/sshd_config and set PermitRootLogin no',
    standardRefsPlaceholder: 'CIS-5.4.1, ISO27001-A.9.2.3',

    errLoadRuns: 'Could not load the run history',
    errLoadResults: 'Could not load the results',
    backToRuns: 'Back to the run list',
    runSummary: 'Score {score} · {pass} pass · {fail} fail · {results} results',
    colFinishedAt: 'Finished',
    colRunId: 'Run ID',
    colScore: 'Score',
    colPassFail: 'Pass / fail',
    colHostsRules: 'Hosts × rules',
    runsEmpty: 'No runs yet.',
  },
} satisfies Bundle<BaselineKey>
