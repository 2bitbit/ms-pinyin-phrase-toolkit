# ms-pinyin-phrase-toolkit

批量读写 Windows 微软拼音的「用户自定义短语」—— 一条命令改词库并立刻生效。

## 用法（推荐：无 GUI）

加一两条**不需要任何文件**：

```bash
# 管道（append 首选）
"aa`t1`tα" | uv run tools/apply_silent.py --stdin --append

# 或直接给短语：<拼音>:<位>:<文本>
uv run tools/apply_silent.py --add aa:1:α --append
```

全量替换去掉 `--append`。批量时再读 TSV：

```bash
uv run tools/apply_silent.py plan.tsv --append
```

流程：写 `.lex` → 杀 `TextInputHost` + `ChsIME` → Win+Space 切走再切回 → 回读校验。

不弹窗、不抢焦点。杀进程最多打断当前那次未上屏的拼音（约 0.5s）。

## 备选：GUI 导入

```bash
uv run tools/apply_phrases.py plan.tsv --append
```

直达 `ms-settings:regionlanguage-chsime-pinyin-udp`，点「导入」。会弹窗抢焦点，只在无 GUI 路线不可用时用。

## 安装

需要 [uv](https://docs.astral.sh/uv/) 和 Python ≥ 3.11（无第三方依赖）：

```bash
git clone https://github.com/2bitbit/ms-pinyin-phrase-toolkit.git
cd ms-pinyin-phrase-toolkit
uv run tools/msudp.py list
```

## 命令

### `apply_silent.py` — 无 GUI 应用

| 命令 | 作用 |
|---|---|
| `--stdin [--append]` | 从标准输入读 TSV |
| `--add <拼音>:<位>:<文本> [...]` | 直接给短语 |
| `<tsv> [--append]` | 从文件读 |

默认全量替换；`--append` 按 `(拼音, 位置)` 覆盖后保留其余。

### `msudp.py` — 词库读写

| 命令 | 作用 |
|---|---|
| `list [文件]` | 列出短语 |
| `dump [文件]` | 导出 TSV |
| `export <tsv> <输出>` | 合并后另存为导入文件 |
| `import <tsv>` | 直接写词库（写前备份；**不会**让输入法重载） |
| `roundtrip [文件]` | 读入再重建，逐字节比对 |

省略文件参数时使用 `%APPDATA%\Microsoft\InputMethod\Chs\ChsPinyinEUDPv1.lex`。

## TSV 格式

```
aa	1	α
aa	2	Α
ss	1	σ
```

`#` 开头为注释。同 `(拼音, 位置)` 覆盖。

## 必须知道的限制

| 操作 | 打字是否生效 |
|---|---|
| 只改 `.lex` | ❌ |
| 只按 Win+Space | ❌ |
| 只杀 `ChsIME` | 部分（已学过的词可能碰巧生效） |
| 杀 `TextInputHost` + `ChsIME`，再 Win+Space 切走切回 | ✅ |
| 设置页「导入」/「添加」 | ✅ |

其它：

- 拼音只接受 `a-z`，不区分大小写。`dd`→δ / `DD`→Δ 用候选位置 1 / 2 区分。
- 写出按 `(拼音, 位置)` 排序，否则 IME 查找错位。
- 拼音 ≤32 字母，位置 1–9，短语 ≤64 字符。

## 示例：希腊字母

`examples/greek.tsv`：45 条（小写位 1、大写位 2）。`jj` 无大写（与 `ff` 的 Φ 冲突）。

```bash
uv run tools/apply_silent.py examples/greek.tsv --append
```

## 文档

- [docs/FORMAT.md](docs/FORMAT.md) — 二进制格式与踩坑
- [SKILL.md](SKILL.md) — 给 AI agent 的技能入口

```bash
uv run tests/test_msudp.py     # 21 项，不读真实词库
```

## 致谢

格式交叉验证：[youmuyou/mschxudp](https://github.com/youmuyou/mschxudp)。
另可参考 [mchudie/PinyinLexTool](https://github.com/mchudie/PinyinLexTool)、
[studyzy/imewlconverter](https://github.com/studyzy/imewlconverter)。

## 许可

MIT
