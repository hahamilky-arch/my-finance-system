import numpy as np
import pandas as pd

def get_rs_score(pivot_df, benchmark_ticker, window=20):
    """
    함수명을 유지하면서, 최근 window 기간의 상대적 초과 수익률(RS)을 계산합니다.
    데이터가 지정된 window보다 부족하더라도 min_periods=1을 통해 가용한 데이터로 계산하며,
    결과 중 누락된 값(NaN)은 0.0으로 안전하게 처리합니다.
    """
    if benchmark_ticker not in pivot_df.columns:
        return pd.Series(0.0, index=pivot_df.columns)

    # 지정된 window 기간 동안 데이터가 일부 부족해도 가용한 기간만큼 수익률 계산
    returns = pivot_df.pct_change(window, min_periods=1)
    
    # 벤치마크 대비 초과 수익률 (Alpha) 산출
    excess_returns = returns.sub(returns[benchmark_ticker], axis=0)
    
    # 마지막 시점(오늘)의 초과 수익률 값을 추출
    rs_scores = excess_returns.iloc[-1]
    
    # 계산 과정에서 발생한 NaN(데이터 부족 등)을 0.0으로 안전하게 치환
    rs_scores = rs_scores.fillna(0.0)
    
    return rs_scores
