import numpy as np
import pandas as pd

def get_rs_score(pivot_df, benchmark_ticker, window=20):
    """
    함수명을 유지하면서, 최근 window 기간의 상대적 초과 수익률(RS)을 계산합니다.
    """
    # 수익률 계산 (pct_change는 NaN을 자동으로 처리하기 용이함)
    returns = pivot_df.pct_change(window)
    
    # 벤치마크 대비 초과 수익률 (Alpha)
    # 지수 수익률을 모든 종목에서 뺍니다.
    excess_returns = returns.sub(returns[benchmark_ticker], axis=0)
    
    # 마지막 시점(오늘)의 초과 수익률 값을 추출
    rs_scores = excess_returns.iloc[-1]
    
    # 결과가 Series 형태이므로 딕셔너리로 변환하여 반환 (기존 호출부 호환성 유지)
    return rs_scores
