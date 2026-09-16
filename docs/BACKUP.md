# 数据备份与恢复

Elastic AI Copilot 的持久化数据分两块,备份方式不同。

| 数据 | 在哪 | 备份方式 |
|---|---|---|
| 网关配置 / License 激活记录 / 配额 / server_guid | `gateway_state` 卷(`/app/state`) | `scripts/backup.sh` |
| 反馈失败用例 | 容器内 `/app/eval/failed_cases.yaml` | `scripts/backup.sh`(一并) |
| 账号 / 角色(企业版多用户) | `userdb_data` 卷(Postgres) | `pg_dump`,见 §1.1 |
| 审计日志 | ES 索引 `.rst_copilot_audit*` | ES 快照 |
| 知识库(RAG) | ES 索引 `.rst_copilot_kb*` | ES 快照 |

> 多轮对话上下文只在内存里(1 小时 TTL),不需要也无法备份。

---

## 1. 网关状态备份(脚本)

```bash
bash scripts/backup.sh [备份目录]      # 默认 ./backups
```

产物:`gateway-state-<时间戳>.tar.gz`(+ `failed_cases-<时间戳>.yaml`)。
脚本自动保留 30 天、清理更早的。

> **这个 tar 包等价于明文。** `/app/state` 里同时有 `settings.yml`(五个敏感值是
> `enc:v1:` 密文)和解密它们的 `.rst_secret_key`,拿到包就等于拿到 ES 密码、SMTP
> 口令、webhook secret。备份目录按 `chmod 700` 存,离机保存要再加一层加密。
>
> 反过来也成立:**恢复必须带上 `.rst_secret_key`**。用 `RST_SECRET_KEY` 环境变量
> 而不是密钥文件的部署,这个包里没有钥匙 —— 换机恢复时同一个环境变量也要带过去,
> 否则 `settings.yml` 解不开,界面上只会显示成「没设置」。

**建议挂 cron**(每日 02:00):

```cron
0 2 * * * cd /opt/rst-copilot && bash scripts/backup.sh /backup/rst-copilot >> /var/log/rst-backup.log 2>&1
```

恢复:

```bash
bash scripts/restore.sh /backup/rst-copilot/gateway-state-XXXX.tar.gz \
                        /backup/rst-copilot/failed_cases-XXXX.yaml
docker compose -f docker-compose.prod.yml restart gateway
```

### 1.1 账号表(启用 `RST_USER_DB_URL` 时)

账号和角色在独立的 Postgres 里,`scripts/backup.sh` 不碰它。

```bash
docker exec rst-elastic-ai-copilot-userdb     pg_dump -U rst rst_users > /backup/rst-copilot/users-$(date +%F).sql
```

恢复:

```bash
docker exec -i rst-elastic-ai-copilot-userdb psql -U rst rst_users < users-XXXX.sql
docker compose -f docker-compose.prod.yml restart gateway
```

丢了这个卷不会让部署打不开:网关重新建表,并把 `.env` 里的
`RST_ADMIN_USERNAME` / `RST_ADMIN_PASSWORD_HASH` 重新种成第一个管理员。但其他
所有账号都没了,得重建。

---

## 2. ES 索引备份(审计 / 知识库)

审计与知识库数据在 Elasticsearch 里,用 ES 原生**快照**备份(这也是等保对
审计日志留存的要求)。

**一次性:注册快照仓库**(`path.repo` 须先在 `elasticsearch.yml` 配好):

```
PUT /_snapshot/rst_copilot_backup
{ "type": "fs", "settings": { "location": "rst_copilot_backup" } }
```

**定期:打快照**(建议每日 cron):

```
PUT /_snapshot/rst_copilot_backup/snap-20260522?wait_for_completion=true
{ "indices": ".rst_copilot_audit*,.rst_copilot_kb*", "include_global_state": false }
```

**恢复**:

```
POST /_snapshot/rst_copilot_backup/snap-20260522/_restore
{ "indices": ".rst_copilot_audit*,.rst_copilot_kb*" }
```

> 形态 A(接客户已有 ELK):并入客户现有的 ES 快照策略即可,把上面两个索引
> 模式加进客户的快照 indices 列表。
> 形态 B(自带全栈):给 `docker-compose.prod.yml` 的 `elasticsearch` 服务
> 加一个 `path.repo` 卷,再按上面注册仓库。

---

## 3. 恢复演练

备份只有验证过能恢复才算数。**上线前至少演练一次**:在一台测试机
`restore.sh` + ES `_restore`,确认网关起来后 License `valid`、审计/知识库数据齐全。

## 4. 留存周期

| 数据 | 建议留存 |
|---|---|
| 网关状态 | 30 天(脚本默认) |
| 审计日志快照 | ≥ 180 天(按等保要求,通常 6 个月起) |
| 知识库快照 | 按需,通常 30–90 天 |
