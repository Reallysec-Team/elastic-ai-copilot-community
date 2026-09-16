import type { Bundle } from '@/lib/i18n'

/** AI 配置页。样板见 `shell.ts` 开头。 */
export type AiSettingsKey =
  | 'title'
  | 'secOverview'
  | 'secRouting'
  | 'secChain'
  | 'chainTitle'
  | 'chainEmpty'
  | 'chainDescOk'
  | 'chainDescFailing'
  | 'chainActive'
  | 'chainFailing'
  | 'chainLastOk'
  | 'chainNeverCalled'
  | 'actTitle'
  | 'actCalls'
  | 'actCallsUnit'
  | 'actFailed'
  | 'actAdminOnly'
  | 'actAuditOff'
  | 'actNoCalls'
  | 'secEmbedding'
  // 概览三张卡
  | 'ovLoading'
  | 'ovAvailability'
  | 'ovNoCallsYet'
  | 'ovFailingN'
  | 'ovAllOk'
  | 'ovEnabledOf'
  | 'ovFailoverChain'
  | 'ovChainLevels'
  | 'ovNoChain'
  | 'ovCalls24h'
  | 'ovAuditOff'
  | 'ovFailedN'
  | 'ovNoFailures'
  | 'ovAuditOffDesc'
  | 'ovFromAudit'
  | 'ovP95'
  | 'ovTotalFailures'
  | 'ovHasConsecutive'
  | 'ovNoConsecutive'
  | 'ovTotalDesc'
  | 'ovLastFailure'
  | 'ovNoRecord'
  // 模型路由
  | 'prSaved'
  | 'prConfirmRemove'
  | 'prTitle'
  | 'prDesc'
  | 'prReload'
  | 'prEmpty'
  | 'prAdd'
  | 'prSaving'
  | 'prSaveReload'
  | 'prUnsaved'
  | 'prDisabled'
  | 'prNoKey'
  | 'prFailing'
  | 'prOk'
  | 'prUnnamed'
  | 'prNoModel'
  | 'prNoBaseUrl'
  | 'prEnableAria'
  | 'prThisProvider'
  | 'prCollapse'
  | 'prExpand'
  | 'prRemove'
  | 'prRemoveAria'
  | 'prFieldKind'
  | 'prKindAria'
  | 'prOpenaiCompatible'
  | 'prFieldApiVersion'
  | 'prFieldDeployment'
  | 'prFieldModel'
  | 'prDeploymentPlaceholder'
  | 'prModelPlaceholder'
  | 'prKeyPasteNew'
  | 'prKeyKeep'
  | 'prKeyRequired'
  | 'prFieldTags'
  | 'prTagsPlaceholder'
  | 'prFieldTimeout'
  | 'prFieldReasoning'
  | 'prReasoningHint'
  | 'prReasoningAuto'
  | 'prReasoningOff'
  | 'prReasoningLow'
  | 'prReasoningHigh'
  | 'prLastError'
  // 向量模型
  | 'emEnabled'
  | 'emDisabled'
  | 'emMisconfigured'
  | 'emOkDims'
  | 'emErrTest'
  | 'emSavedDims'
  | 'emTitle'
  | 'emDesc'
  | 'emFieldModelId'
  | 'emRequired'
  | 'emReuseChatEndpoint'
  | 'emKeyKeep'
  | 'emKeyReuse'
  | 'emKeyKeepWithTail'
  | 'emFieldDims'
  | 'emDimsDesc'
  | 'emDimsPlaceholder'
  | 'emFieldEnable'
  | 'emDimsMismatch'
  | 'emCannotSaveYet'
  | 'emTestConnection'

export const aiSettingsCopy = {
  zh: {
    title: 'AI 配置',
    secOverview: '模型运行概览',
    secRouting: '模型路由',
    secChain: '故障转移链与调用活动',
    chainTitle: '故障转移链',
    chainEmpty: '还没有配置 provider。',
    chainDescOk: '{n} 个已启用，按顺序故障转移；全部正常。',
    chainDescFailing: '{n} 个已启用，{f} 个正在连续失败。',
    chainActive: '当前在用',
    chainFailing: '连续失败 {n} 次',
    chainLastOk: '上次成功 {when}',
    chainNeverCalled: '还没调用过',
    actTitle: '调用活动（过去 24 小时）',
    actCalls: '调用',
    actCallsUnit: '次',
    actFailed: '失败',
    actAdminOnly: '仅管理员可见',
    actAuditOff: '审计未开启',
    actNoCalls: '这段时间没有调用',
    secEmbedding: '向量与嵌入',

    ovLoading: '正在读取 provider 状态…',
    ovAvailability: '模型可用率',
    ovNoCallsYet: '本次启动后还没调用',
    ovFailingN: '{n} 个在报错',
    ovAllOk: '全部正常',
    ovEnabledOf: '{enabled} / {total} 个 provider 启用中 · 计数随网关重启清零',
    ovFailoverChain: '故障转移链路',
    ovChainLevels: '{n} 级',
    ovNoChain: '没有可用的',
    ovCalls24h: '调用量（24 小时）',
    ovAuditOff: '审计未开启',
    ovFailedN: '{n} 次失败',
    ovNoFailures: '没有失败',
    ovAuditOffDesc: '在系统设置里打开审计后才有这项',
    ovFromAudit: '按审计索引里的记录统计',
    ovP95: 'p95 耗时',
    ovTotalFailures: '累计失败',
    ovHasConsecutive: '有 provider 连续失败',
    ovNoConsecutive: '当前无连续失败',
    ovTotalDesc: '网关启动以来的累计值，不随时间窗变',
    ovLastFailure: '最近一次失败',
    ovNoRecord: '没有记录',

    prSaved: '已保存并重载',
    prConfirmRemove: '确定移除该 provider？保存后会从 yaml 中删除。',
    prTitle: '模型路由',
    prDesc: '按列表顺序故障转移',
    prReload: '重载',
    prEmpty:
      '列表为空。保存空列表会让所有 LLM 调用失败，替换 provider 的顺序是：先「新增 provider」把新的填好，再删掉旧的，最后保存。',
    prAdd: '新增 provider',
    prSaving: '保存中',
    prSaveReload: '保存并重载',
    prUnsaved: '未保存',
    prDisabled: '已停用',
    prNoKey: '缺 Key',
    prFailing: '失败 {n}',
    prOk: '正常',
    prUnnamed: '（未命名）',
    prNoModel: '未填模型',
    prNoBaseUrl: '未填 base url',
    prEnableAria: '启用 {name}',
    prThisProvider: '这个 provider',
    prCollapse: '收起设置',
    prExpand: '展开设置',
    prRemove: '移除',
    prRemoveAria: '移除 {name}',
    prFieldKind: '类型',
    prKindAria: 'provider 类型',
    prOpenaiCompatible: 'openai（含兼容网关）',
    prFieldApiVersion: 'API 版本',
    prFieldDeployment: '部署名（不是模型名）',
    prFieldModel: '模型',
    prDeploymentPlaceholder: 'deployment 名称',
    prModelPlaceholder: 'ark-code-latest 或 endpoint id',
    prKeyPasteNew: '粘贴新 key',
    prKeyKeep: '留空保留现有 key（尾 4 位 {last4}）',
    prKeyRequired: '尚未设置 key，必填',
    prFieldTags: '标签',
    prTagsPlaceholder: 'primary,cloud（逗号分隔）',
    prFieldTimeout: '超时（秒）',
    prFieldReasoning: '推理强度',
    prReasoningHint: '思考模型（豆包 / GPT-5 / Claude / Qwen3 等）先推理再作答。「自动」按任务定：起标题、想角度这类不推理，告警调查这类才推理。模型慢得难受选「关」，只要最准选「高」——覆盖所有任务。',
    prReasoningAuto: '自动（推荐）',
    prReasoningOff: '关',
    prReasoningLow: '低',
    prReasoningHigh: '高',
    prLastError: '最后一次调用失败：{err}',

    emEnabled: '知识库已启用',
    emDisabled: '未配置',
    emMisconfigured: '配置有误',
    emOkDims: '连通，维度 {dims}',
    emErrTest: '测试失败',
    emSavedDims: '已保存，维度 {dims}',
    emTitle: '知识库向量模型（Embedding）',
    emDesc: '测试连通后保存即启用知识库',
    emFieldModelId: '模型 ID',
    emRequired: '必填',
    emReuseChatEndpoint: '留空复用聊天模型端点',
    emKeyKeep: '留空保留现有 key',
    emKeyReuse: '留空复用聊天模型 key',
    emKeyKeepWithTail: '留空保留现有 key（尾 4 位 {last4}）',
    emFieldDims: '向量维度',
    emDimsDesc: '测试连接后回填',
    emDimsPlaceholder: '测试连接后自动填入',
    emFieldEnable: '启用',
    emDimsMismatch: '现有 KB 索引是 {kbDims} 维，当前模型是 {dims} 维。保存会被服务端拒绝，得先重建索引。',
    emCannotSaveYet: '测试通过前无法保存',
    emTestConnection: '测试连接',
  },
  en: {
    title: 'AI settings',
    secOverview: 'Model activity',
    secRouting: 'Model routing',
    secChain: 'Failover chain and call activity',
    chainTitle: 'Failover chain',
    chainEmpty: 'No providers configured yet.',
    chainDescOk: '{n} enabled, tried in order; all healthy.',
    chainDescFailing: '{n} enabled, {f} failing consecutively.',
    chainActive: 'In use',
    chainFailing: '{n} consecutive failures',
    chainLastOk: 'last success {when}',
    chainNeverCalled: 'never called',
    actTitle: 'Call activity (last 24 hours)',
    actCalls: 'Calls',
    actCallsUnit: 'calls',
    actFailed: 'Failed',
    actAdminOnly: 'Admins only',
    actAuditOff: 'Audit is off',
    actNoCalls: 'No calls in this window',
    secEmbedding: 'Vectors and embeddings',

    ovLoading: 'Reading provider status…',
    ovAvailability: 'Model availability',
    ovNoCallsYet: 'No calls since this start',
    ovFailingN: '{n} failing',
    ovAllOk: 'All healthy',
    ovEnabledOf: '{enabled} of {total} providers enabled · counters reset when the gateway restarts',
    ovFailoverChain: 'Failover chain',
    ovChainLevels: '{n} deep',
    ovNoChain: 'none available',
    ovCalls24h: 'Calls (24h)',
    ovAuditOff: 'Auditing is off',
    ovFailedN: '{n} failed',
    ovNoFailures: 'No failures',
    ovAuditOffDesc: 'Turn auditing on under Settings to get this figure',
    ovFromAudit: 'Counted from the audit index',
    ovP95: 'p95 latency',
    ovTotalFailures: 'Failures since start',
    ovHasConsecutive: 'A provider is failing repeatedly',
    ovNoConsecutive: 'No consecutive failures',
    ovTotalDesc: 'Cumulative since the gateway started; does not follow the time window',
    ovLastFailure: 'Last failure',
    ovNoRecord: 'no record',

    prSaved: 'Saved and reloaded',
    prConfirmRemove: 'Remove this provider? Saving deletes it from the yaml.',
    prTitle: 'Model routing',
    prDesc: 'Failover follows the list order',
    prReload: 'Reload',
    prEmpty:
      'The list is empty. Saving an empty list makes every LLM call fail. To replace a provider: add the new one first, then delete the old one, then save.',
    prAdd: 'Add a provider',
    prSaving: 'Saving',
    prSaveReload: 'Save and reload',
    prUnsaved: 'unsaved',
    prDisabled: 'disabled',
    prNoKey: 'no key',
    prFailing: '{n} failures',
    prOk: 'healthy',
    prUnnamed: '(unnamed)',
    prNoModel: 'no model',
    prNoBaseUrl: 'no base url',
    prEnableAria: 'Enable {name}',
    prThisProvider: 'this provider',
    prCollapse: 'Collapse the settings',
    prExpand: 'Expand the settings',
    prRemove: 'Remove',
    prRemoveAria: 'Remove {name}',
    prFieldKind: 'Kind',
    prKindAria: 'Provider kind',
    prOpenaiCompatible: 'openai (and compatible gateways)',
    prFieldApiVersion: 'API version',
    prFieldDeployment: 'Deployment name (not the model name)',
    prFieldModel: 'Model',
    prDeploymentPlaceholder: 'deployment name',
    prModelPlaceholder: 'ark-code-latest or an endpoint id',
    prKeyPasteNew: 'Paste a new key',
    prKeyKeep: 'Leave empty to keep the current key (ending {last4})',
    prKeyRequired: 'No key set yet — required',
    prFieldTags: 'Tags',
    prTagsPlaceholder: 'primary,cloud (comma-separated)',
    prFieldTimeout: 'Timeout (seconds)',
    prFieldReasoning: 'Reasoning',
    prReasoningHint: 'Reasoning models (Doubao / GPT-5 / Claude / Qwen3 …) think before answering. "Auto" decides per task: no thinking for titles or angle suggestions, thinking for alert investigation. Pick "Off" if the model is painfully slow, "High" if accuracy is all that matters — either overrides every task.',
    prReasoningAuto: 'Auto (recommended)',
    prReasoningOff: 'Off',
    prReasoningLow: 'Low',
    prReasoningHigh: 'High',
    prLastError: 'Last call failed: {err}',

    emEnabled: 'Runbooks enabled',
    emDisabled: 'Not configured',
    emMisconfigured: 'Misconfigured',
    emOkDims: 'Reachable, {dims} dimensions',
    emErrTest: 'Test failed',
    emSavedDims: 'Saved, {dims} dimensions',
    emTitle: 'Runbook embedding model',
    emDesc: 'Test the connection, then save to enable runbooks',
    emFieldModelId: 'Model ID',
    emRequired: 'Required',
    emReuseChatEndpoint: 'Leave empty to reuse the chat model endpoint',
    emKeyKeep: 'Leave empty to keep the current key',
    emKeyReuse: 'Leave empty to reuse the chat model key',
    emKeyKeepWithTail: 'Leave empty to keep the current key (ending {last4})',
    emFieldDims: 'Vector dimensions',
    emDimsDesc: 'Filled in after a connection test',
    emDimsPlaceholder: 'Filled in automatically after the test',
    emFieldEnable: 'Enable',
    emDimsMismatch:
      'The existing KB index is {kbDims}-dimensional and this model is {dims}. The server would refuse the save — rebuild the index first.',
    emCannotSaveYet: 'Cannot save until the test passes',
    emTestConnection: 'Test connection',
  },
} satisfies Bundle<AiSettingsKey>
