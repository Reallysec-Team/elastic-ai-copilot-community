import ReactMarkdown from 'react-markdown'
import remarkGfm from 'remark-gfm'

import { cn } from '@/lib/utils'

/*
 * 报告正文的 Markdown 渲染。后端 report_render.py 产出的是 GFM：标题、嵌套
 * 列表、加粗、行内代码、引用、表格——所以要 remark-gfm，纯 CommonMark 表格
 * 出不来。
 *
 * 没装 @tailwindcss/typography：这套 prose 只有报告一处用，十来条规则手写比
 * 引一个插件小。不渲染原始 HTML（react-markdown 默认就不渲染），正文来自
 * 后端模板，但报告里会拼进告警字段值，别让它们变成标签。
 */
const PROSE = [
  'text-sm leading-relaxed text-foreground',
  '[&_h1]:mb-3 [&_h1]:text-base [&_h1]:font-semibold',
  '[&_h2]:mt-5 [&_h2]:mb-2 [&_h2]:text-sm [&_h2]:font-semibold',
  '[&_h3]:mt-4 [&_h3]:mb-1.5 [&_h3]:text-sm [&_h3]:font-medium',
  '[&_p]:my-2 [&_ul]:my-2 [&_ol]:my-2 [&_ul]:list-disc [&_ol]:list-decimal [&_ul]:pl-5 [&_ol]:pl-5',
  '[&_li]:my-0.5 [&_li>ul]:my-0.5',
  '[&_strong]:font-semibold',
  '[&_code]:rounded [&_code]:bg-muted [&_code]:px-1 [&_code]:py-0.5 [&_code]:font-mono [&_code]:text-12',
  '[&_pre]:my-2 [&_pre]:overflow-x-auto [&_pre]:rounded-lg [&_pre]:bg-muted [&_pre]:p-3 [&_pre_code]:bg-transparent [&_pre_code]:p-0',
  '[&_blockquote]:my-2 [&_blockquote]:border-l-2 [&_blockquote]:border-warning [&_blockquote]:pl-3 [&_blockquote]:text-muted-foreground',
  '[&_table]:my-2 [&_table]:w-full [&_table]:border-collapse [&_table]:text-12',
  '[&_th]:border-b [&_th]:px-2 [&_th]:py-1.5 [&_th]:text-left [&_th]:font-medium [&_th]:text-muted-foreground',
  '[&_td]:border-b [&_td]:border-border/60 [&_td]:px-2 [&_td]:py-1.5 [&_td]:align-top',
  '[&_hr]:my-4 [&_hr]:border-border',
  '[&_a]:underline [&_a]:underline-offset-2',
].join(' ')

export function Markdown({ children, className }: { children: string; className?: string }) {
  return (
    <div className={cn(PROSE, className)}>
      <ReactMarkdown remarkPlugins={[remarkGfm]}>{children}</ReactMarkdown>
    </div>
  )
}
