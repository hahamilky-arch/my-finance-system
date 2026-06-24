import pandas as pd
import numpy as np
from scipy import stats

#
# RS 점수를 계산
#
def get_rs_score(price_df, benchmark_ticker="^KS11", window=90):
    pivot_df = price_df.pivot(index='price_date', columns='ticker', values='close_price').sort_index()
    
    # 벤치마크 수익률 고정
    bench_ret = np.log(pivot_df[benchmark_ticker] / pivot_df[benchmark_ticker].shift(1))
    
    # 수익률 산출
    returns = np.log(pivot_df / pivot_df.shift(1))
    
    # 벤치마크 제외한 종목별 상대 수익률 산출
    relative_returns = returns.drop(columns=[benchmark_ticker]).sub(bench_ret, axis=0)
    
    def calc_slope(s):
        # 데이터가 너무 적은 경우(상장 초기 등) 방지
        if s.isna().sum() > window * 0.2: return 0 
        y = s.fillna(0).cumsum()
        x = np.arange(len(y))
        slope, _, _, _, _ = stats.linregress(x, y)
        return slope

    # 각 종목별로 RS 점수 계산
    rs_scores = relative_returns.rolling(window=window).apply(calc_slope)
    
    return rs_scores.iloc[-1]