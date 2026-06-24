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
    
    # 3. 데이터 가져오기 (Supabase에서 데이터를 안전하게 추출)
    response = supabase.table("stock_prices") \
        .select("ticker, price_date, close_price") \
        .in_("ticker", ticker_list) \
        .execute()
        
    prices = response.data
        
    if not prices or len(prices) == 0:
        print(f"[{market}] 분석할 가격 데이터가 없습니다.")
        return

    df = pd.DataFrame(prices)
    
    # [디버깅] 데이터 구조 확인
    print(f"로드된 컬럼: {df.columns.tolist()}")
    
    # 필수 컬럼 존재 여부 확인 (에러 방지)
    required_cols = ['price_date', 'ticker', 'close_price']
    if not all(col in df.columns for col in required_cols):
        print(f"에러: 필수 컬럼이 누락되었습니다. 현재 컬럼: {df.columns.tolist()}")
        return

    # 4. 데이터 피벗
    # pivot 전에 정렬을 하면 더 정확한 시계열 분석이 가능합니다.
    pivot_df = df.pivot(index='price_date', columns='ticker', values='close_price').sort_index()
    
    # 5. RS 점수 계산
    # get_rs_score 내부에서 benchmark_ticker가 pivot_df에 있는지 확인해야 합니다.
    if benchmark_ticker not in pivot_df.columns:
        print(f"에러: 벤치마크 데이터({benchmark_ticker})가 부족하여 분석할 수 없습니다.")
        return
        
    rs_map = get_rs_score(pivot_df, benchmark_ticker=benchmark_ticker, window=90)
    
    # 6. 결과 DB 적재
    today = datetime.now().strftime('%Y-%m-%d')
    analysis_data = [
        {
            "ticker": ticker,
            "rs_score": float(score),
            "price_date": today,
            "market": market
        }
        for ticker, score in rs_map.items() 
        if ticker != benchmark_ticker and pd.notna(score)
    ]
    
    if analysis_data:
        supabase.table("daily_analysis").upsert(analysis_data, on_conflict="ticker,price_date").execute()
        print(f"[{market}] 분석 완료 및 {len(analysis_data)}건 DB 적재 완료.")
    else:
        print("적재할 유효한 분석 데이터가 없습니다.")
