import numpy as np
import pandas as pd

def get_rs_score(pivot_df, benchmark_ticker, window=20):
    """
    pct_change 에러를 방지하기 위해 shift()를 직접 사용하여 window 기간 동안의 상대적 초과 수익률(RS)을 계산합니다.
    """
    if benchmark_ticker not in pivot_df.columns:
        return pd.Series(0.0, index=pivot_df.columns)

    # shift를 이용해 window 기간 전의 가격과 현재 가격으로 직접 수익률 계산 (min_periods 에러 원천 차단)
    shifted_df = pivot_df.shift(window)
    returns = (pivot_df - shifted_df) / shifted_df
    
    # 벤치마크 대비 초과 수익률 (Alpha) 산출
    excess_returns = returns.sub(returns[benchmark_ticker], axis=0)
    
    # 마지막 시점(오늘)의 초과 수익률 값을 추출
    rs_scores = excess_returns.iloc[-1]
    
    # 계산 과정에서 발생한 NaN(데이터 부족 등)을 0.0으로 안전하게 치환
    rs_scores = rs_scores.fillna(0.0)
    
    return rs_scores
