# ms-pinyin-phrase-toolkit

批量读写 Windows 微软拼音输入法的「用户自定义短语」。

不点 GUI、不逐条录入 —— 用一份 TSV 管理全部短语，一次导入。

```
uv run tools/msudp.py dump > my.tsv          # 导出现有短语
# 编辑 my.tsv ...
uv run tools/msudp.py export my.tsv out.dat  # 生成全量导入文件
# 设置 > 时间和语言 > 语言和区域 > 用户自定义短语 > 导入 > 选 out.dat
```

## 为什么需要它

微软拼音的自定义短语存在一个二进制文件里，且**设置界面只支持逐条手动添加**。
要维护几十上百条短语（比如一整套符号触发码），手点不现实。

本项目解析该格式，并提供导出/导入/校验能力。

## 关键发现

### 1. 直接改词库文件无效，必须走「导入」

| 方式 | 实测结果 |
|---|---|
| 直接写 `ChsPinyinEUDPv1.lex` | **无效**。输入法启动时读一次并缓存，运行中不重读 |
| GUI「导入」按钮读 `.dat` | **有效** |

### 2. 「导出」的产物与词库是同一格式

设置页「导出」得到的 `UserDefinedPhrase.dat`，与
`%APPDATA%\Microsoft\InputMethod\Chs\ChsPinyinEUDPv1.lex` **格式完全相同**
（magic 均为 `mschxudp`）。所以本工具生成的文件可直接被「导入」按钮读取。

### 3. 大小写只能靠候选位置区分

微软拼音的拼音字段只接受 `a-z` 且**不区分大小写**，`DD` 会被规范化成 `dd`。
所以 LaTeX Suite 那类 `dd`→δ / `DD`→Δ 的映射无法直接照搬，正确做法是：

```
dd  位置1  δ      # 敲 dd，候选第 1 位
dd  位置2  Δ      # 同一个 dd，候选第 2 位
```

### 4. 格式验证方式

`roundtrip` 子命令会读入文件、内存中重建、与原文件**逐字节比对**。
对用户在 GUI 里「导出」得到的 `.dat` 能做到 `逐字节一致: True`，
即证明格式理解无误。这是排查「导入不生效」的第一手段。

## 环境要求

- Windows 10 / 11，已启用「中文(简体) - 微软拼音」
- Python ≥ 3.11（用 [uv](https://docs.astral.sh/uv/) 运行，无第三方依赖）

## 用法

```bash
uv run tools/msudp.py list      [文件]        # 短语详表（含候选位置）
uv run tools/msudp.py dump      [文件]        # 导出 TSV
uv run tools/msudp.py import    <tsv> [--lex 文件]  # 直接写词库（见下方警告）
uv run tools/msudp.py export    <tsv> <输出> [--lex 源文件]  # 合并另存（推荐）
uv run tools/msudp.py roundtrip [文件]        # 格式自检
```

省略文件参数时使用当前用户的默认词库路径。

> [!WARNING]
> `import` 会直接改写词库文件。若输入法正在运行，改动**可能不被加载**，
> 甚至被内存副本覆盖。除非你已确知环境行为，否则优先用 `export` 生成
> 文件后走 GUI「导入」。

### TSV 格式

每行 `拼音 <TAB> 候选位置 <TAB> 输出文本`，`#` 开头为注释：

```
aa	1	α
aa	2	Α
ss	1	σ
ss	2	Σ
rq	1	2026-01-01
```

导入时同 `(拼音, 候选位置)` 覆盖，其余保留。非法行会被跳过并打印原因。

## 示例：希腊字母触发码

`examples/greek.tsv` 提供 45 条映射（23 个触发码，小写在第 1 位、大写在第 2 位）：

```bash
uv run tools/msudp.py export examples/greek.tsv greek.dat
```

| 触发码 | 位1 | 位2 | | 触发码 | 位1 | 位2 | | 触发码 | 位1 | 位2 |
|---|---|---|---|---|---|---|---|---|---|---|
| `aa` | α | Α | | `hh` | η | Η | | `rr` | ρ | Ρ |
| `bb` | β | Β | | `jj` | ϕ | — | | `ss` | σ | Σ |
| `cc` | χ | Χ | | `kk` | κ | Κ | | `tt` | τ | Τ |
| `dd` | δ | Δ | | `ll` | λ | Λ | | `uu` | υ | Υ |
| `ee` | ε | Ε | | `mm` | μ | Μ | | `ww` | ω | Ω |
| `ff` | φ | Φ | | `nn` | ν | Ν | | `xx` | ξ | Ξ |
| `gg` | γ | Γ | | `pp` | π | Π | | `yy` | ψ | Ψ |
| | | | | `qq` | θ | Θ | | `zz` | ζ | Ζ |

`jj` 没有大写候选，因为它的大写 Φ 与 `ff` 的第 2 位重复。

## 测试

```bash
uv run tests/test_msudp.py
```

全部在内存中构造合成样本，不读取真实词库，可安全反复运行。
覆盖：往返一致性、头部不变式、`offset` 字段公式、空词库、输入校验、
TSV 往返与容错、合并语义、坏文件报错。

## 文件格式

```
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

0x40         phrase_offsets[]: u32 × phrase_count
             第 0 项恒为 0；第 N 项 = 第 N 条记录相对 phrase_start 的偏移

记录区（phrase_start 起），每条记录：
  16 字节头：
    0..3   magic         10 00 10 00
    4..5   offset        0x10 + len(pinyin_utf16)
    6      candidate     候选框位置 1..9
    7      candidate2    实测恒为 6
    8..15  unknown8      输入法内部标识，原样保留
  pinyin    UTF-16LE，以 0x0000 结尾
  phrase    UTF-16LE，以 0x0000 结尾
```

不变式：

```
phrase_offset_start + 4 * phrase_count == phrase_start
phrase_offsets[N] + offset + len(phrase) == phrase_offsets[N+1]
phrase_start + phrase_offsets[N] == 第 N 条记录的起点
```

### 容易踩的坑

排查格式问题时，以下两处是实际踩过的：

1. **`offset` 字段不是「拼音长度」**。它是 `0x10 + len(pinyin_utf16)`
   （含结尾 `\0` 的 2 字节），且指向的是**短语**数据，拼音固定在头后 16 字节处。
   把 `offset` 当成 `拼音字节数 + 2` 会正好差 8。
2. **记录头里有 8 字节 `unknown8`**，容易被误当成填充而与短语文本混淆。

## 致谢

格式依据 [youmuyou/mschxudp](https://github.com/youmuyou/mschxudp) 的文档与
实现交叉验证。本项目在其基础上补充了官方导出产物的逐字节往返验证、
TSV 工作流、输入校验与自检测试。

另可参考 [mchudie/PinyinLexTool](https://github.com/mchudie/PinyinLexTool)
（C#/WPF 实现）与 [studyzy/imewlconverter](https://github.com/studyzy/imewlconverter)
（深蓝词库转换，支持从其他输入法转换）。

## 许可

MIT
