import sys
from datetime import datetime, timedelta
from database.client import supabase
import yfinance as yf

def sync_us_stocks_1year(target_ticker=None):
    """
    미국 주식 및 벤치마크(^GSPC)의 최근 정확히 1년치 데이터를 수집하여 Supabase에 적재합니다.
    """
    # 1. 대상 종목 조회 (US 시장 종목 + S&P 500 벤치마크 지수)
    query = supabase.table("stocks").select("ticker").or_("market.eq.US,ticker.eq.^GSPC")
    if target_ticker:
        query = query.eq("ticker", target_ticker.strip().upper())
    
    stocks = query.execute().data
    
    if not stocks:
        print("동기화할 대상 종목이 없습니다.")
        return

    # 2. 최근 1년치 날짜 계산 (오늘 기준 정확히 365일 전 ~ 오늘)
    end_dt = datetime.now()
    start_dt = end_dt - timedelta(days=365)
    
    start_str = start_dt.strftime('%Y-%m-%d')
    end_str = (end_dt + timedelta(days=1)).strftime('%Y-%m-%d')
    
    print(f"=== [전용] US 주식 최근 1년치 데이터 동기화 시작 (기간: {start_str} ~ {end_dt.strftime('%Y-%m-%d')}) ===")
    
    for stock in stocks:
        ticker = stock["ticker"]
        try:
            # yfinance를 통해 최근 1년치 데이터 다운로드
            df = yf.Ticker(ticker).history(start=start_str, end=end_str)
            
            if df.empty:
                print(f"[{ticker}] 수집된 데이터가 없습니다.")
                continue
                
            records = []
            for date, row in df.iterrows():
                records.append({
                    "ticker": ticker,
                    "price_date": date.strftime('%Y-%m-%d'),
                    "close_price": float(row['Close']),
                    "volume": int(row['Volume'])
                })
            
            if records:
                # 500건씩 분할하여 Supabase Upsert 실행
                chunk_size = 500
                for i in range(0, len(records), chunk_size):
                    chunk = records[i:i + chunk_size]
                    supabase.table("stock_prices").upsert(chunk, on_conflict="ticker,price_date").execute()
                print(f"[{ticker}] 최근 1년치 데이터 총 {len(records)}건 적재 완료")
                
        except Exception as e:
            print(f"Error syncing {ticker}: {e}")
            continue
            
    print("=== US 주식 최근 1년치 데이터 동기화 완료 ===")

if __name__ == "__main__":
    # 터미널 인자가 전달된 경우 해당 티커만 수집, 없으면 전체 US 종목 대상 수집
    target = sys.argv[1] if len(sys.argv) > 1 else None
    sync_us_stocks_1year(target_ticker=target)
