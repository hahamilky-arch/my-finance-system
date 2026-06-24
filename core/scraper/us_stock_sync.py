import yfinance as yf
from datetime import datetime, timedelta
from database.client import supabase

def sync_us_stocks():
    stocks = supabase.table("stocks").select("ticker").eq("market", "US").execute().data
    for stock in stocks:
        ticker = stock["ticker"]

        # 미국은 티커 변환 없이 그대로 사용                        
        last_date = supabase.table("stock_prices").select("price_date").eq("ticker", ticker).order("price_date", desc=True).limit(1).execute().data
        # 미국은 전일 데이터까지 기준
        start_date = (datetime.strptime(last_date[0]["price_date"], '%Y-%m-%d') + timedelta(days=1)) if last_date else (datetime.now() - timedelta(days=5))
                                                                
        df = yf.Ticker(ticker).history(start=start_date)
        for date, row in df.iterrows():
            # ​on_conflict 활용: ticker와 price_date를 조합하여 중복 입력을 방지(Upsert)합니다.
            supabase.table("stock_prices").upsert({
                "ticker": ticker, "price_date": date.strftime('%Y-%m-%d'),
                "close_price": float(row['Close']), "volume": int(row['Volume'])
            }, on_conflict="ticker,price_date").execute()
    print("US 주식 데이터 동기화 완료.")
