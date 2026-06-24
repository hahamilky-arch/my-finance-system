import yfinance as yf
from datetime import datetime, timedelta
from database.client import supabase

def sync_us_stocks(start_date=None, end_date=None):
    # 1. 대상 종목 조회 (market='US')
    stocks = supabase.table("stocks").select("ticker").eq("market", "US").execute().data
    
    for stock in stocks:
        ticker = stock["ticker"]
        
        # 2. 날짜 결정 로직 (인자 우선 적용)
        if start_date:
            start_dt = datetime.strptime(start_date, '%Y-%m-%d')
            end_dt = datetime.strptime(end_date, '%Y-%m-%d') if end_date else datetime.now()
        else:
            # 기존 로직: DB의 마지막 데이터 기준
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
            # yfinance 호출 시 end 날짜 포함을 위해 하루 추가
            fetch_end = end_dt + timedelta(days=1)
            df = yf.Ticker(ticker).history(start=start_dt.strftime('%Y-%m-%d'), end=fetch_end.strftime('%Y-%m-%d'))
            
            if df.empty:
                continue
            
            # 4. DB 적재 (대량 upsert)
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
                
        except Exception as e:
            print(f"Error syncing US stock [{ticker}]: {e}")
            continue
            
    print("US 주식 데이터 동기화 완료.")
