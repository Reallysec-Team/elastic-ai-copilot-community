"""Eval harness: run NL->DSL on test cases, measure pass rate.

Two bars are reported:

    executes — the DSL runs against ES without error. The original bar, kept so
               runs stay comparable with the historical baselines.
    correct  — it also satisfies the case's `expect:` block (eval/expectations.py).

Only the second one says anything about answer quality: a syntactically perfect
`match_all` executes fine and answers nothing.

Usage (run from `poc/` directory):
    python -m eval.run                       # run all cases
    python -m eval.run --case top-urls       # run one
    python -m eval.run --gate 0.9            # exit nonzero if executes rate < 90%
    python -m eval.run --gate-correct 0.8    # ... or if correct rate < 80%
"""
import argparse
import asyncio
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

import yaml
from dotenv import load_dotenv

load_dotenv()

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from backend.es_client import close_es, execute_search, get_mapping  # noqa: E402
from backend.llm import generate_dsl  # noqa: E402
from backend.llm_router import load_router  # noqa: E402
from backend.validator import validate_dsl  # noqa: E402
from eval.expectations import check  # noqa: E402

# How stale the newest document may be before the time-window cases stop meaning
# anything. seed_eval_data.py lays docs down relative to the moment it runs, so a
# dataset seeded yesterday has no "today" in it — and every such case then passes
# the executes bar while answering nothing.
_STALE_AFTER_HOURS = 6


def _llm_configured() -> bool:
    """True when an LLM provider is available (env LLM_* or llm_providers.yml).
    When false, the gate has nothing to evaluate against."""
    try:
        return bool(load_router().providers)
    except Exception:  # noqa: BLE001
        return False


async def run_case(case: dict) -> dict:
    cid = case["id"]
    q = case["question"]
    idx = case["index"]
    try:
        mapping = await get_mapping(idx)
    except Exception as e:
        return {"id": cid, "status": "FAIL", "stage": "mapping", "error": str(e)}
    try:
        dsl, explanation, *_ = await generate_dsl(q, idx, mapping)
    except Exception as e:
        return {"id": cid, "status": "FAIL", "stage": "llm", "error": str(e)}
    try:
        validate_dsl(dsl)
    except Exception as e:
        return {"id": cid, "status": "FAIL", "stage": "validate", "error": str(e), "dsl": dsl}
    try:
        result = await execute_search(idx, dsl)
    except Exception as e:
        return {"id": cid, "status": "FAIL", "stage": "execute", "error": str(e), "dsl": dsl}

    hits = result.get("hits", {}).get("total", {}).get("value", 0)
    aggs = list(result.get("aggregations", {}).keys()) if "aggregations" in result else []
    record = {
        "id": cid,
        "status": "PASS",
        "executed": True,
        "hits": hits,
        "aggs": aggs,
        "dsl": dsl,
        "explanation": explanation,
    }
    problems = check(dsl, result, case.get("expect"))
    if problems:
        # It ran — that is the `executes` bar — but it did not answer the question.
        record.update(status="FAIL", stage="expect", error="; ".join(problems))
    return record


async def warn_if_stale(index: str) -> None:
    """Say so, loudly, when the newest document predates the questions we ask.

    Silence here is what let `今天到现在多少个请求` return 0 hits and still count
    as a pass for weeks.
    """
    try:
        newest = await execute_search(
            index, {"size": 0, "aggs": {"newest": {"max": {"field": "@timestamp"}}}}
        )
        value = (newest.get("aggregations") or {}).get("newest", {}).get("value")
        if not value:
            return
        age_h = (datetime.now(timezone.utc).timestamp() - value / 1000) / 3600
    except Exception:  # noqa: BLE001 — a probe failure must not stop the run
        return
    if age_h > _STALE_AFTER_HOURS:
        print(
            f"[WARN] {index}: newest document is {age_h:.0f}h old. The time-window "
            f"cases (今天 / 最近 5 分钟 / 本周) have no data to match.\n"
            f"       Re-seed first:  python scripts/seed_eval_data.py\n",
            flush=True,
        )


async def main(
    filter_id: str | None,
    gate_threshold: float | None = None,
    gate_correct: float | None = None,
) -> int:
    # Skip gracefully when no LLM is configured (e.g. CI without LLM_* secrets):
    # the gate can't evaluate NL→DSL without a model, so don't fail the build on
    # a config gap. Exit 0 with a clear SKIPPED marker. When secrets ARE present
    # the gate runs and enforces the threshold as before.
    if not _llm_configured():
        print("[GATE] SKIPPED — no LLM configured "
              "(set LLM_API_KEY/LLM_MODEL or llm_providers.yml to run the eval).")
        return 0

    cases_path = Path(__file__).parent / "cases.yaml"
    cases = yaml.safe_load(cases_path.read_text(encoding="utf-8"))["cases"]
    if filter_id:
        cases = [c for c in cases if c["id"] == filter_id]
        if not cases:
            print(f"No case matched id={filter_id}")
            await close_es()
            return 1

    for index in dict.fromkeys(c["index"] for c in cases):
        await warn_if_stale(index)

    # Bounded concurrency — cases are independent; running them 6-at-a-time
    # turns a ~20-min sequential run into a few minutes.
    sem = asyncio.Semaphore(6)

    async def _run_one(c: dict) -> dict:
        async with sem:
            r = await run_case(c)
        if r["status"] == "PASS":
            tail = f"hits={r.get('hits')} aggs={r.get('aggs')}"
        else:
            tail = f"{r.get('stage', '?')}: {r.get('error', '')[:200]}"
        print(f"[{r['status']:<4}] {r['id']:<24} {tail}", flush=True)
        return r

    results = list(await asyncio.gather(*[_run_one(c) for c in cases]))

    total = len(results)
    executed = sum(1 for r in results if r.get("executed"))
    correct = sum(1 for r in results if r["status"] == "PASS")
    exec_rate = executed / total if total else 0
    correct_rate = correct / total if total else 0
    print()
    print(f"Executes: {executed}/{total} = {exec_rate:.0%}  (ran against ES without error)")
    print(f"Correct : {correct}/{total} = {correct_rate:.0%}  (also satisfied the case's expect:)")

    out_path = Path(__file__).parent / "last_run.json"
    out_path.write_text(json.dumps(results, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"Details : {out_path}")

    await close_es()

    exit_code = 0
    for label, rate, threshold in (
        ("executes", exec_rate, gate_threshold),
        ("correct", correct_rate, gate_correct),
    ):
        if threshold is None:
            continue
        if rate < threshold:
            print(f"\n[GATE] FAIL — {label} rate {rate:.1%} < threshold {threshold:.0%}")
            exit_code = 1
        else:
            print(f"\n[GATE] PASS — {label} rate {rate:.1%} ≥ threshold {threshold:.0%}")
    return exit_code


if __name__ == "__main__":
    p = argparse.ArgumentParser()
    p.add_argument("--case", default=None, help="run only this case id")
    p.add_argument(
        "--gate", type=float, default=None,
        help="exit nonzero if the EXECUTES rate < threshold (e.g. --gate 0.9)",
    )
    p.add_argument(
        "--gate-correct", type=float, default=None,
        help="exit nonzero if the CORRECT rate < threshold. Set this once a "
             "correct-rate baseline has been measured — the two bars are not "
             "comparable, so the executes threshold does not carry over.",
    )
    args = p.parse_args()
    sys.exit(asyncio.run(main(args.case, args.gate, args.gate_correct)))
