import yfinance as yf
from database.client import supabase

# 시장별 지수 티커 매핑 (함수 외부로 빼서 관리)
INDEX_MAP = {"KR": "^KS11", "US": "^GSPC"}

def sync_index(market):  # 'market' 인자를 받도록 변경
    ticker = INDEX_MAP.get(market)
    if not ticker:
        print(f"해당 시장({market})에 대한 지수 티커가 없습니다.")
        return

    print(f"Syncing Index: {ticker} ({market})...")
    df = yf.Ticker(ticker).history(period="1y")
                        
    for date, row in df.iterrows():
        data = {
            "ticker": ticker,
            "price_date": date.strftime('%Y-%m-%d'),
            "close_price": float(row['Close']),
            "volume": int(row['Volume'])
        }
        # Upsert 실행
        supabase.table("stock_prices").upsert(data, on_conflict="ticker,price_date").execute()
    
    print(f"[{market}] 지수 데이터({ticker}) 동기화 완료.")
