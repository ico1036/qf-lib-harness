<p align="right">
  <a href="README.md">English</a> ·
  <strong>한국어</strong> ·
  <a href="README_ZH.md">中文</a> ·
  <a href="README_FR.md">Français</a>
</p>

<h1 align="center">qf-lib-harness</h1>

<p align="center">
  <em>미국 주식 대상, 가격 데이터만으로 하는 자율 알파 리서치.<br>
  전략을 — 손으로든 AI 에이전트로든 — 작성하고, 게이트에 통과시키고, 판정을 읽는다.</em>
</p>

<p align="center">
  <img src="https://img.shields.io/badge/python-3.11-blue" alt="Python 3.11">
  <img src="https://img.shields.io/badge/engine-qf--lib%20(pinned)-orange" alt="qf-lib pinned">
  <img src="https://img.shields.io/badge/tests-82%20passing-brightgreen" alt="tests">
  <img src="https://img.shields.io/badge/built%20with-Claude%20Code-d97757" alt="Claude Code">
</p>

<p align="center">
  <a href="#1-데이터-받기">데이터</a> ·
  <a href="#2-손으로-전략-작성">손코드</a> ·
  <a href="#3-프롬프트로-전략-작성-ai-에이전트">에이전트</a> ·
  <a href="#4-결과-보기--ledger--대시보드">결과</a> ·
  <a href="#5-에이전트-루프">루프</a> ·
  <a href="#6-스킬--이슈--pr-자동화">스킬</a>
</p>

---

## 여기서 할 수 있는 것

| # | 목표 | 위치 | 명령 |
|---|---|---|---|
| 1 | **데이터 받기** | `research/` | `uv run python research/1_fetch_universe.py …` |
| 2 | **손으로 전략 작성** | `alpha_lab/experiments/exp_<id>/strategy.py` | `uv run python -m alpha_lab run …` |
| 3 | **AI 에이전트로 전략 작성** | `alpha_lab/CLAUDE.md` (계약서) | 레포에 Claude Code를 붙인다 |
| 4 | **결과 보기** | ledger + 대시보드 | `uv run python -m alpha_lab status` · `uv run python research/dashboard.py` |
| 5 | **에이전트 루프 이해** | [§5](#5-에이전트-루프) | — |
| 6 | **개발 자동화: 이슈 → PR** | `.claude/skills/` | `/issue-author` · `/issue-to-pr` |

**먼저, 1회만:** `uv sync`로 qf-lib(핀 고정)+의존성 설치. 그다음 `touch .env`
(로컬 `uv` 설정이 기대하는 빈 파일). Python은 3.11로 고정돼 있다.

### 구조

```
qf-lib-harness/
├── alpha_lab/      # 하네스: AST 게이트, IS/OS 백테스트, ledger, 실험
├── research/       # 데이터 파이프라인 + 수동 백테스트 + 대시보드
├── .claude/skills/ # issue-author + issue-to-pr 개발 워크플로 스킬
├── data/           # OHLCV parquet (gitignore — 머신 밖으로 안 나감)
└── pyproject.toml  # qf-lib을 외부 의존성으로 핀 고정
```

---

## 1. 데이터 받기

데이터 층은 미국 주식 OHLCV를 받아 시점(point-in-time) 유니버스를 만든다.
번호 스크립트를 순서대로 실행한다 (레포 루트에서):

```bash
uv run python research/0_smoke_test.py       # ~5초   yfinance 동작?
uv run python research/1_fetch_universe.py   # ~5초   NASDAQ/NYSE/AMEX 티커 (~7천)
uv run python research/2_download_prices.py  # 30분~2시간 일봉 OHLCV (재시작 가능)
uv run python research/3_build_universe.py   # ~30초  달러볼륨 상위 3000 PIT
uv run python research/5_quality_check.py    # 무결성 / NaN / 갭 점검
```

**산출물:** `data/prices.parquet`, `data/universe_pit_top3000.parquet`.
이후 모든 단계가 이걸 읽는다. (`data/`는 gitignore.)

## 2. 손으로 전략 작성

템플릿을 복사하고, 함수 하나를 고치고, 실행한다:

```bash
mkdir -p alpha_lab/experiments/exp_myidea
cp alpha_lab/trial_template.py alpha_lab/experiments/exp_myidea/strategy.py
```

`strategy.py`를 편집 — 상수와 `signal()`만 건드린다:

```python
REBAL = "M"              # 리밸런스: "M" | "W" | "Q"
TOP_N = 30               # 리밸런스마다 보유 종목 수 (5~200), 동일가중
WEIGHT_SCHEME = "equal"  # "equal"만 연결돼 있음
LOOKBACK_DAYS = 252      # 정보용

def signal(ctx) -> pd.DataFrame:
    # date × ticker 점수. 높을수록 bullish. NaN = 제외.
    px = ctx.adj_close
    return px.pct_change(LOOKBACK_DAYS).shift(21)   # ← 여기에 당신의 아이디어
```

`ctx`가 제공하는 것 (모두 date × ticker): `adj_close`, `open/high/low`,
`volume`, `dollar_volume`, `universe`. **두 가지 하드 룰** (자동 거부): 미래
바 금지(`.shift(-N)` 금지), 파일 읽기 금지(`pd.read_*`/`open()` 금지 — 데이터는
오직 `ctx`로).

실행:

```bash
uv run python -m alpha_lab run --strategy alpha_lab/experiments/exp_myidea/strategy.py
```

## 3. 프롬프트로 전략 작성 (AI 에이전트)

손으로 안 써도 된다. **AI 코딩 에이전트(Claude Code)를 이 레포에 붙이고 루프를
시작하라고 하면** — 에이전트가 전략을 직접 만들어낸다.

```bash
cd qf-lib-harness
claude            # 그다음: "alpha_lab 루프 시작해."
```

`alpha_lab/CLAUDE.md`가 에이전트의 **계약서**다: 에이전트는 오직
`alpha_lab/experiments/exp_<id>/strategy.py`만 생성/수정할 수 있다. 코어
(`core.py`, `pipeline.py`)는 **동결**돼 있고, AST 게이트가 전략 실행 전에 모든
look-ahead를 하드 거부한다 — 그래서 에이전트는 속이거나 엔진을 깰 수 없다.

## 4. 결과 보기 — ledger & 대시보드

두 가지 뷰, 두 가지 소스:

```bash
# A) 루프 결과 — 매 실행이 alpha_lab/alpha_ledger.jsonl 에 한 줄 추가
uv run python -m alpha_lab status --last 20
```

```
PASS = Sharpe_IS > 0.5  AND  Sharpe_OS > 0.5 × Sharpe_IS
```

```bash
# B) 시각 대시보드 — 전체 백테스트의 인터랙티브 Plotly tearsheet
uv run python research/dashboard.py        # → http://localhost:8765
```

대시보드는 `research/output/backtesting/`(`research/run_tsmom_backtest.py`가
생성)의 상세 tearsheet를 렌더링한다. `status` CLI는 에이전트 루프 ledger의 빠른
텍스트 뷰다.

## 5. 에이전트 루프

이 하네스는 멈추지 않는 촘촘한 리서치 루프로 돌도록 만들어졌다:

```
LOOP FOREVER:
  1. ledger 읽기            (status --last 20: 뭘 시도했고 뭐가 통과했나)
  2. 팩터 아이디어 고르기    (모멘텀, 리버설, 저변동성, 유동성, …)
  3. 베이스 선택            (현재 최고 / 아쉬운 케이스 / 템플릿 / 처음부터)
  4. strategy.py 작성       (템플릿 cp → signal() + alpha-meta 헤더 편집)
  5. 실행                   (alpha_lab run … > run.log)
  6. 판정 읽기              (pass / fail / crash → ledger 행)
  7. 1로 돌아가기
```

**ledger가 곧 기억**이다 — git diff(무엇이 바뀌었나)와 ledger 행(어떤 점수였나)이
교훈이다. 루프는 사람이 중단하거나 어떤 전략이 `sharpe_is > 1.5`를 넘을 때까지
돈다. 전체 계약: **`alpha_lab/CLAUDE.md`**.

## 6. 스킬 — 이슈 → PR 자동화

`.claude/skills/`의 **독립된** Claude Code 스킬 2개가 목표를 GitHub 이슈로,
다시 이슈를 PR로 바꾼다 — 서로 코드로 안 엮이고 **GitHub Issues로만** 통신.
Claude Code 세션에서 각각 따로 invoke한다:

```text
/issue-author    # 목표/스펙 → epic → feature → task 이슈 (needs-human 플래그 포함)
/issue-to-pr     # ready task 이슈 → 브랜치 → 테스트 → PR 생성 (사람 머지 대기에서 멈춤)
```

| 스킬 | 하는 일 | 멈추는 곳 |
|---|---|---|
| **`issue-author`** | 목표를 **epic → feature → task** 트리로 분해·그룹핑·연결(sub-issue)하고, 사람 검증이 필요한 것에 `needs-human` 표시. **발행 전 트리를 보여주고 승인받는다.** | GitHub에 이슈 생성 |
| **`issue-to-pr`** | **ready** task를 골라(`needs-human` 건너뜀, `Depends on #N` 대기) 브랜치에 구현하고 테스트 후 PR 생성(`Closes #N`). | PR 생성 — **사람이 머지** |

```
목표 ─► /issue-author ─► GitHub Issues ─► /issue-to-pr ─► PR ─► (사람 머지)
                              ▲
                  여기서 사람이 검토/수정/needs-human 지정
```

공유 규약(라벨, sub-issue 계층, `Depends on #N`, `## Verify`, needs-human 기준)은
**`.claude/skills/CONVENTIONS.md`**에 있다. `issue-to-pr`는 규약만 맞으면 *손으로
만든 이슈를 포함해* 어떤 이슈든 처리한다.

---

## 전체가 맞물리는 방식

```
전략 (사람 또는 에이전트) ─► alpha_lab (AST 게이트 ─► 백테스트 ─► IS/OS 슬라이스 ─► ledger)
                                            │
                                   data/prices.parquet ◄── research/ 데이터 파이프라인 (§1)
                                            │
                                         qf-lib ◄── 엔진, 핀 고정된 의존성
```

**qf-lib은 여기에 vendoring돼 있지 않다** — `pyproject.toml`
(`[tool.uv.sources]`, 포크 master `9ba5a0f`)에 외부 의존성으로 핀 고정되고
`uv.lock`에 잠긴다. 엔진을 올리려면 rev를 bump하고 `uv lock`. 로컬에서 고치려면
주석 처리된 `editable` 줄로 전환. 모든 결과는 *(qf-lib 커밋) × (데이터) ×
(실험)* 으로 추적된다.

### 백테스트: 기본값은 벡터화

에이전트 루프의 백테스트(`alpha_lab/pipeline.py`)는 **벡터화**돼 있다 — 일별
PnL이 행렬연산 한 방(전일 top-N membership × 수익률)이라, 실험 1개가 수 분이
아니라 **약 2초** 만에 end-to-end로 돈다. look-ahead는 안전하지만 **거래비용·
슬리피지는 무시**하므로 보고되는 Sharpe는 약간 낙관적이다 — 넓게 *탐색*하는
용도. event-driven qf-lib 경로(`_run_qf_backtest`, IB 커미션 포함)는 후보로
좁혀진 전략의 **거래비용 현실검증**용으로 남겨뒀고, `research/run_tsmom_backtest.py`
가 대시보드 tearsheet 생성에 여전히 이 경로를 쓴다. 전략 계약은 그대로다:
`signal(ctx)`는 `date × ticker` 점수 매트릭스를 반환한다.
