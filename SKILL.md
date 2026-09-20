---
name: ms-pinyin-phrase
description: 批量读写 Windows 微软拼音输入法的「用户自定义短语」。当需要批量导入/导出/修改自定义短语、用触发码快速输入希腊字母或数学符号、解析 ChsPinyinEUDPv1.lex 或 UserDefinedPhrase.dat 文件、或排查导入不生效时使用。
version: "1.0.0"
---

# 微软拼音自定义短语工具

用脚本批量管理 Windows「中文(简体) - 微软拼音」的用户自定义短语，替代逐条手点 GUI。

## 何时使用

- 用户要批量添加/修改/删除拼音输入法的自定义短语
- 要给输入法配一套符号触发码（希腊字母、数学符号、常用模板）
- 要备份、导出、或在多台机器间迁移短语表
- 写入了 `.lex` 但输入法不认，需要排查

## 核心事实（务必先读）

### 1. 文件位置

```
%APPDATA%\Microsoft\InputMethod\Chs\ChsPinyinEUDPv1.lex
```

### 2. 修改必须走「导入」通道，不要直接改 `.lex`

| 方式 | 结果 |
|---|---|
| 直接改 `ChsPinyinEUDPv1.lex` | **实测无效**。输入法启动时读一次并缓存，运行中不重读，界面也不会刷新 |
| GUI「导入」按钮 → 读 `.dat` | **有效** |

设置页路径：`设置 > 时间和语言 > 语言和区域 > 用户自定义短语`

### 3. 「导出」产物就是同一格式的二进制

导出的 `UserDefinedPhrase.dat` 与 `.lex` **格式完全相同**（magic `mschxudp`），
所以本工具生成的文件可以直接喂给「导入」按钮。

### 4. 导入文件应是**全量**

`导入` 的语义（覆盖 vs 合并）未经官方确认，因此生成导入文件时始终用
`export` 子命令把「现有短语 + 新增短语」一起写入，两种语义下都安全。

### 5. 微软拼音的限制

| 项 | 限制 |
|---|---|
| 拼音字符集 | 只能 `a-z`，**不区分大小写** |
| 拼音长度 | ≤ 32 |
| 候选位置 | `1`..`9` |
| 短语长度 | ≤ 64 字符 |

**大小写无法用触发码区分**（`DD` 会被规范化成 `dd`）。要让同一个触发码
同时给出大小写两种结果，做法是建两条记录、用**候选位置**区分：
`aa` 位置 1 → `α`，`aa` 位置 2 → `Α`。

## 使用流程

### 第 1 步：先导出/备份现状

```bash
# 列出现有短语
uv run tools/msudp.py list

# 导出为可编辑的 TSV
uv run tools/msudp.py dump > current.tsv
```

### 第 2 步：准备要新增的短语（TSV）

每行 `拼音 <TAB> 位置 <TAB> 输出文本`，`#` 开头为注释：

```
aa	1	α
aa	2	Α
ss	1	σ
ss	2	Σ
```

### 第 3 步：生成全量导入文件

```bash
uv run tools/msudp.py export new.tsv out.dat
```

这会把「当前默认词库 + new.tsv」合并写入 `out.dat`，并在写前不触碰原文件。

### 第 4 步：交给用户导入

**必须由用户在 GUI 完成**（脚本无法可靠代劳）：

1. 打开 `设置 > 时间和语言 > 语言和区域 > 用户自定义短语`
2. 点「导入」，选择上一步的 `out.dat`
3. 导入后**切换一次输入法**（Win+Space）再测试

## 脚本参考

```bash
uv run tools/msudp.py list      [文件]          # 短语详表
uv run tools/msudp.py dump      [文件]          # 导出 TSV
uv run tools/msudp.py import    <tsv> [--lex 文件]   # 直接写词库（需自行验证生效性）
uv run tools/msudp.py export    <tsv> <输出> [--lex 源文件]  # 合并另存（推荐）
uv run tools/msudp.py roundtrip [文件]          # 格式自检：重建并逐字节比对
```

省略文件参数时使用当前用户的默认词库路径。`import` 写前会自动生成
`<文件名>.<时间戳>.bak` 备份。

自检（不依赖真实词库，可安全反复运行）：

```bash
uv run tests/test_msudp.py
```

## 排查：导入后不生效

按顺序检查：

1. **文件格式是否逐字节正确** —— 跑 `roundtrip`。若对官方导出产物
   （用户在 GUI 点「导出」得到的 `.dat`）能 `逐字节一致: True`，
   说明格式理解无误。
2. **是否切换过输入法** —— 词库在输入法激活时加载，导入后需 Win+Space 切换。
3. **是否被运行中的输入法覆盖** —— 若在输入法运行时直接改 `.lex`，
   退出时可能被内存副本覆盖。用文件时间戳判断。
4. **触发码是否与真实拼音冲突** —— 如 `aa`、`dd` 这类双字母在中文里基本
   不构成音节，干扰小；单字母会与常用字抢候选。

## 文件格式速查

```
0x00  8B   proto "mschxudp"
0x08  u32  unknown        0x00600002
0x0C  u32  version        1
0x10  u32  phrase_offset_start   0x40
0x14  u32  phrase_start          0x40 + 4*phrase_count
0x18  u32  phrase_end            文件总长
0x1C  u32  phrase_count
0x20  u32  timestamp
0x24  28B  保留

0x40       phrase_offsets[]: u32 × count
           第 0 项恒为 0；第 N 项 = 第 N 条记录相对 phrase_start 的偏移

记录区，每条记录：
  16B 头: magic(4)=10001000 | offset(2)=0x10+len(pinyin_utf16)
          | candidate(1)=候选位置 | candidate2(1)=6 | unknown8(8)
  pinyin  UTF-16LE + 0x0000
  phrase  UTF-16LE + 0x0000
```

不变式：`phrase_offset_start + 4*count == phrase_start`，
`phrase_start + phrase_offsets[N] == 第 N 条记录起点`。

格式交叉验证来源：[youmuyou/mschxudp](https://github.com/youmuyou/mschxudp)。

## 安全须知

- 任何写入操作前先备份。`import` 会自动备份，`export` 不触碰原文件。
- 不要删除同目录下的 `UDP*.tmp`（输入法运行时的暂存文件，常被独占锁定）。
- 交付前用 `roundtrip` 自检生成的文件。
