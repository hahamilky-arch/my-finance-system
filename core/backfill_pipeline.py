import pandas as pd
import numpy as np
import os
from datetime import datetime, timedelta
from core.indicators import get_rs_score
from supabase import create_client
from dotenv import load_dotenv

# 💡 미래 버전 변경에 따른 경고 방지 설정 추가
pd.set_option('future.no_silent_downcasting', True)

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
    
    # 분석 대상 티커 리스트 (인덱스 포함)
    target_tickers = [t["ticker"] for t in supabase.table("stocks").select("ticker").or_(f"market.eq.{market},market.eq.INDEX").execute().data]
    
    if not target_tickers:
        print("대상 티커 목록이 없습니다.")
        return

    # 1. 전체 데이터 한 번에 조회 (지표 계산용 300일 여유 기간 포함)
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
        
    print(f"데이터 수집 완료. 총 {len(df_all)} 행. 백필 연산 시작...")
    
    # 데이터 전처리
    df_all['price_date'] = pd.to_datetime(df_all['price_date'])
    for col in ['open_price', 'high_price', 'low_price', 'close_price']:
        df_all[col] = pd.to_numeric(df_all[col], errors='coerce')
    df_all['volume'] = pd.to_numeric(df_all['volume'], errors='coerce').fillna(0)

    # 사전 피벗 데이터프레임 생성 (속도 극대화)
    pivot_close = df_all.pivot(index='price_date', columns='ticker', values='close_price').sort_index().ffill()
    pivot_high = df_all.pivot(index='price_date', columns='ticker', values='high_price').sort_index().ffill()
    pivot_low = df_all.pivot(index='price_date', columns='ticker', values='low_price').sort_index().ffill()
    pivot_open = df_all.pivot(index='price_date', columns='ticker', values='open_price').sort_index().ffill()
    pivot_volume = df_all.pivot(index='price_date', columns='ticker', values='volume').sort_index().fillna(0)

    # 사전 ATR 계산 (전체 기간 일괄 연산으로 속도 향상)
    prev_close = pivot_close.shift(1)
    tr1 = pivot_high - pivot_low
    tr2 = (pivot_high - prev_close).abs()
    tr3 = (pivot_low - prev_close).abs()
    true_range = np.maximum(tr1, np.maximum(tr2, tr3))
    atr_df = true_range.rolling(window=14, min_periods=1).mean()

    # 2. 날짜별 루프 실행
    for current_date in date_range:
        d_str = current_date.strftime('%Y-%m-%d')
        d_ts = pd.Timestamp(d_str)
        
        if d_ts not in pivot_close.index:
            continue
            
        # 해당 일자까지의 슬라이스
        sub_close = pivot_close.loc[:d_ts]
        
        if benchmark_ticker not in sub_close.columns:
            continue
            
        # 3. RS 및 모멘텀 계산
        rs_map_90 = get_rs_score(sub_close, benchmark_ticker=benchmark_ticker, window=90)
        rs_map_10 = get_rs_score(sub_close, benchmark_ticker=benchmark_ticker, window=10)
        
        r1 = sub_close.pct_change(20).iloc[-1]
        r2 = sub_close.pct_change(40).iloc[-1]
        r4 = sub_close.pct_change(80).iloc[-1]
        r6 = sub_close.pct_change(120).iloc[-1]
        r12 = sub_close.pct_change(240).iloc[-1]
        
        weighted_momentum = (r1.fillna(0) * 12) + (r2.fillna(0) * 6) + \
                            (r4.fillna(0) * 4) + (r6.fillna(0) * 2) + \
                            (r12.fillna(0) * 1)
        
        rank_map = weighted_momentum.rank(ascending=False)
        
        ma10_series = sub_close.rolling(window=10, min_periods=1).mean().iloc[-1]
        ma20_series = sub_close.rolling(window=20, min_periods=1).mean().iloc[-1]
        ma50_series = sub_close.rolling(window=50, min_periods=1).mean().iloc[-1]
        ma200_series = sub_close.rolling(window=200, min_periods=1).mean().iloc[-1]
        
        # 4. 저장용 데이터 생성
        analysis_data = []
        for ticker in target_tickers:
            if ticker == benchmark_ticker or ticker not in sub_close.columns:
                continue
            
            current_close = sub_close.loc[d_ts, ticker]
            if pd.isna(current_close):
                continue

            analysis_data.append({
                "ticker": ticker,
                "market": market,
                "weighted_momentum": safe_float(weighted_momentum.get(ticker, 0.0)),
                "rs_score": safe_float(rs_map_90.get(ticker, 0.0)),
                "momentum_rank": int(rank_map.get(ticker, 999)) if pd.notna(rank_map.get(ticker)) else 999,
                "close_price": safe_float(current_close),
                "open_price": safe_float(pivot_open.loc[d_ts, ticker]) if ticker in pivot_open.columns else 0.0,
                "high_price": safe_float(pivot_high.loc[d_ts, ticker]) if ticker in pivot_high.columns else 0.0,
                "low_price": safe_float(pivot_low.loc[d_ts, ticker]) if ticker in pivot_low.columns else 0.0,
                "volume": int(pivot_volume.loc[d_ts, ticker]) if ticker in pivot_volume.columns else 0,
                "atr": safe_float(atr_df.loc[d_ts, ticker]) if (d_ts in atr_df.index and ticker in atr_df.columns) else 0.0,
                "ma10": safe_float(ma10_series.get(ticker, 0.0)),
                "ma20": safe_float(ma20_series.get(ticker, 0.0)),
                "ma50": safe_float(ma50_series.get(ticker, 0.0)),
                "ma200": safe_float(ma200_series.get(ticker, 0.0)),
                "rs_score_10": safe_float(rs_map_10.get(ticker, 0.0)),
                "price_date": d_str
            })
            
        # 5. DB 적재 (500건씩 분할 업서트)
        if analysis_data:
            chunk_size = 500
            for i in range(0, len(analysis_data), chunk_size):
                chunk = analysis_data[i:i + chunk_size]
                supabase.table("daily_analysis").upsert(chunk, on_conflict="ticker,price_date").execute()
            print(f"[{d_str}] 백필 완료: {len(analysis_data)}개 종목 적재")
        
    print("모든 날짜 백필 분석 및 적재 완료.")
