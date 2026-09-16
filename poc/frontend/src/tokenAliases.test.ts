import { readFileSync } from 'node:fs'
import { fileURLToPath } from 'node:url'
import { describe, expect, it } from 'vitest'

/*
 * 语义 token 的别名表。
 *
 * 全站有 400 多处写法从 `text-[var(--t-fg-subtle)]` 这种直接引用原始变量，换成了
 * `text-muted-foreground` 这种语义类名。那次替换之所以敢说「零视觉变化」，靠的
 * 完全是 `index.css` 别名层里已经存在的一行赋值：
 *
 *     --muted-foreground: var(--t-fg-subtle);
 *
 * 也就是说两种写法解析出来是同一个值，明暗两端都是。
 *
 * 这个前提没有任何东西守着 —— 有人把 `--accent` 从 `--t-s1` 改成别的，那 46 处
 * 就会在没人察觉的情况下换掉颜色，而且是「换对了名字之后」才出的问题，比原来
 * 更难查。这个测试就是那道守。
 *
 * 用截图比对做门试过，不行：这个界面显示实时数据（审计条数、试用额度、时间戳），
 * 两次跑之间本来就会变，噪声盖过信号。别名表是确定性的，钉它。
 */

const CSS = readFileSync(
  fileURLToPath(new URL('./index.css', import.meta.url)),
  'utf8',
)

/** 语义 token → 它必须指向的原始变量。左边这一列就是替换后用的类名词根。 */
const ALIASES: Record<string, string> = {
  foreground: '--t-fg',
  'muted-foreground': '--t-fg-subtle',
  card: '--t-card',
  accent: '--t-s1',
  secondary: '--t-s2',
  'primary-foreground': '--t-on-fg',
  'destructive-foreground': '--t-err-fg',
  'success-foreground': '--t-ok-fg',
  success: '--t-ok-dot',
  'info-foreground': '--t-info-fg',
  warning: '--t-warn-fg',
  border: '--t-line',
  destructive: '--color-ship',
  info: '--color-develop',
}

/*
 * 第二批别名，跟上面那批的区别只在写在 `index.css` 的哪个块里：这些落在
 * `@theme` / `@theme inline`（Tailwind 靠它们生成 `text-fg-muted`、
 * `bg-destructive-subtle` 这些类名），而不是中间那段 shadcn 别名层，所以
 * `lightBlock()` 找不到它们，得对整份 CSS 断言。
 *
 * 文字灰阶原来是两套：`--color-fg-*` 是遗留的 Geist 十六进制（#4d4d4d /
 * #666666 / #808080），`--t-fg-*` 是现行的 oklch，值接近但都不相等。前者当时
 * 全站零消费，所以直接让它转发给后者，105 处 `text-[var(--t-fg-muted)]` 才换
 * 得成类名。这些断言守的就是「转发」这件事本身。
 */
const THEME_ALIASES: Record<string, string> = {
  'color-fg': '--t-fg',
  'color-fg-strong': '--t-fg-strong',
  'color-fg-muted': '--t-fg-muted',
  'color-fg-subtle': '--t-fg-subtle',
  'color-fg-faint': '--t-fg-faint',
  'color-fg-disabled': '--t-fg-disabled',
  'color-destructive-subtle': '--t-err-bg',
  'color-success-subtle': '--t-ok-bg',
  'color-info-subtle': '--t-info-bg',
  'color-warning-subtle': '--t-warn-bg',
}

/** `:root` 之后、`.dark` 之前的那段别名层。 */
function lightBlock(): string {
  const start = CSS.indexOf('shadcn token alias layer')
  expect(start, '别名层的段落注释不见了，index.css 结构变了').toBeGreaterThan(-1)
  const dark = CSS.indexOf('\n.dark {', start)
  return CSS.slice(start, dark > -1 ? dark : undefined)
}

describe('语义 token 的别名表', () => {
  const block = lightBlock()

  for (const [token, raw] of Object.entries(ALIASES)) {
    it(`--${token} 指向 var(${raw})`, () => {
      const re = new RegExp(`--${token}:\\s*var\\(${raw}\\)\\s*;`)
      expect(
        re.test(block),
        `--${token} 不再是 var(${raw})。全站有一批 ${token} 类名是按这条等价关系` +
          `从 [var(${raw})] 换过来的 —— 改这一行会静默改掉它们的颜色。`,
      ).toBe(true)
    })
  }

  /* s1/s2/s3 明暗两端都是同一个值，`--accent: var(--t-s1)` 在 .dark 里写的是
     `var(--t-s2)`。上面那条替换（t-s1 → accent）依赖的正是这个巧合，写下来免得
     以后有人把三档拆开时不知道这里挂着东西。 */
  it('s1 / s2 / s3 在明暗两端都是同一个值', () => {
    for (const scope of [':root', '.dark']) {
      const i = CSS.indexOf(`\n${scope} {`)
      expect(i, `${scope} 块不见了`).toBeGreaterThan(-1)
      const seg = CSS.slice(i, i + 2000)
      const vals = ['--t-s1', '--t-s2', '--t-s3'].map((v) => {
        const m = new RegExp(`${v}:\\s*([^;]+);`).exec(seg)
        return m?.[1].trim()
      })
      expect(new Set(vals).size, `${scope} 里 s1/s2/s3 不再同值：${vals.join(' / ')}`).toBe(1)
    }
  })

  for (const [token, raw] of Object.entries(THEME_ALIASES)) {
    it(`--${token} 转发给 var(${raw})`, () => {
      expect(
        new RegExp(`--${token}:\\s*var\\(${raw}\\)\\s*;`).test(CSS),
        `--${token} 不再转发给 ${raw}。它是 Tailwind 生成类名用的，写死一个值` +
          `就等于在 ${raw} 之外再开一套并存的色阶。`,
      ).toBe(true)
    })
  }

  /* `--t-fg-*` 自己在 `.dark` 里翻，所以 `--color-fg-*` 只要转发就跟着翻。若有人
     在 `.dark` 里补一行覆盖，明暗两端就又分叉成两套灰阶，而且只有深色模式下才
     看得出来。 */
  it('.dark 里没有再覆盖 --color-fg-*', () => {
    const i = CSS.indexOf('\n.dark {')
    expect(i, '.dark 块不见了').toBeGreaterThan(-1)
    const seg = CSS.slice(i, CSS.indexOf('\n}', i))
    expect(seg.match(/--color-fg[a-z-]*:/g) ?? []).toEqual([])
  })

  /* codemod 特意没碰 --color-line：它是 #ebebeb，而 --border 走的是 --t-line
     （oklch(0.922)）。两个值接近但不相等，换过去是可见改动。 */
  it('--color-line 和 --t-line 仍然是两个不同的值', () => {
    const line = /--color-line:\s*([^;]+);/.exec(CSS)?.[1].trim()
    const tLine = /--t-line:\s*([^;]+);/.exec(CSS)?.[1].trim()
    expect(line).toBeTruthy()
    expect(tLine).toBeTruthy()
    expect(line).not.toBe(tLine)
  })
})

describe('替换之后不该再冒出直接引用原始变量的写法', () => {
  /* 这一条盯的是新代码。已知还剩一批没有语义别名的（--t-fg-muted / --t-fg-faint
     / --t-err-bg 之类），那是判断题不是替换题，所以这里只禁已经有别名的那些。 */
  it('已经有语义别名的原始变量不再出现在工具类里', async () => {
    const { glob } = await import('node:fs/promises')
    const root = fileURLToPath(new URL('.', import.meta.url))
    const banned = Object.values(ALIASES).map((v) => v.replace('--', ''))
    const re = new RegExp(
      `\\b(?:bg|text|border|ring|fill|stroke|from|to|via|shadow|outline|decoration|caret|accent|divide|placeholder)-\\[var\\(--(${banned.join('|')})\\)\\]`,
    )
    const offenders: string[] = []
    for await (const entry of glob('**/*.{ts,tsx}', { cwd: root })) {
      // 这个文件自己的注释里就举了被禁的例子，跳过。
      if (entry.endsWith('tokenAliases.test.ts')) continue
      const src = readFileSync(new URL(entry, new URL('./', import.meta.url)), 'utf8')
      const m = re.exec(src)
      if (m) offenders.push(`${entry}: ${m[0]}`)
    }
    expect(offenders, `改用语义类名，别名表见 ${'tokenAliases.test.ts'}`).toEqual([])
  })
})

/*
 * 字号阶梯。全站原来写的是 `text-[12px]` 这种任意值 —— 只设 font-size，行高继承。
 * 换成 Tailwind 的 `text-xs` 不是零变化：它那一档连行高一起设（0.75rem / 1rem）。
 * 所以另起了一套只设字号的档位，名字就是像素值。
 *
 * 这条测试守的是「只设字号」这个前提：谁给某一档补上行高，348 处的行高会在没人
 * 察觉的情况下一起变，而且是「换成了规范写法之后」才出的问题。
 */
describe('字号阶梯', () => {
  const STEPS: Record<string, string> = {
    '10': '0.625rem',
    '11': '0.6875rem',
    '12': '0.75rem',
    '13': '0.8125rem',
    '14': '0.875rem',
    '15': '0.9375rem',
    '16': '1rem',
    '18': '1.125rem',
  }

  for (const [name, value] of Object.entries(STEPS)) {
    it(`--text-${name} 是 ${value}（${Number(value.replace('rem', '')) * 16}px）`, () => {
      const re = new RegExp(`--text-${name}:\\s*${value.replace('.', '\\.')}\\s*;`)
      expect(re.test(CSS), `--text-${name} 不再是 ${value}`).toBe(true)
    })
  }

  it('每一档都只设字号，没有行高', () => {
    for (const name of Object.keys(STEPS)) {
      const re = new RegExp(`--text-${name}:[^;]*;`)
      const m = re.exec(CSS)
      expect(m, `--text-${name} 不见了`).toBeTruthy()
      // Tailwind 的 `--text-<n>--line-height` 是给档位补行高的写法。
      expect(
        CSS.includes(`--text-${name}--line-height`),
        `--text-${name} 补了行高 —— 这一套的全部意义就是不动行高`,
      ).toBe(false)
    }
  })

  it('组件里不再写这几个像素值的任意字号', async () => {
    const { glob } = await import('node:fs/promises')
    const root = fileURLToPath(new URL('.', import.meta.url))
    const px = Object.keys(STEPS).map((n) => `${n}px`)
    const re = new RegExp(
      `text-\\[(?:${px.join('|')}|0\\.625rem|0\\.6875rem|0\\.8125rem)\\]`,
    )
    const offenders: string[] = []
    for await (const entry of glob('**/*.{ts,tsx}', { cwd: root })) {
      if (entry.endsWith('tokenAliases.test.ts')) continue
      const src = readFileSync(new URL(entry, new URL('./', import.meta.url)), 'utf8')
      const m = re.exec(src)
      if (m) offenders.push(`${entry}: ${m[0]}`)
    }
    expect(offenders, '改用 text-10 / text-12 这套档位').toEqual([])
  })
})
