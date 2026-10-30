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
WARMUP_HOUR = TARGET_HOUR
WARMUP_MINUTE = (TARGET_MINUTE - 10) % 60
if TARGET_MINUTE < 10:
    WARMUP_HOUR = (TARGET_HOUR - 1) % 24
MAX_RETRY = 8
RETRY_GAP = 20 * 60


def _wb_exe():
    """定位 WorkBuddy.exe：优先 config.json 的 workbuddyExe，其次常见路径。"""
    for p in (os.path.join(os.path.dirname(BASE), "config.json"),
              os.path.join(BASE, "config.json")):
        try:
            with open(p, "r", encoding="utf-8") as f:
                v = str(json.load(f).get("workbuddyExe", "")).strip()
            if v and os.path.exists(v):
                return v
        except Exception:
            continue
    for p in (r"D:\WorkBuddy\WorkBuddy.exe",
              os.path.expandvars(r"%LOCALAPPDATA%\Programs\WorkBuddy\WorkBuddy.exe"),
              os.path.expandvars(r"%PROGRAMFILES%\WorkBuddy\WorkBuddy.exe")):
        if os.path.exists(p):
            return p
    return ""


WB_EXE = _wb_exe()


def wb_window_exists():
    """WorkBuddy 窗口是否已存在（避免重复启动）。"""
    try:
        return bool(ctypes.windll.user32.FindWindowW(None, "WorkBuddy"))
    except Exception:
        return False


def warm_up():
    """提前拉起 WorkBuddy：冷启动要 1~2 分钟，到点才启动会等超时。"""
    if wb_window_exists():
        log("预热：WorkBuddy 已在运行，无需启动")
        return
    if not WB_EXE:
        log("预热：未找到 WorkBuddy.exe，跳过")
        return
    if not os.path.exists(WB_EXE):
        log("预热：启动路径不存在 %s" % WB_EXE)
        return
    try:
        subprocess.Popen([WB_EXE], close_fds=True)
        log("预热：已提前启动 WorkBuddy（避免到点冷启动超时）")
    except Exception as e:
        log("预热：启动失败 %s" % e)


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


LOCK_PATH = os.path.join(BASE, "runner.lock")


def _pid_alive(pid):
    """判断 PID 是否还活着（不依赖 pywin32）。"""
    try:
        k32 = ctypes.windll.kernel32
        h = k32.OpenProcess(0x1000, False, int(pid))  # PROCESS_QUERY_LIMITED_INFORMATION
        if not h:
            return False
        code = ctypes.c_ulong()
        k32.GetExitCodeProcess(h, ctypes.byref(code))
        k32.CloseHandle(h)
        return code.value == 259  # STILL_ACTIVE
    except Exception:
        return False


def single_instance():
    """锁文件 + PID 存活检查。

    之前用命名互斥量，实测在「登录自启 + 手动启动」同时发生时仍会起两份实例
    （同名互斥量创建成功两次），两份同时到点会互踢、日志互相覆盖。
    """
    try:
        if os.path.exists(LOCK_PATH):
            try:
                with open(LOCK_PATH, "r", encoding="utf-8") as f:
                    old = int((f.read() or "0").strip() or 0)
            except Exception:
                old = 0
            if old and old != os.getpid() and _pid_alive(old):
                log("已有实例在运行（pid=%s），退出" % old)
                return None
        with open(LOCK_PATH, "w", encoding="utf-8") as f:
            f.write(str(os.getpid()))
        return True
    except Exception as e:
        log("单实例检查异常，继续运行: %s" % e)
        return True


def today_str():
    return datetime.now().strftime("%Y-%m-%d")


def clean_env():
    """清掉从父进程继承来的 Python 变量。

    真实故障（2026-10-29 08:00）：子进程报
    「Could not find platform independent libraries <prefix>」
    「ModuleNotFoundError: No module named 'encodings'」
    —— 环境里带了错误的 PYTHONHOME/PYTHONPATH，解释器连标准库都找不到。
    """
    env = dict(os.environ)
    for k in ("PYTHONHOME", "PYTHONPATH", "PYTHONSTARTUP", "PYTHONEXECUTABLE"):
        env.pop(k, None)
    env["PYTHONUTF8"] = "1"
    env["PYTHONIOENCODING"] = "utf-8"
    return env


def _spawn(py, extra, env):
    return subprocess.run([py, CLAIM] + extra, cwd=BASE, env=env,
                          capture_output=True, timeout=900)


def run_claim():
    pyw = PYW if os.path.exists(PYW) else sys.executable
    pyc = os.path.join(os.path.dirname(pyw), "python.exe")
    extra = [a for a in os.environ.get("WB_CLAIM_ARGS", "").split(" ") if a.strip()]
    env = clean_env()
    log("启动 claim_ocr.py（解释器 %s，参数 %s）" % (pyw, extra or "-"))
    try:
        p = _spawn(pyw, extra, env)
        err = (p.stderr or b"").decode("utf-8", "replace")
        # 解释器环境损坏时（encodings/<prefix>），换 python.exe 再试一次
        if p.returncode != 0 and ("encodings" in err or "<prefix>" in err):
            log("解释器环境异常，改用 python.exe 重试：%s" % err.strip()[:120])
            if os.path.exists(pyc):
                p = _spawn(pyc, extra, env)
                err = (p.stderr or b"").decode("utf-8", "replace")
        out = (p.stdout or b"").decode("utf-8", "replace")
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
        return p.returncode == 0 and status in ("claimed", "already_claimed",
                                                "claimed_unverified", "need_manual")
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
    try:
        return _main_loop()
    finally:
        # 退出时释放锁文件，避免下次启动被残留 PID 挡住
        try:
            if os.path.exists(LOCK_PATH):
                with open(LOCK_PATH, "r", encoding="utf-8") as f:
                    if (f.read() or "").strip() == str(os.getpid()):
                        os.remove(LOCK_PATH)
        except Exception:
            pass


def _main_loop():
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

        # 目标时间前 10 分钟预热：提前把 WorkBuddy 拉起来，到点直接是热窗口
        if (st.get("last_run") != today
                and st.get("warmup_date") != today
                and (now.hour, now.minute) >= (WARMUP_HOUR, WARMUP_MINUTE)):
            warm_up()
            st["warmup_date"] = today
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
