# -*- coding: utf-8 -*-
"""WorkBuddy 每日 100 积分自动领取（方案 B：图像 + Windows OCR）

什么时候用这个脚本
------------------
方案 A（SKILL.md 主流程）用 windows-mcp 的 `Snapshot(use_ui_tree)` 按文字
「立即领取」定位。但 WorkBuddy 是 Electron 客户端，在部分机器上
**它的窗口在 Windows UI 树里是空的**（只有窗口外壳、没有子控件），
Snapshot 读不到按钮 —— 这时用本脚本：截图（PrintWindow）+ Windows 自带 OCR
按文字定位，再真实点击，效果等价且不依赖连接器。

设计要点
--------
1. DPI 感知：125% 缩放下 GetWindowRect 返回逻辑像素，必须先 SetProcessDpiAwareness(2)
   让矩形与截图（物理像素）同坐标系，否则点击全部偏移。
2. PrintWindow 截图：不受壁纸/微信等窗口遮挡影响。
3. 定位靠 OCR 文字，不靠硬编码坐标：
   左下角「Buddy加油站」卡片是多张自动轮播，只有出现「立即领取」四个字才点，
   绝不点「立即前往」「立即投稿」（守安全红线）。
   OCR 可能把简体识别成繁体（「立即领取」→「立即領取」），故所有 OCR 文本先经
   norm_text() 繁→简归一化，否则按钮永远匹配不上、被误判成「今日已领」（静默漏领）。
   卡片区若读到「退出登录/意见反馈」，说明账号面板挡住了卡片 → close_overlays() 先 ESC 清掉。
4. 验证靠账号面板余额：点左下角账号看「积分余额」，领前领后对比。

用法
----
  python claim_ocr.py            # 正常领取
  python claim_ocr.py --dry      # 只看状态不点击
  python claim_ocr.py --balance  # 只读余额
"""

import argparse
import ctypes
import ctypes.wintypes as wt
import json
import os
import re
import subprocess
import sys
import time
from datetime import datetime

try:
    ctypes.windll.shcore.SetProcessDpiAwareness(2)  # PROCESS_PER_MONITOR_DPI_AWARE
except Exception:
    try:
        ctypes.windll.user32.SetProcessDPIAware()
    except Exception:
        pass

from PIL import Image, ImageOps

BASE = os.path.dirname(os.path.abspath(__file__))
OCR_PS = os.path.join(BASE, "ocr.ps1")
LOG_PATH = os.path.join(BASE, "claim.log")
STATE_PATH = os.path.join(BASE, "state.json")
SHOT_DIR = os.path.join(BASE, "shots")
TMP_DIR = os.path.join(BASE, "tmp")
WIN_TITLE = "WorkBuddy"

# 客户端 exe 位置因安装方式而异：优先从窗口反查进程路径，再退回到常见路径
EXE_CANDIDATES = [
    os.environ.get("WORKBUDDY_EXE", ""),
    os.path.join(os.environ.get("LOCALAPPDATA", ""), "Programs", "WorkBuddy", "WorkBuddy.exe"),
    os.path.join(os.environ.get("ProgramFiles", r"C:\Program Files"), "WorkBuddy", "WorkBuddy.exe"),
    r"D:\WorkBuddy\WorkBuddy.exe",
]

CLAIM_TEXT = "立即领取"
TITLE_HINT_A = "每日可领"
TITLE_HINT_B = "100"

# Windows OCR 有时把简体字识别成繁体（实测「立即领取」→「立即領取」），
# 导致按钮永远匹配不上、被误判成「今日已领」。统一归一化后再匹配。
TRAD2SIMP = str.maketrans({
    "領": "领", "積": "积", "餘": "余", "額": "额", "員": "员",
    "開": "开", "級": "级", "獎": "奖", "對": "对", "這": "这",
    "個": "个", "點": "点", "擊": "击", "確": "确", "認": "认",
    "暫": "暂", "無": "无", "務": "务", "進": "进",
})

# 弹层特征词：出现这些说明左下角被账号面板/子菜单挡住，卡片必然检测不到
OVERLAY_HINTS = ("积分余额", "退出登录", "意见反馈", "检查更新", "外观记忆", "外观上新", "设置")


def norm_text(s):
    """OCR 文本归一化：繁体→简体，去空白与全角空格。"""
    if not s:
        return ""
    return s.translate(TRAD2SIMP).replace("\u3000", "").replace(" ", "")


def looks_like_overlay(txt):
    return any(k in (txt or "") for k in OVERLAY_HINTS)

user32 = ctypes.WinDLL("user32", use_last_error=True)
gdi32 = ctypes.WinDLL("gdi32", use_last_error=True)
kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)

user32.GetWindowRect.argtypes = [wt.HWND, ctypes.POINTER(wt.RECT)]
user32.GetWindowTextW.argtypes = [wt.HWND, wt.LPWSTR, ctypes.c_int]
user32.PrintWindow.argtypes = [wt.HWND, wt.HDC, wt.UINT]
user32.GetWindowDC.argtypes = [wt.HWND]
user32.GetWindowDC.restype = wt.HDC
user32.ReleaseDC.argtypes = [wt.HWND, wt.HDC]
gdi32.CreateCompatibleDC.argtypes = [wt.HDC]
gdi32.CreateCompatibleDC.restype = wt.HDC
gdi32.CreateCompatibleBitmap.argtypes = [wt.HDC, ctypes.c_int, ctypes.c_int]
gdi32.CreateCompatibleBitmap.restype = wt.HBITMAP
gdi32.SelectObject.argtypes = [wt.HDC, wt.HGDIOBJ]
gdi32.SelectObject.restype = wt.HGDIOBJ
gdi32.DeleteObject.argtypes = [wt.HGDIOBJ]
gdi32.DeleteDC.argtypes = [wt.HDC]


class BITMAPINFOHEADER(ctypes.Structure):
    _fields_ = [("biSize", wt.DWORD), ("biWidth", wt.LONG), ("biHeight", wt.LONG),
                ("biPlanes", wt.WORD), ("biBitCount", wt.WORD), ("biCompression", wt.DWORD),
                ("biSizeImage", wt.DWORD), ("biXPelsPerMeter", wt.LONG),
                ("biYPelsPerMeter", wt.LONG), ("biClrUsed", wt.DWORD), ("biClrImportant", wt.DWORD)]


class BITMAPINFO(ctypes.Structure):
    _fields_ = [("bmiHeader", BITMAPINFOHEADER), ("bmiColors", wt.DWORD * 3)]


gdi32.GetDIBits.argtypes = [wt.HDC, wt.HBITMAP, ctypes.c_uint, ctypes.c_uint,
                            ctypes.c_void_p, ctypes.POINTER(BITMAPINFO), ctypes.c_uint]
gdi32.GetDIBits.restype = ctypes.c_int

user32.GetWindowThreadProcessId.argtypes = [wt.HWND, ctypes.POINTER(wt.DWORD)]
kernel32.OpenProcess.argtypes = [wt.DWORD, wt.BOOL, wt.DWORD]
kernel32.OpenProcess.restype = wt.HANDLE
kernel32.QueryFullProcessImageNameW.argtypes = [wt.HANDLE, wt.DWORD, wt.LPWSTR,
                                                ctypes.POINTER(wt.DWORD)]
kernel32.QueryFullProcessImageNameW.restype = wt.BOOL
kernel32.CloseHandle.argtypes = [wt.HANDLE]


def exe_from_window(hwnd):
    """从窗口句柄反查进程 exe 路径（不依赖安装位置，最可靠）。"""
    try:
        pid = wt.DWORD(0)
        user32.GetWindowThreadProcessId(hwnd, ctypes.byref(pid))
        PROCESS_QUERY_LIMITED_INFORMATION = 0x1000
        h = kernel32.OpenProcess(PROCESS_QUERY_LIMITED_INFORMATION, False, pid.value)
        if not h:
            return None
        try:
            size = wt.DWORD(1024)
            buf = ctypes.create_unicode_buffer(1024)
            if kernel32.QueryFullProcessImageNameW(h, 0, buf, ctypes.byref(size)):
                return buf.value
        finally:
            kernel32.CloseHandle(h)
    except Exception:
        pass
    return None


def resolve_exe(hwnd=None):
    p = exe_from_window(hwnd) if hwnd else None
    if p and os.path.exists(p):
        return p
    for c in EXE_CANDIDATES:
        if c and os.path.exists(c):
            return c
    return None


# ---------------------------------------------------------------- logging
def log(msg):
    line = "[%s] %s" % (datetime.now().strftime("%Y-%m-%d %H:%M:%S"), msg)
    print(line, flush=True)
    try:
        os.makedirs(BASE, exist_ok=True)
        with open(LOG_PATH, "a", encoding="utf-8") as f:
            f.write(line + "\n")
    except Exception:
        pass


def write_state(**kw):
    try:
        with open(STATE_PATH, "w", encoding="utf-8") as f:
            json.dump(kw, f, ensure_ascii=False, indent=2)
    except Exception:
        pass


# ---------------------------------------------------------------- window
def find_window():
    found = []

    def cb(hwnd, _):
        if user32.IsWindowVisible(hwnd):
            n = user32.GetWindowTextLengthW(hwnd)
            if n:
                buf = ctypes.create_unicode_buffer(n + 1)
                user32.GetWindowTextW(hwnd, buf, n + 1)
                if buf.value.strip() == WIN_TITLE:
                    r = wt.RECT()
                    user32.GetWindowRect(hwnd, ctypes.byref(r))
                    w, h = r.right - r.left, r.bottom - r.top
                    if w > 400 and h > 300:
                        found.append((w * h, hwnd))
        return True

    user32.EnumWindows(ctypes.WINFUNCTYPE(ctypes.c_bool, wt.HWND, wt.LPARAM)(cb), 0)
    if not found:
        return None
    found.sort(reverse=True)
    return found[0][1]


def get_rect(hwnd):
    r = wt.RECT()
    user32.GetWindowRect(hwnd, ctypes.byref(r))
    return r.left, r.top, r.right, r.bottom


def ensure_window(wait=90):
    hwnd = find_window()
    if hwnd:
        return hwnd
    exe = resolve_exe()
    if not exe:
        log("未找到 WorkBuddy 窗口，也没能定位客户端 exe（可用环境变量 WORKBUDDY_EXE 指定）")
        return None
    log("WorkBuddy 未运行，尝试启动: %s" % exe)
    try:
        subprocess.Popen([exe], close_fds=True)
    except Exception as e:
        log("启动失败: %s" % e)
        return None
    t0 = time.time()
    while time.time() - t0 < wait:
        time.sleep(3)
        hwnd = find_window()
        if hwnd:
            log("WorkBuddy 已启动，等待界面渲染 20s")
            time.sleep(20)
            return hwnd
    log("等待窗口超时")
    return None


def focus(hwnd, tries=3):
    SW_RESTORE = 9
    for _ in range(tries):
        if user32.IsIconic(hwnd):
            user32.ShowWindow(hwnd, SW_RESTORE)
            time.sleep(0.8)
        fg = user32.GetForegroundWindow()
        if fg == hwnd:
            return True
        cur = kernel32.GetCurrentThreadId()
        tid = user32.GetWindowThreadProcessId(fg, None)
        attached = False
        try:
            attached = bool(user32.AttachThreadInput(cur, tid, True))
        except Exception:
            pass
        user32.BringWindowToTop(hwnd)
        user32.SetForegroundWindow(hwnd)
        user32.SetFocus(hwnd)
        if attached:
            user32.AttachThreadInput(cur, tid, False)
        time.sleep(0.5)
        if user32.GetForegroundWindow() == hwnd:
            return True
    return user32.GetForegroundWindow() == hwnd


def capture(hwnd, path=None):
    l, t, r, b = get_rect(hwnd)
    w, h = r - l, b - t
    hwnd_dc = user32.GetWindowDC(hwnd)
    mem_dc = gdi32.CreateCompatibleDC(hwnd_dc)
    bmp = gdi32.CreateCompatibleBitmap(hwnd_dc, w, h)
    gdi32.SelectObject(mem_dc, bmp)
    user32.PrintWindow(hwnd, mem_dc, 2)  # PW_RENDERFULLCONTENT
    bmi = BITMAPINFO()
    bmi.bmiHeader.biSize = ctypes.sizeof(BITMAPINFOHEADER)
    bmi.bmiHeader.biWidth = w
    bmi.bmiHeader.biHeight = -h
    bmi.bmiHeader.biPlanes = 1
    bmi.bmiHeader.biBitCount = 32
    bmi.bmiHeader.biCompression = 0
    buf = ctypes.create_string_buffer(w * h * 4)
    gdi32.GetDIBits(mem_dc, bmp, 0, h, ctypes.cast(buf, ctypes.c_void_p), ctypes.byref(bmi), 0)
    img = Image.frombuffer("RGBA", (w, h), buf, "raw", "BGRA", 0, 1).convert("RGB")
    gdi32.DeleteObject(bmp)
    gdi32.DeleteDC(mem_dc)
    user32.ReleaseDC(hwnd, hwnd_dc)
    if path:
        img.save(path)
    return img


def click(x, y):
    user32.SetCursorPos(int(x), int(y))
    time.sleep(0.08)
    user32.mouse_event(0x0002, 0, 0, 0, 0)  # LEFTDOWN
    time.sleep(0.05)
    user32.mouse_event(0x0004, 0, 0, 0, 0)  # LEFTUP
    time.sleep(0.12)


def press_esc():
    VK_ESCAPE = 0x1B
    user32.keybd_event(VK_ESCAPE, 0, 0, 0)
    time.sleep(0.05)
    user32.keybd_event(VK_ESCAPE, 0, 2, 0)
    time.sleep(0.3)


# ---------------------------------------------------------------- OCR
CREATE_NO_WINDOW = 0x08000000


def ocr(img, name="roi", scale=2.0, gray=False):
    """对 PIL 图像做 OCR，返回 word 列表（坐标为「原图」像素坐标）。"""
    os.makedirs(TMP_DIR, exist_ok=True)
    if gray:
        try:
            img = ImageOps.autocontrast(img.convert("L")).convert("RGB")
        except Exception:
            pass
    if scale and scale != 1.0:
        img2 = img.resize((int(img.width * scale), int(img.height * scale)), Image.LANCZOS)
    else:
        img2, scale = img, 1.0
    png = os.path.join(TMP_DIR, "ocr_%s.png" % name)
    out = os.path.join(TMP_DIR, "ocr_%s.json" % name)
    img2.save(png)
    if os.path.exists(out):
        try:
            os.remove(out)
        except Exception:
            pass
    try:
        subprocess.run(["powershell", "-NoProfile", "-ExecutionPolicy", "Bypass", "-File",
                        OCR_PS, "-ImagePath", png, "-OutFile", out],
                       capture_output=True, timeout=90, creationflags=CREATE_NO_WINDOW)
    except Exception as e:
        log("OCR 调用失败: %s" % e)
        return []
    if not os.path.exists(out):
        return []
    try:
        with open(out, "r", encoding="utf-8-sig") as f:
            data = json.load(f)
    except Exception as e:
        log("OCR 结果解析失败: %s" % e)
        return []
    if isinstance(data, dict):
        data = [data]
    words = []
    for d in data:
        if not isinstance(d, dict) or "text" not in d:
            continue
        words.append({"text": norm_text(d["text"]), "x": d["x"] / scale, "y": d["y"] / scale,
                      "w": d["w"] / scale, "h": d["h"] / scale})
    return [w for w in words if w["text"]]


def char_cells(words):
    """把 OCR 词展开成单字符，按行分组后按 x 排序。"""
    lines = []
    for w in sorted(words, key=lambda d: (d["y"], d["x"])):
        tol = max(8.0, w["h"] * 0.7)
        placed = False
        for ln in lines:
            if abs(ln["y"] - w["y"]) <= tol:
                ln["words"].append(w)
                placed = True
                break
        if not placed:
            lines.append({"y": w["y"], "words": [w]})
    cells = []
    for ln in lines:
        for w in sorted(ln["words"], key=lambda d: d["x"]):
            txt = w["text"]
            n = max(1, len(txt))
            step = w["w"] / n
            for i, ch in enumerate(txt):
                cells.append({"ch": ch, "x": w["x"] + step * (i + 0.5),
                              "y": w["y"] + w["h"] / 2.0, "h": w["h"],
                              "bx": w["x"], "by": w["y"], "bw": w["w"], "bh": w["h"]})
    return cells


def find_seq(words, target):
    """在同一行内按 x 递增顺序匹配字符串，返回其外接框与中心点。"""
    cells = char_cells(words)
    n = len(target)
    for i in range(len(cells)):
        if cells[i]["ch"] != target[0]:
            continue
        got = [cells[i]]
        k = 1
        for c in cells[i + 1:]:
            if k >= n:
                break
            prev = got[-1]
            if c["ch"] == target[k] and c["x"] > prev["x"] and abs(c["y"] - prev["y"]) <= max(8.0, prev["h"]):
                got.append(c)
                k += 1
        if k == n:
            xs0 = min(g["bx"] for g in got)
            ys0 = min(g["by"] for g in got)
            xs1 = max(g["bx"] + g["bw"] for g in got)
            ys1 = max(g["by"] + g["bh"] for g in got)
            return {"x0": xs0, "y0": ys0, "x1": xs1, "y1": ys1,
                    "cx": (xs0 + xs1) / 2.0, "cy": (ys0 + ys1) / 2.0,
                    "w": xs1 - xs0, "h": ys1 - ys0}
    return None


def joined_text(words):
    return "".join(w["text"] for w in words)


# ---------------------------------------------------------------- 余额
def find_balance(words):
    """在 OCR 结果里找「积分余额」标签下方的数字。

    返回 (值, 原始数字串, 数字位数)；位数越多表示那次 OCR 读得越完整。
    """
    lab = find_seq(words, "积分余额")
    if not lab:
        return None, None, 0
    # 收集标签下方一定范围内的数字 token
    toks = []
    for w in words:
        t = w["text"].replace(" ", "")
        if not re.search(r"\d", t):
            continue
        if w["y"] < lab["y0"] - 6 or w["y"] > lab["y1"] + 90:
            continue
        if w["x"] + w["w"] < lab["x0"] - 40 or w["x"] > lab["x0"] + 260:
            continue
        toks.append(w)
    if not toks:
        return None, None, 0
    toks.sort(key=lambda d: d["x"])
    groups, seps = [], []
    for w in toks:
        t = w["text"].strip()
        if re.fullmatch(r"[\d,.\s]+", t) and re.search(r"\d", t):
            digits = re.sub(r"[^\d]", "", t)
            if digits:
                groups.append(digits)
                if re.search(r"[,.]", t):
                    seps.append(len(groups) - 1)
        elif w["w"] <= 8 and w["h"] <= 8:
            seps.append(len(groups) - 1)
    if not groups:
        return None, None, 0
    digits = "".join(groups)
    raw = ",".join(groups)
    n = len(digits)
    # WorkBuddy 面板固定两位小数，千分位逗号常被 OCR 一并吞掉，
    # 因此按总位数还原：>=5 位取末两位为小数，4 位取末一位，其余视为整数。
    if n >= 5:
        val = float(digits[:-2] + "." + digits[-2:])
    elif n == 4:
        val = float(digits[:-1] + "." + digits[-1])
    else:
        val = float(digits)
    if not (0 < val < 10_000_000):
        return None, raw, n
    return val, raw, n


def read_balance(hwnd, tag="bal"):
    """点开左下角账号面板读「积分余额」，读完关闭面板。

    - 面板可能本来就是开着的（上次异常退出），所以先检测再决定是否点头像
    - 面板停在子菜单（无「积分余额」）时，先 ESC 再点头像
    - OCR 偶发漏位，多次读数取「数字位数最多」的那次；两次一致即提前采用
    """
    cands = []
    words = []
    opened = False
    for attempt in range(4):
        img = capture(hwnd, os.path.join(SHOT_DIR, "%s_%s_%d.png" %
                                        (tag, datetime.now().strftime("%H%M%S"), attempt)))
        W, H = img.size
        roi = img.crop((0, int(H * 0.18), int(W * 0.38), int(H * 0.99)))
        words = ocr(roi, name="%s_%d" % (tag, attempt), scale=2.0, gray=True)
        if find_seq(words, "积分余额"):
            opened = True
            val, raw, nd = find_balance(words)
            if val is not None:
                cands.append((nd, val, raw))
                log("第%d次读数: %s (raw=%s 位数=%d)" % (attempt + 1, val, raw, nd))
                if len(cands) >= 2 and cands[-1][1] == cands[-2][1]:
                    break
            time.sleep(0.5)
        else:
            if opened:
                break
            # 有弹层但不是余额面板（子菜单）→ 先 ESC 收起，再点头像
            if looks_like_overlay(joined_text(words)):
                log("账号面板停在子菜单，先按 ESC 收起")
                press_esc()
                time.sleep(0.6)
                continue
            rect = get_rect(hwnd)
            click(rect[0] + W * 0.040, rect[1] + H * 0.958)
            time.sleep(1.4)
    if not cands:
        log("余额读取失败（未识别到「积分余额」或数字）")
        return None, None, words
    best = max(cands, key=lambda c: c[0])
    val, raw = best[1], best[2]
    log("采用余额: %s（共 %d 次读数）" % (val, len(cands)))

    # 关闭面板，避免遮挡左下角加油站卡片
    if find_seq(words, "积分余额"):
        press_esc()
        time.sleep(0.5)
        chk = capture(hwnd)
        cw, ch = chk.size
        w2 = ocr(chk.crop((0, int(ch * 0.18), int(cw * 0.38), int(ch * 0.99))),
                 name=tag + "_chk", scale=3.0)
        if find_seq(w2, "积分余额"):
            log("ESC 未关闭面板，再点一次头像")
            rect = get_rect(hwnd)
            click(rect[0] + cw * 0.040, rect[1] + ch * 0.958)
            time.sleep(0.6)
    return val, raw, words


# ---------------------------------------------------------------- 卡片
def card_roi(img):
    W, H = img.size
    return (0, int(H * 0.68), int(W * 0.30), H)


def detect_card(hwnd, idx):
    img = capture(hwnd, os.path.join(SHOT_DIR, "card_%02d.png" % idx))
    x0, y0, x1, y1 = card_roi(img)
    crop = img.crop((x0, y0, x1, y1))
    words = ocr(crop, name="card", scale=2.0)
    txt = joined_text(words)
    btn = find_seq(words, CLAIM_TEXT)
    # 标题是「每日可领100积分」却没检测到按钮 → 用灰度增强再试一次，
    # 避免因 OCR 质量问题把「还该领」误判成「已领」。
    if not btn and ((TITLE_HINT_A in txt) or (TITLE_HINT_B in txt)):
        words2 = ocr(crop, name="card_g", scale=3.0, gray=True)
        txt2 = joined_text(words2)
        btn2 = find_seq(words2, CLAIM_TEXT)
        if btn2:
            words, txt, btn = words2, txt2, btn2
        elif txt2:
            txt = txt2
    if btn:
        btn = {"cx": btn["cx"] + x0, "cy": btn["cy"] + y0, "w": btn["w"], "h": btn["h"]}
    return txt, btn, img.size, (x0, y0)


def close_overlays(hwnd, tries=3):
    """按 ESC 关掉账号面板/子菜单等弹层。

    真实踩到的坑：面板停在「外观/意见反馈/退出登录」子菜单时，既读不到
    「积分余额」，又遮住加油站卡片，会被误判成「今日已领」→ 静默漏领。
    """
    closed = False
    for i in range(tries):
        img = capture(hwnd)
        W, H = img.size
        roi = img.crop((0, int(H * 0.10), int(W * 0.40), H))
        txt = joined_text(ocr(roi, name="ovl_%d" % i, scale=2.0))
        if not looks_like_overlay(txt):
            if i == 0:
                return False
            break
        log("检测到弹层，按 ESC 关闭（第%d次）: %s" % (i + 1, txt[:40]))
        press_esc()
        time.sleep(0.7)
        closed = True
    return closed


def prune_shots(days=7):
    """清理 7 天前的截图，避免目录无限增长。"""
    try:
        cutoff = time.time() - days * 86400
        for fn in os.listdir(SHOT_DIR):
            p = os.path.join(SHOT_DIR, fn)
            if os.path.isfile(p) and os.path.getmtime(p) < cutoff:
                os.remove(p)
    except Exception:
        pass


def acquire_single_instance():
    """防止两个实例同时点头像/点按钮互相干扰。"""
    try:
        k32 = ctypes.windll.kernel32
        k32.SetLastError(0)
        h = k32.CreateMutexW(None, False, "Local\\WorkBuddyDailyCreditClaim")
        if k32.GetLastError() == 183:  # ERROR_ALREADY_EXISTS
            return None
        return h or True
    except Exception:
        return True


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--dry", action="store_true", help="只检测不点击")
    ap.add_argument("--balance", action="store_true", help="只读余额")
    ap.add_argument("--tries", type=int, default=14, help="轮播检测次数")
    ap.add_argument("--interval", type=float, default=2.0, help="检测间隔秒")
    args = ap.parse_args()

    os.makedirs(SHOT_DIR, exist_ok=True)
    os.makedirs(TMP_DIR, exist_ok=True)
    prune_shots()
    log("=" * 56)
    log("开始执行（dry=%s balance_only=%s）" % (args.dry, args.balance))
    if acquire_single_instance() is None:
        log("已有另一个领取实例在运行，本次退出")
        return 0

    hwnd = ensure_window()
    if not hwnd:
        write_state(ok=False, error="no_window", ts=datetime.now().isoformat(timespec="seconds"))
        return 2
    log("窗口句柄 %s 矩形 %s" % (hwnd, get_rect(hwnd)))

    if not focus(hwnd):
        log("警告：置前可能失败（前台窗口被抢占），继续尝试截图/点击")
    time.sleep(0.6)

    bal_before, raw_before, _ = read_balance(hwnd, tag="before")
    log("领前余额: %s (raw=%s)" % (bal_before, raw_before))
    if args.balance:
        write_state(ok=True, mode="balance", balance=bal_before, ts=datetime.now().isoformat(timespec="seconds"))
        return 0

    time.sleep(0.8)
    focus(hwnd)

    # 开局先清掉可能残留的弹层（上次异常退出会留下账号面板挡住卡片）
    close_overlays(hwnd)

    clicked = False
    after_gone = False
    seen = []
    title_seen = 0
    for i in range(args.tries):
        txt, btn, size, off = detect_card(hwnd, i)
        seen.append(txt[:40])
        hit_title = (TITLE_HINT_A in txt) or (TITLE_HINT_B in txt) or (CLAIM_TEXT in txt)
        if hit_title:
            title_seen += 1
        log("第%d次检测: 按钮=%s 标题命中=%s 文本=%s" %
            (i + 1, "立即领取" if btn else "-", hit_title, txt.replace("\n", " ")[:60]))
        if btn and (hit_title or True):
            if args.dry:
                log("dry 模式：检测到「立即领取」，不点击，位置图内 (%.0f,%.0f)" % (btn["cx"], btn["cy"]))
                return 0
            rect = get_rect(hwnd)
            sx, sy = rect[0] + btn["cx"], rect[1] + btn["cy"]
            if not focus(hwnd):
                log("警告：点击前置前失败")
            log("点击「立即领取」屏幕坐标 (%d,%d)" % (sx, sy))
            click(sx, sy)
            clicked = True
            time.sleep(1.6)
            txt2, btn2, _, _ = detect_card(hwnd, 99)
            after_gone = btn2 is None
            log("点击后卡片文本=%s 按钮=%s" % (txt2.replace("\n", " ")[:60], "已消失" if after_gone else "仍在"))
            break
        # 没检测到按钮，且画面看着像被弹层挡住 → 清弹层后继续下一轮（避免误判已领）
        if looks_like_overlay(txt):
            log("卡片区被弹层遮挡，清理后重试")
            close_overlays(hwnd)
            continue
        time.sleep(args.interval)

    status = "unknown"
    bal_after, raw_after = None, None
    if clicked:
        time.sleep(1.0)
        focus(hwnd)
        bal_after, raw_after, _ = read_balance(hwnd, tag="after")
        delta = None
        if bal_before is not None and bal_after is not None:
            delta = round(bal_after - bal_before, 2)
            log("领后余额: %s，差值 %+.2f" % (bal_after, delta))
        else:
            log("领后余额读取失败（before=%s after=%s）" % (bal_before, bal_after))
        # 主判据：点击后「立即领取」按钮消失；余额差值作为佐证
        if after_gone:
            status = "claimed"
        elif delta is not None and delta >= 99:
            status = "claimed"
        else:
            status = "claimed_unverified"
        log("判定依据: 按钮消失=%s 余额差值=%s → %s" % (after_gone, delta, status))
    else:
        # 关键：出现过「每日可领100积分」却没能点下去，不能算「已领」，否则会静默漏领
        if title_seen > 0:
            status = "need_manual"
            log("检测到 %d 次可领卡片但按钮未能定位 → 状态 need_manual（不算已领）" % title_seen)
        else:
            status = "already_claimed"
            log("整轮检测未出现「立即领取」→ 判定今日已领取")

    write_state(ok=True, status=status, clicked=clicked, balance_before=bal_before,
                balance_after=bal_after, ts=datetime.now().isoformat(timespec="seconds"),
                samples=seen[-6:])
    log("结束，状态=%s" % status)
    return 0


if __name__ == "__main__":
    sys.exit(main())
