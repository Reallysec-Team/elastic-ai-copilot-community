"""Every JSON-emitting prompt must carry the same output contract.

These are the rules whose ABSENCE is invisible until a customer sees it: a
prompt without the half-width-punctuation clause parses fine in testing and then
returns "AI 返回格式错误" the first time the model reaches for a full-width ，.
"""
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent))

from backend import prompts  # noqa: E402
from conftest import premium_core  # noqa: E402

# The four that declare a JSON schema inline and share _JSON_ONLY +
# _OUTPUT_DISCIPLINE. SYSTEM_PROMPT and the detection-rule prompt use the
# numbered "严格遵守：" form and carry their own copy of these rules — they are
# deliberately excluded (SYSTEM_PROMPT in particular is pinned by the NL→DSL
# eval gate, so it does not get edited for tidiness).
#
# Read through the getters, not the constants: the investigate and triage
# prompts are SEC-CC-1 sealed (the text lives in premium_src/, not here), so
# on a checkout without the vault those two skip instead of failing.
SCHEMA_PROMPTS = [
    ("explain", None, prompts.explain_system_prompt),
    ("explain_result", None, prompts.explain_result_system_prompt),
    ("investigate", "alert_investigation", prompts.investigate_system_prompt),
    ("triage", "alert_triage", prompts.triage_system_prompt),
]
_IDS = [p[0] for p in SCHEMA_PROMPTS]


def _text(feature, getter):
    if feature:
        premium_core(feature)
    return getter()


@pytest.mark.parametrize("name,feature,getter", SCHEMA_PROMPTS, ids=_IDS)
def test_schema_prompts_forbid_full_width_json_punctuation(name, feature, getter):
    assert "半角" in _text(feature, getter)


@pytest.mark.parametrize("name,feature,getter", SCHEMA_PROMPTS, ids=_IDS)
def test_schema_prompts_carry_the_output_discipline(name, feature, getter):
    text = _text(feature, getter)
    for rule in ("不复述输入", "不含糊其辞", "不硬凑"):
        assert rule in text, f"{name} lost «{rule}»"


@pytest.mark.parametrize("name,feature,getter", SCHEMA_PROMPTS, ids=_IDS)
def test_the_shared_language_rule_is_not_also_duplicated_per_prompt(name, feature, getter):
    """It used to be four near-copies with different example terms."""
    assert _text(feature, getter).count("中文输出，技术术语保留英文") == 1


def test_the_agentic_prompt_still_finds_its_slice_point():
    """AGENTIC_INVESTIGATE_SYSTEM_PROMPT is built by slicing INVESTIGATE at
    "严格按以下" and pasting a tool-use preamble in front. That phrase now lives
    in the shared _JSON_ONLY block, so editing it silently changes what the
    agentic loop is told — or raises ValueError at import."""
    premium_core("alert_investigation")
    agentic = prompts.agentic_investigate_system_prompt()
    assert agentic.startswith("你是 SOC 高级分析师，具备")
    assert "es_search" in agentic, "the tool-use preamble must survive"
    # everything after the slice point comes along, including the shared blocks
    assert "严格按以下" in agentic
    assert "半角" in agentic
    assert "不复述输入" in agentic
    # and the single-step prompt's own opener must NOT leak in
    assert "给定一条告警/事件文档" not in agentic
