"""Entity extraction + normalization — the join-key生死线. Pure, no ES."""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent))

from backend.enrich import entity  # noqa: E402


def test_normalize_host_fqdn_and_short():
    assert entity.normalize_host("WIN-DB01.corp.local") == ["win-db01.corp.local", "win-db01"]


def test_normalize_host_bare_short():
    assert entity.normalize_host("Web-07") == ["web-07"]


def test_normalize_host_dedupes_when_no_dot():
    # short == fqdn → single key, no duplicate
    assert entity.normalize_host("host") == ["host"]


def test_normalize_user_strips_domain_prefix():
    assert entity.normalize_user("CORP\\jsmith") == "jsmith"


def test_normalize_user_strips_upn_suffix():
    assert entity.normalize_user("jsmith@corp.local") == "jsmith"


def test_normalize_user_lowercases():
    assert entity.normalize_user("JSmith") == "jsmith"


def test_normalize_ip_exact():
    assert entity.normalize_ip(" 203.0.113.5 ") == "203.0.113.5"


def test_extract_priority_order_host_before_user_before_ip():
    raw = {"host.name": "WIN-DB01.corp.local", "user.name": "CORP\\jsmith",
           "source.ip": "203.0.113.5"}
    kinds = [e.kind for e in entity.extract_entities(raw)]
    assert kinds == ["host", "user", "ip"]


def test_extract_handles_list_values():
    raw = {"host": {"name": ["win-db01.corp.local", "other"]}}
    ents = entity.extract_entities(raw)
    assert ents[0].kind == "host"
    assert "win-db01" in ents[0].keys


def test_extract_empty_when_no_entities():
    assert entity.extract_entities({"message": "hello"}) == []
