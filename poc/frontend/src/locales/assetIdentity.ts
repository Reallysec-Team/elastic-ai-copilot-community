import type { Bundle } from '@/lib/i18n'

/** 资产台账页。样板见 `shell.ts` 开头。 */
export type AssetIdentityKey =
  | 'title'
  | 'tabAssets'
  | 'tabIdentities'
  | 'secCoverage'
  | 'coverageHeading'
  | 'kpiCoverage'
  | 'coverageUnknown'
  | 'coverageDetail'
  | 'coverageNoSubject'
  | 'kpiAssets'
  | 'kpiIdentities'
  | 'importedRows'
  | 'secFilter'
  | 'searchPlaceholder'
  | 'searchAria'
  | 'countMatched'
  | 'countTotal'
  | 'errLoad'
  | 'secList'
  | 'emptyFilteredTitle'
  | 'emptyFilteredDesc'
  | 'emptyTitle'
  | 'emptyDesc'
  | 'colName'
  | 'colHostIp'
  | 'colAccount'
  | 'colCriticality'
  | 'colCategory'
  | 'colOwner'
  | 'colDepartment'
  | 'loadMore'
  | 'secImport'
  // CSV 导入卡
  | 'csvTitle'
  | 'csvDesc'
  | 'csvSources'
  | 'csvAvailable'
  | 'csvUnavailable'
  | 'csvAssetsLabel'
  | 'csvIdentitiesLabel'
  | 'csvColumns'
  | 'csvDownloadSample'
  | 'csvUpload'
  | 'csvImported'
  | 'csvErrImport'
  | 'csvSampleAssets'
  | 'csvSampleIdentities'

export const assetIdentityCopy = {
  zh: {
    title: '资产台账',
    tabAssets: '资产',
    tabIdentities: '身份',
    secCoverage: '匹配情况',
    coverageHeading: '匹配情况',
    kpiCoverage: '覆盖率',
    coverageUnknown: '说不上',
    coverageDetail: '抽样 {sampled} 条告警，其中 {withSubject} 条有主体，命中 {matched} 条',
    coverageNoSubject: '抽样里没有带主体的告警',
    kpiAssets: '资产',
    kpiIdentities: '身份',
    importedRows: '已导入的行数',
    secFilter: '台账筛选',
    searchPlaceholder: '名字、责任人、部门，或直接搜主机名 / IP / 账号',
    searchAria: '搜索资产台账',
    countMatched: '匹配 {n} 条',
    countTotal: '共 {n} 条',
    errLoad: '读取失败',
    secList: '台账列表',
    emptyFilteredTitle: '没有匹配的行',
    emptyFilteredDesc: '换个关键词试试。',
    emptyTitle: '还没有导入',
    emptyDesc: '用下面的模板整理成 CSV 再导进来。',
    colName: '名称',
    colHostIp: '主机 / IP',
    colAccount: '账号',
    colCriticality: '重要度',
    colCategory: '类别',
    colOwner: '责任人',
    colDepartment: '部门',
    loadMore: '加载更多（还有 {n} 条）',
    secImport: '导入',

    csvTitle: '资产/身份富化',
    csvDesc: '关联告警中的 host / user / IP 到真实业务资产。列名须在白名单内，仅索引字符串值。',
    csvSources: '探测到的源：',
    csvAvailable: '可用',
    csvUnavailable: '不可用',
    csvAssetsLabel: '资产表（.rst_copilot_assets）',
    csvIdentitiesLabel: '用户表（.rst_copilot_identities）',
    csvColumns: '列：{cols}',
    csvDownloadSample: '下载样本',
    csvUpload: '上传 CSV',
    csvImported: '已导入 {n} 行 → {index}',
    csvErrImport: '导入失败',
    /* 样本 CSV 的示例行也跟着语言走：客户是照着这两行改的，中文界面下给一串
       英文人名和部门，第一件事是先把它们换掉。表头不翻 —— 那是后端认的列名。 */
    csvSampleAssets:
      '财务DB-01,WIN-DB01.corp.local,203.0.113.5,high,db,张三,财务部\nWeb-07,web-07.corp.local,,medium,server,李四,运维部\n',
    csvSampleIdentities:
      '张三,CORP\\jsmith,high,,财务部经理,财务部\n李四,lisi@corp.local,medium,,运维工程师,运维部\n',
  },
  en: {
    title: 'Asset inventory',
    tabAssets: 'Assets',
    tabIdentities: 'Identities',
    secCoverage: 'Match rate',
    coverageHeading: 'Match rate',
    kpiCoverage: 'Coverage',
    coverageUnknown: 'Unknown',
    coverageDetail: '{sampled} alerts sampled, {withSubject} had a subject, {matched} matched',
    coverageNoSubject: 'No sampled alert carried a subject',
    kpiAssets: 'Assets',
    kpiIdentities: 'Identities',
    importedRows: 'Rows imported',
    secFilter: 'Filter',
    searchPlaceholder: 'Name, owner, department — or a hostname / IP / account directly',
    searchAria: 'Search the asset register',
    countMatched: '{n} matching',
    countTotal: '{n} rows',
    errLoad: 'Could not load the register',
    secList: 'Register',
    emptyFilteredTitle: 'Nothing matches',
    emptyFilteredDesc: 'Try another term.',
    emptyTitle: 'Nothing imported yet',
    emptyDesc: 'Fill in the template below as CSV and import it.',
    colName: 'Name',
    colHostIp: 'Host / IP',
    colAccount: 'Account',
    colCriticality: 'Criticality',
    colCategory: 'Category',
    colOwner: 'Owner',
    colDepartment: 'Department',
    loadMore: 'Load more ({n} left)',
    secImport: 'Import',

    csvTitle: 'Asset and identity enrichment',
    csvDesc:
      'Links the host / user / IP in an alert to a real business asset. Column names must be on the allowlist; only string values are indexed.',
    csvSources: 'Sources detected:',
    csvAvailable: 'available',
    csvUnavailable: 'unavailable',
    csvAssetsLabel: 'Asset table (.rst_copilot_assets)',
    csvIdentitiesLabel: 'Identity table (.rst_copilot_identities)',
    csvColumns: 'Columns: {cols}',
    csvDownloadSample: 'Download a template',
    csvUpload: 'Upload CSV',
    csvImported: 'Imported {n} rows → {index}',
    csvErrImport: 'Import failed',
    csvSampleAssets:
      'Finance-DB-01,WIN-DB01.corp.local,203.0.113.5,high,db,J. Smith,Finance\nWeb-07,web-07.corp.local,,medium,server,L. Wu,Operations\n',
    csvSampleIdentities:
      'J. Smith,CORP\\jsmith,high,,Finance manager,Finance\nL. Wu,lwu@corp.local,medium,,SRE,Operations\n',
  },
} satisfies Bundle<AssetIdentityKey>
