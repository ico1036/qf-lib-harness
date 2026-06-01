"""Build PIT (point-in-time) top-3000 universe by 21-day trailing dollar volume.

For each month-start trading day, rank tickers by trailing average dollar volume
over the previous 21 trading days and select top N.
"""
import pandas as pd

from config import LOOKBACK_DAYS, PIT_UNIVERSE_PATH, PRICES_PATH, REBAL_FREQ, TOP_N


def main() -> None:
    print(f"Loading prices from {PRICES_PATH} ...")
    prices = pd.read_parquet(PRICES_PATH)
    prices["date"] = pd.to_datetime(prices["date"])

    print("Pivoting to (date x ticker) dollar-volume matrix ...")
    dv = prices.pivot(index="date", columns="ticker", values="dollar_volume")
    dv = dv.sort_index()
    print(f"  shape: {dv.shape[0]:,} dates x {dv.shape[1]:,} tickers")

    print(f"Computing {LOOKBACK_DAYS}-day rolling mean dollar volume (ADV) ...")
    adv = dv.rolling(LOOKBACK_DAYS, min_periods=max(5, LOOKBACK_DAYS // 2)).mean()

    print(f"Generating rebalance dates (freq={REBAL_FREQ}) ...")
    month_starts = pd.date_range(adv.index.min(), adv.index.max(), freq=REBAL_FREQ)
    rebal_dates = []
    for d in month_starts:
        future = adv.index[adv.index >= d]
        if len(future):
            rebal_dates.append(future[0])
    print(f"  {len(rebal_dates)} rebal dates: {rebal_dates[0].date()} -> {rebal_dates[-1].date()}")

    print(f"Selecting top {TOP_N} per rebal date ...")
    parts = []
    for d in rebal_dates:
        row = adv.loc[d].dropna()
        if row.empty:
            continue
        top = row.nlargest(TOP_N)
        parts.append(
            pd.DataFrame(
                {
                    "rebal_date": d,
                    "ticker": top.index,
                    "rank": range(1, len(top) + 1),
                    "adv_21d": top.values,
                }
            )
        )

    univ = pd.concat(parts, ignore_index=True)
    univ.to_parquet(PIT_UNIVERSE_PATH)

    print(f"\nSaved {len(univ):,} (rebal_date, ticker) rows -> {PIT_UNIVERSE_PATH}")
    avg_n = univ.groupby("rebal_date").size().mean()
    print(f"Avg coverage per rebal date: {avg_n:.0f} (target {TOP_N})")
    print(f"Unique tickers across all rebal dates: {univ['ticker'].nunique():,}")


if __name__ == "__main__":
    main()
