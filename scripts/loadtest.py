"""Gateway concurrency load test (P1-C).

Measures single-worker capacity:
  * light endpoint (/healthz)            — raw request-handling throughput
  * full middleware chain (/api/license/status)
  * concurrent LLM (/api/generate)       — confirms async, no serialization

Usage:
  python scripts/loadtest.py
  RST_LOADTEST_URL=https://copilot.host python scripts/loadtest.py

Re-run this on the Linux deployment host for representative numbers — a
Windows dev box co-locating the load generator with the gateway gives a
pessimistic floor, not the production ceiling.
"""
import asyncio
import os
import time

import httpx

BASE = os.environ.get("RST_LOADTEST_URL", "http://127.0.0.1:18765").rstrip("/")


async def _one(client, method, path, body):
    t0 = time.perf_counter()
    try:
        r = (await client.get(BASE + path)) if method == "GET" \
            else (await client.post(BASE + path, json=body))
        return time.perf_counter() - t0, r.status_code
    except Exception:
        return time.perf_counter() - t0, -1


async def run(method, path, concurrency, total, body=None, timeout=30.0):
    sem = asyncio.Semaphore(concurrency)
    results: list[tuple[float, int]] = []
    limits = httpx.Limits(max_connections=concurrency + 20,
                          max_keepalive_connections=concurrency + 20)
    async with httpx.AsyncClient(timeout=timeout, limits=limits) as client:
        async def worker():
            async with sem:
                results.append(await _one(client, method, path, body))
        t0 = time.perf_counter()
        await asyncio.gather(*(worker() for _ in range(total)))
        wall = time.perf_counter() - t0

    lats = sorted(r[0] * 1000 for r in results)
    ok = sum(1 for r in results if 200 <= r[1] < 400)

    def pct(p):
        return lats[min(len(lats) - 1, int(len(lats) * p))]

    print(f"  {method} {path}  concurrency={concurrency} total={total}")
    print(f"    throughput {total / wall:8.0f} req/s | ok {ok}/{total} | wall {wall:.1f}s")
    print(f"    latency  p50 {pct(.5):.0f}ms  p95 {pct(.95):.0f}ms  "
          f"p99 {pct(.99):.0f}ms  max {lats[-1]:.0f}ms")
    return wall, lats, ok


async def main():
    print(f"target: {BASE}\n")
    print("=== 1. light endpoint /healthz  (raw gateway throughput) ===")
    for c in (10, 50, 100, 200):
        await run("GET", "/healthz", c, 4000)

    print()
    print("=== 2. full middleware chain /api/license/status ===")
    for c in (50, 100):
        await run("GET", "/api/license/status", c, 2000)

    print()
    print("=== 3. concurrent LLM — 3x /api/generate at once ===")
    body = {"question": "count of each response status code in the last hour",
            "index": "kibana_sample_data_logs"}
    wall, lats, ok = await run("POST", "/api/generate", 3, 3,
                               body=body, timeout=150.0)
    serial = sum(lats) / 1000
    verdict = "CONCURRENT-OK" if wall < serial * 0.6 else "SERIALIZED?"
    print(f"    3 concurrent: wall {wall:.1f}s vs serial-estimate {serial:.1f}s"
          f"  -> {verdict}")


if __name__ == "__main__":
    asyncio.run(main())
