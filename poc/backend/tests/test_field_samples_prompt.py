"""Sample values must reach the NL→DSL prompt — and must be masked on the way.

The regression this guards: asked for "登录失败" against a Windows security
index, the model wrote `match_phrase: {message: "登录失败"}` — a field that does
not exist there — because the prompt only listed field names and types. The
answer it needed was `event.code: 4625`, which is obvious once the prompt says
event.code only ever holds 4624 / 4625 / 4740.
"""
import pytest

from backend import field_dict
from backend.prompts import build_user_prompt

MAPPING = {
    "idx": {
        "mappings": {
            "properties": {
                "event": {"properties": {"code": {"type": "keyword"}}},
                "message": {"type": "text"},
            }
        }
    }
}


def test_samples_render_into_the_field_list():
    out = build_user_prompt(
        "最近 30 天登录失败的事件",
        "idx",
        MAPPING,
        field_samples={"event.code": ["4624", "4625", "4740"]},
    )
    assert "- event.code: keyword  取值: 4624, 4625, 4740" in out
    # A field with no samples keeps the plain name+type line.
    assert "- message: text" in out


def test_prompt_is_unchanged_without_samples():
    # The header explains the column and always mentions 取值; what must be
    # absent is the per-field marker (two spaces before it).
    assert "  取值: " not in build_user_prompt("q", "idx", MAPPING)


def test_only_low_cardinality_non_date_fields_are_sampleable():
    assert field_dict._sampleable({"type": "keyword", "cardinality_approx": 3})
    # A near-unique field's top-N says nothing and ships data for nothing.
    assert not field_dict._sampleable({"type": "keyword", "cardinality_approx": 100_000})
    # Timestamps: the useful fact is the range, not five sampled instants.
    assert not field_dict._sampleable({"type": "date", "cardinality_approx": 5})
    # Unaggregatable fields come back with no cardinality at all.
    assert not field_dict._sampleable({"type": "text", "cardinality_approx": None})


@pytest.mark.asyncio
async def test_sample_values_are_masked_and_bounded(monkeypatch):
    async def fake_dict(index, sample_size=5):
        return {
            "fields": [
                {
                    "name": "event.code",
                    "type": "keyword",
                    "cardinality_approx": 3,
                    "samples": [{"value": v, "count": 1} for v in ("4624", "4625", "4740")],
                },
                {
                    "name": "user.name",
                    "type": "keyword",
                    "cardinality_approx": 2,
                    "samples": [{"value": "zhangwei", "count": 1}],
                },
                {
                    "name": "source.ip",
                    "type": "ip",
                    "cardinality_approx": 9_000,  # too many to be an enum
                    "samples": [{"value": "10.0.0.1", "count": 1}],
                },
            ]
        }

    monkeypatch.setattr(field_dict, "get_field_dictionary", fake_dict)
    monkeypatch.setenv("RST_MASKING_MODE", "cloud")
    from backend import field_masking

    field_masking.reset_cached_mode() if hasattr(field_masking, "reset_cached_mode") else None

    out = await field_dict.sample_values_for_prompt("idx")

    # Enum-ish codes survive verbatim — they are the whole point.
    assert out["event.code"] == ["4624", "4625", "4740"]
    # High-cardinality fields are dropped entirely.
    assert "source.ip" not in out
    # Usernames go through the same masking policy as every model-facing payload.
    assert out["user.name"] != ["zhangwei"] or field_masking.current_mode() == "airgapped"


@pytest.mark.asyncio
async def test_field_dict_failure_degrades_instead_of_breaking(monkeypatch):
    async def boom(index, sample_size=5):
        raise RuntimeError("ES down")

    monkeypatch.setattr(field_dict, "get_field_dictionary", boom)
    assert await field_dict.sample_values_for_prompt("idx") == {}


@pytest.mark.asyncio
async def test_multi_index_widens_the_per_field_sample(monkeypatch):
    """Across several indices the samples are a union, and a top-5 cut drops the
    spelling only one source uses (`ERROR` fell off behind `info/INFO/warning/
    information/error`, and the model filtered on a value the Java stream never
    writes). The sample width has to grow with the number of indices."""
    asked: list[int] = []

    async def fake_dict(index, sample_size=5):
        asked.append(sample_size)
        return {
            "fields": [{
                "name": "log.level",
                "type": "keyword",
                "cardinality_approx": 6,
                "samples": [{"value": v, "count": 1}
                            for v in ("info", "INFO", "warning", "information", "error", "ERROR")],
            }]
        }

    monkeypatch.setattr(field_dict, "get_field_dictionary", fake_dict)

    single = await field_dict.sample_values_for_prompt("logs-app.java-default")
    assert asked[-1] == field_dict._SAMPLE_VALUES_PER_FIELD

    both = await field_dict.sample_values_for_prompt("logs-app.java-default,logs-docker.container-default")
    assert asked[-1] == 2 * field_dict._SAMPLE_VALUES_PER_FIELD
    assert "ERROR" in both["log.level"] and "error" in both["log.level"]
    assert len(both["log.level"]) >= len(single["log.level"])


@pytest.mark.asyncio
async def test_sample_width_is_capped(monkeypatch):
    """Widening is bounded — a 20-index selection must not ask ES for 160 terms
    per field, nor paste them all into the prompt."""
    asked: list[int] = []

    async def fake_dict(index, sample_size=5):
        asked.append(sample_size)
        return {"fields": []}

    monkeypatch.setattr(field_dict, "get_field_dictionary", fake_dict)
    await field_dict.sample_values_for_prompt(",".join(f"idx-{i}" for i in range(20)))
    assert asked[-1] == field_dict._SAMPLE_VALUES_MAX
