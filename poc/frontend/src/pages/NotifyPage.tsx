import { HugeiconsIcon } from '@hugeicons/react'
import { AlertCircleIcon } from '@hugeicons/core-free-icons'

import { useT } from '@/lib/i18n'
import { commonCopy } from '@/locales/common'
import { notifyCopy } from '@/locales/notify'
import { Alert, AlertDescription } from '@/components/reui/alert'
import {
  Frame, FrameHeader, FramePanel, FrameTitle,
} from '@/components/reui/frame'
import { PageHeader } from '@/components/shell/page-header'
import {
  DeliveriesBlock, ScheduleBlock, TargetsBlock, useNotifyConfig,
} from '@/components/notify/NotifyConfigPanel'
import { SmtpBlock } from '@/components/notify/SmtpBlock'
import { AuditCard } from '@/components/settings/audit-card'
import { Tabs, TabsContent, TabsList, TabsTrigger } from '@/components/ui/tabs'
import { HintTip } from '@/components/hint-tip'

/*
 * 对外通道 —— 报告和告警往产品外面走的所有出口。
 *
 * 原名「投递与通知」。改名的原因不是好听：审计转发之后也归到这一族，那就不止是
 * 「通知」了 —— 这一页回答的是「有什么东西会离开这套系统，走哪条路」。
 *
 * 原来是系统设置页尾的一张卡，那时只有飞书一个渠道，放页尾是对的。渠道多起来
 * 之后它需要的是一屏：都有谁、各自通不通、发失败的那几条怎么办。
 *
 * 三块的顺序就是排障顺序：先看目标（配了什么）→ 再看记录（发出去没有）→
 * 发件服务器排最后（只有邮件目标用得上）。
 */
export function NotifyPage() {
  const t = useT(notifyCopy)
  const c = useT(commonCopy)
  const { config, setConfig, loading, error } = useNotifyConfig()

  return (
    <div className="@container flex w-full flex-col gap-5">
      <PageHeader title={t('title')} />

      {error && (
        <Alert variant="destructive">
          <HugeiconsIcon icon={AlertCircleIcon} strokeWidth={2} className="size-4" />
          <AlertDescription>{error}</AlertDescription>
        </Alert>
      )}

      {/* 四个出口是同一段设置的四张脸，所以整组是一个区块；卡壳按模板那套
          （`Frame dense` + 「标题 + 一句说明」的卡头 + 面板本身带内边距）。 */}
      <section aria-label={t('secOutlets')}>
        <Tabs defaultValue="targets" className="w-full min-w-0 flex-col gap-5">
          <TabsList>
            <TabsTrigger value="targets">{t('tabTargets')}</TabsTrigger>
            <TabsTrigger value="deliveries">{t('tabDeliveries')}</TabsTrigger>
            <TabsTrigger value="smtp">{t('tabSmtp')}</TabsTrigger>
            <TabsTrigger value="audit">{t('tabAudit')}</TabsTrigger>
          </TabsList>

          <TabsContent value="targets">
            <Frame dense className="w-full min-w-0">
              <FrameHeader>
                <FrameTitle className="text-balance">{t('tabTargets')}</FrameTitle>
              </FrameHeader>
              <FramePanel className="flex flex-col gap-2.5">
                {loading ? (
                  <p className="py-6 text-center text-sm text-muted-foreground">{c('loading')}…</p>
                ) : config ? (
                  <>
                    <ScheduleBlock config={config} onSaved={setConfig} />
                    <TargetsBlock config={config} onChanged={setConfig} />
                  </>
                ) : null}
              </FramePanel>
            </Frame>
          </TabsContent>

          <TabsContent value="deliveries">
            <Frame dense className="w-full min-w-0">
              <FrameHeader>
                {/* 「已放弃」不是「失败」：它是重试到头了，除非有人来重投，这条
                    永远发不出去。客户看到的现象只是「报告没收到」。这句进问号。 */}
                <FrameTitle className="flex items-center gap-1.5 text-balance">
                  {t('tabDeliveries')}
                  <HintTip text={t('deliveriesDesc')} />
                </FrameTitle>
              </FrameHeader>
              {/* 表格自己画内边距和边线，panel 再套一层就是双层。 */}
              <FramePanel className="p-0!">
                <DeliveriesBlock />
              </FramePanel>
            </Frame>
          </TabsContent>

          <TabsContent value="smtp">
            <Frame dense className="w-full min-w-0">
              <FrameHeader>
                <FrameTitle className="flex items-center gap-1.5 text-balance">
                  {t('tabSmtp')}
                  <HintTip text={t('smtpDesc')} />
                </FrameTitle>
              </FrameHeader>
              <FramePanel>
                {loading ? (
                  <p className="py-6 text-center text-sm text-muted-foreground">{c('loading')}…</p>
                ) : config ? (
                  <SmtpBlock config={config} onSaved={setConfig} />
                ) : null}
              </FramePanel>
            </Frame>
          </TabsContent>
          {/* 审计转发自带一份只管那六个键的草稿和自己的保存浮条 —— 和上面三块
              （存在 ES 里的投递配置）不是同一份存储，所以不共用保存动作。 */}
          <TabsContent value="audit">
            <AuditCard />
          </TabsContent>
        </Tabs>
      </section>
    </div>
  )
}

export default NotifyPage
