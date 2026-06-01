"""Backtest dashboard — list of runs + interactive Plotly detail view.

All numbers come from qf-lib's TimeseriesAnalysis; charts are rendered with
Plotly using the same source series so the figures are interactive but the
underlying data is exactly the values the PDF tearsheet shows.

Run:
    uv run python research/dashboard.py
Then open http://localhost:8765
"""
from __future__ import annotations

import os
from functools import lru_cache
from pathlib import Path

import numpy as np
import pandas as pd
import plotly.graph_objects as go
import scipy.stats as stats
from nicegui import app, ui

_HERE = Path(__file__).parent.resolve()
os.environ.setdefault("QF_STARTING_DIRECTORY", str(_HERE))

import qf_lib.plotting  # noqa: F401, E402  # registers tearsheet mplstyle
from qf_lib.analysis.timeseries_analysis.timeseries_analysis import TimeseriesAnalysis  # noqa: E402
from qf_lib.containers.series.prices_series import PricesSeries  # noqa: E402

OUTPUT_DIR = _HERE / "output" / "backtesting"

# ----- style -----
C_PRIMARY = "#1f3a8a"
C_GREY = "#6b7280"
C_TEXT = "#0f172a"
AXIS = dict(showgrid=True, gridcolor="#e5e7eb", linecolor="#9ca3af",
            zerolinecolor="#cbd5e1", zerolinewidth=1, ticks="outside",
            tickcolor="#9ca3af")
TITLE = dict(font=dict(size=14, color=C_TEXT), x=0.02, xanchor="left")
H_HERO, H_FULL, H_HALF, H_DD = 340, 300, 320, 240


def make_fig(title: str, height: int = H_FULL) -> go.Figure:
    fig = go.Figure()
    fig.update_layout(
        template="plotly_white",
        font=dict(family="Inter,system-ui,-apple-system,sans-serif", size=12, color=C_TEXT),
        paper_bgcolor="white", plot_bgcolor="white",
        margin=dict(l=55, r=20, t=40, b=40),
        title=dict(text=title, **TITLE),
        xaxis=AXIS, yaxis=AXIS,
        legend=dict(orientation="h", yanchor="bottom", y=1.02, xanchor="right", x=1,
                    bgcolor="rgba(255,255,255,0.8)"),
        hoverlabel=dict(bgcolor="white", bordercolor="#cbd5e1", font_size=12),
        height=height,
    )
    return fig


# ----- run discovery / loading -----

def scan_runs() -> list[dict]:
    if not OUTPUT_DIR.exists():
        return []
    runs = []
    for d in sorted(OUTPUT_DIR.iterdir(), reverse=True):
        if not d.is_dir():
            continue
        ts_xlsx = next(d.glob("*Timeseries.xlsx"), None)
        if not ts_xlsx:
            continue
        ts_str, _, name = d.name.partition(" ")
        runs.append(dict(id=d.name, name=name or d.name, ts_str=ts_str,
                         path=d, ts_xlsx=ts_xlsx))
    return runs


@lru_cache(maxsize=64)
def load_strategy_series(ts_xlsx_str: str, name: str) -> PricesSeries:
    df = pd.read_excel(ts_xlsx_str, sheet_name="Sheet")
    df = df.rename(columns={df.columns[0]: "date"})
    s = df.set_index("date").iloc[:, 0]
    s.index = pd.to_datetime(s.index)
    series = PricesSeries(s.sort_index())
    series.name = name
    return series


# ----- statistics: same fields, same order, same format as the PDF -----

def _fmt(x, places: int = 2) -> str:
    if x is None or (isinstance(x, float) and np.isnan(x)):
        return "—"
    return f"{x:.{places}f}"


def stats_rows(series: PricesSeries) -> list[tuple[str, str, str]]:
    ta = TimeseriesAnalysis(series.to_simple_returns(), series.get_frequency())
    return [
        ("Start Date", ta.start_date.strftime("%Y-%m-%d"), ""),
        ("End Date", ta.end_date.strftime("%Y-%m-%d"), ""),
        ("Total Return", _fmt(ta.total_return * 100), "%"),
        ("Annualised Return", _fmt(ta.cagr * 100), "%"),
        ("Annualised Volatility", _fmt(ta.annualised_vol * 100), "%"),
        ("Annualised Upside Vol.", _fmt(ta.annualised_upside_vol * 100), "%"),
        ("Annualised Downside Vol.", _fmt(ta.annualised_downside_vol * 100), "%"),
        ("Sharpe Ratio", _fmt(ta.sharpe_ratio), ""),
        ("Omega Ratio", _fmt(ta.omega_ratio), ""),
        ("Calmar Ratio", _fmt(ta.calmar_ratio), ""),
        ("Gain to Pain Ratio", _fmt(ta.gain_to_pain_ratio), ""),
        ("Sorino Ratio", _fmt(ta.sorino_ratio), ""),
        ("5% CVaR", _fmt(ta.cvar * 100), "%"),
        ("Annualised 5% CVaR", _fmt(ta.annualised_cvar * 100), "%"),
        ("Max Drawdown", _fmt(ta.max_drawdown * 100), "%"),
        ("Avg Drawdown", _fmt(ta.avg_drawdown * 100), "%"),
        ("Avg Drawdown Duration", _fmt(ta.avg_drawdown_duration), "days"),
        ("Best Return", _fmt(ta.best_return * 100), "%"),
        ("Worst Return", _fmt(ta.worst_return * 100), "%"),
        ("Avg Positive Return", _fmt(ta.avg_positive_return * 100), "%"),
        ("Avg Negative Return", _fmt(ta.avg_negative_return * 100), "%"),
        ("Skewness", _fmt(ta.skewness), ""),
        ("No. of daily samples", str(len(ta.returns_tms)), ""),
    ]


def double_check(series: PricesSeries) -> list[dict]:
    """Compute headline numbers two ways and report agreement."""
    ta = TimeseriesAnalysis(series.to_simple_returns(), series.get_frequency())
    rets = series.pct_change().dropna()
    norm = series / series.iloc[0]
    log_rets = np.log(series / series.shift(1)).dropna()  # qf-lib uses log returns for vol

    pairs = [
        ("Total Return [%]",        ta.total_return * 100,    (norm.iloc[-1] - 1) * 100),
        ("Max Drawdown [%]",        ta.max_drawdown * 100,    abs((norm / norm.cummax() - 1).min()) * 100),
        ("Annualised Volatility [%]", ta.annualised_vol * 100, log_rets.std(ddof=1) * np.sqrt(252) * 100),
        ("Skewness",                ta.skewness,              rets.skew()),
        ("Best daily return [%]",   ta.best_return * 100,     rets.max() * 100),
        ("Worst daily return [%]",  ta.worst_return * 100,    rets.min() * 100),
    ]
    return [
        dict(label=label, pdf=f"{q:.4f}", chart=f"{c:.4f}",
             diff=f"{abs(q - c):.6f}", ok=abs(q - c) < 0.01)
        for label, q, c in pairs
    ]


# ----- chart builders -----

def _monthly_simple_returns(series: PricesSeries) -> pd.Series:
    return series.resample("ME").last().pct_change().dropna()


def fig_strategy_performance(series: PricesSeries) -> go.Figure:
    norm = series / series.iloc[0]
    fig = make_fig("Strategy Performance", height=H_HERO)
    fig.update_layout(yaxis=dict(title=None))
    fig.add_trace(go.Scatter(x=norm.index, y=norm.values, name=str(series.name),
                             line=dict(color=C_PRIMARY, width=1.6),
                             hovertemplate="%{x|%Y-%m-%d}<br>×%{y:.3f}<extra></extra>"))
    fig.add_hline(y=1.0, line_color="black", line_width=0.7)
    return fig


def fig_monthly_heatmap(series: PricesSeries) -> go.Figure:
    monthly = _monthly_simple_returns(series) * 100
    df = pd.DataFrame({"year": monthly.index.year, "month": monthly.index.month, "ret": monthly.values})
    grid = df.pivot(index="year", columns="month", values="ret").reindex(columns=range(1, 13)).sort_index()
    months = ["Jan","Feb","Mar","Apr","May","Jun","Jul","Aug","Sep","Oct","Nov","Dec"]
    abs_max = np.nanmax(np.abs(grid.values))
    text = [[f"{v:.1f}" if pd.notna(v) else "" for v in row] for row in grid.values]

    fig = make_fig(f"Monthly Returns - {series.name}", height=H_HALF)
    fig.update_layout(
        xaxis=dict(showgrid=False),
        yaxis=dict(showgrid=False, autorange="reversed", tickmode="linear", dtick=1),
    )
    fig.add_trace(go.Heatmap(
        z=np.where(np.isnan(grid.values), 0, grid.values),
        x=months, y=grid.index.astype(int), text=text, texttemplate="%{text}",
        colorscale=[[0, "#b91c1c"], [0.5, "#ffffff"], [1, "#1f3a8a"]],
        zmid=0, zmin=-abs_max, zmax=abs_max,
        textfont=dict(size=10),
        hovertemplate="%{y} %{x}: %{z:.2f}%<extra></extra>",
        colorbar=dict(thickness=10, len=0.7, ticksuffix="%"),
    ))
    return fig


def fig_annual_returns(series: PricesSeries) -> go.Figure:
    annual = series.resample("YE").last().pct_change().dropna() * 100
    mean_ret = float(annual.mean())
    fig = make_fig(f"Annual Returns - {series.name}", height=H_HALF)
    fig.update_layout(xaxis=dict(ticksuffix="%"), yaxis=dict(autorange="reversed"),
                      showlegend=False)
    fig.add_trace(go.Bar(
        x=annual.values, y=annual.index.year.astype(str), orientation="h",
        marker_color=C_PRIMARY, text=[f"{v:.0f}%" for v in annual.values],
        textposition="outside", cliponaxis=False,
        hovertemplate="%{y}: %{x:.2f}%<extra></extra>",
    ))
    fig.add_vline(x=mean_ret, line_dash="dash", line_color=C_GREY,
                  annotation_text=f"Mean {mean_ret:.1f}%", annotation_position="top right")
    return fig


def fig_returns_distribution(series: PricesSeries) -> go.Figure:
    monthly = _monthly_simple_returns(series) * 100
    fig = make_fig("Distribution of Monthly Returns", height=H_HALF)
    fig.update_layout(xaxis=dict(ticksuffix="%", title=None),
                      yaxis=dict(title="Occurrences"),
                      bargap=0.04, showlegend=False)
    fig.add_trace(go.Histogram(x=monthly.values, nbinsx=22,
                               marker_color=C_PRIMARY,
                               marker_line=dict(color="white", width=0.5),
                               hovertemplate="%{x:.1f}%: %{y}<extra></extra>"))
    fig.add_vline(x=float(monthly.mean()), line_dash="dash", line_color=C_GREY,
                  annotation_text="Mean", annotation_position="top right")
    return fig


def fig_qq(series: PricesSeries) -> go.Figure:
    rets = series.pct_change().dropna() * 100
    osm, osr = stats.probplot(rets.values, dist="norm", fit=False)
    slope, intercept, *_ = stats.linregress(osm, osr)
    fig = make_fig("Normal Distribution Q-Q", height=H_HALF)
    fig.update_layout(xaxis=dict(title="Normal Distribution Quantile"),
                      yaxis=dict(title="Observed Quantile"))
    fig.add_trace(go.Scatter(x=osm, y=osr, mode="markers", name="Observed",
                             marker=dict(color=C_PRIMARY, size=4, opacity=0.7),
                             hovertemplate="N=%{x:.2f}<br>Obs=%{y:.2f}<extra></extra>"))
    fig.add_trace(go.Scatter(x=[osm.min(), osm.max()],
                             y=[slope * osm.min() + intercept, slope * osm.max() + intercept],
                             mode="lines", name="Normal", hoverinfo="skip",
                             line=dict(color=C_GREY, width=1.5)))
    return fig


def fig_rolling_stats(series: PricesSeries, window: int = 126, step: int = 42) -> go.Figure:
    rets = series.pct_change().dropna()
    points = []
    for i in range(window, len(rets) + 1, step):
        w = rets.iloc[i - window:i]
        cum = float((1 + w).prod() - 1) * 100
        vol = float(w.std() * np.sqrt(252)) * 100
        points.append((rets.index[i - 1], cum, vol))
    df = pd.DataFrame(points, columns=["date", "ret", "vol"])
    fig = make_fig(f"Rolling Stats [{window} daily samples]", height=H_FULL)
    fig.update_layout(yaxis=dict(ticksuffix="%"))
    fig.add_trace(go.Scatter(x=df["date"], y=df["ret"], name="Rolling Return",
                             line=dict(color=C_PRIMARY, width=1.6),
                             hovertemplate="%{x|%Y-%m-%d}<br>Return %{y:.2f}%<extra></extra>"))
    fig.add_trace(go.Scatter(x=df["date"], y=df["vol"], name="Rolling Volatility",
                             line=dict(color=C_GREY, width=1.4),
                             hovertemplate="%{x|%Y-%m-%d}<br>Vol %{y:.2f}%<extra></extra>"))
    fig.add_hline(y=0, line_color="black", line_width=0.7)
    return fig


def fig_cone(series: PricesSeries, nr_of_data_points: int = 252) -> go.Figure:
    """Project pre-IS-end log-return mean/sigma onto OOS window with ±1σ/±2σ bands."""
    is_end = max(2, len(series) - nr_of_data_points)
    log_rets = np.log(1 + series.iloc[:is_end].pct_change().dropna())
    mu, sigma = float(log_rets.mean()), float(log_rets.std())

    oos = series.iloc[is_end - 1:].copy()
    oos = oos / oos.iloc[0]
    days = np.arange(len(oos))
    expected = np.exp(mu * days)
    upper1 = np.exp(mu * days + sigma * np.sqrt(days))
    lower1 = np.exp(mu * days - sigma * np.sqrt(days))
    upper2 = np.exp(mu * days + 2 * sigma * np.sqrt(days))
    lower2 = np.exp(mu * days - 2 * sigma * np.sqrt(days))

    fig = make_fig("Performance vs. Expectation", height=H_HALF)
    fig.update_layout(xaxis=dict(title="Observations in the past"),
                      yaxis=dict(title="Current valuation"))
    blank = dict(line=dict(width=0), showlegend=False, hoverinfo="skip")
    fig.add_trace(go.Scatter(x=days, y=upper2, **blank))
    fig.add_trace(go.Scatter(x=days, y=lower2, fill="tonexty",
                             fillcolor="rgba(148,163,184,0.18)", **blank))
    fig.add_trace(go.Scatter(x=days, y=upper1, **blank))
    fig.add_trace(go.Scatter(x=days, y=lower1, fill="tonexty",
                             fillcolor="rgba(148,163,184,0.30)", **blank))
    fig.add_trace(go.Scatter(x=days, y=expected, name="Expected",
                             line=dict(color=C_GREY, width=1.5)))
    fig.add_trace(go.Scatter(x=days, y=oos.values, name="Current valuation",
                             line=dict(color=C_PRIMARY, width=1.7),
                             hovertemplate="t=%{x}<br>×%{y:.3f}<extra></extra>"))
    return fig


def fig_quantiles(series: PricesSeries) -> go.Figure:
    daily = series.pct_change().dropna()
    weekly = series.resample("W").last().pct_change().dropna()
    monthly = _monthly_simple_returns(series)
    fig = make_fig("Return Quantiles", height=H_HALF)
    fig.update_layout(yaxis=dict(title="returns", tickformat=".2f"))
    for name, data in [("daily", daily), ("weekly", weekly), ("monthly", monthly)]:
        fig.add_trace(go.Box(y=data.values, name=name, marker_color=C_PRIMARY,
                             line=dict(color=C_PRIMARY), boxmean=False,
                             boxpoints="outliers", showlegend=False))
    return fig


def fig_underwater(series: PricesSeries) -> go.Figure:
    norm = series / series.iloc[0]
    dd = (norm / norm.cummax() - 1) * 100
    fig = make_fig("Drawdown", height=H_DD)
    fig.update_layout(yaxis=dict(ticksuffix="%"), showlegend=False)
    fig.add_trace(go.Scatter(x=dd.index, y=dd.values, fill="tozeroy",
                             line=dict(color=C_PRIMARY, width=1),
                             fillcolor="rgba(31, 58, 138, 0.45)",
                             name="Drawdown",
                             hovertemplate="%{x|%Y-%m-%d}<br>DD %{y:.2f}%<extra></extra>"))
    return fig


def fig_skewness(series: PricesSeries) -> go.Figure:
    rets = series.pct_change().dropna()
    chrono = (1 + rets).cumprod()
    sorted_cum = (1 + rets.sort_values().reset_index(drop=True)).cumprod()
    sorted_cum.index = chrono.index
    fig = make_fig("Skewness", height=H_HALF)
    fig.update_layout(yaxis=dict(title="Profit/Loss"))
    fig.add_trace(go.Scatter(x=chrono.index, y=chrono.values, name="Chronological returns",
                             line=dict(color=C_PRIMARY, width=1.6),
                             hovertemplate="%{x|%Y-%m-%d}<br>×%{y:.3f}<extra></extra>"))
    fig.add_trace(go.Scatter(x=sorted_cum.index, y=sorted_cum.values,
                             name="Returns sorted by magnitude",
                             line=dict(color=C_GREY, width=1.4),
                             hovertemplate="t=%{x|%Y-%m-%d}<br>×%{y:.3f}<extra></extra>"))
    return fig


# ----- UI -----

_PAGE_CSS = """
<style>
  body{background:#f7f8fa;color:#0f172a;
       font-family:Inter,-apple-system,system-ui,'Segoe UI',Roboto,sans-serif;}
  .qf-card{background:#ffffff;border:1px solid #e5e7eb;border-radius:6px;padding:14px 18px;}
  .qf-section-h{font-size:11px;letter-spacing:0.10em;text-transform:uppercase;
                color:#475569;font-weight:600;
                border-bottom:1px solid #e5e7eb;padding-bottom:6px;margin-bottom:10px;}
  .qf-mono{font-family:ui-monospace,Menlo,Monaco,Consolas,monospace;font-size:12px;}
  .stats-table{width:100%;border-collapse:collapse;font-size:13px;}
  .stats-table th{text-align:left;padding:8px 14px;background:#f1f5f9;color:#334155;
                  font-weight:600;border-bottom:1px solid #cbd5e1;}
  .stats-table td{padding:7px 14px;border-bottom:1px solid #e5e7eb;}
  .stats-table td.value{text-align:right;font-variant-numeric:tabular-nums;}
  .stats-table tr:nth-child(odd) td{background:#fafbfc;}
  table.q-table thead th{background:#f1f5f9!important;color:#334155!important;font-weight:600;}
  table.q-table tbody tr:hover{background:#eff6ff!important;cursor:pointer;}
  .verify-row, .verify-head{display:grid;grid-template-columns:1fr 120px 120px 110px 70px;
                            gap:8px;padding:6px 0;}
  .verify-head{font-size:11px;letter-spacing:0.06em;text-transform:uppercase;
               color:#64748b;font-weight:600;border-bottom:1px solid #cbd5e1;}
  .verify-row{font-size:13px;border-bottom:1px dashed #e5e7eb;}
  .verify-row .num{text-align:right;font-variant-numeric:tabular-nums;
                   font-family:ui-monospace,Menlo,Monaco,monospace;}
  .verify-ok{color:#15803d;font-weight:600;}
  .verify-bad{color:#b91c1c;font-weight:600;}
</style>
"""


def _section(title: str):
    container = ui.element("div").classes("qf-card w-full")
    with container:
        ui.label(title).classes("qf-section-h")
    return container


def _full(title: str, fig: go.Figure) -> None:
    with _section(title):
        ui.plotly(fig).classes("w-full")


def _pair(left_title: str, left_fig: go.Figure,
          right_title: str, right_fig: go.Figure) -> None:
    with ui.row().classes("w-full gap-3"):
        with _section(left_title).classes("flex-1 min-w-0"):
            ui.plotly(left_fig).classes("w-full")
        with _section(right_title).classes("flex-1 min-w-0"):
            ui.plotly(right_fig).classes("w-full")


@ui.page("/")
def home() -> None:
    ui.add_head_html(_PAGE_CSS)
    with ui.column().classes("w-full max-w-screen-2xl mx-auto p-8 gap-4"):
        ui.label("QF-Lib Backtest Dashboard").classes("text-3xl font-semibold tracking-tight")
        ui.label("Click a row to drill into the same charts and statistics as the auto-generated PDF tearsheet."
                 ).classes("text-sm text-slate-500")

        rows = []
        for r in scan_runs():
            row = dict(id=r["id"], name=r["name"], ts=r["ts_str"])
            try:
                series = load_strategy_series(str(r["ts_xlsx"]), r["name"])
                m = {label: f"{v} {u}".strip() for label, v, u in stats_rows(series)}
                row.update(start=m["Start Date"], end=m["End Date"],
                           total=m["Total Return"], ann=m["Annualised Return"],
                           sharpe=m["Sharpe Ratio"], max_dd=m["Max Drawdown"],
                           skew=m["Skewness"])
            except Exception:
                row.update(start="—", end="—", total="—", ann="—",
                           sharpe="—", max_dd="—", skew="—")
            rows.append(row)

        cols = [
            {"name": "name", "label": "Strategy", "field": "name", "align": "left", "sortable": True},
            {"name": "ts", "label": "Run", "field": "ts", "sortable": True},
            {"name": "start", "label": "Start", "field": "start"},
            {"name": "end", "label": "End", "field": "end"},
            {"name": "total", "label": "Total Return", "field": "total", "sortable": True},
            {"name": "ann", "label": "Annualised", "field": "ann", "sortable": True},
            {"name": "sharpe", "label": "Sharpe", "field": "sharpe", "sortable": True},
            {"name": "max_dd", "label": "Max DD", "field": "max_dd", "sortable": True},
            {"name": "skew", "label": "Skew", "field": "skew"},
        ]

        with ui.element("div").classes("qf-card w-full"):
            with ui.row().classes("w-full items-center gap-3 mb-2"):
                ui.icon("query_stats").classes("text-slate-500")
                ui.label(f"{len(rows)} backtest runs").classes("text-sm text-slate-600 font-medium")
                search = ui.input(placeholder="Filter by strategy name...") \
                    .classes("ml-auto").props("dense outlined clearable")
            table = ui.table(columns=cols, rows=rows, row_key="id").classes("w-full")
            table.props('dense flat separator="horizontal"')
            table.bind_filter_from(search, "value")
            table.on("rowClick", lambda e: ui.navigate.to(f"/run/{e.args[1]['id']}"))


@ui.page("/run/{run_id}")
def detail(run_id: str) -> None:
    ui.add_head_html(_PAGE_CSS)
    with ui.column().classes("w-full max-w-screen-2xl mx-auto p-8 gap-3"):
        with ui.row().classes("w-full items-center gap-2"):
            ui.button(icon="arrow_back", on_click=lambda: ui.navigate.to("/")).props("flat round")
            ui.label("Backtests").classes("text-sm text-slate-500")
            ui.label("/").classes("text-sm text-slate-400")
            ui.label(run_id).classes("qf-mono text-sm text-slate-600")

        run = next((r for r in scan_runs() if r["id"] == run_id), None)
        if run is None:
            ui.label("Run not found").classes("text-xl text-red-600")
            return

        series = load_strategy_series(str(run["ts_xlsx"]), run["name"])
        rows = stats_rows(series)
        rows_dict = {label: (value, unit) for label, value, unit in rows}

        # ----- header (CERN-style) -----
        with ui.element("div").classes("qf-card w-full"):
            with ui.row().classes("w-full items-baseline justify-between"):
                with ui.column().classes("gap-0"):
                    ui.label("US Universe Research").classes(
                        "text-sm font-semibold tracking-wide text-slate-700")
                    ui.label(run["name"]).classes("text-2xl font-bold tracking-tight")
                    ui.label(f"{rows_dict['Start Date'][0]} – {rows_dict['End Date'][0]}  "
                             f"·  {rows_dict['No. of daily samples'][0]} daily samples"
                             ).classes("text-sm text-slate-500")
                ui.label(f"Run {run['ts_str']}").classes("qf-mono text-xs text-slate-400")

        # ----- value double-check -----
        verify = double_check(series)
        with _section("Sanity check (Plotly chart series vs qf-lib TimeseriesAnalysis)"):
            ui.html(
                "<div class='verify-head'>"
                "<div>Metric</div><div class='num'>From qf-lib</div>"
                "<div class='num'>From chart series</div><div class='num'>|Δ|</div>"
                "<div class='num'>Match</div></div>"
            )
            for r in verify:
                cls, tick = ("verify-ok", "✓") if r["ok"] else ("verify-bad", "✗")
                ui.html(
                    f"<div class='verify-row'>"
                    f"<div>{r['label']}</div>"
                    f"<div class='num'>{r['pdf']}</div>"
                    f"<div class='num'>{r['chart']}</div>"
                    f"<div class='num'>{r['diff']}</div>"
                    f"<div class='num {cls}'>{tick}</div></div>"
                )
            ok_count = sum(1 for r in verify if r["ok"])
            ui.label(f"{ok_count}/{len(verify)} metrics agree to within 0.01"
                     ).classes("text-xs mt-1 text-slate-500")

        # ----- charts (PDF order) -----
        _full("Strategy Performance", fig_strategy_performance(series))
        _pair("Monthly Returns",                fig_monthly_heatmap(series),
              "Annual Returns",                 fig_annual_returns(series))
        _pair("Distribution of Monthly Returns", fig_returns_distribution(series),
              "Normal Distribution Q-Q",        fig_qq(series))
        _full("Rolling Stats", fig_rolling_stats(series))
        _pair("Performance vs. Expectation",    fig_cone(series),
              "Return Quantiles",               fig_quantiles(series))
        _pair("Drawdown",                       fig_underwater(series),
              "Skewness",                       fig_skewness(series))

        # ----- statistics table (1:1 with PDF) -----
        with _section("Statistics"):
            html = ['<table class="stats-table">',
                    f'<thead><tr><th>Statistic</th><th class="value">{run["name"]}</th></tr></thead>',
                    "<tbody>"]
            for label, value, unit in rows:
                full_label = f"{label} [{unit}]" if unit else label
                html.append(f"<tr><td>{full_label}</td><td class=\"value\">{value}</td></tr>")
            html.append("</tbody></table>")
            ui.html("".join(html))

        # ----- artifact files -----
        with _section("Artifact Files"):
            for f in sorted(p for p in run["path"].iterdir() if p.is_file()):
                icon = {".pdf": "picture_as_pdf", ".csv": "grid_on",
                        ".xlsx": "table_chart", ".yml": "settings"}.get(f.suffix.lower(), "insert_drive_file")
                with ui.row().classes("items-center gap-2"):
                    ui.icon(icon).classes("text-slate-500")
                    ui.link(f.name, f"/runs/{run_id}/{f.name}", new_tab=True).classes(
                        "qf-mono text-sm text-blue-700 hover:underline")
                    ui.label(f"{f.stat().st_size / 1024:,.0f} KB"
                             ).classes("text-xs text-slate-400 ml-auto")


app.add_static_files("/runs", str(OUTPUT_DIR))


if __name__ in {"__main__", "__mp_main__"}:
    ui.run(title="QF-Lib Dashboard", port=8765, reload=False, show=False)
