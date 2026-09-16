"""镜像装的是锁文件，所以锁必须跟得上 requirements.txt。

漏了一条的现象是「镜像少装一个包」—— 直到运行时某条路径 ImportError 才发现，
而且只在交付镜像上复现（开发机是按 requirements.txt 装的）。
"""
from __future__ import annotations

import re
from pathlib import Path

_POC = Path(__file__).resolve().parent.parent.parent
REQ = _POC / "requirements.txt"
LOCK = _POC / "requirements.lock.txt"


def _norm(name: str) -> str:
    return name.strip().lower().replace("_", "-")


def _direct() -> list[str]:
    out = []
    for line in REQ.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        out.append(_norm(re.split(r"[\[><=!;]", line, maxsplit=1)[0]))
    return out


def _locked() -> dict[str, str]:
    out = {}
    for line in LOCK.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "==" not in line:
            continue
        name, version = line.split("==", 1)
        out[_norm(name)] = version.strip()
    return out


def test_every_direct_dependency_is_locked():
    missing = [d for d in _direct() if d not in _locked()]
    assert not missing, (
        f"这几条在 requirements.txt 里但不在锁里，镜像不会装它们: {missing}。"
        " 重生成：docker exec <gateway> pip freeze | sort > poc/requirements.lock.txt"
    )


def test_lock_pins_exact_versions():
    """锁里只能是 ==，不能有范围或 VCS/本地路径。"""
    bad = [
        line.strip()
        for line in LOCK.read_text(encoding="utf-8").splitlines()
        if line.strip() and not line.startswith("#") and (" @ " in line or "==" not in line)
    ]
    assert not bad, f"锁里有没钉死的条目: {bad}"


def test_dockerfile_installs_the_lock():
    df = (_POC.parent / "Dockerfile").read_text(encoding="utf-8")
    assert "pip install -r /app/requirements.lock.txt" in df
