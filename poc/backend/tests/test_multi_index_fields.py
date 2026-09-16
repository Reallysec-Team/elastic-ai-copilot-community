"""Cross-index prompting (#multi-index) — pure function tests, no LLM/ES.

The failure this guards: with ten ops data streams selected, every field was
merged into one flat list, so the model put `url.path` (nginx only) in the
top-level `must` and the other nine sources matched nothing — a silent false
negative that reads like "nothing else was wrong".
"""
from __future__ import annotations

import sys
from pathlib import Path

_POC = Path(__file__).resolve().parent.parent.parent
if str(_POC) not in sys.path:
    sys.path.insert(0, str(_POC))

from backend import prompts  # noqa: E402


def _idx(properties: dict) -> dict:
    return {"mappings": {"properties": {k: {"type": v} for k, v in properties.items()}}}


COMMON = {"@timestamp": "date", "message": "text"}
NGINX = {**COMMON, "url.path": "keyword", "http.response.status_code": "long"}
JAVA = {**COMMON, "log.level": "keyword", "service.name": "keyword"}


def test_fields_by_source_keeps_ownership():
    by_source = prompts._fields_by_source({"logs-nginx": _idx(NGINX), "logs-java": _idx(JAVA)})
    assert set(by_source) == {"logs-nginx", "logs-java"}
    assert "url.path" in by_source["logs-nginx"]
    assert "url.path" not in by_source["logs-java"]


def test_data_stream_backing_indices_collapse_to_the_stream_name():
    """get_mapping on a data stream answers with `.ds-…-000001` backing indices.

    Two backing indices of one stream must not become two groups, and the group
    must be named the thing the operator can actually query.
    """
    by_source = prompts._fields_by_source({
        ".ds-logs-nginx.access-default-2026.09.01-000001": _idx(NGINX),
        ".ds-logs-nginx.access-default-2026.09.03-000002": _idx(NGINX),
    })
    assert list(by_source) == ["logs-nginx.access-default"]


def test_multi_index_prompt_groups_fields_and_names_the_owner():
    prompt = prompts.build_user_prompt(
        "结账接口今天下午出故障了",
        "logs-nginx,logs-java",
        {"logs-nginx": _idx(NGINX), "logs-java": _idx(JAVA)},
    )
    # Shared core listed once, not per index.
    assert prompt.count("- @timestamp: date") == 1
    assert "【所有索引共有】" in prompt
    # Index-specific fields sit under their owner's header.
    nginx_block = prompt.split("【logs-nginx】")[1].split("【")[0]
    assert "url.path" in nginx_block
    assert "log.level" not in nginx_block
    assert "字段按索引分组" in prompt


def test_single_index_prompt_is_unchanged():
    prompt = prompts.build_user_prompt("登录失败", "logs-nginx", {"logs-nginx": _idx(NGINX)})
    assert "【所有索引共有】" not in prompt
    assert "字段按索引分组" not in prompt
    assert "- url.path: keyword" in prompt


def test_multi_index_suppresses_the_merged_data_type_guess():
    """`index_profile` is first-rule-wins; over a merged soup it labels the whole
    query as whatever matched first. Per-group labels replace it."""
    prompt = prompts.build_user_prompt(
        "错误", "logs-nginx,logs-java", {"logs-nginx": _idx(NGINX), "logs-java": _idx(JAVA)}
    )
    assert "\n数据类型: " not in prompt  # no single top-level label
    assert "【logs-nginx】  数据类型: " in prompt  # nginx still profiled as web access log


def test_system_prompt_carries_the_cross_index_rule():
    assert "minimum_should_match" in prompts.SYSTEM_PROMPT
    assert "多索引查询" in prompts.SYSTEM_PROMPT
