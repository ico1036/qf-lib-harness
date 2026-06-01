"""Data quality check for prices.parquet and universe_pit_top3000.parquet."""
import pandas as pd

from config import PIT_UNIVERSE_PATH, PRICES_PATH


def section(title: str) -> None:
    print()
    print("=" * 60)
    print(title)
    print("=" * 60)


def main() -> None:
    print("Loading prices ...")
    p = pd.read_parquet(PRICES_PATH)
    p["date"] = pd.to_datetime(p["date"])
    print(f"  {len(p):,} rows, {p['ticker'].nunique():,} tickers")

    section("Per-ticker data length")
    counts = p.groupby("ticker").size()
    print(counts.describe(percentiles=[0.05, 0.25, 0.5, 0.75, 0.95]).to_string())
    short = (counts < 252).sum()
    print(f"\n  Tickers with <1yr data: {short:,} ({short / len(counts):.1%})")
    full = (counts >= 252 * 10).sum()
    print(f"  Tickers with >=10yr data: {full:,} ({full / len(counts):.1%})")

    section("NaN ratios per column")
    cols = ["Open", "High", "Low", "Close", "Volume", "dollar_volume"]
    nan_pct = (p[cols].isna().sum() / len(p) * 100).round(3)
    print(nan_pct.to_string())

    section("Anomaly check")
    zero_close = (p["Close"] <= 0).sum()
    zero_vol = (p["Volume"] <= 0).sum()
    print(f"  Close <= 0: {zero_close:,}")
    print(f"  Volume <= 0: {zero_vol:,}")
    high_lt_low = (p["High"] < p["Low"]).sum()
    print(f"  High < Low: {high_lt_low:,}")

    section("Date coverage")
    all_dates = p["date"].sort_values().unique()
    print(f"  Total unique trading dates: {len(all_dates):,}")
    print(f"  Range: {all_dates[0].date()} -> {all_dates[-1].date()}")
    # Check for unexpected gaps (>5 calendar days)
    gaps = pd.Series(all_dates[1:] - all_dates[:-1])
    big_gaps = gaps[gaps > pd.Timedelta(days=5)]
    if len(big_gaps) > 0:
        print(f"  Gaps >5 calendar days: {len(big_gaps)}")
        # Print location of biggest gaps
        for i in big_gaps.nlargest(3).index:
            print(f"    {pd.Timestamp(all_dates[i]).date()} -> {pd.Timestamp(all_dates[i+1]).date()}: {gaps[i].days}d")
    else:
        print("  No suspicious gaps")

    section("PIT universe — month-over-month turnover")
    pit = pd.read_parquet(PIT_UNIVERSE_PATH)
    pit_by_date = pit.groupby("rebal_date")["ticker"].apply(set)
    dates = pit_by_date.index.tolist()
    turnover = []
    for prev, cur in zip(dates[:-1], dates[1:]):
        prev_set = pit_by_date.loc[prev]
        cur_set = pit_by_date.loc[cur]
        added = len(cur_set - prev_set)
        removed = len(prev_set - cur_set)
        turnover.append({"date": cur, "added": added, "removed": removed,
                         "turnover_pct": (added + removed) / 2 / len(prev_set) * 100})
    tdf = pd.DataFrame(turnover)
    print(tdf["turnover_pct"].describe(percentiles=[0.05, 0.5, 0.95]).round(2).to_string())
    print(f"\n  Largest turnover months:")
    print(tdf.nlargest(5, "turnover_pct").to_string(index=False))


if __name__ == "__main__":
    main()
