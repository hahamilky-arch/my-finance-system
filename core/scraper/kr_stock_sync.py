import yfinance as yf
from datetime import datetime, timedelta
from database.client import supabase

def sync_kr_stocks():
    # 1. 대상 종목 조회 (market='KR'인 것만)
    stocks = supabase.table("stocks").select("ticker").eq("market", "KR").execute().data
    
    for stock in stocks:
        ticker = stock["ticker"]
        yf_ticker = f"{str(ticker).zfill(6)}.KS"
        
        # 2. 마지막 데이터 확인
        last_data = supabase.table("stock_prices") \
            .select("price_date") \
            .eq("ticker", yf_ticker) \
            .order("price_date", desc=True) \
            .limit(1) \
            .execute().data
            
        # 3. 수집 시작일 설정 (날짜 오류 방지 로직 적용)
        today = datetime.now()
        if last_data:
            last_dt = datetime.strptime(last_data[0]["price_date"], '%Y-%m-%d')
            start_dt = last_dt + timedelta(days=1)
        else:
            start_dt = today - timedelta(days=5)
            
        # [핵심] 시작일이 미래라면 수집하지 않고 건너뜀
        if start_dt.date() > today.date():
            continue
            
        # 4. 데이터 수집
        df = yf.Ticker(yf_ticker).history(start=start_dt.strftime('%Y-%m-%d'))
        
        if df.empty:
            continue
            
        # 5. DB 적재
        records = []
        for date, row in df.iterrows():
            records.append({
                "ticker": yf_ticker,
                "price_date": date.strftime('%Y-%m-%d'),
                "close_price": float(row['Close']),
                "volume": int(row['Volume'])
            })
            
        if records:
            supabase.table("stock_prices").upsert(records, on_conflict="ticker,price_date").execute()
            
    print("KR 주식 데이터 동기화 완료.")
