# mschxudp 文件格式

微软拼音自定义短语文件的二进制格式，含字段语义与排查过程中踩过的坑。

格式交叉验证来源：[youmuyou/mschxudp](https://github.com/youmuyou/mschxudp)。

## 适用文件

同一格式用于两处：

| 路径 | 说明 |
|---|---|
| `%APPDATA%\Microsoft\InputMethod\Chs\ChsPinyinEUDPv1.lex` | 词库本体 |
| 设置页「导出」得到的 `UserDefinedPhrase.dat` | 导出产物，格式完全相同 |

两者 magic 均为 `mschxudp`，故工具生成的文件可直接被设置页「导入」读取。

## 整体布局

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
             第 0 项恒为 0
             第 N 项 = 第 N 条记录相对 phrase_start 的起始偏移

phrase_start 起为记录区
```

## 单条记录

```
16 字节头：
  0..3   magic         10 00 10 00
  4..5   offset        0x10 + len(pinyin_utf16)
  6      candidate     候选框位置 1..9
  7      candidate2    实测恒为 6
  8..15  unknown8      输入法内部标识，原样保留

pinyin    UTF-16LE，以 0x0000 结尾
phrase    UTF-16LE，以 0x0000 结尾
```

头部之后**紧跟拼音**，`offset` 指向的是**短语**数据的起点，而不是拼音。

## 不变式

实现读写时可用来做自检：

```
phrase_offset_start + 4 * phrase_count == phrase_start
phrase_offsets[N] + offset + len(phrase) == phrase_offsets[N+1]
phrase_start + phrase_offsets[N] == 第 N 条记录的起点
```

记录按 `(拼音, 候选位置)` 排序。官方导出与 GUI 导入产物均如此。
无序时 IME 按有序表查找会错位：文件顺序若是 `t, p`，打 `p` 会把两条都塞进候选，打 `t` 一条都找不到。

## 踩过的坑

以下三处是实际逆向时出错并付出调试代价的地方，记录下来避免重蹈。

### 1. `offset` 字段不是拼音长度

`offset = 0x10 + len(pinyin_utf16)`，其中 `pinyin_utf16` **包含结尾的 2 字节 `\0`**。

若误当作 `拼音字节数 + 2`，结果会正好差 8 —— 因为漏掉了记录头自身的 16 字节中
拼音之前的 8 字节（magic 4 + offset 2 + candidate 2）。

且 `offset` 指向短语而非拼音。正确读法：

```python
pinyin = buf[base + 16 : base + offset]      # 头部之后即拼音
phrase = buf[base + offset : seg_end]        # offset 处是短语
```

### 2. `unknown8` 容易被误当成填充

记录头 `8..15` 共 8 字节，在真实数据里内容各不相同，看起来像随机值或哈希，
但它是输入法内部标识。**写入新记录时可安全使用固定默认值**
`00 00 00 00 96 0a 99 20`，已有记录则应原样保留。

一个迷惑现象：单字短语时其 `8..13` 字节恰好等于该字 UTF-16 码点按字节取反
（如 `∧` U+2227 → `ef e8`），容易让人误以为能推导出算法。对多字短语该规律不成立。

### 3. 直接改词库文件不会被加载

输入法启动时读取 `ChsPinyinEUDPv1.lex` 并缓存，运行期间不重读。
直接写文件后：

- 设置页列表**不会刷新**（仍显示旧数据）
- 打字时**不会生效**
- 输入法退出时还可能用内存副本**覆盖**你的修改

必须经设置页「导入」通道加载。设置页路径：

```
设置 > 时间和语言 > 语言和区域 > 用户自定义短语
```

## 字段语义

### candidate（候选框位置）

取值 1..9，与设置页 UI 上显示的「位置」一致。同一拼音的多条记录靠它区分。

由于拼音字段不区分大小写（`DD` 会被规范化成 `dd`），要让一个触发码同时给出
大小写两种结果，只能靠 candidate 区分：

```
dd  candidate=1  δ
dd  candidate=2  Δ
```

### candidate2

实测在全部真实样本中恒为 `6`。工具默认写 6。

### unknown8

见上文「踩过的坑」第 2 条。

## 限制

微软输入法自身的录入限制：

| 项 | 上限 |
|---|---|
| 拼音 | 32 字符，仅 `a-z` |
| candidate | 1–9 |
| 短语长度 | 64 字符 |

## 验证方法

`roundtrip` 子命令读入文件、在内存中重建、与原文件逐字节比对。

**对用户在 GUI 里点「导出」得到的 `.dat` 能做到 `逐字节一致: True`，
即证明格式实现无误。** 这是排查「导入不生效」的第一手段。

## 版本差异

本工具实现的是 `version = 1` / `unknown = 0x00600002` / magic `0x00100010`
的版本（Windows 10 1703 及以后，含 Windows 11）。

更早的 Windows 10 1607 使用 magic `0x00080008`，记录头少 8 字节 `unknown8`，
本工具**不支持**，遇到时会因 magic 校验失败而明确报错。
