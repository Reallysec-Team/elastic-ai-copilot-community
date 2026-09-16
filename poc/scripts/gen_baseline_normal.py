#!/usr/bin/env python3
"""Build the "normal" tier baseline pack (Linux + Windows) → rules_normal.json.

Why a generator, not hand-written JSON: the repetitive families (sysctl,
kernel modules, Windows registry) are one osquery pattern with a value table, so
a loop is smaller and less error-prone than ~100 near-identical JSON objects. It
also validates every rule at build time (operator ∈ known set, unique rule_id,
platform ∈ {linux,windows}, on_missing ∈ {pass,fail,error}) so a broken rule
can't reach the pack.

Sourcing (permissive only): queries target standard osquery tables
(system_controls / kernel_modules / users / shadow / mounts / registry /
services — Apache-2.0 osquery schema). standard_refs cite 等保2.0 and the CIS
control *number* as a reference, not CIS text (no copyrighted content is
copied). remediation/title/category are authored here.

ponytail: HIGH-CONFIDENCE families only (single-value equals / enumeration
expect_empty). File-content CIS checks (SSH/PAM/audit.rules) need osquery's
`augeas` table or file parsing and are fragile — left out or marked
manual_review. osquery QUERY correctness must still be validated against a real
osquery agent before shipping; this build only guarantees schema validity.

Usage:
    cd poc
    python -m scripts.gen_baseline_normal            # write the JSON
    python -m scripts.baseline_load_rules --file backend/baseline/data/rules_normal.json
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

_POC = Path(__file__).resolve().parent.parent
OUT = _POC / "backend" / "baseline" / "data" / "rules_normal.json"

_VALID_OPS = {"equals", "not_equals", "expect_empty", "expect_nonempty", "gte", "lte", "manual_review"}
_VALID_ON_MISSING = {"pass", "fail", "error"}
_VALID_PLATFORM = {"linux", "windows"}

rules: list[dict] = []


def R(rid, title, category, platform, severity, query, judge, refs, remediation, on_missing=None):
    j = dict(judge)
    if on_missing:
        j["on_missing"] = on_missing
    rules.append({
        "rule_id": rid,
        "title": title,
        "category": category,
        "platform": platform,
        "severity": severity,
        "depends_on": None,
        "standard_refs": refs,
        "collect": {"type": "osquery", "query": query},
        "judge": j,
        "remediation_template": remediation,
    })


def sysctl(rid, name, expected, title, sev, refs, remediation):
    R(rid, title, "内核网络参数", "linux", sev,
      f"SELECT current_value FROM system_controls WHERE name='{name}';",
      {"operator": "equals", "field": "current_value", "expected": expected},
      refs, remediation, on_missing="fail")


def modoff(rid, mod, title, sev, refs):
    R(rid, title, "内核模块最小化", "linux", sev,
      f"SELECT name FROM kernel_modules WHERE name='{mod}';",
      {"operator": "expect_empty"}, refs,
      f"禁用未使用的内核模块 {mod}：在 /etc/modprobe.d/ 中加 `install {mod} /bin/true`，"
      f"并 `rmmod {mod}`（如已加载）。", on_missing="pass")


def reg(rid, path, expected, title, category, sev, refs, remediation, op="equals"):
    R(rid, title, category, "windows", sev,
      f"SELECT data FROM registry WHERE path='{path}';",
      {"operator": op, "field": "data", "expected": expected},
      refs, remediation, on_missing="fail")


def svc_disabled(rid, name, title, sev, refs):
    R(rid, title, "服务最小化", "windows", sev,
      f"SELECT start_type FROM services WHERE name='{name}';",
      {"operator": "equals", "field": "start_type", "expected": "DISABLED"},
      refs, f"禁用 Windows 服务 {name}：`sc config {name} start= disabled` 并 `sc stop {name}`。",
      on_missing="pass")  # service absent = compliant


DJ = "等保2.0-三级"  # 等级保护 2.0 三级 (Chinese classified-protection)

# ─────────────────────────────── LINUX ───────────────────────────────

# 内核网络参数 (sysctl → system_controls.current_value)
sysctl("NB-KRN-001", "net.ipv4.ip_forward", "0", "禁用 IP 转发（非路由主机）", "medium",
       [f"{DJ}-8.1.3.1 访问控制", "CIS-Linux-3.3.1"], "临时禁用：`sysctl -w net.ipv4.ip_forward=0`；持久化写入 /etc/sysctl.d/。")
sysctl("NB-KRN-002", "net.ipv4.conf.all.send_redirects", "0", "禁止发送 ICMP 重定向（all）", "medium",
       [f"{DJ}-8.1.3.1", "CIS-Linux-3.3.2"], "写入 /etc/sysctl.d/ 后 `sysctl --system`。")
sysctl("NB-KRN-003", "net.ipv4.conf.default.send_redirects", "0", "禁止发送 ICMP 重定向（default）", "medium",
       [f"{DJ}-8.1.3.1", "CIS-Linux-3.3.2"], "写入 /etc/sysctl.d/ 后 `sysctl --system`。")
sysctl("NB-KRN-004", "net.ipv4.conf.all.accept_source_route", "0", "禁止接受源路由包（all）", "high",
       [f"{DJ}-8.1.3.1", "CIS-Linux-3.3.3"], "写入 /etc/sysctl.d/ 后 `sysctl --system`。")
sysctl("NB-KRN-005", "net.ipv4.conf.default.accept_source_route", "0", "禁止接受源路由包（default）", "high",
       [f"{DJ}-8.1.3.1", "CIS-Linux-3.3.3"], "写入 /etc/sysctl.d/ 后 `sysctl --system`。")
sysctl("NB-KRN-006", "net.ipv4.conf.all.accept_redirects", "0", "禁止接受 ICMP 重定向（all）", "medium",
       [f"{DJ}-8.1.3.1", "CIS-Linux-3.3.4"], "写入 /etc/sysctl.d/ 后 `sysctl --system`。")
sysctl("NB-KRN-007", "net.ipv4.conf.default.accept_redirects", "0", "禁止接受 ICMP 重定向（default）", "medium",
       [f"{DJ}-8.1.3.1", "CIS-Linux-3.3.4"], "写入 /etc/sysctl.d/ 后 `sysctl --system`。")
sysctl("NB-KRN-008", "net.ipv4.conf.all.secure_redirects", "0", "禁止接受安全 ICMP 重定向（all）", "low",
       [f"{DJ}-8.1.3.1", "CIS-Linux-3.3.5"], "写入 /etc/sysctl.d/ 后 `sysctl --system`。")
sysctl("NB-KRN-009", "net.ipv4.conf.all.log_martians", "1", "记录异常来源包（martians）", "low",
       [f"{DJ}-8.1.4.3 安全审计", "CIS-Linux-3.3.6"], "写入 /etc/sysctl.d/ 后 `sysctl --system`。")
sysctl("NB-KRN-010", "net.ipv4.icmp_echo_ignore_broadcasts", "1", "忽略广播 ICMP 请求", "medium",
       [f"{DJ}-8.1.3.1", "CIS-Linux-3.3.7"], "写入 /etc/sysctl.d/ 后 `sysctl --system`。")
sysctl("NB-KRN-011", "net.ipv4.icmp_ignore_bogus_error_responses", "1", "忽略伪造的 ICMP 错误响应", "low",
       [f"{DJ}-8.1.3.1", "CIS-Linux-3.3.8"], "写入 /etc/sysctl.d/ 后 `sysctl --system`。")
sysctl("NB-KRN-012", "net.ipv4.conf.all.rp_filter", "1", "启用反向路径过滤（all）", "medium",
       [f"{DJ}-8.1.3.1", "CIS-Linux-3.3.9"], "写入 /etc/sysctl.d/ 后 `sysctl --system`。")
sysctl("NB-KRN-013", "net.ipv4.tcp_syncookies", "1", "启用 TCP SYN Cookies（抗 SYN flood）", "high",
       [f"{DJ}-8.1.3.1", "CIS-Linux-3.3.10"], "写入 /etc/sysctl.d/ 后 `sysctl --system`。")
sysctl("NB-KRN-014", "net.ipv6.conf.all.accept_redirects", "0", "禁止接受 IPv6 ICMP 重定向", "medium",
       [f"{DJ}-8.1.3.1", "CIS-Linux-3.3.11"], "写入 /etc/sysctl.d/ 后 `sysctl --system`。")
sysctl("NB-KRN-015", "net.ipv6.conf.all.accept_ra", "0", "禁止接受 IPv6 路由通告", "low",
       [f"{DJ}-8.1.3.1", "CIS-Linux-3.3.12"], "写入 /etc/sysctl.d/ 后 `sysctl --system`。")
sysctl("NB-KRN-016", "kernel.randomize_va_space", "2", "启用完整地址空间随机化（ASLR）", "high",
       [f"{DJ}-8.1.10 入侵防范", "CIS-Linux-1.5.3"], "写入 /etc/sysctl.d/ 后 `sysctl --system`。")
sysctl("NB-KRN-017", "fs.suid_dumpable", "0", "禁止 setuid 程序生成 core dump", "medium",
       [f"{DJ}-8.1.10", "CIS-Linux-1.5.1"], "写入 /etc/sysctl.d/ 后 `sysctl --system`。")
sysctl("NB-KRN-018", "kernel.dmesg_restrict", "1", "限制非特权用户读取内核环缓冲", "low",
       [f"{DJ}-8.1.4.3", "CIS-Linux-1.5.2"], "写入 /etc/sysctl.d/ 后 `sysctl --system`。")

# 内核模块最小化 (kernel_modules → expect_empty)
modoff("NB-MOD-001", "cramfs", "禁用 cramfs 文件系统模块", "low", [f"{DJ}-8.1.10", "CIS-Linux-1.1.1.1"])
modoff("NB-MOD-002", "freevxfs", "禁用 freevxfs 文件系统模块", "low", [f"{DJ}-8.1.10", "CIS-Linux-1.1.1.2"])
modoff("NB-MOD-003", "jffs2", "禁用 jffs2 文件系统模块", "low", [f"{DJ}-8.1.10", "CIS-Linux-1.1.1.3"])
modoff("NB-MOD-004", "hfs", "禁用 hfs 文件系统模块", "low", [f"{DJ}-8.1.10", "CIS-Linux-1.1.1.4"])
modoff("NB-MOD-005", "hfsplus", "禁用 hfsplus 文件系统模块", "low", [f"{DJ}-8.1.10", "CIS-Linux-1.1.1.5"])
modoff("NB-MOD-006", "udf", "禁用 udf 文件系统模块", "low", [f"{DJ}-8.1.10", "CIS-Linux-1.1.1.6"])
modoff("NB-MOD-007", "usb-storage", "禁用 USB 存储模块（防数据外带）", "medium", [f"{DJ}-8.1.3.1", "CIS-Linux-1.1.10"])
modoff("NB-MOD-008", "dccp", "禁用 DCCP 协议模块", "low", [f"{DJ}-8.1.10", "CIS-Linux-3.4.1"])
modoff("NB-MOD-009", "sctp", "禁用 SCTP 协议模块", "low", [f"{DJ}-8.1.10", "CIS-Linux-3.4.2"])
modoff("NB-MOD-010", "rds", "禁用 RDS 协议模块", "low", [f"{DJ}-8.1.10", "CIS-Linux-3.4.3"])
modoff("NB-MOD-011", "tipc", "禁用 TIPC 协议模块", "low", [f"{DJ}-8.1.10", "CIS-Linux-3.4.4"])

# 账户与口令 (users / shadow → expect_empty enumeration)
R("NB-ACC-001", "除 root 外不存在 UID=0 的账户", "账户与口令", "linux", "high",
  "SELECT username FROM users WHERE uid=0 AND username!='root';",
  {"operator": "expect_empty"}, [f"{DJ}-8.1.4.1 身份鉴别", "CIS-Linux-6.2.9"],
  "非 root 的 UID=0 账户是越权风险；核实身份后删除或改 UID：`usermod -u <newuid> <user>`。", on_missing="pass")
R("NB-ACC-002", "不存在重复的 UID", "账户与口令", "linux", "medium",
  "SELECT uid, count(*) AS c FROM users GROUP BY uid HAVING c > 1;",
  {"operator": "expect_empty"}, [f"{DJ}-8.1.4.1", "CIS-Linux-6.2.15"],
  "重复 UID 使权限归属混乱；为多余账户分配唯一 UID。", on_missing="pass")
R("NB-ACC-003", "不存在重复的用户名", "账户与口令", "linux", "medium",
  "SELECT username, count(*) AS c FROM users GROUP BY username HAVING c > 1;",
  {"operator": "expect_empty"}, [f"{DJ}-8.1.4.1", "CIS-Linux-6.2.16"],
  "重复用户名会导致鉴别歧义；重命名冲突账户。", on_missing="pass")
R("NB-ACC-004", "不存在空口令账户", "账户与口令", "linux", "critical",
  "SELECT username FROM shadow WHERE password_status='empty';",
  {"operator": "expect_empty"}, [f"{DJ}-8.1.4.1", "CIS-Linux-6.2.1"],
  "空口令账户可被直接登录；`passwd -l <user>` 锁定或设置强口令。", on_missing="error")
R("NB-ACC-005", "系统账户（UID<1000）均为不可登录 shell", "账户与口令", "linux", "medium",
  "SELECT username FROM users WHERE uid<1000 AND uid!=0 AND shell NOT IN "
  "('/usr/sbin/nologin','/sbin/nologin','/bin/false');",
  {"operator": "expect_empty"}, [f"{DJ}-8.1.4.1", "CIS-Linux-6.2.8"],
  "系统账户不应可交互登录；`usermod -s /usr/sbin/nologin <user>`。", on_missing="pass")
R("NB-ACC-006", "root 是唯一 GID=0 的属主账户", "账户与口令", "linux", "medium",
  "SELECT username FROM users WHERE gid=0 AND username!='root';",
  {"operator": "expect_empty"}, [f"{DJ}-8.1.4.1", "CIS-Linux-6.2.11"],
  "核实非 root 的 GID=0 账户，调整其主组。", on_missing="pass")

# 文件权限 (file.mode → equals，mode 为八进制字符串如 '0644')
R("NB-FIL-001", "/etc/passwd 权限为 0644", "文件权限", "linux", "medium",
  "SELECT mode FROM file WHERE path='/etc/passwd';",
  {"operator": "equals", "field": "mode", "expected": "0644"},
  [f"{DJ}-8.1.4.4 数据保密性", "CIS-Linux-6.1.2"], "`chmod 0644 /etc/passwd`。", on_missing="fail")
R("NB-FIL-002", "/etc/shadow 权限不宽于 0640", "文件权限", "linux", "high",
  "SELECT mode FROM file WHERE path='/etc/shadow';",
  {"operator": "equals", "field": "mode", "expected": "0640"},
  [f"{DJ}-8.1.4.4", "CIS-Linux-6.1.3"], "`chmod 0640 /etc/shadow`（部分发行版为 0000）。", on_missing="fail")
R("NB-FIL-003", "/etc/group 权限为 0644", "文件权限", "linux", "medium",
  "SELECT mode FROM file WHERE path='/etc/group';",
  {"operator": "equals", "field": "mode", "expected": "0644"},
  [f"{DJ}-8.1.4.4", "CIS-Linux-6.1.4"], "`chmod 0644 /etc/group`。", on_missing="fail")
R("NB-FIL-004", "/etc/gshadow 权限不宽于 0640", "文件权限", "linux", "high",
  "SELECT mode FROM file WHERE path='/etc/gshadow';",
  {"operator": "equals", "field": "mode", "expected": "0640"},
  [f"{DJ}-8.1.4.4", "CIS-Linux-6.1.5"], "`chmod 0640 /etc/gshadow`。", on_missing="fail")
R("NB-FIL-005", "/etc/crontab 权限为 0600", "文件权限", "linux", "medium",
  "SELECT mode FROM file WHERE path='/etc/crontab';",
  {"operator": "equals", "field": "mode", "expected": "0600"},
  [f"{DJ}-8.1.4.4", "CIS-Linux-5.1.1"], "`chmod 0600 /etc/crontab`。", on_missing="fail")
R("NB-FIL-006", "/etc/ssh/sshd_config 权限为 0600", "文件权限", "linux", "medium",
  "SELECT mode FROM file WHERE path='/etc/ssh/sshd_config';",
  {"operator": "equals", "field": "mode", "expected": "0600"},
  [f"{DJ}-8.1.4.4", "CIS-Linux-5.2.1"], "`chmod 0600 /etc/ssh/sshd_config`。", on_missing="fail")

# 挂载选项 (mounts.flags → expect_empty 违规匹配)
for i, (path, opt, cis) in enumerate([
    ("/tmp", "nodev", "1.1.2.2"), ("/tmp", "nosuid", "1.1.2.3"), ("/tmp", "noexec", "1.1.2.4"),
    ("/dev/shm", "nodev", "1.1.8.2"), ("/dev/shm", "nosuid", "1.1.8.3"), ("/dev/shm", "noexec", "1.1.8.4"),
    ("/home", "nodev", "1.1.6.2"),
], 1):
    R(f"NB-MNT-{i:03d}", f"{path} 挂载启用 {opt} 选项", "挂载选项", "linux", "low",
      f"SELECT path FROM mounts WHERE path='{path}' AND flags NOT LIKE '%{opt}%';",
      {"operator": "expect_empty"}, [f"{DJ}-8.1.10", f"CIS-Linux-{cis}"],
      f"在 /etc/fstab 中为 {path} 增加 {opt} 挂载选项后 `mount -o remount {path}`。", on_missing="pass")

# 网络服务最小化 (listening_ports / processes → expect_empty)
R("NB-NET-001", "未监听 Telnet（23）", "网络服务最小化", "linux", "high",
  "SELECT port FROM listening_ports WHERE port=23;",
  {"operator": "expect_empty"}, [f"{DJ}-8.1.3.1", "CIS-Linux-2.2.x"],
  "Telnet 明文传输；停用 telnet 服务，改用 SSH。", on_missing="pass")
R("NB-NET-002", "未监听 rsh/rlogin（513/514）", "网络服务最小化", "linux", "high",
  "SELECT port FROM listening_ports WHERE port IN (512,513,514);",
  {"operator": "expect_empty"}, [f"{DJ}-8.1.3.1", "CIS-Linux-2.2.x"],
  "r 系服务不安全；卸载 rsh-server。", on_missing="pass")
R("NB-NET-003", "未运行 telnet/rsh 等明文服务进程", "网络服务最小化", "linux", "high",
  "SELECT name FROM processes WHERE name IN ('telnetd','in.telnetd','rshd','in.rshd','rlogind');",
  {"operator": "expect_empty"}, [f"{DJ}-8.1.3.1", "CIS-Linux-2.2.x"],
  "停止并卸载明文远程服务。", on_missing="pass")
R("NB-NET-004", "已运行时间同步服务（chrony/ntp）", "网络服务最小化", "linux", "medium",
  "SELECT name FROM processes WHERE name IN ('chronyd','ntpd');",
  {"operator": "expect_nonempty"}, [f"{DJ}-8.1.4.3", "CIS-Linux-2.1.1"],
  "安装并启用 chrony：`systemctl enable --now chronyd`。", on_missing="fail")
R("NB-NET-005", "已运行审计守护进程 auditd", "安全审计", "linux", "high",
  "SELECT name FROM processes WHERE name='auditd';",
  {"operator": "expect_nonempty"}, [f"{DJ}-8.1.4.3 安全审计", "CIS-Linux-4.1.1.1"],
  "安装并启用 auditd：`systemctl enable --now auditd`。", on_missing="fail")

# ────────────────────────────── WINDOWS ──────────────────────────────

HKLM = "HKEY_LOCAL_MACHINE"

# 认证与 LSA 加固 (registry → equals data)
reg("NB-WIN-001", f"{HKLM}\\SYSTEM\\CurrentControlSet\\Control\\Lsa\\RestrictAnonymous", "1",
    "限制匿名枚举 SAM 及共享", "认证加固", "high", [f"{DJ}-8.1.4.1", "CIS-Win-2.3.10.3"],
    "设置 RestrictAnonymous=1（组策略：网络访问-不允许 SAM 帐户和共享的匿名枚举）。")
reg("NB-WIN-002", f"{HKLM}\\SYSTEM\\CurrentControlSet\\Control\\Lsa\\RestrictAnonymousSAM", "1",
    "限制匿名枚举 SAM 帐户", "认证加固", "high", [f"{DJ}-8.1.4.1", "CIS-Win-2.3.10.2"],
    "设置 RestrictAnonymousSAM=1。")
reg("NB-WIN-003", f"{HKLM}\\SYSTEM\\CurrentControlSet\\Control\\Lsa\\LimitBlankPasswordUse", "1",
    "限制空口令帐户仅本地登录", "认证加固", "high", [f"{DJ}-8.1.4.1", "CIS-Win-2.3.1.3"],
    "设置 LimitBlankPasswordUse=1。")
reg("NB-WIN-004", f"{HKLM}\\SYSTEM\\CurrentControlSet\\Control\\Lsa\\LmCompatibilityLevel", "5",
    "NTLM 认证级别设为仅 NTLMv2（5）", "认证加固", "high", [f"{DJ}-8.1.4.1", "CIS-Win-2.3.11.7"],
    "设置 LmCompatibilityLevel=5（仅发送 NTLMv2，拒绝 LM/NTLM）。")
reg("NB-WIN-005", f"{HKLM}\\SOFTWARE\\Microsoft\\Windows\\CurrentVersion\\Policies\\System\\DontDisplayLastUserName", "1",
    "登录界面不显示上次登录用户名", "认证加固", "medium", [f"{DJ}-8.1.4.1", "CIS-Win-2.3.7.1"],
    "设置 DontDisplayLastUserName=1。")
reg("NB-WIN-006", f"{HKLM}\\SOFTWARE\\Microsoft\\Windows\\CurrentVersion\\Policies\\System\\EnableLUA", "1",
    "启用用户账户控制（UAC）", "认证加固", "high", [f"{DJ}-8.1.3.1", "CIS-Win-2.3.17.6"],
    "设置 EnableLUA=1 后重启。")
reg("NB-WIN-007", f"{HKLM}\\SOFTWARE\\Microsoft\\Windows\\CurrentVersion\\Policies\\System\\ConsentPromptBehaviorAdmin", "2",
    "UAC 管理员提升需在安全桌面同意", "认证加固", "medium", [f"{DJ}-8.1.3.1", "CIS-Win-2.3.17.2"],
    "设置 ConsentPromptBehaviorAdmin=2。")

# SMB / 网络 (registry → equals data)
reg("NB-WIN-010", f"{HKLM}\\SYSTEM\\CurrentControlSet\\Services\\LanmanServer\\Parameters\\SMB1", "0",
    "禁用 SMBv1 服务端", "网络协议加固", "critical", [f"{DJ}-8.1.10 入侵防范", "CIS-Win-18.3.3"],
    "设置 SMB1=0 并卸载 SMB1 特性（防 WannaCry 类蠕虫）。")
reg("NB-WIN-011", f"{HKLM}\\SYSTEM\\CurrentControlSet\\Services\\LanmanServer\\Parameters\\RequireSecuritySignature", "1",
    "SMB 服务端要求安全签名", "网络协议加固", "medium", [f"{DJ}-8.1.4.2 完整性", "CIS-Win-2.3.9.2"],
    "设置 RequireSecuritySignature=1。")
reg("NB-WIN-012", f"{HKLM}\\SYSTEM\\CurrentControlSet\\Services\\LanmanWorkstation\\Parameters\\RequireSecuritySignature", "1",
    "SMB 客户端要求安全签名", "网络协议加固", "medium", [f"{DJ}-8.1.4.2", "CIS-Win-2.3.8.2"],
    "设置 RequireSecuritySignature=1。")
reg("NB-WIN-013", f"{HKLM}\\SYSTEM\\CurrentControlSet\\Services\\NetBT\\Parameters\\NoNameReleaseOnDemand", "1",
    "拒绝 NetBIOS 名称释放请求", "网络协议加固", "low", [f"{DJ}-8.1.10", "CIS-Win-18.5.4.1"],
    "设置 NoNameReleaseOnDemand=1。")

# RDP / 远程 (registry → equals data)
reg("NB-WIN-020", f"{HKLM}\\SYSTEM\\CurrentControlSet\\Control\\Terminal Server\\WinStations\\RDP-Tcp\\UserAuthentication", "1",
    "RDP 要求网络级身份验证（NLA）", "远程访问加固", "high", [f"{DJ}-8.1.4.1", "CIS-Win-18.9.65.3.9.1"],
    "设置 UserAuthentication=1（组策略：要求使用网络级别身份验证的远程连接）。")
reg("NB-WIN-021", f"{HKLM}\\SOFTWARE\\Policies\\Microsoft\\Windows NT\\Terminal Services\\MinEncryptionLevel", "3",
    "RDP 加密级别设为高", "远程访问加固", "medium", [f"{DJ}-8.1.4.2", "CIS-Win-18.9.65.3.9.2"],
    "设置 MinEncryptionLevel=3（高，128 位）。")
reg("NB-WIN-022", f"{HKLM}\\SOFTWARE\\Policies\\Microsoft\\Windows NT\\Terminal Services\\fPromptForPassword", "1",
    "RDP 连接时始终提示输入口令", "远程访问加固", "medium", [f"{DJ}-8.1.4.1", "CIS-Win-18.9.65.3.9.3"],
    "设置 fPromptForPassword=1。")

# 自动播放 / 外设 (registry → equals data)
reg("NB-WIN-030", f"{HKLM}\\SOFTWARE\\Microsoft\\Windows\\CurrentVersion\\Policies\\Explorer\\NoDriveTypeAutoRun", "255",
    "禁用所有驱动器自动运行", "外设与自动运行", "high", [f"{DJ}-8.1.10", "CIS-Win-18.9.8.3"],
    "设置 NoDriveTypeAutoRun=255（0xFF）。")
reg("NB-WIN-031", f"{HKLM}\\SOFTWARE\\Microsoft\\Windows\\CurrentVersion\\Policies\\Explorer\\NoAutorun", "1",
    "禁止自动运行命令", "外设与自动运行", "medium", [f"{DJ}-8.1.10", "CIS-Win-18.9.8.2"],
    "设置 NoAutorun=1。")

# 审计与日志 (registry → equals data)
reg("NB-WIN-040", f"{HKLM}\\SYSTEM\\CurrentControlSet\\Control\\Lsa\\SCENoApplyLegacyAuditPolicy", "1",
    "强制使用高级审计策略子类别", "安全审计", "medium", [f"{DJ}-8.1.4.3 安全审计", "CIS-Win-2.3.2.1"],
    "设置 SCENoApplyLegacyAuditPolicy=1。")
reg("NB-WIN-041", f"{HKLM}\\SOFTWARE\\Policies\\Microsoft\\Windows\\EventLog\\Security\\MaxSize", "196608",
    "安全日志大小不小于 192MB", "安全审计", "low", [f"{DJ}-8.1.4.3", "CIS-Win-18.9.27.2.2"],
    "设置 Security\\MaxSize ≥ 196608(KB)。", op="gte")

# 防火墙 (registry → equals data)
reg("NB-WIN-050", f"{HKLM}\\SOFTWARE\\Policies\\Microsoft\\WindowsFirewall\\DomainProfile\\EnableFirewall", "1",
    "启用域配置文件防火墙", "主机防火墙", "high", [f"{DJ}-8.1.3.1", "CIS-Win-9.1.1"],
    "启用域配置文件 Windows 防火墙。")
reg("NB-WIN-051", f"{HKLM}\\SOFTWARE\\Policies\\Microsoft\\WindowsFirewall\\PrivateProfile\\EnableFirewall", "1",
    "启用专用配置文件防火墙", "主机防火墙", "high", [f"{DJ}-8.1.3.1", "CIS-Win-9.2.1"],
    "启用专用配置文件 Windows 防火墙。")
reg("NB-WIN-052", f"{HKLM}\\SOFTWARE\\Policies\\Microsoft\\WindowsFirewall\\PublicProfile\\EnableFirewall", "1",
    "启用公用配置文件防火墙", "主机防火墙", "high", [f"{DJ}-8.1.3.1", "CIS-Win-9.3.1"],
    "启用公用配置文件 Windows 防火墙。")

# Windows Update / Defender (registry → equals data)
reg("NB-WIN-060", f"{HKLM}\\SOFTWARE\\Policies\\Microsoft\\Windows Defender\\DisableAntiSpyware", "0",
    "未禁用 Windows Defender 防病毒", "恶意代码防范", "high", [f"{DJ}-8.1.9 恶意代码防范", "CIS-Win-18.9.47"],
    "确保 DisableAntiSpyware=0（不禁用 Defender）。")

# 服务最小化 (services.start_type → equals DISABLED, service 缺失=合规)
svc_disabled("NB-WSV-001", "TlntSvr", "禁用 Telnet 服务", "high", [f"{DJ}-8.1.3.1", "CIS-Win-5.x"])
svc_disabled("NB-WSV-002", "RemoteRegistry", "禁用远程注册表服务", "medium", [f"{DJ}-8.1.3.1", "CIS-Win-5.30"])
svc_disabled("NB-WSV-003", "SSDPSRV", "禁用 SSDP 发现服务", "low", [f"{DJ}-8.1.3.1", "CIS-Win-5.x"])
svc_disabled("NB-WSV-004", "upnphost", "禁用 UPnP 设备主机服务", "low", [f"{DJ}-8.1.3.1", "CIS-Win-5.x"])
svc_disabled("NB-WSV-005", "RemoteAccess", "禁用路由和远程访问服务", "medium", [f"{DJ}-8.1.3.1", "CIS-Win-5.29"])
svc_disabled("NB-WSV-006", "SharedAccess", "禁用 Internet 连接共享", "low", [f"{DJ}-8.1.3.1", "CIS-Win-5.x"])
svc_disabled("NB-WSV-007", "SNMP", "禁用 SNMP 服务（如未使用）", "medium", [f"{DJ}-8.1.3.1", "CIS-Win-5.x"])
svc_disabled("NB-WSV-008", "WMSvc", "禁用 IIS 管理服务（如未使用）", "low", [f"{DJ}-8.1.3.1", "CIS-Win-5.x"])


# ═══════════════ EXTENDED SET (→120+): more families, some fragile ═══════════════
# ponytail: SSH / login.defs checks read config via osquery's `augeas` table
# (node path -> value). augeas parsing + node paths are FRAGILE and distro-
# dependent — these especially need real-osquery-agent validation before ship.


def aug(rid, node, expected, title, category, sev, refs, remediation, op="equals"):
    R(rid, title, category, "linux", sev,
      f"SELECT value FROM augeas WHERE node='{node}';",
      {"operator": op, "field": "value", "expected": expected},
      refs, remediation, on_missing="fail")


# SSH 加固 (augeas: /files/etc/ssh/sshd_config/*)
SSHN = "/files/etc/ssh/sshd_config"
aug("NB-SSH-001", f"{SSHN}/PermitRootLogin", "no", "SSH 禁止 root 直接登录", "远程访问加固", "high",
    [f"{DJ}-8.1.4.1 身份鉴别", "CIS-Linux-5.2.8"], "sshd_config 设 `PermitRootLogin no` 后 reload sshd。")
aug("NB-SSH-002", f"{SSHN}/PermitEmptyPasswords", "no", "SSH 禁止空口令登录", "远程访问加固", "critical",
    [f"{DJ}-8.1.4.1", "CIS-Linux-5.2.9"], "sshd_config 设 `PermitEmptyPasswords no`。")
aug("NB-SSH-003", f"{SSHN}/X11Forwarding", "no", "SSH 禁用 X11 转发", "远程访问加固", "low",
    [f"{DJ}-8.1.3.1", "CIS-Linux-5.2.6"], "sshd_config 设 `X11Forwarding no`。")
aug("NB-SSH-004", f"{SSHN}/IgnoreRhosts", "yes", "SSH 忽略 .rhosts 文件", "远程访问加固", "medium",
    [f"{DJ}-8.1.4.1", "CIS-Linux-5.2.7"], "sshd_config 设 `IgnoreRhosts yes`。")
aug("NB-SSH-005", f"{SSHN}/HostbasedAuthentication", "no", "SSH 禁用基于主机的认证", "远程访问加固", "medium",
    [f"{DJ}-8.1.4.1", "CIS-Linux-5.2.7"], "sshd_config 设 `HostbasedAuthentication no`。")
aug("NB-SSH-006", f"{SSHN}/PermitUserEnvironment", "no", "SSH 禁止用户环境变量注入", "远程访问加固", "medium",
    [f"{DJ}-8.1.4.1", "CIS-Linux-5.2.10"], "sshd_config 设 `PermitUserEnvironment no`。")
aug("NB-SSH-007", f"{SSHN}/MaxAuthTries", "4", "SSH 认证重试次数不超过 4", "远程访问加固", "medium",
    [f"{DJ}-8.1.4.1", "CIS-Linux-5.2.5"], "sshd_config 设 `MaxAuthTries 4`。", op="lte")
aug("NB-SSH-008", f"{SSHN}/LoginGraceTime", "60", "SSH 登录宽限时间不超过 60 秒", "远程访问加固", "low",
    [f"{DJ}-8.1.4.1", "CIS-Linux-5.2.17"], "sshd_config 设 `LoginGraceTime 60`。", op="lte")

# 口令策略 (augeas: /files/etc/login.defs/*)
LDN = "/files/etc/login.defs"
aug("NB-PWD-001", f"{LDN}/PASS_MAX_DAYS", "90", "口令最长使用期限不超过 90 天", "账户与口令", "medium",
    [f"{DJ}-8.1.4.1", "CIS-Linux-5.4.1.1"], "login.defs 设 `PASS_MAX_DAYS 90`。", op="lte")
aug("NB-PWD-002", f"{LDN}/PASS_MIN_DAYS", "1", "口令最短使用期限不少于 1 天", "账户与口令", "low",
    [f"{DJ}-8.1.4.1", "CIS-Linux-5.4.1.2"], "login.defs 设 `PASS_MIN_DAYS 1`。", op="gte")
aug("NB-PWD-003", f"{LDN}/PASS_WARN_AGE", "7", "口令到期提前告警不少于 7 天", "账户与口令", "low",
    [f"{DJ}-8.1.4.1", "CIS-Linux-5.4.1.3"], "login.defs 设 `PASS_WARN_AGE 7`。", op="gte")

# 更多内核网络参数
sysctl("NB-KRN-019", "net.ipv4.conf.default.rp_filter", "1", "启用反向路径过滤（default）", "medium",
       [f"{DJ}-8.1.3.1", "CIS-Linux-3.3.9"], "写入 /etc/sysctl.d/ 后 `sysctl --system`。")
sysctl("NB-KRN-020", "net.ipv4.conf.default.log_martians", "1", "记录异常来源包（default）", "low",
       [f"{DJ}-8.1.4.3", "CIS-Linux-3.3.6"], "写入 /etc/sysctl.d/ 后 `sysctl --system`。")
sysctl("NB-KRN-021", "net.ipv4.conf.default.accept_redirects", "0", "禁止接受 ICMP 重定向（default 补充）", "medium",
       [f"{DJ}-8.1.3.1", "CIS-Linux-3.3.4"], "写入 /etc/sysctl.d/ 后 `sysctl --system`。")
sysctl("NB-KRN-022", "net.ipv6.conf.default.accept_redirects", "0", "禁止接受 IPv6 ICMP 重定向（default）", "medium",
       [f"{DJ}-8.1.3.1", "CIS-Linux-3.3.11"], "写入 /etc/sysctl.d/ 后 `sysctl --system`。")
sysctl("NB-KRN-023", "net.ipv6.conf.default.accept_ra", "0", "禁止接受 IPv6 路由通告（default）", "low",
       [f"{DJ}-8.1.3.1", "CIS-Linux-3.3.12"], "写入 /etc/sysctl.d/ 后 `sysctl --system`。")
sysctl("NB-KRN-024", "kernel.kptr_restrict", "1", "限制内核指针地址泄露", "low",
       [f"{DJ}-8.1.10", "CIS-Linux-1.5.x"], "写入 /etc/sysctl.d/ 后 `sysctl --system`。", )

# 更多文件权限
R("NB-FIL-007", "/etc/cron.d 目录权限为 0700", "文件权限", "linux", "low",
  "SELECT mode FROM file WHERE path='/etc/cron.d';",
  {"operator": "equals", "field": "mode", "expected": "0700"},
  [f"{DJ}-8.1.4.4", "CIS-Linux-5.1.7"], "`chmod 0700 /etc/cron.d`。", on_missing="fail")
R("NB-FIL-008", "/etc/cron.daily 目录权限为 0700", "文件权限", "linux", "low",
  "SELECT mode FROM file WHERE path='/etc/cron.daily';",
  {"operator": "equals", "field": "mode", "expected": "0700"},
  [f"{DJ}-8.1.4.4", "CIS-Linux-5.1.4"], "`chmod 0700 /etc/cron.daily`。", on_missing="fail")
R("NB-FIL-009", "/boot/grub2/grub.cfg 权限不宽于 0600", "文件权限", "linux", "medium",
  "SELECT mode FROM file WHERE path='/boot/grub2/grub.cfg';",
  {"operator": "equals", "field": "mode", "expected": "0600"},
  [f"{DJ}-8.1.4.4", "CIS-Linux-1.4.1"], "`chmod 0600 /boot/grub2/grub.cfg`（路径随发行版）。", on_missing="fail")

# 完整性 / 日志 存在性 (file / processes → expect_nonempty)
R("NB-AUD-001", "已部署文件完整性基线（AIDE 数据库存在）", "完整性校验", "linux", "medium",
  "SELECT path FROM file WHERE path IN ('/var/lib/aide/aide.db.gz','/var/lib/aide/aide.db');",
  {"operator": "expect_nonempty"}, [f"{DJ}-8.1.4.2 数据完整性", "CIS-Linux-1.3.1"],
  "安装并初始化 AIDE：`aide --init` 后将新库置为基线库。", on_missing="fail")
R("NB-AUD-002", "已运行系统日志服务 rsyslog", "安全审计", "linux", "medium",
  "SELECT name FROM processes WHERE name='rsyslogd';",
  {"operator": "expect_nonempty"}, [f"{DJ}-8.1.4.3", "CIS-Linux-4.2.1.1"],
  "启用 rsyslog：`systemctl enable --now rsyslog`。", on_missing="fail")
R("NB-NET-006", "已运行主机防火墙（firewalld/nftables）", "网络服务最小化", "linux", "high",
  "SELECT name FROM processes WHERE name IN ('firewalld','nft','nftables');",
  {"operator": "expect_nonempty"}, [f"{DJ}-8.1.3.1", "CIS-Linux-3.4.x"],
  "启用主机防火墙：`systemctl enable --now firewalld`。", on_missing="fail")

# ── 更多 Windows 注册表加固 ──
reg("NB-WIN-070", f"{HKLM}\\SYSTEM\\CurrentControlSet\\Services\\Tcpip\\Parameters\\DisableIPSourceRouting", "2",
    "禁用 IPv4 源路由", "网络协议加固", "medium", [f"{DJ}-8.1.10", "CIS-Win-18.5.19.2.1"],
    "设置 DisableIPSourceRouting=2。")
reg("NB-WIN-071", f"{HKLM}\\SYSTEM\\CurrentControlSet\\Services\\Tcpip\\Parameters\\EnableICMPRedirect", "0",
    "禁止 ICMP 重定向覆盖 OSPF 路由", "网络协议加固", "low", [f"{DJ}-8.1.10", "CIS-Win-18.5.19.2.3"],
    "设置 EnableICMPRedirect=0。")
reg("NB-WIN-072", f"{HKLM}\\SYSTEM\\CurrentControlSet\\Control\\SecurityProviders\\WDigest\\UseLogonCredential", "0",
    "禁止 WDigest 明文缓存凭据（防 mimikatz）", "认证加固", "high", [f"{DJ}-8.1.4.1", "CIS-Win-18.3.7"],
    "设置 UseLogonCredential=0。")
reg("NB-WIN-073", f"{HKLM}\\SYSTEM\\CurrentControlSet\\Control\\Lsa\\RunAsPPL", "1",
    "启用 LSASS 保护进程（RunAsPPL）", "认证加固", "high", [f"{DJ}-8.1.4.1", "CIS-Win-18.3.6"],
    "设置 RunAsPPL=1 后重启。")
reg("NB-WIN-074", f"{HKLM}\\SYSTEM\\CurrentControlSet\\Control\\Lsa\\NoLMHash", "1",
    "禁止存储 LM 哈希", "认证加固", "high", [f"{DJ}-8.1.4.1", "CIS-Win-2.3.11.5"],
    "设置 NoLMHash=1。")
reg("NB-WIN-075", f"{HKLM}\\SYSTEM\\CurrentControlSet\\Services\\LanmanWorkstation\\Parameters\\EnablePlainTextPassword", "0",
    "禁止向 SMB 服务器发送明文口令", "网络协议加固", "high", [f"{DJ}-8.1.4.1", "CIS-Win-18.5.8.1"],
    "设置 EnablePlainTextPassword=0。")
reg("NB-WIN-076", f"{HKLM}\\SOFTWARE\\Microsoft\\Windows NT\\CurrentVersion\\Winlogon\\AutoAdminLogon", "0",
    "禁用自动登录", "认证加固", "high", [f"{DJ}-8.1.4.1", "CIS-Win-18.x"],
    "设置 AutoAdminLogon=0 并清除明文口令。")
reg("NB-WIN-077", f"{HKLM}\\SOFTWARE\\Microsoft\\Windows NT\\CurrentVersion\\Winlogon\\CachedLogonsCount", "4",
    "缓存登录凭据数不超过 4", "认证加固", "medium", [f"{DJ}-8.1.4.1", "CIS-Win-2.3.7.5"],
    "设置 CachedLogonsCount<=4。", op="lte")
reg("NB-WIN-078", f"{HKLM}\\SOFTWARE\\Policies\\Microsoft\\Windows\\Installer\\AlwaysInstallElevated", "0",
    "禁止以提升权限安装 MSI", "系统加固", "high", [f"{DJ}-8.1.3.1", "CIS-Win-18.9.85.1"],
    "设置 AlwaysInstallElevated=0。")
reg("NB-WIN-079", f"{HKLM}\\SOFTWARE\\Microsoft\\Windows\\CurrentVersion\\Policies\\System\\FilterAdministratorToken", "1",
    "内置管理员启用管理审批模式", "认证加固", "medium", [f"{DJ}-8.1.3.1", "CIS-Win-2.3.17.1"],
    "设置 FilterAdministratorToken=1。")
reg("NB-WIN-080", f"{HKLM}\\SOFTWARE\\Policies\\Microsoft\\Windows\\WindowsUpdate\\AU\\NoAutoUpdate", "0",
    "未禁用自动更新", "补丁管理", "high", [f"{DJ}-8.1.5 补丁管理", "CIS-Win-18.9.108.2.1"],
    "设置 NoAutoUpdate=0。")
reg("NB-WIN-081", f"{HKLM}\\SOFTWARE\\Policies\\Microsoft\\Windows\\WindowsUpdate\\AU\\AUOptions", "4",
    "自动更新配置为自动下载并计划安装", "补丁管理", "medium", [f"{DJ}-8.1.5", "CIS-Win-18.9.108.2.2"],
    "设置 AUOptions=4。")
reg("NB-WIN-082", f"{HKLM}\\SOFTWARE\\Policies\\Microsoft\\Windows Defender\\Real-Time Protection\\DisableRealtimeMonitoring", "0",
    "未禁用 Defender 实时监控", "恶意代码防范", "high", [f"{DJ}-8.1.9", "CIS-Win-18.9.47.9.1"],
    "确保 DisableRealtimeMonitoring=0。")
reg("NB-WIN-083", f"{HKLM}\\SOFTWARE\\Policies\\Microsoft\\Windows\\PowerShell\\ScriptBlockLogging\\EnableScriptBlockLogging", "1",
    "启用 PowerShell 脚本块日志", "安全审计", "medium", [f"{DJ}-8.1.4.3", "CIS-Win-18.9.100.1"],
    "设置 EnableScriptBlockLogging=1。")
reg("NB-WIN-084", f"{HKLM}\\SOFTWARE\\Policies\\Microsoft\\Windows NT\\DNSClient\\EnableMulticast", "0",
    "禁用 LLMNR（防投毒）", "网络协议加固", "medium", [f"{DJ}-8.1.10", "CIS-Win-18.5.4.2"],
    "设置 EnableMulticast=0。")
reg("NB-WIN-085", f"{HKLM}\\SOFTWARE\\Microsoft\\Windows\\CurrentVersion\\Policies\\System\\InactivityTimeoutSecs", "900",
    "交互登录空闲锁屏不超过 900 秒", "认证加固", "low", [f"{DJ}-8.1.4.1", "CIS-Win-2.3.7.3"],
    "设置 InactivityTimeoutSecs<=900（且>0）。", op="lte")
reg("NB-WIN-086", f"{HKLM}\\SYSTEM\\CurrentControlSet\\Control\\Lsa\\FullPrivilegeAuditing", "1",
    "审计特权使用（备份/还原权限）", "安全审计", "low", [f"{DJ}-8.1.4.3", "CIS-Win-2.3.4.x"],
    "启用完整权限审计。")

# 更多服务最小化
svc_disabled("NB-WSV-009", "Fax", "禁用传真服务", "low", [f"{DJ}-8.1.3.1", "CIS-Win-5.x"])
svc_disabled("NB-WSV-010", "WMPNetworkSvc", "禁用 WMP 网络共享服务", "low", [f"{DJ}-8.1.3.1", "CIS-Win-5.x"])
svc_disabled("NB-WSV-011", "LxssManager", "禁用 WSL 管理服务（如未使用）", "low", [f"{DJ}-8.1.3.1", "CIS-Win-5.x"])
svc_disabled("NB-WSV-012", "SessionEnv", "禁用远程桌面配置服务（如未使用）", "low", [f"{DJ}-8.1.3.1", "CIS-Win-5.x"])


# ─────────────────────────────── validate + emit ───────────────────────────────

def _validate() -> list[str]:
    errs: list[str] = []
    seen: set[str] = set()
    for r in rules:
        rid = r["rule_id"]
        if rid in seen:
            errs.append(f"duplicate rule_id: {rid}")
        seen.add(rid)
        if r["platform"] not in _VALID_PLATFORM:
            errs.append(f"{rid}: bad platform {r['platform']}")
        op = r["judge"]["operator"]
        if op not in _VALID_OPS:
            errs.append(f"{rid}: bad operator {op}")
        om = r["judge"].get("on_missing")
        if om is not None and om not in _VALID_ON_MISSING:
            errs.append(f"{rid}: bad on_missing {om}")
        if op in ("equals", "not_equals", "gte", "lte") and not r["judge"].get("field"):
            errs.append(f"{rid}: {op} requires judge.field")
        if not r["collect"]["query"].strip():
            errs.append(f"{rid}: empty query")
    return errs


def main() -> int:
    errs = _validate()
    if errs:
        print("VALIDATION FAILED:")
        for e in errs:
            print("  -", e)
        return 1
    OUT.write_text(json.dumps({"rules": rules}, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    from collections import Counter
    plat = Counter(r["platform"] for r in rules)
    print(f"OK — wrote {len(rules)} rules → {OUT.relative_to(_POC)}")
    print(f"     platforms: {dict(plat)}")
    print(f"     operators: {dict(Counter(r['judge']['operator'] for r in rules))}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
