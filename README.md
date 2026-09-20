# ms-pinyin-phrase-toolkit（开发中）

批量读写 Windows 微软拼音的「用户自定义短语」—— 用一份 TSV 管理全部触发码，一次导入。

## 两条路线

### 路线 A：无 GUI（推荐，零窗口零干扰）

加一两条短语**不需要任何文件**：

```bash
uv run tools/apply_silent.py --add aa:1:α --append      # <拼音>:<位>:<文本>
uv run tools/apply_silent.py --add qq:1:甲 --add ww:2:乙
```

也可以走管道：

```bash
"u`t1`t有什么" | uv run tools/apply_silent.py --stdin --append
```

批量维护时再从 TSV 读（`--append` 保留现有，默认全量替换）：

```bash
uv run tools/apply_silent.py plan.tsv --append
```

流程：改词库 → 杀 TextInputHost + ChsIME → Win+Space 切走再切回 → 回读校验。

**不弹任何窗口、不抢焦点、不阻塞等待。** 杀进程最多让你当前那次未上屏的
拼音断掉，代价约 0.5 秒，比 GUI 方案抢焦点轻得多，所以默认直接执行；
确需等键鼠空闲时加 `--wait-idle`。

### 路线 B：GUI 导入（备选）

```bash
uv run tools/apply_phrases.py <tsv>            # 全量替换
uv run tools/apply_phrases.py --append <tsv>   # 保留现有，追加
```

会打开设置窗口、直达到短语页、点「导入」并填路径。**会弹窗抢焦点**，
知道你正在打字时被文件选择器糊脸不好受 —— 只在路线 A 不可用时用。

> [!IMPORTANT]
> **为什么改完文件要重启输入法？**
> 输入法只在启动时读词库并缓存，运行中改文件**不会**重载。
> 单独按 Win+Space 也不够。实测可行的是：杀掉 **TextInputHost + ChsIME**
> 后再 Win+Space 切走切回（让新进程绑到前台会话），或走设置页「导入」。

> [!WARNING]
> 路线 B 依赖 UI 自动化，导入的几秒内若用户点击、切换窗口或按 Esc 可能打断。
> 脚本以「回读设置页条数一致」为成功判据，不一致就报错退出；写入幂等，可重跑。

## 解决什么问题

微软拼音的自定义短语存在一个二进制文件里，设置界面**只支持逐条手动添加**。
想配一套符号触发码（`aa`→α、`ss`→σ、`rq`→当前日期……）就得点几十次。

本项目解析该格式，让你用文本文件维护短语表。

## 安装

需要 [uv](https://docs.astral.sh/uv/) 和 Python ≥ 3.11（无第三方依赖）：

```bash
git clone https://github.com/2bitbit/ms-pinyin-phrase-toolkit.git
cd ms-pinyin-phrase-toolkit
uv run tools/msudp.py list        # 应列出你现有的短语
```

## 命令

### `msudp.py` — 词库读写

| 命令 | 作用 |
|---|---|
| `list [文件]` | 列出短语（含候选位置） |
| `dump [文件]` | 导出为 TSV |
| `export <tsv> <输出>` | 合并现有短语与 TSV，另存为导入文件 |
| `import <tsv>` | 直接写词库（写前自动备份） |
| `roundtrip [文件]` | 格式自检：重建并逐字节比对 |

省略文件参数时使用当前用户的默认词库路径。

### `apply_silent.py` — 无 GUI 应用（推荐）

| 命令 | 作用 |
|---|---|
| `apply_silent.py --add <拼音>:<位>:<文本> [...]` | 直接给短语，**不落文件** |
| `apply_silent.py --stdin` | 从标准输入读 TSV |
| `apply_silent.py <tsv>` | 从 TSV 文件读 |

均支持 `--append`（保留现有短语；默认全量替换）。

### `apply_phrases.py` — GUI 应用（备选）

| 命令 | 作用 |
|---|---|
| `apply_phrases.py <tsv>` | 全量替换并驱动 GUI 导入 |
| `apply_phrases.py --append <tsv>` | 保留现有短语，追加后导入 |

## TSV 格式

每行 `拼音 <TAB> 候选位置 <TAB> 输出文本`：

```
aa	1	α
aa	2	Α
ss	1	σ
ss	2	Σ
rq	1	2026-01-01
```

同 `(拼音, 候选位置)` 覆盖，其余保留；`#` 开头为注释，非法行会跳过并报错。

## 三条必须知道的限制

### 1. 直接改词库文件不生效

| 方式 | 结果 |
|---|---|
| 直接写 `ChsPinyinEUDPv1.lex` | ❌ 输入法启动时读一次并缓存，运行中不重读 |
| 设置页「导入」读 `.dat` | ✅ 有效 |

所以推荐流程是 `export` 生成文件 → GUI 导入。`import` 子命令能直接写文件，
但只在你有把握时用。

### 2. 拼音不区分大小写

微软拼音的拼音字段只接受 `a-z`，`DD` 会被规范化成 `dd`。
LaTeX Suite 那类 `dd`→δ / `DD`→Δ 的映射无法照搬，正确做法是用**候选位置**区分：

```
dd	1	δ     # 敲 dd，候选项第 1 位
dd	2	Δ     # 同一个 dd，第 2 位
```

### 3. 导入后要切换一次输入法

词库在输入法激活时加载。导入后按 **Win+Space** 切换一次再测试。

## 限制

| 项 | 上限 |
|---|---|
| 拼音 | 32 字符，仅 `a-z` |
| 候选位置 | 1–9 |
| 短语长度 | 64 字符 |

## 示例：希腊字母

`examples/greek.tsv` 是 45 条现成映射（23 个触发码，小写在第 1 位、大写在第 2 位）：

```bash
uv run tools/msudp.py export examples/greek.tsv greek.dat
```

| | | | | | | | | | | |
|---|---|---|---|---|---|---|---|---|---|---|
| `aa` α Α | `bb` β Β | `cc` χ Χ | `dd` δ Δ | `ee` ε Ε | `ff` φ Φ | `gg` γ Γ | `hh` η Η | `jj` ϕ | `kk` κ Κ | `ll` λ Λ |
| `mm` μ Μ | `nn` ν Ν | `pp` π Π | `qq` θ Θ | `rr` ρ Ρ | `ss` σ Σ | `tt` τ Τ | `uu` υ Υ | `ww` ω Ω | `xx` ξ Ξ | `yy` ψ Ψ |
| `zz` ζ Ζ | | | | | | | | | | |

`jj` 无大写候选（其大写 Φ 与 `ff` 冲突）。

## 排查

导入后不生效，按顺序查：

1. 跑 `roundtrip` 确认格式 —— 对 GUI「导出」得到的 `.dat` 应显示 `逐字节一致: True`
2. 是否切换过输入法（Win+Space）
3. 导入文件是否为**全量** —— `export` 已保证这点

## 文档

- [docs/FORMAT.md](docs/FORMAT.md) —— 二进制格式规格、字段语义与踩坑记录
- [SKILL.md](SKILL.md) —— 供 AI agent 调用的技能入口

## 测试

```bash
uv run tests/test_msudp.py     # 20 项，不读真实词库，可反复运行
```

## 致谢

格式依据 [youmuyou/mschxudp](https://github.com/youmuyou/mschxudp) 交叉验证。
另可参考 [mchudie/PinyinLexTool](https://github.com/mchudie/PinyinLexTool)（C#/WPF）
与 [studyzy/imewlconverter](https://github.com/studyzy/imewlconverter)（深蓝词库转换）。

## 许可

MIT
