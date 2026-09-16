"""Embedding client for RAG.

By default reuses the FIRST enabled provider's `base_url` + `api_key` from
`llm_router.get_router()` — fine when the chat endpoint also serves
`/v1/embeddings` (OpenAI, DashScope, …). When the embedding model lives on a
DIFFERENT endpoint than chat (e.g. Volcengine Ark's `coding/v3` serves chat
only, no embeddings), set RST_EMBED_BASE_URL to point embeddings elsewhere.

Env vars:
  RST_EMBED_MODEL     — embedding model id (provider-specific). REQUIRED.
                        e.g. "text-embedding-3-small" / "doubao-embedding" /
                        "nomic-embed-text".
  RST_EMBED_BASE_URL  — optional: embedding endpoint URL, when different from
                        the chat provider's base_url.
  RST_EMBED_API_KEY   — optional: api key for RST_EMBED_BASE_URL (defaults to a
                        placeholder — local servers like Ollama need none).
  RST_EMBED_DIM       — embedding vector dimension. Default 1536. Used by
                        `rag.py` for the ES `dense_vector` mapping; must match
                        what the model returns (e.g. nomic-embed-text → 768).

Singleton model: `get_embedding_client()` caches a single `EmbeddingClient`.
`reset()` clears the cache (used by tests / config-reload paths).
"""

from __future__ import annotations

import logging
import os
import time
from typing import Any

from openai import AsyncOpenAI

from .llm_router import config_path, get_router

logger = logging.getLogger("rst.embeddings")

DEFAULT_EMBED_DIM = 1536
DEFAULT_EMBED_BATCH = 16

import yaml

EMBED_PROBE_TEXT = "connectivity probe"


def _embed_batch() -> int:
    """Max number of texts per /v1/embeddings call. Conservative default (16) to
    stay under provider per-request limits (e.g. DashScope caps at 25/batch)."""
    raw = os.environ.get("RST_EMBED_BATCH", "").strip()
    if not raw:
        return DEFAULT_EMBED_BATCH
    try:
        v = int(raw)
        if v <= 0:
            raise ValueError
        return v
    except ValueError:
        logger.warning(
            "invalid_embed_batch",
            extra={"value": raw, "fallback": DEFAULT_EMBED_BATCH},
        )
        return DEFAULT_EMBED_BATCH


def _embed_model() -> str:
    cfg = load_embedding_config()
    if cfg is not None and cfg["enabled"]:
        return cfg["model"]
    raw = os.environ.get("RST_EMBED_MODEL", "").strip()
    if not raw:
        raise RuntimeError(
            "RST_EMBED_MODEL is not set. Embedding model id is provider-specific "
            "(e.g. 'text-embedding-3-small', 'doubao-embedding', 'text-embedding-v2'); "
            "set it in the gateway env / .env file, or configure it in the AI settings page."
        )
    return raw


def embed_dim() -> int:
    cfg = load_embedding_config()
    if cfg is not None and cfg["enabled"] and cfg["dims"] > 0:
        return cfg["dims"]
    raw = os.environ.get("RST_EMBED_DIM", "").strip()
    if not raw:
        return DEFAULT_EMBED_DIM
    try:
        v = int(raw)
        if v <= 0:
            raise ValueError
        return v
    except ValueError:
        logger.warning(
            "invalid_embed_dim",
            extra={"value": raw, "fallback": DEFAULT_EMBED_DIM},
        )
        return DEFAULT_EMBED_DIM


def load_embedding_config() -> dict | None:
    """Read the `embedding:` section from llm_providers.yml.

    Returns a normalized dict, or None when the file is missing, has no
    `embedding` key, or the model is empty (→ treated as unconfigured, KB off).
    """
    cfg = config_path()
    if not cfg.exists():
        return None
    try:
        raw = yaml.safe_load(cfg.read_text(encoding="utf-8")) or {}
    except Exception as e:  # noqa: BLE001
        logger.warning("embedding_config_read_failed", extra={"error": str(e)[:200]})
        return None
    emb = raw.get("embedding")
    if not isinstance(emb, dict):
        return None
    model = (emb.get("model") or "").strip()
    if not model:
        return None
    dims_raw = emb.get("dims")
    try:
        dims = int(dims_raw) if dims_raw is not None else 0
    except (TypeError, ValueError):
        dims = 0
    return {
        "model": model,
        "base_url": (emb.get("base_url") or "").strip(),
        "api_key": (emb.get("api_key") or "").strip(),
        "dims": dims,
        "enabled": bool(emb.get("enabled", True)),
    }


def save_embedding_config(cfg_dict: dict) -> None:
    """Write the `embedding:` section, preserving `providers:` / `routing:`.

    Read-modify-write the whole yml so a providers list saved earlier is never
    clobbered. Mirror of llm_router.save_providers preserving `embedding:`.
    """
    path = config_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    raw: dict = {}
    if path.exists():
        try:
            raw = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
        except Exception as e:  # noqa: BLE001
            logger.warning("embedding_config_merge_read_failed", extra={"error": str(e)[:200]})
            raw = {}
    raw["embedding"] = {
        "model": (cfg_dict.get("model") or "").strip(),
        "base_url": (cfg_dict.get("base_url") or "").strip(),
        "api_key": (cfg_dict.get("api_key") or "").strip(),
        "dims": int(cfg_dict.get("dims") or 0),
        "enabled": bool(cfg_dict.get("enabled", True)),
    }
    path.write_text(yaml.safe_dump(raw, sort_keys=False, allow_unicode=True), encoding="utf-8")
    logger.info("embedding_config_saved", extra={"path": str(path), "model": raw["embedding"]["model"]})


def embedding_configured() -> bool:
    """True when RAG/KB should be considered ON: a yml embedding config with an
    enabled model, OR the legacy RST_EMBED_MODEL env fallback."""
    cfg = load_embedding_config()
    if cfg is not None and cfg["enabled"]:
        return True
    return bool(os.environ.get("RST_EMBED_MODEL", "").strip())


def _embed_endpoint() -> tuple[str, str] | None:
    """Explicit embedding endpoint override. Returns (base_url, api_key) when
    RST_EMBED_BASE_URL is set, else None → reuse the chat provider's endpoint."""
    base = os.environ.get("RST_EMBED_BASE_URL", "").strip()
    if not base:
        return None
    api_key = os.environ.get("RST_EMBED_API_KEY", "").strip() or "not-needed"
    return base, api_key


def resolve_endpoint(base_url: str, api_key: str) -> tuple[str, str]:
    """Fill blank base_url / api_key from the first ENABLED chat provider.

    A blank base_url means "reuse the chat endpoint"; a blank api_key means
    "reuse the chat key". Raises RuntimeError if base is blank and no provider
    exists to borrow from.
    """
    base = (base_url or "").strip()
    key = (api_key or "").strip()
    if base and key:
        return base, key
    first = next((p for p in get_router().providers if p.enabled), None)
    if not base:
        if first is None:
            raise RuntimeError(
                "embedding base_url 为空且没有可复用的 enabled chat provider。"
                "请填写 Base URL 或先配置聊天模型。"
            )
        base = first.base_url
    if not key:
        key = first.api_key if first is not None else "not-needed"
    return base, key


async def probe_embedding(model: str, base_url: str, api_key: str) -> int:
    """Embed a probe string with an EPHEMERAL client (never cached, never
    persisted) and return the real vector length. Used by test-connection and
    by save's dimension guard. Raises on endpoint/auth/model error."""
    model = (model or "").strip()
    if not model:
        raise RuntimeError("model 必填")
    base, key = resolve_endpoint(base_url, api_key)
    client = AsyncOpenAI(api_key=key, base_url=base, timeout=30.0)
    resp: Any = await client.embeddings.create(model=model, input=[EMBED_PROBE_TEXT])
    vec = list(resp.data[0].embedding)
    return len(vec)


class EmbeddingClient:
    """Async embedding client backed by an OpenAI-compatible /v1/embeddings endpoint.

    Picks the first ENABLED provider from the LLM router and reuses its
    base_url + api_key. The actual OpenAI SDK client is cached so we don't pay
    connection-setup cost on every call.
    """

    def __init__(self) -> None:
        self._client: AsyncOpenAI | None = None
        self._provider_id: str | None = None
        # 熔断：embedding 端点连不上时，每次调用要等 SDK 重试完（~5s）才失败，
        # 而一次提问要 embed 两回（学到的解法 + 知识库）——配置坏了的网关每个问题
        # 白等 10 秒。失败后冷却 RST_EMBED_COOLDOWN_S 秒，期间直接抛，调用方照旧
        # 降级；冷却到期再试一次，好了就自动恢复。
        self._open_until: float = 0.0
        self._last_error: str = ""

    def _get_client(self) -> AsyncOpenAI:
        if self._client is not None:
            return self._client
        cfg = load_embedding_config()
        if cfg is not None and cfg["enabled"]:
            base_url, api_key = resolve_endpoint(cfg["base_url"], cfg["api_key"])
            self._client = AsyncOpenAI(api_key=api_key, base_url=base_url, timeout=60.0)
            self._provider_id = "yml:embedding"
            logger.info(
                "embedding_client_initialized",
                extra={"provider": "yml-config", "base_url": base_url},
            )
            return self._client
        override = _embed_endpoint()
        if override is not None:
            base_url, api_key = override
            self._client = AsyncOpenAI(api_key=api_key, base_url=base_url, timeout=60.0)
            self._provider_id = "env:RST_EMBED_BASE_URL"
            logger.info(
                "embedding_client_initialized",
                extra={"provider": "env-override", "base_url": base_url},
            )
            return self._client
        router = get_router()
        first = next((p for p in router.providers if p.enabled), None)
        if first is None:
            raise RuntimeError(
                "No enabled LLM provider configured — embedding client cannot derive "
                "base_url / api_key. Set RST_EMBED_BASE_URL, or configure "
                "llm_providers.yml / LLM_API_KEY."
            )
        self._client = AsyncOpenAI(
            api_key=first.api_key,
            base_url=first.base_url,
            timeout=first.timeout_s,
        )
        self._provider_id = first.id
        logger.info(
            "embedding_client_initialized",
            extra={"provider": first.id, "base_url": first.base_url},
        )
        return self._client

    def circuit_open(self) -> bool:
        return time.monotonic() < self._open_until

    async def embed_texts(self, texts: list[str]) -> list[list[float]]:
        """Embed a list of texts; returns a list of vectors in the same order."""
        if not texts:
            return []
        if self.circuit_open():
            raise EmbeddingUnavailable(self._last_error or "embedding endpoint cooling down")
        # Guard against empty / whitespace-only chunks — many providers 400 on those.
        cleaned = [t if (t and t.strip()) else " " for t in texts]
        client = self._get_client()
        model = _embed_model()
        batch_size = _embed_batch()
        # Split into batches — a single oversized request 400s on most providers
        # (DashScope caps at 25/batch, etc.). Stitch results back in input order.
        out: list[list[float]] = []
        try:
            for start in range(0, len(cleaned), batch_size):
                batch = cleaned[start : start + batch_size]
                resp: Any = await client.embeddings.create(model=model, input=batch)
                # OpenAI SDK returns objects in deterministic order; sort defensively
                # in case — index is relative to this batch's input.
                data = sorted(resp.data, key=lambda d: getattr(d, "index", 0))
                out.extend(list(d.embedding) for d in data)
        except Exception as e:  # noqa: BLE001 — 连接 / 4xx / 5xx 一律熔断
            cooldown = _embed_cooldown_s()
            self._open_until = time.monotonic() + cooldown
            self._last_error = str(e)[:200]
            logger.warning(
                "embedding_circuit_opened",
                extra={"provider": self._provider_id, "cooldown_s": cooldown, "error": self._last_error},
            )
            raise
        return out


class EmbeddingUnavailable(RuntimeError):
    """熔断期间的调用：端点刚失败过，这次不去碰。调用方按 embedding 失败降级。"""


def _embed_cooldown_s() -> float:
    try:
        v = float(os.environ.get("RST_EMBED_COOLDOWN_S", "60") or "60")
    except ValueError:
        return 60.0
    return max(0.0, v)


_client: EmbeddingClient | None = None


def get_embedding_client() -> EmbeddingClient:
    global _client
    if _client is None:
        _client = EmbeddingClient()
    return _client


def reset() -> None:
    """Clear the cached embedding client. Used by tests / config-reload paths."""
    global _client
    _client = None
