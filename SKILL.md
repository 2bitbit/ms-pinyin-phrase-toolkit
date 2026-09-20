---
name: ms-pinyin-phrase
description: 批量读写 Windows 微软拼音输入法的「用户自定义短语」。当需要批量导入/导出/修改自定义短语、用触发码快速输入希腊字母或数学符号、解析 ChsPinyinEUDPv1.lex 或 UserDefinedPhrase.dat 文件、或排查导入不生效时使用。
version: "1.1.0"
---

# 微软拼音自定义短语

用脚本批量管理 Windows「中文(简体) - 微软拼音」的用户自定义短语，替代逐条手点 GUI。

工具位于本 skill 目录下的 `tools/msudp.py`，无需第三方依赖：

```bash
uv run tools/msudp.py <子命令>
```

## 文件放哪里

**短语表（TSV）与生成的 `.dat` 一律放临时目录，不要写进本仓库。**

本仓库是只读的工具代码；`*.tsv`（除 `examples/`）与 `*.dat` 已被 `.gitignore`
排除，但仍应主动写到临时目录，避免污染工作区：

```bash
WORK="${TMPDIR:-/tmp}/msph_work"     # Windows: $env:TEMP\msph_work
mkdir -p "$WORK"
uv run tools/msudp.py dump > "$WORK/current.tsv"
uv run tools/apply_silent.py "$WORK/plan.tsv"
```

回滚用的快照同样放临时目录。仓库里只保留代码、文档与 `examples/greek.tsv`
这一个示例表。

## 何时使用

- 用户要批量添加/修改/删除拼音输入法的自定义短语
- 要给输入法配一套符号触发码（希腊字母、数学符号、常用模板）
- 要备份、导出、或在多台机器间迁移短语表
- 写入了词库但输入法不认，需要排查

## 三条铁律

### 1. 只有 GUI 操作或「杀输入法进程」会重载词库

输入法只在启动时读 `ChsPinyinEUDPv1.lex` 并缓存。实测结论（判据是**用户实际
打字能否打出新短语**，而不是设置页列表是否刷新 —— 后者只是页面缓存）：

| 操作 | 是否重载 |
|---|---|
| 直接改 `.lex` 文件 | ❌ |
| 切换输入法（Win+Space） | ❌ |
| 杀掉 `ChsIME` 进程 | ✅ **约 1 秒内服务自动重启并重载** |
| 设置页「导入」/「添加」 | ✅ |

> ⚠️ 踩坑记录：`Stop-Process` 与 `taskkill /F` 对 `ChsIME` 都会返回
> `Access is denied`；必须直接调 Win32 API
> `OpenProcess(PROCESS_TERMINATE)` + `TerminateProcess`。
> 且判断是否重启成功要用**进程启动时间**，不能用 PID（Windows 会复用 PID）。
> 用错这两点会导致脚本「以为杀掉了其实没杀」，从而误判该方案无效。

### 2. 生成的导入文件必须是全量

「导入」是覆盖还是合并未经确认，因此始终用 `export`（自动把现有短语一并写入），
两种语义下都安全。

### 3. 大小写只能靠候选位置区分

拼音字段只接受 `a-z` 且不区分大小写，`DD` 会被规范化成 `dd`。
所以 LaTeX Suite 那类 `dd`→δ / `DD`→Δ 无法照搬，要用候选位置：

```
dd	1	δ
dd	2	Δ
```

## 工作流

### 方式一：无 GUI（推荐，零窗口零干扰）

```bash
uv run tools/apply_silent.py <tsv>            # 全量替换
uv run tools/apply_silent.py --append <tsv>   # 保留现有，追加
```

流程：等用户键鼠空闲 → 改词库 → 杀 ChsIME（0.5s 自动重启）→ 回读校验。

**不弹任何窗口、不抢焦点。** 空闲检测（`GetLastInputInfo`）保证不在用户打字时动手；
若用户持续操作超过 60 秒则放弃并报错，不打断。

### 方式二：GUI 导入（无 GUI 方案不可用时）

```bash
uv run tools/apply_phrases.py <tsv>            # 全量替换
uv run tools/apply_phrases.py --append <tsv>   # 保留现有，追加
```

会打开设置窗口、用 `ms-settings:regionlanguage-chsime-pinyin-udp` 直达短语页、
点「导入」并填入路径。**会弹窗抢焦点**，是备选方案。

### 方式三：纯手动

1. `uv run tools/msudp.py dump > current.tsv` 查看现状
2. 编辑 TSV（格式见下）
3. `uv run tools/msudp.py export new.tsv out.dat`
4. 用户在设置页点「导入」选 `out.dat`

## TSV 格式

每行 `拼音 <TAB> 候选位置 <TAB> 输出文本`，`#` 开头为注释：

```
aa	1	α
aa	2	Α
ss	1	σ
ss	2	Σ
```

## 子命令

| 命令 | 作用 |
|---|---|
| `list [文件]` | 列出短语（含候选位置） |
| `dump [文件]` | 导出为 TSV |
| `export <tsv> <输出> [--lex 源]` | 合并后另存（**推荐**） |
| `import <tsv> [--lex 文件]` | 直接写词库，写前自动备份 |
| `roundtrip [文件]` | 格式自检：重建并逐字节比对 |

省略文件参数时使用当前用户的默认词库路径。

## 限制

| 项 | 上限 |
|---|---|
| 拼音 | 32 字符，仅 `a-z` |
| 候选位置 | 1–9 |
| 短语长度 | 64 字符 |

## 排查：导入后不生效

按顺序验证：

1. **格式是否正确** —— 跑 `roundtrip`。对用户在 GUI 点「导出」得到的 `.dat`
   应输出 `逐字节一致: True`；若为 `False`，说明生成逻辑有问题。
2. **是否切换过输入法** —— 词库在输入法激活时加载，导入后需 Win+Space。
3. **触发码是否与真实拼音冲突** —— `aa`、`dd` 这类双字母在中文里基本不构成音节，
   干扰小；单字母会与常用字抢候选。

## 文件格式

完整规格（头部字段、记录结构、不变式、`offset` 与 `unknown8` 的语义、
排查踩坑记录）见 [docs/FORMAT.md](docs/FORMAT.md)。

速记要点：

```
记录头 16B: magic(4)=10001000 | offset(2)=0x10+len(pinyin含\0)
            | candidate(1)=候选位置 | candidate2(1)=6 | unknown8(8)
头部之后紧跟拼音；offset 指向短语
```

## 安全须知

- 任何写入前先备份。`import` 会自动生成 `<文件>.<时间戳>.bak`；
  `export` 不触碰原文件。
- 不要删除同目录下的 `UDP*.tmp`（输入法运行时的暂存文件，常被独占锁定）。
- 交付前用 `roundtrip` 自检生成的文件。
