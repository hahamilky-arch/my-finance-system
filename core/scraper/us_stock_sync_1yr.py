import sys
import pandas as pd
import yfinance as yf
from datetime import datetime, timedelta
from database.client import supabase

def sync_us_stocks_1year(target_ticker=None):
    """
    미국 주식 및 벤치마크(^GSPC)의 최근 정확히 1년치 OHLCV 데이터를 수집하여 Supabase에 적재합니다.
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
    
    fetch_start_dt = start_dt - timedelta(days=300)
    
    fetch_start_str = fetch_start_dt.strftime('%Y-%m-%d')
    fetch_end_str = (end_dt + timedelta(days=1)).strftime('%Y-%m-%d')
    
    print(f"=== [전용] US 주식 최근 1년치 데이터 동기화 시작 (목표 기간: {start_dt.strftime('%Y-%m-%d')} ~ {end_dt.strftime('%Y-%m-%d')}) ===")
    
    for stock in stocks:
        ticker = stock["ticker"]
        try:
            df = yf.Ticker(ticker).history(start=fetch_start_str, end=fetch_end_str)
            
            if df.empty:
                print(f"[{ticker}] 수집된 데이터가 없습니다.")
                continue
                
            # 💡 yfinance 타임존 제거 (Invalid comparison 에러 방지)
            if df.index.tz is not None:
                df.index = df.index.tz_localize(None)

            # 실제 목표로 하는 1년치 시작일 범위로 필터링
            target_start_ts = pd.Timestamp(start_dt.strftime('%Y-%m-%d'))
            df = df[df.index >= target_start_ts]

            if df.empty:
                print(f"[{ticker}] 조건에 부합하는 필터링된 1년치 데이터가 없습니다.")
                continue

            # 3. DB 적재 데이터 가공 (stock_prices 테이블 스키마에 맞춤: OHLCV)
            records = []
            for date, row in df.iterrows():
                records.append({
                    "ticker": ticker,
                    "price_date": date.strftime('%Y-%m-%d'),
                    "open_price": float(row['Open']) if pd.notna(row['Open']) else None,
                    "high_price": float(row['High']) if pd.notna(row['High']) else None,
                    "low_price": float(row['Low']) if pd.notna(row['Low']) else None,
                    "close_price": float(row['Close']),
                    "volume": int(row['Volume']) if pd.notna(row['Volume']) else 0
                })
            
            if records:
                # 500건씩 분할하여 Supabase Upsert 실행
                chunk_size = 500
                for i in range(0, len(records), chunk_size):
                    chunk = records[i:i + chunk_size]
                    supabase.table("stock_prices").upsert(chunk, on_conflict="ticker,price_date").execute()
                print(f"[{ticker}] 최근 1년치 OHLCV 데이터 총 {len(records)}건 적재 완료")
                
        except Exception as e:
            print(f"Error syncing {ticker}: {e}")
            continue
            
    print("=== US 주식 최근 1년치 데이터 동기화 완료 ===")

if __name__ == "__main__":
    if len(sys.argv) < 2 or not sys.argv[1].strip():
        print("❌ [중단] 티커가 전달되지 않아 실행을 중단합니다.")
        sys.exit(1)
        
    target = sys.argv[1]
    sync_us_stocks_1year(target_ticker=target)
