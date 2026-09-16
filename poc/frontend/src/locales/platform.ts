import type { Bundle } from '@/lib/i18n'

/** 平台健康（平台体检）页。样板见 `shell.ts` 开头。 */
export type PlatformKey =
  | 'title'
  | 'descDone'
  | 'verdictOk'
  | 'verdictWarn'
  | 'verdictFail'
  | 'verdictUnknown'
  | 'overallOk'
  | 'overallWarn'
  | 'overallFail'
  | 'overallUnknown'
  | 'groupTodo'
  | 'groupOk'
  | 'groupUnknown'
  | 'errCheckup'
  | 'errInterpret'
  | 'aiRead'
  | 'aiReading'
  | 'recheck'
  | 'checking'
  | 'secOverview'
  | 'secAiRead'
  | 'secChecks'
  | 'kpiOkLabel'
  | 'kpiOk'
  | 'kpiTodoLabel'
  | 'kpiTodo'
  | 'kpiUnknownLabel'
  | 'kpiUnknown'
  | 'checkingCluster'
  | 'aiRagUsed'
  | 'aiDegraded'
  | 'aiThinking'

export const platformCopy = {
  zh: {
    title: '平台健康',
    descDone: '{overall} · 本次体检完成于 {time}',

    verdictOk: '正常',
    verdictWarn: '注意',
    verdictFail: '异常',
    verdictUnknown: '查不了',

    overallOk: '平台各项检查正常',
    overallWarn: '有需要留意的项',
    overallFail: '发现异常，建议尽快处理',
    overallUnknown: '部分检查无法完成',

    groupTodo: '需处理',
    groupOk: '通过',
    groupUnknown: '查不了',

    errCheckup: '体检失败',
    errInterpret: '解读失败',
    aiRead: 'AI 解读',
    aiReading: '解读中…',
    recheck: '重新体检',
    checking: '体检中…',

    secOverview: '体检概览',
    secAiRead: 'AI 解读',
    secChecks: '检查项明细',

    kpiOkLabel: '共 {n} 项',
    kpiOk: '通过',
    kpiTodoLabel: '异常 {fail} · 注意 {warn}',
    kpiTodo: '需处理',
    kpiUnknownLabel: '权限不足或 API 不可用',
    kpiUnknown: '查不了',

    checkingCluster: '正在检查集群…',

    aiRagUsed: '· 参考了知识库 {n} 段',
    aiDegraded: '· 模型未返回可用结果，以下按检查项本身排序',
    aiThinking: '正在把这几项串起来看…',
  },
  en: {
    title: 'Platform health',
    descDone: '{overall} · checked at {time}',

    verdictOk: 'OK',
    verdictWarn: 'Watch',
    verdictFail: 'Failing',
    verdictUnknown: 'Unavailable',

    overallOk: 'Every check passed',
    overallWarn: 'Some items need watching',
    overallFail: 'Something is failing — deal with it soon',
    overallUnknown: 'Some checks could not run',

    groupTodo: 'To do',
    groupOk: 'Passing',
    groupUnknown: 'Unavailable',

    errCheckup: 'Checkup failed',
    errInterpret: 'Could not interpret',
    aiRead: 'AI read',
    aiReading: 'Reading…',
    recheck: 'Run again',
    checking: 'Checking…',

    secOverview: 'Checkup overview',
    secAiRead: 'AI read',
    secChecks: 'Checks',

    kpiOkLabel: '{n} checks in total',
    kpiOk: 'Passing',
    kpiTodoLabel: '{fail} failing · {warn} to watch',
    kpiTodo: 'To do',
    kpiUnknownLabel: 'Insufficient permission, or the API is unavailable',
    kpiUnknown: 'Unavailable',

    checkingCluster: 'Checking the cluster…',

    aiRagUsed: '· used {n} runbook passages',
    aiDegraded: '· the model returned nothing usable; ordered by the checks themselves',
    aiThinking: 'Reading these together…',
  },
} satisfies Bundle<PlatformKey>
