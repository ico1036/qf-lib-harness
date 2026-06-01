<p align="right">
  <a href="README.md">English</a> ·
  <a href="README_KO.md">한국어</a> ·
  <a href="README_ZH.md">中文</a> ·
  <strong>Français</strong>
</p>

# qf-lib-harness

> **Recherche d'alpha autonome, uniquement à partir des prix**, sur les actions
> américaines. Écrivez une stratégie — à la main ou avec un agent IA — passez-la
> dans un filtre in-sample / out-of-sample à l'épreuve du look-ahead, lisez le
> verdict. C'est une itération.

## Ce que vous pouvez faire ici

| # | Objectif | Où | Commande |
|---|---|---|---|
| 1 | **Obtenir les données** | `research/` | `uv run python research/1_fetch_universe.py …` |
| 2 | **Écrire une stratégie à la main** | `alpha_lab/experiments/exp_<id>/strategy.py` | `uv run python -m alpha_lab run …` |
| 3 | **Laisser un agent IA écrire des stratégies** | `alpha_lab/CLAUDE.md` (le contrat) | pointez Claude Code vers le dépôt |
| 4 | **Voir les résultats** | ledger + tableau de bord | `uv run python -m alpha_lab status` · `uv run python research/dashboard.py` |
| 5 | **Comprendre la boucle de l'agent** | [§5](#5-la-boucle-de-lagent) | — |

**D'abord, une seule fois :** `uv sync` installe qf-lib (épinglé) + les
dépendances. Puis `touch .env` (un fichier vide attendu par la config `uv`
locale). Python est épinglé à 3.11.

### Structure

```
qf-lib-harness/
├── alpha_lab/      # le moteur : filtre AST, backtest IS/OS, ledger, expériences
├── research/       # pipeline de données + backtests manuels + tableau de bord
├── data/           # parquet OHLCV (gitignoré, ne quitte jamais votre machine)
└── pyproject.toml  # qf-lib épinglé comme dépendance externe
```

---

## 1. Obtenir les données

La couche de données télécharge l'OHLCV des actions américaines et construit un
univers point-in-time. Lancez les scripts numérotés dans l'ordre (depuis la
racine du dépôt) :

```bash
uv run python research/0_smoke_test.py       # ~5s    yfinance fonctionne ?
uv run python research/1_fetch_universe.py   # ~5s    tickers NASDAQ/NYSE/AMEX (~7k)
uv run python research/2_download_prices.py  # 30m–2h OHLCV quotidien (reprenable)
uv run python research/3_build_universe.py   # ~30s   top-3000 PIT par volume en dollars
uv run python research/5_quality_check.py    # cohérence / NaN / trous
```

**Sortie :** `data/prices.parquet` et `data/universe_pit_top3000.parquet`.
Tout l'aval lit ces fichiers. (`data/` est gitignoré.)

## 2. Écrire une stratégie à la main

Copiez le modèle, modifiez une fonction, lancez-la :

```bash
mkdir -p alpha_lab/experiments/exp_myidea
cp alpha_lab/trial_template.py alpha_lab/experiments/exp_myidea/strategy.py
```

Éditez `strategy.py` — vous ne touchez qu'aux constantes et à `signal()` :

```python
REBAL = "M"              # rééquilibrage : "M" | "W" | "Q"
TOP_N = 30               # titres détenus par rééquilibrage (5–200), équipondérés
WEIGHT_SCHEME = "equal"  # seul "equal" est branché
LOOKBACK_DAYS = 252      # informatif

def signal(ctx) -> pd.DataFrame:
    # scores date × ticker. plus haut = plus haussier. NaN = exclure.
    px = ctx.adj_close
    return px.pct_change(LOOKBACK_DAYS).shift(21)   # ← votre idée ici
```

`ctx` fournit (tout en date × ticker) : `adj_close`, `open/high/low`, `volume`,
`dollar_volume`, `universe`. **Deux règles strictes** (rejet automatique) : pas
de barres futures (`.shift(-N)` interdit), pas de lecture de fichiers
(`pd.read_*`/`open()` interdits — les données viennent uniquement de `ctx`).

Lancez :

```bash
uv run python -m alpha_lab run --strategy alpha_lab/experiments/exp_myidea/strategy.py
```

## 3. Écrire des stratégies par prompt (agent IA)

Vous n'êtes pas obligé d'écrire à la main. **Pointez un agent de codage IA
(Claude Code) vers ce dépôt et demandez-lui de lancer la boucle** — il invente
des stratégies pour vous.

```bash
cd qf-lib-harness
claude            # puis : "Start the alpha_lab loop."
```

`alpha_lab/CLAUDE.md` est le **contrat** de l'agent : il ne peut que créer/éditer
`alpha_lab/experiments/exp_<id>/strategy.py`. Le cœur (`core.py`, `pipeline.py`)
est **gelé**, et un filtre AST rejette d'emblée tout look-ahead avant qu'une
stratégie puisse tourner — l'agent ne peut donc ni tricher ni casser le moteur.
L'agent copie le modèle, écrit un `signal()`, le lance, lit le ledger, et itère
(voir §5).

## 4. Voir les résultats — ledger & tableau de bord

Deux vues, deux sources :

```bash
# A) Résultats de la boucle — chaque exécution ajoute une ligne à alpha_lab/alpha_ledger.jsonl
uv run python -m alpha_lab status --last 20
```

```
PASS = Sharpe_IS > 0.5  AND  Sharpe_OS > 0.5 × Sharpe_IS
```

```bash
# B) Tableau de bord visuel — tearsheets Plotly interactifs des backtests complets
uv run python research/dashboard.py        # → http://localhost:8765
```

Le tableau de bord affiche les tearsheets détaillés de
`research/output/backtesting/` (produits par `research/run_tsmom_backtest.py`) ;
la CLI `status` est la vue texte rapide du ledger de la boucle de l'agent.

## 5. La boucle de l'agent

Le moteur est conçu pour tourner en boucle de recherche serrée et sans arrêt :

```
LOOP FOREVER:
  1. Lire le ledger         (status --last 20 : ce qui a été tenté, ce qui a passé)
  2. Choisir une idée de facteur (momentum, reversal, faible vol, liquidité, …)
  3. Choisir une base       (meilleure actuelle / quasi-réussite / modèle / from scratch)
  4. Écrire strategy.py     (cp modèle → éditer signal() + en-tête alpha-meta)
  5. Lancer                 (alpha_lab run … > run.log)
  6. Lire le verdict        (pass / fail / crash → ligne du ledger)
  7. Revenir à l'étape 1
```

**Le ledger est la mémoire** — pas de fichier de notes séparé. Le diff git (ce
qui a changé) et la ligne du ledger (le score obtenu) sont la leçon. La boucle
tourne jusqu'à ce qu'un humain l'interrompe ou qu'une stratégie dépasse
`sharpe_is > 1.5`.

Contrat complet — l'API `signal`, les champs `ctx`, les dates IS/OS verrouillées,
le menu des facteurs : **`alpha_lab/CLAUDE.md`**.

---

## Comment tout s'articule

```
stratégie (vous ou agent) ─► alpha_lab (filtre AST ─► backtest ─► découpe IS/OS ─► ledger)
                                            │
                                   data/prices.parquet ◄── pipeline de données research/ (§1)
                                            │
                                         qf-lib ◄── le moteur, dépendance épinglée
```

**qf-lib n'est pas vendorisé ici** — il est épinglé comme dépendance externe
dans `pyproject.toml` (`[tool.uv.sources]`, fork master `9ba5a0f`) et verrouillé
dans `uv.lock`. Pour mettre à jour le moteur, changez le rev et `uv lock`. Pour
l'éditer en local, basculez sur la ligne `editable` commentée. Chaque résultat
est traçable à *(commit qf-lib) × (données) × (expérience)*.
