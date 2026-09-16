"""网关不以 root 跑，两份 compose 都把权限收干净了。

失败模式是「客户现场容器起不来」，所以这条只钉声明本身（YAML 能解析、几个键都在、
镜像里建了用户并有降权 entrypoint）；真正跑一次镜像 + 挂一个老的 root 属主卷的
验证在会话记录里，不适合放进单元测试。
"""
from __future__ import annotations

from pathlib import Path

import pytest
import yaml

_ROOT = Path(__file__).resolve().parent.parent.parent.parent
COMPOSES = [_ROOT / "docker-compose.prod.yml", _ROOT / "docker-compose.sso.yml"]
DOCKERFILE = _ROOT / "Dockerfile"
ENTRYPOINT = _ROOT / "docker-entrypoint.sh"

NEEDED_CAPS = {"CHOWN", "DAC_OVERRIDE", "FOWNER", "SETUID", "SETGID"}


@pytest.mark.parametrize("path", COMPOSES, ids=lambda p: p.name)
def test_compose_parses(path):
    """裸的 `*` 和值里带 `: ` 的条目都会被 YAML 读成 map —— docker compose 直接
    起不来，而错误信息（`unexpected type map`）指不到是哪一行。"""
    doc = yaml.safe_load(path.read_text(encoding="utf-8"))
    assert "gateway" in doc["services"]
    for svc in doc["services"].values():
        for entry in svc.get("environment") or []:
            assert isinstance(entry, str), f"{path.name}: 这条环境变量被读成了 {type(entry)}"


@pytest.mark.parametrize("path", COMPOSES, ids=lambda p: p.name)
def test_gateway_drops_privileges(path):
    gw = yaml.safe_load(path.read_text(encoding="utf-8"))["services"]["gateway"]
    assert "no-new-privileges:true" in (gw.get("security_opt") or [])
    assert gw.get("cap_drop") == ["ALL"]
    # entrypoint 修老卷属主 + 降权要用的那几个，别的都不留
    assert set(gw.get("cap_add") or []) == NEEDED_CAPS
    # user: 是故意不写的 —— 老部署的 state 卷是 root 建的，钉死 uid 会让升级起不来
    assert "user" not in gw


def test_image_creates_the_unprivileged_user():
    df = DOCKERFILE.read_text(encoding="utf-8")
    assert "useradd -r -u 10001" in df
    assert "chown -R 10001:10001 /app/state /app/eval" in df
    assert 'ENTRYPOINT ["/usr/local/bin/docker-entrypoint.sh"]' in df


def test_entrypoint_drops_to_the_unprivileged_uid():
    sh = ENTRYPOINT.read_text(encoding="utf-8")
    assert "setpriv --reuid=" in sh          # util-linux，没有额外依赖
    assert 'if [ "$(id -u)" != "0" ]' in sh  # compose 已经钉了 uid 时不再折腾
