import pandas as pd
import numpy as np  # 추가
from datetime import datetime
from database.client import supabase
from core.indicators import get_rs_score

def calculate_weighted_momentum(pivot_df):
    r1 = pivot_df.pct_change(20).iloc[-1]
    r2 = pivot_df.pct_change(40).iloc[-1]
    r4 = pivot_df.pct_change(80).iloc[-1]
    r6 = pivot_df.pct_change(120).iloc[-1]
    r12 = pivot_df.pct_change(240).iloc[-1]
    
    # 계산 결과에 NaN이 발생하면 0으로 치환
    weighted_score = (r1.fillna(0) * 12) + (r2.fillna(0) * 6) + \
                     (r4.fillna(0) * 4) + (r6.fillna(0) * 2) + \
                     (r12.fillna(0) * 1)
    return weighted_score

def run_analysis_pipeline(market='KR'):
    benchmark_ticker = "^KS11" if market == "KR" else "^GSPC"
    
    target_tickers = supabase.table("stocks").select("ticker").or_(f"market.eq.{market},market.eq.INDEX").execute().data
    if not target_tickers: return
    ticker_list = [t["ticker"] for t in target_tickers]
    
    prices = []
    for ticker in ticker_list:
        try:
            response = supabase.table("stock_prices").select("ticker, price_date, close_price").eq("ticker", ticker).order("price_date", desc=False).limit(300).execute()
            if response.data: prices.extend(response.data)
        except Exception as e: print(f"[{ticker}] 조회 실패: {e}")
            
    if not prices: return

    df = pd.DataFrame(prices)
    pivot_df = df.pivot(index='price_date', columns='ticker', values='close_price').sort_index().ffill()

    if benchmark_ticker not in pivot_df.columns: return
        
    rs_map = get_rs_score(pivot_df, benchmark_ticker=benchmark_ticker, window=90)
    momentum_scores = calculate_weighted_momentum(pivot_df)
    rank_map = momentum_scores.rank(ascending=False)
    
    today = datetime.now().strftime('%Y-%m-%d')
    analysis_data = []
    
    for ticker in ticker_list:
        if ticker == benchmark_ticker: continue
        
        # 각 값을 추출하고 타입 변환 및 NaN/Inf 체크
        w_mom = momentum_scores.get(ticker, 0.0)
        rs_val = rs_map.get(ticker, 0.0)
        close_val = pivot_df.loc[pivot_df.index[-1], ticker] if ticker in pivot_df.columns else 0.0
        
        # 값이 숫자가 아니거나 무한대일 경우 0.0으로 강제 고정
        analysis_data.append({
            "ticker": ticker,
            "rs_score": float(rs_val) if np.isfinite(rs_val) else 0.0,
            "momentum_rank": int(rank_map.get(ticker, 999)),
            "weighted_momentum": float(w_mom) if np.isfinite(w_mom) else 0.0,
            "close_price": float(close_val) if np.isfinite(close_val) else 0.0,
            "price_date": today,
            "market": market
        })
    
    if analysis_data:
        # DB 적재 전 데이터 확인 (디버깅용)
        try:
            supabase.table("daily_analysis").upsert(analysis_data, on_conflict="ticker,price_date").execute()
            print(f"[{market}] {len(analysis_data)}건 DB 적재 완료.")
        except Exception as e:
            print(f"DB 업서트 실패: {e}")
            # 에러 발생 시 어떤 데이터가 문제인지 출력
            print(analysis_data[:3]) 

if __name__ == "__main__":
    run_analysis_pipeline('KR')
