# 部署文档 — RST Elastic AI Copilot

面向实施 / 运维。从零到可用的完整流程,已在干净 Ubuntu 主机全链路验证。
本文是**权威部署指南**;专项细节链接到:
[`DEPLOY-RUNBOOK.md`](DEPLOY-RUNBOOK.md)（单用户最短路径）·
[`SSO.md`](SSO.md)（企业 SSO）· [`CONTENT-SIGNING.md`](CONTENT-SIGNING.md)（内容签名）·
[`BACKUP.md`](BACKUP.md)（备份）· [`LLM-PROVIDERS.md`](LLM-PROVIDERS.md)（多模型）。

---

## 1. 概览

- **形态**:仅 Docker。多服务栈,license 强制模块已 Cython 编译进镜像。
- **不带 ES**:连接客户**已有的 Elasticsearch 8.x / Kibana**。
- **默认单副本、网关自带单账号登录**;多用户切 SSO(见 §12)。

```
分析师浏览器 ──HTTPS(443)──▶  Caddy 反代  ──HTTP(内网)──▶  AI 网关(FastAPI)
                             TLS + 登录                        │
                                                               ├─▶ 大模型端点(火山方舟 / 自建 LLM):443
                                                               ├─▶ 客户 Elasticsearch:9200 / Kibana:5601
                                                               └─▶ license.reallysec.com:443（激活/心跳/更新）
```

容器:`rst-elastic-ai-copilot-gateway`、`rst-elastic-ai-copilot-caddy`。

---

## 2. 前提

| 项 | 要求 |
|---|---|
| 主机 | Ubuntu 20.04/22.04/24.04(或等价 Linux),2 vCPU / 4 GB / 20 GB+ |
| 运行时 | Docker Engine 24+ 与 Docker Compose v2 |
| ES | 客户已有 Elasticsearch **8.x**,网关主机网络可达 |
| LLM | `LLM_API_KEY` / `LLM_BASE_URL` / `LLM_MODEL`(火山方舟或任意 OpenAI 兼容端点) |
| 访问名 | 一个**域名**(勿用裸 IP,见 §4) |
| License | 绑本机的 license(§9;先取 GUID/指纹再签发) |

---

## 3. 防火墙:端口与域名

**入站**（放通到网关主机）：

| 端口 | 协议 | 来源 | 用途 |
|---|---|---|---|
| 443 | TCP | 分析师网段 | `https://<域名>/v2/` —— 唯一入口 |
| 80 | TCP | 分析师网段 | HTTP→HTTPS 跳转（可选） |

> 网关 8000 / ES 9200 / Kibana 5601 **不对外**——prod 栈里只在内部网络。
> 云主机记得在**安全组**同步放通 443（本机 ufw/iptables 之外）。

**出站**（网关主机需能访问）：

| 目标 | 端口 | 用途 | 必需 |
|---|---|---|---|
| `license.reallysec.com` | 443 | 激活 + 心跳 + 在线更新下发 | ✅ |
| 大模型端点（如 `ark.cn-beijing.volces.com`） | 443 | 推理 + 向量化 | ✅ |
| 客户 Elasticsearch | 9200 / 9243 | 查询 / 审计 / 知识库 | ✅ |
| 客户 Kibana | 5601 | “在 Kibana 中打开”深链 | 可选 |

**站点地址（域名或 IP）**：`CADDY_SITE_ADDRESS` 填分析师访问用的域名或 IP。

用**裸 IP**（如 `https://10.250.1.82/v2/`）也能用：浏览器直连 IP 字面量按 RFC 6066
不发 SNI，Caddy 靠全局 `default_sni` 兜底取证书（`CADDY_DEFAULT_SNI` 缺省回退到站点
地址）。deploy.sh 会自动写好；手工编辑 .env 时，`CADDY_SITE_ADDRESS` 若填了多个
空格分隔的地址，须另外把 `CADDY_DEFAULT_SNI` 设为其中一个（`default_sni` 只接受单值）。

自签名内部 CA 下，浏览器首次访问 IP 仍会弹证书警告，需分发根证书或手动信任。

长期推荐用**内网域名** + `CADDY_SITE_ADDRESS` 配域名：浏览器正常发 SNI，日后换受信
任证书也顺。无内网 DNS 时，给分析师主机加一条 hosts 记录 `<主机IP> copilot.corp.local`。

---

## 4. 获取交付包

一体包 `RST-Elastic-AI-Copilot-<版本>.tar.gz` = 网关镜像 + 全部部署文件（compose、
Caddyfile、`.env.example`、`deploy.sh`、`deploy/` 更新脚本）。两条取包路径：

**A. 从 GitHub Release（运维标准）**
```bash
gh release download v1.1.1 -R reallysec/RST-Elastic-AI-Copilot
sha256sum -c RST-Elastic-AI-Copilot-1.1.1.tar.gz.sha256   # 校验完整性
```

**B. 自行构建（有网 Linux 机,产品源码目录）**
```bash
scripts/build-release.sh            # → RST-Elastic-AI-Copilot-<版本>.tar.gz [+ .sha256]
```
> 打包/交付走 **Linux**。别从 Windows 工作树直接 tar —— autocrlf 会把 `.sh` 变 CRLF,
> Linux 上跑不了（仓库 `.gitattributes` 已强制 LF,`git clone`/Release 包正常）。

发版流程（厂商侧）：`git tag vX.Y.Z && git push origin vX.Y.Z` → CI 自动构建、打包、
生成 release notes、传 Release。

---

## 5. 安装 Docker（目标主机）

```bash
curl -fsSL https://get.docker.com | sudo sh
sudo usermod -aG docker $USER          # 退出重登生效
docker version && docker compose version
```

---

## 6. 一键部署

把交付包拷到目标主机,解压后进目录跑 `deploy.sh`：

```bash
tar xzf RST-Elastic-AI-Copilot-<版本>.tar.gz
cd RST-Elastic-AI-Copilot-<版本>
./deploy.sh
```

`deploy.sh` 交互引导（已实测流程）：

1. **预检** Docker + 生成 `state/machine-id` 和 `state/server_guid`（license 硬件指纹源，**永不重建**；老安装的 server_guid 会从 `gateway_state` 卷迁出，指纹不变）。
2. **自动 `docker load`** 包内镜像 tar（gateway + caddy）。
3. 选**认证方式**（1 = 网关自带 `/v2` 登录 / 2 = SSO）、**Elasticsearch**（1 = 客户已有）。
4. 填：LLM url/key/model、ES url/账号/密码、Kibana url、**访问域名**。
5. 自动生成内部密钥 → 写 `.env`（权限 600）。
6. `docker compose -f docker-compose.prod.yml up -d` + 等 healthy，打印访问地址 + 管理 token。

**手动备选**（不走交互）：`cp .env.example .env` 填必填项（见 §16）→
`docker load < RST-Elastic-AI-Copilot-images-*.tar` → `docker compose -f docker-compose.prod.yml up -d`。

---

## 7. 冒烟验证

```bash
curl -k https://copilot.corp.local/healthz     # → {"status":"ok"}
curl -k https://copilot.corp.local/readyz      # 看 es_write / license / sso
```

- `/healthz` = 进程存活。
- `/readyz` 的 `es_write` **必须 `ok`**;若 `denied` → ES 账号缺 `.rst_copilot_*` 权限（§8）。
- `sso: disabled`（单用户）、`es ping`（未激活/ES 未通）在此阶段可为非就绪,属预期。

---

## 8. 客户 ES 权限（8.x 启用安全）

给 `ES_USER` 一个角色,至少：

- 客户日志索引（如 `logs-*`）：`read`、`view_index_metadata`。
- 网关自有索引 `.rst_copilot_*`：`create_index`、`read`、`write`、`manage`
  （审计 ILM 数据流 + 每用户状态需要）。这一组目前有 12 个隐藏索引，角色里用通配
  `.rst_copilot_*` 一次覆盖，别逐个列：
  `audit`（审计）、`userstate`（每用户 UI 状态/偏好）、`kb`（知识库向量）、
  `solutions`（NL→DSL 学习库）、`reports`（运营报告）、`analysis`（分析记录）、
  `alerts`（实时告警）、`cursors`（告警拉取游标）、`conversations`（多轮会话，默认
  `RST_CONVERSATION_BACKEND=es`）、`notify_config` / `deliveries`（通知通道与投递
  出站队列）、`assets`（CSV 导入的资产表）。
- 若启用实时告警拉取（`RST_ALERT_INGEST_INDEX=.alerts-security.alerts-default`）：
  对 `.alerts-security.alerts-*` 和 `.internal.alerts-security.alerts-*` 再给
  `read`、`view_index_metadata`。这些是隐藏索引，Kibana 角色页的下拉不会自动补全，
  把模式手敲进去按 Enter 即可；不需要「包含受限索引」开关。

权限不全表现：`/readyz` 的 `es_write=denied`,网关日志 `es_write_denied`。
安全建议：设 `RST_INDEX_WHITELIST=logs-*,filebeat-*` 限制可查询索引。

---

## 9. License 激活（绑本机）

浏览器开 `https://copilot.corp.local/v2/` 登录 → License 页：

**在线**：
1. 复制 **Server GUID**。
2. 交厂商签发绑定该 GUID 的 license。
3. 粘回 → 激活 → 状态 `valid`。

**离线 / 气隙**：
1. 复制 **主机指纹（Host Fingerprint,64 位十六进制）**。
2. 厂商 `issue-offline --fingerprint <指纹> --features ... --with-keyring` 签发。
3. License 页“离线激活”上传 token 文件 → 本地校验+解锁,全程不联网。

> ⚠️ **永不重建 `state/machine-id` / `state/server_guid`** —— 换文件 = 换硬件,license 要重激活。
> 命令行等价:`curl -k -u analyst:<口令> https://.../api/license/server-guid`（或 `.../host-fingerprint`）。

---

## 10. 访问

```
https://copilot.corp.local/v2/
```
用 `admin` + 口令在 `/v2` 表单登录。首次自签证书需在浏览器接受（生产请换客户自有证书,改 Caddyfile）。

---

## 11. 在线更新 / 回滚

在线更新分两段（签名 + 健康门控）：

1. **网关侧**（下载暂存）：网关心跳收到新版 → License/更新页触发下载,或
   `POST /api/admin/release/download`。`release_store` 验签 + 每制品 sha256,
   fail-closed 写入 `./release/staging`。
2. **主机侧**（安装）：
   ```bash
   ./deploy/rst-update.sh              # 载暂存镜像 → 切 GATEWAY_IMAGE_TAG → 健康探测
   ./deploy/rst-update.sh --rollback   # 回上一版
   ```
   `/healthz` 连续 3 次 200 才算成功,否则**自动回滚**。license 状态在 `state/` +
   `gateway_state` 卷,不丢。

---

## 12. 多用户（企业版）

两条路,按客户有没有 IdP 选一条。**不要同时开** —— 开了 SSO 就由 IdP 说了算,
网关自带的密码登录会在启动时被拒绝。

### 12.1 客户没有 IdP：网关自己管账号

账号存在一个**独立 Postgres** 里。不写客户的 Elasticsearch —— 对客户 ES 的
只读承诺不因为要管人就作废。

```bash
# .env
RST_USER_DB_PASSWORD=<32 位随机串>
RST_USER_DB_URL=postgresql://rst:<同上>@userdb:5432/rst_users
```

```bash
docker compose -f docker-compose.prod.yml up -d userdb gateway caddy
```

客户自己有 Postgres 的话,把 `RST_USER_DB_URL` 指过去,别起 `userdb` 服务。

首次启动会建表,并把 `RST_ADMIN_USERNAME` / `RST_ADMIN_PASSWORD_HASH` 这个
账号写成第一个管理员 —— 所以从单账号部署升上来的,原来的口令照旧能进,不
需要另想一套凭据。**没有迁移脚本,也不需要执行任何 SQL。**

之后管理员在 `/api/users` 增删账号、改角色、停用。停用和改角色**立即生效**,
被改的人不用重新登录。

### 12.2 客户有 IdP：SSO

改用 `docker-compose.sso.yml`（Caddy → oauth2-proxy + Keycloak → 网关）。设
`RST_SSO_ENABLED=1` + `RST_SSO_ENFORCE=1` + `RST_GATEWAY_SHARED_SECRET`。账号
由 IdP 管,`RST_USER_DB_URL` 不起作用。完整配置见 [`SSO.md`](SSO.md)。

### 12.3 三档角色

| 角色 | 能做什么 |
|---|---|
| `admin` 管理员 | 全部,含用户管理、设置、Provider、索引白名单等管理操作 |
| `analyst` 分析员 | 除管理操作外的全部,含查询、执行、调查、归档、保存 |
| `viewer` 只读 | 只读。除登录 / 登出 / 改自己口令外,任何写请求一律 403 |

只读是**按 HTTP 方法**在网关拦的,不是逐个接口挂的开关 —— 所以对每一个写接口
都成立,包括以后新增的。

SSO 部署下角色来自 IdP 组:

```bash
RST_RBAC_ADMIN_GROUPS=soc-admins
RST_RBAC_ANALYST_GROUPS=soc-l1,soc-l2
RST_RBAC_VIEWER_GROUPS=auditors
```

一个人在多个组里,取最高的那一档。一个组都不在 = 不给角色,行为跟启用角色前
一样(能写,不能管)。要真正落实只读,把组写进 `RST_RBAC_VIEWER_GROUPS`。

---

## 13. 备份

纳入备份：
- `./state/`（machine-id + server_guid —— 指纹的两半，丢了 license 要重激活）
- `gateway_state` 卷（网关状态）
- `userdb_data` 卷（**账号表**,启用 12.1 时;丢了等于所有人退回只剩首管理员）
- 客户 ES 的 `.rst_copilot_*` 索引（随其快照策略）

脚本:`scripts/backup.sh` / `scripts/restore.sh`。详见 [`BACKUP.md`](BACKUP.md)。

---

## 14. 可选模块

- **安全基线巡检**（等保 2.0 / CIS,读 osquery 结果,确定性、气隙可用）：见
  `DEPLOY-RUNBOOK.md §6`。
- **内容签名**（专用 key 签内容包/在线发布）：默认不启用,基础产品用镜像内置
  license 公钥回落即可。启用见 [`CONTENT-SIGNING.md`](CONTENT-SIGNING.md)。

---

## 15. 故障排查

| 症状 | 排查 |
|---|---|
| 打不开 `/v2/` | `docker compose -f docker-compose.prod.yml logs caddy gateway`;确认入站 443、`CADDY_SITE_ADDRESS` 用域名 |
| HTTPS 握手失败（裸 IP，TLS internal error） | 确认 caddy 传入了 `CADDY_DEFAULT_SNI`（多地址站点须显式设为其一）;`docker restart rst-elastic-ai-copilot-caddy` 生效（`admin off`,reload 不可用） |
| `/readyz` es_write=denied | ES 账号缺 `.rst_copilot_*` 建/写权限（§8） |
| 激活报“无法连接 license 服务器” | 出站到 `license.reallysec.com:443` 是否放通;气隙走离线激活（§9） |
| 查询报错 / 空 | ES 连通?`RST_INDEX_WHITELIST` 是否漏了目标索引;LLM key/endpoint 是否正确 |
| 更新后异常 | `./deploy/rst-update.sh --rollback` 回滚 |
| license 突然失效 | 是否重建过 `state/machine-id` / `state/server_guid`?（换文件=换硬件） |

---

## 16. 附录:`.env` 关键项

```bash
# —— LLM（必填）——
LLM_API_KEY=<key>
LLM_BASE_URL=https://ark.cn-beijing.volces.com/api/v3
LLM_MODEL=<model 或 endpoint id>

# —— 客户 Elasticsearch（必填,本栈不带 ES）——
ES_URL=https://es.corp.local:9200
ES_USER=rst_copilot_gateway
ES_PASSWORD=<password>
# HTTPS + 私有 CA:CA 放 ./certs/es-ca.pem,并:
# RST_ES_VERIFY_CERTS=true
# RST_ES_CA_CERT=/certs/es-ca.pem
RST_INDEX_WHITELIST=logs-*,filebeat-*,winlogbeat-*   # 安全:限制可查询索引
# 查询成本上限(可选,不设走默认)。/api/execute 转发用户给的 DSL,这两个
# 数是网关自己的那道防线;ES 的 max_result_window / search.max_buckets 在
# 它们之后再兜一层。
# RST_MAX_QUERY_SIZE=1000     # from+size 上限(默认 1000)
# RST_MAX_AGG_BUCKETS=10000   # 聚合最多能产出的桶数(默认 10000,嵌套相乘)

# —— 审计（安全产品,建议开）——
RST_AUDIT_ENABLED=1
RST_ILM_BOOTSTRAP=1            # 新部署零接触留存

# —— 网关认证（必填,各 32+ 随机串）——
RST_GATEWAY_SHARED_SECRET=<openssl rand -hex 32>
RST_ADMIN_TOKEN=<openssl rand -hex 32>

# —— Caddy 反代（必填）——
CADDY_SITE_ADDRESS=copilot.corp.local   # 域名或 IP 均可
# CADDY_DEFAULT_SNI=                     # 留空回退到站点地址;站点填多个地址时设为其一(裸 IP 访问必需)
# 登录走网关自带 /v2 表单(默认 admin / Admin@123);生产改口令用下面的
# RST_ADMIN_PASSWORD_HASH,Caddy 不再有 Basic Auth 弹窗。
RST_ADMIN_PASSWORD_HASH=<docker exec rst-elastic-ai-copilot-gateway python -m backend.session_auth 'PWD'>

# —— 可选 ——
# KIBANA_URL=https://kibana.corp.local:5601
# RST_CONTENT_PUBLIC_KEY_PATH=/certs/content_public.pem   # 启用内容签名时
```

> `deploy.sh` 会自动生成密钥 + bcrypt 哈希 + machine-id;手动填时以上为最小集。
