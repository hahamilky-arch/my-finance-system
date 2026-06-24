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
    
    # 3. 데이터 가져오기 (100개씩 나누어 조회하여 1,000건 제한 우회)
    prices = []
    chunk_size = 100 
    print(f"총 {len(ticker_list)}개 종목에 대해 데이터를 조회합니다.")
    
    for i in range(0, len(ticker_list), chunk_size):
        chunk = ticker_list[i : i + chunk_size]
        # 디버깅: 루프가 제대로 도는지 확인
        print(f"조회 중: {i} ~ {i + len(chunk)}번째 종목...")
        
        response = supabase.table("stock_prices") \
            .select("ticker, price_date, close_price") \
            .in_("ticker", chunk) \
            .execute()
        
        if response.data:
            prices.extend(response.data)
        
    if not prices:
        print(f"[{market}] 분석할 가격 데이터가 없습니다.")
        return

    df = pd.DataFrame(prices)
    print(f"Supabase에서 가져온 총 데이터 행 개수: {len(df)}")
    print(f"가격 데이터에 존재하는 고유 종목 수: {df['ticker'].nunique()}")
    
    # 필수 컬럼 존재 여부 확인
    required_cols = ['price_date', 'ticker', 'close_price']
    if not all(col in df.columns for col in required_cols):
        print(f"에러: 필수 컬럼이 누락되었습니다. 현재 컬럼: {df.columns.tolist()}")
        return

    # 4. 데이터 피벗 및 전처리
    # 날짜 정렬 후, 빈 값은 이전 종가로 채움 (Forward Fill)
    pivot_df = df.pivot(index='price_date', columns='ticker', values='close_price') \
                 .sort_index() \
                 .ffill()

    print(f"Pivot 데이터 형태: {pivot_df.shape}") # (날짜수, 종목수)

    # 5. RS 점수 계산
    if benchmark_ticker not in pivot_df.columns:
        print(f"에러: 벤치마크 데이터({benchmark_ticker})가 피벗 데이터에 없습니다.")
        return
        
    rs_map = get_rs_score(pivot_df, benchmark_ticker=benchmark_ticker, window=90)
    print(f"RS Map 샘플: {list(rs_map.items())[:5]}")
    
    # 6. 결과 DB 적재
    today = datetime.now().strftime('%Y-%m-%d')
    # NaN일 경우 0.0으로 저장하여 데이터 누락 방지
    analysis_data = [
        {
            "ticker": ticker,
            "rs_score": float(score) if pd.notna(score) else 0.0,
            "price_date": today,
            "market": market
        }
        for ticker, score in rs_map.items() 
        if ticker != benchmark_ticker
    ]
    
    if analysis_data:
        supabase.table("daily_analysis").upsert(analysis_data, on_conflict="ticker,price_date").execute()
        print(f"[{market}] 분석 완료 및 {len(analysis_data)}건 DB 적재 완료.")
    else:
        print("적재할 유효한 분석 데이터가 없습니다.")
