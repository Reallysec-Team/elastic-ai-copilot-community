<!-- Community Edition -->
> **RST Elastic AI Copilot — Community Edition.** Apache-2.0. This tree is
> exported from the product repository; the four paid engines (alert triage,
> alert investigation, detection-rule copilot, platform-ops copilot) are not
> included — the UI shows them as "requires a license". Everything else is
> here and runs. A commercial license activates in place, no reinstall.
>
> **Trademark.** "RST", "Reallysec" and the product logos are trademarks of
> Reallysec and are NOT licensed under Apache-2.0. A modified distribution
> must not use them in a way that suggests it is the official product.
>
> **Install.** Either take the prebuilt bundle from this repository's Releases
> (`RST-Elastic-AI-Copilot-<version>.tar.gz`, then `./deploy.sh`), or build the
> gateway image from this tree and run the same compose stack:
>
> ```bash
> docker build -t rst-elastic-ai-copilot-gateway:community .
> cp .env.example .env            # fill LLM_*, ES_*, CADDY_SITE_ADDRESS, secrets
> echo GATEWAY_IMAGE_TAG=community >> .env
> docker compose -f docker-compose.prod.yml up -d
> ```
>
> Docs: https://reallysec.com/docs/elastic-ai-copilot

<h1 align="center">RST Elastic AI Copilot</h1>

<p align="center">
  <b>面向 Elasticsearch & Kibana 的安全运营 AI 层。</b><br>
  自然语言进,可执行 DSL、排清的告警、检测规则出 —— 每个答案都可核验。
</p>

<p align="center">
  <img alt="version"  src="https://img.shields.io/badge/version-v1.1.1-111827">
  <img alt="platform" src="https://img.shields.io/badge/deploy-Docker%20Compose-2496ED">
  <img alt="elastic"  src="https://img.shields.io/badge/built%20for-Elasticsearch%208.x-005571">
  <img alt="license"  src="https://img.shields.io/badge/license-Commercial-6D28D9">
  <img alt="air-gap"  src="https://img.shields.io/badge/air--gapped-supported-059669">
</p>

<p align="center">
  <a href="README.md">English</a> · <b>简体中文</b>
</p>

<p align="center">
  <img src=".github/assets/screenshot-query.png" alt="自然语言查询" width="90%">
</p>

---

RST Elastic AI Copilot 架设在客户**已有的 Elasticsearch / Kibana** 之上,把 SOC 真正在做的活
—— 查询、分诊、写规则、调查 —— 变成自然语言,同时不交出控制权。面向**私有化 / 本地化 /
气隙**部署:数据不出客户网络,每一次模型调用都留痕可审。

它不是搜索框上外挂一个聊天窗。自然语言只是真实分析师工作流里的一个入口,而**信任本身就是
产品**:生成的 DSL、推理过程、审计记录始终摊在桌面上,供分析师核验或推翻。

## 为什么做它

分析师把意图翻译成 ES DSL 和 Kibana 检测规则要耗时间,管理者又看不清 AI 在自己数据上到底
做了什么。本产品同时补上这两个缺口:**自然语言 → 可执行、只读校验的 DSL**,一次成率高,外
围包裹批量分诊、规则生成、引导式调查和完整审计 —— 全部部署在客户自己的边界之内。

## 功能

### 自然语言 → Elasticsearch DSL
用一句话问,得到经**只读**校验的 ES DSL,执行前先看查询。字段字典与响应缓存让它有据可依、
响应快。分析师信了才跑。

### 批量告警分诊
<img src=".github/assets/screenshot-triage.png" alt="批量告警分诊" width="100%">

粘贴一批告警(或从 ES 拉取),自动**归类、定级、排序** —— 高危在最前,每簇附可执行处置建议。
比手工更快清空队列。

### 检测规则生成
<img src=".github/assets/screenshot-detection-rule.png" alt="检测规则生成" width="100%">

描述一种行为,得到带 MITRE ATT&CK 映射的 Kibana 检测引擎规则,可预览、可上线。

### 引导式调查
<img src=".github/assets/screenshot-conversations.png" alt="引导式调查与对话记录" width="100%">

跨步骤保持上下文的多轮调查 —— 新问题独立成题,追问才续上线程。每段对话留存可回溯。

### 知识库(RAG)
<img src=".github/assets/screenshot-kb.png" alt="RAG 知识库" width="100%">

让答案落在客户自己的运行手册与 SOP 上。每个答案都显示引用了哪些知识库文档,影响可见,不藏。

### 报告、仪表盘与审计
<img src=".github/assets/screenshot-reports.png" alt="定时巡检报告" width="100%">
<img src=".github/assets/screenshot-audit.png" alt="每次模型调用的完整审计" width="100%">

定时巡检报告、团队仪表盘,以及**每次模型调用的完整审计**(含 token 用量)—— 管理者能精确复盘
AI 做了什么并向上汇报。

### 以及 SOC 的其余面
- **安全基线巡检** —— 对 osquery 结果做确定性的等保 2.0 / CIS 判定;不调 LLM,气隙可用。
- **资产与身份富化** —— 调查中对实体补充 Elastic 原生上下文。
- **数据脱敏** —— 云 / 私有 / 气隙三档;敏感值不出边界。
- **多模型故障转移** —— 扛住供应商故障;每个答案记录由哪个模型作答。

## 架构

```
分析师浏览器 ──HTTPS(443)──▶  Caddy 反向代理  ──HTTP(内网)──▶  AI 网关(FastAPI)
                             TLS + 登录认证                       │
                                                                  ├─▶ 大模型端点(火山方舟 / 自建 LLM)
                                                                  ├─▶ 客户 Elasticsearch / Kibana
                                                                  └─▶ license.reallysec.com(激活 / 心跳)
```

企业 SSO 形态下,Caddy 与网关之间多一层 oauth2-proxy + Keycloak 前置鉴权。

## 部署

以单一自包含交付包形态发布 —— 网关镜像(license 强制模块已编译为原生二进制)加全部部署文件。
客户主机无需镜像仓库、无需外网。

```bash
tar xzf RST-Elastic-AI-Copilot-<版本>.tar.gz
cd RST-Elastic-AI-Copilot-<版本> && ./deploy.sh
```

`deploy.sh` 载入镜像、生成密钥、写配置,把服务栈拉起在 Caddy TLS 之后。它连接客户**自己的**
Elasticsearch —— 不自带 ES。

完整指南:**[`docs/DEPLOYMENT.md`](docs/DEPLOYMENT.md)**(端口、DNS、激活、在线更新、排障)·
单用户最短路径 [`docs/DEPLOY-RUNBOOK.md`](docs/DEPLOY-RUNBOOK.md) ·
内容签名 [`docs/CONTENT-SIGNING.md`](docs/CONTENT-SIGNING.md)

## 安全与授权

- **生而私有** —— 运行在客户边界内;分析师浏览器是唯一入口(443),出站仅限大模型、客户 ES、
  license 服务器。
- **默认对客户数据只读**;审计与 UI 状态存在网关自有的 `.rst_copilot_*` 索引。
- **license 强制** —— 在线激活,支持离线 / 气隙令牌;强制模块在镜像内编译为原生二进制。
- **健康门控在线更新**,失败自动回滚;发布包与内容包均签名验证。

商业软件。© ReallySec。授权与试用请联系厂商。

---

<p align="center"><sub>面向 SOC / MDR / 等保 / 国产化 · Elasticsearch 8.x · Docker</sub></p>
