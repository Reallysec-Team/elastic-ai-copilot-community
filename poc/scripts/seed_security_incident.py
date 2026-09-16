#!/usr/bin/env python3
"""Seed ONE realistic intrusion, told from every angle the product can look at.

Why this exists: the demo alerts were synthetic placeholders — `host-2`,
`rule-4`, subjects that appear in no log index. Open one and 深入调查 searches
for evidence, finds nothing, and the investigation can only say "无法确认告警真
实性". That is a true statement about fake data, and it means the whole
investigation surface has never been exercised against a case with real
evidence behind it.

So: one attack, seeded end to end, anchored to `now`.

  T-7h05 → T-6h35   203.0.113.77 brute-forces SSH on web-prod-03 (~380 fails)
  T-6h34            ONE success — svc_backup. Foothold.
  T-6h31            recon: id / uname / cat /etc/passwd
  T-6h28 → T-6h22   sudo abuse: three refusals, then root
  T-6h18            reads /etc/shadow, ~/.ssh/id_rsa, /var/backups/*.sql.gz
  T-6h12            stages an archive in /tmp/.cache/
  T-6h08 → T-5h28   C2 beacon to 185.243.115.84:4444, every 60s
  T-26h             (separate, unrelated) sqlmap scan on web-prod-01

Everything interlocks on the two identifiers a SOC actually pivots on — the
host `web-prod-03` and the account `svc_backup` — so an investigation that
searches for either finds the whole chain, and one that searches the source IP
finds where it came in.

The alerts are written in the Kibana detection-alert shape into
`.alerts-security.alerts-default`, which is what the gateway polls; they go
through the product's real ingest path (normalize → summarize → store), not
straight into the product's own index. Two of them are deliberately benign —
a backup job and a monitoring probe — because an alert list where everything
is a real attack teaches nobody anything about triage.

Usage:
    ES_URL=http://localhost:9200 python scripts/seed_security_incident.py
    ES_URL=... python scripts/seed_security_incident.py --purge

`--purge` deletes what a previous run of THIS script wrote (matched on
`labels.seed = rst-incident-001`) before seeding again. It never touches
anything else: the ops-scenario data and the toy alerts are left alone.
"""
import json
import os
import random
import sys
import urllib.error
import urllib.request
from datetime import datetime, timedelta, timezone

ES_URL = os.environ.get("ES_URL", "http://localhost:9200").rstrip("/")
PURGE = "--purge" in sys.argv
NOW = datetime.now(timezone.utc).replace(microsecond=0)
RNG = random.Random(20260906)

SEED_TAG = "rst-incident-001"
ALERT_INDEX = ".alerts-security.alerts-default"

# The compromised host and the account the attacker landed on. Both already
# exist in the ops-scenario data, so the new events sit among real neighbours
# instead of forming an island.
VICTIM = "web-prod-03"
ACCOUNT = "svc_backup"
ATTACKER_IP = "203.0.113.77"
C2_IP = "185.243.115.84"
C2_PORT = 4444
SCANNER_IP = "203.0.113.60"
SCAN_TARGET = "web-prod-01"


def ago(hours=0, minutes=0, seconds=0):
    return NOW - timedelta(hours=hours, minutes=minutes, seconds=seconds)


def iso(dt):
    return dt.strftime("%Y-%m-%dT%H:%M:%SZ")


def req(method, path, body=None):
    data = None
    if body is not None:
        data = body.encode("utf-8") if isinstance(body, str) else json.dumps(body).encode("utf-8")
    r = urllib.request.Request(f"{ES_URL}{path}", data=data, method=method)
    r.add_header(
        "Content-Type",
        "application/x-ndjson" if isinstance(body, str) else "application/json",
    )
    try:
        with urllib.request.urlopen(r, timeout=120) as resp:
            return resp.status, json.loads(resp.read().decode("utf-8") or "{}")
    except urllib.error.HTTPError as e:
        return e.code, json.loads(e.read().decode("utf-8") or "{}")


def bulk(index, docs, op="create"):
    """Append to an existing stream/index. Never creates or deletes it —
    the ops-scenario seeder owns those, and re-running this must not wipe them."""
    total = 0
    for i in range(0, len(docs), 1000):
        chunk = docs[i : i + 1000]
        lines = []
        for d in chunk:
            lines.append(json.dumps({op: {"_index": index}}))
            lines.append(json.dumps(d, ensure_ascii=False))
        status, body = req("POST", "/_bulk?refresh=wait_for", "\n".join(lines) + "\n")
        if status >= 300 or body.get("errors"):
            first = next(
                (it for it in body.get("items", []) if "error" in next(iter(it.values()), {})),
                None,
            )
            print(f"  ! bulk {index} -> {status} {json.dumps(first)[:400]}", file=sys.stderr)
            return total
        total += len(chunk)
    print(f"  {index}: {total} docs")
    return total


def tag():
    return {"labels": {"seed": SEED_TAG}}


# ── 1. linux.auth — 暴力破解、落脚、提权 ────────────────────────────────────

def auth_events():
    """SSH failures, the one success, and the sudo escalation that follows.

    Field shape copied from what the ops seeder already writes to this stream
    (`event.action` / `event.outcome` / `process.name` / ECS-ish `message`), so
    a query written against the existing data works on these rows too.
    """
    docs = []

    def auth(ts, action, outcome, msg, user=ACCOUNT, ip=ATTACKER_IP, proc="sshd", port=None):
        d = {
            "@timestamp": iso(ts),
            "host": {"name": VICTIM},
            "user": {"name": user},
            "source": {"ip": ip, "port": port or RNG.randint(40000, 61000)},
            "process": {"name": proc, "pid": RNG.randint(1000, 30000)},
            "event": {
                "dataset": "system.auth",
                "action": action,
                "outcome": outcome,
                "category": "authentication",
            },
            "log": {"level": "warning" if outcome == "failure" else "info"},
            "message": msg,
        }
        d.update(tag())
        return d

    # 30 分钟的密码喷洒。用户名列表是真实字典里最常见的那几个，最后才落到
    # svc_backup —— 攻击者是从枚举里撞出这个名字的，不是一开始就知道。
    dict_users = ["root", "admin", "oracle", "postgres", "test", "ubuntu", "git", "jenkins", ACCOUNT]
    t = ago(hours=7, minutes=5)
    for i in range(380):
        u = dict_users[i % len(dict_users)]
        invalid = u not in ("root", ACCOUNT)
        msg = (
            f"Failed password for {'invalid user ' if invalid else ''}{u} "
            f"from {ATTACKER_IP} port {RNG.randint(40000, 61000)} ssh2"
        )
        docs.append(auth(t, "ssh_login", "failure", msg, user=u))
        t += timedelta(seconds=RNG.randint(3, 6))

    # 撞开。同一个 IP、同一个会话窗口 —— 这是「暴破后成功」判定的全部依据。
    hit = ago(hours=6, minutes=34)
    docs.append(
        auth(hit, "ssh_login", "success",
             f"Accepted password for {ACCOUNT} from {ATTACKER_IP} port 51022 ssh2", port=51022)
    )
    docs.append(
        auth(hit + timedelta(seconds=1), "session_opened", "success",
             f"pam_unix(sshd:session): session opened for user {ACCOUNT} by (uid=0)")
    )

    # 三次 sudo 被拒（密码不对），第四次成功 —— 攻击者在试这个账号有没有 sudo。
    esc = ago(hours=6, minutes=28)
    for i in range(3):
        docs.append(
            auth(esc + timedelta(seconds=i * 40), "sudo", "failure",
                 f"sudo: {ACCOUNT} : 1 incorrect password attempt ; TTY=pts/1 ; "
                 f"PWD=/home/{ACCOUNT} ; USER=root ; COMMAND=/bin/bash",
                 proc="sudo", ip=ATTACKER_IP)
        )
    docs.append(
        auth(ago(hours=6, minutes=22), "sudo", "success",
             f"sudo: {ACCOUNT} : TTY=pts/1 ; PWD=/home/{ACCOUNT} ; USER=root ; "
             f"COMMAND=/bin/bash", proc="sudo")
    )

    # 攻击者顺手加了一个后门账号 —— 持久化，也是给分诊留的一条明确证据。
    docs.append(
        auth(ago(hours=6, minutes=20), "useradd", "success",
             "useradd[24188]: new user: name=sysmon, UID=0, GID=0, home=/var/lib/sysmon, "
             "shell=/bin/bash", user="root", proc="useradd")
    )

    # 同一时间窗里的正常登录 —— 没有噪声的日志不像真的，分诊也需要能区分。
    for h, u, ip in (
        (6, "deploy", "10.30.2.41"),
        (5, "ops", "10.30.1.87"),
        (4, "jenkins", "10.30.4.12"),
    ):
        docs.append(
            auth(ago(hours=h, minutes=RNG.randint(1, 50)), "ssh_login", "success",
                 f"Accepted publickey for {u} from {ip} port 22 ssh2", user=u, ip=ip)
        )
    return docs


# ── 2. linux.syslog — auditd 文件访问、打包、外联 ───────────────────────────

def syslog_events():
    docs = []

    def sys(ts, proc, msg, level="notice", pid=None):
        d = {
            "@timestamp": iso(ts),
            "host": {"name": VICTIM},
            "process": {"name": proc, "pid": pid or RNG.randint(1000, 30000)},
            "log": {"level": level},
            "event": {"dataset": "system.syslog", "category": "process"},
            "message": msg,
            "user": {"name": ACCOUNT},
        }
        d.update(tag())
        return d

    # 落脚后的探路。每条都是真命令，顺序也是真人会敲的顺序。
    recon = ago(hours=6, minutes=31)
    for i, cmd in enumerate(("id", "uname -a", "cat /etc/passwd", "crontab -l", "ss -tunlp")):
        docs.append(
            sys(recon + timedelta(seconds=i * 12), "bash",
                f"{ACCOUNT} : command executed: {cmd}")
        )

    # auditd 的 SYSCALL 记录 —— 「敏感文件访问」这条告警的原始证据就是这三行。
    audit_t = ago(hours=6, minutes=18)
    for i, (path, comm) in enumerate((
        ("/etc/shadow", "cat"),
        (f"/home/{ACCOUNT}/.ssh/id_rsa", "cat"),
        ("/var/backups/shop-db-2026-09-05.sql.gz", "cp"),
    )):
        docs.append(
            sys(audit_t + timedelta(seconds=i * 20), "auditd",
                f'audit[{1200 + i}]: SYSCALL arch=c000003e syscall=257 success=yes '
                f'exit=3 comm="{comm}" exe="/usr/bin/{comm}" key="sensitive-file" '
                f'auid=1004 uid=0 name="{path}"',
                level="warning")
        )

    # 打包外带。/tmp 下的隐藏目录是最常见的暂存点。
    docs.append(
        sys(ago(hours=6, minutes=12), "bash",
            f"{ACCOUNT} : command executed: tar -czf /tmp/.cache/.sysmon.tgz "
            f"/var/backups /home/{ACCOUNT}/.ssh", level="warning")
    )

    # C2 信标：40 分钟、每 60 秒一次，包大小几乎恒定 —— 这个规律本身就是判定依据。
    beacon = ago(hours=6, minutes=8)
    for i in range(40):
        docs.append(
            {
                "@timestamp": iso(beacon + timedelta(minutes=i)),
                "host": {"name": VICTIM},
                "process": {"name": "kernel", "pid": 0},
                "log": {"level": "info"},
                "event": {"dataset": "system.syslog", "category": "network",
                          "action": "iptables_out"},
                "source": {"ip": "10.30.7.23", "port": RNG.randint(40000, 61000)},
                "destination": {"ip": C2_IP, "port": C2_PORT},
                "network": {"transport": "tcp", "bytes": 1180 + RNG.randint(-40, 40)},
                "user": {"name": ACCOUNT},
                "message": (
                    f"kernel: [UFW ALLOW] IN= OUT=eth0 SRC=10.30.7.23 DST={C2_IP} "
                    f"LEN={1180 + RNG.randint(-40, 40)} PROTO=TCP SPT={RNG.randint(40000, 61000)} "
                    f"DPT={C2_PORT} WINDOW=502"
                ),
                **tag(),
            }
        )
    return docs


# ── 3. nginx.access — 前一天的扫描（另一条线，故意不相干）─────────────────

def nginx_events():
    docs = []
    t = ago(hours=26)
    paths = ["/admin", "/wp-login.php", "/.env", "/api/v1/users?id=1%27", "/phpmyadmin",
             "/.git/config", "/api/v1/login", "/backup.zip", "/server-status"]
    for i in range(120):
        p = paths[i % len(paths)]
        code = 404 if i % 9 else 200
        docs.append(
            {
                "@timestamp": iso(t + timedelta(seconds=i * 7)),
                "host": {"name": SCAN_TARGET},
                "source": {"ip": SCANNER_IP},
                "url": {"path": p},
                "http": {"request": {"method": "GET"},
                         "response": {"status_code": code, "body": {"bytes": RNG.randint(120, 900)}}},
                "user_agent": {"original": "sqlmap/1.7.11#stable (https://sqlmap.org)"},
                "event": {"dataset": "nginx.access", "category": "web",
                          "outcome": "failure" if code >= 400 else "success"},
                "message": f'{SCANNER_IP} - - "GET {p} HTTP/1.1" {code}',
                **tag(),
            }
        )
    return docs


# ── 4. 告警（Kibana 检测告警的形状，走网关自己的摄取路径）──────────────────

def alert_doc(ts, rule_name, severity, risk, *, host=VICTIM, user=None, src_ip=None,
              dst_ip=None, technique=None, reason=""):
    """One detection alert, shaped like Elastic Security writes them.

    `kibana.alert.*` is what `alerts/store.normalize()` reads; `host.name` /
    `user.name` / `source.ip` are what it guesses the subject from, and what
    the investigation then pivots on. Keeping both means the alert list, the
    Discover deep-link and 深入调查 all agree on who this is about.
    """
    doc = {
        "@timestamp": iso(ts),
        "kibana.alert.uuid": f"{SEED_TAG}-{abs(hash((rule_name, iso(ts)))) % 10**9}",
        "kibana.alert.rule.name": rule_name,
        "kibana.alert.rule.rule_id": rule_name,
        "kibana.alert.rule.uuid": f"rule-{abs(hash(rule_name)) % 10**6}",
        "kibana.alert.severity": severity,
        "kibana.alert.risk_score": risk,
        "kibana.alert.status": "active",
        "kibana.alert.workflow_status": "open",
        "kibana.alert.original_time": iso(ts),
        "kibana.alert.reason": reason,
        "host": {"name": host},
        "event": {"kind": "signal", "category": "intrusion_detection"},
        **tag(),
    }
    if user:
        doc["user"] = {"name": user}
    if src_ip:
        doc["source"] = {"ip": src_ip}
    if dst_ip:
        doc["destination"] = {"ip": dst_ip, "port": C2_PORT}
    if technique:
        doc["kibana.alert.rule.threat"] = [
            {
                "framework": "MITRE ATT&CK",
                "technique": [{"id": technique[0], "name": technique[1]}],
            }
        ]
    return doc


def alerts():
    return [
        alert_doc(
            ago(hours=6, minutes=35), "SSH 暴力破解", "high", 73,
            src_ip=ATTACKER_IP, technique=("T1110.001", "Password Guessing"),
            reason=f"{ATTACKER_IP} 在 30 分钟内对 {VICTIM} 发起 380 次失败的 SSH 认证",
        ),
        alert_doc(
            ago(hours=6, minutes=34), "暴力破解后登录成功", "critical", 91,
            user=ACCOUNT, src_ip=ATTACKER_IP,
            technique=("T1078.003", "Valid Accounts: Local Accounts"),
            reason=f"账号 {ACCOUNT} 在大量失败尝试后从同一来源 {ATTACKER_IP} 登录成功",
        ),
        alert_doc(
            ago(hours=6, minutes=22), "可疑本地提权", "high", 78,
            user=ACCOUNT, technique=("T1548.003", "Sudo and Sudo Caching"),
            reason=f"{ACCOUNT} 连续 3 次 sudo 失败后取得 root shell",
        ),
        alert_doc(
            ago(hours=6, minutes=20), "新建特权账号", "high", 80,
            user="root", technique=("T1136.001", "Create Account: Local Account"),
            reason="新建 UID=0 账号 sysmon，疑似持久化",
        ),
        alert_doc(
            ago(hours=6, minutes=18), "敏感文件访问", "critical", 88,
            user=ACCOUNT, technique=("T1552.001", "Credentials In Files"),
            reason="auditd 记录到 /etc/shadow、id_rsa 与数据库备份被读取",
        ),
        alert_doc(
            ago(hours=6, minutes=8), "可疑外联（疑似 C2 信标）", "critical", 90,
            user=ACCOUNT, dst_ip=C2_IP,
            technique=("T1071.001", "Application Layer Protocol: Web Protocols"),
            reason=f"{VICTIM} 每 60 秒向 {C2_IP}:{C2_PORT} 发送等长报文，持续 40 分钟",
        ),
        alert_doc(
            ago(hours=26), "Web 扫描器探测", "medium", 42,
            host=SCAN_TARGET, src_ip=SCANNER_IP,
            technique=("T1595.002", "Vulnerability Scanning"),
            reason=f"{SCANNER_IP} 使用 sqlmap 在 15 分钟内请求 120 个不存在的路径",
        ),
        # ── 下面两条是真误报。没有误报的告警列表教不会任何人分诊。 ──
        alert_doc(
            ago(hours=3, minutes=10), "敏感文件访问", "medium", 45,
            host="db-prod-01", user="backup",
            reason="备份任务读取 /var/backups/*.sql.gz —— 每日 02:00 计划任务",
        ),
        alert_doc(
            ago(hours=1, minutes=40), "异常端口扫描", "low", 21,
            host="app-prod-01", src_ip="10.30.9.5",
            reason="来自内网监控节点 10.30.9.5 的端口探测，与 Zabbix 巡检周期一致",
        ),
    ]


def purge():
    """Delete only what a previous run of this script wrote."""
    q = {"query": {"term": {"labels.seed": SEED_TAG}}}
    for idx in ("logs-linux.auth-default", "logs-linux.syslog-default",
                "logs-nginx.access-default", ALERT_INDEX, ".rst_copilot_alerts"):
        status, body = req("POST", f"/{idx}/_delete_by_query?refresh=true&conflicts=proceed", q)
        deleted = body.get("deleted", 0) if isinstance(body, dict) else 0
        print(f"  purge {idx}: {deleted} deleted" + (f" (status {status})" if status >= 300 else ""))


def main():
    print(f"ES: {ES_URL}   now: {iso(NOW)}")
    if PURGE:
        purge()

    print("seeding raw evidence…")
    bulk("logs-linux.auth-default", auth_events())
    bulk("logs-linux.syslog-default", syslog_events())
    bulk("logs-nginx.access-default", nginx_events())

    print("seeding detection alerts…")
    # 告警索引不是 data stream，用 index 而不是 create。
    bulk(ALERT_INDEX, alerts(), op="index")

    print(
        "\n完成。网关下一轮轮询会把这些告警摄进来（系统设置 → 摄取配置里能看到间隔）。\n"
        f"这次的故事：{ATTACKER_IP} 暴破 {VICTIM} → 拿到 {ACCOUNT} → sudo 提权 → "
        f"读 /etc/shadow 与备份 → 向 {C2_IP}:{C2_PORT} 每分钟回连。\n"
        "在「实时告警」里打开「暴力破解后登录成功」，深入调查应当能沿着 "
        f"{VICTIM} / {ACCOUNT} 找到上面每一步。"
    )


if __name__ == "__main__":
    main()
