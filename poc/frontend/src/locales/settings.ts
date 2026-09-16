import type { Bundle } from '@/lib/i18n'

/** 系统设置页。样板见 `shell.ts` 开头。 */
export type SettingsKey =
  | 'title'
  | 'secCluster'
  | 'secDataAccess'
  | 'secVersion'
  | 'cardEsTitle'
  | 'cardDataTitle'
  | 'fieldWhitelist'
  | 'fieldMasking'
  | 'maskCloud'
  | 'maskPrivate'
  | 'maskAirgapped'
  | 'mustTestFirst'
  | 'maskingBlocked'
  // ES 连接表单
  | 'fieldClusterUrl'
  | 'errConnect'
  | 'connOk'
  | 'connFail'
  | 'connTesting'
  | 'connUnverified'
  | 'noUrlYet'
  | 'testing'
  | 'testConnection'
  | 'fieldUser'
  | 'userPlaceholder'
  | 'fieldPassword'
  | 'fieldVerifyCerts'
  | 'verifyCertsDesc'
  | 'fieldCaPath'
  | 'caPathDesc'
  | 'noListPerm'
  // 首次安装弹窗
  | 'setupOk'
  | 'setupTitle'
  | 'setupDesc'
  | 'setupLater'
  | 'setupSaving'
  | 'setupSave'
  // 审计卡
  | 'auditCardTitle'
  | 'auditEnable'
  | 'auditIndex'
  | 'auditIndexDesc'
  | 'syslogDesc'
  | 'webhookDesc'
  | 'keepCurrent'
  | 'tlsVerify'
  | 'tlsVerifyDesc'
  | 'tlsDefault'
  | 'tlsOn'
  | 'tlsOff'
  // 在线更新
  | 'updateStaged'
  | 'updateCardTitle'
  | 'updateReady'
  | 'updateCurrentVersion'
  | 'updateFound'
  | 'updateStagedPending'
  | 'updateLatest'
  | 'updateUnchecked'
  | 'updateUncheckedShort'
  | 'updateDownloadTitle'
  | 'updateDownloading'
  | 'updateDownload'
  | 'updateStagedShort'
  // 保存浮条
  | 'unsavedChanges'
  | 'discard'
  | 'saveAndApply'

export const settingsCopy = {
  zh: {
    title: '系统设置',
    secCluster: '集群连接',
    secDataAccess: '数据访问范围与脱敏',
    secVersion: '版本与更新',
    cardEsTitle: 'Elasticsearch 连接',
    cardDataTitle: '数据访问',
    fieldWhitelist: '索引白名单',
    fieldMasking: '字段脱敏模式',
    /* 档位名括号里留英文 —— 这三个值要和后端设置里的值对得上，排障时截图给到的
       也是同一个词。英文那边不需要括号，档位名本来就是那个词。 */
    maskCloud: '云端（cloud）',
    maskPrivate: '私有（private）',
    maskAirgapped: '离网（airgapped）',
    mustTestFirst: '请先点「测试连接」，通过后才能保存',
    maskingBlocked: '当前 license 不允许「{mode}」，可用：{available}',

    fieldClusterUrl: '集群地址',
    errConnect: '连接失败',
    connOk: '已连接',
    connFail: '连不上',
    connTesting: '测试中',
    connUnverified: '未验证',
    noUrlYet: '尚未填写地址',
    testing: '测试中',
    testConnection: '测试连接',
    fieldUser: '用户名',
    userPlaceholder: '留空表示集群未开安全认证',
    fieldPassword: '密码',
    fieldVerifyCerts: '校验服务端证书',
    verifyCertsDesc: '自签证书请关闭，或在下面填 CA 路径',
    fieldCaPath: 'CA 证书路径',
    caPathDesc: '容器内路径，通常是 /certs/ca.pem；填了就自动开启校验',
    noListPerm:
      '连接成功，但这个账号列不出索引。请给它 monitor + 目标索引的 read 权限，否则查询页会是空的。',

    setupOk: '已连接 · 正在加载数据',
    setupTitle: '连接到你的 Elasticsearch',
    setupDesc: '这是使用前唯一必需的一步。平台不自带存储，日志和告警都从你现有的集群里读。',
    setupLater: '稍后配置',
    setupSaving: '连接中',
    setupSave: '保存并连接',

    auditCardTitle: '审计 + 多通道转发',
    auditEnable: '启用审计',
    auditIndex: '审计索引名',
    auditIndexDesc: '默认 .rst_copilot_audit',
    syslogDesc: '可选；RFC 5424',
    webhookDesc: '可选；POST JSON',
    keepCurrent: '留空保留现值',
    tlsVerify: 'TLS 校验',
    tlsVerifyDesc: '只影响 webhook sink',
    tlsDefault: '默认（校验）',
    tlsOn: '校验',
    tlsOff: '不校验',

    updateStaged: '镜像已下载并暂存',
    updateCardTitle: '在线更新',
    updateReady: '镜像已就绪（暂存版本 {version}）。请运维在宿主机执行 ./rst-update.sh 完成安装。',
    updateCurrentVersion: '当前版本',
    updateFound: '发现新版本 {version}',
    updateStagedPending: '已暂存 {version} · 待安装',
    updateLatest: '已是最新',
    updateUnchecked: '未连接更新源（激活并完成一次心跳后才会检查）',
    updateUncheckedShort: '未检查',
    updateDownloadTitle: '下载并暂存',
    updateDownloading: '下载并暂存中',
    updateDownload: '下载并暂存',
    updateStagedShort: '已暂存',

    unsavedChanges: '有未保存的更改',
    discard: '撤销',
    saveAndApply: '保存并应用',
  },
  en: {
    title: 'Settings',
    secCluster: 'Cluster connection',
    secDataAccess: 'Data scope and masking',
    secVersion: 'Version and updates',
    cardEsTitle: 'Elasticsearch connection',
    cardDataTitle: 'Data access',
    fieldWhitelist: 'Index allowlist',
    fieldMasking: 'Field masking',
    maskCloud: 'Cloud',
    maskPrivate: 'Private',
    maskAirgapped: 'Air-gapped',
    mustTestFirst: 'Test the connection first — it has to pass before this can be saved',
    maskingBlocked: 'This license does not allow "{mode}". Available: {available}',

    fieldClusterUrl: 'Cluster URL',
    errConnect: 'Connection failed',
    connOk: 'Connected',
    connFail: 'Unreachable',
    connTesting: 'Testing',
    connUnverified: 'Not verified',
    noUrlYet: 'No URL yet',
    testing: 'Testing',
    testConnection: 'Test connection',
    fieldUser: 'Username',
    userPlaceholder: 'Leave empty if the cluster has no security',
    fieldPassword: 'Password',
    fieldVerifyCerts: 'Verify the server certificate',
    verifyCertsDesc: 'Turn this off for self-signed certificates, or give a CA path below',
    fieldCaPath: 'CA certificate path',
    caPathDesc: 'A path inside the container, usually /certs/ca.pem; filling it turns verification on',
    noListPerm:
      'Connected, but this account cannot list indices. Give it monitor plus read on the target indices, or the query page will be empty.',

    setupOk: 'Connected · loading data',
    setupTitle: 'Connect to your Elasticsearch',
    setupDesc:
      'This is the one step required before anything else. The product stores nothing itself — logs and alerts are read from your existing cluster.',
    setupLater: 'Later',
    setupSaving: 'Connecting',
    setupSave: 'Save and connect',

    auditCardTitle: 'Audit and forwarding',
    auditEnable: 'Enable auditing',
    auditIndex: 'Audit index',
    auditIndexDesc: 'Defaults to .rst_copilot_audit',
    syslogDesc: 'Optional; RFC 5424',
    webhookDesc: 'Optional; POSTs JSON',
    keepCurrent: 'Leave empty to keep the current value',
    tlsVerify: 'TLS verification',
    tlsVerifyDesc: 'Applies to the webhook sink only',
    tlsDefault: 'Default (verify)',
    tlsOn: 'Verify',
    tlsOff: "Don't verify",

    updateStaged: 'Image downloaded and staged',
    updateCardTitle: 'Online update',
    updateReady:
      'The image is ready (staged version {version}). Ops runs ./rst-update.sh on the host to install it.',
    updateCurrentVersion: 'Current version',
    updateFound: 'Version {version} available',
    updateStagedPending: '{version} staged · not installed',
    updateLatest: 'Up to date',
    updateUnchecked: 'No update source yet (checks after activation and the first heartbeat)',
    updateUncheckedShort: 'Not checked',
    updateDownloadTitle: 'Download and stage',
    updateDownloading: 'Downloading',
    updateDownload: 'Download and stage',
    updateStagedShort: 'Staged',

    unsavedChanges: 'Unsaved changes',
    discard: 'Discard',
    saveAndApply: 'Save and apply',
  },
} satisfies Bundle<SettingsKey>
