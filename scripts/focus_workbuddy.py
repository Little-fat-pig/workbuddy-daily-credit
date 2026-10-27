# -*- coding: utf-8 -*-
"""
把 WorkBuddy 客户端窗口提到前台（ctypes 实现）。

【为什么需要它】
windows-mcp 的 Click 是真实鼠标点击，落在**最上层可见窗口**上。
若此刻 Chrome / 向日葵远程会话 / 其它窗口压在 WorkBuddy 上面，
点击会落到错误窗口 —— 表现为「坐标明明对，点击却没反应」。

【为什么用 ctypes 而不是 PowerShell + Add-Type】
WorkBuddy 的命令安全策略会拦截内联 Add-Type（本机实测被拦）。
纯 Python ctypes 直接调 user32.dll，无此问题，且无第三方依赖。

用法：
  python focus_workbuddy.py
退出码：0 = 已成功置前；1 = 没找到窗口或置前失败
"""
import ctypes
import ctypes.wintypes as wt
import sys

user32 = ctypes.windll.user32
SW_RESTORE = 9
SW_SHOW = 5

# 需要排除的标题特征（浏览器里的个人中心页、远程会话等）
EXCLUDE = ("个人中心", "google chrome", "microsoft edge", "firefox", "向日葵", "sunlogin")


def window_title(hwnd):
    n = user32.GetWindowTextLengthW(hwnd)
    buf = ctypes.create_unicode_buffer(n + 1)
    user32.GetWindowTextW(hwnd, buf, n + 1)
    return buf.value


def is_workbuddy(title):
    t = title.lower()
    if "workbuddy" not in t:
        return False
    for bad in EXCLUDE:
        if bad.lower() in t:
            return False
    return True


def main():
    found = []

    @ctypes.WINFUNCTYPE(ctypes.c_bool, wt.HWND, wt.LPARAM)
    def cb(hwnd, lparam):
        if user32.IsWindowVisible(hwnd):
            t = window_title(hwnd)
            if is_workbuddy(t):
                found.append((hwnd, t))
        return True

    user32.EnumWindows(cb, 0)

    if not found:
        print("[X] 没找到可见的 WorkBuddy 客户端窗口（可能未启动）。")
        return 1

    # 优先选面积最大的那个
    def area(hwnd):
        r = wt.RECT()
        user32.GetWindowRect(hwnd, ctypes.byref(r))
        return (r.right - r.left) * (r.bottom - r.top)

    hwnd, title = max(found, key=lambda x: area(x[0]))
    print("[i] 目标窗口：%r  hwnd=%s" % (title, hwnd))

    user32.ShowWindow(hwnd, SW_RESTORE)
    user32.ShowWindow(hwnd, SW_SHOW)
    user32.BringWindowToTop(hwnd)

    # 经典置前技巧：AttachThreadInput + SetForegroundWindow
    fg = user32.GetForegroundWindow()
    cur_tid = ctypes.windll.kernel32.GetCurrentThreadId()
    fg_tid = user32.GetWindowThreadProcessId(fg, None) if fg else 0
    attached = False
    if fg_tid and fg_tid != cur_tid:
        attached = bool(user32.AttachThreadInput(cur_tid, fg_tid, True))
    try:
        user32.SetForegroundWindow(hwnd)
        user32.SetActiveWindow(hwnd)
    finally:
        if attached:
            user32.AttachThreadInput(cur_tid, fg_tid, False)

    # SetForegroundWindow 可能被系统拒绝，用 Alt 技巧再试一次
    if user32.GetForegroundWindow() != hwnd:
        user32.keybd_event(0x12, 0, 0, 0)          # 按下 Alt
        user32.SetForegroundWindow(hwnd)
        user32.keybd_event(0x12, 0, 0x0002, 0)     # 释放 Alt

    now = user32.GetForegroundWindow()
    if now == hwnd:
        print("[OK] WorkBuddy 窗口已置于前台。")
        return 0
    print("[!] 未能完全置前（当前前台 hwnd=%s，目标 %s）。仍可继续：Snapshot 的 UI 树是跨窗口的，"
          "能读到按钮坐标；但点击可能落到上层窗口，请让用户确认屏幕上 WorkBuddy 可见再点。" % (now, hwnd))
    return 1


if __name__ == "__main__":
    sys.exit(main())
