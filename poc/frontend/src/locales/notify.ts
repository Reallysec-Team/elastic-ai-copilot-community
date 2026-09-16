import type { Bundle } from '@/lib/i18n'

/** 对外通道页。样板见 `shell.ts` 开头。 */
export type NotifyKey =
  | 'title'
  | 'secOutlets'
  | 'tabTargets'
  | 'tabDeliveries'
  | 'tabSmtp'
  | 'tabAudit'
  | 'deliveriesDesc'
  | 'smtpDesc'
  // 排期
  | 'periodDaily'
  | 'periodWeekly'
  | 'periodMonthly'
  | 'errLoadConfig'
  | 'errSave'
  | 'schedTitle'
  | 'schedDesc'
  | 'fieldPeriods'
  | 'fieldHour'
  | 'fieldTimezone'
  | 'fieldThreshold'
  | 'savingDots'
  | 'saved'
  | 'saveSchedule'
  // 投递目标
  | 'chFeishu'
  | 'chDingtalk'
  | 'chWecom'
  | 'chEmail'
  | 'errDelete'
  | 'errTest'
  | 'targetsLabel'
  | 'addTarget'
  | 'noTargets'
  | 'targetDisabled'
  | 'secretSet'
  | 'secretStale'
  | 'smtpPasswordStale'
  | 'testSend'
  | 'confirmDelete'
  | 'groupCount'
  | 'rowActions'
  | 'badgeStale'
  | 'badgeNoSecret'
  | 'badgeRecipients'
  | 'deleteTarget'
  | 'deleteTargetBody'
  | 'noPeriods'
  | 'thresholdIs'
  | 'testOk'
  | 'testFailed'
  | 'sending'
  // 目标弹窗
  | 'errNameRequired'
  | 'errRecipientsRequired'
  | 'errWebhookRequired'
  | 'dlgCreate'
  | 'dlgEdit'
  | 'fieldChannel'
  | 'channelAria'
  | 'fieldName'
  | 'namePlaceholderEmail'
  | 'namePlaceholderChat'
  | 'fieldRecipients'
  | 'recipientsHint'
  | 'fieldSecret'
  | 'secretPlaceholderSet'
  | 'webhookPlaceholderSet'
  | 'secretPlaceholderUnset'
  | 'clearSecret'
  | 'fieldBindPeriods'
  | 'enableTarget'
  // 投递记录
  | 'dvQueued'
  | 'dvSending'
  | 'dvSent'
  | 'dvFailed'
  | 'dvDead'
  | 'errResend'
  | 'deadCount'
  | 'allStatuses'
  | 'noRecordsForStatus'
  | 'noRecords'
  | 'colKind'
  | 'colChannel'
  | 'colTarget'
  | 'colStatus'
  | 'colAttempts'
  | 'colLastError'
  | 'colUpdatedAt'
  | 'kindReport'
  | 'kindAlert'
  | 'resend'
  // SMTP
  | 'encNone'
  | 'smtpSaved'
  | 'smtpUnset'
  | 'smtpHost'
  | 'smtpEncryption'
  | 'smtpEncryptionDesc'
  | 'smtpPort'
  | 'smtpUser'
  | 'smtpUserDesc'
  | 'smtpPassword'
  | 'smtpPasswordSet'
  | 'smtpPasswordUnset'
  | 'smtpFrom'
  | 'smtpFromName'
  | 'smtpFooter'

export const notifyCopy = {
  zh: {
    title: '对外通道',
    secOutlets: '出口配置',
    tabTargets: '投递目标',
    tabDeliveries: '投递记录',
    tabSmtp: '邮件服务器',
    tabAudit: '审计转发',
    deliveriesDesc: '失败会自动退避重试；重试到头记为「已放弃」，修好配置后可以手动重投。',
    smtpDesc: '全局一份；所有邮件目标共用，改密码只改这里。',

    periodDaily: '日报',
    periodWeekly: '周报',
    periodMonthly: '月报',
    errLoadConfig: '加载投递配置失败',
    errSave: '保存失败',
    schedTitle: '推送排期',
    schedDesc: '定时报告生成后自动推送到下方绑定了该周期的目标。',
    fieldPeriods: '推送周期',
    fieldHour: '发送时刻（小时）',
    fieldTimezone: '时区',
    fieldThreshold: '告警阈值',
    savingDots: '保存中…',
    saved: '已保存',
    saveSchedule: '保存排期',

    chFeishu: '飞书',
    chDingtalk: '钉钉',
    chWecom: '企业微信',
    chEmail: '邮件',
    errDelete: '删除失败',
    errTest: '测试失败',
    targetsLabel: '投递目标',
    addTarget: '新增目标',
    noTargets: '还没有投递目标。点「新增目标」绑定第一个群机器人或邮件收件人。',
    targetDisabled: '已停用',
    secretSet: '已设置密钥',
    secretStale: '密钥失效，请重填（网关重装后旧密文解不开）',
    smtpPasswordStale: '已保存的密码这台网关解不开（重装后旧密文失效），请重填',
    testSend: '测试发送',
    confirmDelete: '确认删除？',
    groupCount: '{n} 个',
    rowActions: '{name} 的操作',
    badgeStale: '密钥失效',
    badgeNoSecret: '未设置密钥',
    badgeRecipients: '{n} 个收件人',
    deleteTarget: '删除「{name}」？',
    deleteTargetBody: '这条投递目标会立即停止收到报告和告警，历史投递记录保留。此操作不可撤销。',
    noPeriods: '未绑定周期',
    thresholdIs: '阈值 {level}',
    testOk: '测试发送成功',
    testFailed: '测试失败：{err}',
    sending: '发送中…',

    errNameRequired: '请填写目标名称',
    errRecipientsRequired: '请填写收件人',
    errWebhookRequired: '请填写 webhook URL',
    dlgCreate: '新增投递目标',
    dlgEdit: '编辑投递目标',
    fieldChannel: '渠道',
    channelAria: '投递渠道',
    fieldName: '名称',
    namePlaceholderEmail: '安全运营组',
    namePlaceholderChat: 'SOC 值班群',
    fieldRecipients: '收件人',
    recipientsHint: '逗号、分号或换行分隔。发件服务器在「邮件服务器」里配，全局一份。',
    fieldSecret: '签名密钥（secret）',
    secretPlaceholderSet: '留空不改',
    webhookPlaceholderSet: '已设置（{host}），留空不改',
    secretPlaceholderUnset: '机器人开启签名校验时才需要（可选）',
    clearSecret: '清除已设置的密钥（改为无签名）',
    fieldBindPeriods: '绑定周期',
    enableTarget: '启用该目标',

    dvQueued: '排队中',
    dvSending: '发送中',
    dvSent: '已送达',
    dvFailed: '待重试',
    dvDead: '已放弃',
    errResend: '重投失败',
    deadCount: '{n} 条已放弃',
    allStatuses: '全部状态',
    noRecordsForStatus: '这个状态下没有记录。',
    noRecords: '暂无投递记录。',
    colKind: '类型',
    colChannel: '渠道',
    colTarget: '目标',
    colStatus: '状态',
    colAttempts: '尝试',
    colLastError: '最后错误',
    colUpdatedAt: '更新于',
    kindReport: '报告',
    kindAlert: '告警',
    resend: '重投',

    encNone: '不加密',
    smtpSaved: '已保存 · 邮件目标下次投递生效',
    smtpUnset: '还没配发件服务器。邮件目标会一直投递失败，报告和告警发不出去，只有投递记录里能看到原因。',
    smtpHost: '服务器地址',
    smtpEncryption: '加密方式',
    smtpEncryptionDesc: '端口会跟着变，改过的不动',
    smtpPort: '端口',
    smtpUser: '用户名',
    smtpUserDesc: '留空表示服务器不要求认证',
    smtpPassword: '密码',
    smtpPasswordSet: '已保存；留空不改',
    smtpPasswordUnset: '应用专用密码或授权码',
    smtpFrom: '发件地址',
    smtpFromName: '发件人名称',
    smtpFooter:
      '存完之后，去「投递目标」建一个邮件目标，用它的「测试发送」验证这条链路。这里只校验格式，发不发得出去要真发一封才知道。',
  },
  en: {
    title: 'Outbound channels',
    secOutlets: 'Outbound configuration',
    tabTargets: 'Destinations',
    tabDeliveries: 'Delivery log',
    tabSmtp: 'Mail server',
    tabAudit: 'Audit forwarding',
    deliveriesDesc:
      'Failures retry with backoff. Once retries run out a delivery is marked "given up" — fix the configuration and resend it by hand.',
    smtpDesc: 'One server for the whole deployment. Every mail destination uses it; change the password here only.',

    periodDaily: 'Daily',
    periodWeekly: 'Weekly',
    periodMonthly: 'Monthly',
    errLoadConfig: 'Could not load the delivery configuration',
    errSave: 'Save failed',
    schedTitle: 'Schedule',
    schedDesc: 'A scheduled report is pushed to every destination below that is bound to that period.',
    fieldPeriods: 'Periods',
    fieldHour: 'Hour of day',
    fieldTimezone: 'Time zone',
    fieldThreshold: 'Alert threshold',
    savingDots: 'Saving…',
    saved: 'Saved',
    saveSchedule: 'Save the schedule',

    chFeishu: 'Feishu',
    chDingtalk: 'DingTalk',
    chWecom: 'WeCom',
    chEmail: 'Email',
    errDelete: 'Delete failed',
    errTest: 'Test failed',
    targetsLabel: 'Destinations',
    addTarget: 'Add a destination',
    noTargets: 'No destinations yet. Add one to bind the first bot or mail recipient.',
    targetDisabled: 'disabled',
    secretSet: 'secret set',
    secretStale: 'secret unreadable — re-enter it (the gateway was reinstalled, old ciphertext cannot be opened)',
    smtpPasswordStale: 'The saved password cannot be opened by this gateway (reinstalled) — re-enter it',
    testSend: 'Send a test',
    confirmDelete: 'Delete?',
    groupCount: '{n}',
    rowActions: 'Actions for {name}',
    badgeStale: 'Secret invalid',
    badgeNoSecret: 'No secret',
    badgeRecipients: '{n} recipients',
    deleteTarget: 'Delete "{name}"?',
    deleteTargetBody: 'This destination stops receiving reports and alerts immediately; past deliveries are kept. This cannot be undone.',
    noPeriods: 'no period bound',
    thresholdIs: 'threshold {level}',
    testOk: 'Test delivery succeeded',
    testFailed: 'Test failed: {err}',
    sending: 'Sending…',

    errNameRequired: 'Enter a name',
    errRecipientsRequired: 'Enter the recipients',
    errWebhookRequired: 'Enter the webhook URL',
    dlgCreate: 'New destination',
    dlgEdit: 'Edit destination',
    fieldChannel: 'Channel',
    channelAria: 'Delivery channel',
    fieldName: 'Name',
    namePlaceholderEmail: 'Security operations',
    namePlaceholderChat: 'SOC on-call room',
    fieldRecipients: 'Recipients',
    recipientsHint:
      'Separate with commas, semicolons or newlines. The sending server is configured once, under Mail server.',
    fieldSecret: 'Signing secret',
    secretPlaceholderSet: 'Leave empty to keep it',
    webhookPlaceholderSet: 'Set ({host}) — leave empty to keep it',
    secretPlaceholderUnset: 'Only needed when the bot has signature checking on (optional)',
    clearSecret: 'Clear the stored secret (switch to unsigned)',
    fieldBindPeriods: 'Bound periods',
    enableTarget: 'Enable this destination',

    dvQueued: 'Queued',
    dvSending: 'Sending',
    dvSent: 'Delivered',
    dvFailed: 'Will retry',
    dvDead: 'Given up',
    errResend: 'Resend failed',
    deadCount: '{n} given up',
    allStatuses: 'All statuses',
    noRecordsForStatus: 'Nothing in this status.',
    noRecords: 'No deliveries yet.',
    colKind: 'Kind',
    colChannel: 'Channel',
    colTarget: 'Destination',
    colStatus: 'Status',
    colAttempts: 'Attempts',
    colLastError: 'Last error',
    colUpdatedAt: 'Updated',
    kindReport: 'report',
    kindAlert: 'alert',
    resend: 'Resend',

    encNone: 'None',
    smtpSaved: 'Saved · takes effect on the next mail delivery',
    smtpUnset:
      'No sending server configured yet. Mail destinations will keep failing — reports and alerts go nowhere, and the reason only shows up in the delivery log.',
    smtpHost: 'Server',
    smtpEncryption: 'Encryption',
    smtpEncryptionDesc: 'The port follows it, unless you changed the port yourself',
    smtpPort: 'Port',
    smtpUser: 'Username',
    smtpUserDesc: 'Leave empty if the server requires no authentication',
    smtpPassword: 'Password',
    smtpPasswordSet: 'Stored; leave empty to keep it',
    smtpPasswordUnset: 'An app password or authorisation code',
    smtpFrom: 'From address',
    smtpFromName: 'From name',
    smtpFooter:
      'Once saved, create a mail destination under Destinations and use its Send a test to verify the path end to end. This form only checks the format — whether mail actually goes out is only known after one is sent.',
  },
} satisfies Bundle<NotifyKey>
