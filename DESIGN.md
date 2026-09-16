---
name: RST Elastic AI Copilot
description: A Geist/Vercel-grade design system for an AI security-operations copilot over Elasticsearch.
colors:
  bg: "#ffffff"
  fg: "#171717"
  fg-strong: "#404040"
  fg-muted: "#525252"
  fg-subtle: "#737373"
  fg-faint: "#a3a3a3"
  line: "#ebebeb"
  surface-1: "#fafafa"
  surface-2: "#f4f4f5"
  surface-3: "#f5f5f5"
  ship: "#ff5b4f"
  preview: "#de1d8d"
  develop: "#0a72ef"
  link: "#0072f5"
  focus: "#0070f3"
  code-blue: "#0070f3"
  code-purple: "#7928ca"
  code-pink: "#eb367f"
  badge-bg: "#ebf5ff"
  badge-fg: "#0068d6"
  sev-medium-bg: "#fef3c7"
  sev-medium-fg: "#92400e"
  sev-high-bg: "#fee2e2"
  sev-high-fg: "#991b1b"
  sev-critical-bg: "#171717"
  sev-critical-fg: "#ffffff"
  ok-fg: "#15803d"
  err-fg: "#991b1b"
  dark-bg: "#0a0a0b"
  dark-card: "#161618"
  dark-fg: "#ededed"
  dark-line: "#2a2a2e"
typography:
  hero:
    fontFamily: "Geist Variable, Geist, Arial, sans-serif"
    fontSize: "64px"
    fontWeight: 600
    lineHeight: 1.04
    letterSpacing: "-3.2px"
  display:
    fontFamily: "Geist Variable, Geist, Arial, sans-serif"
    fontSize: "48px"
    fontWeight: 600
    lineHeight: 1.05
    letterSpacing: "-2.4px"
  headline:
    fontFamily: "Geist Variable, Geist, Arial, sans-serif"
    fontSize: "32px"
    fontWeight: 600
    lineHeight: 1.2
    letterSpacing: "-1.28px"
  title:
    fontFamily: "Geist Variable, Geist, Arial, sans-serif"
    fontSize: "24px"
    fontWeight: 600
    lineHeight: 1.33
    letterSpacing: "-0.96px"
  body:
    fontFamily: "Geist Variable, Geist, Arial, sans-serif"
    fontSize: "14px"
    fontWeight: 400
    lineHeight: 1.43
    letterSpacing: "0"
  label:
    fontFamily: "Geist Mono Variable, Geist Mono, ui-monospace, monospace"
    fontSize: "12px"
    fontWeight: 500
    lineHeight: 1
    letterSpacing: "0"
rounded:
  sm: "6px"
  md: "8px"
  lg: "12px"
  xl: "16px"
  pill: "9999px"
spacing:
  xs: "4px"
  sm: "8px"
  md: "12px"
  lg: "20px"
  xl: "48px"
components:
  button-primary:
    backgroundColor: "{colors.fg}"
    textColor: "{colors.bg}"
    rounded: "{rounded.md}"
    padding: "0 16px"
    height: "36px"
  button-secondary:
    backgroundColor: "{colors.bg}"
    textColor: "{colors.fg}"
    rounded: "{rounded.md}"
    padding: "0 16px"
    height: "36px"
  button-pill:
    backgroundColor: "{colors.fg}"
    textColor: "{colors.bg}"
    rounded: "{rounded.pill}"
    padding: "0 16px"
    height: "36px"
  button-ghost:
    backgroundColor: "{colors.bg}"
    textColor: "{colors.fg}"
    rounded: "{rounded.md}"
    padding: "0 16px"
    height: "36px"
  input:
    backgroundColor: "{colors.bg}"
    textColor: "{colors.fg}"
    rounded: "{rounded.md}"
    padding: "8px 12px"
    height: "36px"
  card:
    backgroundColor: "{colors.bg}"
    textColor: "{colors.fg}"
    rounded: "{rounded.lg}"
    padding: "20px"
  pill-badge:
    backgroundColor: "{colors.badge-bg}"
    textColor: "{colors.badge-fg}"
    rounded: "{rounded.pill}"
    padding: "2px 10px"
---

# Design System: RST Elastic AI Copilot

## 1. Overview

**Creative North Star: "The Analyst's Console"**

This is the console an experienced security analyst would build for themselves: a
white, near-silent canvas where the only color on screen is information. It
borrows Vercel's Geist language wholesale (one variable sans, one mono, depth
carried by stacked shadows instead of lines) and bends it toward a SOC: triage
urgency, detection-rule preview, investigation. The premium feel is earned by
restraint and finish, never by ornament. Nothing decorates; everything reports.

Density is dialed per surface. The Query and Triage surfaces can run dense when
an analyst is mid-incident (mono code blocks, tabular numbers, compact pills),
while review surfaces (reports, audit) breathe. The interface is bilingual-aware:
zh-CN body copy sits next to mono uppercase English/technical labels
(`INDEX`, `CONFIDENCE`, `MAX CLUSTERS TO LLM`), which is the system's signature
texture, not an accident.

It explicitly rejects the four anti-references in PRODUCT.md: the gray, gauge-
covered density of legacy SIEM (Splunk/QRadar); the thin "ChatGPT box on a search
bar" AI-chat wrapper; consumer/playful SaaS (mascots, bright gradients, bouncy
motion); and the over-decorated dashboard (hero-metric template, charts for the
sake of charts, identical card grids).

**Key Characteristics:**
- One sans (Geist) + one mono (Geist Mono); no display face.
- No CSS borders anywhere — depth is shadow-as-border.
- Color is semantic only: severity tints + three workflow accents.
- Full light/dark via a `--t-*` token swap on `.dark`.
- Tight negative tracking on headings; mono uppercase for technical labels.

## 2. Colors

A white-and-ink achromatic base where saturated color appears only to carry
meaning: severity, workflow stage, system state.

### Primary
- **Develop Blue** (#0a72ef): The single interactive accent. Primary-action focus
  rings, the hero search-box focus glow, links/develop-class actions
  ("深入调查", investigation). This is the closest thing to a brand color and it
  earns its place by being the analyst's "go" signal.

### Secondary (workflow accents — used only in their semantic context)
- **Ship Red** (#ff5b4f): Triage urgency only. Critical/high cluster rings,
  "TRUNCATED: YES", slow-operation warnings, escalation. Never decorative.
- **Preview Magenta** (#de1d8d): Detection-rule / pre-prod preview artifacts only
  ("转成检测规则", the ShieldCheck action).

### Tertiary (severity tints — light bg + dark text, pill-shaped)
- **Info** (bg #ebf5ff / fg #0068d6), **Low** (#f3f4f6 / #374151),
  **Medium** (#fef3c7 / #92400e), **High** (#fee2e2 / #991b1b),
  **Critical** (#171717 / #ffffff — inverted ink chip, the loudest token in the
  system). Severity is the one place color is allowed to escalate.
- **Code syntax** (#0070f3 blue / #7928ca purple / #eb367f pink): DSL and field
  values inside mono code blocks.

### Neutral (the achromatic ramp — the system's true surface)
- **Ink** (#171717): primary text and the dark-button surface.
- **Strong / Muted / Subtle / Faint** (#404040 / #525252 / #737373 / #a3a3a3):
  the text hierarchy. Body copy lives at Muted or stronger; Faint is placeholders
  and timers only.
- **Line** (#ebebeb): hairline dividers (`CardDivider`, summary-strip splits).
- **Surface 1/2/3** (#fafafa / #f4f4f5 / #f5f5f5): inset chips, toggles, code
  rows, the inner-glow ring on cards.
- **Dark mode** swaps the whole ramp: canvas #0a0a0b, card #161618, ink #ededed,
  line #2a2a2e. Workflow accents and code colors stay fixed across modes.

### Named Rules
**The Meaning-Only Color Rule.** No hue appears on screen unless it encodes
state. White/ink is the resting palette; Develop blue, the workflow accents, and
the severity tints are the only saturated colors, and each is scoped to one
context. If a color shows up as decoration, it's a bug.

**The Inverted-Critical Rule.** `critical` is the only token that flips to a solid
ink fill with white text. Its rarity is the alarm; never reuse the inverted chip
for non-critical emphasis.

## 3. Typography

**Display / Body Font:** Geist Variable (with Geist, Arial, system sans fallback)
**Label / Mono Font:** Geist Mono Variable (with ui-monospace, Menlo, monospace)

**Character:** One humanist-geometric sans does everything from 64px heroes to
14px body; a single mono carries every technical label, code block, ID, and
tabular number. The contrast axis is sans-vs-mono and weight, never two competing
sans faces. Letter-spacing scales negatively with size: heavy negative tracking
on heroes (-3.2px), tightening to 0 at body.

### Hierarchy
- **Hero** (600, 64px / lh 1.04 / -3.2px; `.hero-display`, ↓48px under 900px):
  page-defining screen titles ("让安全运维像聊天一样简单").
- **Display / h1** (600, 48px / -2.4px): standard page title.
- **Headline / h2** (600, 32px / -1.28px): section headings.
- **Title / h3** (600, 24px / -0.96px): card titles.
- **Body** (400, 14px / lh 1.43): default copy. Prose capped at 65–75ch
  (`max-w-[680px]` hero subcopy, `max-w-[400px]` empty-state text). Secondary
  copy sits at Muted (#525252), never lighter for body.
- **Label / mono** (500, 12px, uppercase; `.label-mono` / `LabelMono`): section
  eyebrows and column headers (`INDEX`, `CONFIDENCE`, `ALERTS JSON`). Also the
  18px hero search input — large enough to feel like a primary affordance.
- **Tabular numbers** (`tabular-nums`): all counts, timers, hit totals, ranks.

### Named Rules
**The Mono-Label Rule.** Every technical/section label is Geist Mono, 12px,
uppercase, tracked at 0 — even in a zh-CN interface. This is the system's
fingerprint; don't substitute sans for it. Reserve uppercase for these short
labels only — never on body copy.

## 4. Elevation

This system has no CSS borders. Depth is conveyed entirely by a multi-layer
shadow stack ("shadow-as-border"): a 1px-equivalent ring plus soft ambient
layers, with an inner `--t-s1` glow ring on full cards that gives Geist surfaces
their lift. On dark canvases the black ring is invisible, so every shadow flips
to a translucent-white ring. Motion uses shadow growth (hover, focus) rather than
border-color changes, so transitions stay smooth.

### Shadow Vocabulary
- **Ring** (`0 0 0 1px rgba(0,0,0,0.08)`): the default "border". Buttons, chips.
- **Ring-light** (`0 0 0 1px rgb(235,235,235)`): softer hairline ring for inputs,
  toggles, secondary buttons, inset rows.
- **Card-full** (ring + `0 2px 2px`, `0 8px 8px -8px`, inset `0 0 0 1px #fafafa`):
  the elevated card surface with inner glow.
- **Pop** (ring + `0 8px 24px -12px`, inset ring): dropdowns, mobile sheet,
  popovers.
- **Focus** (`0 0 0 2px var(--color-focus)`): the keyboard focus ring on every
  interactive element.
- **Severity rings** (e.g. `0 0 0 1px var(--color-ship)` on critical clusters):
  status escalation expressed as a colored ring, not a border or fill.

### Named Rules
**The No-Border Rule.** `border` / `border-*` as a visible line is forbidden.
Use `[box-shadow:var(--shadow-ring-light)]` (or a heavier ring) instead. The only
exception is the 1px `--color-line` divider, which is a background-colored `<div>`
(`CardDivider`), not a CSS border.

## 5. Components

### Buttons
- **Shape:** rounded-md (8px) for square variants, rounded-full for pill variants.
  Sizes sm/md/lg map to h-7/h-9/h-11.
- **Primary:** ink fill (#171717), white text, hover `opacity-90`, active
  `scale-[0.98]`. The main CTA.
- **Pill:** same ink fill, fully rounded — the canonical "submit" CTA on workflow
  pages ("开始分诊", "执行查询").
- **Secondary / pill-secondary:** white surface + ring-light, hover to surface-1.
- **Ghost:** transparent until hover (`bg-[var(--t-s3)]`); sub-actions inside
  cards.
- **States:** all share `disabled:opacity-40 disabled:cursor-not-allowed` and a
  `focus-visible` focus ring. Loading swaps the label for a spinning `Loader2` +
  text.

### Pills / Badges
- **Badge (blue):** #ebf5ff bg / #0068d6 fg, fully rounded, 12px/500.
- **Gray:** surface-tint bg + ring-light.
- **Severity:** the five sev-* tone pairs. Tone is passed as a prop; severity
  pills always render the level in UPPERCASE.

### Cards / Containers
- **Corner:** rounded-lg (12px).
- **Background:** `--t-card` (#fff ↔ #161618 dark).
- **Shadow:** card-full (see Elevation) — no border.
- **Structure:** `CardHeader` (px-5 pt-5 pb-3) → `CardDivider` (1px line) →
  `CardBody` → optional `CardFooter`. Headers pair a `LabelMono` eyebrow with
  inline status (confidence pill, hit count, mode toggle).
- **Internal padding:** 20px horizontal (px-5).

### Inputs / Fields
- **Style:** `--t-card` bg, rounded-md, ring-light instead of a border, 14px text,
  faint placeholder (#a3a3a3).
- **Hover:** ring darkens to full ring. **Focus:** 2px focus ring, no outline.
- **Disabled:** surface-1 bg, faint text, not-allowed cursor.
- **Field wrapper:** a `LabelMono` eyebrow above the control, 8px gap.

### Navigation
- **Top bar:** sticky, h-16, max-w-1200. Logo + one primary link ("查询") + three
  `NavDropdown`s (工作流 / 数据 / 运营) + a gear admin menu. Active link goes
  semibold ink; inactive is Muted with hover to ink.
- **Mobile (<900px):** the dropdown bar collapses to a hamburger that opens a
  `shadow-pop` sheet with sectioned mono labels.
- **Command palette:** global ⌘K, mounted once in the shell.

### Signature Components
- **SearchHero:** the 720px hero query box. Two rows (INDEX combobox / 18px
  question input + ink pill CTA with embedded ⌘⏎ kbd), wrapped in
  `.hero-search-ring` which pulls a 2px Develop-blue ring and a soft scale on
  focus-within. The product's front door.
- **HeroBackdrop:** three slow-drifting blurred orbs (blue/pink/warm) behind page
  content at low opacity (0.45 light / 0.22 dark), disabled under reduced-motion.
  The one ambient flourish — kept faint enough to never compete with content.
- **ClusterCard (Triage):** ranked card with `#rank` + severity pill + count +
  time range, a copyable subject `field=value` mono row, recommendation, optional
  LIKELY-FP chip, a status pill-group (处置), and an expand/investigate footer.
  Critical/high clusters get a colored severity ring; handled/FP cards dim to 60%.

## 6. Do's and Don'ts

### Do:
- **Do** use `[box-shadow:var(--shadow-ring-light)]` everywhere you'd reach for a
  border. The No-Border Rule is the system's backbone.
- **Do** keep color semantic: Develop blue for interaction, ship/preview for their
  workflows, sev-* for severity. White/ink is the resting state.
- **Do** label every technical eyebrow with `LabelMono` (Geist Mono, 12px,
  uppercase), even in zh-CN.
- **Do** pair color with text/icon for state (severity level spelled out, license
  dot beside "已激活") so meaning never rides on color alone.
- **Do** use `tabular-nums` for every count, rank, timer, and hit total.
- **Do** give each animation a `prefers-reduced-motion: reduce` path (orbs,
  reveals, staggers already do).
- **Do** keep body copy at Muted (#525252) or stronger; verify 4.5:1 in both
  themes.

### Don't:
- **Don't** add CSS borders (`border`, `border-left`, colored side-stripes). The
  only line is the `CardDivider` background div.
- **Don't** build the gray, gauge-covered density of **legacy SIEM
  (Splunk/QRadar)** — no wall of charts, no buried hierarchy.
- **Don't** let the NL input become a **generic AI-chat wrapper**; it is one
  affordance inside the SOC workflow, not the whole screen.
- **Don't** drift toward **consumer/playful SaaS**: no mascots, no bright
  multi-stop gradients, no bounce/elastic easing, no marketing cheer.
- **Don't** build **over-decorated dashboards**: no hero-metric template (big
  number + gradient + supporting stats), no chart-for-chart's-sake, no identical
  card grids.
- **Don't** use gradient text, glassmorphism as default, or decorative motion.
- **Don't** introduce a third font family or a display face; Geist + Geist Mono
  carry everything.
- **Don't** use the inverted critical chip for anything but `critical` severity.
