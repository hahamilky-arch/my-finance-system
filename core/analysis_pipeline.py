import pandas as pd
from datetime import datetime
from database.client import supabase
from core.indicators import get_rs_score

def run_analysis_pipeline(market='KR'):
    # 1. 벤치마크 설정
    benchmark_ticker = "^KS11" if market == "KR" else "^GSPC"
    
    # 2. 시장 내 모든 티커 및 지수 데이터 조회
    # stocks 테이블에서 대상 시장 종목들 + 지수 조회
    target_tickers = supabase.table("stocks") \
        .select("ticker") \
        .or_(f"market.eq.{market},market.eq.INDEX") \
        .execute().data
    
    ticker_list = [t["ticker"] for t in target_tickers]
    
    # 3. 데이터 가져오기 (stock_prices에서 해당 티커들만)
    # 데이터를 메모리상에서 빠르게 처리하기 위해 필터링
    prices = supabase.table("stock_prices") \
        .select("ticker, price_date, close_price") \
        .in_("ticker", ticker_list) \
        .execute().data
        
    if not prices:
        print("분석할 데이터가 없습니다.")
        return

    df = pd.DataFrame(prices)
    
    # 4. 분석을 위해 데이터 피벗 (날짜별/종목별 종가 매트릭스 생성)
    # 이 과정이 필수입니다: 그래야 get_rs_score가 종목별/날짜별 계산을 수행합니다.
    pivot_df = df.pivot(index='price_date', columns='ticker', values='close_price')
    
    # 5. RS 점수 계산
    # pivot_df는 이제 인덱스가 날짜, 컬럼이 티커(지수 포함)인 형태입니다.
    rs_map = get_rs_score(pivot_df, benchmark_ticker=benchmark_ticker, window=90)
    
    # 6. 결과 DB 적재 (daily_analysis 테이블)
    today = datetime.now().strftime('%Y-%m-%d')
    analysis_data = [
        {
            "ticker": ticker,
            "rs_score": float(score),
            "analysis_date": today,
            "market": market
        }
        for ticker, score in rs_map.items() 
        if ticker != benchmark_ticker # 벤치마크 자체는 분석 결과에서 제외
    ]
    
    if analysis_data:
        supabase.table("daily_analysis").upsert(analysis_data, on_conflict="ticker,analysis_date").execute()
        print(f"[{market}] 분석 완료 및 {len(analysis_data)}건 DB 적재 완료.")
    else:
        print("적재할 데이터가 없습니다.")
