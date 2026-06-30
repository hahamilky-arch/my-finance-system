import pandas as pd
from datetime import datetime
from database.client import supabase
from core.indicators import get_rs_score

def calculate_weighted_momentum(pivot_df):
    """
    12(1M) + 6(2M) + 4(4M) + 2(6M) + 1(12M) 가중 모멘텀 계산
    """
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
    
    target_tickers = supabase.table("stocks").select("ticker").or_(f"market.eq.{market},market.eq.INDEX").execute().data
    if not target_tickers:
        print("대상 티커 목록이 없습니다.")
        return
        
    ticker_list = [t["ticker"] for t in target_tickers]
    
    prices = []
    print(f"총 {len(ticker_list)}개 종목의 데이터를 로드합니다.")
    
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
    pivot_df = df.pivot(index='price_date', columns='ticker', values='close_price').sort_index().ffill()

    if benchmark_ticker not in pivot_df.columns:
        print(f"에러: 벤치마크 데이터({benchmark_ticker})가 없습니다.")
        return
        
    # RS 점수 계산
    rs_map = get_rs_score(pivot_df, benchmark_ticker=benchmark_ticker, window=90)
    
    # 가중 모멘텀 계산 및 순위 매기기
    momentum_scores = calculate_weighted_momentum(pivot_df)
    rank_map = momentum_scores.rank(ascending=False)
    
    today = datetime.now().strftime('%Y-%m-%d')
    analysis_data = []
    
    for ticker in ticker_list:
        if ticker == benchmark_ticker:
            continue
            
        current_close = pivot_df.loc[pivot_df.index[-1], ticker] if ticker in pivot_df.columns else 0.0
        
        analysis_data.append({
            "ticker": ticker,
            "rs_score": float(rs_map.get(ticker, 0.0)),
            "momentum_rank": int(rank_map.get(ticker, 999)),
            "weighted_momentum": float(momentum_scores.get(ticker, 0.0)),
            "close_price": float(current_close),
            "price_date": today,
            "market": market
        })
    
    if analysis_data:
        supabase.table("daily_analysis").upsert(analysis_data, on_conflict="ticker,price_date").execute()
        print(f"[{market}] 가중 모멘텀 분석 완료 및 {len(analysis_data)}건 DB 적재 완료.")
    else:
        print("적재할 유효한 데이터가 없습니다.")

if __name__ == "__main__":
    run_analysis_pipeline('KR')
