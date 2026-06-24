from database.client import supabase
from core.indicators import get_rs_score
import pandas as pd
from datetime import datetime

def run_analysis_pipeline(market='KR'):
    # 1. 분석 대상 티커와 벤치마크 불러오기
    # market에 따른 벤치마크 설정
    benchmark_ticker = "^KS11" if market == "KR" else "^GSPC"
    
    # 2. 최근 120일 치 가격 데이터 조회 (계산 안정성을 위해 window보다 길게 조회)
    # stock_prices 테이블에서 market에 해당하는 모든 종목 데이터 가져오기
    prices = supabase.table("stock_prices").select("*").execute().data
    df = pd.DataFrame(prices)
    
    # 3. RS 점수 계산
    rs_map = get_rs_score(df, benchmark_ticker=benchmark_ticker, window=90)
    
    # 4. 결과 DB 적재 (daily_analysis 테이블)
    today = datetime.now().strftime('%Y-%m-%d')
    analysis_data = [
        {
            "ticker": ticker,
            "rs_score": float(score),
            "analysis_date": today,
            "market": market
        }
        for ticker, score in rs_map.items()
    ]
    
    # Upsert 실행
    supabase.table("daily_analysis").upsert(analysis_data, on_conflict="ticker,analysis_date").execute()
    print(f"[{market}] 분석 완료 및 {len(analysis_data)}건 DB 적재 완료.")
