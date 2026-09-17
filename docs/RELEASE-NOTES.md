# Release Notes

Customer-facing changes per release. Versions are the gateway image tag
(`GATEWAY_IMAGE_TAG` in `docker-compose.prod.yml`), which is also what the
delivery archive is named after.

---

## 1.1.24 — 2026-09-17

Four fixes found while standing up the public demo (aisoc.reallysec.com).
No schema or `.env` changes required; one optional new key.

### 修复

- **周报再也不会静默丢失。** 报表归档索引 `.rst_copilot_reports` 之前由
  第一份日报动态建映射，`boundary_key="2026-09-17"` 被推断成 date，随后
  周报的 `2026-W38` 写入 400，daily+weekly 同开的部署每个周期都丢周报。
  现在索引带显式映射（`boundary_key` keyword）。已有索引不动；如果你的
  周报历史为空、日志里有 `report_persist_failed … boundary_key`，删掉该
  索引让网关重建即可（报表可重新生成）。
- **重启后 AI 不再「消失」。** 在「AI 设置 → 向量化」保存后，
  `state/llm_providers.yml` 只有 `embedding:` 段，网关重启时把它当成
  「配置了 0 个供应商」，`LLM_API_KEY / LLM_MODEL` 被整体忽略，所有 AI
  功能报 `No LLM providers configured`。现在没有 `providers:` 段就回落到
  环境变量；显式 `providers: []` 仍表示故意不配。
- **安全基线按主机平台判定。** 引擎原来把全部规则跑在每台主机上，Linux
  主机被 36 条 Windows 规则（on_missing=fail）判 fail，干净的 Ubuntu 只有
  70 分出头。现在读上报里的 `host.os.*` 判平台，只跑本平台规则；上报里没有
  os 字段（老 Agent）时保持旧行为。
- **告警摄取冷启动窗口可配。** 新增 `RST_ALERT_INGEST_LOOKBACK`（如 `7d`），
  第一次拉取时回溯多久；默认仍是 `1h`。之前对已有几周检测告警的索引开摄取，
  只能拿到最近一小时。
- **在线更新第一次真正能从交付镜像跑通。** 网关侧下载器用的是 `requests`，
  而交付镜像里只有 `httpx`——从任何交付包出发，「下载更新」都会 500
  `No module named 'requests'`（7 月的验证用的是本机构建镜像，没暴露）。
  改用 httpx。**注意：装着 ≤1.1.23 的现场拿不到这次更新的在线推送，
  这一版要用离线包升级；之后的版本才能走在线通道。**
- **`./release` 暂存目录权限。** compose 首次启动把它建成 root:root 755，
  网关以 uid 10001 跑，下载到暂存时 PermissionError。现在容器入口和
  `/app/state` 一样接管它的属主。`rst-update.sh` 在目录不可写时明确提示
  用 sudo，而不是误报「另一个更新在跑」。
- `deploy/rst-update.sh` 的 `COMPOSE_FILE` 支持 docker 自己的冒号写法
  （`docker-compose.prod.yml:my-overlay.yml`），带覆盖层的部署也能走在线更新。

---

## 1.1.23 — 2026-09-16

Login page only. No gateway behaviour changes.

### 登录页

- Layout follows ReUI auth-20: plain background, one 26rem card, the title
  「登录 Elastic AI Copilot」at the page-title scale. The header keeps the
  wordmark and the language / theme toggles (icons only); the footer keeps
  the copyright line.
- The mandatory「我已阅读并同意《服务条款》和《隐私政策》」checkbox is gone,
  and so are the two documents. It only lived in the browser's localStorage,
  so it never recorded consent; on-prem obligations sit in the purchase
  contract, not on each analyst's login. The Sign in button is no longer
  greyed out.
- 「没有账号？…」hint and the chat tagline under the title removed.

---

## 1.1.22 — 2026-09-16

Packaging release. No gateway behaviour changes; two delivery bugs and the
docs link.

### 升级须知

- **Same-directory upgrade now actually upgrades.** The documented path —
  unpack the new bundle over the install directory, run `./deploy.sh`,
  keep `.env` — loaded whichever `RST-Elastic-AI-Copilot-images-*.tar`
  sorted first (the *old* one), left `GATEWAY_IMAGE_TAG` alone and printed
  部署完成 on the previous version. `deploy.sh` now loads every bundle in
  the directory and switches to the newest tag. Upgrading **to** 1.1.22 with
  the 1.1.21 script: delete the old images tar first, or check
  `docker inspect rst-elastic-ai-copilot-gateway --format '{{.Config.Image}}'`
  afterwards.
- **GitHub Release bundles up to v1.1.21 carried no paid features.** The
  four sealed engines (告警分级 / 告警调查 / 检测规则 / 功能管理助手) are
  release artifacts outside git; the CI build had none and shipped an
  empty `premium/`, so those bundles reported "license cannot unlock this
  feature" for every licence. Bundles built by hand were fine. CI now
  restores the blobs from a secret and the build fails closed without
  them. If you installed from a GitHub Release asset, upgrade to 1.1.22.

### 界面

- 侧栏「帮助中心」「文档」指向 https://reallysec.com/docs/elastic-ai-copilot.

---

## 1.1.21 — 2026-09-15

Speed release. Smart query used to sit on a blank screen for 30 seconds to
five minutes before the first character appeared; now it is 1.5–6 seconds.
No screen changes beyond a progress strip and one new dropdown. **Read
升级须知 if you run an offline (air-gapped) license.**

### 智能查询快了一个数量级

Every "thinking" model (豆包 / GPT-5 / Claude / Qwen3 / Gemini 2.5 …)
reasons before it answers. The gateway was letting it reason on *every*
call — picking an index, suggesting angles, summarising a result — and each
of those cost 30–90 seconds. Reasoning is now graded per task: off for the
quick helper calls, low for NL→DSL, high only for triage / investigation /
detection rules / agentic runs, and the gateway translates that grade into
each vendor's own parameter. Measured: first token 30–300 s → 1.5–6 s;
angle suggestions 80 s → 1–2 s; NL→DSL eval 28/30 at low vs 29/30 with full
reasoning.

- AI 设置 → provider → **推理强度** `auto | 关 | 低 | 高`. Pick 关 if your
  private model is too slow, 高 if you only care about accuracy.
- While a query generates you now see 理解问题 → 生成查询 → 执行 with the
  model's reasoning behind a collapsed 「AI 在想」.
- A query whose first character does not arrive within 45 s is aborted with
  a retry prompt instead of hanging (`RST_LLM_FIRST_TOKEN_TIMEOUT_S`).
- Aggregation queries get the same dry-run as document queries: an
  aggregation-level ES error is fed back to the model for one repair round
  before you see it.
- A failing embedding endpoint no longer slows every question: after one
  failure the gateway skips it for 60 s (`RST_EMBED_COOLDOWN_S`).

### 会话不再留空壳

A conversation is created only once its first turn completes; every turn
carries a state (进行中 / 完成 / 失败 / 已中止). The conversation list
shows a badge per state, replaying history respects it, and a turn whose
gateway died mid-generation is reaped into 失败 instead of spinning forever.

### 许可

- License expired or revoked? You can still **log in, log out, change
  your password and deactivate** — the licence page is reachable to fix
  it. Before 1.1.21 an invalid licence blocked the login itself.
- 许可 → 激活 accepts the `.lic` file as issued (JSON envelope), not only
  the bare token pasted out of it.

### 升级须知

- **`state/server_guid` is new and joins `state/machine-id` as the host
  fingerprint.** Until now half of the fingerprint lived inside the
  `gateway_state` Docker volume, so losing the volume (`down -v`, a renamed
  compose project) silently changed the fingerprint and killed the licence
  while `state/machine-id` was intact. `./deploy.sh` copies the existing
  value out of the volume on upgrade — the fingerprint does not change.
  Manual installs: `docker cp rst-elastic-ai-copilot-gateway:/app/state/server_guid state/server_guid`
  **before** `up -d`, never generate a new one. Back up `./state/` as a whole.
- **Offline (air-gapped) licences issued before 2026-09-11** still lack the
  keys for 告警分级 / 告警调查 / 功能管理助手 — ask for a re-issued `.lic`.
  Online licences need nothing.
- Four new `.env` keys, all optional with sane defaults (see
  `.env.example`): `LLM_REASONING`, `RST_NL2DSL_REASONING`,
  `RST_LLM_FIRST_TOKEN_TIMEOUT_S`, `RST_EMBED_COOLDOWN_S`.
- If you use OpenAI o-series / GPT-5, the 高 grade sends
  `reasoning_effort=high`, which bills more than the vendor default; leave
  the provider on `auto` unless you need it.

---

## 1.1.20 — 2026-09-11

Licensing release. No new screens; what changes is which capabilities are
paid, and how the paid ones are protected. **Read 升级须知.**

### 收费能力收成四项，其余全部免费

Paid, on every tier that lists them: 告警批量分级, 告警调查, 检测规则生成,
功能管理助手. Everything else — including **多轮追问** and **all three
field-masking modes (cloud / private / airgapped)** — is free on every tier,
trial included. Masking is how you protect your own data before it leaves the
cluster; charging a tier to be more careful never made sense.

### 四个付费引擎全部加密交付

Until now only the detection-rule engine shipped sealed (SEC-CC-1); the other
paid features were a plain permission check. All four engines now ship as
encrypted blobs. The key for each is issued by the license server, only to
tiers that include the feature, and bound to the activated host. A gateway
whose license does not include a feature cannot run it — not by
configuration, not by patching.

### 试用 = 标准版 14 天

A trial license is the Standard tier on a 14-day clock: all four paid
capabilities, one node. Before this release a trial license granted *less*
than an unactivated gateway did. The free tier is the open-source Community
Edition, not a reduced trial.

### 心跳修复（重要）

Since 1.1.5 (2026-07-11) an activated **online** license never completed a
heartbeat: an import error inside the heartbeat path failed every cycle,
silently. Revocations, content packs and engine key updates never reached
the gateway. Fixed. **Upgrade to 1.1.20 before expecting the three newly
sealed engines to unlock** — the keys arrive over the first successful
heartbeat after upgrade (within 5 minutes). Offline licenses were unaffected.

### 升级须知

- **Unactivated (demo) mode no longer runs the four paid features.** Until
  now an unactivated gateway ran everything under a daily quota; from 1.1.20
  the four paid engines need an activated license. Trial licenses are free —
  <https://reallysec.com/products/elastic-ai-copilot/trial>. Everything
  else keeps working unactivated, under the same quota as before.
- Existing online licenses pick up their new feature keys on the first
  successful heartbeat after upgrading (see 心跳修复) — nothing to do. Offline (air-gapped) licenses issued before
  2026-09-11 do not carry keys for the three newly sealed features; ask for
  a re-issued offline token if you use 告警分级 / 告警调查 / 功能管理助手.
- `RST_MASKING_MODE` / the settings-page masking mode now accept all three
  values on any tier. No `.env` changes.

---

## 1.1.19 — 2026-09-11

The largest release since 1.0. Every page was rebuilt, the appliance gained
users and roles, and the whole UI is bilingual. **Read 升级须知 before
upgrading** — three `.env` keys change behaviour.

### 界面重做，地址一个没变

All 19 pages were rebuilt on a single shell: two-level sidebar, per-page top
tabs, one time-range picker everywhere, one result table, one index picker.
Every URL and deep link (`/v2/alerts?alert=<id>`, `?rule=<keyword>`) still
works. New first screen: **安全态势** (posture) — what is on fire right now,
before you ask anything.

### 中英双语

Language switch in the account menu. Backend errors now carry a code, so the
English UI no longer shows Chinese sentences.

### 用户与角色

Optional Postgres user table (`RST_USER_DB_*`). Three roles: 管理员 / 分析师 /
只读. Read-only accounts can query, investigate and triage but cannot change
anything; buttons they cannot use stay focusable and say why (keyboard and
screen-reader users get the reason too). Pages only an administrator can read
say so instead of showing an error. Without a user table the single `admin`
account keeps working as before.

### 安装完在界面上配 Elastic

A fresh install prompts for the ES connection on first login and proves it
reachable before saving — no more editing `settings.yml`. ES credentials and
the audit / alert secrets are no longer stored in plaintext on the state
volume.

### 智能查询

Picks the index for you (you can still pin one). Understands the time range
stated in the question and syncs the picker to it. A repeat of the same
question starts a fresh conversation instead of narrowing the previous one.

### 实时告警、通知、报告

Alerts ingest from the `.alerts-security` alias or a Kibana webhook
connector. Notifications: Teams, Slack, 钉钉, 企业微信, SMTP; delivery targets
and history on their own page. Daily patrol reports archived and listed.
Alert summaries skipped for budget are now marked as such, not shown as
broken.

### 安全加固

The gateway no longer runs as root (dropped to uid 10001 at start; existing
root-owned state volumes are fixed up automatically). Container capabilities
reduced to the five the entrypoint needs. Alert webhook auth no longer
collides with the login gate. Two concurrent admin demotions can no longer
leave zero administrators. `/metrics` can require a token.

### 许可档位

The tier map now matches the product page: three tiers (trial / standard /
enterprise). Four paid capabilities — 告警分级、告警调查、检测规则、功能管理助手.
Multi-turn conversation and all three field-masking modes are included in
every tier, trial included. Apply `deploy/license/tiers.json` on the license
server when rolling this out.

### 升级须知

New in `.env` (all optional; defaults keep the 1.1.18 behaviour unless noted):

- `RST_TIMEZONE` — **set this.** It is how the model interprets "今天" and how
  the trial quota resets. Default `UTC`; most deployments want `+08:00`.
- `RST_REPORT_TZ` — **behaviour change:** when unset it now follows
  `RST_TIMEZONE` (was: UTC). A deployment that only set `RST_TIMEZONE` will see
  the daily report boundary move from 00:00 UTC to local midnight.
- `RST_USER_DB_URL` / `_USER` / `_PASSWORD` / `_NAME` — Postgres for the user
  table. Unset = single `admin` account, as before.
- `RST_METRICS_TOKEN` — unset = `/metrics` stays open, as before.
- `RST_ALERT_INGEST_CONCURRENCY`, `RST_ALERT_INGEST_BUDGET_S` — bound the LLM
  work one webhook push may trigger.
- `RST_ES_VERIFY_CERTS`, `RST_ES_CA_CERT` — TLS to a self-signed cluster.

`settings.yml` moved into the state volume; the old file is migrated on first
start. SSO deployments: `docker-compose.sso.yml` had three YAML errors that
prevented it from parsing at all — fixed; the RBAC group mapping gained
`RST_RBAC_ANALYST_GROUPS` and `RST_RBAC_VIEWER_GROUPS`.

---

## 1.1.18 — 2026-07-25

Removes the second login. This changes `.env`: see below before upgrading.

### 只剩一次登录

The appliance used to challenge you twice: the browser's own username/password
popup (Caddy Basic Auth) and then the app's `/v2` login form. The popup is gone.
Login is now only the `/v2` form — the single `admin` account.

Why: the app login (added 1.1.16) already gates every page, so the Caddy popup
was a second credential to distribute and reset for no extra protection — and its
password could not be recovered from the stored hash, only reset.

### 升级须知(改了 .env)

The Caddy service no longer reads `CADDY_BASIC_AUTH_USER` / `CADDY_BASIC_AUTH_HASH`,
and `docker-compose.prod.yml` no longer *requires* the hash to start. On an
existing deployment the two lines in `.env` are now simply ignored — nothing to
do, but you may delete them.

Because the popup is the only thing that was gone, **make sure the app login
password is not the published default**: set `RST_ADMIN_PASSWORD_HASH` in `.env`
(generate it with `docker exec rst-elastic-ai-copilot-gateway python -m
backend.session_auth '<new-password>'`). Without it the sole gate is
`admin` / `Admin@123`, which is printed in the manual.

SSO deployments (`docker-compose.sso.yml`) are unaffected — they never used Basic
Auth.

---

## 1.1.17 — 2026-07-24

Usability release. Every change is in the web UI or in an error message; no
configuration changes, no migration: replace the image and restart.

### 可以退出登录了

Sign-in is on by default and the session cookie is HttpOnly, so until now the
only way to end a session was to clear browser data — awkward on a shared
workstation. The gear menu and the mobile menu now carry 退出登录, and show which
account is signed in above it. Deployments with sign-in disabled see neither.

A session that expires while you sit on one page used to break every button
silently — generate, execute, save, all failing with no explanation. You are now
returned to the login screen, and (since 1.1.16) back to the page you were on.

### 查询页

- **继续追问不再清空屏幕.** The previous answer and its results stay while you
  type the next question. Reading the last turn is the reason you are asking a
  follow-up.
- **改「取前 N」立即重新查询.** It reads as a live filter, so it now behaves like
  one instead of waiting for another 执行查询 click.
- **「存为快捷查询」有回执了.** Saving now confirms the name and tells you where
  the query reappears. Previously a save, a failure and a no-op looked identical.
- **「全部送分诊」不再多送.** Triage processes at most 100 alerts per batch and
  discarded the remainder without saying so. The hand-off is now capped at the
  source and states how many of how many were taken.
- **回车即查询.** Pressing Enter in the search box did nothing at all; only
  Ctrl/Cmd+Enter worked. Enter now runs the query, and confirming a Chinese input
  method candidate no longer submits by accident.

### 批量分诊

- **时间窗在粘贴模式下也可见.** The field only appeared when reading alerts from
  Elasticsearch, but it also governs the context 深入调查 pulls — pasted alerts
  were pinned to 60 minutes with no control on screen.
- **载入历史分诊后「深入调查」查对索引.** Re-opening a saved run and drilling into
  a cluster queried the default alert index instead of the one the run came from.
  Saved runs now record the index per cluster. Runs saved before this release
  keep the old behaviour.

### 导航

- The top-nav dropdowns show the one-line description each entry always carried,
  and the colour marking a feature as 预览 / 正式 is visible again on entries with
  an icon.
- ⌘K / Ctrl+K reaches 基线巡检, 实时告警 and AI 配置管理, which were missing from
  the palette.
- The login page's show-password button showed the wrong icon.

### For operators

- Rate-limit rejections (HTTP 429) now answer in Chinese, state how many seconds
  to wait, and carry a standard `Retry-After` header. The message was previously
  the sole English string in the interface.

---

## 1.1.16 — 2026-07-23

Reliability release for natural-language → DSL generation. No configuration
changes, no migration: replace the image and restart.

### 智能查询更少失败

One model slip caused four out of five failed generations: the brace closing the
query object went missing, so the explanation and confidence fields were
swallowed into the query itself. It surfaced either as "AI 返回格式错误" or as
Elasticsearch rejecting `Unknown key for a VALUE_STRING in [explanation]`.

The gateway now repairs that class of output instead of failing on it:

- unterminated strings and unclosed brackets are closed (append-only — nothing
  the model wrote is edited or dropped);
- fields that landed inside the query are lifted back out;
- `date_histogram.interval`, removed in Elasticsearch 8 but still emitted by
  models trained on 7.x, is rewritten to `calendar_interval` / `fixed_interval`;
- before the DSL reaches you, its query clause is checked against Elasticsearch.
  If Elasticsearch rejects it, the model is asked once more with the actual error
  — most often invalid date math such as `now/M-1ms`. The retry has its own
  45-second budget (`RST_LLM_CORRECTION_TIMEOUT_S`), so a slow provider cannot
  double the wait, and a failed retry always leaves the original result standing.

Measured over 30 rounds of the 30-case evaluation suite: **91.5% → 98.3%**.

### 说明文字讲结论，不复述查询

Generated explanations used to narrate the DSL already on screen — which field
was filtered, what `size` and `track_total_hits` were set to. They now state what
the query answers. DSL jargon dropped from 19.3% of explanations to 0%, average
length from 46 to 27 characters. The same constraint was applied to detection
rule explanations.

### 登录后回到原来要去的页面

Opening a link to a specific page while logged out sent you to the login screen
and then to the home page. You now land on the page you asked for. Shared links,
bookmarks and links inside alert notifications work in one step.

### 文案一致性

- Deleting a knowledge base document now says 不可撤销, matching every other
  destructive confirmation.
- The dashboards empty state says 当前态势 rather than 当前 ES 状态, which read
  as cluster health.
- The 深入调查 tooltip is worded the same on the alerts and triage pages.

### For operators

- **New environment variable**: `RST_LLM_CORRECTION_TIMEOUT_S` (default 45)
  bounds the corrective LLM round-trip described above. Unset is fine.
- Every generation now issues one extra `_validate/query` call to Elasticsearch.
  It parses the query without executing it and is cheap, but it does appear in
  Elasticsearch's request count.
- The evaluation harness (`python -m eval.run`, for vendor use) now reports two
  rates: whether the DSL executes, and whether it satisfies the case's structural
  expectations. The CI gate enforces both at 80%.

---

## Earlier releases

Not documented here. See `git log` between the version tags.
