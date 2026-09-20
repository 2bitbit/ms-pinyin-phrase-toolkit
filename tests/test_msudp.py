# /// script
# requires-python = ">=3.11"
# dependencies = []
# ///
"""自检：格式往返、边界用例、TSV 往返。

不依赖任何真实词库文件，全部在内存中构造合成样本，可安全反复运行。

    uv run tests/test_msudp.py
"""

from __future__ import annotations

import importlib.util
import struct
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
spec = importlib.util.spec_from_file_location("msudp", ROOT / "tools" / "msudp.py")
msudp = importlib.util.module_from_spec(spec)
sys.modules["msudp"] = msudp
spec.loader.exec_module(msudp)

PASSED: list[str] = []
FAILED: list[str] = []


def check(name: str, cond: bool, detail: str = "") -> None:
    """记录一条断言结果。"""
    (PASSED if cond else FAILED).append(name)
    mark = "PASS" if cond else "FAIL"
    print(f"[{mark}] {name}" + (f"  -- {detail}" if detail and not cond else ""))


def sample_recs() -> list[msudp.Rec]:
    """构造覆盖各类字符的样本记录。"""
    return [
        msudp.Rec("and", 1, "\u2227"),                    # 数学符号
        msudp.Rec("cha", 1, "\u274c"),                    # 单字符 emoji
        msudp.Rec("dui", 2, "\u2714\ufe0f"),              # emoji + 变体选择符
        msudp.Rec("han", 5, "\U0001f605"),                # 代理对（非 BMP）
        msudp.Rec("dianj", 1, "\u70b9\u79ef"),            # 多字中文
        msudp.Rec("sp", 1, "superpowers"),                # 长 ASCII
        msudp.Rec("if", 1, "\u2192"),                     # 同拼音多候选
        msudp.Rec("if", 2, "\u2194"),
        msudp.Rec("z", 9, "\u6808"),                      # 位置 9
        msudp.Rec("aa", 1, "\u03b1"),                     # 希腊字母
        msudp.Rec("aa", 2, "\u0391"),
    ]


def tmp_meta() -> dict:
    """构造一份头部元信息。"""
    return {"raw": b"", "count": 0, "timestamp": 1700000000,
            "unknown": msudp.UNKNOWN_HDR, "version": msudp.VERSION}


def test_roundtrip() -> None:
    """核心：构造 -> 写出 -> 读回 -> 再写出，必须逐字节稳定。"""
    recs = sample_recs()
    data = msudp.build(tmp_meta(), recs)
    tmp = ROOT / "tests" / "_tmp_roundtrip.dat"
    tmp.write_bytes(data)

    meta2, back = msudp.read(tmp)
    expect = sorted(recs, key=lambda r: (r.pinyin, r.index))
    check("读回条数一致", len(back) == len(recs), f"{len(back)} != {len(recs)}")
    check("读回内容一致（拼音序）", back == expect)
    data2 = msudp.build(meta2, back)
    check("二次写出逐字节一致", data2 == data,
          f"{len(data2)}B vs {len(data)}B")
    tmp.unlink(missing_ok=True)


def test_header_invariants() -> None:
    """头部不变式：offset_start + 4*count == start，end == 文件长度。"""
    recs = sample_recs()
    data = msudp.build(tmp_meta(), recs)
    off_start = struct.unpack_from("<I", data, 0x10)[0]
    start = struct.unpack_from("<I", data, 0x14)[0]
    end = struct.unpack_from("<I", data, 0x18)[0]
    count = struct.unpack_from("<I", data, 0x1C)[0]
    check("phrase_offset_start == 0x40", off_start == 0x40, hex(off_start))
    check("offset_start + 4*count == start",
          off_start + 4 * count == start, f"{off_start:#x}+{4*count} != {start:#x}")
    check("phrase_end == 文件长度", end == len(data), f"{end} != {len(data)}")
    check("首项 offset 为 0",
          struct.unpack_from("<I", data, 0x40)[0] == 0)


def test_offset_field() -> None:
    """offset 字段必须等于 0x10 + len(pinyin_utf16)。"""
    ok = True
    detail = ""
    for r in sample_recs():
        data = msudp.build(tmp_meta(), [r])
        expect = 0x10 + len(r.pinyin.encode("utf-16-le")) + 2
        got = struct.unpack_from("<H", data, 0x44 + 4)[0]
        if got != expect:
            ok = False
            detail = f"{r.pinyin}: {got} != {expect}"
    check("offset = 0x10 + len(pinyin_utf16)", ok, detail)


def test_empty() -> None:
    """零条记录也必须能正确读写。"""
    data = msudp.build(tmp_meta(), [])
    tmp = ROOT / "tests" / "_tmp_empty.dat"
    tmp.write_bytes(data)
    meta, recs = msudp.read(tmp)
    check("空词库可读", recs == [] and meta["count"] == 0)
    check("空词库可重建", msudp.build(meta, recs) == data)
    tmp.unlink(missing_ok=True)


def test_validate() -> None:
    """校验规则应正确拦截非法输入。"""
    cases = [
        (msudp.Rec("", 1, "x"), True, "空拼音"),
        (msudp.Rec("a" * 33, 1, "x"), True, "拼音超长"),
        (msudp.Rec("aa1", 1, "x"), True, "拼音含数字"),
        (msudp.Rec("aa", 0, "x"), True, "位置 0"),
        (msudp.Rec("aa", 10, "x"), True, "位置 10"),
        (msudp.Rec("aa", 1, ""), True, "空短语"),
        (msudp.Rec("aa", 1, "x" * 65), True, "短语超长"),
        (msudp.Rec("aa", 1, "x"), False, "合法"),
        (msudp.Rec("aa", 9, "x" * 64), False, "边界合法"),
    ]
    ok = True
    detail = ""
    for rec, should_fail, label in cases:
        got = msudp.check(rec) is not None
        if got != should_fail:
            ok = False
            detail = f"{label}: 期望失败={should_fail} 实际={got}"
    check("校验规则正确", ok, detail)


def test_tsv() -> None:
    """TSV 往返：导出再解析应还原记录。"""
    recs = [r for r in sample_recs() if msudp.check(r) is None]
    text = msudp.to_tsv(recs)
    back, errs = msudp.parse_tsv(text)
    check("TSV 解析无误", not errs, "; ".join(errs))
    check("TSV 往返一致", back == recs,
          f"{len(back)} != {len(recs)}")


def test_tsv_errors() -> None:
    """TSV 非法行应被跳过并报错，合法行保留。"""
    text = "aa\t1\t\u03b1\nbb\tx\t\u03b2\ncc\t1\n\ndd\t2\t\u03b4\n"
    recs, errs = msudp.parse_tsv(text)
    check("非法行被跳过", len(errs) == 2, f"errs={errs}")
    check("合法行保留", len(recs) == 2 and {r.pinyin for r in recs} == {"aa", "dd"})


def test_merge() -> None:
    """合并语义：同 (拼音, 位置) 覆盖，其余保留。"""
    existing = [msudp.Rec("aa", 1, "old"), msudp.Rec("bb", 1, "keep")]
    new = [msudp.Rec("aa", 1, "new"), msudp.Rec("cc", 1, "add")]
    merged, dropped = msudp.merge(existing, new)
    check("覆盖计数正确", dropped == 1, str(dropped))
    check("合并后 3 条", len(merged) == 3, str(len(merged)))
    aa = [r for r in merged if r.pinyin == "aa"][0]
    check("同键被覆盖", aa.text == "new", aa.text)
    check("未冲突项保留", any(r.pinyin == "bb" and r.text == "keep" for r in merged))


def test_build_sorts_by_pinyin() -> None:
    """写出必须按 (拼音, 位置) 排序，否则 IME 查找会错位。"""
    recs = [
        msudp.Rec("t", 2, "天台"),
        msudp.Rec("p", 1, "大侠"),
        msudp.Rec("i", 1, "i人"),
    ]
    tmp = ROOT / "tests" / "_tmp_sort.dat"
    tmp.write_bytes(msudp.build(tmp_meta(), recs))
    _, back = msudp.read(tmp)
    tmp.unlink(missing_ok=True)
    check("拼音序 i < p < t", [r.pinyin for r in back] == ["i", "p", "t"],
          str([r.pinyin for r in back]))


def test_bad_input() -> None:
    """非法文件应明确报错而非静默返回。"""
    tmp = ROOT / "tests" / "_tmp_bad.dat"
    tmp.write_bytes(b"NOTMSCHX" + b"\x00" * 60)
    try:
        msudp.read(tmp)
        check("坏文件报错", False, "未抛异常")
    except ValueError:
        check("坏文件报错", True)
    finally:
        tmp.unlink(missing_ok=True)


def main() -> None:
    """运行全部用例。"""
    print("=" * 58)
    print("msudp 自检")
    print("=" * 58)
    for fn in (test_roundtrip, test_header_invariants, test_offset_field,
               test_empty, test_validate, test_tsv, test_tsv_errors,
               test_merge, test_build_sorts_by_pinyin, test_bad_input):
        fn()
    print("=" * 58)
    print(f"通过 {len(PASSED)} / {len(PASSED) + len(FAILED)}")
    if FAILED:
        print("失败用例:")
        for f in FAILED:
            print(f"  - {f}")
        raise SystemExit(1)
    print("全部通过")


if __name__ == "__main__":
    main()
