"""Sanity-check the produced data files."""
import pandas as pd

from config import PIT_UNIVERSE_PATH, PRICES_PATH, UNIVERSE_PATH


def section(title: str) -> None:
    print()
    print("=" * 60)
    print(title)
    print("=" * 60)


def main() -> None:
    if UNIVERSE_PATH.exists():
        section("tickers.parquet")
        u = pd.read_parquet(UNIVERSE_PATH)
        print(f"Total tickers: {len(u):,}")
        print(f"Exchange:\n{u['exchange'].value_counts()}")
        print(f"ETF flag:\n{u['is_etf'].value_counts(dropna=False)}")
    else:
        print(f"[skip] {UNIVERSE_PATH} not found")

    if PRICES_PATH.exists():
        section("prices.parquet")
        p = pd.read_parquet(PRICES_PATH)
        print(f"Total rows: {len(p):,}")
        print(f"Unique tickers: {p['ticker'].nunique():,}")
        print(f"Date range: {p['date'].min().date()} -> {p['date'].max().date()}")
        print(f"Memory: {p.memory_usage(deep=True).sum() / 1e6:.1f} MB")
    else:
        print(f"[skip] {PRICES_PATH} not found")

    if PIT_UNIVERSE_PATH.exists():
        section("universe_pit_top3000.parquet")
        pit = pd.read_parquet(PIT_UNIVERSE_PATH)
        print(f"Total rows: {len(pit):,}")
        print(f"Rebal dates: {pit['rebal_date'].nunique()}")
        print(f"Unique tickers across history: {pit['ticker'].nunique():,}")
        avg = pit.groupby("rebal_date").size().mean()
        print(f"Avg coverage: {avg:.0f}")

        last = pit["rebal_date"].max()
        print(f"\nLatest rebal ({last.date()}) -- top 10:")
        latest = pit[pit["rebal_date"] == last].nsmallest(10, "rank")
        print(latest[["rank", "ticker", "adv_21d"]].to_string(index=False))
    else:
        print(f"[skip] {PIT_UNIVERSE_PATH} not found")


if __name__ == "__main__":
    main()
