"""Pure validation for in-app authored baseline rules (no ES)."""
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent))

from backend.baseline.rule_input import validate_rule_payload  # noqa: E402
from backend.baseline.schema import Rule  # noqa: E402


def _equals_rule(**over):
    d = {
        "rule_id": "custom-ssh-root",
        "title": "SSH 禁止 root 登录",
        "category": "ssh",
        "platform": "linux",
        "severity": "high",
        "judge": {"operator": "equals", "field": "value", "expected": "no", "on_missing": "fail"},
        "collect": {"query": "SELECT value FROM ssh_configs WHERE key='PermitRootLogin';"},
        "standard_refs": ["等保2.0-8.1.4.2"],
        "remediation_template": "设置 PermitRootLogin no 并重启 sshd",
    }
    d.update(over)
    return d


def test_valid_equals_rule_round_trips():
    rule = validate_rule_payload(_equals_rule())
    assert isinstance(rule, Rule)
    assert rule.rule_id == "custom-ssh-root"
    assert rule.judge.operator == "equals"
    assert rule.judge.expected == "no"
    assert rule.query_name == "custom-ssh-root"  # defaults to rule_id


def test_valid_manual_rule_needs_no_query():
    rule = validate_rule_payload({
        "rule_id": "manual-review-1",
        "title": "人工复核项",
        "judge": {"operator": "manual_review"},
        "collect": {},
    })
    assert rule.judge.operator == "manual_review"


@pytest.mark.parametrize("rid", ["ab", "", "has space", "x" * 65, "bad/slash"])
def test_bad_rule_id_rejected(rid):
    with pytest.raises(ValueError, match="rule_id"):
        validate_rule_payload(_equals_rule(rule_id=rid))


def test_empty_title_rejected():
    with pytest.raises(ValueError, match="title"):
        validate_rule_payload(_equals_rule(title="  "))


def test_unknown_operator_rejected():
    with pytest.raises(ValueError, match="operator"):
        validate_rule_payload(_equals_rule(judge={"operator": "wat"}))


def test_equals_without_expected_rejected():
    with pytest.raises(ValueError, match="expected"):
        validate_rule_payload(_equals_rule(judge={"operator": "equals", "field": "value"}))


def test_equals_without_field_rejected():
    with pytest.raises(ValueError, match="field"):
        validate_rule_payload(_equals_rule(judge={"operator": "equals", "expected": "no"}))


def test_data_operator_without_query_rejected():
    with pytest.raises(ValueError, match="collect.query"):
        validate_rule_payload(_equals_rule(collect={"query": ""}))


def test_bad_severity_rejected():
    with pytest.raises(ValueError, match="severity"):
        validate_rule_payload(_equals_rule(severity="apocalyptic"))


def test_expect_empty_needs_field_not_expected():
    # expect_empty needs a field but not an expected value.
    rule = validate_rule_payload({
        "rule_id": "no-world-writable",
        "title": "无全局可写文件",
        "judge": {"operator": "expect_empty", "field": "path", "on_missing": "pass"},
        "collect": {"query": "SELECT path FROM file WHERE ...;"},
    })
    assert rule.judge.operator == "expect_empty"
