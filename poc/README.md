# RST Elastic AI Copilot — PoC

验证一件事：**在 30-50 个测试用例上，自然语言→Elasticsearch DSL 一次可执行率 ≥ 80%**。

## 架构

```
浏览器 ──► FastAPI ──► Volcengine Ark (LLM) ──► DSL
                  └──► Elasticsearch (mapping / search)
```

- 后端：FastAPI（`backend/`），调火山方舟生成 DSL，调 ES 取 mapping + 执行查询
- 前端：单文件 HTML（`static/index.html`），FastAPI 直接 mount
- 数据：Kibana 自带 `kibana_sample_data_logs` 样本
- 评测：`eval/run.py`，跑 `cases.yaml` 输出通过率

## 快速开始

### 1. 起 Elasticsearch + Kibana

```bash
cd poc
docker compose up -d
```

等 30-60 秒，访问 http://localhost:5601 → Home → **Try sample data** → **Other sample data sets** → 加载 **Sample web logs**。

### 2. 配置火山方舟

```bash
cp .env.example .env
# 编辑 .env，填入 LLM_API_KEY 和 LLM_MODEL（接入点 ID）
```

模型选型建议（coding plan 内）：
- **DeepSeek-V3** — 结构化 JSON 输出更稳，首选
- **Doubao-1.5-pro-32k** — 中文场景理解略胜，备选

### 3. 装依赖

PowerShell:
```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1     # PowerShell（首次可能要 Set-ExecutionPolicy -Scope Process Bypass）
pip install -r requirements.txt
```

Git Bash / WSL:
```bash
python -m venv .venv && source .venv/Scripts/activate
pip install -r requirements.txt
```

不想搞 venv 也行，直接 `pip install -r requirements.txt` 装到 user site-packages 也能跑。

> Python 3.14 用户：requirements 已放宽 pydantic 版本，pip 会自动拿 cp314 预编译 wheel；若仍报 PyO3/maturin 编译错误，把 `pydantic` 版本再调高（`pip install -U "pydantic>=2.12"`）或回退到 Python 3.13。

### 4. 构建前端（裸机直跑必做）

后端从 `frontend/dist` 静态 serve v2 UI。**裸机/本地直跑 uvicorn 时，改过前端源码后必须重新构建**，否则浏览器看到的是上一次的旧产物（`dist` 不会自动跟随 `src` 更新）：

```bash
cd frontend && npm install && npm run build && cd ..
```

> Docker 部署不受此影响：镜像构建阶段（`Dockerfile` stage 1）会 `npm run build` 从源码重构 SPA，无需手动执行。仅本地直跑 uvicorn 才需要这步。

### 5. 跑后端 + 打开 UI

```powershell
python -m uvicorn backend.main:app --reload --port 8000
```

> 直接 `uvicorn` 命令找不到？说明装到了 user site-packages 但 Scripts 目录不在 PATH 上。用 `python -m uvicorn` 形式可以绕开。

浏览器开 http://localhost:8000 ，输入问题点"生成 DSL"→"执行查询"。

### 6. 跑评测

```bash
python scripts/seed_eval_data.py      # 先灌数据：文档时间戳按运行时刻生成，
                                      # 隔夜的数据里没有「今天」，时间窗用例会全空
python -m eval.run                    # 全部
python -m eval.run --case top-urls    # 单条
```

两档口径：`executes` = DSL 能在 ES 上跑通（老口径）；`correct` = 还满足该用例
`expect:` 里的结构断言与命中区间（见 `eval/expectations.py`）。一条语法完美的
`match_all` 能拿满第一档，答不出任何东西。

输出形如：
```
[PASS] total-7d              hits=14000 aggs=[]
[PASS] top-clientip-7d       hits=14000 aggs=['top_clients']
[FAIL] daily-trend-30d       execute: parsing_exception ...
[FAIL] count-today           expect: hits 0 < min_hits 1

Executes: 10/10 = 100%  (ran against ES without error)
Correct : 8/10 = 80%    (also satisfied the case's expect:)
Details : eval/last_run.json
```

详细 DSL + 错误存到 `eval/last_run.json`，方便对失败用例做迭代。

## 目录

```
poc/
├── backend/
│   ├── main.py        # FastAPI: /api/generate, /api/execute
│   ├── llm.py         # 火山方舟（OpenAI-compatible）调用
│   ├── es_client.py   # AsyncElasticsearch 封装
│   ├── prompts.py     # System prompt + mapping 扁平化
│   └── validator.py   # 只读 DSL 校验
├── static/
│   └── index.html     # 调试 UI
├── eval/
│   ├── cases.yaml     # 测试用例
│   └── run.py         # 评测脚本
├── docker-compose.yml # ES 8.13 + Kibana 8.13（关安全）
├── .env.example
└── requirements.txt
```

## 当前刻意不做的（PoC 范围之外）

- Kibana 插件 / Vite 前端 / React 组件
- RAG / 知识库
- 字段脱敏
- 多模型路由
- License / 审计 / 用户隔离

这些在 v0.5 MVP 之后再加。PoC 阶段只为一件事：把 NL→DSL 的准确率打到 80%。

## 下一步

1. 用 10 个用例跑出基线准确率
2. 看哪些类型失败（时间表达 / .keyword 误用 / 聚合结构错误 / 字段名漂移）
3. 用 few-shot examples 补强 system prompt，再跑一遍
4. 扩到 30-50 用例，覆盖：错误日志、Nginx、Wazuh、Suricata、Filebeat 常见模式
5. 达到 80% 再考虑下一阶段（RAG / Kibana 插件）
