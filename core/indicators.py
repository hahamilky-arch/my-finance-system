import numpy as np
import pandas as pd

def get_rs_score(pivot_df, benchmark_ticker, window=20):
    """
    지정된 window 기간 동안의 상대적 초과 수익률(RS)을 계산합니다.
    데이터가 window 기간보다 부족할 경우, 가용한 최대 기간을 기준으로 계산합니다.
    """
    if benchmark_ticker not in pivot_df.columns:
        return pd.Series(0.0, index=pivot_df.columns)

    rs_scores = {}
    
    # 벤치마크의 전체 수익률 계산을 미리 준비
    bench_series = pivot_df[benchmark_ticker]

    for ticker in pivot_df.columns:
        if ticker == benchmark_ticker:
            continue
            
        stock_series = pivot_df[ticker].dropna()
        if stock_series.empty:
            rs_scores[ticker] = 0.0
            continue
            
        # 실제 가용 데이터 개수 확인 후 동적 window 결정 (지정된 window보다 적으면 있는 만큼만 사용)
        available_len = len(stock_series)
        effective_window = min(window, available_len - 1)
        
        if effective_window <= 0:
            rs_scores[ticker] = 0.0
            continue
            
        try:
            # 현재가와 과거 시점 가격 비교를 통한 수익률 계산
            current_price = pivot_df[ticker].iloc[-1]
            past_price = pivot_df[ticker].iloc[-1 - effective_window]
            
            if pd.isna(past_price) or past_price == 0:
                rs_scores[ticker] = 0.0
                continue
                
            stock_return = (current_price - past_price) / past_price
            
            # 벤치마크의 동일 기간 수익률 계산
            bench_current = bench_series.iloc[-1]
            bench_past = bench_series.iloc[-1 - effective_window]
            
            if pd.isna(bench_past) or bench_past == 0:
                bench_return = 0.0
            else:
                bench_return = (bench_current - bench_past) / bench_past
                
            # 초과 수익률(RS) 산출
            rs_scores[ticker] = float(stock_return - bench_return)
        except Exception:
            rs_scores[ticker] = 0.0

    return pd.Series(rs_scores)
