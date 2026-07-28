import pandas as pd
import numpy as np
import os
from datetime import datetime, timedelta
from core.indicators import get_rs_score
from supabase import create_client
from dotenv import load_dotenv

load_dotenv()
supabase = create_client(os.getenv("SUPABASE_URL"), os.getenv("SUPABASE_KEY"))

def safe_float(val):
    try:
        val = float(val)
        if not np.isfinite(val):
            return 0.0
        return val
    except (TypeError, ValueError):
        return 0.0

def backfill_pipeline(start_date_str, end_date_str, market='KR'):
    start_date = datetime.strptime(start_date_str, '%Y-%m-%d')
    end_date = datetime.strptime(end_date_str, '%Y-%m-%d')
    date_range = [start_date + timedelta(days=x) for x in range((end_date - start_date).days + 1)]
    
    benchmark_ticker = "^KS11" if market == "KR" else "^GSPC"
    
    # 분석 대상 티커 리스트
    target_tickers = [t["ticker"] for t in supabase.table("stocks").select("ticker").or_(f"market.eq.{market},market.eq.INDEX").execute().data]
    
    if not target_tickers:
        print("대상 티커 목록이 없습니다.")
        return

    # 1. 종목별 루프를 돌며 stock_prices 테이블에서 주가 데이터 수집 (OHLCV 조회)
    print(f"총 {len(target_tickers)}개 종목의 과거 데이터 수집 시작...")
    limit_date = (start_date - timedelta(days=300)).strftime('%Y-%m-%d')
    
    all_prices = []
    for ticker in target_tickers:
        try:
            response = supabase.table("stock_prices") \
                .select("ticker, price_date, open_price, high_price, low_price, close_price, volume") \
                .eq("ticker", ticker) \
                .gte("price_date", limit_date) \
                .lte("price_date", end_date_str) \
                .execute()
            if response.data:
                all_prices.extend(response.data)
        except Exception as e:
            print(f"[{ticker}] 조회 실패: {e}")
            
    df_all = pd.DataFrame(all_prices)
    if df_all.empty:
        print("수집된 가격 데이터가 없습니다.")
        return
        
    print(f"데이터 수집 완료. 총 {len(df_all)} 행.")
    
    # 날짜별 데이터 처리를 위해 datetime 변환
    df_all['price_date'] = pd.to_datetime(df_all['price_date'])
    df_all['close_price'] = pd.to_numeric(df_all['close_price'], errors='coerce')
    
    # 2. 날짜별 루프 실행
    for current_date in date_range:
        d_str = current_date.strftime('%Y-%m-%d')
        d_ts = pd.Timestamp(d_str)
        
        sub_df = df_all[df_all['price_date'] <= d_ts]
        if sub_df.empty:
            continue
            
        pivot_df = sub_df.pivot(index='price_date', columns='ticker', values='close_price').sort_index().ffill()
        
        if benchmark_ticker not in pivot_df.columns:
            continue
            
        # 3. RS 및 모멘텀 계산
        rs_map_90 = get_rs_score(pivot_df, benchmark_ticker=benchmark_ticker, window=90)
        rs_map_10 = get_rs_score(pivot_df, benchmark_ticker=benchmark_ticker, window=10)
        
        returns_90d = pivot_df.pct_change(90).iloc[-1]
        rank_map = returns_90d.rank(ascending=False)
        
        ma10_series = pivot_df.rolling(window=10, min_periods=1).mean().iloc[-1]
        ma20_series = pivot_df.rolling(window=20, min_periods=1).mean().iloc[-1]
        ma50_series = pivot_df.rolling(window=50, min_periods=1).mean().iloc[-1]
        ma200_series = pivot_df.rolling(window=200, min_periods=1).mean().iloc[-1]
        
        # 해당 날짜의 원본 OHLCV 데이터를 쉽게 조회하기 위한 맵 생성
        sub_today = sub_df[sub_df['price_date'] == d_ts].set_index('ticker')
        
        # 4. 저장용 데이터 생성
        analysis_data = []
        for ticker in target_tickers:
            if ticker == benchmark_ticker or ticker not in pivot_df.columns:
                continue
            
            current_close = pivot_df.loc[pivot_df.index[-1], ticker]
            rs_val = rs_map_90.get(ticker, 0.0)
            rs_10_val = rs_map_10.get(ticker, 0.0)
            rank_val = rank_map.get(ticker, 999)
            
            row_data = sub_today.loc[ticker] if ticker in sub_today.index else {}
            
            # ATR 계산 (당일 기준 고가-저가 범위 또는 간단한 14일 TR 평균 산출)
            # pivot_df를 활용한 ATR(14) 계산 예시
            try:
                high_s = sub_df.pivot(index='price_date', columns='ticker', values='high_price').ffill()
                low_s = sub_df.pivot(index='price_date', columns='ticker', values='low_price').ffill()
                close_s = pivot_df
                prev_close = close_s.shift(1)
                tr1 = high_s - low_s
                tr2 = (high_s - prev_close).abs()
                tr3 = (low_s - prev_close).abs()
                true_range = pd.concat([tr1, tr2, tr3], axis=1).max(axis=1)
                atr_val = true_range[ticker].rolling(window=14, min_periods=1).mean().iloc[-1]
            except Exception:
                atr_val = 0.0

            analysis_data.append({
                "ticker": ticker,
                "market": market,
                "weighted_momentum": safe_float(returns_90d[ticker]),
                "rs_score": safe_float(rs_val),
                "momentum_rank": int(rank_val) if pd.notna(rank_val) else 999,
                "close_price": safe_float(current_close),
                "ma10": safe_float(ma10_series.get(ticker, 0.0)),
                "ma20": safe_float(ma20_series.get(ticker, 0.0)),
                "rs_score_10": safe_float(rs_10_val),
                "open_price": safe_float(row_data.get('open_price', 0.0)),
                "high_price": safe_float(row_data.get('high_price', 0.0)),
                "low_price": safe_float(row_data.get('low_price', 0.0)),
                "volume": int(row_data.get('volume', 0)) if pd.notna(row_data.get('volume', 0)) else 0,
                "atr": safe_float(atr_val),
                "ma50": safe_float(ma50_series.get(ticker, 0.0)),
                "ma200": safe_float(ma200_series.get(ticker, 0.0)),
                "price_date": d_str
            })
            
        # 5. DB 적재 (500건씩 분할 업서트)
        if analysis_data:
            chunk_size = 500
            for i in range(0, len(analysis_data), chunk_size):
                chunk = analysis_data[i:i + chunk_size]
                supabase.table("daily_analysis").upsert(chunk, on_conflict="ticker,price_date").execute()
            print(f"[{d_str}] 완료: {len(analysis_data)}개 종목 적재")
        
    print("모든 날짜 분석 및 적재 완료.")
