import pandas as pd
import numpy as np
import sys
from datetime import datetime
from database.client import supabase
from core.indicators import get_rs_score

def safe_float(val):
    """NaN 또는 Infinity 값을 0.0으로 정제"""
    val = float(val)
    if not np.isfinite(val):
        return 0.0
    return val

def run_analysis_pipeline(market='KR', target_date=None):
    print(f"DEBUG: 파이프라인 대상 날짜 확인 -> {target_date}")
    analysis_date = target_date if target_date else datetime.now().strftime('%Y-%m-%d')
    
    benchmark_ticker = "^KS11" if market == "KR" else "^GSPC"
    
    # 1. 대상 티커 가져오기
    target_tickers = supabase.table("stocks") \
        .select("ticker") \
        .or_(f"market.eq.{market},market.eq.INDEX") \
        .execute().data
    
    if not target_tickers:
        print("대상 티커 목록이 없습니다.")
        return
        
    ticker_list = [t["ticker"] for t in target_tickers]
    
    # 2. 데이터 가져오기 (각 종목별 300일치)
    prices = []
    print(f"총 {len(ticker_list)}개 종목 데이터를 로드합니다.")
    
    for ticker in ticker_list:
        try:
            response = supabase.table("stock_prices") \
                .select("ticker, price_date, close_price") \
                .eq("ticker", ticker) \
                .order("price_date", desc=False) \
                .limit(300) \
                .execute()
            if response.data:
                prices.extend(response.data)
        except Exception as e:
            print(f"[{ticker}] 조회 실패: {e}")
        
    if not prices:
        print(f"[{market}] 분석할 가격 데이터가 없습니다.")
        return

    df = pd.DataFrame(prices)
    
    # 3. 데이터 피벗 및 전처리
    pivot_df = df.pivot(index='price_date', columns='ticker', values='close_price') \
                 .sort_index() \
                 .ffill()

    # 4. 각종 지표 계산
    if benchmark_ticker not in pivot_df.columns:
        print(f"에러: 벤치마크 데이터({benchmark_ticker})가 없습니다.")
        return
        
    # [수정] 이동평균선 계산 (최신 데이터 시점)
    ma10_series = pivot_df.rolling(window=10, min_periods=1).mean().iloc[-1]
    ma20_series = pivot_df.rolling(window=20, min_periods=1).mean().iloc[-1]
    
    # RS 점수 및 가중 모멘텀 계산
    rs_map = get_rs_score(pivot_df, benchmark_ticker=benchmark_ticker, window=90)
    
    r1 = pivot_df.pct_change(20).iloc[-1]
    r2 = pivot_df.pct_change(40).iloc[-1]
    r4 = pivot_df.pct_change(80).iloc[-1]
    r6 = pivot_df.pct_change(120).iloc[-1]
    r12 = pivot_df.pct_change(240).iloc[-1]
    
    weighted_momentum_series = (r1.fillna(0) * 12) + (r2.fillna(0) * 6) + \
                               (r4.fillna(0) * 4) + (r6.fillna(0) * 2) + \
                               (r12.fillna(0) * 1)
    
    rank_map = weighted_momentum_series.rank(ascending=False)
    
    # 5. 결과 DB 적재
    analysis_data = []
    for ticker in ticker_list:
        if ticker == benchmark_ticker:
            continue
            
        current_close = pivot_df.loc[pivot_df.index[-1], ticker] if ticker in pivot_df.columns else 0.0
        
        analysis_data.append({
            "ticker": ticker,
            "rs_score": safe_float(rs_map.get(ticker, 0.0)),
            "momentum_rank": int(rank_map.get(ticker, 999)),
            "weighted_momentum": safe_float(weighted_momentum_series.get(ticker, 0.0)),
            "close_price": safe_float(current_close),
            "price_date": analysis_date,
            "market": market,
            "ma10": safe_float(ma10_series.get(ticker, 0.0)), # DB 적재용
            "ma20": safe_float(ma20_series.get(ticker, 0.0))  # DB 적재용
        })
    
    if analysis_data:
        supabase.table("daily_analysis").upsert(analysis_data, on_conflict="ticker,price_date").execute()
        print(f"[{market}] 분석 완료! MA10, MA20 포함 {len(analysis_data)}건 DB 적재 완료.")
    else:
        print("적재할 유효한 데이터가 없습니다.")

if __name__ == "__main__":
    target_date = None
    if len(sys.argv) > 2 and sys.argv[1] == "--target_date":
        target_date = sys.argv[2]
    
    run_analysis_pipeline('KR', target_date=target_date)
