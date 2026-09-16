"""Extract candidate asset/identity entities from an alert `raw` source and
normalize their join keys. Pure — no ES. This is the MVP join-key生死线:
dirty keys (FQDN vs short name, DOMAIN\\user vs UPN) must all normalize or the
resolver全 miss and the detail card is empty."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, TypedDict

from ..alerts.store import dig


class AssetContext(TypedDict, total=False):
    business_name: str | None
    criticality: str | None
    category: str | None
    owner: str | None
    department: str | None
    source: str
    confidence: str
    candidates: int


@dataclass(frozen=True)
class Entity:
    kind: str            # "host" | "user" | "ip"
    keys: tuple[str, ...]
    value: str


def _first(v: Any) -> str:
    if isinstance(v, list):
        v = v[0] if v else ""
    return str(v or "").strip()


def normalize_host(v: str) -> list[str]:
    v = _first(v).lower()
    if not v:
        return []
    short = v.split(".")[0]
    return [v] if short == v else [v, short]


def normalize_user(v: str) -> str:
    v = _first(v)
    if "\\" in v:            # DOMAIN\user
        v = v.split("\\", 1)[1]
    if "@" in v:            # user@domain UPN
        v = v.split("@", 1)[0]
    return v.lower()


def normalize_ip(v: str) -> str:
    return _first(v)


_HOST_FIELDS = ("host.name", "host.hostname")
_USER_FIELDS = ("user.name",)
_IP_FIELDS = ("source.ip", "host.ip", "destination.ip")


def extract_entities(raw: dict[str, Any]) -> list[Entity]:
    """host, user, ip in priority order (stable keys before IP)."""
    out: list[Entity] = []
    hv = dig(raw, *_HOST_FIELDS)
    if hv:
        keys = normalize_host(hv)
        if keys:
            out.append(Entity("host", tuple(keys), _first(hv)))
    uv = dig(raw, *_USER_FIELDS)
    if uv:
        k = normalize_user(uv)
        if k:
            out.append(Entity("user", (k,), _first(uv)))
    iv = dig(raw, *_IP_FIELDS)
    if iv:
        k = normalize_ip(iv)
        if k:
            out.append(Entity("ip", (k,), k))
    return out
