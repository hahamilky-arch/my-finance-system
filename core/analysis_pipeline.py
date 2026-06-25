import pandas as pd
from datetime import datetime
from database.client import supabase
from core.indicators import get_rs_score

def run_analysis_pipeline(market='KR'):
    # 1. 벤치마크 설정
    benchmark_ticker = "^KS11" if market == "KR" else "^GSPC"
    
    # 2. 분석 대상 티커 리스트 가져오기
    target_tickers = supabase.table("stocks") \
        .select("ticker") \
        .or_(f"market.eq.{market},market.eq.INDEX") \
        .execute().data
    
    if not target_tickers:
        print("대상 티커 목록이 없습니다.")
        return
        
    ticker_list = [t["ticker"] for t in target_tickers]
    
    # 3. 데이터 가져오기
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
    
    # 4. 데이터 피벗 및 전처리
    pivot_df = df.pivot(index='price_date', columns='ticker', values='close_price') \
                 .sort_index() \
                 .ffill()

    # 5. RS 점수 및 모멘텀 순위 계산
    if benchmark_ticker not in pivot_df.columns:
        print(f"에러: 벤치마크 데이터({benchmark_ticker})가 없습니다.")
        return
        
    rs_map = get_rs_score(pivot_df, benchmark_ticker=benchmark_ticker, window=90)
    
    # 모멘텀 순위 계산 (90일 수익률 기준)
    returns_90d = pivot_df.pct_change(90).iloc[-1]
    rank_map = returns_90d.rank(ascending=False)
    
    # 6. 결과 DB 적재
    today = datetime.now().strftime('%Y-%m-%d')
    analysis_data = []
    
    for ticker in ticker_list:
        if ticker == benchmark_ticker:
            continue
            
        # 데이터 존재 여부 확인 및 값 할당
        current_close = pivot_df.loc[pivot_df.index[-1], ticker] if ticker in pivot_df.columns else 0.0
        rs_val = rs_map.get(ticker, 0.0)
        rank_val = rank_map.get(ticker, 999)
        momentum_val = returns_90d.get(ticker, 0.0)
        
        analysis_data.append({
            "ticker": ticker,
            "rs_score": float(rs_val) if pd.notna(rs_val) else 0.0,
            "momentum_rank": int(rank_val) if pd.notna(rank_val) else 999,
            "weighted_momentum": float(momentum_val) if pd.notna(momentum_val) else 0.0,
            "close_price": float(current_close) if pd.notna(current_close) else 0.0,
            "price_date": today,
            "market": market
        })
    
    if analysis_data:
        supabase.table("daily_analysis").upsert(analysis_data, on_conflict="ticker,price_date").execute()
        print(f"[{market}] 분석 완료 및 {len(analysis_data)}건 DB 적재 완료.")
    else:
        print("적재할 유효한 데이터가 없습니다.")

# 파이프라인 실행
if __name__ == "__main__":
    run_analysis_pipeline('KR')
