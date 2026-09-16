"""Detection Rule Copilot: take a natural-language description of a detection
intent and produce a Kibana Detection Engine rule body (8.12).

Supports rule types: query (KQL/Lucene), threshold, eql. ML / new_terms /
threat_match are intentionally out of scope — refusal is expected.

Output is shaped so the operator can POST it directly to
`/api/detection_engine/rules` after review. We never set `enabled: true`,
never assign an `id`, and strip any script/runtime fields the LLM might emit.

SEC-CC-1: the rule normalization/sanitization engine — the premium IP of this
feature — is NOT in this file. It ships ENCRYPTED as
``premium/detection_rule_copilot.sealed`` and is decrypted in memory only when a
genuine, host-bound, entitled license carries the feature's wrapped data key
(see ``feature_unlock.py``). Patching the license check or forging an enterprise
tier therefore unlocks nothing: without the server-signed keyring there is no
key to decrypt the engine, so generation fails SAFE.
"""

import logging
from typing import Any


from . import feature_unlock
from .field_masking import mask_doc
from .llm import parse_json, lift_contract_keys
from .llm_router import get_router
from .prompts import detection_rule_system_prompt, build_detection_rule_prompt
from .rag import augment_prompt_meta

logger = logging.getLogger("rst.detection_rule")

FEATURE = "detection_rule_copilot"


async def generate_detection_rule(
    question: str,
    index: str,
    mapping: dict[str, Any],
    rule_type_hint: str | None = None,
) -> dict[str, Any]:
    # SEC-CC-1: unlock the sealed normalization engine BEFORE spending an LLM
    # call. Raises FeatureLocked when this host's license can't unwrap it — the
    # endpoint maps that to a clear "not entitled on this host" response.
    core = feature_unlock.load_premium(FEATURE)
    normalize = core["normalize"]

    masked_mapping = mask_doc(mapping) if isinstance(mapping, dict) else mapping
    user_prompt = build_detection_rule_prompt(question, index, masked_mapping, rule_type_hint)
    user_prompt, rag_used = await augment_prompt_meta(user_prompt, top_k=3)
    resp, _provider = await get_router().chat_completion(
        messages=[
            {"role": "system", "content": detection_rule_system_prompt()},
            {"role": "user", "content": user_prompt},
        ],
        temperature=0,
        reasoning="high",  # 检测规则：付费引擎，要推理
    )
    # Empty `choices` would IndexError → opaque 500. Treat a missing/malformed
    # model reply as a transient failure (RuntimeError → 500 "failed, retry"),
    # NOT a content rejection (ValueError → 422 "rejected"). Only `normalize`
    # raising ValueError represents a genuine content-level rejection.
    if not resp.choices:
        raise RuntimeError("模型未返回内容,请重试。")
    raw = resp.choices[0].message.content or ""
    try:
        payload = parse_json(raw)
    except ValueError as e:
        raise RuntimeError(f"模型输出无法解析,请重试: {e}")
    # parse_json may return a top-level list (LLM emitted a JSON array) — normalize
    # expects a dict, so guard here rather than let a TypeError bubble up as a 500.
    if not isinstance(payload, dict):
        raise RuntimeError("模型返回格式异常,请重试。")
    # Same slip as the NL→DSL path: the brace closing `rule` goes missing and the
    # sibling contract keys end up inside the rule body.
    payload = lift_contract_keys(payload, "rule")
    result = normalize(payload, index)
    if isinstance(result, dict):
        # Surface KB influence so a changed rule after a KB edit isn't mysterious.
        result["rag_chunks_used"] = rag_used
    return result
