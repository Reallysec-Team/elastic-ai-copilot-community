"""推理强度（「思考模式」）——一个意图，按供应商翻译成各家的参数。

为什么要有这一层：2025 年后的主流模型（豆包 / o-系 / GPT-5 / Claude / Qwen3 /
DeepSeek-R1 / Gemini 2.5）默认都先推理再作答。对告警调查这种活值得；对「把一句
话翻成 5 个问句」「起个会话标题」这种活，等 80 秒思考只换来 3 秒的输出。
实测 2026-09-14（ark-code-latest）：角度建议开思考首条 80–144s，关掉 1–2s；
NL→DSL 开思考首字 30s，有的问题 300s 都不出字。

调用方只说三档意图，不碰供应商细节：
    none  这活不需要推理，能关就关
    low   要一点，但别多想（NL→DSL 这种有明确输出格式的）
    high  真正需要推理的（分诊 / 调查 / 检测规则）
不传 = 不动，模型按自己的默认来。

供应商侧另有一个覆盖开关（llm_providers.yml 里每个 provider 的 `reasoning`）：
    auto  按调用方意图（默认）
    off / low / high  不管调用方说什么，一律这一档
给的是「我接的这个私有模型就是慢 / 就是要最准」的客户，不用找我们改代码。

翻译表只对认识的家族发参数；认不出来就什么都不发——发错参数被 400 比慢更糟。
路由层还有一道兜底：带了参数被 400，去掉参数再试一次。
"""
from __future__ import annotations

import re
from typing import Any, Literal

Level = Literal["none", "low", "high"]
LEVELS: tuple[str, ...] = ("none", "low", "high")
# provider 级覆盖的合法值。
PROVIDER_MODES: tuple[str, ...] = ("auto", "off", "low", "high")

# 只有这些 OpenAI 模型认 reasoning_effort；gpt-4o / gpt-4.1 收到会 400。
_OPENAI_REASONING_MODEL = re.compile(r"^(o[1-9]|gpt-5)")


def normalize_mode(value: Any) -> str:
    v = str(value or "auto").strip().lower()
    return v if v in PROVIDER_MODES else "auto"


def resolve(provider_mode: str, hint: str | None) -> str | None:
    """provider 覆盖 > 调用方意图 > 不动。返回 none/low/high 或 None（不发参数）。"""
    mode = normalize_mode(provider_mode)
    if mode == "off":
        return "none"
    if mode in ("low", "high"):
        return mode
    if hint in LEVELS:
        return hint
    return None


def from_request(value: str | None, default: str | None) -> str | None:
    """请求里的用户开关（"on" / "off" / None）→ 调用方意图。不传 = 这一步的默认档。"""
    if value == "on":
        return "high"
    if value == "off":
        return "none"
    return default


def detect_family(base_url: str, model: str, kind: str = "openai") -> str:
    """按 base_url / 模型名猜供应商家族。猜不出来 → unknown（不发任何参数）。"""
    u = (base_url or "").lower()
    m = (model or "").lower()
    if kind == "azure":
        return "openai"
    # 方舟（volces）上挂着第三方模型：kimi / glm / minimax 收到豆包的思考参数直接
    # 400 InvalidParameter（2026-09-18 实测），所以家族按模型名定，base_url 只在
    # 模型名认不出时兜底。
    if m.startswith(("doubao", "ark-", "seed-")):
        return "ark"
    if m.startswith(("kimi", "glm", "minimax")):
        return "unknown"
    if "deepseek" in u or m.startswith("deepseek"):
        return "deepseek"
    if "volces.com" in u or "volcengine" in u:
        return "ark"
    if "dashscope" in u or "aliyuncs" in u or m.startswith(("qwen", "qwq")):
        return "dashscope"
    if "anthropic" in u or m.startswith("claude"):
        return "anthropic"
    if "generativelanguage.googleapis" in u or m.startswith("gemini"):
        return "gemini"
    if "openrouter" in u:
        return "openrouter"
    if "api.openai.com" in u or _OPENAI_REASONING_MODEL.match(m):
        return "openai"
    return "unknown"


def params_for(family: str, model: str, level: str) -> dict[str, Any]:
    """把一档意图翻成 chat.completions.create 的额外 kwargs。空 dict = 这家表达不了，
    按模型默认。"""
    m = (model or "").lower()
    if family == "ark":
        # 方舟认 reasoning_effort（2026-09-18 实测同一研判提示，ark-code-latest：
        # minimal 5.3s / low 8.4s / medium 9.6s / 不传 52s / thinking enabled 70s；
        # `thinking.type=auto` 400）。low 仍有少量推理增量，够 JSON 格式任务用。
        return {"reasoning_effort": {"none": "minimal", "low": "low", "high": "high"}[level]}
    if family == "openai":
        if not _OPENAI_REASONING_MODEL.match(m):
            return {}
        return {"reasoning_effort": {"none": "minimal", "low": "low", "high": "high"}[level]}
    if family == "dashscope":
        # Qwen3 系列认 enable_thinking；老模型忽略 extra_body 里不认识的键。
        return {"extra_body": {"enable_thinking": level != "none"}}
    if family == "anthropic":
        if level == "none":
            return {"extra_body": {"thinking": {"type": "disabled"}}}
        budget = 1024 if level == "low" else 8192
        return {"extra_body": {"thinking": {"type": "enabled", "budget_tokens": budget}}}
    if family == "gemini":
        # OpenAI 兼容口只认 low / medium / high；关不掉，none 退成 low。
        return {"reasoning_effort": "low" if level in ("none", "low") else "high"}
    if family == "openrouter":
        if level == "none":
            return {"extra_body": {"reasoning": {"enabled": False}}}
        return {"extra_body": {"reasoning": {"effort": level}}}
    # deepseek：思考与否由模型名决定（deepseek-chat / deepseek-reasoner），没有参数。
    return {}


def merge_params(kwargs: dict[str, Any], extra: dict[str, Any]) -> dict[str, Any]:
    """把翻译出来的参数合进调用 kwargs；extra_body 是 dict 要合并，不能整个覆盖
    （调用方自己可能也带了 extra_body）。"""
    out = dict(kwargs)
    for k, v in extra.items():
        if k == "extra_body" and isinstance(out.get("extra_body"), dict):
            out["extra_body"] = {**out["extra_body"], **v}
        else:
            out[k] = v
    return out
