# -*- coding: utf-8 -*-
"""常驻调度器：每天定时跑 claim_ocr.py（无需管理员、重启后自动恢复）

适用场景
--------
不想依赖 WorkBuddy 内部定时任务，或者本机账号不是管理员、
`Register-ScheduledTask` / `schtasks` / COM 计划任务接口全部不可用时，
用「登录自启（HKCU Run）+ 常驻进程计时」达到同样效果，重启后自动恢复。

行为
----
- 时间取技能目录 config.json 的 claimTime（默认 08:00）
- 启动时若「今天已过目标时间且今天还没跑过」→ 立即补跑（关机/重启当天不会漏）
- 否则睡到当天目标时间再跑
- 跑失败按 RETRY_GAP 重试，最多 MAX_RETRY 次（覆盖锁屏、客户端未就绪等情况）
- 单实例：命名互斥量，避免重复启动
"""

import ctypes
import json
import os
import subprocess
import sys
import time
from datetime import datetime, timedelta

BASE = os.path.dirname(os.path.abspath(__file__))
CLAIM = os.path.join(BASE, "claim_ocr.py")
STATE = os.path.join(BASE, "runner_state.json")
LOG = os.path.join(BASE, "runner.log")
PYW = sys.executable if sys.executable.lower().endswith("pythonw.exe") else \
    os.path.join(os.path.dirname(sys.executable), "pythonw.exe")


def claim_time():
    """读 config.json 的 claimTime（技能根目录或 scripts 目录都可）。"""
    for p in (os.path.join(os.path.dirname(BASE), "config.json"),
              os.path.join(BASE, "config.json")):
        try:
            with open(p, "r", encoding="utf-8") as f:
                t = str(json.load(f).get("claimTime", "")).strip()
            hh, mm = [int(x) for x in t.split(":")[:2]]
            if 0 <= hh < 24 and 0 <= mm < 60:
                return hh, mm
        except Exception:
            continue
    return 8, 0


TARGET_HOUR, TARGET_MINUTE = claim_time()
MAX_RETRY = 8
RETRY_GAP = 20 * 60


def log(msg):
    line = "[%s] %s" % (datetime.now().strftime("%Y-%m-%d %H:%M:%S"), msg)
    try:
        with open(LOG, "a", encoding="utf-8") as f:
            f.write(line + "\n")
    except Exception:
        pass


def load_state():
    try:
        with open(STATE, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return {}


def save_state(d):
    try:
        with open(STATE, "w", encoding="utf-8") as f:
            json.dump(d, f, ensure_ascii=False, indent=2)
    except Exception:
        pass


def single_instance():
    """Local 命名互斥量（非管理员无法创建 Global 命名空间对象）。"""
    kernel32 = ctypes.windll.kernel32
    kernel32.SetLastError(0)
    handle = kernel32.CreateMutexW(None, False, "Local\\WorkBuddyDailyCreditRunner")
    err = kernel32.GetLastError()
    if err == 183:  # ERROR_ALREADY_EXISTS
        return None
    return handle or True


def today_str():
    return datetime.now().strftime("%Y-%m-%d")


def run_claim():
    pyw = PYW if os.path.exists(PYW) else sys.executable
    extra = [a for a in os.environ.get("WB_CLAIM_ARGS", "").split(" ") if a.strip()]
    log("启动 claim_ocr.py（解释器 %s，参数 %s）" % (pyw, extra or "-"))
    try:
        p = subprocess.run([pyw, CLAIM] + extra, cwd=BASE,
                           capture_output=True, timeout=900)
        out = (p.stdout or b"").decode("utf-8", "replace")
        err = (p.stderr or b"").decode("utf-8", "replace")
        for line in out.strip().splitlines()[-6:]:
            if line.strip():
                log("  claim| " + line.strip())
        if p.returncode != 0:
            log("claim 退出码 %s %s" % (p.returncode, err.strip()[:300]))
        status = None
        try:
            with open(os.path.join(BASE, "state.json"), "r", encoding="utf-8") as f:
                status = json.load(f).get("status")
        except Exception:
            pass
        log("claim 完成，退出码=%s 状态=%s" % (p.returncode, status))
        return p.returncode == 0 and status in ("claimed", "already_claimed", "claimed_unverified")
    except Exception as e:
        log("claim 异常: %s" % e)
        return False


def next_target(now):
    t = now.replace(hour=TARGET_HOUR, minute=TARGET_MINUTE, second=0, microsecond=0)
    if now >= t:
        t += timedelta(days=1)
    return t


def main():
    if single_instance() is None:
        log("已有实例在运行，退出")
        return 0
    log("调度器启动，目标时间每天 %02d:%02d" % (TARGET_HOUR, TARGET_MINUTE))
    if os.environ.get("WB_FORCE_RUN") == "1":
        log("测试模式 WB_FORCE_RUN=1：立即执行一次后退出")
        ok = run_claim()
        log("测试模式结束，结果=%s" % ("成功" if ok else "失败"))
        return 0 if ok else 1
    st = load_state()
    retries = 0
    last_logged = None
    while True:
        now = datetime.now()
        today = today_str()
        # 清零每日重试计数
        if st.get("retry_date") != today:
            retries = 0
            st["retry_date"] = today
            save_state(st)

        if st.get("last_run") != today and now.hour >= TARGET_HOUR:
            ok = run_claim()
            if ok:
                st["last_run"] = today
                st["last_result"] = "ok"
                save_state(st)
            else:
                retries += 1
                st["last_result"] = "fail_%d" % retries
                save_state(st)
                if retries >= MAX_RETRY:
                    log("今日重试已达上限，跳过（明天再试）")
                    st["last_run"] = today
                    save_state(st)
                else:
                    log("第 %d 次失败，%d 分钟后再试" % (retries, RETRY_GAP // 60))
                    time.sleep(RETRY_GAP)
                    continue
            # 跑完（无论成败）等到下一个整点目标
            time.sleep(60)
            continue

        # 未到时间：分段睡眠，最多 120 秒醒一次，便于系统休眠恢复后及时校正
        target = next_target(now) if st.get("last_run") == today else \
            now.replace(hour=TARGET_HOUR, minute=TARGET_MINUTE, second=0, microsecond=0)
        if target <= now:
            target = now + timedelta(seconds=60)
        remain = (target - now).total_seconds()
        if last_logged != target.strftime("%Y-%m-%d %H:%M"):
            log("下一次执行: %s（剩余 %.0f 分钟）" % (target.strftime("%Y-%m-%d %H:%M"), remain / 60.0))
            last_logged = target.strftime("%Y-%m-%d %H:%M")
        time.sleep(min(120, max(5, remain)))


if __name__ == "__main__":
    sys.exit(main())
