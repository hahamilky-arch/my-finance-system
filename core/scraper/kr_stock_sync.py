import pandas as pd
import FinanceDataReader as fdr # yfinance 대신 fdr 사용
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
                # 초기 적재 시 넉넉하게 400일 전부터 가져옴
                start_dt = today - timedelta(days=400)
            end_dt = today
        
        # 3. 데이터 수집 (지표 계산용 여유 기간 300일 추가)
        try:
            fetch_start = start_dt - timedelta(days=300)
            fetch_end = end_dt + timedelta(days=1)
            
            start_str = fetch_start.strftime('%Y-%m-%d')
            end_str = fetch_end.strftime('%Y-%m-%d')
            
            # 💡 수정된 부분: fdr.DataReader 사용 (.KS, .KQ 구분 불필요)
            df = fdr.DataReader(db_ticker, start_str, end_str)
            
            if df.empty:
                print(f"[{db_ticker}] 데이터가 존재하지 않습니다. (상장폐지 또는 거래정지 가능성)")
                continue
                
            # FinanceDataReader는 기본적으로 tz-naive 인덱스를 반환하므로 timezone 제거 로직 불필요

            # 실제 수집 요청한 시작일 범위로 필터링
            target_start_ts = pd.Timestamp(start_dt.strftime('%Y-%m-%d'))
            df = df[df.index >= target_start_ts]

            if df.empty:
                continue

            # 4. DB 적재 데이터 가공 (stock_prices 테이블 스키마에 맞춤: OHLCV)
            records = []
            for date, row in df.iterrows():
                records.append({
                    "ticker": db_ticker,
                    "price_date": date.strftime('%Y-%m-%d'),
                    "open_price": float(row['Open']) if pd.notna(row['Open']) else None,
                    "high_price": float(row['High']) if pd.notna(row['High']) else None,
                    "low_price": float(row['Low']) if pd.notna(row['Low']) else None,
                    "close_price": float(row['Close']),
                    "volume": int(row['Volume']) if pd.notna(row['Volume']) else 0
                })
            
            if records:
                supabase.table("stock_prices").upsert(records, on_conflict="ticker,price_date").execute()
                print(f"[{db_ticker}] OHLCV 데이터 적재 완료")
                
        except Exception as e:
            print(f"Error syncing {db_ticker}: {e}")
            continue
            
    print("KR 주식 데이터 동기화 완료.")
