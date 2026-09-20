# /// script
# requires-python = ">=3.11"
# dependencies = []
# ///
"""一站式应用自定义短语：改文件 + 驱动设置页「导入」+ 回读验证，无需人工介入。

用法:
    uv run apply_phrases.py <tsv>            # 用 TSV 全量替换词库并导入
    uv run apply_phrases.py --append <tsv>   # 保留现有短语，追加 TSV 中的条目

## 为什么不能只改文件

输入法在启动时读取 ChsPinyinEUDPv1.lex 并缓存，运行期间不重读。
实测：直接写入文件后，设置页列表纹丝不动，打字也不生效。
必须经设置页「导入」通道加载 —— 本脚本把这一步也自动化了。

## 自动化流程

1. 用 msudp 生成目标词库文件（全量，避免导入语义不确定）
2. 确保「设置 > 时间和语言 > 语言和区域 > 用户自定义短语」页已打开并滚动到列表
3. UIAutomation 点击「导入」→ 在文件名框填入路径 → 点「打开(O)」
4. 回读设置页列表，与实际条数比对，作为成功判据
"""

from __future__ import annotations

import importlib.util
import subprocess
import sys
import time
from pathlib import Path

HERE = Path(__file__).parent
spec = importlib.util.spec_from_file_location("msudp", HERE / "msudp.py")
msudp = importlib.util.module_from_spec(spec)
sys.modules["msudp"] = msudp
spec.loader.exec_module(msudp)

SETTINGS_TITLE = "设置"
LIST_LIMIT = 400

# 直达「用户自定义短语」页的 URI。取自社区整理的 Windows 11 设置 URI 手册：
#   https://aky.moe/Windows实用手册/Windows11设置URI/
# 同组的其它拼音设置页：-chsime-pinyin（设置主页）、-domainlexicon（词库和自学习）、
#   -keyconfig（按键）
PHRASES_URI = "ms-settings:regionlanguage-chsime-pinyin-udp"


def _ps(script: str) -> str:
    """执行一段 PowerShell 并返回 stdout。"""
    r = subprocess.run(["pwsh", "-NoProfile", "-NonInteractive", "-Command", script],
                       capture_output=True, text=True, timeout=180)
    if r.returncode != 0 and r.stderr.strip():
        print(f"  [pwsh stderr] {r.stderr.strip()[:300]}")
    return r.stdout


_PS_HEAD = """
Add-Type -AssemblyName UIAutomationClient, UIAutomationTypes
$root = [System.Windows.Automation.AutomationElement]::RootElement
$cond = New-Object System.Windows.Automation.PropertyCondition(
  [System.Windows.Automation.AutomationElement]::NameProperty, '%s')
$win = $root.FindFirst([System.Windows.Automation.TreeScope]::Children, $cond)
""" % SETTINGS_TITLE


def settings_open() -> bool:
    """设置窗口是否已打开。"""
    return "NO_WINDOW" not in _ps(_PS_HEAD + 'if ($win) { "OK" } else { "NO_WINDOW" }')


def close_settings() -> None:
    """关闭设置窗口（URI 导航对已存在的窗口无效，需先关闭）。"""
    _ps(_PS_HEAD + """
if ($win) {
  try { $win.GetCurrentPattern([System.Windows.Automation.WindowPattern]::Pattern).Close() } catch {}
}
"CLOSED"
""")
    for _ in range(10):
        time.sleep(1)
        if not settings_open():
            return
    raise SystemExit("设置窗口无法关闭")


def open_settings() -> None:
    """用直达 URI 打开「用户自定义短语」页并等待加载。"""
    _ps(f"Start-Process '{PHRASES_URI}'")
    for _ in range(25):
        time.sleep(1)
        if settings_open() and has_import_button():
            return
    raise SystemExit(
        f"未能打开短语页（URI: {PHRASES_URI}）。\n"
        "若设置窗口已打开但停在别的页面，请先关闭它再重试。")


def has_import_button() -> bool:
    """设置窗口内是否存在「导入」按钮（即已停在短语页）。"""
    out = _ps(_PS_HEAD + """
$c = New-Object System.Windows.Automation.AndCondition(
  (New-Object System.Windows.Automation.PropertyCondition(
    [System.Windows.Automation.AutomationElement]::ControlTypeProperty,
    [System.Windows.Automation.ControlType]::Button)),
  (New-Object System.Windows.Automation.PropertyCondition(
    [System.Windows.Automation.AutomationElement]::NameProperty, '导入')))
if ($win.FindFirst([System.Windows.Automation.TreeScope]::Descendants, $c)) { "YES" } else { "NO" }
""")
    return "YES" in out


def read_list() -> list[str]:
    """读取设置页当前显示的短语列表。"""
    out = _ps(_PS_HEAD + """
$all = $win.FindAll([System.Windows.Automation.TreeScope]::Descendants,
  [System.Windows.Automation.Condition]::TrueCondition)
$items = @()
foreach ($e in $all) {
  if ($e.Current.ControlType.ProgrammaticName -eq 'ControlType.ListItem') {
    $n = $e.Current.Name
    if ($n -match '^拼音:') { $items += $n }
  }
}
"COUNT=$($items.Count)"
$items | Select-Object -First %d | ForEach-Object { "ITEM=$_" }
""" % LIST_LIMIT)
    if "NO_WINDOW" in out:
        raise SystemExit("设置窗口未打开")
    return [ln[5:] for ln in out.splitlines() if ln.startswith("ITEM=")]


def click_import(path: Path) -> None:
    """点「导入」并在文件对话框中选定路径。"""
    out = _ps(_PS_HEAD + """
$btnCond = New-Object System.Windows.Automation.AndCondition(
  (New-Object System.Windows.Automation.PropertyCondition(
    [System.Windows.Automation.AutomationElement]::ControlTypeProperty,
    [System.Windows.Automation.ControlType]::Button)),
  (New-Object System.Windows.Automation.PropertyCondition(
    [System.Windows.Automation.AutomationElement]::NameProperty, '导入')))
$btn = $win.FindFirst([System.Windows.Automation.TreeScope]::Descendants, $btnCond)
if (-not $btn) { "NO_BUTTON"; exit }
$btn.GetCurrentPattern([System.Windows.Automation.InvokePattern]::Pattern).Invoke()
"CLICKED"
""")
    if "NO_BUTTON" in out:
        raise SystemExit("未找到「导入」按钮，确认设置页停在「用户自定义短语」")
    time.sleep(2.5)

    # 文件对话框嵌在设置窗口内部
    out = _ps(_PS_HEAD + """
$editCond = New-Object System.Windows.Automation.AndCondition(
  (New-Object System.Windows.Automation.PropertyCondition(
    [System.Windows.Automation.AutomationElement]::ControlTypeProperty,
    [System.Windows.Automation.ControlType]::Edit)),
  (New-Object System.Windows.Automation.PropertyCondition(
    [System.Windows.Automation.AutomationElement]::NameProperty, '文件名(N):')))
$edit = $win.FindFirst([System.Windows.Automation.TreeScope]::Descendants, $editCond)
if (-not $edit) { "NO_EDIT"; exit }
$edit.GetCurrentPattern([System.Windows.Automation.ValuePattern]::Pattern).SetValue('%s')
Start-Sleep -Milliseconds 700
$openCond = New-Object System.Windows.Automation.AndCondition(
  (New-Object System.Windows.Automation.PropertyCondition(
    [System.Windows.Automation.AutomationElement]::ControlTypeProperty,
    [System.Windows.Automation.ControlType]::Button)),
  (New-Object System.Windows.Automation.PropertyCondition(
    [System.Windows.Automation.AutomationElement]::NameProperty, '打开(O)')))
$openBtn = $win.FindFirst([System.Windows.Automation.TreeScope]::Descendants, $openCond)
if (-not $openBtn) { "NO_OPEN"; exit }
$openBtn.GetCurrentPattern([System.Windows.Automation.InvokePattern]::Pattern).Invoke()
"OPENED"
""" % str(path))
    if "NO_EDIT" in out:
        raise SystemExit("导入对话框未出现（未找到文件名输入框）")
    if "NO_OPEN" in out:
        raise SystemExit("未找到「打开(O)」按钮")
    time.sleep(4)


def main() -> None:
    argv = sys.argv[1:]
    append = "--append" in argv
    argv = [a for a in argv if a != "--append"]
    if not argv:
        raise SystemExit(__doc__)
    tsv = Path(argv[0])
    lex = msudp.default_lex()

    new, errs = msudp.parse_tsv(tsv.read_text(encoding="utf-8"))
    for e in errs:
        print(f"  跳过：{e}")
    if not new:
        raise SystemExit("TSV 中没有可用的短语")

    meta, existing = msudp.read(lex)
    if append:
        recs, dropped = msudp.merge(existing, new)
        print(f"[1] 追加模式：现有 {len(existing)} 条 + 新增 {len(new)} 条"
              f"（覆盖 {dropped}）= {len(recs)} 条")
    else:
        recs = new
        print(f"[1] 全量替换：{len(existing)} 条 -> {len(new)} 条")

    out = Path.home() / "Downloads" / "msudp_apply.dat"
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_bytes(msudp.build(meta, recs))
    print(f"[2] 已生成导入文件：{out}  ({out.stat().st_size}B)")

    if has_import_button():
        print("[3] 设置窗口已停在「用户自定义短语」页，直接复用")
    else:
        if settings_open():
            # 已开在别的页面时, ms-settings URI 不会导航, 必须先关闭
            print("[3] 设置窗口停在其它页面，关闭后重新直达目标页")
            close_settings()
        else:
            print("[3] 设置窗口未打开，正在直达目标页")
        open_settings()
        print(f"    已就绪（{PHRASES_URI}）")

    print("[4] 驱动设置页「导入」...")
    click_import(out)

    print("[5] 回读设置页验证...")
    items = read_list()
    print(f"    设置页现有 {len(items)} 条")
    for it in items[:8]:
        print(f"      {it}")
    if len(items) > 8:
        print(f"      ...（共 {len(items)} 条）")

    ok = len(items) == len(recs)
    print()
    if ok:
        print(f"==> 成功：设置页条数 {len(items)} 与目标 {len(recs)} 一致")
        print("    提示：切换一次输入法（Win+Space）后即可打字测试")
    else:
        print(f"==> 不一致：设置页 {len(items)} 条，目标 {len(recs)} 条")
        raise SystemExit(1)


if __name__ == "__main__":
    main()
