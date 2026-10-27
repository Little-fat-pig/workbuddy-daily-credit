# -*- coding: utf-8 -*-
"""
一键自检：确认「每日自动领 WorkBuddy 积分」的全部前置条件。

用法：
  python verify.py

输出分两类：
  * 硬性项（HARD）：脚本/配置层，必须全绿，否则功能不可能工作 -> 影响退出码
  * 人工项（MANUAL）：WorkBuddy 的安全闸门，AI 无法代做 -> 不影响退出码，但会醒目提示

退出码：0 = 硬性项全过（可直接建定时任务）；1 = 有硬性项失败
"""
import glob
import json
import os
import sys

HOME = os.path.expanduser("~")
BASE = os.path.join(HOME, ".workbuddy")
VENV = os.path.join(BASE, "binaries", "python", "envs", "default")
EXE = os.path.join(VENV, "Scripts", "windows-mcp.exe")
MCP = os.path.join(BASE, "mcp.json")
APR = os.path.join(BASE, "mcp-approvals.json")
BOM = b"\xef\xbb\xbf"

hard_ok = True
manual_ok = True


def hard(pass_, name, detail=""):
    global hard_ok
    if not pass_:
        hard_ok = False
    print("%s %s%s" % ("[PASS]" if pass_ else "[FAIL]", name, ("  ->  " + detail) if detail else ""))


def manual(pass_, name, detail=""):
    global manual_ok
    if pass_:
        print("[PASS] %s" % name)
    else:
        manual_ok = False
        print("[TODO] %s  ->  %s" % (name, detail))


print("== WorkBuddy 每日领积分 · 环境自检 ==")
print("")

# 1. 托管 venv
have_venv = os.path.isdir(VENV)
hard(have_venv, "WorkBuddy 托管 venv 存在", VENV)

# 2. windows-mcp 可执行文件
have_exe = os.path.isfile(EXE)
hard(have_exe, "windows-mcp.exe 已安装", EXE if not have_exe else "")

# 3. mcp.json 存在
have_mcp = os.path.isfile(MCP)
hard(have_mcp, "mcp.json 存在", MCP)

# 4. 无 BOM  <-- 最常见故障源
if have_mcp:
    raw = open(MCP, "rb").read()
    nobom = raw[:3] != BOM
    hard(nobom, "mcp.json 无 UTF-8 BOM",
         "" if nobom else "文件头是 EF BB BF，WorkBuddy 会静默忽略整个文件。修复：重跑 scripts/install.ps1")
    # 5. 可解析
    data = {}
    try:
        data = json.loads(raw.decode("utf-8"))
        hard(True, "mcp.json 可被 JSON 解析")
    except Exception as e:
        hard(False, "mcp.json 可被 JSON 解析", str(e))
    # 6. 条目存在
    ent = (data.get("mcpServers") or {}).get("windows-mcp") if isinstance(data, dict) else None
    hard(isinstance(ent, dict), "mcpServers 中存在 windows-mcp 条目")
    # 7. command 路径真实存在
    if isinstance(ent, dict):
        cmd = ent.get("command", "")
        hard(os.path.isfile(cmd), "windows-mcp 的 command 路径真实存在", cmd)
    # 8. 保留了别的 MCP 条目（信息性）
    others = [k for k in (data.get("mcpServers") or {}) if k != "windows-mcp"]
    if others:
        print("[INFO] 同时保留的其它 MCP 条目：", ", ".join(others))

# 9. 连接器信任状态（人工闸门）
trusted = False
if os.path.isfile(APR):
    try:
        with open(APR, encoding="utf-8") as f:
            trusted = any(str(k).endswith("::windows-mcp") for k in json.load(f))
    except Exception:
        pass
manual(trusted, "连接器已信任 windows-mcp",
       "未信任：连接器面板 **右上角「自定义连接器」** -> 点「信任」-> 彻底重启 WorkBuddy")

print("")
print("---- 结论 ----")
if not hard_ok:
    print("[X] 有硬性项未通过，按提示修复后重跑本脚本。")
    print("    一键修复：powershell -ExecutionPolicy Bypass -File scripts\\install.ps1")
    sys.exit(1)
if not manual_ok:
    print("[!] 脚本层已就绪。还差 1 个人工步骤（信任连接器 + 重启 WorkBuddy），完成后本脚本会全绿。")
    sys.exit(0)
print("[OK] 全部通过 —— 可以直接建定时任务并跑一次领取验证。")
sys.exit(0)
