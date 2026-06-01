"""Download daily OHLCV via yfinance for the full universe, in batches.

- Saves one parquet file per batch (resumable: rerun skips finished batches).
- Concatenates everything into prices.parquet at the end.
- Logs failed batches to logs/failed_tickers.txt.
"""
import time

import pandas as pd
import yfinance as yf

from config import (
    BATCH_SIZE,
    END_DATE,
    FAILED_TICKERS_LOG,
    INTER_BATCH_SLEEP,
    MAX_RETRIES,
    PRICES_BATCHES_DIR,
    PRICES_PATH,
    START_DATE,
    UNIVERSE_PATH,
)


def reshape_to_long(df: pd.DataFrame, batch: list[str]) -> pd.DataFrame:
    """yfinance multi-ticker output -> long format (date, ticker, OHLCV)."""
    if not isinstance(df.columns, pd.MultiIndex):
        # single-ticker fallback (shouldn't happen with batch size >=2)
        df = df.copy()
        df.columns = pd.MultiIndex.from_product([df.columns, [batch[0]]])
    df.index.name = "date"
    df.columns.names = ["field", "ticker"]
    long = df.stack(level="ticker", future_stack=True).reset_index()
    return long


def download_batch(batch: list[str]) -> pd.DataFrame:
    """Download with retries. yfinance with batches >50 hits rate limits a lot."""
    last_err: Exception | None = None
    for attempt in range(MAX_RETRIES):
        try:
            df = yf.download(
                batch,
                start=START_DATE,
                end=END_DATE,
                auto_adjust=True,
                actions=False,
                progress=False,
                threads=True,
            )
            if df.empty:
                # retry — empty often means a transient rate limit
                last_err = RuntimeError("empty result")
                time.sleep(2.0 * (attempt + 1))
                continue
            long = reshape_to_long(df, batch)
            long = long.dropna(subset=["Close", "Volume"], how="any")
            if long.empty:
                last_err = RuntimeError("all NaN after reshape")
                time.sleep(2.0 * (attempt + 1))
                continue
            long["dollar_volume"] = long["Close"] * long["Volume"]
            return long
        except Exception as e:
            last_err = e
            time.sleep(3.0 * (attempt + 1))
    raise RuntimeError(f"failed after {MAX_RETRIES} attempts: {last_err}")


def main() -> None:
    universe = pd.read_parquet(UNIVERSE_PATH)
    tickers = sorted(universe["ticker"].dropna().unique().tolist())
    n = len(tickers)
    n_batches = (n + BATCH_SIZE - 1) // BATCH_SIZE

    print(f"Downloading {n:,} tickers, {START_DATE} -> {END_DATE}")
    print(f"Batch size {BATCH_SIZE}, total {n_batches} batches")

    failed: list[str] = []
    for batch_id in range(n_batches):
        out_path = PRICES_BATCHES_DIR / f"batch_{batch_id:04d}.parquet"
        if out_path.exists():
            print(f"[{batch_id:04d}/{n_batches}] cached, skip")
            continue

        batch = tickers[batch_id * BATCH_SIZE : (batch_id + 1) * BATCH_SIZE]
        print(f"[{batch_id:04d}/{n_batches}] {len(batch)} tickers ({batch[0]} ... {batch[-1]})")
        try:
            long = download_batch(batch)
            if long.empty:
                print("  empty result")
                failed.extend(batch)
                continue
            long.to_parquet(out_path)
            print(f"  saved {len(long):,} rows ({long['ticker'].nunique()} tickers w/ data)")
        except Exception as e:
            print(f"  FAILED: {type(e).__name__}: {e}")
            failed.extend(batch)
            time.sleep(5.0)
            continue
        time.sleep(INTER_BATCH_SLEEP)

    if failed:
        FAILED_TICKERS_LOG.write_text("\n".join(failed))
        print(f"\n{len(failed)} failed tickers logged -> {FAILED_TICKERS_LOG}")

    print("\nConcatenating batches ...")
    parts = sorted(PRICES_BATCHES_DIR.glob("batch_*.parquet"))
    if not parts:
        print("No batches saved.")
        return
    full = pd.concat([pd.read_parquet(p) for p in parts], ignore_index=True)
    full = full.sort_values(["date", "ticker"]).reset_index(drop=True)
    full.to_parquet(PRICES_PATH, compression="zstd")
    print(f"Saved {len(full):,} rows / {full['ticker'].nunique():,} unique tickers -> {PRICES_PATH}")
    print(f"Date range: {full['date'].min().date()} -> {full['date'].max().date()}")


if __name__ == "__main__":
    main()
