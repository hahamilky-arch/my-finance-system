import yfinance as yf
from datetime import datetime, timedelta
from database.client import supabase

def sync_kr_stocks(start_date=None, end_date=None):
    # 1. 대상 종목 조회
    stocks = supabase.table("stocks").select("ticker").eq("market", "KR").execute().data
    
    for stock in stocks:
        raw_ticker = stock["ticker"]
        # DB 적재 및 조회용 원본 티커 (예: '005930')
        db_ticker = str(raw_ticker).zfill(6) 
        
        # 2. 날짜 결정 로직
        if start_date:
            start_dt = datetime.strptime(start_date, '%Y-%m-%d')
            end_dt = datetime.strptime(end_date, '%Y-%m-%d') if end_date else datetime.now()
        else:
            # 💡 [버그 수정] DB 조회 시 yf_ticker가 아닌 db_ticker로 검색해야 함
            last_data = supabase.table("stock_prices") \
                .select("price_date") \
                .eq("ticker", db_ticker) \
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
            
            # 💡 [핵심 수정] 코스피(.KS)로 먼저 시도 후, 데이터가 없으면 코스닥(.KQ)으로 폴백(Fallback) 시도
            yf_ticker_ks = f"{db_ticker}.KS"
            df = yf.Ticker(yf_ticker_ks).history(start=start_str, end=end_str)
            
            if df.empty:
                yf_ticker_kq = f"{db_ticker}.KQ"
                df = yf.Ticker(yf_ticker_kq).history(start=start_str, end=end_str)
            
            if df.empty:
                # 주말, 공휴일이거나 완전히 유효하지 않은 티커인 경우 건너뜀
                continue
                
            # 4. DB 적재
            records = []
            for date, row in df.iterrows():
                records.append({
                    "ticker": db_ticker,
                    "price_date": date.strftime('%Y-%m-%d'),
                    "close_price": float(row['Close']),
                    "volume": int(row['Volume'])
                })
            
            if records:
                supabase.table("stock_prices").upsert(records, on_conflict="ticker,price_date").execute()
                print(f"[{db_ticker}] 데이터 적재 완료")
                
        except Exception as e:
            print(f"Error syncing {db_ticker}: {e}")
            continue
            
    print("KR 주식 데이터 동기화 완료.")
