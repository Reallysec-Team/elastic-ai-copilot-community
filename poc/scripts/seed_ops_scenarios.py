#!/usr/bin/env python3
"""Seed enterprise ops/security logs so the product can be exercised against
scenarios a real SOC/NOC actually works through.

Why this exists: the demo cluster only had Windows security events and a Web
access log, both ending weeks in the past — so every question had to be
rewritten with an explicit date range before it returned anything, and whole
classes of work (Linux hosts, containers, JVM services, MySQL, host metrics)
could not be exercised at all.

Every index here is anchored to *now* and carries a planted story with a known
answer, so a scenario run can be graded rather than eyeballed:

  linux.auth      SSH brute force from 203.0.113.77 against web-prod-03,
                  D-1 02:00–02:35, ~380 failures then ONE success (foothold).
  linux.syslog    OOM-killer takes mysqld on db-prod-01 (D-2 03:12);
                  /var fills on web-prod-02 (D-1 onward, "No space left").
  nginx.access    /api/checkout 5xx spike, today 14:00–15:00 (upstream down).
  nginx.error     upstream timed out → app-prod-02:8080, same window.
  docker          payment-svc OOMKilled + restart loop (exit 137), D-0.
  k8s.events      payment-svc CrashLoopBackOff; report-svc ImagePullBackOff.
  app.java        order-svc Hikari pool exhaustion + NPE burst, today 14:00.
  mysql.slowlog   unindexed SELECT on orders, 8–15 s, from D-1.
  system.metrics  db-prod-01 memory climbs to the OOM; web-prod-02 disk 96%.
  windows.system  SVC-WIN-02 service 7031 crash loop + disk error event 7.

The stories interlock on purpose: the checkout 5xx, the Hikari exhaustion, the
MySQL slow query and the payment-svc OOM are one incident seen from four
angles, which is what makes a cross-index question worth asking.

Usage:  ES_URL=http://localhost:9200 python scripts/seed_ops_scenarios.py
        ES_URL=... python scripts/seed_ops_scenarios.py --drop   (recreate)
"""
import json
import os
import random
import sys
import urllib.error
import urllib.request
from datetime import datetime, timedelta, timezone

ES_URL = os.environ.get("ES_URL", "http://localhost:9200").rstrip("/")
DROP = "--drop" in sys.argv
NOW = datetime.now(timezone.utc).replace(microsecond=0)
RNG = random.Random(20260903)  # deterministic: a rerun grades the same way

HOSTS_LINUX = ["web-prod-01", "web-prod-02", "web-prod-03", "app-prod-01", "app-prod-02", "db-prod-01"]
USERS = ["deploy", "appuser", "dbadmin", "jenkins", "ops", "root"]
OFFICE_IPS = [f"10.30.{RNG.randint(1, 4)}.{RNG.randint(2, 250)}" for _ in range(40)]

KW = {"type": "keyword"}
TXT = {"type": "text", "fields": {"keyword": {"type": "keyword", "ignore_above": 1024}}}
LONG = {"type": "long"}
DBL = {"type": "double"}
IP = {"type": "ip"}
DATE = {"type": "date"}


def ago(days=0, hours=0, minutes=0, seconds=0):
    return NOW - timedelta(days=days, hours=hours, minutes=minutes, seconds=seconds)


def iso(dt):
    return dt.isoformat().replace("+00:00", "Z")


# The deployment (and every question an operator types) is in +08:00; ES stores
# UTC. Planting "this afternoon" at 14:00 UTC would put it at 22:00 local, so a
# correct query for 下午 would find nothing — the seed has to think in local
# time exactly like the operator does.
TZ_OFFSET = timedelta(hours=8)


def local(days_ago, hour, minute=0):
    """UTC instant for local-time HH:MM, `days_ago` days back."""
    d = (NOW + TZ_OFFSET - timedelta(days=days_ago)).replace(hour=hour, minute=minute, second=0)
    return d - TZ_OFFSET


def day_start(days_ago):
    """Midnight UTC of the day N days back — anchors a planted window."""
    d = (NOW - timedelta(days=days_ago)).replace(hour=0, minute=0, second=0)
    return d


def req(method, path, body=None):
    data = None
    if body is not None:
        data = body.encode("utf-8") if isinstance(body, str) else json.dumps(body).encode("utf-8")
    r = urllib.request.Request(f"{ES_URL}{path}", data=data, method=method)
    r.add_header("Content-Type", "application/x-ndjson" if isinstance(body, str) else "application/json")
    try:
        with urllib.request.urlopen(r, timeout=120) as resp:
            return resp.status, json.loads(resp.read().decode("utf-8") or "{}")
    except urllib.error.HTTPError as e:
        return e.code, json.loads(e.read().decode("utf-8") or "{}")


def create(index, props):
    """Create the stream as a DATA STREAM.

    `logs-*` / `metrics-*` match Elasticsearch's built-in templates, which are
    data-stream-only, so a plain `PUT /<index>` is rejected. That is also what a
    real customer has: everything Fleet / Elastic Agent ships lands in a data
    stream, so seeding one keeps the demo cluster shaped like production.
    """
    req("DELETE", f"/_data_stream/{index}")
    base = {"@timestamp": DATE, "message": TXT, "host": {"properties": {"name": KW}}}
    merged = dict(base)
    merged.update(props)
    tpl = f"rst-ops-{index}"
    status, body = req(
        "PUT",
        f"/_index_template/{tpl}",
        {
            "index_patterns": [index],
            "data_stream": {},
            # Above the built-in logs/metrics templates (100/200) so ours wins.
            "priority": 500,
            "template": {
                "settings": {"number_of_shards": 1, "number_of_replicas": 0},
                "mappings": {"properties": merged},
            },
        },
    )
    if status >= 300:
        print(f"  ! template {index} -> {status} {body}", file=sys.stderr)
        return
    status, body = req("PUT", f"/_data_stream/{index}")
    if status >= 300:
        print(f"  ! create {index} -> {status} {body}", file=sys.stderr)


def bulk(index, docs):
    """Index in chunks; ES rejects a single body that grows too large."""
    total = 0
    for i in range(0, len(docs), 2000):
        chunk = docs[i : i + 2000]
        lines = []
        for d in chunk:
            # Data streams accept `create` only.
            lines.append(json.dumps({"create": {"_index": index}}))
            lines.append(json.dumps(d, ensure_ascii=False))
        status, body = req("POST", "/_bulk?refresh=wait_for", "\n".join(lines) + "\n")
        if status >= 300 or body.get("errors"):
            first = next((it for it in body.get("items", []) if "error" in it.get("index", {})), None)
            print(f"  ! bulk {index} -> {status} {json.dumps(first)[:300]}", file=sys.stderr)
            return total
        total += len(chunk)
    print(f"  {index}: {total} docs")
    return total


# ── 1. Linux auth (SSH / sudo) ──────────────────────────────────────────────

def seed_linux_auth():
    index = "logs-linux.auth-default"
    create(
        index,
        {
            "event": {"properties": {"dataset": KW, "action": KW, "outcome": KW, "category": KW}},
            "user": {"properties": {"name": KW}},
            "source": {"properties": {"ip": IP, "port": LONG}},
            "process": {"properties": {"name": KW, "pid": LONG}},
            "log": {"properties": {"level": KW}},
        },
    )
    docs = []

    def auth(ts, host, user, ip, action, outcome, proc="sshd", msg=None):
        return {
            "@timestamp": iso(ts),
            "host": {"name": host},
            "user": {"name": user},
            "source": {"ip": ip, "port": RNG.randint(30000, 61000)},
            "process": {"name": proc, "pid": RNG.randint(800, 30000)},
            "event": {
                "dataset": "system.auth",
                "action": action,
                "outcome": outcome,
                "category": "authentication",
            },
            "log": {"level": "info" if outcome == "success" else "warning"},
            "message": msg
            or (
                f"Accepted publickey for {user} from {ip} port 22 ssh2"
                if outcome == "success"
                else f"Failed password for {user} from {ip} port 22 ssh2"
            ),
        }

    # Background: routine logins and sudo across the week.
    for _ in range(1800):
        ts = ago(minutes=RNG.randint(0, 7 * 24 * 60))
        host = RNG.choice(HOSTS_LINUX)
        user = RNG.choice(USERS)
        ip = RNG.choice(OFFICE_IPS)
        if RNG.random() < 0.25:
            docs.append(
                auth(ts, host, user, ip, "sudo", "success", "sudo",
                     f"{user} : TTY=pts/0 ; PWD=/home/{user} ; USER=root ; COMMAND=/usr/bin/systemctl status nginx")
            )
        else:
            outcome = "failure" if RNG.random() < 0.06 else "success"
            docs.append(auth(ts, host, user, ip, "ssh_login", outcome))

    # Planted: brute force from one external IP, then a single success.
    attacker = "203.0.113.77"
    start = day_start(1) + timedelta(hours=2)
    for i in range(380):
        ts = start + timedelta(seconds=i * 5 + RNG.randint(0, 3))
        docs.append(auth(ts, "web-prod-03", RNG.choice(["root", "admin", "test", "oracle", "deploy"]),
                         attacker, "ssh_login", "failure"))
    docs.append(auth(start + timedelta(minutes=33), "web-prod-03", "deploy", attacker, "ssh_login", "success"))
    docs.append(auth(start + timedelta(minutes=34), "web-prod-03", "deploy", attacker, "sudo", "success", "sudo",
                     "deploy : TTY=pts/1 ; PWD=/tmp ; USER=root ; COMMAND=/bin/bash"))
    return bulk(index, docs)


# ── 2. Linux syslog (kernel / systemd) ──────────────────────────────────────

def seed_linux_syslog():
    index = "logs-linux.syslog-default"
    create(
        index,
        {
            "event": {"properties": {"dataset": KW}},
            "process": {"properties": {"name": KW, "pid": LONG}},
            "log": {"properties": {"level": KW}},
            "service": {"properties": {"name": KW}},
        },
    )
    docs = []

    def sys(ts, host, proc, level, msg, svc=None):
        d = {
            "@timestamp": iso(ts),
            "host": {"name": host},
            "process": {"name": proc, "pid": RNG.randint(1, 30000)},
            "log": {"level": level},
            "event": {"dataset": "system.syslog"},
            "message": msg,
        }
        if svc:
            d["service"] = {"name": svc}
        return d

    routine = [
        ("cron", "info", "(root) CMD (/usr/local/bin/backup.sh)"),
        ("systemd", "info", "Started Session 4021 of user deploy."),
        ("systemd", "info", "Starting Daily apt download activities..."),
        ("chronyd", "info", "Selected source 10.30.0.10"),
        ("kernel", "info", "TCP: request_sock_TCP: Possible SYN flooding on port 443. Sending cookies."),
    ]
    for _ in range(1400):
        ts = ago(minutes=RNG.randint(0, 7 * 24 * 60))
        proc, level, msg = RNG.choice(routine)
        docs.append(sys(ts, RNG.choice(HOSTS_LINUX), proc, level, msg))

    # Planted A: OOM killer takes mysqld on db-prod-01, D-2 03:12.
    oom = day_start(2) + timedelta(hours=3, minutes=12)
    docs += [
        sys(oom, "db-prod-01", "kernel", "error",
            "Out of memory: Killed process 2841 (mysqld) total-vm:14203912kB, anon-rss:11982044kB, file-rss:0kB"),
        sys(oom + timedelta(seconds=1), "db-prod-01", "kernel", "warning",
            "oom_reaper: reaped process 2841 (mysqld), now anon-rss:0kB, file-rss:0kB"),
        sys(oom + timedelta(seconds=4), "db-prod-01", "systemd", "error",
            "mysqld.service: Main process exited, code=killed, status=9/KILL", "mysqld"),
        sys(oom + timedelta(seconds=5), "db-prod-01", "systemd", "warning",
            "mysqld.service: Scheduled restart job, restart counter is at 1.", "mysqld"),
        sys(oom + timedelta(seconds=42), "db-prod-01", "systemd", "info",
            "Started MySQL Community Server.", "mysqld"),
    ]

    # Planted B: /var fills on web-prod-02 from D-1 onward.
    for i in range(60):
        ts = day_start(1) + timedelta(hours=9) + timedelta(minutes=i * 20)
        docs.append(sys(ts, "web-prod-02", "kernel", "error",
                        "EXT4-fs (sda2): Delayed block allocation failed for inode 393228 (-28): No space left on device"))
    for i in range(24):
        ts = day_start(1) + timedelta(hours=9) + timedelta(minutes=i * 45)
        docs.append(sys(ts, "web-prod-02", "systemd", "warning",
                        "/var is 96% full — only 1.8G of 50G remaining"))
    return bulk(index, docs)


# ── 3. Nginx access ─────────────────────────────────────────────────────────

PATHS = ["/", "/api/v1/orders", "/api/v1/users", "/api/checkout", "/api/search",
         "/static/app.js", "/static/main.css", "/health", "/api/v1/inventory"]
UAS = [
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/128.0",
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/605.1.15 Safari/17.4",
    "curl/8.5.0",
    "python-requests/2.32.3",
    "Mozilla/5.0 (compatible; Nmap Scripting Engine; https://nmap.org/book/nse.html)",
]


def seed_nginx_access():
    index = "logs-nginx.access-default"
    create(
        index,
        {
            "event": {"properties": {"dataset": KW, "duration": LONG}},
            "url": {"properties": {"path": KW, "original": KW}},
            "http": {
                "properties": {
                    "request": {"properties": {"method": KW}},
                    "response": {"properties": {"status_code": LONG, "body": {"properties": {"bytes": LONG}}}},
                }
            },
            "source": {"properties": {"ip": IP}},
            "user_agent": {"properties": {"original": TXT, "name": KW}},
            "service": {"properties": {"name": KW}},
        },
    )
    docs = []

    def acc(ts, path, code, ip=None, ua=None, dur_ms=None):
        return {
            "@timestamp": iso(ts),
            "host": {"name": RNG.choice(["web-prod-01", "web-prod-02", "web-prod-03"])},
            "service": {"name": "nginx"},
            "event": {"dataset": "nginx.access", "duration": (dur_ms or RNG.randint(5, 180)) * 1000000},
            "url": {"path": path, "original": path},
            "http": {
                "request": {"method": "POST" if path == "/api/checkout" else "GET"},
                "response": {"status_code": code, "body": {"bytes": RNG.randint(200, 90000)}},
            },
            "source": {"ip": ip or RNG.choice(OFFICE_IPS)},
            "user_agent": {"original": ua or RNG.choice(UAS[:2]), "name": "Chrome"},
            "message": f'{ip or "-"} - - "{path}" {code}',
        }

    for _ in range(4200):
        ts = ago(minutes=RNG.randint(0, 7 * 24 * 60))
        path = RNG.choice(PATHS)
        r = RNG.random()
        code = 200 if r < 0.93 else (404 if r < 0.975 else (301 if r < 0.99 else 500))
        docs.append(acc(ts, path, code))

    # Planted: /api/checkout 5xx spike today 14:00–15:00 (upstream down).
    spike = local(0, 14)
    if spike > NOW:
        spike = local(1, 14)
    for i in range(420):
        ts = spike + timedelta(seconds=i * 8 + RNG.randint(0, 4))
        docs.append(acc(ts, "/api/checkout", RNG.choice([502, 502, 502, 504, 500]), dur_ms=RNG.randint(3000, 30000)))
    for i in range(90):
        ts = spike + timedelta(seconds=i * 40)
        docs.append(acc(ts, "/api/checkout", 200, dur_ms=RNG.randint(800, 4000)))

    # Planted: a scanner sweeping admin paths from one IP, D-3.
    scan_ip = "198.51.100.23"
    scan_start = day_start(3) + timedelta(hours=21)
    for i, p in enumerate(
        ["/wp-login.php", "/admin", "/.env", "/.git/config", "/phpmyadmin", "/actuator/env",
         "/api/v1/../../etc/passwd", "/console", "/manager/html", "/solr/admin/info/system"] * 12
    ):
        docs.append(acc(scan_start + timedelta(seconds=i * 3), p, 404, ip=scan_ip, ua=UAS[4], dur_ms=3))
    return bulk(index, docs)


# ── 4. Nginx error ──────────────────────────────────────────────────────────

def seed_nginx_error():
    index = "logs-nginx.error-default"
    create(
        index,
        {
            "event": {"properties": {"dataset": KW}},
            "log": {"properties": {"level": KW}},
            "url": {"properties": {"path": KW}},
            "upstream": {"properties": {"address": KW}},
            "service": {"properties": {"name": KW}},
        },
    )
    docs = []

    def err(ts, level, msg, path=None, upstream=None):
        return {
            "@timestamp": iso(ts),
            "host": {"name": RNG.choice(["web-prod-01", "web-prod-02", "web-prod-03"])},
            "service": {"name": "nginx"},
            "event": {"dataset": "nginx.error"},
            "log": {"level": level},
            "url": {"path": path} if path else {},
            "upstream": {"address": upstream} if upstream else {},
            "message": msg,
        }

    for _ in range(260):
        ts = ago(minutes=RNG.randint(0, 7 * 24 * 60))
        docs.append(err(ts, "warn", "client closed connection while waiting for request"))

    spike = local(0, 14)
    if spike > NOW:
        spike = local(1, 14)
    for i in range(300):
        ts = spike + timedelta(seconds=i * 11)
        docs.append(err(ts, "error",
                        'upstream timed out (110: Connection timed out) while reading response header from upstream, '
                        'upstream: "http://10.30.9.22:8080/api/checkout"',
                        "/api/checkout", "app-prod-02:8080"))
    for i in range(40):
        ts = spike + timedelta(minutes=2, seconds=i * 60)
        docs.append(err(ts, "error",
                        'connect() failed (111: Connection refused) while connecting to upstream, '
                        'upstream: "http://10.30.9.22:8080/api/checkout"',
                        "/api/checkout", "app-prod-02:8080"))
    return bulk(index, docs)


# ── 5. Docker container logs ────────────────────────────────────────────────

CONTAINERS = [
    ("payment-svc", "registry.corp.local/payment-svc:2.7.1", "app-prod-02"),
    ("order-svc", "registry.corp.local/order-svc:4.1.0", "app-prod-01"),
    ("redis-cache", "redis:7.2-alpine", "app-prod-01"),
    ("nginx-edge", "nginx:1.25-alpine", "web-prod-01"),
    ("report-svc", "registry.corp.local/report-svc:1.3.9", "app-prod-02"),
]


def seed_docker():
    index = "logs-docker.container-default"
    create(
        index,
        {
            "event": {"properties": {"dataset": KW, "action": KW}},
            "container": {
                "properties": {
                    "id": KW,
                    "name": KW,
                    "image": {"properties": {"name": KW, "tag": KW}},
                    "runtime": KW,
                }
            },
            "log": {"properties": {"level": KW}},
            "process": {"properties": {"exit_code": LONG}},
        },
    )
    docs = []

    def c(ts, name, image, host, level, msg, action="container_log", exit_code=None):
        d = {
            "@timestamp": iso(ts),
            "host": {"name": host},
            "container": {
                "id": f"{abs(hash(name)) % (16**12):012x}",
                "name": name,
                "image": {"name": image.split(":")[0], "tag": image.split(":")[1]},
                "runtime": "docker",
            },
            "event": {"dataset": "docker.container_logs", "action": action},
            "log": {"level": level},
            "message": msg,
        }
        if exit_code is not None:
            d["process"] = {"exit_code": exit_code}
        return d

    chatter = ["request handled in 23ms", "cache warm complete", "health check ok",
               "connection pool size=20 active=3", "scheduled job finished"]
    for _ in range(3000):
        ts = ago(minutes=RNG.randint(0, 7 * 24 * 60))
        name, image, host = RNG.choice(CONTAINERS)
        lvl = "info" if RNG.random() < 0.92 else "warn"
        docs.append(c(ts, name, image, host, lvl, RNG.choice(chatter)))

    # Planted: payment-svc OOMKilled restart loop today.
    loop = local(0, 13, 40)
    if loop > NOW:
        loop = local(1, 13, 40)
    for k in range(9):
        base = loop + timedelta(minutes=k * 9)
        docs += [
            c(base, "payment-svc", "registry.corp.local/payment-svc:2.7.1", "app-prod-02", "error",
              "java.lang.OutOfMemoryError: Java heap space"),
            c(base + timedelta(seconds=3), "payment-svc", "registry.corp.local/payment-svc:2.7.1", "app-prod-02",
              "error", "Container killed due to memory limit (OOMKilled), exit code 137",
              action="container_die", exit_code=137),
            c(base + timedelta(seconds=12), "payment-svc", "registry.corp.local/payment-svc:2.7.1", "app-prod-02",
              "info", "Container start", action="container_start"),
        ]

    # Planted: redis refusing connections for a stretch on D-1.
    rd = day_start(1) + timedelta(hours=11)
    for i in range(70):
        docs.append(c(rd + timedelta(seconds=i * 30), "redis-cache", "redis:7.2-alpine", "app-prod-01", "error",
                      "# Can't save in background: fork: Cannot allocate memory"))
    return bulk(index, docs)


# ── 6. Kubernetes events ────────────────────────────────────────────────────

def seed_k8s():
    index = "logs-k8s.events-default"
    create(
        index,
        {
            "event": {"properties": {"dataset": KW, "reason": KW, "type": KW, "count": LONG}},
            "kubernetes": {
                "properties": {
                    "namespace": KW,
                    "node": {"properties": {"name": KW}},
                    "pod": {"properties": {"name": KW}},
                    "container": {"properties": {"name": KW}},
                }
            },
        },
    )
    docs = []

    def ev(ts, ns, pod, node, reason, etype, msg, container=None, count=1):
        return {
            "@timestamp": iso(ts),
            "host": {"name": node},
            "kubernetes": {
                "namespace": ns,
                "node": {"name": node},
                "pod": {"name": pod},
                "container": {"name": container or pod.rsplit("-", 2)[0]},
            },
            "event": {"dataset": "kubernetes.event", "reason": reason, "type": etype, "count": count},
            "message": msg,
        }

    nodes = ["k8s-node-01", "k8s-node-02", "k8s-node-03"]
    normal = [("Scheduled", "Successfully assigned pod to node"), ("Pulled", "Container image already present on machine"),
              ("Created", "Created container"), ("Started", "Started container")]
    for _ in range(520):
        ts = ago(minutes=RNG.randint(0, 7 * 24 * 60))
        reason, msg = RNG.choice(normal)
        pod = f"{RNG.choice(['order-svc', 'web-svc', 'report-svc'])}-{RNG.randint(10000,99999)}-{RNG.randint(10000,99999)}"
        docs.append(ev(ts, "prod", pod, RNG.choice(nodes), reason, "Normal", msg))

    # Planted: payment-svc CrashLoopBackOff today; report-svc ImagePullBackOff D-1.
    loop = local(0, 13, 42)
    if loop > NOW:
        loop = local(1, 13, 42)
    pod = "payment-svc-7d9f4c8b5-x2klm"
    for k in range(22):
        ts = loop + timedelta(minutes=k * 4)
        docs.append(ev(ts, "prod", pod, "k8s-node-02", "BackOff", "Warning",
                       "Back-off restarting failed container payment-svc in pod " + pod, count=k + 1))
    docs.append(ev(loop + timedelta(minutes=90), "prod", pod, "k8s-node-02", "Unhealthy", "Warning",
                   "Liveness probe failed: HTTP probe failed with statuscode: 500"))
    rpod = "report-svc-5c7b9d6f4-qq8vt"
    for k in range(14):
        ts = day_start(1) + timedelta(hours=16, minutes=k * 5)
        docs.append(ev(ts, "prod", rpod, "k8s-node-03", "Failed", "Warning",
                       'Failed to pull image "registry.corp.local/report-svc:1.4.0-rc2": '
                       "rpc error: code = NotFound desc = manifest unknown"))
        docs.append(ev(ts + timedelta(seconds=2), "prod", rpod, "k8s-node-03", "BackOff", "Warning",
                       "Back-off pulling image registry.corp.local/report-svc:1.4.0-rc2"))
    docs.append(ev(day_start(2) + timedelta(hours=7), "prod", "web-svc-6f8b7c9d4-mm3lp", "k8s-node-01",
                   "Evicted", "Warning", "The node was low on resource: ephemeral-storage."))
    return bulk(index, docs)


# ── 7. JVM application logs ─────────────────────────────────────────────────

def seed_app_java():
    index = "logs-app.java-default"
    create(
        index,
        {
            "event": {"properties": {"dataset": KW}},
            "service": {"properties": {"name": KW, "version": KW, "environment": KW}},
            "log": {"properties": {"level": KW, "logger": KW}},
            "error": {"properties": {"type": KW, "message": TXT, "stack_trace": TXT}},
            "trace": {"properties": {"id": KW}},
            "transaction": {"properties": {"duration": {"properties": {"us": LONG}}}},
        },
    )
    docs = []
    services = [("order-svc", "4.1.0", "app-prod-01"), ("payment-svc", "2.7.1", "app-prod-02"),
                ("report-svc", "1.3.9", "app-prod-02"), ("auth-svc", "3.0.2", "app-prod-01")]

    def app(ts, svc, ver, host, level, logger, msg, err_type=None, stack=None, dur_us=None):
        d = {
            "@timestamp": iso(ts),
            "host": {"name": host},
            "service": {"name": svc, "version": ver, "environment": "production"},
            "event": {"dataset": "app.java"},
            "log": {"level": level, "logger": logger},
            "trace": {"id": f"{RNG.getrandbits(64):016x}"},
            "message": msg,
        }
        if err_type:
            d["error"] = {"type": err_type, "message": msg, "stack_trace": stack or ""}
        if dur_us:
            d["transaction"] = {"duration": {"us": dur_us}}
        return d

    for _ in range(2400):
        ts = ago(minutes=RNG.randint(0, 7 * 24 * 60))
        svc, ver, host = RNG.choice(services)
        r = RNG.random()
        level = "INFO" if r < 0.9 else ("WARN" if r < 0.97 else "ERROR")
        docs.append(app(ts, svc, ver, host, level, "c.corp.web.RequestLogger",
                        f"handled {RNG.choice(['GET', 'POST'])} in {RNG.randint(4, 400)}ms",
                        dur_us=RNG.randint(4000, 400000)))

    spike = local(0, 14)
    if spike > NOW:
        spike = local(1, 14)
    # Planted A: Hikari pool exhaustion in order-svc during the checkout incident.
    hikari_stack = (
        "java.sql.SQLTransientConnectionException: HikariPool-1 - Connection is not available, "
        "request timed out after 30000ms\n"
        "\tat com.zaxxer.hikari.pool.HikariPool.createTimeoutException(HikariPool.java:696)\n"
        "\tat com.zaxxer.hikari.pool.HikariPool.getConnection(HikariPool.java:197)\n"
        "\tat com.corp.order.OrderRepository.findPending(OrderRepository.java:88)"
    )
    for i in range(260):
        ts = spike + timedelta(seconds=i * 13)
        docs.append(app(ts, "order-svc", "4.1.0", "app-prod-01", "ERROR", "c.z.h.pool.HikariPool",
                        "HikariPool-1 - Connection is not available, request timed out after 30000ms",
                        "java.sql.SQLTransientConnectionException", hikari_stack, dur_us=30000000))
    # Planted B: NPE burst in the same window, one class.
    npe_stack = (
        "java.lang.NullPointerException: Cannot invoke \"com.corp.order.Cart.total()\" because \"cart\" is null\n"
        "\tat com.corp.order.CheckoutService.settle(CheckoutService.java:142)\n"
        "\tat com.corp.order.CheckoutController.post(CheckoutController.java:61)"
    )
    for i in range(120):
        ts = spike + timedelta(seconds=i * 27)
        docs.append(app(ts, "order-svc", "4.1.0", "app-prod-01", "ERROR", "c.c.o.CheckoutService",
                        'Cannot invoke "com.corp.order.Cart.total()" because "cart" is null',
                        "java.lang.NullPointerException", npe_stack))
    # Planted C: long GC pauses on payment-svc before it gets OOMKilled.
    loop = local(0, 13, 30)
    if loop > NOW:
        loop = local(1, 13, 30)
    for i in range(45):
        ts = loop + timedelta(seconds=i * 40)
        docs.append(app(ts, "payment-svc", "2.7.1", "app-prod-02", "WARN", "gc",
                        f"[Full GC (Ergonomics)] pause {RNG.randint(2100, 8400)}ms, heap 3.9G->3.8G(4.0G)"))
    return bulk(index, docs)


# ── 8. MySQL slow log ───────────────────────────────────────────────────────

def seed_mysql_slow():
    index = "logs-mysql.slowlog-default"
    create(
        index,
        {
            "event": {"properties": {"dataset": KW, "duration": LONG}},
            "user": {"properties": {"name": KW}},
            "mysql": {
                "properties": {
                    "slowlog": {
                        "properties": {
                            "query": TXT,
                            "query_time": {"properties": {"sec": DBL}},
                            "rows_examined": LONG,
                            "rows_sent": LONG,
                            "schema": KW,
                        }
                    }
                }
            },
        },
    )
    docs = []

    def slow(ts, q, sec, examined, sent=1, user="appuser", schema="shop"):
        return {
            "@timestamp": iso(ts),
            "host": {"name": "db-prod-01"},
            "user": {"name": user},
            "event": {"dataset": "mysql.slowlog", "duration": int(sec * 1000000000)},
            "mysql": {"slowlog": {"query": q, "query_time": {"sec": sec},
                                  "rows_examined": examined, "rows_sent": sent, "schema": schema}},
            "message": f"# Query_time: {sec:.3f}  Rows_examined: {examined}\n{q}",
        }

    ordinary = [
        ("SELECT id, name FROM users WHERE email = ?", 1.2, 1400),
        ("UPDATE inventory SET qty = qty - ? WHERE sku = ?", 1.6, 900),
        ("SELECT * FROM sessions WHERE token = ?", 1.1, 2200),
    ]
    for _ in range(240):
        ts = ago(minutes=RNG.randint(0, 7 * 24 * 60))
        q, base, ex = RNG.choice(ordinary)
        docs.append(slow(ts, q, round(base + RNG.random(), 3), ex + RNG.randint(0, 400)))

    # Planted: an unindexed scan on orders, from D-1, worst during the incident.
    bad = ("SELECT o.*, c.name FROM orders o JOIN customers c ON c.id = o.customer_id "
           "WHERE o.status = 'PENDING' AND o.created_at > ? ORDER BY o.created_at DESC")
    for i in range(180):
        ts = day_start(1) + timedelta(hours=10) + timedelta(minutes=i * 11)
        docs.append(slow(ts, bad, round(RNG.uniform(8.0, 15.5), 3), RNG.randint(3_100_000, 4_800_000), sent=50))
    return bulk(index, docs)


# ── 9. Host metrics ─────────────────────────────────────────────────────────

def seed_metrics():
    index = "metrics-system-default"
    create(
        index,
        {
            "event": {"properties": {"dataset": KW}},
            "system": {
                "properties": {
                    "cpu": {"properties": {"total": {"properties": {"pct": DBL}}}},
                    "memory": {"properties": {"actual": {"properties": {"used": {"properties": {"pct": DBL}}}}}},
                    "filesystem": {"properties": {"used": {"properties": {"pct": DBL}}, "mount_point": KW}},
                    "load": {"properties": {"1": DBL}},
                }
            },
        },
    )
    docs = []
    step = 15  # minutes
    points = (7 * 24 * 60) // step
    for host in HOSTS_LINUX:
        for i in range(points):
            ts = NOW - timedelta(minutes=i * step)
            cpu = RNG.uniform(0.08, 0.42)
            mem = RNG.uniform(0.35, 0.62)
            disk = RNG.uniform(0.40, 0.68)
            mount = "/"
            # Planted: db-prod-01 memory climbs toward the D-2 OOM.
            if host == "db-prod-01":
                hours_before_oom = (day_start(2) + timedelta(hours=3, minutes=12) - ts).total_seconds() / 3600
                if 0 <= hours_before_oom <= 20:
                    mem = min(0.985, 0.62 + (20 - hours_before_oom) * 0.019)
            # Planted: web-prod-02 /var fills from D-1.
            if host == "web-prod-02" and ts >= day_start(1) + timedelta(hours=9):
                disk = RNG.uniform(0.93, 0.968)
                mount = "/var"
            docs.append({
                "@timestamp": iso(ts),
                "host": {"name": host},
                "event": {"dataset": "system.metrics"},
                "system": {
                    "cpu": {"total": {"pct": round(cpu, 4)}},
                    "memory": {"actual": {"used": {"pct": round(mem, 4)}}},
                    "filesystem": {"used": {"pct": round(disk, 4)}, "mount_point": mount},
                    "load": {"1": round(cpu * RNG.uniform(6, 14), 2)},
                },
                "message": f"{host} cpu={cpu:.2f} mem={mem:.2f} disk={disk:.2f}",
            })
    return bulk(index, docs)


# ── 10. Windows system log ──────────────────────────────────────────────────

def seed_windows_system():
    index = "logs-windows.system-default"
    create(
        index,
        {
            "event": {"properties": {"code": KW, "provider": KW, "action": KW}},
            "winlog": {"properties": {"channel": KW, "event_id": LONG, "provider_name": KW,
                                      "event_data": {"properties": {"param1": KW, "param2": KW}}}},
            "log": {"properties": {"level": KW}},
            "service": {"properties": {"name": KW}},
        },
    )
    docs = []
    win_hosts = ["SVC-WIN-01", "SVC-WIN-02", "SVC-WIN-03", "DC-01.corp.local"]

    def w(ts, host, code, provider, level, msg, svc=None, p1=None):
        return {
            "@timestamp": iso(ts),
            "host": {"name": host},
            "event": {"code": str(code), "provider": provider, "action": "system"},
            "winlog": {"channel": "System", "event_id": code, "provider_name": provider,
                       "event_data": {"param1": p1 or "", "param2": ""}},
            "log": {"level": level},
            "service": {"name": svc} if svc else {},
            "message": msg,
        }

    routine = [
        (7036, "Service Control Manager", "information", "The Print Spooler service entered the running state."),
        (1, "Microsoft-Windows-Kernel-General", "information", "The system time has changed."),
        (10016, "DCOM", "warning", "The application-specific permission settings do not grant Local Activation permission."),
    ]
    for _ in range(1100):
        ts = ago(minutes=RNG.randint(0, 7 * 24 * 60))
        code, prov, lvl, msg = RNG.choice(routine)
        docs.append(w(ts, RNG.choice(win_hosts), code, prov, lvl, msg))

    # Planted: SVC-WIN-02 service crash loop (7031) starting D-1.
    for k in range(28):
        ts = day_start(1) + timedelta(hours=8) + timedelta(minutes=k * 25)
        docs.append(w(ts, "SVC-WIN-02", 7031, "Service Control Manager", "error",
                      "The IIS Admin Service service terminated unexpectedly. It has done this 1 time(s). "
                      "The following corrective action will be taken in 60000 milliseconds: Restart the service.",
                      svc="IISADMIN", p1="IIS Admin Service"))
    # Planted: disk errors on the same box.
    for k in range(16):
        ts = day_start(1) + timedelta(hours=7) + timedelta(minutes=k * 37)
        docs.append(w(ts, "SVC-WIN-02", 7, "disk", "error",
                      "The device, \\Device\\Harddisk1\\DR1, has a bad block.", p1="\\Device\\Harddisk1\\DR1"))
    return bulk(index, docs)


SEEDERS = [
    seed_linux_auth, seed_linux_syslog, seed_nginx_access, seed_nginx_error,
    seed_docker, seed_k8s, seed_app_java, seed_mysql_slow, seed_metrics,
    seed_windows_system,
]


def main():
    status, _ = req("GET", "/")
    if status >= 300:
        print(f"Elasticsearch not reachable at {ES_URL}", file=sys.stderr)
        return 1
    print(f"Seeding into {ES_URL} (now = {iso(NOW)})")
    total = 0
    for fn in SEEDERS:
        total += fn()
    print(f"done: {total} docs across {len(SEEDERS)} indices")
    return 0


if __name__ == "__main__":
    sys.exit(main())
