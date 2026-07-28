import pandas as pd
import yfinance as yf
from datetime import datetime, timedelta
from database.client import supabase

def sync_us_stocks(start_date=None, end_date=None):
    # 1. 대상 종목 조회 (일반 US 종목 + 미국 시장 벤치마크 지수 ^GSPC 포함)
    stocks = supabase.table("stocks") \
        .select("ticker") \
        .or_("market.eq.US,ticker.eq.^GSPC") \
        .execute().data
    
    for stock in stocks:
        ticker = stock["ticker"]
        
        # 2. 날짜 결정 로직
        if start_date:
            start_dt = datetime.strptime(start_date, '%Y-%m-%d')
            end_dt = datetime.strptime(end_date, '%Y-%m-%d') if end_date else datetime.now()
        else:
            last_data = supabase.table("stock_prices") \
                .select("price_date") \
                .eq("ticker", ticker) \
                .order("price_date", desc=True) \
                .limit(1) \
                .execute().data
            
            today = datetime.now()
            if last_data:
                start_dt = datetime.strptime(last_data[0]["price_date"], '%Y-%m-%d') + timedelta(days=1)
            else:
                # 기술적 지표(MA200, ATR) 계산을 위해 최초 적재 시 넉넉하게 400일 전부터 가져옴
                start_dt = today - timedelta(days=400)
            end_dt = today
        
        # 3. 데이터 수집 (지표 계산용 여유 기간 300일 추가)
        try:
            fetch_start = start_dt - timedelta(days=300)
            fetch_end = end_dt + timedelta(days=1)
            
            start_str = fetch_start.strftime('%Y-%m-%d')
            end_str = fetch_end.strftime('%Y-%m-%d')
            
            df = yf.Ticker(ticker).history(start=start_str, end=end_str)
            
            if df.empty:
                continue
                
            # 4. 기술적 지표 계산 (ATR, MA50, MA200)
            df['Previous Close'] = df['Close'].shift(1)
            df['TR1'] = df['High'] - df['Low']
            df['TR2'] = abs(df['High'] - df['Previous Close'])
            df['TR3'] = abs(df['Low'] - df['Previous Close'])
            df['True Range'] = df[['TR1', 'TR2', 'TR3']].max(axis=1)
            df['atr'] = df['True Range'].rolling(window=14).mean()

            df['ma50'] = df['Close'].rolling(window=50).mean()
            df['ma200'] = df['Close'].rolling(window=200).mean()

            # 실제 수집 요청한 시작일 범위로 필터링
            target_start_ts = pd.Timestamp(start_dt.strftime('%Y-%m-%d'))
            df = df[df.index >= target_start_ts]

            if df.empty:
                continue

            # 5. DB 적재 데이터 가공
            records = []
            for date, row in df.iterrows():
                records.append({
                    "ticker": ticker,
                    "price_date": date.strftime('%Y-%m-%d'),
                    "open_price": float(row['Open']) if pd.notna(row['Open']) else None,
                    "high_price": float(row['High']) if pd.notna(row['High']) else None,
                    "low_price": float(row['Low']) if pd.notna(row['Low']) else None,
                    "close_price": float(row['Close']),
                    "volume": int(row['Volume']) if pd.notna(row['Volume']) else 0,
                    "atr": float(row['atr']) if pd.notna(row['atr']) else None,
                    "ma50": float(row['ma50']) if pd.notna(row['ma50']) else None,
                    "ma200": float(row['ma200']) if pd.notna(row['ma200']) else None
                })
            
            if records:
                supabase.table("stock_prices").upsert(records, on_conflict="ticker,price_date").execute()
                print(f"[{ticker}] OHLCV 및 기술적 지표 데이터 적재 완료")
                
        except Exception as e:
            print(f"Error syncing {ticker}: {e}")
            continue
            
    print("US 주식 데이터 동기화 완료.")
