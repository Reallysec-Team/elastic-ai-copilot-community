import type { Bundle } from '@/lib/i18n'

/** 字段字典页。样板见 `shell.ts` 开头。 */
export type FieldDictKey =
  | 'title'
  | 'indexPlaceholder'
  | 'scan'
  | 'scanning'
  | 'errIndexRequired'
  | 'errScan'
  | 'copied'
  | 'errCopy'
  | 'stagedToQuery'
  | 'aggQuestion'
  | 'pickIndexTitle'
  | 'pickIndexDesc'
  | 'secOverview'
  | 'typeMix'
  | 'unitFields'
  | 'noUsableFields'
  | 'secTable'
  | 'gridEmpty'
  | 'cardTitle'
  | 'cardDesc'
  | 'filterByName'
  | 'clearFilter'
  | 'filterByType'
  | 'typeAll'
  | 'typeOther'
  | 'countFields'
  | 'paginationInfo'
  | 'indexCount'
  | 'kpiDocs'
  | 'kpiScannedLabel'
  | 'kpiScanned'
  | 'kpiTruncated'
  | 'kpiEmptyLabel'
  | 'kpiEmpty'
  | 'kpiTopNone'
  | 'kpiTop'
  | 'colField'
  | 'colCardinality'
  | 'colSamples'
  | 'copyFieldName'
  | 'insertIntoQuery'
  | 'copySample'

export const fieldDictCopy = {
  zh: {
    title: '字段字典',
    indexPlaceholder: '索引名（支持 wildcard）',
    scan: '扫描索引',
    scanning: '扫描中…',
    errIndexRequired: '请填写索引名',
    errScan: '扫描失败',
    copied: '已复制 {text}',
    errCopy: '复制失败',
    stagedToQuery: '已暂存到查询页',
    aggQuestion: '按 {field} 聚合，取 top 10',
    pickIndexTitle: '先选一个索引',
    pickIndexDesc: '没有想好的话，从这几个开始：',
    secOverview: '扫描概览',
    typeMix: '字段类型分布',
    unitFields: '字段',
    noUsableFields: '这个索引的 mapping 里没有可用字段',
    secTable: '字段表',
    gridEmpty: '没有匹配的字段。换个字段名关键词，或把类型筛选放开。',
    cardTitle: '字段',
    cardDesc: '样本值按出现次数倒序，点一下复制成 `字段:"值"`，可以直接贴进查询',
    filterByName: '按字段名过滤',
    clearFilter: '清空过滤',
    filterByType: '按类型筛选',
    typeAll: '类型：全部',
    typeOther: '其他',
    countFields: '{shown} / {total} 字段',
    paginationInfo: '{from} - {to} / 共 {count} 个字段',
    indexCount: '{n} 个索引',
    kpiDocs: '文档数',
    kpiScannedLabel: 'mapping 里共 {n} 个',
    kpiScanned: '扫到的字段',
    kpiTruncated: '只扫了前一批',
    kpiEmptyLabel: '扫到的 {n} 个字段里',
    kpiEmpty: '空字段',
    kpiTopNone: '没有可估算基数的字段',
    kpiTop: '基数最高的字段',
    colField: '字段',
    colCardinality: '独立值数 (≈)',
    colSamples: '样本值',
    copyFieldName: '复制字段名',
    insertIntoQuery: '插入到查询',
    copySample: '点击复制 {text}',
  },
  en: {
    title: 'Field dictionary',
    indexPlaceholder: 'Index name (wildcards allowed)',
    scan: 'Scan index',
    scanning: 'Scanning…',
    errIndexRequired: 'Enter an index name',
    errScan: 'Scan failed',
    copied: 'Copied {text}',
    errCopy: 'Could not copy',
    stagedToQuery: 'Staged for the query page',
    aggQuestion: 'Aggregate by {field}, top 10',
    pickIndexTitle: 'Pick an index first',
    pickIndexDesc: 'If nothing comes to mind, start with one of these:',
    secOverview: 'Scan overview',
    typeMix: 'Field types',
    unitFields: 'fields',
    noUsableFields: "This index's mapping has no usable fields",
    secTable: 'Fields',
    gridEmpty: 'No field matches. Try another name, or widen the type filter.',
    cardTitle: 'Fields',
    cardDesc: 'Sample values are ordered by frequency. Click one to copy it as `field:"value"`, ready to paste into a query.',
    filterByName: 'Filter by field name',
    clearFilter: 'Clear filter',
    filterByType: 'Filter by type',
    typeAll: 'Type: all',
    typeOther: 'other',
    countFields: '{shown} / {total} fields',
    paginationInfo: '{from} - {to} of {count} fields',
    indexCount: '{n} indices',
    kpiDocs: 'Documents',
    kpiScannedLabel: '{n} in the mapping',
    kpiScanned: 'Fields scanned',
    kpiTruncated: 'First batch only',
    kpiEmptyLabel: 'of the {n} fields scanned',
    kpiEmpty: 'Empty fields',
    kpiTopNone: 'No field has an estimable cardinality',
    kpiTop: 'Highest cardinality',
    colField: 'Field',
    colCardinality: 'Distinct values (≈)',
    colSamples: 'Samples',
    copyFieldName: 'Copy field name',
    insertIntoQuery: 'Insert into a query',
    copySample: 'Click to copy {text}',
  },
} satisfies Bundle<FieldDictKey>
