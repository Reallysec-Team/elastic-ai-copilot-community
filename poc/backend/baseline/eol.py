"""OS 版本 EOL 自动判定（HB-SYS-001）。

判定确定性、离线友好：
  - 纯函数吃注入的 today: date，内部不读 now → 可复现可测。
  - 只查本地 eol-catalog（eol_store.lookup），绝不实时调外网 endoflife API。

engine 对 operator==eol 单开分支调 judge_eol，operators 纯函数保持纯净。

verdict 矩阵（见 test_baseline_eol.py）:
  os_version 无结果行            → error
  发行版名映射不到 slug          → manual_review
  slug 已知但 catalog 无该 cycle → error（缓存缺项，需同步）
  catalog eol 日期已过 today      → fail
  catalog eol 日期未过 / 当天      → pass
  catalog eol == "false"          → pass
  catalog eol == "true"           → fail
  catalog eol 不可解析            → error
"""
from __future__ import annotations

from datetime import date
from typing import Any, Awaitable, Callable

from . import eol_store
from .schema import VERDICT_ERROR, VERDICT_FAIL, VERDICT_MANUAL, VERDICT_PASS

# 发行版名（osquery os_version.name）→ endoflife slug。子串匹配，按序首个命中。
# 顺序敏感：更专有的名字排前（almalinux/rocky 不含 centos，无冲突；red hat → rhel）。
_SLUG_TABLE: tuple[tuple[str, str], ...] = (
    ("almalinux", "almalinux"),
    ("rocky", "rocky"),
    ("centos", "centos"),
    ("red hat", "rhel"),
    ("rhel", "rhel"),
    ("ubuntu", "ubuntu"),
    ("debian", "debian"),
    ("amazon", "amazon-linux"),
    ("oracle", "oracle-linux"),
    ("suse linux enterprise", "sles"),
    ("sles", "sles"),
    ("opensuse", "opensuse-leap"),
    ("fedora", "fedora"),
)

# cycle 取「主.次」而非仅主版本的产品（版本粒度到点后一位）。
_MINOR_CYCLE_SLUGS = frozenset({"ubuntu"})

LookupFn = Callable[[str, str], Awaitable[dict[str, Any] | None]]


def extract_os(rows: list[dict[str, Any]]) -> tuple[str, str] | None:
    """从 os_version 结果行取 (name, version)。首行即可（每主机一条 os_version）。"""
    if not rows:
        return None
    row = rows[0] or {}
    name = row.get("name")
    version = row.get("version")
    if not name:
        return None
    return str(name), str(version or "")


def _match_slug(text: str) -> str | None:
    low = text.strip().lower()
    if not low:
        return None
    return next((slug for key, slug in _SLUG_TABLE if key in low), None)


def to_slug(name: str, platform: str = "") -> str | None:
    """发行版名 → endoflife slug；名字匹配不到时回退 platform；仍无 → None。"""
    return _match_slug(name or "") or _match_slug(platform or "")


def to_cycle(slug: str, version: str) -> str | None:
    """版本号 → endoflife cycle。ubuntu 取 主.次，其余取主版本。无法解析 → None。"""
    token = (version or "").strip().split()[0] if (version or "").strip() else ""
    parts = token.split(".") if token else []
    nums = [p for p in parts if p.isdigit()]
    if not nums:
        return None
    if slug in _MINOR_CYCLE_SLUGS and len(nums) >= 2:
        return f"{nums[0]}.{nums[1]}"
    return nums[0]


def _parse_date(s: str) -> date | None:
    try:
        return date.fromisoformat(s)
    except (TypeError, ValueError):
        return None


def compare_eol(eol_raw: str | None, today: date) -> str:
    """EOL 原始值（日期串 / "true" / "false"）+ today → verdict。

    日期语义：EOL 当天仍算受支持最后一日 → pass；次日起 fail。
    """
    if eol_raw is None:
        return VERDICT_ERROR
    low = eol_raw.strip().lower()
    if low == "false":
        return VERDICT_PASS      # 尚未 EOL
    if low == "true":
        return VERDICT_FAIL      # 已 EOL（无具体日期）
    d = _parse_date(eol_raw.strip())
    if d is None:
        return VERDICT_ERROR
    return VERDICT_FAIL if today > d else VERDICT_PASS


def decide(name: str, version: str, slug: str, cycle: str,
           entry: dict[str, Any] | None, today: date) -> tuple[str, str]:
    """slug/cycle 已定后，结合 catalog entry 出 (verdict, actual)。纯函数。"""
    if entry is None:
        return VERDICT_ERROR, f"eol-catalog 缺 {slug}:{cycle}（需运行 eol_sync 同步）"
    eol_raw = entry.get("eol_raw")
    verdict = compare_eol(eol_raw, today)
    actual = f"{name} {version} → {slug}:{cycle} EOL={eol_raw or '未知'}"
    return verdict, actual


async def judge_eol(rows: list[dict[str, Any]], today: date,
                    lookup: LookupFn | None = None) -> tuple[str, str]:
    """EOL 判定编排：取 OS → slug/cycle → 查本地 catalog → 判定。

    lookup 可注入（测试 / 换数据源）；缺省用 eol_store.lookup（只读本地 eol-catalog）。
    """
    lookup = lookup or eol_store.lookup

    os_info = extract_os(rows)
    if os_info is None:
        return VERDICT_ERROR, "os_version 无结果（拿不到 OS 名/版本，无法判定 EOL）"
    name, version = os_info

    slug = to_slug(name, str((rows[0] or {}).get("platform") or ""))
    if slug is None:
        return VERDICT_MANUAL, f"未知发行版「{name}」，无 EOL 数据源，转人工"

    cycle = to_cycle(slug, version)
    if cycle is None:
        return VERDICT_ERROR, f"版本「{version}」无法解析出 cycle（{slug}）"

    entry = await lookup(slug, cycle)
    return decide(name, version, slug, cycle, entry, today)
