import { renderToStaticMarkup } from 'react-dom/server'
import { describe, expect, it } from 'vitest'

import { Markdown } from './markdown'

/*
 * 报告正文里拼进了告警字段值（主机名、进程名、URL……），那些值是攻击者可控的。
 * 这里钉住 react-markdown 的两条默认行为：原始 HTML 当文本、`javascript:` 链接
 * 被去掉 href。任何一条变了（升级、加了 rehype-raw）都会在这里先红。
 */
describe('Markdown (report body)', () => {
  it('renders raw HTML in field values as text, not tags', () => {
    const html = renderToStaticMarkup(
      <Markdown>{'主机 `web-01` 进程 <img src=x onerror=alert(1)> 触发'}</Markdown>,
    )
    expect(html).not.toContain('<img')
    expect(html).toContain('&lt;img src=x onerror=alert(1)&gt;')
  })

  it('strips javascript: hrefs while keeping the link text', () => {
    const html = renderToStaticMarkup(
      <Markdown>{'来源 [查看详情](javascript:alert(document.cookie)) 。'}</Markdown>,
    )
    expect(html).not.toContain('javascript:')
    expect(html).toContain('查看详情')
  })

  it('keeps ordinary https links', () => {
    const html = renderToStaticMarkup(<Markdown>{'[文档](https://example.com/a)'}</Markdown>)
    expect(html).toContain('href="https://example.com/a"')
  })
})
