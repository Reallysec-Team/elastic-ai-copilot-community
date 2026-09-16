"""错误码两张表要对得上。

中文在后端（`api_errors.MESSAGES`），英文在前端（`src/locales/errors.ts`）。
分开是故意的 —— 中文只有一处真源。代价是没人盯着的话，加了码却忘了加英文，
英文界面就会悄悄退回中文，而且没有任何报错。这个文件就是那个盯着的人。
"""
from __future__ import annotations

import re
import sys
from pathlib import Path

_POC = Path(__file__).resolve().parent.parent.parent
if str(_POC) not in sys.path:
    sys.path.insert(0, str(_POC))

from backend.api_errors import MESSAGES, ApiError  # noqa: E402

_ERRORS_TS = _POC / "frontend" / "src" / "locales" / "errors.ts"
_PLACEHOLDER = re.compile(r"\{(\w+)\}")


def _en_table() -> dict[str, str]:
    """从 errors.ts 里抠出 errorEn 的键和模板。

    正则读 TS 而不是跑 node：这条断言要在 pytest 里就能红，不该依赖前端工具链。
    """
    src = _ERRORS_TS.read_text(encoding="utf-8")
    body = src.split("export const errorEn: Record<string, string> = {", 1)[1]
    body = body.split("\n}\n", 1)[0]
    out: dict[str, str] = {}
    for m in re.finditer(r"^  (\w+):\s*(.*?)(?=^  \w+:|\Z)", body, re.S | re.M):
        out[m.group(1)] = m.group(2)
    return out


def test_every_code_has_an_english_message():
    missing = sorted(set(MESSAGES) - set(_en_table()))
    assert not missing, f"errors.ts 缺这些码的英文文案：{missing}"


def test_no_stale_english_messages():
    """反向也要成立 —— 后端删了码，前端那条就是死文案。"""
    stale = sorted(set(_en_table()) - set(MESSAGES))
    assert not stale, f"errors.ts 里这些码后端已经没有了：{stale}"


def test_placeholders_match():
    """英文模板不能引用中文模板没有的参数 —— 那种洞在界面上是一个原样的 {x}。"""
    en = _en_table()
    for code, zh in MESSAGES.items():
        zh_keys = set(_PLACEHOLDER.findall(zh))
        en_keys = set(_PLACEHOLDER.findall(en[code]))
        assert en_keys <= zh_keys, f"{code}: 英文模板多了参数 {sorted(en_keys - zh_keys)}"


def test_unknown_code_is_loud():
    """打错码要当场炸，不能渲染出一句半截话。"""
    try:
        ApiError("no_such_code")
    except KeyError:
        return
    raise AssertionError("未知错误码应当抛 KeyError")


def test_params_survive_into_the_body():
    from backend.api_errors import error_body

    e = ApiError("user_not_found", 404, name="alice")
    assert error_body(e) == {
        "detail": "用户 alice 不存在。",
        "code": "user_not_found",
        "params": {"name": "alice"},
    }


def test_exception_params_are_stringified():
    """`reason=e` 是最常见的写法，异常对象不能就这么进 JSON。"""
    e = ApiError("import_failed", 502, reason=ValueError("boom"))
    assert e.params == {"reason": "boom"}
    assert str(e) == "导入失败：boom"
