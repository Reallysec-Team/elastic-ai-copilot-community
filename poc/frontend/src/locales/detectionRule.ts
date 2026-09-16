import type { Bundle } from '@/lib/i18n'

/** 检测规则页。样板见 `shell.ts` 开头。 */
export type DetectionRuleKey =
  | 'title'
  | 'handoffNote'
  | 'errGenerate'
  | 'okSaved'
  | 'errSave'
  | 'secIntent'
  | 'secResult'
  | 'cardIntentTitle'
  | 'fieldIndex'
  | 'fieldIntent'
  | 'intentPlaceholder'
  | 'fieldRuleType'
  | 'ruleTypeAuto'
  | 'generate'
  | 'generating'
  | 'examples'
  | 'ex1'
  | 'ex1q'
  | 'ex2'
  | 'ex2q'
  | 'ex3'
  | 'ex3q'
  | 'savedRules'
  | 'errLoadSaved'
  | 'errDeleteSaved'
  | 'confirmDelete'
  | 'loadFailed'
  | 'noSavedRules'
  | 'untitled'
  | 'cardRuleTitle'
  | 'confidence'
  | 'ragUsed'
  | 'labelTags'
  | 'labelEql'
  | 'labelKql'
  | 'labelThreshold'
  | 'showFullJson'
  | 'copyJson'
  | 'exportNdjson'
  | 'exportNdjsonTitle'
  | 'saveRule'
  | 'saveRuleTitle'
  | 'showDeploySteps'
  | 'step1'
  | 'step2'
  | 'step3Strong'
  | 'step3Rest'
  | 'step4'
  | 'enabledTitle'
  | 'refusalTitle'
  | 'suggestLabel'
  | 'suggestBody'

export const detectionRuleCopy = {
  zh: {
    title: '检测规则',
    handoffNote: '已带入查询意图，可按需调整。',
    errGenerate: '生成失败',
    okSaved: '已存入规则库 · 全队可见',
    errSave: '保存失败',
    secIntent: '检测意图',
    secResult: '生成结果',
    cardIntentTitle: '描述检测意图',
    fieldIndex: '索引',
    fieldIntent: '检测意图',
    intentPlaceholder: '例如：当同一 source.ip 在 5 分钟内登录失败 ≥ 5 次时告警',
    fieldRuleType: '规则类型',
    ruleTypeAuto: '规则类型：自动',
    generate: '生成规则',
    generating: '生成中…',
    examples: '示例',
    ex1: '登录失败超过 5 次的源 IP，5 分钟内',
    ex1q: '当同一 source.ip 在 5 分钟内 event.action="login_failure" 出现 ≥ 5 次时告警',
    ex2: '检测 user_agent 包含 sqlmap 或 nikto 的请求',
    ex2q: '检测 user_agent 包含 sqlmap 或 nikto 等扫描器关键字的 HTTP 请求',
    ex3: '进程创建后 10 秒内出现外联连接的序列',
    ex3q: '当 host 上 process.start 之后 10 秒内出现 network.connection 外联事件，按 host.id 关联',
    savedRules: '已生成规则',
    errLoadSaved: '加载失败',
    errDeleteSaved: '删除失败',
    confirmDelete: '删除已保存的规则「{name}」？此操作不可撤销。',
    loadFailed: '加载失败：{err}',
    noSavedRules: '还没有保存的规则',
    untitled: '(未命名)',
    cardRuleTitle: '生成的检测规则',
    confidence: '置信度 {level}',
    ragUsed: '参考了 {n} 篇知识库文档',
    labelTags: '标签',
    labelEql: 'EQL 查询',
    labelKql: 'KQL 查询',
    labelThreshold: '阈值',
    showFullJson: '查看完整规则 JSON',
    copyJson: '复制 JSON',
    exportNdjson: '导出 .ndjson',
    exportNdjsonTitle: '导出为 Kibana 规则导入格式 (.ndjson)，在 Security → Rules → Import 导入',
    saveRule: '存为规则',
    saveRuleTitle: '存入团队规则库，稍后可加载回填或再次导出',
    showDeploySteps: '查看在 Kibana 部署的步骤',
    step1: '进入 Kibana → Security → Rules → Create rule',
    step2: '选择对应类型，粘贴 query/threshold 配置',
    step3Strong: '保留 enabled=false',
    step3Rest: '，先在 Detection Engine 模拟运行',
    step4: '验证误报率后再 enable',
    enabledTitle: '运维 review 后再手动启用',
    refusalTitle: '模型选择拒答',
    suggestLabel: '建议：',
    suggestBody:
      '重新组织问题，明确触发条件、时间窗与字段名（例如 source.ip / event.action），或用上方示例作为模板。',
  },
  en: {
    title: 'Detection rules',
    handoffNote: 'Carried the query intent over — adjust it as needed.',
    errGenerate: 'Generation failed',
    okSaved: 'Saved to the rule library · visible to the whole team',
    errSave: 'Save failed',
    secIntent: 'Detection intent',
    secResult: 'Generated rule',
    cardIntentTitle: 'Describe the detection',
    fieldIndex: 'Index',
    fieldIntent: 'Detection intent',
    intentPlaceholder:
      'For example: alert when one source.ip fails to log in 5 or more times within 5 minutes',
    fieldRuleType: 'Rule type',
    ruleTypeAuto: 'Rule type: auto',
    generate: 'Generate rule',
    generating: 'Generating…',
    examples: 'Examples',
    ex1: 'Source IPs with more than 5 failed logins in 5 minutes',
    ex1q: 'Alert when the same source.ip produces 5 or more event.action="login_failure" within 5 minutes',
    ex2: 'Requests whose user_agent contains sqlmap or nikto',
    ex2q: 'Detect HTTP requests whose user_agent contains scanner keywords such as sqlmap or nikto',
    ex3: 'An outbound connection within 10 seconds of a process start',
    ex3q: 'Alert when a host sees a network.connection outbound event within 10 seconds of process.start, correlated by host.id',
    savedRules: 'Saved rules',
    errLoadSaved: 'Could not load',
    errDeleteSaved: 'Could not delete',
    confirmDelete: 'Delete the saved rule "{name}"? This cannot be undone.',
    loadFailed: 'Could not load: {err}',
    noSavedRules: 'No saved rules yet',
    untitled: '(untitled)',
    cardRuleTitle: 'Generated detection rule',
    confidence: 'Confidence: {level}',
    ragUsed: 'Used {n} runbook documents as reference',
    labelTags: 'Tags',
    labelEql: 'EQL query',
    labelKql: 'KQL query',
    labelThreshold: 'Threshold',
    showFullJson: 'Show the full rule JSON',
    copyJson: 'Copy JSON',
    exportNdjson: 'Export .ndjson',
    exportNdjsonTitle:
      "Export in Kibana's rule-import format (.ndjson); import under Security → Rules → Import",
    saveRule: 'Save rule',
    saveRuleTitle: 'Save to the team rule library to reload or re-export later',
    showDeploySteps: 'How to deploy this in Kibana',
    step1: 'Go to Kibana → Security → Rules → Create rule',
    step2: 'Pick the matching type and paste the query/threshold configuration',
    step3Strong: 'Keep enabled=false',
    step3Rest: ' and let it run in the Detection Engine first',
    step4: 'Enable it once the false-positive rate checks out',
    enabledTitle: 'Enable it by hand after an ops review',
    refusalTitle: 'The model declined to answer',
    suggestLabel: 'Suggestion: ',
    suggestBody:
      'Rewrite the request with an explicit trigger condition, time window and field names (source.ip / event.action, say) — or start from one of the examples above.',
  },
} satisfies Bundle<DetectionRuleKey>
