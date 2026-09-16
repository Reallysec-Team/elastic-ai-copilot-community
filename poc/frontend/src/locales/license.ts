import type { Bundle } from '@/lib/i18n'

/** 产品激活页。样板见 `shell.ts` 开头。 */
export type LicenseKey =
  | 'title'
  | 'descUnactivated'
  | 'stUnactivated'
  | 'stValid'
  | 'stExpiring'
  | 'stGrace'
  | 'stExpired'
  | 'stRevoked'
  | 'stInvalid'
  | 'stHeartbeatLost'
  | 'stUnknown'
  | 'errStatus'
  | 'errNeedAdmin'
  | 'errPasteKey'
  | 'errFileTooLarge'
  | 'errNoToken'
  | 'errReadFile'
  | 'secMode'
  | 'modeOnline'
  | 'modeOffline'
  | 'secSwap'
  | 'secDeactivate'
  | 'deactivateHint'
  | 'confirmDeactivate'
  | 'deactivate'
  | 'secStatus'
  | 'secReactivate'
  | 'secActivate'
  | 'secBinding'
  | 'noticeHeartbeatTitle'
  | 'noticeHeartbeatDesc'
  | 'noticeExpiredTitle'
  | 'noticeExpiredDesc'
  | 'noticeRevokedTitle'
  | 'noticeRevokedDesc'
  | 'noticeInvalidTitle'
  | 'noticeInvalidDesc'
  | 'fieldLicenseId'
  | 'fieldType'
  | 'fieldEmail'
  | 'fieldExpiry'
  | 'fieldLastHeartbeat'
  | 'fieldFeatures'
  | 'secOverview'
  | 'secDetail'
  | 'detailTitle'
  | 'kpiStatus'
  | 'kpiNoType'
  | 'kpiExpiry'
  | 'kpiNoExpiry'
  | 'expiredDays'
  | 'daysLeft'
  | 'renewSoon'
  | 'kpiFeatures'
  | 'featuresWildcardLabel'
  | 'featuresPerIdLabel'
  | 'featuresAll'
  | 'featureAllBadge'
  | 'featureWildcardTitle'
  | 'secUsage'
  | 'factDaysLeft'
  | 'metricQuota'
  | 'metricQuotaTrial'
  | 'metricQuotaOff'
  | 'metricHeartbeatDesc'
  | 'featDetectionRule'
  | 'featAlertTriage'
  | 'featAlertInvestigation'
  | 'featPlatformOps'
  | 'cardPasteTitle'
  | 'cardUploadTitle'
  | 'badgeOnline'
  | 'badgeOffline'
  | 'uploadFile'
  | 'keyPlaceholder'
  | 'activate'
  | 'activating'
  | 'fingerprintTitle'
  | 'fingerprintBadge'
  | 'copyFingerprint'
  | 'okCopiedFingerprint'
  | 'errCopyFingerprint'
  | 'fingerprintOnlineNote'

export const licenseCopy = {
  zh: {
    title: '产品激活',
    descUnactivated: '当前状态：{status}。未激活时可以用智能查询、多轮追问、脱敏等全部基础功能（每日有试用额度）；告警批量分级、告警调查、检测规则生成、平台健康助手四项需要许可。试用（标准版功能，14 天）向销售申请后会收到一段 license key，粘贴到下面即可；离线环境用「离线激活」。',

    stUnactivated: '未激活',
    stValid: '有效',
    stExpiring: '即将到期',
    stGrace: '宽限期内',
    stExpired: '已过期',
    stRevoked: '已吊销',
    stInvalid: '无效',
    stHeartbeatLost: '心跳丢失',
    stUnknown: '状态未知',

    errStatus: '无法获取 license 状态：{detail}',
    errNeedAdmin: '需要管理员权限',
    errPasteKey: '请粘贴 license key',
    errFileTooLarge: '文件过大，请确认选择的是 license token 文件（.lic / .txt / .json）。',
    errNoToken: '未在文件中找到 license token，请检查文件，或直接粘贴密钥。',
    errReadFile: '读取文件失败，请重试或直接粘贴。',

    secMode: '激活方式',
    modeOnline: '在线激活',
    modeOffline: '离线激活',
    secSwap: '更换或续期',
    secDeactivate: '撤销激活',
    deactivateHint: '撤销后回到未激活状态，可以重新激活。',
    confirmDeactivate: '确认撤销',
    deactivate: '撤销当前 license',
    secStatus: '许可证状态',
    secReactivate: '重新激活',
    secActivate: '激活',
    secBinding: '主机绑定',

    noticeHeartbeatTitle: '许可证心跳丢失',
    noticeHeartbeatDesc:
      '许可证仍在有效期内，但与许可服务器的连接已中断。请检查本机网络或许可服务器状态；若失联持续超过离线宽限期，许可证将自动失效。',
    noticeExpiredTitle: '许可证已过期',
    noticeExpiredDesc: '当前许可证已超过有效期。请联系销售续期后，粘贴新的 license key 重新激活。',
    noticeRevokedTitle: '许可证已被吊销',
    noticeRevokedDesc: '该许可证已被签发方吊销，无法继续使用。请联系销售获取新的 license key 后重新激活。',
    noticeInvalidTitle: '许可证无效',
    noticeInvalidDesc:
      '许可证校验未通过（签名、所属产品或主机绑定不匹配）。请确认粘贴的是与本机绑定的正确 license key 后重新激活。',

    fieldLicenseId: '许可证 ID',
    fieldType: '类型',
    fieldEmail: '邮箱',
    fieldExpiry: '到期',
    fieldLastHeartbeat: '最后一次心跳',
    fieldFeatures: '功能',

    secOverview: '许可证概览',
    secDetail: '许可证详情',
    detailTitle: '许可证详情',
    kpiStatus: '许可证状态',
    kpiNoType: '未标注类型',
    kpiExpiry: '到期',
    kpiNoExpiry: '没有到期日',
    expiredDays: '已过期 {n} 天',
    daysLeft: '还剩 {n} 天',
    renewSoon: '该续期了',
    kpiFeatures: '已解锁功能',
    featuresWildcardLabel: '通配符 *（企业版）',
    featuresPerIdLabel: '按 feature id 逐项授权',
    featuresAll: '全部',
    featureAllBadge: '全部功能',
    featureWildcardTitle: '通配符：解锁全部功能（企业版）',
    secUsage: '用量',
    factDaysLeft: '剩余',
    metricQuota: '今日额度',
    metricQuotaTrial: '试用期每日 LLM 调用',
    metricQuotaOff: '已激活，不限次',
    metricHeartbeatDesc: '与许可服务器最近一次成功校验',
    featDetectionRule: '检测规则助手',
    featAlertTriage: '批量分诊',
    featAlertInvestigation: '告警调查',
    featPlatformOps: '平台健康 AI 解读',

    cardPasteTitle: '粘贴 license key',
    cardUploadTitle: '上传离线 license',
    badgeOnline: '在线 · 联网激活',
    badgeOffline: '离线 · 主机绑定',
    uploadFile: '上传 license 文件',
    keyPlaceholder: 'ey…（粘贴销售提供的 license key）',
    activate: '激活',
    activating: '激活中…',

    fingerprintTitle: '主机指纹',
    fingerprintBadge: '本机标识 · 仅供参考',
    copyFingerprint: '复制主机指纹',
    okCopiedFingerprint: '已复制主机指纹',
    errCopyFingerprint: '复制失败，请手动选中复制',
    fingerprintOnlineNote:
      '在线激活时会自动绑定本机，无需把任何标识符发给销售。此指纹仅供排查参考。',
  },
  en: {
    title: 'License',
    descUnactivated: 'Current status: {status}. Without a license every core feature works (ask, follow-ups, masking) under a daily trial quota; alert triage, alert investigation, detection-rule generation and the platform-ops assistant need one. Ask sales for a trial (Standard features, 14 days) — you get a license key to paste below; air-gapped hosts use “Offline”.',

    stUnactivated: 'Not activated',
    stValid: 'Valid',
    stExpiring: 'Expiring soon',
    stGrace: 'In grace period',
    stExpired: 'Expired',
    stRevoked: 'Revoked',
    stInvalid: 'Invalid',
    stHeartbeatLost: 'Heartbeat lost',
    stUnknown: 'Unknown',

    errStatus: 'Could not read the license status: {detail}',
    errNeedAdmin: 'Administrator permission required',
    errPasteKey: 'Paste a license key',
    errFileTooLarge: 'That file is too large — pick the license token file (.lic / .txt / .json).',
    errNoToken: 'No license token found in that file. Check the file, or paste the key directly.',
    errReadFile: 'Could not read the file. Try again, or paste the key directly.',

    secMode: 'Activation method',
    modeOnline: 'Online',
    modeOffline: 'Offline',
    secSwap: 'Replace or renew',
    secDeactivate: 'Deactivate',
    deactivateHint: 'Deactivating returns to the unactivated state; you can activate again.',
    confirmDeactivate: 'Confirm',
    deactivate: 'Deactivate this license',
    secStatus: 'License status',
    secReactivate: 'Activate again',
    secActivate: 'Activate',
    secBinding: 'Host binding',

    noticeHeartbeatTitle: 'License heartbeat lost',
    noticeHeartbeatDesc:
      'The license is still within its term, but the connection to the license server has been lost. Check this host’s network and the license server. If it stays unreachable past the offline grace period, the license lapses.',
    noticeExpiredTitle: 'License expired',
    noticeExpiredDesc:
      'This license is past its term. Renew it with sales, then paste the new license key to activate again.',
    noticeRevokedTitle: 'License revoked',
    noticeRevokedDesc:
      'The issuer revoked this license and it can no longer be used. Get a new license key from sales and activate again.',
    noticeInvalidTitle: 'License invalid',
    noticeInvalidDesc:
      'The license did not validate — its signature, product or host binding does not match. Make sure the key you pasted is the one bound to this host, then activate again.',

    fieldLicenseId: 'License ID',
    fieldType: 'Type',
    fieldEmail: 'Email',
    fieldExpiry: 'Expires',
    fieldLastHeartbeat: 'Last heartbeat',
    fieldFeatures: 'Features',

    secOverview: 'License overview',
    secDetail: 'License details',
    detailTitle: 'License details',
    kpiStatus: 'License status',
    kpiNoType: 'No type recorded',
    kpiExpiry: 'Expires',
    kpiNoExpiry: 'No expiry date',
    expiredDays: 'Expired {n} days ago',
    daysLeft: '{n} days left',
    renewSoon: 'Time to renew',
    kpiFeatures: 'Features unlocked',
    featuresWildcardLabel: 'Wildcard * (enterprise)',
    featuresPerIdLabel: 'Licensed per feature id',
    featuresAll: 'All',
    featureAllBadge: 'All features',
    featureWildcardTitle: 'Wildcard: unlocks every feature (enterprise)',
    secUsage: 'Usage',
    factDaysLeft: 'Remaining',
    metricQuota: 'Quota today',
    metricQuotaTrial: 'Daily LLM calls during trial',
    metricQuotaOff: 'Activated, unlimited',
    metricHeartbeatDesc: 'Last successful check with the license server',
    featDetectionRule: 'Detection rule copilot',
    featAlertTriage: 'Batch triage',
    featAlertInvestigation: 'Alert investigation',
    featPlatformOps: 'Platform health AI read',

    cardPasteTitle: 'Paste a license key',
    cardUploadTitle: 'Upload an offline license',
    badgeOnline: 'Online · activated over the network',
    badgeOffline: 'Offline · bound to this host',
    uploadFile: 'Upload a license file',
    keyPlaceholder: 'ey… (paste the license key sales gave you)',
    activate: 'Activate',
    activating: 'Activating…',

    fingerprintTitle: 'Host fingerprint',
    fingerprintBadge: 'Host identifier · for reference',
    copyFingerprint: 'Copy the host fingerprint',
    okCopiedFingerprint: 'Host fingerprint copied',
    errCopyFingerprint: 'Could not copy — select it and copy by hand',
    fingerprintOnlineNote:
      'Online activation binds this host automatically; you never have to send anyone an identifier. This fingerprint is only here for troubleshooting.',
  },
} satisfies Bundle<LicenseKey>
