from pathlib import Path
import pandas as pd

BASE_DIR = Path(__file__).parent
DATA_DIR = BASE_DIR / "data"
PRICES_BATCHES_DIR = DATA_DIR / "prices_batches"
LOG_DIR = DATA_DIR / "logs"

for d in (DATA_DIR, PRICES_BATCHES_DIR, LOG_DIR):
    d.mkdir(parents=True, exist_ok=True)

UNIVERSE_PATH = DATA_DIR / "tickers.parquet"
PRICES_PATH = DATA_DIR / "prices.parquet"
PIT_UNIVERSE_PATH = DATA_DIR / "universe_pit_top3000.parquet"
FAILED_TICKERS_LOG = LOG_DIR / "failed_tickers.txt"

START_DATE = "2015-01-01"
END_DATE = pd.Timestamp.today().normalize().strftime("%Y-%m-%d")

BATCH_SIZE = 50
INTER_BATCH_SLEEP = 0.8
MAX_RETRIES = 3

ALLOWED_ETFS = {
    "SH",    # ProShares Short S&P 500 (-1x)
    "SQQQ",  # ProShares UltraPro Short QQQ (-3x)
    "SPXS",  # Direxion Daily S&P 500 Bear 3x
}

LOOKBACK_DAYS = 21
TOP_N = 3000
REBAL_FREQ = "MS"
