/*
 * ReUI Filters 的中文文案。组件自带的是英文默认值（filters-i18n / filters-operators），
 * 通过 `labels` 和每个字段的 `operators` 注入 —— 不改组件文件，升级时不会被覆盖。
 *
 * 只译界面上会出现的那一层（基础模式）；高级模式（分组、拖拽）这个产品没开。
 */
import type { FilterLabels } from '@/components/reui/filters/filters-types'
import {
  DEFAULT_FILTER_OPERATOR_LABELS, createFilterOperators,
} from '@/components/reui/filters/filters-operators'
import type { FilterOperator, FilterValueType } from '@/components/reui/filters/filters-types'
import type { Lang } from '@/lib/i18n'

const ZH_LABELS: Partial<FilterLabels> = {
  addFilter: '添加条件',
  clearAll: '全部清除',
  searchFields: '搜索字段…',
  searchOperators: '搜索条件…',
  searchOptions: '搜索…',
  back: '返回',
  clear: '清除',
  apply: '应用',
  discard: '放弃修改',
  empty: '没有结果',
  loading: '加载中…',
  where: '当',
  and: '且',
  or: '或',
  negate: '取反',
  remove: '移除',
  duplicate: '复制',
  filtersLabel: '筛选',
  valuePlaceholder: '输入…',
  selectPlaceholder: '选择…',
  noValue: '未填',
  selectCondition: '选择条件',
  incomplete: '条件未填完',
}

const ZH_OPERATORS = createFilterOperators({
  ...DEFAULT_FILTER_OPERATOR_LABELS,
  contains: '包含',
  not_contains: '不包含',
  starts_with: '开头是',
  ends_with: '结尾是',
  is: '是',
  is_not: '不是',
  is_any_of: '是其中之一',
  is_none_of: '都不是',
  eq: '等于',
  neq: '不等于',
  gt: '大于',
  gte: '大于等于',
  lt: '小于',
  lte: '小于等于',
  between: '介于',
  not_between: '不介于',
  is_before: '早于',
  is_after: '晚于',
  empty: '为空',
  not_empty: '不为空',
})

const EN_OPERATORS = createFilterOperators(DEFAULT_FILTER_OPERATOR_LABELS)

export function filterLabelsFor(lang: Lang): Partial<FilterLabels> | undefined {
  return lang === 'zh' ? ZH_LABELS : undefined
}

/** 某种字段类型在这个语言下的运算符表；`only` 限定到这几个（简单页面用不上 27 个）。 */
export function filterOperatorsFor(lang: Lang, type: FilterValueType, only?: string[]): FilterOperator[] {
  const all = (lang === 'zh' ? ZH_OPERATORS : EN_OPERATORS)[type]
  return only ? all.filter((o) => only.includes(o.value)) : all
}
