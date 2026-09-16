"""SEC-FP-1 recipe v2: the hardware fingerprint must not track the NIC set.

Recipe v1 folded uuid.getnode() in unconditionally, so starting Docker Desktop /
WSL / VMware / VirtualBox / Tailscale drifted the fingerprint and bricked an
already-bound activation. v2 uses machine-id as the identity root and only falls
back to the MAC when no machine-id is readable.

There is no v1 compatibility channel: the product never shipped with recipe v1,
so no activation was ever bound to it.
"""
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent))
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import rstlic_client as rc  # noqa: E402
from rstlic_client import RSTLicClient, RSTLicHardwareUnavailable  # noqa: E402

# Real-world MACs that appear/disappear under the user's feet.
NIC_SETS = [
    0x001122334455,  # physical NIC
    0x00155D001122,  # Hyper-V / WSL vEthernet
    0x005056C00001,  # VMware VMnet
]

MACHINE_ID = "9f8c1e2b4a6d47c1b0e3f5a7d9c2b4e6"


def _fp(monkeypatch, *, node, machine_id=MACHINE_ID):
    monkeypatch.setattr(rc.uuid, "getnode", lambda: node)
    monkeypatch.setattr(rc, "_platform_machine_id", lambda: machine_id)
    return RSTLicClient.fingerprint(server_guid="guid-1", app_id="app-1")


def test_fingerprint_is_stable_across_nic_set_changes(monkeypatch):
    """The core invariant. machine-id present → MAC contributes zero entropy."""
    prints = {_fp(monkeypatch, node=n) for n in NIC_SETS}
    assert len(prints) == 1, f"fingerprint drifted with the NIC set: {prints}"


def test_mac_is_the_fallback_when_machine_id_is_unreadable(monkeypatch):
    """Containers without /etc/machine-id still get a hardware-rooted print."""
    prints = {_fp(monkeypatch, node=n, machine_id="") for n in NIC_SETS}
    assert len(prints) == len(NIC_SETS)  # MAC is the only root → it must matter


def test_no_hardware_root_raises(monkeypatch):
    """Never silently fall back to a public-input hash (the SEC-FP-1 regression)."""
    monkeypatch.setattr(rc, "_platform_machine_id", lambda: "")
    monkeypatch.setattr(rc, "_primary_mac", lambda: "")
    with pytest.raises(RSTLicHardwareUnavailable):
        RSTLicClient.fingerprint(server_guid="guid-1", app_id="app-1")


def test_v2_still_binds_to_cpu_os_and_salt(monkeypatch):
    """Removing the MAC must not have removed the remaining entropy."""
    base = _fp(monkeypatch, node=NIC_SETS[0])
    monkeypatch.setattr(rc, "_cpu_descriptor", lambda: "other-cpu|arm64")
    assert _fp(monkeypatch, node=NIC_SETS[0]) != base

    monkeypatch.undo()
    monkeypatch.setattr(rc, "_platform_machine_id", lambda: MACHINE_ID)
    monkeypatch.setattr(rc.uuid, "getnode", lambda: NIC_SETS[0])
    assert RSTLicClient.fingerprint(server_guid="other-guid", app_id="app-1") != base
    assert RSTLicClient.fingerprint(server_guid="guid-1", app_id="other-app") != base
