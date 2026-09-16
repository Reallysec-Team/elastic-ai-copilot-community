import type { Bundle } from '@/lib/i18n'

/** 处置手册页。样板见 `shell.ts` 开头。 */
export type KbKey =
  | 'title'
  | 'embedNotConfigured'
  | 'upload'
  | 'uploadDialogTitle'
  | 'tabDocs'
  | 'tabSearch'
  | 'confirmDelete'
  | 'okDeleted'
  | 'errDelete'
  | 'untitled'
  | 'chunkCount'
  | 'deleteDoc'
  | 'secDocsOverview'
  | 'secDocsList'
  | 'docsListTitle'
  | 'kpiDocsLabel'
  | 'kpiDocs'
  | 'kpiChunksLabel'
  | 'kpiChunks'
  | 'kpiNewestNoTs'
  | 'kpiNewest'
  | 'emptyTitle'
  | 'emptyDesc'
  | 'uploadFirst'
  | 'errTitleBodyRequired'
  | 'fieldTitle'
  | 'titlePlaceholder'
  | 'fieldBody'
  | 'bodyPlaceholder'
  | 'chunkEstimate'
  | 'fieldMetadata'
  | 'metadataDesc'
  | 'metaKeyPlaceholder'
  | 'metaValuePlaceholder'
  | 'metaKeyAria'
  | 'metaValueAria'
  | 'metaRemove'
  | 'metaRemoveAria'
  | 'addField'
  | 'uploadedChunks'
  | 'submitEmbedding'
  | 'similarity'
  | 'secSearchForm'
  | 'searchPlaceholder'
  | 'searchAria'
  | 'clear'
  | 'topKAria'
  | 'topK'
  | 'searching'
  | 'searchAction'
  | 'noHitsTitle'
  | 'noHitsDesc'
  | 'secHits'
  | 'hitsTitle'
  | 'hitsDesc'
  | 'expandFull'
  | 'timeUnknown'
  /* 「刚刚 / N 分钟前」那四档在 common.ts，和查询历史共用。 */
  | 'monthsAgo'

export const kbCopy = {
  zh: {
    title: '处置手册',
    embedNotConfigured: '处置手册未启用，请联系管理员在服务端开启向量模型',
    upload: '上传文档',
    uploadDialogTitle: '上传新文档',
    tabDocs: '文档库',
    tabSearch: '检索测试',

    confirmDelete: '删除「{name}」？这会移除 {n} 个内容片段，此操作不可撤销。',
    okDeleted: '已删除「{name}」',
    errDelete: '删除失败，已回退到服务端的状态',
    untitled: '（无标题）',
    chunkCount: '{n} 个片段',
    deleteDoc: '删除 {name}',

    secDocsOverview: '文档库概览',
    secDocsList: '文档列表',
    docsListTitle: '文档',
    kpiDocsLabel: '可被检索的文档',
    kpiDocs: '文档',
    kpiChunksLabel: '嵌入后的切块总数',
    kpiChunks: '内容片段',
    kpiNewestNoTs: '没有时间戳',
    kpiNewest: '最近入库',

    emptyTitle: '还没有手册',
    emptyDesc: '上传第一篇文档，AI 分析时会自动引用。',
    uploadFirst: '上传第一篇',

    errTitleBodyRequired: '标题和正文都不能为空',
    fieldTitle: '标题',
    titlePlaceholder: '例如：勒索软件应急手册 v3',
    fieldBody: '正文',
    bodyPlaceholder: '粘贴 Markdown 或纯文本，建议 5–20k 字符。',
    chunkEstimate: '约 {chunks} 个片段 · {chars} 字符',
    fieldMetadata: '元数据（可选）',
    metadataDesc: '会随片段一起存下来，检索时能看到这条内容是从哪来的。最多 6 组，当前 {n}/6。',
    metaKeyPlaceholder: 'key（如 source）',
    metaValuePlaceholder: 'value（如 internal-wiki）',
    metaKeyAria: '元数据 {i} 的键',
    metaValueAria: '元数据 {i} 的值',
    metaRemove: '移除',
    metaRemoveAria: '移除元数据 {i}',
    addField: '添加字段',
    uploadedChunks: '已上传 · {n} 个片段 · 即将跳转到文档库…',
    submitEmbedding: '提交并 embedding',

    similarity: '相似度 {score}',
    secSearchForm: '检索条件',
    searchPlaceholder: '输入一个问题，看手册里命中哪些内容…',
    searchAria: '检索问题',
    clear: '清空',
    topKAria: '返回条数',
    topK: '取前 {n} 条',
    searching: '检索中',
    searchAction: '检索',
    noHitsTitle: '没有命中相关内容',
    noHitsDesc: '换个问法，或先上传文档。',
    secHits: '命中片段',
    hitsTitle: '命中',
    hitsDesc: '共 {n} 条片段，按相似度从高到低',
    expandFull: '展开全文',

    timeUnknown: '未知时间',
    monthsAgo: '{n} 个月前',
  },
  en: {
    title: 'Runbooks',
    embedNotConfigured: 'Runbooks are off — ask an administrator to enable the embedding model on the server',
    upload: 'Upload',
    uploadDialogTitle: 'Upload a document',
    tabDocs: 'Library',
    tabSearch: 'Search test',

    confirmDelete: 'Delete "{name}"? This removes {n} chunks and cannot be undone.',
    okDeleted: 'Deleted "{name}"',
    errDelete: 'Delete failed — reverted to the server state',
    untitled: '(untitled)',
    chunkCount: '{n} chunks',
    deleteDoc: 'Delete {name}',

    secDocsOverview: 'Library overview',
    secDocsList: 'Documents',
    docsListTitle: 'Documents',
    kpiDocsLabel: 'Documents that can be retrieved',
    kpiDocs: 'Documents',
    kpiChunksLabel: 'Chunks after embedding',
    kpiChunks: 'Chunks',
    kpiNewestNoTs: 'No timestamp',
    kpiNewest: 'Last indexed',

    emptyTitle: 'No runbooks yet',
    emptyDesc: 'Upload the first document and the AI will cite it during analysis.',
    uploadFirst: 'Upload the first one',

    errTitleBodyRequired: 'Both title and body are required',
    fieldTitle: 'Title',
    titlePlaceholder: 'For example: Ransomware response runbook v3',
    fieldBody: 'Body',
    bodyPlaceholder: 'Paste Markdown or plain text — 5–20k characters works well.',
    chunkEstimate: 'about {chunks} chunks · {chars} characters',
    fieldMetadata: 'Metadata (optional)',
    metadataDesc:
      'Stored alongside each chunk, so a retrieved passage shows where it came from. Up to 6 pairs; {n}/6 used.',
    metaKeyPlaceholder: 'key (e.g. source)',
    metaValuePlaceholder: 'value (e.g. internal-wiki)',
    metaKeyAria: 'Metadata {i} key',
    metaValueAria: 'Metadata {i} value',
    metaRemove: 'Remove',
    metaRemoveAria: 'Remove metadata {i}',
    addField: 'Add a pair',
    uploadedChunks: 'Uploaded · {n} chunks · going to the library…',
    submitEmbedding: 'Submit and embed',

    similarity: 'Score {score}',
    secSearchForm: 'Search',
    searchPlaceholder: 'Ask a question and see which passages it hits…',
    searchAria: 'Search query',
    clear: 'Clear',
    topKAria: 'Number of results',
    topK: 'Top {n}',
    searching: 'Searching',
    searchAction: 'Search',
    noHitsTitle: 'Nothing matched',
    noHitsDesc: 'Try asking differently, or upload a document first.',
    secHits: 'Matching passages',
    hitsTitle: 'Matches',
    hitsDesc: '{n} passages, highest score first',
    expandFull: 'Show the full passage',

    timeUnknown: 'Unknown time',
    monthsAgo: '{n} mo ago',
  },
} satisfies Bundle<KbKey>
