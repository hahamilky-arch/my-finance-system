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
        # 기본 로직: 마지막 수집 날짜 이후부터
        last_data = supabase.table("stock_prices") \
            .select("price_date") \
            .eq("ticker", ticker) \
            .order("price_date", desc=True) \
            .limit(1) \
            .execute().data
        
        today = datetime.now()
        start_dt = (datetime.strptime(last_data[0]["price_date"], '%Y-%m-%d') + timedelta(days=1)) if last_data else (today - timedelta(days=365))
        end_dt = today

    # 2. 데이터 수집
    print(f"Syncing Index: {ticker} ({market}) from {start_dt.date()} to {end_dt.date()}...")
    fetch_end = end_dt + timedelta(days=1)
    df = yf.Ticker(ticker).history(start=start_dt.strftime('%Y-%m-%d'), end=fetch_end.strftime('%Y-%m-%d'))
    
    if df.empty:
        print(f"[{market}] 지수 데이터가 없습니다.")
        return

    # 3. DB 적재 (효율을 위해 리스트 사용)
    records = []
    for date, row in df.iterrows():
        records.append({
            "ticker": ticker,
            "price_date": date.strftime('%Y-%m-%d'),
            "close_price": float(row['Close']),
            "volume": int(row['Volume'])
        })
    
    if records:
        supabase.table("stock_prices").upsert(records, on_conflict="ticker,price_date").execute()
    
    print(f"[{market}] 지수 데이터({ticker}) 동기화 완료.")
