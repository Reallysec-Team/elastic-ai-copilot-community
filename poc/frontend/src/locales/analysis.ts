import type { Bundle } from '@/lib/i18n'

/** 分析记录页。样板见 `shell.ts` 开头。 */
export type AnalysisKey =
  | 'title'
  | 'kindAll'
  | 'kindInvestigation'
  | 'kindTriage'
  | 'kindResultExplain'
  | 'secFilter'
  | 'searchPlaceholder'
  | 'searchAria'
  | 'countMatched'
  | 'countTotal'
  | 'emptyFilteredTitle'
  | 'emptyFilteredDesc'
  | 'emptyTitle'
  | 'emptyDesc'
  | 'secList'
  | 'loadMore'
  | 'detailTriage'
  | 'detailInvestigation'
  | 'detailFallbackTitle'
  | 'askAboutSubject'

export const analysisCopy = {
  zh: {
    title: '分析记录',
    kindAll: '全部',
    kindInvestigation: '调查',
    kindTriage: '分诊',
    kindResultExplain: '结果解读',
    secFilter: '筛选与搜索',
    searchPlaceholder: '搜索标题与摘要…',
    searchAria: '搜索分析记录',
    countMatched: '匹配 {n} 条',
    countTotal: '共 {n} 条分析记录',
    emptyFilteredTitle: '没有匹配的记录',
    emptyFilteredDesc: '换个关键词，或把分类切回「全部」。',
    emptyTitle: '暂无分析记录',
    emptyDesc: '跑一次事件调查或告警分诊后出现。',
    secList: '记录列表',
    loadMore: '加载更多（还有 {n} 条）',
    detailTriage: '告警分诊',
    detailInvestigation: '告警调查',
    detailFallbackTitle: '分析记录',
    askAboutSubject: '查这个主体',
  },
  en: {
    title: 'Investigations',
    kindAll: 'All',
    kindInvestigation: 'Investigation',
    kindTriage: 'Triage',
    kindResultExplain: 'Result readout',
    secFilter: 'Filter and search',
    searchPlaceholder: 'Search titles and summaries…',
    searchAria: 'Search investigations',
    countMatched: '{n} matching',
    countTotal: '{n} records',
    emptyFilteredTitle: 'Nothing matches',
    emptyFilteredDesc: 'Try another term, or switch the category back to "All".',
    emptyTitle: 'No records yet',
    emptyDesc: 'One appears after you run an investigation or an alert triage.',
    secList: 'Records',
    loadMore: 'Load more ({n} left)',
    detailTriage: 'Alert triage',
    detailInvestigation: 'Alert investigation',
    detailFallbackTitle: 'Record',
    askAboutSubject: 'Ask about this subject',
  },
} satisfies Bundle<AnalysisKey>
