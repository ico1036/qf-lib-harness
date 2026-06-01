"""Fetch full US listed universe from NASDAQ Trader FTP (HTTPS mirror).

Covers NASDAQ + NYSE + AMEX + all other US exchanges.
Filters out preferred shares, warrants, units, rights, notes (debt instruments).
Output: data/tickers.parquet
"""
import re
from io import StringIO

import pandas as pd
import requests

from config import ALLOWED_ETFS, UNIVERSE_PATH

DROP_NAME_RE = re.compile(
    r"\b(?:Preferred|Cumulative|Warrant|Subordinated|Note|Notes|Right|Rights)s?\b"
    r"|\bUnit\b(?!ed)",
    re.IGNORECASE,
)

NASDAQ_URL = "https://www.nasdaqtrader.com/dynamic/symdir/nasdaqlisted.txt"
OTHER_URL = "https://www.nasdaqtrader.com/dynamic/symdir/otherlisted.txt"


def fetch(url: str) -> pd.DataFrame:
    r = requests.get(url, timeout=30)
    r.raise_for_status()
    text = r.text
    lines = text.strip().split("\n")
    if lines[-1].startswith("File Creation"):
        text = "\n".join(lines[:-1])
    return pd.read_csv(StringIO(text), sep="|")


def main() -> None:
    print("Fetching nasdaqlisted.txt ...")
    nasdaq = fetch(NASDAQ_URL)
    nasdaq = nasdaq.rename(columns={"Symbol": "ticker"})
    nasdaq["exchange"] = "NASDAQ"
    nasdaq = nasdaq[["ticker", "Security Name", "ETF", "Test Issue", "exchange"]]

    print("Fetching otherlisted.txt ...")
    other = fetch(OTHER_URL)
    other = other.rename(columns={"ACT Symbol": "ticker", "Exchange": "exchange"})
    other = other[["ticker", "Security Name", "ETF", "Test Issue", "exchange"]]

    df = pd.concat([nasdaq, other], ignore_index=True)
    df = df.dropna(subset=["ticker"])
    df = df[df["Test Issue"] != "Y"]
    df = df.drop_duplicates(subset=["ticker"])

    # Yahoo Finance uses '-' instead of '.' for class shares (BRK.A -> BRK-A)
    df["ticker"] = df["ticker"].str.replace(".", "-", regex=False)

    df = df.rename(columns={"Security Name": "name", "ETF": "is_etf", "Test Issue": "is_test"})

    # Keep all common stocks; filter ETFs to whitelist only
    before = len(df)
    etf_keep = (df["is_etf"] != "Y") | df["ticker"].isin(ALLOWED_ETFS)
    df = df[etf_keep].reset_index(drop=True)
    print(f"\nDropped {before - len(df):,} ETFs (kept whitelist: {sorted(ALLOWED_ETFS)})")

    # Filter out preferred shares / warrants / units / rights / notes
    before = len(df)
    name_keep = ~df["name"].fillna("").str.contains(DROP_NAME_RE, regex=True) | df["ticker"].isin(ALLOWED_ETFS)
    df = df[name_keep].reset_index(drop=True)
    print(f"Dropped {before - len(df):,} preferred/warrant/unit/right/note securities")

    df.to_parquet(UNIVERSE_PATH)

    print(f"Saved {len(df):,} tickers -> {UNIVERSE_PATH}")
    etf_counts = df["is_etf"].value_counts(dropna=False).to_dict()
    ex_counts = df["exchange"].value_counts().to_dict()
    print(f"  ETF flag: {etf_counts}")
    print(f"  Exchange: {ex_counts}")
    kept_etfs = df.loc[df["is_etf"] == "Y", "ticker"].tolist()
    print(f"  Kept ETFs: {kept_etfs}")


if __name__ == "__main__":
    main()
