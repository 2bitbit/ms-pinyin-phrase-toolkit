# /// script
# requires-python = ">=3.11"
# dependencies = []
# ///
"""微软拼音自定义短语文件 (mschxudp) 读写工具。

支持 Windows 10/11「中文(简体) - 微软拼音」的用户自定义短语文件：

    %APPDATA%\\Microsoft\\InputMethod\\Chs\\ChsPinyinEUDPv1.lex

同一格式也用于系统设置里「时间和语言 > 语言和区域 > 用户自定义短语」
的「导出」产物（默认文件名 UserDefinedPhrase.dat），因此本工具生成的
文件可以直接用该页面的「导入」按钮加载。

## 命令行

    list      [文件]            列出短语（含候选位、candidate2）
    dump      [文件]            导出为 TSV：拼音 <TAB> 位置 <TAB> 文本
    import    <tsv> [--lex 文件]  从 TSV 导入（同拼音同位置覆盖），写前自动备份
    roundtrip [文件]            读入再重建并与原文逐字节比对（格式自检）

省略文件参数时使用当前用户的默认词库路径。

## 文件格式

   偏移   长度  含义
   0x00   8     proto "mschxudp"
   0x08   4     unknown        0x00600002
   0x0C   4     version        1
   0x10   4     phrase_offset_start   恒为 0x40
   0x14   4     phrase_start          0x40 + 4 * phrase_count
   0x18   4     phrase_end            文件总长度
   0x1C   4     phrase_count          记录条数
   0x20   4     timestamp             Unix 时间戳
   0x24   28    保留（全 0）

   0x40         phrase_offsets[]: u32 * phrase_count
                第 0 项恒为 0，第 N 项 = 第 N 条记录相对 phrase_start 的偏移

记录区（phrase_start 起），每条记录：

   16 字节头：
     0..3   magic         10 00 10 00
     4..5   offset        0x10 + len(pinyin_utf16)
     6      candidate     候选框位置 1..9
     7      candidate2    实测恒为 6
     8..15  unknown8      输入法内部标识，原样保留
   pinyin    UTF-16LE，以 0x0000 结尾
   phrase    UTF-16LE，以 0x0000 结尾

不变式：

    phrase_offset_start + 4 * phrase_count == phrase_start
    phrase_offsets[N] + offset + len(phrase) == phrase_offsets[N+1]
    phrase_start + phrase_offsets[N] == 第 N 条记录的起点

格式交叉验证来源：https://github.com/youmuyou/mschxudp
"""

from __future__ import annotations

import os
import shutil
import struct
import sys
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

PROTO = b"mschxudp"
OFF_UNKNOWN = 0x08
OFF_VERSION = 0x0C
OFF_PHRASE_OFFSET_START = 0x10
OFF_PHRASE_START = 0x14
OFF_PHRASE_END = 0x18
OFF_PHRASE_COUNT = 0x1C
OFF_TIMESTAMP = 0x20
PHRASE_OFFSET_START = 0x40
MAGIC = 0x00100010
UNKNOWN_HDR = 0x00600002
VERSION = 1
REC_HEAD = 16
DEFAULT_CAND2 = 6
DEFAULT_UNKNOWN8 = bytes.fromhex("00000000960a9920")
MAX_PINYIN = 32
MAX_PHRASE = 64


@dataclass(frozen=True)
class Rec:
    """一条自定义短语。

    pinyin     触发码（只含 a-z，微软拼音不区分大小写）
    index      候选框位置 1..9，对应 UI 上的「位置」
    text       上屏文本
    candidate2 记录头第 7 字节，实测恒为 6
    unknown8   记录头 8..15 字节，输入法内部标识，原样保留
    """

    pinyin: str
    index: int
    text: str
    candidate2: int = DEFAULT_CAND2
    unknown8: bytes = DEFAULT_UNKNOWN8


def _u32(buf: bytes, off: int) -> int:
    """读取小端 u32。"""
    return struct.unpack_from("<I", buf, off)[0]


def default_lex() -> Path:
    """当前用户的微软拼音自定义短语文件路径。"""
    return (Path(os.environ["APPDATA"]) / "Microsoft" / "InputMethod" / "Chs"
            / "ChsPinyinEUDPv1.lex")


def _utf16z(s: str) -> bytes:
    """UTF-16LE 编码并追加结尾 0x0000。"""
    return s.encode("utf-16-le") + b"\x00\x00"


def _decode_utf16z(raw: bytes) -> str:
    """解码 UTF-16LE 并去掉结尾空字符。"""
    return raw.decode("utf-16-le").rstrip("\x00")


def read(path: Path) -> tuple[dict, list[Rec]]:
    """读取词库文件，返回 (头部信息, 记录列表)。"""
    buf = Path(path).read_bytes()
    if buf[:8] != PROTO:
        raise ValueError(f"proto 不匹配，非 mschxudp 文件: {buf[:8]!r}")

    off_start = _u32(buf, OFF_PHRASE_OFFSET_START)
    start = _u32(buf, OFF_PHRASE_START)
    end = _u32(buf, OFF_PHRASE_END)
    count = _u32(buf, OFF_PHRASE_COUNT)
    if off_start + 4 * count != start:
        raise ValueError(
            f"头部不自洽: phrase_offset_start({off_start:#x}) + "
            f"4*count({count}) != phrase_start({start:#x})")
    if end > len(buf):
        raise ValueError(f"phrase_end({end:#x}) 超出文件长度({len(buf):#x})")

    offsets = [_u32(buf, off_start + i * 4) for i in range(count)]
    offsets.append(end - start)

    recs: list[Rec] = []
    for i in range(count):
        base = start + offsets[i]
        seg_end = start + offsets[i + 1]
        if not start <= base < seg_end <= len(buf):
            raise ValueError(f"记录 {i} 区间非法: {base:#x}..{seg_end:#x}")
        magic, off, cand, cand2 = struct.unpack_from("<IHBB", buf, base)
        if magic != MAGIC:
            raise ValueError(f"记录 {i} magic 异常: {magic:#010x}")
        if not REC_HEAD <= off <= seg_end - base:
            raise ValueError(f"记录 {i} offset 字段非法: {off}")
        # 拼音紧随 16 字节头部；offset 指向短语数据起点
        pinyin = _decode_utf16z(buf[base + REC_HEAD:base + off])
        text = _decode_utf16z(buf[base + off:seg_end])
        if not pinyin or not text:
            raise ValueError(f"记录 {i} 拼音或短语为空")
        recs.append(Rec(pinyin=pinyin, index=cand, text=text,
                        candidate2=cand2, unknown8=buf[base + 8:base + 16]))

    meta = {
        "raw": buf,
        "count": count,
        "timestamp": _u32(buf, OFF_TIMESTAMP),
        "unknown": _u32(buf, OFF_UNKNOWN),
        "version": _u32(buf, OFF_VERSION),
    }
    return meta, recs


def build(meta: dict, recs: list[Rec]) -> bytes:
    """按记录列表重建完整文件字节。"""
    count = len(recs)
    start = PHRASE_OFFSET_START + 4 * count

    body = bytearray()
    offsets: list[int] = []
    for r in recs:
        py = _utf16z(r.pinyin)
        tx = _utf16z(r.text)
        offsets.append(len(body))
        head = struct.pack("<IHBB", MAGIC, REC_HEAD + len(py),
                           r.index, r.candidate2)
        unk = (r.unknown8 or DEFAULT_UNKNOWN8)[:8].ljust(8, b"\x00")
        body += head + unk + py + tx
    end = start + len(body)

    out = bytearray(start)
    out[0:8] = PROTO
    struct.pack_into("<I", out, OFF_UNKNOWN, meta.get("unknown", UNKNOWN_HDR))
    struct.pack_into("<I", out, OFF_VERSION, meta.get("version", VERSION))
    struct.pack_into("<I", out, OFF_PHRASE_OFFSET_START, PHRASE_OFFSET_START)
    struct.pack_into("<I", out, OFF_PHRASE_START, start)
    struct.pack_into("<I", out, OFF_PHRASE_END, end)
    struct.pack_into("<I", out, OFF_PHRASE_COUNT, count)
    struct.pack_into("<I", out, OFF_TIMESTAMP, meta.get("timestamp", 0))
    for i, o in enumerate(offsets):
        struct.pack_into("<I", out, PHRASE_OFFSET_START + i * 4, o)
    out += body
    return bytes(out)


def check(r: Rec) -> str | None:
    """校验一条短语是否符合微软输入法的录入限制，返回错误说明或 None。"""
    if not r.pinyin:
        return "拼音为空"
    if len(r.pinyin) > MAX_PINYIN:
        return f"拼音超长 {len(r.pinyin)} > {MAX_PINYIN}"
    if not r.pinyin.isascii() or not r.pinyin.isalpha():
        return "拼音只能由英文字母组成"
    if not 1 <= r.index <= 9:
        return f"候选位置越界 {r.index}（须 1..9）"
    if not r.text:
        return "短语文本为空"
    if len(r.text) > MAX_PHRASE:
        return f"短语超长 {len(r.text)} > {MAX_PHRASE}"
    return None


def merge(existing: list[Rec], new: list[Rec]) -> tuple[list[Rec], int]:
    """按 (拼音, 候选位置) 合并，返回 (结果列表, 被覆盖条数)。"""
    keys = {(r.pinyin, r.index) for r in new}
    kept = [r for r in existing if (r.pinyin, r.index) not in keys]
    return kept + new, len(existing) - len(kept)


def backup(path: Path) -> Path:
    """为文件生成带时间戳的备份副本。"""
    stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    dst = Path(path).with_name(f"{Path(path).name}.{stamp}.bak")
    shutil.copy2(path, dst)
    return dst


def parse_tsv(text: str) -> tuple[list[Rec], list[str]]:
    """解析 TSV（拼音 <TAB> 位置 <TAB> 文本），返回 (记录, 错误信息)。"""
    recs: list[Rec] = []
    errs: list[str] = []
    for ln, line in enumerate(text.splitlines(), 1):
        if not line.strip() or line.lstrip().startswith("#"):
            continue
        parts = line.split("\t")
        if len(parts) < 3:
            errs.append(f"第 {ln} 行：需要 3 个 TAB 分隔字段，实际 {len(parts)}")
            continue
        pinyin, pos = parts[0].strip(), parts[1].strip()
        phrase = "\t".join(parts[2:])
        if not pos.isdigit():
            errs.append(f"第 {ln} 行：位置须为数字，得到 {pos!r}")
            continue
        r = Rec(pinyin=pinyin, index=int(pos), text=phrase)
        if (e := check(r)) is not None:
            errs.append(f"第 {ln} 行：{e}")
            continue
        recs.append(r)
    return recs, errs


def to_tsv(recs: list[Rec]) -> str:
    """把记录列表导出为 TSV 文本。"""
    return "".join(f"{r.pinyin}\t{r.index}\t{r.text}\n" for r in recs)


def cmd_list(path: Path) -> None:
    """打印短语详表。"""
    meta, recs = read(path)
    print(f"# {path}")
    print(f"# 大小={len(meta['raw'])}B  条数={meta['count']}  "
          f"version={meta['version']}  unknown={meta['unknown']:#010x}")
    print(f"{'#':>3}  {'拼音':<12} {'位':>2} {'c2':>3} 短语")
    for i, r in enumerate(recs):
        print(f"{i:>3}  {r.pinyin:<12} {r.index:>2} {r.candidate2:>3} {r.text}")


def cmd_dump(path: Path) -> None:
    """导出为 TSV。"""
    _, recs = read(path)
    sys.stdout.write(to_tsv(recs))


def cmd_roundtrip(path: Path) -> None:
    """读入再重建，与原文逐字节比对。"""
    meta, recs = read(path)
    rebuilt = build(meta, recs)
    same = rebuilt == meta["raw"]
    print(f"原文 {len(meta['raw'])}B  重建 {len(rebuilt)}B  逐字节一致: {same}")
    if same:
        return
    n = min(len(meta["raw"]), len(rebuilt))
    diff = [i for i in range(n) if meta["raw"][i] != rebuilt[i]]
    print(f"差异字节数 {len(diff)}，前 10 处:")
    for i in diff[:10]:
        print(f"  0x{i:04x}: 原 {meta['raw'][i]:02x} -> 新 {rebuilt[i]:02x}")
    raise SystemExit(1)


def cmd_import(tsv: Path, lex: Path) -> None:
    """从 TSV 导入并写回词库（写前备份）。"""
    meta, existing = read(lex)
    new_recs, errs = parse_tsv(Path(tsv).read_text(encoding="utf-8"))
    for e in errs:
        print(f"跳过：{e}")
    if not new_recs:
        print("没有可导入的短语，未改动文件。")
        return
    merged, dropped = merge(existing, new_recs)
    data = build(meta, merged)
    bak = backup(lex)
    Path(lex).write_bytes(data)
    print(f"备份 -> {bak.name}")
    print(f"写入 {len(new_recs)} 条，覆盖 {dropped} 条，"
          f"现共 {len(merged)} 条，{len(data)}B")
    _, back = read(lex)
    print(f"回读校验：{len(back)} 条，全部可解析 = {len(back) == len(merged)}")


def cmd_export(src: Path, dst: Path, tsv: Path | None) -> None:
    """把一份词库与一份 TSV 合并后另存为新文件（不触碰原文件）。"""
    meta, existing = read(src)
    new_recs, errs = parse_tsv(Path(tsv).read_text(encoding="utf-8")) if tsv else ([], [])
    for e in errs:
        print(f"跳过：{e}")
    merged, dropped = merge(existing, new_recs)
    data = build(meta, merged)
    Path(dst).write_bytes(data)
    print(f"原有 {len(existing)} 条 + 新增 {len(new_recs)} 条"
          f"（覆盖 {dropped}）= {len(merged)} 条")
    print(f"输出 {dst}  {len(data)}B")
    _, back = read(dst)
    print(f"回读校验：{len(back)} 条，可解析 = {len(back) == len(merged)}")


USAGE = """用法:
  msudp.py list      [文件]
  msudp.py dump      [文件]
  msudp.py import    <tsv> [--lex 文件]
  msudp.py export    <tsv> <输出文件> [--lex 源文件]
  msudp.py roundtrip [文件]

省略文件参数时使用默认词库路径。"""


def main(argv: list[str] | None = None) -> None:
    """命令行入口。"""
    argv = list(sys.argv[1:] if argv is None else argv)
    if not argv or argv[0] in ("-h", "--help"):
        print(__doc__)
        print(USAGE)
        return

    cmd, rest = argv[0], argv[1:]
    lex: Path | None = None
    if "--lex" in rest:
        i = rest.index("--lex")
        if i + 1 >= len(rest):
            raise SystemExit("--lex 缺少路径参数")
        lex = Path(rest[i + 1])
        rest = rest[:i] + rest[i + 2:]

    if cmd == "import":
        if len(rest) != 1:
            raise SystemExit("用法: msudp.py import <tsv> [--lex 文件]")
        cmd_import(Path(rest[0]), lex or default_lex())
        return
    if cmd == "export":
        if len(rest) != 2:
            raise SystemExit("用法: msudp.py export <tsv> <输出文件> [--lex 源文件]")
        cmd_export(lex or default_lex(), Path(rest[1]), Path(rest[0]))
        return

    path = lex or (Path(rest[0]) if rest else default_lex())
    handlers = {"list": cmd_list, "dump": cmd_dump, "roundtrip": cmd_roundtrip}
    if cmd not in handlers:
        print(__doc__)
        print(USAGE)
        raise SystemExit(f"未知命令: {cmd}")
    handlers[cmd](path)


if __name__ == "__main__":
    main()
