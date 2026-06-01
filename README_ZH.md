<p align="right">
  <a href="README.md">English</a> ·
  <a href="README_KO.md">한국어</a> ·
  <strong>中文</strong> ·
  <a href="README_FR.md">Français</a>
</p>

<h1 align="center">qf-lib-harness</h1>

<p align="center">
  <em>面向美股的纯价格自主 alpha 研究。<br>
  编写策略——手写或借助 AI 智能体——通过闸门，读取判定。</em>
</p>

<p align="center">
  <img src="https://img.shields.io/badge/python-3.11-blue" alt="Python 3.11">
  <img src="https://img.shields.io/badge/engine-qf--lib%20(pinned)-orange" alt="qf-lib pinned">
  <img src="https://img.shields.io/badge/tests-82%20passing-brightgreen" alt="tests">
  <img src="https://img.shields.io/badge/built%20with-Claude%20Code-d97757" alt="Claude Code">
</p>

---

## 你可以在这里做什么

| # | 目标 | 位置 | 命令 |
|---|---|---|---|
| 1 | **获取数据** | `research/` | `uv run python research/1_fetch_universe.py …` |
| 2 | **手写策略** | `alpha_lab/experiments/exp_<id>/strategy.py` | `uv run python -m alpha_lab run …` |
| 3 | **让 AI 智能体写策略** | `alpha_lab/CLAUDE.md`（契约） | 将 Claude Code 指向本仓库 |
| 4 | **查看结果** | ledger + 仪表盘 | `uv run python -m alpha_lab status` · `uv run python research/dashboard.py` |
| 5 | **理解智能体循环** | 见下文 §5 | — |
| 6 | **开发自动化：issue → PR** | `.claude/skills/` | `/issue-author` · `/issue-to-pr` |

**首次，仅一次：** `uv sync` 安装 qf-lib（已锁定）+ 依赖。然后 `touch .env`
（本地 `uv` 配置所期望的一个空文件）。Python 固定为 3.11。

### 结构

```
qf-lib-harness/
├── alpha_lab/      # 框架核心：AST 闸门、IS/OS 回测、ledger、实验
├── research/       # 数据管道 + 手动回测 + 仪表盘
├── .claude/skills/ # issue-author + issue-to-pr 开发工作流技能
├── data/           # OHLCV parquet（已 gitignore，绝不离开你的机器）
└── pyproject.toml  # 将 qf-lib 作为外部依赖锁定
```

---

## 1. 获取数据

数据层下载美股 OHLCV 并构建一个时点（point-in-time）股票池。
在仓库根目录按顺序运行带编号的脚本：

```bash
uv run python research/0_smoke_test.py       # ~5秒    yfinance 是否可用？
uv run python research/1_fetch_universe.py   # ~5秒    NASDAQ/NYSE/AMEX 代码（~7千）
uv run python research/2_download_prices.py  # 30分~2小时 日线 OHLCV（可断点续传）
uv run python research/3_build_universe.py   # ~30秒   按成交额取 PIT 前 3000
uv run python research/5_quality_check.py    # 完整性 / NaN / 缺口检查
```

**产出：** `data/prices.parquet` 与 `data/universe_pit_top3000.parquet`。
下游一切都读取它们。（`data/` 已 gitignore。）

## 2. 手写策略

复制模板，改一个函数，运行它：

```bash
mkdir -p alpha_lab/experiments/exp_myidea
cp alpha_lab/trial_template.py alpha_lab/experiments/exp_myidea/strategy.py
```

编辑 `strategy.py`——你只需改常量与 `signal()`：

```python
REBAL = "M"              # 再平衡: "M" | "W" | "Q"
TOP_N = 30               # 每次再平衡持有的标的数（5~200），等权
WEIGHT_SCHEME = "equal"  # 仅接通 "equal"
LOOKBACK_DAYS = 252      # 仅供参考

def signal(ctx) -> pd.DataFrame:
    # date × ticker 评分。越高越看多。NaN = 排除。
    px = ctx.adj_close
    return px.pct_change(LOOKBACK_DAYS).shift(21)   # ← 在此填入你的想法
```

`ctx` 提供（均为 date × ticker）：`adj_close`、`open/high/low`、`volume`、
`dollar_volume`、`universe`。**两条硬规则**（自动拒绝）：禁止未来数据
（禁用 `.shift(-N)`）、禁止读文件（禁用 `pd.read_*`/`open()`——数据只能来自
`ctx`）。

运行：

```bash
uv run python -m alpha_lab run --strategy alpha_lab/experiments/exp_myidea/strategy.py
```

## 3. 用提示词写策略（AI 智能体）

你不必手写。**把一个 AI 编码智能体（Claude Code）指向本仓库，让它开始循环**
——它会替你发明策略。

```bash
cd qf-lib-harness
claude            # 然后输入："Start the alpha_lab loop."
```

`alpha_lab/CLAUDE.md` 是智能体的**契约**：它只能创建/修改
`alpha_lab/experiments/exp_<id>/strategy.py`。核心（`core.py`、`pipeline.py`）
是**冻结**的，且 AST 闸门会在策略运行前硬性拒绝任何未来函数——因此智能体无法
作弊或破坏引擎。

## 4. 查看结果 — ledger 与仪表盘

两种视图，两个来源：

```bash
# A) 循环结果 —— 每次运行都会向 alpha_lab/alpha_ledger.jsonl 追加一行
uv run python -m alpha_lab status --last 20
```

```
PASS = Sharpe_IS > 0.5  AND  Sharpe_OS > 0.5 × Sharpe_IS
```

```bash
# B) 可视化仪表盘 —— 完整回测的交互式 Plotly tearsheet
uv run python research/dashboard.py        # → http://localhost:8765
```

仪表盘渲染 `research/output/backtesting/`（由 `research/run_tsmom_backtest.py`
生成）中的详细 tearsheet；`status` CLI 则是智能体循环 ledger 的快速文本视图。

## 5. 智能体循环

本框架被设计为一个紧凑、永不停止的研究循环来运行：

```
LOOP FOREVER:
  1. 读取 ledger          (status --last 20: 尝试过什么、通过了什么)
  2. 选一个因子想法        (动量、反转、低波动、流动性, …)
  3. 选一个基底           (当前最优 / 险些通过 / 模板 / 从零开始)
  4. 编写 strategy.py     (cp 模板 → 改 signal() + alpha-meta 头)
  5. 运行                 (alpha_lab run … > run.log)
  6. 读取判定             (pass / fail / crash → ledger 行)
  7. 回到第 1 步
```

**ledger 即记忆**——git diff（改了什么）与 ledger 行（得了多少分）就是教训。
循环一直运行，直到人为中断或某个策略越过 `sharpe_is > 1.5`。完整契约：
**`alpha_lab/CLAUDE.md`**。

## 6. 技能 — issue → PR 自动化

`.claude/skills/` 中两个**相互独立**的 Claude Code 技能把目标变成 GitHub issue，
再把 issue 变成 PR——彼此不靠代码耦合，**只通过 GitHub Issues** 通信。
在 Claude Code 会话中分别单独调用：

```text
/issue-author    # 目标/spec → epic → feature → task issue（含 needs-human 标记）
/issue-to-pr     # ready 的 task issue → 分支 → 测试 → 开 PR（停在等待人工合并）
```

| 技能 | 做什么 | 停在哪 |
|---|---|---|
| **`issue-author`** | 把目标分解为 **epic → feature → task** 树，分组并链接（sub-issue），并对需要人工审查的标记 `needs-human`。**创建前先展示整棵树供你批准。** | 在 GitHub 上创建 issue |
| **`issue-to-pr`** | 挑选 **ready** 的 task（跳过 `needs-human`，等待 `Depends on #N`），在分支上实现并跑测试后开 PR（`Closes #N`）。 | 开 PR —— **由人合并** |

```
目标 ─► /issue-author ─► GitHub Issues ─► /issue-to-pr ─► PR ─► (人工合并)
                              ▲
                    你在这里审查 / 编辑 / 设定 needs-human
```

共享契约（标签、sub-issue 层级、`Depends on #N`、`## Verify`、needs-human 标准）
位于 **`.claude/skills/CONVENTIONS.md`**。`issue-to-pr` 会处理*任何*符合契约的
issue——包括你手写的。

---

## 各部分如何协同

```
策略 (你或智能体) ─► alpha_lab (AST 闸门 ─► 回测 ─► IS/OS 切片 ─► ledger)
                                            │
                                   data/prices.parquet ◄── research/ 数据管道 (§1)
                                            │
                                         qf-lib ◄── 引擎，锁定的依赖
```

**qf-lib 并未 vendoring 进本仓库**——它在 `pyproject.toml`
（`[tool.uv.sources]`，fork master `9ba5a0f`）中作为外部依赖被锁定，并在
`uv.lock` 中固定。升级引擎：bump rev 后 `uv lock`。本地修改：切到被注释的
`editable` 行。每个结果都可追溯到 *(qf-lib 提交) × (数据) × (实验)*。
