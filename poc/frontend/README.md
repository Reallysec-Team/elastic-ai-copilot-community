# RST Copilot — v2 UI

React 19 + TypeScript + Vite + Tailwind v4. Visual language is the **Vercel/Geist
design system** (Geist Sans/Mono, shadow-as-border, white canvas, three-weight
typography). The legacy `/static/index.html` UI keeps running side-by-side at
`/`; this app is mounted at `/v2`.

## Dev workflow

```bash
# 1. Backend gateway on :8000
cd poc
python -m uvicorn backend.main:app --port 8000

# 2. Vite dev server on :5173 (proxies /api/* to :8000)
cd poc/frontend
npm run dev
# → http://localhost:5173/v2/
```

Hot reload works as you'd expect. The `vite.config.ts` proxy means there's no
CORS configuration — everything is same-origin.

## Production build

```bash
cd poc/frontend
npm run build
# Build output goes to poc/frontend/dist/, served by FastAPI at /v2.
```

The FastAPI gateway auto-detects `dist/` on startup. After a build, just
restart uvicorn (or hit it as `/v2/` directly — the route is registered
unconditionally if the dir exists). Deep links (`/v2/triage`, `/v2/knowledge-base`) fall
back to `index.html` for SPA routing.

## Structure

```
src/
├── App.tsx               # routes
├── main.tsx              # mount + StrictMode
├── index.css             # Geist tokens + Tailwind v4 @theme block
├── components/
│   ├── AppShell.tsx      # sticky header + nav + license chip
│   ├── DslPreview.tsx    # Geist Mono code block w/ copy
│   ├── ResultTable.tsx   # auto-column-detect ES results
│   └── ui/
│       ├── Button.tsx    # primary / secondary / ghost
│       ├── Input.tsx     # input + textarea (shared field base)
│       ├── Card.tsx      # multi-layer shadow, no CSS border
│       └── Pill.tsx      # badges incl. severity tones
├── lib/
│   ├── api.ts            # typed client for every gateway endpoint
│   └── utils.ts          # cn() — clsx + tailwind-merge
└── routes/
    ├── QueryPage.tsx     # ✅ Round 1 — main flow
    └── PlaceholderPage.tsx
```

## Design rules (don't break these)

1. **Never use a CSS `border` property.** Use `[box-shadow:var(--shadow-ring)]`
   for a 1px line. The shadow-as-border technique is the foundation of the
   Geist look; introducing a real border breaks the rhythm.
2. **Letter-spacing is negative on big text.** -2.4px at 48px, -1.28px at 32px,
   -0.96px at 24px, normal at 14px. The `<h1>` / `<h2>` / `<h3>` base styles
   already handle this; if you write inline sizes, follow the same scale.
3. **Three weights only:** 400 read, 500 interact, 600 announce. No 700.
4. **White canvas, period.** No tinted section backgrounds. Depth comes from
   shadow stacks and the `--color-line` (#ebebeb) divider.
5. **Workflow accents are semantic, not decorative.** `--color-develop` (blue)
   for investigation contexts only. `--color-preview` (pink) for detection
   rules. `--color-ship` (red) for triage urgency. Don't sprinkle them.
6. **Geist Mono uppercase = technical label.** Section eyebrows, column heads,
   metadata labels — use `<LabelMono>` or `.label-mono`.

## What's done in Round 1

- ✅ Vite + React 19 + TS scaffold
- ✅ Tailwind v4 with full Geist token set in `@theme`
- ✅ Shadow-as-border, multi-layer card stack, focus ring system
- ✅ Geist Sans + Mono fonts (`@fontsource-variable/geist*`)
- ✅ Button / Input / Textarea / Card / Pill / LabelMono primitives
- ✅ App shell (sticky header, nav, license chip, footer)
- ✅ Query page (NL → DSL → execute → result table)
- ✅ DSL preview with copy-to-clipboard
- ✅ Result table with auto-column-detect (mirrors old PREFERRED_COLUMNS logic)
- ✅ Vite dev proxy `/api/*` → `:8000`
- ✅ FastAPI mount at `/v2/*` with SPA fallback
- ✅ Placeholder pages for the four pending routes
- ✅ TypeScript clean, production build green (277 KB JS, 23 KB CSS gzipped)

## What's coming (Round 2)

- Investigation modal (Radix Dialog with Geist styling)
- Result table → "调查" / "解释" buttons triggering modals
- Incident report Markdown export modal
- Detection rule page (NL → rule preview → "复制 to Kibana" button)
- Batch triage page (paste alert JSON → cluster table sorted by priority)

## What's coming (Round 3)

- Field dictionary page (table with filter, click-to-insert into question)
- Knowledge base management (upload Runbook, list documents, delete)
- History sidebar (replace old localStorage HISTORY_KEY)
- Multi-turn conversation continuation UI
- Feedback (thumbs up/down on DSL)
