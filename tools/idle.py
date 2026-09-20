# /// script
# requires-python = ">=3.11"
# dependencies = []
# ///
"""检测用户键鼠空闲时长（Windows GetLastInputInfo）。

脚本用它等待用户停手后再执行会抢焦点的 GUI 操作，避免打断用户输入。
"""

import ctypes
import sys
import time
from ctypes import wintypes


class LASTINPUTINFO(ctypes.Structure):
    """GetLastInputInfo 所需结构。"""

    _fields_ = [("cbSize", wintypes.UINT), ("dwTime", wintypes.DWORD)]


_user32 = ctypes.WinDLL("user32", use_last_error=True)
_kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
_user32.GetLastInputInfo.argtypes = [ctypes.POINTER(LASTINPUTINFO)]
_user32.GetLastInputInfo.restype = wintypes.BOOL
_kernel32.GetTickCount.restype = wintypes.DWORD


def idle_seconds() -> float:
    """自上次键鼠输入以来的秒数。"""
    info = LASTINPUTINFO()
    info.cbSize = ctypes.sizeof(LASTINPUTINFO)
    if not _user32.GetLastInputInfo(ctypes.byref(info)):
        raise OSError(f"GetLastInputInfo 失败: {ctypes.get_last_error()}")
    return (_kernel32.GetTickCount() - info.dwTime) / 1000.0


def wait_idle(threshold: float = 2.0, timeout: float = 90.0) -> float:
    """等到用户空闲达到 threshold 秒；返回最终空闲时长。

    超过 timeout 仍未空闲则放弃等待（返回当前空闲时长）。
    """
    deadline = time.monotonic() + timeout
    last_report = -1
    while time.monotonic() < deadline:
        cur = idle_seconds()
        if cur >= threshold:
            return cur
        whole = int(cur)
        if whole != last_report:
            last_report = whole
            print(f"    用户正在操作（已空闲 {cur:.1f}s），等待…", flush=True)
        time.sleep(0.2)
    return idle_seconds()


if __name__ == "__main__":
    if len(sys.argv) > 1 and sys.argv[1] == "watch":
        print("实时空闲时长（Ctrl+C 结束）:")
        while True:
            print(f"  {idle_seconds():6.2f}s", end="\r")
            time.sleep(0.3)
    else:
        print(f"当前空闲: {idle_seconds():.2f}s")
        print("演示: 等待空闲 3 秒（请勿触碰键鼠）…")
        got = wait_idle(3.0, timeout=30.0)
        print(f"已达到 {got:.2f}s 空闲")
