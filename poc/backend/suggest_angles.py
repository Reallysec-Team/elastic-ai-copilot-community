"""「让 AI 再想几个角度」—— 把一句傻问题（「有人在攻击我们吗？」）翻成几条
具体的、一条 ES 查询能答的问法，给首页示例卡的选项面板追加。

只出问句，不出 DSL：真正生成查询仍走 /api/generate，这里只负责「还能从哪几个
角度看」。索引名传进来是为了让模型只提这台网关上真有数据的角度。

流式逐条出：模型一行一条（不要 JSON，JSON 得等整段闭合才能解析），这边攒到换行
就吐一条，面板上一条条冒出来，不用等 60 秒一起到。
"""
from __future__ import annotations

import logging
from collections.abc import AsyncIterator

from .llm_router import get_router

logger = logging.getLogger("rst.suggest_angles")

_MAX_ANGLES = 5

_SYSTEM = {
    "zh": (
        "你是一位安全运维分析师，帮不熟悉 Elasticsearch 的同事把一个笼统的问题拆成几个"
        "具体的查询角度。要求：每条必须是一条 Elasticsearch 查询就能回答的问句"
        "（明确的时间范围 + 要统计或列出的东西），口语、简短、不带查询术语；"
        "只提给定索引里真有数据的角度；不要重复给定的已有角度；最多 {n} 条。"
        "输出格式：一行一条，不编号、不加符号、不解释、不要 JSON。"
    ),
    "en": (
        "You are a security operations analyst helping a colleague who does not know "
        "Elasticsearch turn a vague question into a few concrete query angles. Each "
        "angle must be answerable by ONE Elasticsearch query (explicit time range + "
        "the thing to count or list), phrased plainly and briefly, no query jargon; "
        "only angles the given indices actually hold data for; do not repeat the "
        "angles already given; at most {n}. Output format: one per line, no numbering, "
        "no bullets, no explanation, no JSON."
    ),
}


def _user_prompt(question: str, indices: list[str], existing: list[str], lang: str) -> str:
    idx = ", ".join(indices[:40]) if indices else ("（未知）" if lang == "zh" else "(unknown)")
    have = "\n".join(f"- {e}" for e in existing) or ("（无）" if lang == "zh" else "(none)")
    if lang == "zh":
        return f"问题：{question}\n可用索引：{idx}\n已有角度：\n{have}"
    return f"Question: {question}\nAvailable indices: {idx}\nExisting angles:\n{have}"


async def _stream(system: str, user_prompt: str) -> AsyncIterator[str]:
    """模型的文本增量。单独一层，测试直接替掉。"""
    async for _provider, chunk in get_router().chat_completion_stream(
        messages=[
            {"role": "system", "content": system},
            {"role": "user", "content": user_prompt},
        ],
        temperature=0.7,
        # 5 句口语问句，不需要推理。实测 ark-code-latest 开思考首条 80–144s，
        # 关掉 1–2s（2026-09-14）。翻译成各家参数的事在 llm_reasoning.py。
        reasoning="none",
    ):
        try:
            delta = chunk.choices[0].delta.content
        except (AttributeError, IndexError):
            delta = None
        if delta:
            yield delta


def _clean(line: str) -> str:
    # 模型偶尔还是会编号或加圆点，剥掉。
    s = line.strip().lstrip("-•*·").strip()
    while s[:1].isdigit() or s[:1] in "（(":
        # "1. xxx" / "1、xxx" / "(1) xxx"
        head, sep, rest = s.partition(" ")
        if not sep:
            break
        if head.rstrip(".、)）:：").strip("（(").isdigit():
            s = rest.strip()
        else:
            break
    return s[:200]


async def suggest(
    question: str,
    indices: list[str],
    existing: list[str],
    lang: str = "zh",
) -> AsyncIterator[str]:
    """逐条产出新角度（去重、去掉已有的、最多 _MAX_ANGLES 条）。"""
    lang = "en" if lang == "en" else "zh"
    system = _SYSTEM[lang].format(n=_MAX_ANGLES)
    seen = {e.strip() for e in existing}
    count = 0
    buf = ""

    def take(line: str) -> str | None:
        nonlocal count
        text = _clean(line)
        if not text or text in seen:
            return None
        seen.add(text)
        count += 1
        return text

    async for delta in _stream(system, _user_prompt(question, indices, existing, lang)):
        buf += delta
        while "\n" in buf and count < _MAX_ANGLES:
            line, buf = buf.split("\n", 1)
            got = take(line)
            if got:
                yield got
        if count >= _MAX_ANGLES:
            return
    if buf.strip() and count < _MAX_ANGLES:
        got = take(buf)
        if got:
            yield got
