"""Multi-provider LLM router with failover.

Loads provider list from `RST_LLM_CONFIG` YAML file (default
`<install_dir>/llm_providers.yml`). Falls back to single-provider env vars
(`LLM_API_KEY` / `LLM_BASE_URL` / `LLM_MODEL`) for v0.x compatibility.

Strategies:
  - failover: try providers in declared order, return first success (v1.0.0)
  - round-robin: future
  - tag-based: future

Each provider is an OpenAI-compatible HTTP endpoint. The OpenAI Python SDK is
the underlying client. Health stats (last_ok_at / consec_failures / etc.) are
exposed via /api/llm/providers for ops dashboards.
"""

from __future__ import annotations

import asyncio
import logging
import os
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import yaml
from openai import AsyncAzureOpenAI, AsyncOpenAI

from . import llm_reasoning

logger = logging.getLogger("rst.llm_router")

DEFAULT_CONFIG = Path(__file__).parent.parent / "llm_providers.yml"


@dataclass
class Provider:
    id: str
    base_url: str
    api_key: str
    model: str
    # Provider protocol dispatched in _get_client: "openai" (AsyncOpenAI, incl.
    # any OpenAI-compatible endpoint / gateway) or "azure" (AsyncAzureOpenAI).
    kind: str = "openai"
    # Azure only — API version, e.g. "2024-06-01". Ignored by other kinds.
    api_version: str = ""
    # Generous default — investigate / triage / report are long structured-
    # output calls that legitimately run 40–110s; 60s would intermittently
    # time them out.
    timeout_s: float = 180.0
    enabled: bool = True
    tags: list[str] = field(default_factory=list)
    # 推理强度覆盖：auto（按调用方意图）| off | low | high。见 llm_reasoning.py。
    reasoning: str = "auto"
    # runtime stats
    last_ok_at: float = 0.0
    last_fail_at: float = 0.0
    last_error: str = ""
    consec_failures: int = 0
    total_calls: int = 0
    total_failures: int = 0


class AllProvidersFailed(RuntimeError):
    """Raised when failover walked through every enabled provider and none worked."""


def _stream_usage_enabled() -> bool:
    """Ask the provider to emit a final usage chunk on streaming calls (token
    accounting). On by default — OpenAI-compatible endpoints incl. Volcengine
    Ark support it. Set RST_LLM_STREAM_USAGE=0 to disable for a provider that
    rejects the `stream_options` param."""
    return os.environ.get("RST_LLM_STREAM_USAGE", "1").strip().lower() in ("1", "true", "yes")


class LLMRouter:
    def __init__(self, providers: list[Provider], strategy: str = "failover") -> None:
        self._providers = providers
        self._strategy = strategy
        self._clients: dict[str, AsyncOpenAI] = {}

    @property
    def providers(self) -> list[Provider]:
        return list(self._providers)

    @property
    def strategy(self) -> str:
        return self._strategy

    def _get_client(self, p: Provider) -> Any:
        # Key the client cache on the full connection identity (kind + base_url +
        # api_key + api_version + timeout), NOT just p.id: if two providers ever
        # share an id but differ in endpoint/key/kind, keying on id alone would
        # silently route one through the other's client. The composite key makes
        # that misrouting impossible.
        ckey = f"{p.kind}\x00{p.base_url}\x00{p.api_key}\x00{p.api_version}\x00{p.timeout_s}"
        if ckey not in self._clients:
            self._clients[ckey] = self._build_client(p)
        return self._clients[ckey]

    def _build_client(self, p: Provider) -> Any:
        """Client factory — dispatch on provider kind. New protocols plug in here
        without touching chat_completion / streaming (both call chat.completions,
        which every kind's client exposes)."""
        if p.kind == "openai":
            return AsyncOpenAI(
                api_key=p.api_key,
                base_url=p.base_url,
                timeout=p.timeout_s,
                # SDK 默认 max_retries=2：一次 timeout_s 超时会再原样重试两次，
                # 分诊 / 调查撞超时前要等 3×timeout_s。失败换 provider 由路由层
                # 做（failover），SDK 层不重试。
                max_retries=0,
            )
        if p.kind == "azure":
            # Azure routes by deployment, not model name — but the deployment is
            # passed as `model` on each chat.completions.create call (kwargs2 sets
            # model=p.model), so p.model must be the *deployment name*. base_url is
            # the resource endpoint (https://<res>.openai.azure.com). api_version
            # is mandatory: without it Azure 404s every request.
            if not p.api_version:
                raise ValueError(
                    f"azure provider '{p.id}' requires api_version "
                    "(e.g. '2024-06-01'); none set."
                )
            return AsyncAzureOpenAI(
                api_key=p.api_key,
                azure_endpoint=p.base_url,
                api_version=p.api_version,
                timeout=p.timeout_s,
                max_retries=0,
            )
        raise ValueError(
            f"unsupported provider kind '{p.kind}' (id={p.id}). "
            "Supported: openai, azure."
        )

    def schedule_close(self) -> None:
        """Best-effort async close of the cached HTTP clients after a router
        swap — closes the httpx connection pools instead of leaking them until
        GC. No-op (GC reclaims) when called outside a running event loop."""
        clients = list(self._clients.values())
        self._clients.clear()
        if not clients:
            return

        async def _close() -> None:
            for c in clients:
                try:
                    await c.close()
                except Exception:  # noqa: BLE001
                    pass

        try:
            asyncio.get_running_loop().create_task(_close())
        except RuntimeError:
            pass  # no running loop (sync / test context) — GC reclaims them

    @staticmethod
    def _with_reasoning(
        p: Provider, kwargs: dict[str, Any], hint: str | None,
    ) -> tuple[dict[str, Any], str | None]:
        """把调用方的推理意图翻成这家供应商的参数。返回 (kwargs, 实际档位或 None)。"""
        level = llm_reasoning.resolve(p.reasoning, hint)
        if level is None:
            return dict(kwargs), None
        family = llm_reasoning.detect_family(p.base_url, p.model, p.kind)
        extra = llm_reasoning.params_for(family, p.model, level)
        if not extra:
            return dict(kwargs), None
        out = llm_reasoning.merge_params(kwargs, extra)
        # 思考档单独一层超时：high 在 ark 上 60–130s 一次，provider 的 timeout_s
        # 是按普通调用（NL→AQL 十几秒）定的，不能让一个值管两种活。
        if level == "high" and "timeout" not in out:
            out["timeout"] = max(p.timeout_s, _thinking_timeout_s())
        return out, level

    @staticmethod
    def _is_bad_request(e: Exception) -> bool:
        return getattr(e, "status_code", None) == 400

    async def chat_completion(
        self, *, reasoning: str | None = None, **kwargs: Any,
    ) -> tuple[Any, Provider]:
        """Try enabled providers in order. Return (response, provider_used).

        `reasoning` 是调用方的推理意图（none / low / high / 不传），按供应商翻译；
        带了推理参数被 400 的供应商，去掉参数原地再试一次——参数猜错不该让整次
        调用失败。"""
        if not self._providers:
            raise RuntimeError("No LLM providers configured (set llm_providers.yml or LLM_API_KEY/LLM_MODEL).")

        last_error: Exception | None = None
        tried_any = False

        for p in self._providers:
            if not p.enabled:
                continue
            tried_any = True
            client = self._get_client(p)
            kwargs2, level = self._with_reasoning(p, {**kwargs, "model": p.model}, reasoning)
            start = time.perf_counter()
            try:
                try:
                    resp = await client.chat.completions.create(**kwargs2)
                except Exception as create_err:  # noqa: BLE001
                    if level is None or not self._is_bad_request(create_err):
                        raise
                    logger.warning(
                        "reasoning_params_rejected — retrying without them",
                        extra={"provider": p.id, "level": level, "error": str(create_err)[:200]},
                    )
                    resp = await client.chat.completions.create(**{**kwargs, "model": p.model})
            except Exception as e:  # noqa: BLE001 — failover catches all
                duration_ms = int((time.perf_counter() - start) * 1000)
                p.last_fail_at = time.time()
                p.last_error = str(e)[:300]
                p.consec_failures += 1
                p.total_calls += 1
                p.total_failures += 1
                last_error = e
                logger.warning(
                    "llm_provider_failed",
                    extra={
                        "provider": p.id,
                        "model": p.model,
                        "duration_ms": duration_ms,
                        "error": str(e)[:300],
                        "consec_failures": p.consec_failures,
                    },
                )
                continue

            duration_ms = int((time.perf_counter() - start) * 1000)
            p.last_ok_at = time.time()
            p.consec_failures = 0
            p.total_calls += 1
            logger.info(
                "llm_provider_ok",
                extra={
                    "provider": p.id,
                    "model": p.model,
                    "duration_ms": duration_ms,
                    "tags": p.tags,
                    "reasoning": level,
                },
            )
            return resp, p

        if not tried_any:
            raise RuntimeError(
                "No enabled LLM providers. Check llm_providers.yml or env vars."
            )
        raise AllProvidersFailed(
            f"All {sum(1 for p in self._providers if p.enabled)} enabled providers failed. "
            f"Last error: {last_error}"
        ) from last_error

    async def chat_completion_stream(self, *, reasoning: str | None = None, **kwargs: Any):
        """Streaming variant. Yields tuples (provider, chunk). `reasoning` 同上。

        Failover semantics: try each enabled provider in order. If we
        haven't received any chunk yet and the call raises, advance to
        the next provider. Once we've yielded our first chunk we COMMIT
        — a mid-stream failure surfaces as an exception (no resume).
        """
        if not self._providers:
            raise RuntimeError("No LLM providers configured (set llm_providers.yml or LLM_API_KEY/LLM_MODEL).")

        last_error: Exception | None = None
        tried_any = False

        for p in self._providers:
            if not p.enabled:
                continue
            tried_any = True
            client = self._get_client(p)
            base = {**kwargs, "model": p.model, "stream": True}
            kwargs2, level = self._with_reasoning(p, base, reasoning)
            want_usage = _stream_usage_enabled()
            if want_usage:
                kwargs2["stream_options"] = {"include_usage": True}
            start = time.perf_counter()
            yielded_any = False
            try:
                try:
                    stream = await client.chat.completions.create(**kwargs2)
                except Exception as create_err:  # noqa: BLE001
                    # 两个可选参数（stream_options / 推理参数）都可能被某家拒。
                    # 同一供应商去掉可选参数再试一次——只损失 token 计数 / 推理
                    # 档位，不损失这次生成；仍失败才 failover。
                    if not want_usage and level is None:
                        raise
                    logger.warning(
                        "optional_params_rejected — retrying without stream_options / reasoning",
                        extra={"provider": p.id, "level": level, "error": str(create_err)[:200]},
                    )
                    level = None
                    stream = await client.chat.completions.create(**base)
                async for chunk in stream:
                    yielded_any = True
                    yield p, chunk
            except Exception as e:  # noqa: BLE001
                duration_ms = int((time.perf_counter() - start) * 1000)
                p.last_fail_at = time.time()
                p.last_error = str(e)[:300]
                p.consec_failures += 1
                p.total_calls += 1
                p.total_failures += 1
                last_error = e
                logger.warning(
                    "llm_provider_stream_failed",
                    extra={
                        "provider": p.id,
                        "model": p.model,
                        "duration_ms": duration_ms,
                        "yielded_any": yielded_any,
                        "error": str(e)[:300],
                    },
                )
                if yielded_any:
                    # Mid-stream failure — don't fail over, surface to caller.
                    raise
                continue

            duration_ms = int((time.perf_counter() - start) * 1000)
            p.last_ok_at = time.time()
            p.consec_failures = 0
            p.total_calls += 1
            logger.info(
                "llm_provider_stream_ok",
                extra={
                    "provider": p.id,
                    "model": p.model,
                    "duration_ms": duration_ms,
                    "tags": p.tags,
                    "reasoning": level,
                },
            )
            return  # success — exit the failover loop

        if not tried_any:
            raise RuntimeError(
                "No enabled LLM providers. Check llm_providers.yml or env vars."
            )
        raise AllProvidersFailed(
            f"All {sum(1 for p in self._providers if p.enabled)} enabled providers failed. "
            f"Last error: {last_error}"
        ) from last_error

    def status(self) -> dict[str, Any]:
        return {
            "strategy": self._strategy,
            "providers": [
                {
                    "id": p.id,
                    "model": p.model,
                    "kind": p.kind,
                    "api_version": p.api_version,
                    "base_url": p.base_url,
                    "enabled": p.enabled,
                    "tags": p.tags,
                    # Masked key — last 4 chars only, for UI display.
                    # The real key NEVER leaves the gateway.
                    "api_key_last4": p.api_key[-4:] if p.api_key else "",
                    "timeout_s": p.timeout_s,
                    "reasoning": p.reasoning,
                    "consec_failures": p.consec_failures,
                    "total_calls": p.total_calls,
                    "total_failures": p.total_failures,
                    "last_ok_at": p.last_ok_at or None,
                    "last_fail_at": p.last_fail_at or None,
                    "last_error": p.last_error[:200] if p.last_error else "",
                }
                for p in self._providers
            ],
        }


def config_path() -> Path:
    raw = os.environ.get("RST_LLM_CONFIG", "").strip()
    return Path(raw) if raw else DEFAULT_CONFIG


def _from_yaml(path: Path) -> LLMRouter:
    raw = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    if not isinstance(raw, dict) or "providers" not in raw:
        # 文件在但没有 providers 段：这是「设置 → 向量化」保存后的常态 ——
        # save_embedding 只写 embedding: 段。原来这里把它当成「配了 0 个供应商」，
        # 于是配好 LLM_API_KEY/LLM_MODEL 的部署一重启就 "No LLM providers
        # configured"（2026-09-17 演示机复现）。没这段就当文件不存在，回落到 env；
        # 显式 `providers: []` 仍然是「故意不配」。
        logger.info("llm_providers_file_without_providers — falling back to env",
                    extra={"path": str(path)})
        return _from_env()
    raw_providers = raw.get("providers") or []
    routing = raw.get("routing") or {}
    strategy = (routing.get("strategy") or "failover").strip().lower()
    if strategy != "failover":
        logger.warning(
            f"strategy '{strategy}' not yet supported, defaulting to failover"
        )
        strategy = "failover"

    providers: list[Provider] = []
    seen_ids: set[str] = set()
    for entry in raw_providers:
        pid = entry.get("id")
        if not pid:
            logger.warning("provider entry missing 'id', skipping")
            continue
        if pid in seen_ids:
            # Duplicate id — the status/health UI keys on id and a later edit
            # would be ambiguous. Keep the first, skip the rest.
            logger.warning(f"duplicate provider id '{pid}', skipping later entry")
            continue
        seen_ids.add(pid)

        api_key_env = (entry.get("api_key_env") or "").strip()
        api_key = (entry.get("api_key") or "").strip()
        if api_key_env and not api_key:
            api_key = os.environ.get(api_key_env, "").strip()
        if not api_key:
            logger.warning(
                f"provider '{pid}' has no api_key (env '{api_key_env}' empty / missing). "
                "Skipping."
            )
            continue

        base_url = (entry.get("base_url") or "").strip()
        if not base_url:
            logger.warning(f"provider '{pid}' has no base_url, skipping")
            continue
        model = (entry.get("model") or "").strip()
        if not model:
            logger.warning(f"provider '{pid}' has no model, skipping")
            continue

        providers.append(Provider(
            id=pid,
            base_url=base_url,
            api_key=api_key,
            model=model,
            kind=(entry.get("kind") or "openai").strip().lower(),
            api_version=(entry.get("api_version") or "").strip(),
            timeout_s=float(entry.get("timeout_s", 180.0)),
            enabled=bool(entry.get("enabled", True)),
            tags=list(entry.get("tags") or []),
            reasoning=llm_reasoning.normalize_mode(entry.get("reasoning")),
        ))

    logger.info(
        "llm_providers_loaded",
        extra={
            "source": "yaml",
            "path": str(path),
            "count": len(providers),
            "enabled": sum(1 for p in providers if p.enabled),
        },
    )
    return LLMRouter(providers, strategy=strategy)


# Legacy env-mode fallback base_url (Volcengine Ark). Only used when running the
# backward-compat single-provider path WITHOUT an explicit LLM_BASE_URL. New
# deployments should set LLM_BASE_URL or use llm_providers.yml to target their
# own provider instead of being silently bound to this vendor.
_DEFAULT_LLM_BASE_URL = "https://ark.cn-beijing.volces.com/api/v3"


def _from_env() -> LLMRouter:
    """Backward-compat: build a single-provider router from LLM_* env vars."""
    api_key = os.environ.get("LLM_API_KEY", "").strip()
    model = os.environ.get("LLM_MODEL", "").strip()
    base_url_env = os.environ.get("LLM_BASE_URL", "").strip()
    base_url = base_url_env or _DEFAULT_LLM_BASE_URL

    if not api_key or not model:
        logger.warning(
            "llm_providers_unconfigured — No llm_providers.yml AND no LLM_API_KEY/LLM_MODEL env. "
            "Gateway has no LLM — /api/generate etc. will 500."
        )
        return LLMRouter([])

    if not base_url_env:
        logger.warning(
            "llm_base_url_defaulted — LLM_BASE_URL not set; falling back to Volcengine Ark (%s). "
            "Set LLM_BASE_URL or use llm_providers.yml to target your own LLM provider.",
            _DEFAULT_LLM_BASE_URL,
        )

    timeout_s = float(os.environ.get("LLM_TIMEOUT_S", "180") or "180")
    p = Provider(
        id="default",
        base_url=base_url,
        api_key=api_key,
        model=model,
        timeout_s=timeout_s,
        tags=["env-default"],
        reasoning=llm_reasoning.normalize_mode(os.environ.get("LLM_REASONING")),
    )
    logger.info(
        "llm_providers_loaded",
        extra={"source": "env", "count": 1, "enabled": 1},
    )
    return LLMRouter([p])


def load_router() -> LLMRouter:
    cfg = config_path()
    if cfg.exists():
        try:
            return _from_yaml(cfg)
        except Exception as e:  # noqa: BLE001
            logger.error(
                f"failed to load llm_providers.yml at {cfg}: {e}. "
                "Falling back to env vars."
            )
    return _from_env()


_router: LLMRouter | None = None


def _thinking_timeout_s() -> float:
    """reasoning=high 调用的超时下限（秒）。RST_LLM_THINKING_TIMEOUT_S，默认 600。"""
    try:
        return float(os.environ.get("RST_LLM_THINKING_TIMEOUT_S", "600") or "600")
    except ValueError:
        return 600.0


def get_router() -> LLMRouter:
    global _router
    if _router is None:
        _router = load_router()
    return _router


def reset() -> None:
    """Force reload (e.g., after editing llm_providers.yml). Used by /api/llm/reload
    and save_providers."""
    global _router
    old = _router
    _router = None
    if old is not None:
        old.schedule_close()
    # A different provider/model can answer the same question differently, so the
    # memoised NL→DSL results are no longer trustworthy after a provider change.
    try:
        from . import response_cache
        response_cache.clear()
    except Exception:  # noqa: BLE001
        pass


def save_providers(providers_payload: list[dict[str, Any]]) -> dict[str, Any]:
    """Persist a provider list to llm_providers.yml and reload the router.

    Each entry in `providers_payload` may set `api_key` directly. If `api_key`
    is empty AND a provider with the same `id` already exists in the current
    router, the existing key is preserved — this is how "edit but don't
    re-enter the key" works on the UI side.

    Returns the new `status()` after reload.
    """
    cfg = config_path()
    cfg.parent.mkdir(parents=True, exist_ok=True)

    # Build id → existing key map for "leave blank to keep" UX.
    existing_keys: dict[str, str] = {}
    try:
        for p in get_router()._providers:
            if p.api_key:
                existing_keys[p.id] = p.api_key
    except Exception:  # noqa: BLE001
        # Brand-new install with no router yet — fine.
        pass

    cleaned: list[dict[str, Any]] = []
    seen_ids: set[str] = set()
    for entry in providers_payload:
        pid = (entry.get("id") or "").strip()
        if not pid:
            raise ValueError("provider missing 'id'")
        if pid in seen_ids:
            raise ValueError(f"duplicate provider id '{pid}' — ids must be unique")
        seen_ids.add(pid)
        base_url = (entry.get("base_url") or "").strip()
        if not base_url:
            raise ValueError(f"provider '{pid}' missing 'base_url'")
        # URL validation — previously a malformed base_url was silently
        # accepted and only blew up later inside httpx on the first /generate.
        from urllib.parse import urlparse
        _p = urlparse(base_url)
        if _p.scheme not in ("http", "https") or not _p.hostname:
            raise ValueError(
                f"provider '{pid}' base_url 不合法：{base_url!r}。"
                f"必须是 http:// 或 https:// 开头的完整 URL"
            )
        model = (entry.get("model") or "").strip()
        if not model:
            raise ValueError(f"provider '{pid}' missing 'model'")
        api_key = (entry.get("api_key") or "").strip()
        if not api_key:
            # Try to inherit from current router state.
            api_key = existing_keys.get(pid, "")
        if not api_key:
            raise ValueError(
                f"provider '{pid}' has no api_key (none provided and none on file)"
            )
        kind = (entry.get("kind") or "openai").strip().lower()
        api_version = (entry.get("api_version") or "").strip()
        # Azure without api_version 404s every call — reject at save time, not at
        # first /generate, so the misconfig surfaces on the settings screen.
        if kind == "azure" and not api_version:
            raise ValueError(
                f"provider '{pid}' kind=azure requires 'api_version' (e.g. '2024-06-01')"
            )
        cleaned.append({
            "id": pid,
            "enabled": bool(entry.get("enabled", True)),
            "kind": kind,
            "base_url": base_url,
            "api_key": api_key,
            "model": model,
            # api_version is Azure-only but harmless to persist for other kinds
            # (loader ignores it). Omit when empty to keep openai entries clean.
            **({"api_version": api_version} if api_version else {}),
            # `or` (not a default arg) so an explicit `timeout_s: null` in the
            # payload falls back to 180 instead of float(None) → TypeError → 500.
            "timeout_s": float(entry.get("timeout_s") or 180.0),
            "tags": list(entry.get("tags") or []),
            "reasoning": llm_reasoning.normalize_mode(entry.get("reasoning")),
        })

    # Preserve any existing top-level `embedding:` section — the embedding GUI
    # config lives in the same file and must survive a providers save.
    existing_embedding = None
    if cfg.exists():
        try:
            prev = yaml.safe_load(cfg.read_text(encoding="utf-8")) or {}
            existing_embedding = prev.get("embedding")
        except Exception:  # noqa: BLE001
            existing_embedding = None

    payload: dict[str, Any] = {"providers": cleaned, "routing": {"strategy": "failover"}}
    if isinstance(existing_embedding, dict):
        payload["embedding"] = existing_embedding
    cfg.write_text(yaml.safe_dump(payload, sort_keys=False, allow_unicode=True), encoding="utf-8")
    logger.info(
        "llm_providers_saved",
        extra={"path": str(cfg), "count": len(cleaned)},
    )
    reset()
    return get_router().status()
