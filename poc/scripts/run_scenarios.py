#!/usr/bin/env python3
"""Drive the product through enterprise ops/security scenarios and grade it.

Pairs with `seed_ops_scenarios.py`, which plants a known answer in each data
stream. Each scenario here asks the question an operator would actually type,
then checks that the product (a) produced a runnable query, (b) returned
something, and (c) surfaced the specific evidence the story was seeded with.

That third check is the point. "The DSL executed" only proves the plumbing
works; "the answer contains 203.0.113.77" proves the operator would have
actually found the brute force.

Usage:
  RST_URL=http://localhost:18765 RST_PASSWORD=... python scripts/run_scenarios.py
  ... python scripts/run_scenarios.py --only 3,7,15     (subset)
  ... python scripts/run_scenarios.py --out report.md
"""
import json
import os
import re
import sys
import time
import urllib.error
import urllib.request
from http.cookiejar import CookieJar

BASE = os.environ.get("RST_URL", "http://localhost:18765").rstrip("/")
USER = os.environ.get("RST_USER", "admin")
PASSWORD = os.environ.get("RST_PASSWORD", "")

SEC = "logs-linux.auth-default"
SYS = "logs-linux.syslog-default"
NGX = "logs-nginx.access-default"
NGE = "logs-nginx.error-default"
DOC = "logs-docker.container-default"
K8S = "logs-k8s.events-default"
JVM = "logs-app.java-default"
SQL = "logs-mysql.slowlog-default"
MET = "metrics-system-default"
WIN = "logs-windows.system-default"
ALL_OPS = ",".join([SEC, SYS, NGX, NGE, DOC, K8S, JVM, SQL, MET, WIN])

# (id, area, index, question, expected substrings — any one counts as found)
SCENARIOS = [
    # ── Security operations ────────────────────────────────────────────────
    (1, "SOC/Linux", SEC, "最近一周有没有 SSH 暴力破解？是哪个 IP 打的",
     ["203.0.113.77"]),
    (2, "SOC/Linux", SEC, "203.0.113.77 这个 IP 有没有成功登录过？登的是哪个账号",
     ["deploy", "success"]),
    (3, "SOC/Linux", SEC, "最近一周哪些账号执行过 sudo 提权到 root",
     ["sudo", "root"]),
    (4, "SOC/Web", NGX, "有没有人在扫描我们的网站？列出探测路径最多的来源 IP",
     ["198.51.100.23"]),
    (5, "SOC/Linux", SEC, "凌晨 0 点到 6 点之间成功登录的账号有哪些",
     ["deploy", "appuser", "ops", "root", "jenkins", "dbadmin"]),
    (6, "SOC/Windows", WIN, "哪台 Windows 服务器的服务在反复异常终止",
     ["SVC-WIN-02", "7031"]),

    # ── Linux host operations ──────────────────────────────────────────────
    (7, "Linux", SYS, "有没有进程被 OOM killer 杀掉？发生在哪台机器",
     ["db-prod-01", "mysqld"]),
    (8, "Linux", SYS, "哪台机器磁盘要满了？有没有 No space left 的报错",
     ["web-prod-02"]),
    (9, "Linux", MET, "db-prod-01 最近三天的内存使用率，按小时看趋势",
     ["db-prod-01"]),
    (10, "Linux", SYS, "最近一周有哪些 systemd 服务重启过",
     ["mysqld", "restart", "Restart"]),

    # ── Containers / Kubernetes ────────────────────────────────────────────
    (11, "容器", DOC, "哪个容器因为内存超限被杀掉了（OOMKilled）",
     ["payment-svc", "137"]),
    (12, "容器/K8s", K8S, "有没有 pod 在 CrashLoopBackOff？是哪个",
     ["payment-svc", "BackOff"]),
    (13, "容器/K8s", K8S, "有哪些 pod 镜像拉不下来",
     ["report-svc", "1.4.0-rc2", "Failed"]),
    (14, "容器", DOC, "按容器名统计错误日志数量，哪个容器错误最多",
     ["payment-svc", "redis-cache"]),

    # ── Applications / middleware ──────────────────────────────────────────
    (15, "应用", JVM, "order-svc 最近报的错误里，最多的是什么",
     ["Hikari", "Connection is not available", "SQLTransientConnectionException"]),
    (16, "应用", JVM, "最近的空指针异常出现在哪个类？把堆栈给我看看",
     ["CheckoutService", "NullPointerException"]),
    (17, "应用", JVM, "有没有 GC 停顿超过 2 秒的服务",
     ["payment-svc", "Full GC", "gc"]),
    (18, "数据库", SQL, "最慢的 SQL 查询是哪条？扫了多少行",
     ["orders", "customers"]),

    # ── Network / gateway ──────────────────────────────────────────────────
    (19, "网络", NGX, "/api/checkout 什么时候开始大量返回 5xx？按小时统计",
     ["502", "504", "500"]),
    (20, "网络", NGE, "nginx 上游超时指向哪个后端地址",
     ["app-prod-02:8080", "10.30.9.22"]),

    # ── Cross-index incident reconstruction ────────────────────────────────
    (21, "跨源", ALL_OPS, "结账接口今天下午出故障了，把相关的错误都找出来",
     ["checkout", "Hikari", "payment-svc", "502"]),
]


def build_opener():
    return urllib.request.build_opener(urllib.request.HTTPCookieProcessor(CookieJar()))


OPENER = build_opener()


def call(path, payload=None, method=None, timeout=180):
    data = json.dumps(payload).encode("utf-8") if payload is not None else None
    r = urllib.request.Request(f"{BASE}{path}", data=data, method=method or ("POST" if data else "GET"))
    r.add_header("Content-Type", "application/json")
    try:
        with OPENER.open(r, timeout=timeout) as resp:
            body = resp.read().decode("utf-8")
            return resp.status, body
    except urllib.error.HTTPError as e:
        return e.code, e.read().decode("utf-8")
    except Exception as e:  # noqa: BLE001 — a transport failure is a scenario result too
        return 0, str(e)


def login():
    status, body = call("/api/auth/login", {"username": USER, "password": PASSWORD})
    return status < 300, body[:200]


def generate(index, question):
    """Non-streaming generate, so this script does not need an SSE parser."""
    status, body = call("/api/generate", {"index": index, "question": question})
    if status >= 300:
        return None, f"generate HTTP {status}: {body[:220]}"
    try:
        d = json.loads(body)
    except json.JSONDecodeError:
        return None, f"generate: unparsable body {body[:200]}"
    if not d.get("dsl"):
        return None, "no DSL: " + str(d.get("validation_error") or d.get("explanation", ""))[:220]
    return d, None


def execute(index, dsl, question):
    status, body = call("/api/execute", {"index": index, "dsl": dsl, "question": question})
    if status >= 300:
        return None, f"execute HTTP {status}: {body[:220]}"
    try:
        return json.loads(body), None
    except json.JSONDecodeError:
        return None, "execute: unparsable body"


def hit_total(res):
    t = (res.get("hits") or {}).get("total")
    if isinstance(t, dict):
        return t.get("value", 0)
    return t or 0


def bucket_count(res):
    """Rows an aggregation answer actually produced."""
    n = 0
    for v in (res.get("aggregations") or {}).values():
        if isinstance(v, dict) and isinstance(v.get("buckets"), list):
            n += len(v["buckets"])
    return n


def evidence_found(res, expects):
    blob = json.dumps(res, ensure_ascii=False)
    return [e for e in expects if e.lower() in blob.lower()]


def run_one(sid, area, index, question, expects):
    t0 = time.time()
    gen, err = generate(index, question)
    if err:
        return {"id": sid, "area": area, "q": question, "verdict": "GEN_FAIL", "note": err,
                "secs": round(time.time() - t0, 1)}
    res, err = execute(index, gen["dsl"], question)
    if err:
        return {"id": sid, "area": area, "q": question, "verdict": "EXEC_FAIL", "note": err,
                "secs": round(time.time() - t0, 1), "dsl": gen["dsl"]}
    hits, buckets = hit_total(res), bucket_count(res)
    found = evidence_found(res, expects)
    if hits == 0 and buckets == 0:
        verdict, note = "EMPTY", "查询成功但 0 结果"
    elif not found:
        verdict, note = "NO_EVIDENCE", f"有结果({hits} hits / {buckets} buckets)但没出现预期证据 {expects}"
    else:
        verdict, note = "PASS", f"{hits} hits / {buckets} buckets · 命中证据 {found}"
    return {"id": sid, "area": area, "q": question, "verdict": verdict, "note": note,
            "secs": round(time.time() - t0, 1), "conf": gen.get("confidence"),
            "expl": (gen.get("explanation") or "")[:160], "dsl": gen["dsl"]}


def main():
    only = None
    if "--only" in sys.argv:
        only = {int(x) for x in sys.argv[sys.argv.index("--only") + 1].split(",")}
    out_path = None
    if "--out" in sys.argv:
        out_path = sys.argv[sys.argv.index("--out") + 1]

    ok, note = login()
    if not ok:
        print(f"login failed: {note}", file=sys.stderr)
        return 1

    rows = []
    for sid, area, index, question, expects in SCENARIOS:
        if only and sid not in only:
            continue
        r = run_one(sid, area, index, question, expects)
        rows.append(r)
        print(f"[{r['verdict']:12}] #{sid:2} {area:10} {r['secs']:5.1f}s  {question[:38]}")
        print(f"               {r['note'][:190]}")

    tally = {}
    for r in rows:
        tally[r["verdict"]] = tally.get(r["verdict"], 0) + 1
    print("\n" + "  ".join(f"{k}={v}" for k, v in sorted(tally.items())))

    if out_path:
        with open(out_path, "w", encoding="utf-8") as f:
            f.write("# 场景测试结果\n\n")
            f.write("| # | 领域 | 判定 | 耗时 | 可信度 | 问题 | 说明 |\n|---|---|---|---|---|---|---|\n")
            for r in rows:
                f.write(f"| {r['id']} | {r['area']} | {r['verdict']} | {r['secs']}s | "
                        f"{r.get('conf', '-')} | {r['q']} | {r['note'][:170]} |\n")
            f.write("\n\n## 生成的查询\n\n")
            for r in rows:
                f.write(f"### #{r['id']} {r['q']}\n\n")
                f.write(f"- 判定: **{r['verdict']}** · {r['note']}\n")
                if r.get("expl"):
                    f.write(f"- 模型说明: {r['expl']}\n")
                if r.get("dsl"):
                    f.write("```json\n" + json.dumps(r["dsl"], ensure_ascii=False, indent=2) + "\n```\n")
                f.write("\n")
        print(f"\nreport -> {out_path}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
