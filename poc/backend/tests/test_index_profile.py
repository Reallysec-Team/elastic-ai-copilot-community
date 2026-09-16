"""Index profile detection (#index-profile) — no LLM/ES, pure function tests.

Covers `prompts.index_profile()` rule priority and its integration into
`prompts.build_user_prompt()` via the `数据类型:` line.
"""
from __future__ import annotations

import sys
from pathlib import Path

_POC = Path(__file__).resolve().parent.parent.parent
if str(_POC) not in sys.path:
    sys.path.insert(0, str(_POC))

from backend import prompts  # noqa: E402


def _mapping(properties: dict) -> dict:
    """Wrap a flat {field: {type: ...}} properties dict the way ES mappings look."""
    return {"my-index": {"mappings": {"properties": properties}}}


def test_windows_event_log_via_winlog_prefix():
    fields = {"winlog.event_id": "long", "winlog.channel": "keyword"}
    assert "Windows" in prompts.index_profile(fields)


def test_windows_event_log_via_event_code_and_module():
    fields = {"event.code": "keyword", "event.module": "keyword"}
    assert "Windows" in prompts.index_profile(fields)


def test_kubernetes_log():
    fields = {"kubernetes.pod.name": "keyword", "kubernetes.namespace": "keyword"}
    assert "Kubernetes" in prompts.index_profile(fields)


def test_web_access_log_via_status_code():
    fields = {"http.response.status_code": "long"}
    assert "Web 访问" in prompts.index_profile(fields)


def test_web_access_log_via_url_path_and_user_agent():
    fields = {"url.path": "keyword", "user_agent.original": "keyword"}
    assert "Web 访问" in prompts.index_profile(fields)


def test_dns_query_log():
    fields = {"dns.question.name": "keyword"}
    assert "DNS" in prompts.index_profile(fields)


def test_network_traffic_log():
    fields = {"source.ip": "ip", "destination.ip": "ip"}
    assert "网络流量" in prompts.index_profile(fields)


def test_host_endpoint_process_log():
    fields = {"process.name": "keyword", "host.name": "keyword"}
    assert "端点" in prompts.index_profile(fields)


def test_application_service_log():
    fields = {"service.name": "keyword", "log.level": "keyword"}
    assert "应用服务" in prompts.index_profile(fields)


def test_no_match_returns_none():
    fields = {"@timestamp": "date", "message": "text"}
    assert prompts.index_profile(fields) is None


def test_priority_windows_over_web():
    # winlog.* + http.response.status_code both present → Windows wins (rule 1 > rule 3).
    fields = {"winlog.event_id": "long", "http.response.status_code": "long"}
    result = prompts.index_profile(fields)
    assert "Windows" in result
    assert "Web" not in result


def test_priority_network_only_when_no_higher_rule_matches():
    # source.ip + destination.ip alone → network traffic.
    fields = {"source.ip": "ip", "destination.ip": "ip", "dns.question.name": "keyword"}
    result = prompts.index_profile(fields)
    # DNS (rule 4) outranks network traffic (rule 5).
    assert "DNS" in result
    assert "网络流量" not in result


def test_build_user_prompt_includes_data_type_line_when_matched():
    mapping = _mapping({
        "winlog": {"properties": {"event_id": {"type": "long"}}},
        "@timestamp": {"type": "date"},
    })
    prompt = prompts.build_user_prompt("查询失败登录", "my-index", mapping)
    assert "数据类型:" in prompt
    assert "Windows" in prompt


def test_build_user_prompt_omits_data_type_line_when_no_match():
    mapping = _mapping({
        "@timestamp": {"type": "date"},
        "message": {"type": "text"},
    })
    prompt = prompts.build_user_prompt("查询消息", "my-index", mapping)
    assert "数据类型:" not in prompt
