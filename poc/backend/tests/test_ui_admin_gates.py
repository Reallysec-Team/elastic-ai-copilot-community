"""界面上「要管理员」的动作，必须挡在管理员那一档。

这道闸挡的是一类具体的错：前端只有一个 `useCanWrite()`（含义是「不是 viewer」），
而后端有几十条路由挂着 `require_admin`。两者错位的结果是 analyst 看到一整排亮着、
按下去必然 403 的按钮 —— 正是这个产品早就否决过的「能点、点了报错」。

做法是从两边各读一次事实，然后对：
  1. 后端：AST 扫出哪些路由的处理函数里调了 `require_admin`（只看会改东西的方法）；
  2. 前端：`lib/api.ts` 里每个函数打向哪条路径；
  3. 哪些 .tsx 调了这些函数 —— 那些文件必须用管理员那一档的闸。

文件级而不是按钮级：跨文件精确追一个 onClick 要写半个类型系统，而这类错误从来
不是「挡错了那一个按钮」，是「整个文件用错了级别」。
"""
from __future__ import annotations

import ast
import io
import re
from pathlib import Path

import pytest

_BACKEND = Path(__file__).resolve().parent.parent
_FRONTEND = _BACKEND.parent / "frontend" / "src"
_API_TS = _FRONTEND / "lib" / "api.ts"

_MUTATING = {"POST", "PUT", "PATCH", "DELETE"}

# 调了管理员接口、但确实不该按管理员挡的地方，逐条写明理由。
_EXEMPT_FILES: dict[str, str] = {
    # 读取用的调用（展示当前配置 / 列表），不是按钮动作。按管理员挡的是动作，
    # 读不出来时页面自己会显示错误。
    "pages/AuditPage.tsx": "只读：拉审计事件",
    "pages/SettingsPage.tsx": "只读 + 保存浮条自己带闸（save-bar.tsx）",
    "pages/UsersPage.tsx": "整页就是管理员页，进不来就没有按钮",
    "pages/LicensePage.tsx": "激活页在 license 未激活时必须可用",
    "components/settings/EsSetupDialog.tsx": "首装弹窗自己带 gate=\"admin\"",
}


def _admin_paths() -> set[tuple[str, str]]:
    """(method, path) —— 处理函数里调了 require_admin 的那些（读写都收）。"""
    out: set[tuple[str, str]] = set()
    for py in _BACKEND.rglob("*.py"):
        if "tests" in py.parts:
            continue
        tree = ast.parse(io.open(py, encoding="utf-8").read())
        for node in ast.walk(tree):
            if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                continue
            calls = {
                c.func.id for c in ast.walk(node)
                if isinstance(c, ast.Call) and isinstance(c.func, ast.Name)
            }
            if "require_admin" not in calls:
                continue
            for dec in node.decorator_list:
                if not isinstance(dec, ast.Call):
                    continue
                fn = dec.func
                name = fn.attr if isinstance(fn, ast.Attribute) else getattr(fn, "id", "")
                if name == "llm_post":
                    name = "post"
                if name not in {"get", "post", "put", "patch", "delete"} or not dec.args:
                    continue
                a0 = dec.args[0]
                if isinstance(a0, ast.Constant) and isinstance(a0.value, str):
                    out.add((name.upper(), a0.value))
    return out


def _api_fn_paths() -> dict[str, str]:
    """lib/api.ts 里 `name: (...) => request(...'/api/...')` 的对应关系。"""
    src = io.open(_API_TS, encoding="utf-8").read()
    out: dict[str, str] = {}
    starts = [m for m in re.finditer(r"^\s{2}(\w+):\s*(?:\([^)]*\)\s*=>|async\b)", src, re.M)]
    for i, m in enumerate(starts):
        # 到下一个顶层条目为止，而不是固定往后看 N 个字符：`auditEvents` /
        # `reportsHistory` 这类的参数类型有三四十行，路径落在窗口外面 —— 于是
        # 两条 admin-only 的读接口从来没被这道闸扫到过，而且是静默的。
        end = starts[i + 1].start() if i + 1 < len(starts) else len(src)
        p = re.search(r"[`'\"](/api/[^`'\"$?]*)", src[m.end(): end])
        if p:
            # `?` 也要停：`/api/admin/enrichment/entries?${qs}` 里带问号的那一段
            # 跟后端路由永远对不上，于是那条接口同样是静默漏掉的。
            out[m.group(1)] = p.group(1)
    return out


def _is_admin_path(path: str, admin: set[tuple[str, str]]) -> bool:
    for _method, ap in admin:
        if path == ap:
            return True
        # 只有带路径参数的路由才按前缀比：`/api/users/{username}` ↔ `/api/users/`。
        # 对没有参数的路由也做前缀比会连坐子路径 —— `POST /api/settings` 会把
        # `/api/settings/es/test` 一起判成管理员接口，哪怕后者根本没挂 require_admin。
        if "{" not in ap:
            continue
        prefix = ap.split("{")[0]
        if prefix and path.startswith(prefix):
            return True
    return False


@pytest.mark.skipif(not _API_TS.exists(), reason="run from a full checkout")
def test_every_admin_only_action_is_gated_as_admin_in_the_ui():
    # 这一条只管"动作"。只读的 admin-only 接口是另一回事，见下面那条。
    admin = {r for r in _admin_paths() if r[0] in _MUTATING}
    assert admin, "一条 require_admin 路由都没扫到，说明扫描本身坏了"

    fn_path = _api_fn_paths()
    admin_fns = {fn for fn, path in fn_path.items() if _is_admin_path(path, admin)}
    assert admin_fns, "api.ts 里一个管理员接口都没匹配上，说明映射坏了"

    offenders: list[str] = []
    for tsx in sorted(_FRONTEND.rglob("*.tsx")):
        rel = tsx.relative_to(_FRONTEND).as_posix()
        if rel in _EXEMPT_FILES or rel == "components/gated-button.tsx":
            continue
        src = io.open(tsx, encoding="utf-8").read()
        used = sorted(fn for fn in admin_fns if re.search(rf"\bapi\.{fn}\b", src))
        if not used:
            continue
        gated = 'gate="admin"' in src or "useGate('admin')" in src
        if not gated:
            offenders.append(f"{rel} 调了 {', '.join(used)} 却没有管理员那一档的闸")

    assert not offenders, "这些界面文件会让非管理员点到必然 403 的动作：\n  " + "\n  ".join(offenders)


# 调了 admin-only 的读接口、但不需要自己解释的文件，逐条写明理由。
_READ_EXEMPT_FILES: dict[str, str] = {
    "components/enrich/AssetCsvCard.tsx": "只出现在 AssetIdentityPage 里，那一页整页已经挡了",
    "components/settings/online-update-card.tsx": "只出现在 SettingsPage 里，那一页整页已经挡了",
    "components/settings/EsSetupDialog.tsx": "首装弹窗，本来就是管理员在装",
}


@pytest.mark.skipif(not _API_TS.exists(), reason="run from a full checkout")
def test_every_admin_only_read_says_so_instead_of_looking_empty():
    """管理员才能读的 GET，界面上必须说「你看不到」，不能显示成空的或坏的。

    这是上一轮那道闸留下的缺口：它只管「动作」（会改东西的方法），于是挂着
    require_admin 的 GET 一条都没被看住。而这一类恰恰最会骗人 —— 常见的写法是
    `.catch(() => setItems([]))`，403 就这么变成了「暂无数据」，界面在说一句
    不真的话：数据是有的，只是这个账号看不到。

    判据是文件里问没问过「我是不是管理员」（`useIsAdmin`）。跟上面那条一样是
    文件级：跨文件精确追一次 fetch 要写半个类型系统，而这类错从来不是「漏了
    那一个请求」，是「整个文件没考虑过非管理员会打开它」。
    """
    reads = {r for r in _admin_paths() if r[0] == "GET"}
    assert reads, "一条 admin-only 的 GET 都没扫到，说明扫描本身坏了"

    fn_path = _api_fn_paths()
    read_fns = {fn for fn, path in fn_path.items() if _is_admin_path(path, reads)}
    assert read_fns, "api.ts 里一个 admin-only 的读接口都没匹配上，说明映射坏了"

    offenders: list[str] = []
    for tsx in sorted(_FRONTEND.rglob("*.tsx")):
        rel = tsx.relative_to(_FRONTEND).as_posix()
        if rel in _READ_EXEMPT_FILES or rel == "components/gated-button.tsx":
            continue
        src = io.open(tsx, encoding="utf-8").read()
        used = sorted(fn for fn in read_fns if re.search(rf"\bapi\.{fn}\b", src))
        if not used:
            continue
        if "useIsAdmin(" not in src:
            offenders.append(f"{rel} 读了 {', '.join(used)} 却没考虑过非管理员打开它")

    assert not offenders, (
        "这些界面文件会把「你没权限」显示成空的或坏的：\n  " + "\n  ".join(offenders)
    )


@pytest.mark.skipif(not _API_TS.exists(), reason="run from a full checkout")
def test_the_gate_component_keeps_the_control_reachable():
    """禁用的按钮不可聚焦，`title` 也不会被读屏器念 —— 权限说明必须走
    aria-disabled + aria-describedby 这条路，否则键盘和读屏用户拿不到原因。"""
    src = io.open(_FRONTEND / "components" / "gated-button.tsx", encoding="utf-8").read()
    assert 'aria-disabled="true"' in src
    assert "aria-describedby" in src
    assert "sr-only" in src
    # 一旦有人图省事换回 disabled，这条就红。
    assert re.search(r"disabled=\{true\}|\bdisabled\b(?!=\{)", src) is None or "disabled={disabled}" not in src
