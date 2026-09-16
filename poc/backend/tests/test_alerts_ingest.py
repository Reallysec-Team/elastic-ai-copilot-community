"""Alert normalize (8.x/7.x/generic), severity mapping, subject guess, broker."""
import asyncio
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent))

from backend.alerts import broker, store  # noqa: E402


# ---- normalize -----------------------------------------------------------

def test_normalize_kibana_8x():
    src = {
        "kibana.alert.uuid": "uuid-1",
        "kibana.alert.rule.name": "Suspicious login",
        "kibana.alert.rule.uuid": "rule-1",
        "kibana.alert.severity": "high",
        "@timestamp": "2026-07-06T10:00:00Z",
        "host.name": "web-01",
    }
    a = store.normalize(src)
    assert a["alert_id"] == "uuid-1"
    assert a["rule_name"] == "Suspicious login"
    assert a["rule_id"] == "rule-1"
    assert a["severity"] == "high"
    assert a["subject_field"] == "host.name" and a["subject_value"] == "web-01"


def test_normalize_siem_signals_7x_nested():
    src = {
        "signal": {"rule": {"id": "r7", "name": "Brute force", "severity": "critical"},
                   "group": {"id": "grp-7"}},
        "@timestamp": "2026-07-06T09:00:00Z",
        "source": {"ip": "10.0.0.9"},
    }
    a = store.normalize(src, doc_id="doc7")
    assert a["alert_id"] == "grp-7"
    assert a["rule_name"] == "Brute force"
    assert a["severity"] == "critical"
    assert a["subject_field"] == "source.ip" and a["subject_value"] == "10.0.0.9"


def test_normalize_falls_back_to_doc_id_and_defaults():
    a = store.normalize({"@timestamp": "2026-07-06T00:00:00Z"}, doc_id="fallback")
    assert a["alert_id"] == "fallback"
    assert a["rule_name"] == "未命名规则"
    assert a["severity"] == "info"


def test_normalize_risk_score_to_severity():
    assert store.normalize({"kibana.alert.risk_score": 95}, doc_id="x")["severity"] == "critical"
    assert store.normalize({"kibana.alert.risk_score": 75}, doc_id="x")["severity"] == "high"
    assert store.normalize({"kibana.alert.risk_score": 50}, doc_id="x")["severity"] == "medium"
    assert store.normalize({"kibana.alert.risk_score": 10}, doc_id="x")["severity"] == "low"


def test_normalize_keeps_raw_and_origin():
    src = {"kibana.alert.uuid": "u", "@timestamp": "t"}
    a = store.normalize(src, origin="webhook")
    assert a["origin"] == "webhook"
    assert a["raw"] is src


def test_normalize_captures_source_index_and_id():
    a = store.normalize({"kibana.alert.uuid": "u"}, source_index=".alerts-security.alerts-default",
                        source_id="es-doc-1")
    assert a["source_index"] == ".alerts-security.alerts-default"
    assert a["source_id"] == "es-doc-1"


def test_normalize_source_falls_back_to_payload_index_id():
    # Source B webhook payloads may embed _index/_id — normalize should pick them up.
    a = store.normalize({"kibana.alert.uuid": "u", "_index": "idx-7", "_id": "id-7"}, origin="webhook")
    assert a["source_index"] == "idx-7"
    assert a["source_id"] == "id-7"


def test_subject_value_list_takes_first():
    a = store.normalize({"kibana.alert.uuid": "u", "host.name": ["h1", "h2"]}, doc_id="u")
    assert a["subject_value"] == "h1"


# ---- broker --------------------------------------------------------------

def test_broker_publish_reaches_subscriber():
    q = broker.subscribe()
    try:
        broker.publish({"alert_id": "a1"})
        assert q.get_nowait() == {"alert_id": "a1"}
    finally:
        broker.unsubscribe(q)


def test_broker_drops_oldest_when_full():
    q = broker.subscribe()
    try:
        for i in range(broker._MAX_QUEUE + 5):
            broker.publish({"alert_id": i})
        # queue is capped; oldest were dropped, newest retained
        drained = []
        while not q.empty():
            drained.append(q.get_nowait()["alert_id"])
        assert len(drained) == broker._MAX_QUEUE
        assert drained[-1] == broker._MAX_QUEUE + 4  # newest kept
        assert 0 not in drained  # oldest dropped
    finally:
        broker.unsubscribe(q)


def test_broker_unsubscribe_stops_delivery():
    q = broker.subscribe()
    broker.unsubscribe(q)
    broker.publish({"alert_id": "x"})
    assert q.empty()
