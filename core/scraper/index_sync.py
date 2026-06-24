import yfinance as yf
from datetime import datetime, timedelta
from database.client import supabase

INDEX_TICKERS = {"KR": "^KS11", "US": "^GSPC"}

def sync_index_data():
    for market, ticker in INDEX_TICKERS.items():
        print(f"Syncing Index: {ticker} ({market})...")
        df = yf.Ticker(ticker).history(period="1y")
                            
        for date, row in df.iterrows():
            data = {
                "ticker": ticker,
                "price_date": date.strftime('%Y-%m-%d'),
                "close_price": float(row['Close']),
                "volume": int(row['Volume'])
            }
            supabase.table("stock_prices").upsert(data, on_conflict="ticker,price_date").execute()
    print("지수 데이터 동기화 완료.")
