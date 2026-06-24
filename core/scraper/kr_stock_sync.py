import yfinance as yf
from datetime import datetime, timedelta
from database.client import supabase

def sync_kr_stocks(start_date=None, end_date=None):
    # 1. 대상 종목 조회
    stocks = supabase.table("stocks").select("ticker").eq("market", "KR").execute().data
    
    for stock in stocks:
        ticker = stock["ticker"]
        yf_ticker = f"{str(ticker).zfill(6)}.KS"

        # DB 적재용 티커(원본)
        db_ticker = str(ticker).zfill(6) 

        
        # 2. 날짜 결정 로직 (인자 우선 적용)
        if start_date:
            start_dt = datetime.strptime(start_date, '%Y-%m-%d')
            # end_date가 없으면 오늘까지로 설정
            end_dt = datetime.strptime(end_date, '%Y-%m-%d') if end_date else datetime.now()
        else:
            # 기존 로직: DB의 마지막 데이터 기준
            last_data = supabase.table("stock_prices") \
                .select("price_date") \
                .eq("ticker", yf_ticker) \
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
            # yfinance는 end를 포함하지 않으므로 end_dt에 하루를 더함
            fetch_end = end_dt + timedelta(days=1)
            df = yf.Ticker(yf_ticker).history(start=start_dt.strftime('%Y-%m-%d'), end=fetch_end.strftime('%Y-%m-%d'))
            
            if df.empty:
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
                
        except Exception as e:
            print(f"Error syncing {yf_ticker}: {e}")
            continue
            
    print("KR 주식 데이터 동기화 완료.")
    
