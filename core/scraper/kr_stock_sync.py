import yfinance as yf
from datetime import datetime, timedelta
from database.client import supabase

def sync_kr_stocks():
    stocks = supabase.table("stocks").select("ticker").eq("market", "KR").execute().data
    for stock in stocks:
        ticker = stock["ticker"]
        yf_ticker = f"{str(ticker).zfill(6)}.KS"
                        
        # 최신 데이터 확인 후 수집 로직 (기존 로직 이식)
        last_date = supabase.table("stock_prices").select("price_date").eq("ticker", yf_ticker).order("price_date", desc=True).limit(1).execute().data
        start_date = (datetime.strptime(last_date[0]["price_date"], '%Y-%m-%d') + timedelta(days=1)) if last_date else (datetime.now() - timedelta(days=5))
                                                        
        df = yf.Ticker(yf_ticker).history(start=start_date)
        for date, row in df.iterrows():
            supabase.table("stock_prices").upsert({
                "ticker": yf_ticker, "price_date": date.strftime('%Y-%m-%d'),
                "close_price": float(row['Close']), "volume": int(row['Volume'])
            }, on_conflict="ticker,price_date").execute()
    print("KR 주식 데이터 동기화 완료.")