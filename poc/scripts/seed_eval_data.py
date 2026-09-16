#!/usr/bin/env python3
"""Seed the `kibana_sample_data_logs` index directly into Elasticsearch.

The NL→DSL eval only talks to ES (backend.es_client get_mapping/execute_search);
Kibana was used purely to populate this index. But Kibana's `POST /api/sample_data/{id}`
route 404s in the CI Kibana image even once the server reports "available", so the
gate could never load data. Seeding ES directly removes the Kibana dependency.

The eval pass bar is "the generated DSL executes against ES without error", and the
LLM builds that DSL from get_mapping() — so the mapping below mirrors the real
kibana_sample_data_logs field shapes (text+keyword multifields, ip, geo_point, …)
to keep model behavior equivalent to the original dataset. A few hundred docs with
recent timestamps give the date-bucketed cases something to return.

Usage:  ES_URL=http://localhost:9200 python scripts/seed_eval_data.py
"""
import json
import os
import sys
import urllib.request
from datetime import datetime, timedelta, timezone

ES_URL = os.environ.get("ES_URL", "http://localhost:9200").rstrip("/")
INDEX = "kibana_sample_data_logs"
DOC_COUNT = 300

MAPPING = {
    "mappings": {
        "properties": {
            "@timestamp": {"type": "date"},
            "timestamp": {"type": "date"},
            "utc_time": {"type": "date"},
            "agent": {"type": "text", "fields": {"keyword": {"type": "keyword", "ignore_above": 256}}},
            "bytes": {"type": "long"},
            "clientip": {"type": "ip"},
            "ip": {"type": "ip"},
            "extension": {"type": "keyword"},
            "geo": {
                "properties": {
                    "coordinates": {"type": "geo_point"},
                    "dest": {"type": "keyword"},
                    "src": {"type": "keyword"},
                    "srcdest": {"type": "keyword"},
                }
            },
            "host": {"type": "keyword"},
            "index": {"type": "keyword"},
            "machine": {
                "properties": {
                    "os": {"type": "text", "fields": {"keyword": {"type": "keyword", "ignore_above": 256}}},
                    "ram": {"type": "long"},
                }
            },
            "memory": {"type": "double"},
            "message": {"type": "text"},
            "phpmemory": {"type": "long"},
            "referer": {"type": "keyword"},
            "request": {"type": "text", "fields": {"keyword": {"type": "keyword", "ignore_above": 1024}}},
            "response": {"type": "keyword"},
            "tags": {"type": "keyword"},
            "url": {"type": "text", "fields": {"keyword": {"type": "keyword", "ignore_above": 1024}}},
            "event": {"properties": {"dataset": {"type": "keyword"}}},
            "bytes_gauge": {"type": "long"},
            "bytes_counter": {"type": "long"},
        }
    }
}

# Value pools mirroring the real sample dataset's variety.
RESPONSES = ["200", "200", "200", "200", "404", "503", "500", "301"]
EXTENSIONS = ["", "", "jpg", "png", "gif", "css", "php", "zip", "rpm", "deb"]
OS = ["win 7", "win xp", "win 8", "ios", "osx"]
DESTS = ["CN", "US", "IN", "BR", "DE", "GB", "RU", "JP", "FR", "ID"]
AGENTS = [
    "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36",
    "Mozilla/5.0 (Windows NT 6.1) Gecko/20100101 Firefox/6.0",
    "Mozilla/5.0 (compatible; Googlebot/2.1; +http://www.google.com/bot.html)",
    "Mozilla/5.0 (compatible; bingbot/2.0)",
    "Mozilla/5.0 (Macintosh; Intel Mac OS X) Safari/537.36",
]
REQUESTS = ["/", "/index.html", "/api/login", "/wp-login.php", "/styles/main.css",
            "/images/hm_bg.jpg", "/people/type:astronauts", "/api/v1/search", "/favicon.ico"]
TAGS = [["success", "info"], ["success"], ["error"], ["warning", "info"], ["security"]]
COORDS = [[-73.9, 40.7], [116.4, 39.9], [77.2, 28.6], [-46.6, -23.5], [13.4, 52.5]]


def _req(method, path, body=None):
    data = body.encode("utf-8") if isinstance(body, str) else body
    r = urllib.request.Request(f"{ES_URL}{path}", data=data, method=method)
    if data is not None:
        ctype = "application/x-ndjson" if path.endswith("_bulk") else "application/json"
        r.add_header("Content-Type", ctype)
    with urllib.request.urlopen(r, timeout=30) as resp:
        return resp.status, resp.read().decode("utf-8")


def main():
    # Fresh index (ignore 404 if absent).
    try:
        _req("DELETE", f"/{INDEX}")
    except urllib.error.HTTPError as e:
        if e.code != 404:
            raise
    _req("PUT", f"/{INDEX}", json.dumps(MAPPING))

    now = datetime.now(timezone.utc)
    lines = []
    for i in range(DOC_COUNT):
        # Spread across the last ~10 days, with a cluster in the last few minutes
        # so "今天/最近5分钟" cases return data. (PASS only needs execution, but
        # realistic counts make the run resemble the original.)
        if i % 10 == 0:
            ts = now - timedelta(minutes=i % 5)
        else:
            ts = now - timedelta(minutes=(i * 37) % (10 * 24 * 60))
        iso = ts.strftime("%Y-%m-%dT%H:%M:%S.000Z")
        doc = {
            "@timestamp": iso,
            "timestamp": iso,
            "utc_time": iso,
            "agent": AGENTS[i % len(AGENTS)],
            "bytes": (i * 2473) % 9000,
            "clientip": f"{(i % 223) + 1}.{(i * 7) % 256}.{(i * 13) % 256}.{(i * 29) % 256}",
            "ip": f"10.{(i * 3) % 256}.{(i * 11) % 256}.{(i * 17) % 256}",
            "extension": EXTENSIONS[i % len(EXTENSIONS)],
            "geo": {
                "coordinates": COORDS[i % len(COORDS)],
                "dest": DESTS[i % len(DESTS)],
                "src": DESTS[(i + 3) % len(DESTS)],
                "srcdest": f"{DESTS[(i + 3) % len(DESTS)]}:{DESTS[i % len(DESTS)]}",
            },
            "host": "artifacts.elastic.co",
            "index": INDEX,
            "machine": {"os": OS[i % len(OS)], "ram": ((i % 16) + 1) * (1024 ** 3)},
            "memory": float((i % 8) * 1000) if i % 4 == 0 else None,
            "message": f"{(i % 223) + 1}.{(i * 7) % 256} - - [{iso}] \"GET {REQUESTS[i % len(REQUESTS)]}\"",
            "phpmemory": (i % 8) * 1000 if i % 4 == 0 else None,
            "referer": "http://www.elastic-elastic-elastic.com/success/",
            "request": REQUESTS[i % len(REQUESTS)],
            "response": RESPONSES[i % len(RESPONSES)],
            "tags": TAGS[i % len(TAGS)],
            "url": f"https://artifacts.elastic.co{REQUESTS[i % len(REQUESTS)]}",
            "event": {"dataset": "sample_web_logs"},
            "bytes_gauge": (i * 2473) % 9000,
            "bytes_counter": (i * 2473) % 90000,
        }
        doc = {k: v for k, v in doc.items() if v is not None}
        lines.append(json.dumps({"index": {}}))
        lines.append(json.dumps(doc))
    ndjson = "\n".join(lines) + "\n"
    status, body = _req("POST", f"/{INDEX}/_bulk?refresh=wait_for", ndjson)
    resp = json.loads(body)
    if resp.get("errors"):
        first = next((it for it in resp.get("items", []) if it.get("index", {}).get("error")), None)
        print(f"[seed_eval_data] bulk had errors: {json.dumps(first)[:500]}", file=sys.stderr)
        sys.exit(1)
    print(f"[seed_eval_data] indexed {DOC_COUNT} docs into {INDEX} at {ES_URL}")
    _ensure_data_view()


def _ensure_data_view():
    """Create the Kibana Data View for the seeded index — best effort.

    `/api/kibana-link` resolves an index to a Kibana index-pattern saved object
    and 404s when none exists (kibana_link.py `_find_data_view_id`), so a freshly
    seeded environment has working queries but dead "在 Kibana 中打开" links, and
    the e2e deep-link case fails for a reason that looks like a code bug.

    Kibana is optional here (CI runs ES only, which is why this script exists at
    all), so any failure is a printed note, never an exit code.
    """
    url = os.environ.get("KIBANA_URL", "http://localhost:5601").rstrip("/")
    if not url:
        return
    body = json.dumps({
        "data_view": {"title": INDEX, "name": INDEX, "timeFieldName": "@timestamp"}
    }).encode("utf-8")
    req = urllib.request.Request(f"{url}/api/data_views/data_view", data=body, method="POST")
    req.add_header("Content-Type", "application/json")
    req.add_header("kbn-xsrf", "true")
    try:
        with urllib.request.urlopen(req, timeout=15) as resp:
            print(f"[seed_eval_data] kibana data view created ({resp.status}) at {url}")
    except urllib.error.HTTPError as e:
        # Kibana answers an existing data view with 400 "Duplicate data view",
        # not 409 — which is the outcome we wanted, so don't shout about it.
        detail = e.read().decode("utf-8", "replace")[:200]
        note = "already exists" if "Duplicate data view" in detail else f"HTTP {e.code} {detail}"
        print(f"[seed_eval_data] kibana data view: {note}")
    except Exception as e:  # noqa: BLE001 — Kibana absent / unreachable is fine
        print(f"[seed_eval_data] kibana data view skipped ({type(e).__name__}) — "
              f"set KIBANA_URL if you want Kibana deep links to resolve")


if __name__ == "__main__":
    main()
