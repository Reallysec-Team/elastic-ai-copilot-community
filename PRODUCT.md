# Product

## Register

product

## Users

Chinese-speaking (zh-CN) security operations teams: front-line SOC analysts and
the team leads / managers above them.

- **Analysts** are the primary daily users. Their context is high-pressure and
  interrupt-driven: triaging alert backlogs, writing ad-hoc queries against
  Elasticsearch during an active incident, authoring detection rules, running
  investigations. They live in the Query, Triage, Detection-Rule, and
  Investigation surfaces. Speed and trust matter more than discovery; they know
  what they want and need the tool to get out of the way.
- **Managers / leads** are secondary. They consume the Reports, Dashboards,
  Audit, and Conversation-history surfaces to understand team output, review
  every AI call, and report up. Their context is calmer and review-oriented.

The shared job to be done: turn intent expressed in natural language into
correct, executable Elasticsearch DSL and Kibana detection-engine rules, then
triage and investigate the results, without leaving the copilot.

## Product Purpose

RST Elastic AI Copilot is an AI layer over Elasticsearch / Kibana for security
operations. Its core promise is natural-language → executable DSL with a high
first-run success rate, surrounded by the workflow a SOC actually runs: batch
alert triage with clustering and prioritization, NL-authored detection rules,
guided investigation, a RAG-backed knowledge base of customer runbooks/SOPs, a
field dictionary, and a full audit trail of every model call. It ships with
licensing, quotas, and SSO/forward-auth for enterprise deployment.

Success looks like: an analyst trusts a generated query enough to run it without
hand-checking the DSL, clears a triage queue faster than by hand, and a manager
can audit exactly what the AI did. The tool earns its place by being correct and
fast, not by being novel.

## Brand Personality

Modern, premium, polished. Quiet confidence carried by visual craft, not
decoration. The voice is precise and technical without being terse; it speaks
the analyst's language (DSL, indices, severities, MITRE) and never dumbs things
down. Emotionally it should read as *trustworthy under pressure*: composed,
legible, fast. The premium feel comes from restraint and finish (typography,
spacing, shadow-as-border, motion that conveys state) rather than from color or
ornament.

## Anti-references

- **Legacy SIEM (Splunk / QRadar / ArcSight).** No cluttered gray enterprise
  density, no wall of gauges, no buried hierarchy. Information density is earned
  per surface, never the default.
- **Generic AI-chat wrapper.** This is not a ChatGPT box bolted onto a search
  bar. The NL input is one affordance inside a real SOC workflow, not the whole
  product.
- **Consumer / playful SaaS.** No mascots, no bright multi-stop gradients, no
  bouncy/elastic motion, no marketing cheer in a serious security tool.
- **Over-decorated dashboards.** No hero-metric template (big number + gradient
  + supporting stats), no chart-for-the-sake-of-chart, no identical card grids.

## Design Principles

1. **The tool disappears into the task.** Earned familiarity over novelty.
   Standard affordances (top nav + dropdowns, command palette, dialogs, tables)
   behave exactly as a Linear/Stripe-fluent user expects.
2. **Trust is the product.** Every AI output is inspectable: show the DSL, the
   reasoning, the audit record. Never ask the user to trust a black box; let
   them verify and override.
3. **Density is dialed per surface, not global.** Query and Triage can run dense
   when the analyst needs it; review and report surfaces breathe. Match the
   altitude to the user's mode.
4. **Restraint carries the premium feel.** Color is semantic (severity tints,
   workflow accents ship/preview/develop), never decorative. Hierarchy comes
   from type scale, weight, and the shadow-as-border system, not from borders or
   fills.
5. **State is always legible.** Loading, empty, error, success, disabled, and
   selected are first-class. Empty states teach the surface; errors say what
   happened and what to do next.

## Accessibility & Inclusion

- Target **WCAG 2.1 AA**. Body text ≥ 4.5:1, large/bold text ≥ 3:1, including
  the muted-foreground tokens and placeholders, in both light and dark themes.
- **Full dark mode** is a first-class theme (`.dark` token swap), not an
  afterthought; contrast is verified in both.
- **Keyboard + focus**: visible focus rings (`focus-visible` 2px focus color),
  command palette and dialogs fully operable by keyboard, logical tab order.
- **Reduced motion**: every animation (hero orbs, reveals, staggers) has a
  `prefers-reduced-motion: reduce` path that disables or crossfades.
- **Localization**: primary UI is zh-CN; keep copy translatable and avoid layout
  that breaks when string lengths change between Chinese and English.
- Don't encode meaning in color alone (severity, license state): pair with text
  or icon labels.
