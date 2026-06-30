import pandas as pd
from datetime import datetime
from database.client import supabase
from core.indicators import get_rs_score

def calculate_weighted_momentum(pivot_df):
    # 각 기간별 수익률 계산 및 가중치 적용
    r1 = pivot_df.pct_change(20).iloc[-1]
    r2 = pivot_df.pct_change(40).iloc[-1]
    r4 = pivot_df.pct_change(80).iloc[-1]
    r6 = pivot_df.pct_change(120).iloc[-1]
    r12 = pivot_df.pct_change(240).iloc[-1]
    
    weighted_score = (r1.fillna(0) * 12) + (r2.fillna(0) * 6) + \
                     (r4.fillna(0) * 4) + (r6.fillna(0) * 2) + \
                     (r12.fillna(0) * 1)
    return weighted_score

def run_analysis_pipeline(market='KR'):
    benchmark_ticker = "^KS11" if market == "KR" else "^GSPC"
    
    # 1. 티커 리스트 로드
    target_tickers = supabase.table("stocks").select("ticker").or_(f"market.eq.{market},market.eq.INDEX").execute().data
    if not target_tickers:
        print("대상 티커 목록이 없습니다.")
        return
    ticker_list = [t["ticker"] for t in target_tickers]
    
    # 2. 가격 데이터 로드
    prices = []
    for ticker in ticker_list:
        try:
            response = supabase.table("stock_prices").select("ticker, price_date, close_price").eq("ticker", ticker).order("price_date", desc=False).limit(300).execute()
            if response.data:
                prices.extend(response.data)
        except Exception as e:
            print(f"[{ticker}] 데이터 조회 실패: {e}")
            
    if not prices:
        print("분석할 데이터가 없습니다.")
        return

    df = pd.DataFrame(prices)
    pivot_df = df.pivot(index='price_date', columns='ticker', values='close_price').sort_index().ffill()

    # 3. 모멘텀/RS 계산
    if benchmark_ticker not in pivot_df.columns:
        print(f"벤치마크 {benchmark_ticker} 데이터 없음.")
        return
        
    rs_map = get_rs_score(pivot_df, benchmark_ticker=benchmark_ticker, window=90)
    momentum_scores = calculate_weighted_momentum(pivot_df)
    rank_map = momentum_scores.rank(ascending=False)
    
    # 4. DB 적재 데이터 생성
    today = datetime.now().strftime('%Y-%m-%d')
    analysis_data = []
    
    for ticker in ticker_list:
        if ticker == benchmark_ticker: continue
        
        analysis_data.append({
            "ticker": ticker,
            "rs_score": float(rs_map.get(ticker, 0.0)),
            "momentum_rank": int(rank_map.get(ticker, 999)),
            "weighted_momentum": float(momentum_scores.get(ticker, 0.0)),
            "close_price": float(pivot_df.loc[pivot_df.index[-1], ticker] if ticker in pivot_df.columns else 0.0),
            "price_date": today,
            "market": market
        })
    
    # 5. 적재
    if analysis_data:
        supabase.table("daily_analysis").upsert(analysis_data, on_conflict="ticker,price_date").execute()
        print(f"[{market}] {len(analysis_data)}건 DB 적재 완료.")

if __name__ == "__main__":
    run_analysis_pipeline('KR')
