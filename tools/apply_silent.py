# /// script
# requires-python = ">=3.11"
# dependencies = []
# ///
"""全自动应用自定义短语（无 GUI 版）。

用法:
    uv run apply_silent.py <tsv> [--append]               # 从 TSV 文件读
    uv run apply_silent.py --stdin [--append]             # 从标准输入读
    uv run apply_silent.py --add <拼音>:<位>:<文本> [...]  # 直接给短语

`--append` 保留现有短语；默认全量替换。

示例（不落任何文件）:

    uv run tools/apply_silent.py --add aa:1:α --append
    echo "aa`t1`tα" | uv run tools/apply_silent.py --stdin

## 原理

实测结论（以「用户实际打字能否打出新短语」为判据，而非设置页显示）：

| 手段                          | 是否生效 |
|-------------------------------|----------|
| 直接改 .lex 文件               | 否       |
| 切换输入法 (Win+Space)         | 否       |
| 杀掉 ChsIME 进程               | 部分（多字母/已学过的词可能碰巧生效） |
| 杀掉 TextInputHost + ChsIME，再 Win+Space 切走切回 | **是** |
| 设置页「导入」按钮             | 是（不杀进程，走官方通知） |

实测：设置页导入后 ChsIME PID 不变，三条全部生效。
只杀 ChsIME 时 `p`/`t` 能出词、`i` 不能 —— `屁股`/`剔骨` 已写入
`ChsPinyinIH.dat`（会话历史），`i人` 没有。真正读 EUDP 的是
候选宿主 TextInputHost，必须一起重启。

杀进程后词库已在磁盘上，但前台会话仍可能握着旧候选缓存；
脚本会再发 Win+Space 切走再切回，让新 IME 绑到当前窗口。

## 与 apply_phrases.py 的区别

apply_phrases.py 走 GUI 导入（会弹设置窗口，可能打断用户）；
本脚本纯文件 + 杀进程，**零窗口、零焦点抢占**。
"""

from __future__ import annotations

import ctypes
import importlib.util
import subprocess
import sys
import time
from ctypes import wintypes
from pathlib import Path

HERE = Path(__file__).parent
_spec = importlib.util.spec_from_file_location("msudp", HERE / "msudp.py")
_m = importlib.util.module_from_spec(_spec)
sys.modules["msudp"] = _m
_spec.loader.exec_module(_m)

import msudp  # noqa: E402

IME_PROCESSES = ("ChsIME", "TextInputHost")
RESTART_TIMEOUT = 10.0
PROCESS_TERMINATE = 0x0001
INPUT_KEYBOARD = 1
KEYEVENTF_KEYUP = 0x0002
VK_LWIN = 0x5B
VK_SPACE = 0x20

_k32 = ctypes.WinDLL("kernel32", use_last_error=True)
_k32.OpenProcess.restype = wintypes.HANDLE
_k32.OpenProcess.argtypes = [wintypes.DWORD, wintypes.BOOL, wintypes.DWORD]
_u32 = ctypes.WinDLL("user32", use_last_error=True)
ULONG_PTR = ctypes.c_size_t


class KEYBDINPUT(ctypes.Structure):
    """SendInput 键盘事件。"""

    _fields_ = [
        ("wVk", wintypes.WORD),
        ("wScan", wintypes.WORD),
        ("dwFlags", wintypes.DWORD),
        ("time", wintypes.DWORD),
        ("dwExtraInfo", ULONG_PTR),
    ]


class MOUSEINPUT(ctypes.Structure):
    """SendInput 联合体对齐用，本脚本不发鼠标事件。"""

    _fields_ = [
        ("dx", wintypes.LONG),
        ("dy", wintypes.LONG),
        ("mouseData", wintypes.DWORD),
        ("dwFlags", wintypes.DWORD),
        ("time", wintypes.DWORD),
        ("dwExtraInfo", ULONG_PTR),
    ]


class INPUT(ctypes.Structure):
    """SendInput 条目。"""

    class _U(ctypes.Union):
        _fields_ = [("ki", KEYBDINPUT), ("mi", MOUSEINPUT)]

    _anonymous_ = ("u",)
    _fields_ = [("type", wintypes.DWORD), ("u", _U)]


_u32.SendInput.argtypes = [wintypes.UINT, ctypes.POINTER(INPUT), ctypes.c_int]
_u32.SendInput.restype = wintypes.UINT


def _key(vk: int, flags: int = 0) -> INPUT:
    """构造一次按键按下或抬起。"""
    inp = INPUT()
    inp.type = INPUT_KEYBOARD
    inp.ki = KEYBDINPUT(vk, 0, flags, 0, 0)
    return inp


def toggle_ime() -> None:
    """Win+Space 切走再切回，让新拉起的 IME 绑到前台会话。

    杀进程后词库已在磁盘上，但当前会话仍可能握着旧候选缓存；
    实测需要主动切换一次输入法才会吃到新短语。切两次回到原布局。
    """
    def chord() -> None:
        seq = (
            _key(VK_LWIN),
            _key(VK_SPACE),
            _key(VK_SPACE, KEYEVENTF_KEYUP),
            _key(VK_LWIN, KEYEVENTF_KEYUP),
        )
        arr = (INPUT * 4)(*seq)
        sent = _u32.SendInput(4, arr, ctypes.sizeof(INPUT))
        if sent != 4:
            print(f"    SendInput 只发出 {sent}/4，win32={ctypes.get_last_error()}")
        time.sleep(0.3)

    chord()
    chord()


def _ps(cmd: str) -> str:
    """执行 PowerShell 片段。

    注意不要用 -ErrorAction SilentlyContinue 包裹关键调用：
    实测 Stop-Process 对 ChsIME 会返回 Access is denied，静默吞掉后
    脚本会误以为操作成功，从而把「没杀掉」误报成「已重启」。
    """
    r = subprocess.run(["powershell", "-NoProfile", "-NonInteractive", "-Command", cmd],
                       capture_output=True, text=True, timeout=60)
    if r.returncode != 0 and r.stderr.strip():
        print(f"    [ps 警告] {r.stderr.strip().splitlines()[0][:160]}")
    return r.stdout.strip()


def ime_state() -> str:
    """当前输入法相关进程的 (名, PID, 启动时间) 快照。

    用启动时间而非 PID 判断重启：Windows 会复用 PID。
    """
    names = ",".join(f"'{n}'" for n in IME_PROCESSES)
    out = _ps(
        f"Get-Process -Name {names} -ErrorAction SilentlyContinue | "
        "ForEach-Object { \"$($_.ProcessName)=$($_.Id)@$($_.StartTime.Ticks)\" }"
    )
    return out.strip()


def ime_pids() -> list[int]:
    """当前 ChsIME 与 TextInputHost 的 PID。"""
    names = ",".join(f"'{n}'" for n in IME_PROCESSES)
    out = _ps(
        f"@(Get-Process -Name {names} -ErrorAction SilentlyContinue | "
        "Select-Object -ExpandProperty Id) -join ','"
    )
    return [int(x) for x in out.split(",") if x.strip().isdigit()]


def kill_pid(pid: int) -> bool:
    """用 Win32 API 强制结束进程。

    必须直接调 API：实测 taskkill 与 Stop-Process 对 ChsIME 都返回
    「Access is denied」，而 OpenProcess(PROCESS_TERMINATE)+TerminateProcess 可行。
    """
    h = _k32.OpenProcess(PROCESS_TERMINATE, False, pid)
    if not h:
        print(f"    OpenProcess({pid}) 失败 win32={ctypes.get_last_error()}")
        return False
    try:
        if not _k32.TerminateProcess(h, 1):
            print(f"    TerminateProcess({pid}) 失败 win32={ctypes.get_last_error()}")
            return False
        return True
    finally:
        _k32.CloseHandle(h)


def restart_ime() -> tuple[str, str, float]:
    """杀掉 ChsIME 与 TextInputHost，等待服务自动拉起。

    只杀 ChsIME 不够：候选窗口在 TextInputHost 里，EUDP 缓存在那里。
    返回 (杀前快照, 重启后快照, 耗时秒)。
    """
    before = ime_state()
    killed = [pid for pid in ime_pids() if kill_pid(pid)]
    if killed:
        print(f"    已结束 PID {killed}")
    t0 = time.monotonic()
    while time.monotonic() - t0 < RESTART_TIMEOUT:
        time.sleep(0.3)
        now = ime_state()
        if now and now != before and all(n in now for n in IME_PROCESSES):
            return before, now, time.monotonic() - t0
    return before, ime_state(), time.monotonic() - t0


def parse_add(items: list[str]) -> tuple[list[msudp.Rec], list[str]]:
    """解析 `拼音:位:文本` 形式的参数。"""
    recs: list[msudp.Rec] = []
    errs: list[str] = []
    for raw in items:
        parts = raw.split(":", 2)
        if len(parts) != 3:
            errs.append(f"{raw!r}：需为 <拼音>:<候选位>:<文本>")
            continue
        pinyin, pos, text = parts[0].strip(), parts[1].strip(), parts[2]
        if not pos.isdigit():
            errs.append(f"{raw!r}：候选位须为数字")
            continue
        rec = msudp.Rec(pinyin=pinyin, index=int(pos), text=text)
        if (e := msudp.check(rec)) is not None:
            errs.append(f"{raw!r}：{e}")
            continue
        recs.append(rec)
    return recs, errs


USAGE = """用法:
  apply_silent.py <tsv> [--append]                 从 TSV 文件读
  apply_silent.py --stdin [--append]               从标准输入读 TSV
  apply_silent.py --add <拼音>:<位>:<文本> [...]    直接给短语

选项:
  --append     保留现有短语（默认全量替换）

示例（不落任何文件）:
  uv run tools/apply_silent.py --add aa:1:α --append
  "aa`t1`tα" | uv run tools/apply_silent.py --stdin --append
"""


def parse_input(argv: list[str]) -> tuple[list[msudp.Rec], list[str]]:
    """按参数形式取得待写入的记录（支持文件 / stdin / 直接参数）。"""
    if "--add" in argv:
        items = argv[argv.index("--add") + 1:]
        if not items or items[0].startswith("--"):
            raise SystemExit(f"--add 缺少参数\n\n{USAGE}")
        return parse_add(items)
    if "--stdin" in argv:
        # 显式按 UTF-8 解码, 避免 PowerShell 管道下中文与符号乱码
        text = sys.stdin.buffer.read().decode("utf-8")
        if not text.strip():
            raise SystemExit("标准输入为空")
        return msudp.parse_tsv(text)
    files = [a for a in argv if not a.startswith("--")]
    if not files:
        raise SystemExit(USAGE)
    return msudp.parse_tsv(Path(files[0]).read_text(encoding="utf-8"))


def main() -> None:
    argv = sys.argv[1:]
    append = "--append" in argv
    argv = [a for a in argv if a != "--append"]
    if not argv:
        raise SystemExit(USAGE)
    lex = msudp.default_lex()

    new, errs = parse_input(argv)
    for e in errs:
        print(f"  跳过：{e}")
    if not new:
        raise SystemExit("没有可用的短语")

    meta, existing = msudp.read(lex)
    # GUI 导入会给整批记录写同一份 unknown8；新记录沿用现有文件里的值，
    # 避免默认 00 00 00 00 96 0a 99 20 与当前会话标识不一致。
    learned = next((r.unknown8 for r in existing if r.unknown8), msudp.DEFAULT_UNKNOWN8)
    new = [msudp.Rec(pinyin=r.pinyin, index=r.index, text=r.text,
                     candidate2=r.candidate2, unknown8=learned) for r in new]
    if append:
        recs, dropped = msudp.merge(existing, new)
        print(f"[1] 追加：现有 {len(existing)} 条 + 新增 {len(new)} 条"
              f"（覆盖 {dropped}）= {len(recs)} 条")
    else:
        recs = new
        print(f"[1] 替换：{len(existing)} 条 -> {len(new)} 条")

    lex.write_bytes(msudp.build(meta, recs))
    print(f"[3] 已写入词库：{len(recs)} 条，{lex.stat().st_size}B")

    print(f"[4] 重启输入法进程使其重载...")
    before, after, cost = restart_ime()
    print(f"    杀前 {before}  ->  重启后 {after}   耗时 {cost:.1f}s")
    if not after:
        print("    ⚠ 进程未自动重启，请手动切换一次输入法")
    elif after == before:
        print("    ⚠ 快照未变化，进程可能未真正重启（输入法可能不会重载）")

    print("[5] 切换输入法（Win+Space ×2）使前台会话重绑...")
    time.sleep(0.4)
    toggle_ime()

    time.sleep(0.6)
    _, back = msudp.read(lex)
    ok = len(back) == len(recs)
    print(f"[6] 回读校验：{len(back)} 条，{'一致' if ok else '不一致'}")
    print()
    if ok:
        print("==> 完成。可直接打字验证")
        for r in back[-min(3, len(back)):]:
            print(f"    {r.pinyin} -> {r.text}（位置 {r.index}）")
    else:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
