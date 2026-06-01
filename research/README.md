# US Universe — Top 3000 by Trailing Dollar Volume

10년치 미국 주식 OHLCV 백테스트 데이터 파이프라인. 펀더멘털 X, OHLCV만.

## 동작

1. **유니버스**: NASDAQ Trader FTP에서 NASDAQ + NYSE + AMEX 전체 listed ticker (~7K)
2. **OHLCV**: yfinance로 2015-01-01 ~ 오늘 일봉 다운로드
3. **PIT 유니버스**: 매월 첫 거래일 시점, 직전 21일 평균 dollar volume 상위 3000 종목 산출

## 셋업

```bash
cd /Users/jwcorp/qf-lib/research/us_universe
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
```

## 실행 (순서대로)

```bash
python 0_smoke_test.py        # ~5초. yfinance 동작 확인
python 1_fetch_universe.py    # ~5초. NASDAQ FTP에서 ticker 리스트
python 2_download_prices.py   # 30분 ~ 2시간. 재시작 가능
python 3_build_universe.py    # ~30초. PIT top-3000 빌드
python 4_inspect.py           # 산출물 sanity check
```

## 출력물

```
data/
├── tickers.parquet                     # NASDAQ FTP 원본 universe (~7K)
├── prices_batches/batch_*.parquet      # yfinance 배치 캐시
├── prices.parquet                      # 일봉 OHLCV long format
├── universe_pit_top3000.parquet        # 매월 PIT top 3000
└── logs/failed_tickers.txt             # 실패한 ticker (있으면)
```

### 컬럼

**prices.parquet**
- `date, ticker, Open, High, Low, Close, Volume, dollar_volume`
- `auto_adjust=True` 적용 (분할/배당 보정된 가격)

**universe_pit_top3000.parquet**
- `rebal_date, ticker, rank, adv_21d`
- 매월 한 번 리밸런싱 시점, 1~3000 랭킹

## qf-lib 백테스트와 결합

`PresetDataProvider`에 직접 주입하거나, 자체 DataProvider 클래스를 만들어 `prices.parquet`을 읽어오는 식.

```python
import pandas as pd
import xarray as xr

prices = pd.read_parquet("data/prices.parquet")
# wide pivot 후 QFDataArray로 감싸 PresetDataProvider 생성
```

전략 안에서 매월 리밸일 시점의 universe를 미리 dict로 만들어두고 사용:

```python
pit = pd.read_parquet("data/universe_pit_top3000.parquet")
universe_at_date = {d: g["ticker"].tolist() for d, g in pit.groupby("rebal_date")}
```

## 주의사항

### Survivorship bias
NASDAQ FTP는 **현재 거래 중인 ticker만** 제공. 폐지된 종목은 후보 풀에 없음.
- 실제 영향: 백테스트 연환산 수익률을 ~0.5%~2% 정도 과대 평가하는 경향
- 완화하려면 FMP `/delisted-companies` 등으로 폐지 ticker 합집합 추가 (별도 API key 필요)

### yfinance 안정성
- 2024년 들어 가끔 rate limit / 일시 차단. 파이프라인은 batch별 cache 저장으로 **재시작 가능**
- `data/prices_batches/`의 partial parquet 그대로 두고 재실행하면 안 받은 batch만 받음
- 일부 ticker는 yfinance에 데이터 없음 (소형주, 최근 IPO 등). NaN 처리됨

### 가격 조정
- `auto_adjust=True`: 분할/배당 반영된 가격
- Volume은 raw share volume 그대로
- Dollar volume = adjusted close × volume → ranking 용도로는 충분 (PIT 정확도가 중요한 절대 수치 분석엔 부적합)

### ETF 포함
- 현재는 ETF도 풀에 포함 (`SPY`, `QQQ` 등 거래량 top 3000에 항상 들어감)
- 주식만 원하면 1번 스크립트 수정해서 `is_etf == 'N'` 필터 추가

## 디스크 공간 추정

- `prices_batches/`: ~300~500 MB (배치별 parquet)
- `prices.parquet`: ~200~400 MB (zstd 압축)
- `universe_pit_top3000.parquet`: ~2 MB
