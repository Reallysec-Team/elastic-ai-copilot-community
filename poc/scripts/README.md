# 部署 / 演示脚本

PoC 阶段的一键脚本。**仅用于本地演示和 POC**，不是生产部署。

## 文件

| 脚本 | 作用 |
|---|---|
| `setup_demo.ps1` / `setup_demo.sh` | 一键起 docker → 等服务健康 → 加载样本数据 → 初始化 .env |
| `load_sample_data.ps1` / `load_sample_data.sh` | 单独加载 Kibana 样本数据集（默认 web logs） |
| `teardown.ps1` / `teardown.sh` | 销毁 docker 容器和数据卷 |

## 前置条件

- Docker Desktop / Docker Engine（启动中）
- Python 3.10+
- 网络能拉 `docker.elastic.co/elasticsearch:8.12.2` 和 `kibana:8.12.2` 镜像

## 使用

### Windows (PowerShell)

```powershell
# 一键
.\scripts\setup_demo.ps1

# 单独加载样本（可换成 ecommerce / flights）
.\scripts\load_sample_data.ps1 kibana_sample_data_ecommerce

# 销毁（清掉所有 ES 数据，慎用）
.\scripts\teardown.ps1 -Y
```

### Linux / macOS / Git Bash

```bash
chmod +x scripts/*.sh
./scripts/setup_demo.sh
./scripts/load_sample_data.sh kibana_sample_data_flights
./scripts/teardown.sh -y
```

### 环境变量

| 变量 | 默认 | 说明 |
|---|---|---|
| `KIBANA_URL` | `http://localhost:5601` | Kibana 地址（用于 sample data 加载） |

## 幂等性

- `setup_demo` 重复跑：`docker compose up -d` 已起的容器不会重启；样本数据已存在时 Kibana 返回 400，脚本视为成功。
- `load_sample_data` 重复跑：同上。
- `teardown -y` 跳过交互确认；不带 `-y` 会要求 y 确认。

## 故障排查

| 现象 | 解决 |
|---|---|
| `docker: command not found` | 安装 Docker Desktop 并启动 |
| ES 一直起不来 | `docker logs rst-elastic-ai-copilot-poc-es`；通常是内存不够（默认 1GB heap），改 docker-compose.yml 的 `ES_JAVA_OPTS` |
| Kibana 连不上 ES | 等 60-120 秒；Kibana 启动确实慢 |
| 端口冲突（9200 / 5601 已占用） | `docker ps` 看是不是已有 ES/Kibana 实例；或改 docker-compose.yml 端口 |
| 加载样本返回 400 但脚本说成功 | 这是预期：Kibana 对"已安装"返回 400，脚本视为幂等成功 |
| 防火墙挡 docker hub | 配 docker registry mirror（国内常用阿里云、腾讯云的镜像加速） |
| PowerShell 报"无法运行脚本" | `Set-ExecutionPolicy -Scope Process Bypass` 或 `powershell -ExecutionPolicy Bypass -File .\scripts\setup_demo.ps1` |
