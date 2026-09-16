"""Eval harness for v1.0.4 Detection Rule Copilot.

Pass = generate_detection_rule produces a rule whose:
  - rule_type matches expected_rule_type
  - rule.query (or eql query body) contains ≥1 expected_keyword (case-insensitive)
For refusal cases (expected_rule_type: null), rule must be None.

Usage (run from `poc/` directory):
    python -m eval.run_detection_rule
    python -m eval.run_detection_rule --case threshold-brute-force
    python -m eval.run_detection_rule --gate 0.7
"""
import argparse
import asyncio
import json
import sys
from pathlib import Path

import yaml
from dotenv import load_dotenv

load_dotenv()

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from backend.detection_rule import generate_detection_rule  # noqa: E402
from backend.es_client import close_es, get_mapping  # noqa: E402


async def run_case(case: dict) -> dict:
    cid = case["id"]
    q = case["question"]
    idx = case["index"]
    expected_type = case.get("expected_rule_type")
    expected_kws = [str(k).lower() for k in case.get("expected_keywords") or []]

    try:
        mapping = await get_mapping(idx)
    except Exception:
        # Many seed cases reference indices that may not exist locally; that's fine —
        # the LLM can still attempt generation from the index name + question alone.
        mapping = {}

    try:
        result = await generate_detection_rule(q, idx, mapping)
    except Exception as e:
        return {"id": cid, "status": "FAIL", "stage": "llm_or_validate", "error": str(e)}

    rule = result.get("rule")
    rt = result.get("rule_type")

    if expected_type is None:
        if rule is None:
            return {"id": cid, "status": "PASS", "kind": "refusal"}
        return {
            "id": cid, "status": "FAIL", "stage": "expected_refusal",
            "error": f"expected refusal but got rule_type={rt}",
            "rule_type": rt,
        }

    if rule is None:
        return {"id": cid, "status": "FAIL", "stage": "unexpected_refusal",
                "error": "expected a rule but model refused"}

    if rt != expected_type:
        return {
            "id": cid, "status": "FAIL", "stage": "rule_type_mismatch",
            "error": f"expected rule_type={expected_type}, got {rt}",
            "rule_type": rt,
        }

    query_text = str(rule.get("query") or "").lower()
    if expected_kws and not any(k in query_text for k in expected_kws):
        return {
            "id": cid, "status": "FAIL", "stage": "missing_keyword",
            "error": f"none of {expected_kws} found in query: {query_text[:200]}",
            "rule_type": rt,
        }

    return {"id": cid, "status": "PASS", "kind": "rule", "rule_type": rt}


async def main(filter_id: str | None, gate_threshold: float | None) -> int:
    cases_path = Path(__file__).parent / "detection_rule.yaml"
    cases = yaml.safe_load(cases_path.read_text(encoding="utf-8"))["cases"]
    if filter_id:
        cases = [c for c in cases if c["id"] == filter_id]
        if not cases:
            print(f"No case matched id={filter_id}")
            await close_es()
            return 1

    results = []
    for c in cases:
        r = await run_case(c)
        results.append(r)
        tail = (
            f"{r.get('kind', '')} rule_type={r.get('rule_type', '-')}"
            if r["status"] == "PASS"
            else f"{r.get('stage', '?')}: {(r.get('error') or '')[:200]}"
        )
        print(f"[{r['status']:<4}] {r['id']:<28} {tail}")

    passed = sum(1 for r in results if r["status"] == "PASS")
    total = len(results)
    rate = passed / total if total else 0
    print()
    print(f"Pass rate: {passed}/{total} = {rate:.0%}")

    out_path = Path(__file__).parent / "last_run_detection_rule.json"
    out_path.write_text(json.dumps(results, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"Details : {out_path}")

    await close_es()

    exit_code = 0
    if gate_threshold is not None:
        if rate < gate_threshold:
            print(f"\n[GATE] FAIL — pass rate {rate:.1%} < threshold {gate_threshold:.0%}")
            exit_code = 1
        else:
            print(f"\n[GATE] PASS — pass rate {rate:.1%} ≥ threshold {gate_threshold:.0%}")
    return exit_code


if __name__ == "__main__":
    p = argparse.ArgumentParser()
    p.add_argument("--case", default=None, help="run only this case id")
    p.add_argument(
        "--gate", type=float, default=None,
        help="exit nonzero if pass rate < threshold (e.g. --gate 0.7)",
    )
    args = p.parse_args()
    sys.exit(asyncio.run(main(args.case, args.gate)))
