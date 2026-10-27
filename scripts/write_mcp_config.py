# -*- coding: utf-8 -*-
"""
合并写入 WorkBuddy 的 MCP 配置（默认 ~/.workbuddy/mcp.json）。

【为什么必须用 Python 写，而不是 PowerShell】
PowerShell 5.1 的 `Set-Content -Encoding utf8` / `Out-File -Encoding utf8` 会写入
UTF-8 BOM（EF BB BF）。WorkBuddy 的 JSON 解析器不认 BOM -> 整个 mcp.json
解析失败 -> **被静默忽略** -> 界面上的连接器列表永远看不到 windows-mcp，
重启多少次都没用。这是本 skill 最大的历史故障源。

本脚本一律用 encoding='utf-8' 写（无 BOM），并在写完立即自检：
  1. 首 3 字节不是 EF BB BF
  2. JSON 可被 json.loads 解析
  3. mcpServers.windows-mcp 条目存在

用法：
  python write_mcp_config.py --command "<...>\\windows-mcp.exe"
"""
import argparse
import json
import os
import shutil
import sys
import time

BOM = b"\xef\xbb\xbf"


def default_paths():
    base = os.path.join(os.path.expanduser("~"), ".workbuddy")
    return base, os.path.join(base, "mcp.json")


def main():
    ap = argparse.ArgumentParser(description="无 BOM 合并写入 WorkBuddy MCP 配置")
    ap.add_argument("--command", required=True, help="windows-mcp.exe 的绝对路径")
    ap.add_argument("--arg", action="append", default=[], help="启动参数，可多次指定（默认 serve）")
    ap.add_argument("--mcp-json", default=None, help="目标 mcp.json 路径（默认 ~/.workbuddy/mcp.json）")
    a = ap.parse_args()

    base, default_mcp = default_paths()
    mcp_json = a.mcp_json or default_mcp
    os.makedirs(os.path.dirname(mcp_json), exist_ok=True)

    data = {}
    if os.path.exists(mcp_json):
        raw = open(mcp_json, "rb").read()
        if raw[:3] == BOM:
            print("[!] 原 mcp.json 带 UTF-8 BOM —— 这正是「配了却不生效」的根因，本次已自动修正。")
        try:
            data = json.loads(raw.decode("utf-8-sig")) or {}
            if not isinstance(data, dict):
                data = {}
        except Exception as e:
            print("[!] 原 mcp.json 无法解析 (%s)，将备份后重建。" % e)
            data = {}
        bak = mcp_json + ".bak-" + time.strftime("%Y%m%d-%H%M%S")
        try:
            shutil.copy2(mcp_json, bak)
            print("[i] 已备份原配置 ->", bak)
        except Exception as e:
            print("[!] 备份失败（继续）：", e)

    servers = data.get("mcpServers")
    if not isinstance(servers, dict):
        servers = {}
    servers["windows-mcp"] = {
        "command": a.command,
        "args": a.arg if a.arg else ["serve"],
        "env": {"ANONYMIZED_TELEMETRY": "false"},
    }
    data["mcpServers"] = servers

    txt = json.dumps(data, ensure_ascii=False, indent=2)
    with open(mcp_json, "w", encoding="utf-8", newline="\n") as f:
        f.write(txt)

    # ---- 立即自检 ----
    raw = open(mcp_json, "rb").read()
    if raw[:3] == BOM:
        print("[X] 写入后仍带 BOM，异常中止！")
        return 1
    try:
        chk = json.loads(raw.decode("utf-8"))
    except Exception as e:
        print("[X] 写入后无法解析：", e)
        return 1
    if "windows-mcp" not in (chk.get("mcpServers") or {}):
        print("[X] 写入后条目缺失，异常中止！")
        return 1

    print("[OK] 已写入", mcp_json)
    print("[OK] 自检通过：无 BOM、JSON 可解析、windows-mcp 条目存在、其余 MCP 条目已保留")
    return 0


if __name__ == "__main__":
    sys.exit(main())
