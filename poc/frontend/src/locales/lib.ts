import type { Bundle } from '@/lib/i18n'

/*
 * `src/lib/*` 里那些会直接显示给人看的字符串：ES 报错的人话解释、放宽条件时
 * 生成的条件描述、断流兜底、admin token 的输入提示。
 *
 * 它们不属于任何一个页面 —— 同一句 ES 报错解释在智能查询、批量分诊、深入调查
 * 三处都会冒出来。
 */
export type LibKey =
  // errorHelp：ES / 网关报错的人话解释
  // 杂项：查询范围标签、剪贴板、执行开销、通用失败/保存提示
  | 'scopeAllLogs'
  | 'clipboardUnavailable'
  | 'outputChars'
  | 'loadFailed'
  | 'settingsSavedReloaded'
  | 'errTextFielddata'
  | 'errParsing'
  | 'errIndexNotFound'
  | 'errSearchPhase'
  | 'errIllegalArgument'
  | 'errTooManyClauses'
  | 'errReadOnly'
  | 'errRateLimited'
  | 'errTimeout'
  | 'errLicense'
  | 'errUnreachable'
  // relaxQuery：条件描述
  | 'rqAnd'
  | 'rqRangeCondition'
  | 'rqOneCondition'
  | 'rqContains'
  | 'rqFieldExists'
  | 'rqMatches'
  | 'rqFullText'
  | 'rqCombined'
  | 'rqUseInstead'
  | 'rqDropClause'
  // analysisFollowUp
  | 'afSubjectQuestion'
  // streamingClient
  | 'scBrokenGenerate'
  | 'scBrokenInvestigate'
  // api：admin token 提示
  | 'adminTokenPrompt'
  // auditFilters
  | 'afNeedOneBound'
  | 'afStartAfterEnd'

export const libCopy = {
  zh: {
    scopeAllLogs: '全部日志 · {n} 个索引',
    clipboardUnavailable: '当前环境不支持剪贴板（需要 HTTPS 或 localhost）。请改用导出。',
    outputChars: '{n} 字符',
    loadFailed: '读取失败',
    settingsSavedReloaded: '已保存 · 模块已自动重载',
    errTextFielddata: '对 text 字段做了聚合/排序。改用它的 .keyword 子字段（如 `request.keyword`）。',
    errParsing: 'DSL 结构有误（常见：括号不配对、字段名拼错、聚合层级不对）。可点「让 AI 带着报错重修」。',
    errIndexNotFound: '索引不存在。检查索引名或通配符是否写对、数据是否已写入。',
    errSearchPhase: '查询执行阶段失败（常见：排序/聚合用了非 keyword 的 text 字段，或字段类型不匹配）。',
    errIllegalArgument: '参数不合法（常见：字段类型与操作不匹配）。检查字段类型，或让 AI 带着报错重修。',
    errTooManyClauses: '查询条款过多。缩小通配范围或拆分条件。',
    errReadOnly: '只读校验未通过（可能用了 script / runtime field / 写操作）。本产品只允许只读查询。',
    errRateLimited: '触发限流或配额上限。稍后重试，或在「产品激活」页查看 / 提升配额。',
    errTimeout: '请求超时。可能是 ES 负载高或查询太重，缩小时间窗 / size 后重试。',
    errLicense: 'license / 授权问题。去「产品激活」页检查授权状态。',
    errUnreachable: '网关或后端不可达。确认服务在运行、网络可达后重试。',

    rqAnd: ' 且 ',
    rqRangeCondition: '范围条件',
    rqOneCondition: '一个条件',
    rqContains: '{field} 里包含 {value}',
    rqFieldExists: '存在字段 {field}',
    rqMatches: '{field} 匹配 {value}',
    rqFullText: '全文查询 {value}',
    rqCombined: '一组组合条件',
    rqUseInstead: '{field} 改用 {alt}',
    rqDropClause: '去掉「{clause}」',

    afSubjectQuestion: '最近 24 小时与 {value} 有关的日志',

    scBrokenGenerate: '连接中断，未收到生成结果。请重试。',
    scBrokenInvestigate: '连接中断，未收到调查结果。请重试。',

    adminTokenPrompt:
      '管理操作需要 RST_ADMIN_TOKEN。\n\n请粘贴 token（部署机器的 .env 文件里 RST_ADMIN_TOKEN= 那一行）。\nToken 只留在这个标签页的内存里，本次会话内的 admin 操作会自动复用；刷新页面要重输一次。',

    afNeedOneBound: '自定义时间范围：请至少填写开始或结束时间。',
    afStartAfterEnd: '自定义时间范围：开始时间不能晚于结束时间。',
  },
  en: {
    scopeAllLogs: 'All logs · {n} indices',
    clipboardUnavailable: 'The clipboard is unavailable here (needs HTTPS or localhost). Use export instead.',
    outputChars: '{n} chars',
    loadFailed: 'Could not load',
    settingsSavedReloaded: 'Saved · the module reloaded itself',
    errTextFielddata:
      'You aggregated or sorted on a text field. Use its .keyword sub-field instead (for example `request.keyword`).',
    errParsing:
      'The DSL is malformed (usually unbalanced brackets, a misspelled field, or a wrong aggregation nesting). Try "Let the AI fix it with the error".',
    errIndexNotFound:
      'No such index. Check the index name or wildcard, and whether any data has been written yet.',
    errSearchPhase:
      'The search phase failed (usually sorting or aggregating on a text field rather than a keyword one, or a field-type mismatch).',
    errIllegalArgument:
      'Invalid argument (usually the field type does not support the operation). Check the field type, or let the AI fix it with the error.',
    errTooManyClauses: 'Too many clauses. Narrow the wildcard or split the conditions.',
    errReadOnly:
      'The read-only check failed (a script, runtime field or write operation). This product only allows read-only queries.',
    errRateLimited: 'Rate limit or quota reached. Retry shortly, or check and raise the quota on the License page.',
    errTimeout:
      'The request timed out. Elasticsearch may be loaded, or the query is heavy — narrow the window or size and retry.',
    errLicense: 'A license problem. Check the activation status on the License page.',
    errUnreachable: 'The gateway or backend is unreachable. Make sure it is running and retry.',

    rqAnd: ' and ',
    rqRangeCondition: 'a range condition',
    rqOneCondition: 'one condition',
    rqContains: '{field} contains {value}',
    rqFieldExists: '{field} exists',
    rqMatches: '{field} matches {value}',
    rqFullText: 'full-text query {value}',
    rqCombined: 'a group of conditions',
    rqUseInstead: '{field} → {alt}',
    rqDropClause: 'Drop "{clause}"',

    afSubjectQuestion: 'Logs involving {value} in the last 24 hours',

    scBrokenGenerate: 'The connection dropped before a result arrived. Try again.',
    scBrokenInvestigate: 'The connection dropped before the investigation finished. Try again.',

    adminTokenPrompt:
      'Administrative actions need RST_ADMIN_TOKEN.\n\nPaste the token (the RST_ADMIN_TOKEN= line in the .env on the deployment host).\nIt is held in this tab’s memory only and reused for the rest of the session; a page reload asks again.',

    afNeedOneBound: 'Custom range: fill in at least a start or an end.',
    afStartAfterEnd: 'Custom range: the start cannot be later than the end.',
  },
} satisfies Bundle<LibKey>
