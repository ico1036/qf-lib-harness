"""Quick smoke test: pull AAPL daily for 1 year. Sanity-check yfinance + pandas + pyarrow."""
import pandas as pd
import yfinance as yf


def main() -> None:
    end = pd.Timestamp.today().normalize()
    start = end - pd.DateOffset(years=1)
    print(f"Pulling AAPL {start.date()} -> {end.date()} ...")
    df = yf.download("AAPL", start=start, end=end, auto_adjust=True, progress=False)
    if df.empty:
        raise SystemExit("Empty result from yfinance. Check network / yfinance install.")
    print(f"OK. {len(df)} rows.")
    print(df.tail(3))


if __name__ == "__main__":
    main()
