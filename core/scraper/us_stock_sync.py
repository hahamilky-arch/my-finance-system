import yfinance as yf
from datetime import datetime, timedelta
from database.client import supabase

def sync_us_stocks(start_date=None, end_date=None):
    # 1. 대상 종목 조회 (일반 US 종목 + 미국 시장 벤치마크 지수 ^GSPC 포함)
    stocks = supabase.table("stocks") \
        .select("ticker") \
        .or_("market.eq.US,ticker.eq.^GSPC") \
        .execute().data
    
    for stock in stocks:
        ticker = stock["ticker"]
        
        # 2. 날짜 결정 로직
        if start_date:
            start_dt = datetime.strptime(start_date, '%Y-%m-%d')
            end_dt = datetime.strptime(end_date, '%Y-%m-%d') if end_date else datetime.now()
        else:
            # DB 조회 시 해당 ticker로 검색
            last_data = supabase.table("stock_prices") \
                .select("price_date") \
                .eq("ticker", ticker) \
                .order("price_date", desc=True) \
                .limit(1) \
                .execute().data
            
            today = datetime.now()
            if last_data:
                start_dt = datetime.strptime(last_data[0]["price_date"], '%Y-%m-%d') + timedelta(days=1)
            else:
                start_dt = today - timedelta(days=5)
            end_dt = today
        
        # 3. 데이터 수집
        try:
            fetch_end = end_dt + timedelta(days=1)
            start_str = start_dt.strftime('%Y-%m-%d')
            end_str = fetch_end.strftime('%Y-%m-%d')
            
            df = yf.Ticker(ticker).history(start=start_str, end=end_str)
            
            if df.empty:
                # 주말, 공휴일이거나 유효하지 않은 데이터인 경우 건너뜀
                continue
                
            # 4. DB 적재
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
                print(f"[{ticker}] 데이터 적재 완료")
                
        except Exception as e:
            print(f"Error syncing {ticker}: {e}")
            continue
            
    print("US 주식 데이터 동기화 완료.")
