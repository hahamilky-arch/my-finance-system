import pandas as pd
import yfinance as yf
from datetime import datetime, timedelta
from database.client import supabase

INDEX_MAP = {"KR": "^KS11", "US": "^GSPC"}

def sync_index(market, start_date=None, end_date=None):
    ticker = INDEX_MAP.get(market)
    if not ticker:
        print(f"해당 시장({market})에 대한 지수 티커가 없습니다.")
        return

    # 1. 날짜 결정 로직
    if start_date:
        start_dt = datetime.strptime(start_date, '%Y-%m-%d')
        end_dt = datetime.strptime(end_date, '%Y-%m-%d') if end_date else datetime.now()
    else:
        last_data = supabase.table("stock_prices") \
            .select("price_date") \
            .eq("ticker", ticker) \
            .order("price_date", desc=True) \
            .limit(1) \
            .execute().data
        
        today = datetime.now()
        start_dt = (datetime.strptime(last_data[0]["price_date"], '%Y-%m-%d') + timedelta(days=1)) if last_data else (today - timedelta(days=400))
        end_dt = today

    # 2. 데이터 수집 (지표 계산용 여유 기간 300일 추가)
    print(f"Syncing Index: {ticker} ({market}) from {start_dt.date()} to {end_dt.date()}...")
    fetch_start = start_dt - timedelta(days=300)
    fetch_end = end_dt + timedelta(days=1)
    
    df = yf.Ticker(ticker).history(start=fetch_start.strftime('%Y-%m-%d'), end=fetch_end.strftime('%Y-%m-%d'))
    
    if df.empty:
        print(f"[{market}] 지수 데이터가 없습니다.")
        return

    # 💡 타임존 제거 (yfinance 최신 버전 대응 및 타입 충돌 방지)
    if df.index.tz is not None:
        df.index = df.index.tz_localize(None)

    # 3. 기술적 지표 계산 (ATR, MA50, MA200)
    df['Previous Close'] = df['Close'].shift(1)
    df['TR1'] = df['High'] - df['Low']
    df['TR2'] = abs(df['High'] - df['Previous Close'])
    df['TR3'] = abs(df['Low'] - df['Previous Close'])
    df['True Range'] = df[['TR1', 'TR2', 'TR3']].max(axis=1)
    df['atr'] = df['True Range'].rolling(window=14).mean()

    df['ma50'] = df['Close'].rolling(window=50).mean()
    df['ma200'] = df['Close'].rolling(window=200).mean()

    # 실제 수집 요청한 시작일 범위로 필터링 (Timestamp로 변환하여 비교)
    target_start_ts = pd.Timestamp(start_dt.strftime('%Y-%m-%d'))
    df = df[df.index >= target_start_ts]

    if df.empty:
        print(f"[{market}] 조건에 부합하는 신규 지수 데이터가 없습니다.")
        return

    # 4. DB 적재 데이터 가공
    records = []
    for date, row in df.iterrows():
        records.append({
            "ticker": ticker,
            "price_date": date.strftime('%Y-%m-%d'),
            "open_price": float(row['Open']) if pd.notna(row['Open']) else None,
            "high_price": float(row['High']) if pd.notna(row['High']) else None,
            "low_price": float(row['Low']) if pd.notna(row['Low']) else None,
            "close_price": float(row['Close']),
            "volume": int(row['Volume']) if pd.notna(row['Volume']) else 0,
            "atr": float(row['atr']) if pd.notna(row['atr']) else None,
            "ma50": float(row['ma50']) if pd.notna(row['ma50']) else None,
            "ma200": float(row['ma200']) if pd.notna(row['ma200']) else None
        })
    
    if records:
        supabase.table("stock_prices").upsert(records, on_conflict="ticker,price_date").execute()
    
    print(f"[{market}] 지수 데이터({ticker}) 동기화 및 지표 적재 완료.")
