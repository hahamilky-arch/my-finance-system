import pandas as pd
import numpy as np
import sys
from datetime import datetime
from database.client import supabase
from core.indicators import get_rs_score

def safe_float(val):
    val = float(val)
    if not np.isfinite(val):
        return 0.0
    return val

def run_analysis_pipeline(market='KR', target_date=None):
    analysis_date = target_date if target_date else datetime.now().strftime('%Y-%m-%d')
    print(f"DEBUG: 파이프라인 실행일 -> {analysis_date}")
    
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
    
    # 2. 데이터 가져오기
    prices = []
    for ticker in ticker_list:
        try:
            # 넉넉하게 300일치 조회
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
        print("분석할 가격 데이터가 없습니다.")
        return

    df = pd.DataFrame(prices)
    
    # 3. 데이터 피벗 및 날짜 필터링 (가장 중요)
    pivot_df = df.pivot(index='price_date', columns='ticker', values='close_price') \
                 .sort_index() \
                 .ffill()

    # [핵심] analysis_date 시점까지만 데이터 필터링
    # 파이프라인 실행일 이후의 데이터는 분석에서 제외하여 데이터 복제 방지
    if analysis_date in pivot_df.index:
        pivot_df = pivot_df.loc[:analysis_date]
    else:
        print(f"경고: {analysis_date} 데이터가 없습니다. 마지막 가용 데이터를 사용합니다.")

    # 4. 각종 지표 계산 (필터링된 pivot_df 기준)
    if benchmark_ticker not in pivot_df.columns:
        print(f"에러: 벤치마크 데이터({benchmark_ticker})가 없습니다.")
        return
        
    ma10_series = pivot_df.rolling(window=10, min_periods=1).mean().iloc[-1]
    ma20_series = pivot_df.rolling(window=20, min_periods=1).mean().iloc[-1]
    
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
            "ma10": safe_float(ma10_series.get(ticker, 0.0)),
            "ma20": safe_float(ma20_series.get(ticker, 0.0))
        })
    
    if analysis_data:
        supabase.table("daily_analysis").upsert(analysis_data, on_conflict="ticker,price_date").execute()
        print(f"[{analysis_date}] {market} 분석 완료 및 DB 적재 완료.")
    else:
        print("적재할 유효한 데이터가 없습니다.")

if __name__ == "__main__":
    target_date = None
    if len(sys.argv) > 2 and sys.argv[1] == "--target_date":
        target_date = sys.argv[2]
    
    run_analysis_pipeline('KR', target_date=target_date)
