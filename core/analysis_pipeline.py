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
    
    # 3. 데이터 가져오기 (종목별 개별 조회 방식 - 가장 안정적)
    prices = []
    print(f"총 {len(ticker_list)}개 종목의 데이터를 안전하게 로드합니다.")
    
    for ticker in ticker_list:
        try:
            # 개별 종목별로 최신 300일치 데이터를 순차적으로 조회
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
    print(f"Supabase에서 가져온 총 데이터 행 개수: {len(df)}")
    print(f"가격 데이터에 존재하는 고유 종목 수: {df['ticker'].nunique()}")
    
    # 4. 데이터 피벗 및 전처리
    pivot_df = df.pivot(index='price_date', columns='ticker', values='close_price') \
                 .sort_index() \
                 .ffill()

    print(f"Pivot 데이터 형태: {pivot_df.shape}")

    # 5. RS 점수 계산
    if benchmark_ticker not in pivot_df.columns:
        print(f"에러: 벤치마크 데이터({benchmark_ticker})가 피벗 데이터에 없습니다.")
        return
        
    rs_map = get_rs_score(pivot_df, benchmark_ticker=benchmark_ticker, window=90)
    
    # 타입 안전성 확보: Series나 Dict 모두 대응 가능한 순회 방식
    rs_items = rs_map.items() if hasattr(rs_map, 'items') else pd.Series(rs_map).items()
    
    # 6. 결과 DB 적재
    today = datetime.now().strftime('%Y-%m-%d')
    analysis_data = [
        {
            "ticker": ticker,
            "rs_score": float(score) if pd.notna(score) else 0.0,
            "price_date": today,
            "market": market
        }
        for ticker, score in rs_items 
        if ticker != benchmark_ticker
    ]
    
    if analysis_data:
        # 400여 건의 데이터를 한 번에 upsert
        supabase.table("daily_analysis").upsert(analysis_data, on_conflict="ticker,price_date").execute()
        print(f"[{market}] 분석 완료 및 {len(analysis_data)}건 DB 적재 완료.")
    else:
        print("적재할 유효한 분석 데이터가 없습니다.")
