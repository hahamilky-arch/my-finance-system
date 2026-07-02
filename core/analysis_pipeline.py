import pandas as pd
import numpy as np
from datetime import datetime
from database.client import supabase
from core.indicators import get_rs_score

def safe_float(val):
    """NaN 또는 Infinity 값을 0.0으로 정제하는 안전한 변환 함수"""
    val = float(val)
    if not np.isfinite(val):
        return 0.0
    return val

def run_analysis_pipeline(market='KR',target_date=None):
    # 날짜 로그 출력 (가장 중요)
    print(f"DEBUG: 파이프라인 대상 날짜 확인 -> {target_date}")
    
    # 날짜가 지정되지 않으면 오늘 날짜 사용
    analysis_date = target_date if target_date else datetime.now().strftime('%Y-%m-%d')
    
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

    # 5. RS 점수 및 가중 모멘텀 계산
    if benchmark_ticker not in pivot_df.columns:
        print(f"에러: 벤치마크 데이터({benchmark_ticker})가 없습니다.")
        return
        
    rs_map = get_rs_score(pivot_df, benchmark_ticker=benchmark_ticker, window=90)
    
    # 가중 모멘텀 계산 (1M:20, 2M:40, 4M:80, 6M:120, 12M:240 거래일 기준)
    r1 = pivot_df.pct_change(20).iloc[-1]
    r2 = pivot_df.pct_change(40).iloc[-1]
    r4 = pivot_df.pct_change(80).iloc[-1]
    r6 = pivot_df.pct_change(120).iloc[-1]
    r12 = pivot_df.pct_change(240).iloc[-1]
    
    weighted_momentum_series = (r1.fillna(0) * 12) + (r2.fillna(0) * 6) + \
                               (r4.fillna(0) * 4) + (r6.fillna(0) * 2) + \
                               (r12.fillna(0) * 1)
    
    # 순위 계산 (높은 점수가 1위)
    rank_map = weighted_momentum_series.rank(ascending=False)
    
    # 6. 결과 DB 적재
    # today = datetime.now().strftime('%Y-%m-%d')
    # 6. 결과 DB 적재 부분 수정
    # [수정] target_date가 있으면 사용하고, 없으면 오늘 날짜 사용
    save_date = target_date if target_date else datetime.now().strftime('%Y-%m-%d')
    
    analysis_data = []
    
    for ticker in ticker_list:
        if ticker == benchmark_ticker:
            continue
            
        current_close = pivot_df.loc[pivot_df.index[-1], ticker] if ticker in pivot_df.columns else 0.0
        
        analysis_data.append({
            "ticker": ticker,
            "rs_score": safe_float(rs_map.get(ticker, 0.0)),
            "momentum_rank": int(rank_map.get(ticker, 999)),
            "weighted_momentum": safe_float(weighted_momentum_series.get(ticker, 0.0)),
            "close_price": safe_float(current_close),
            "price_date": save_date,
            "market": market
        })
    
    if analysis_data:
        print(f"[{ticker} {today}] 등록.")
        supabase.table("daily_analysis").upsert(analysis_data, on_conflict="ticker,price_date").execute()
        print(f"[{market}] 가중 모멘텀 분석 완료 및 {len(analysis_data)}건 DB 적재 완료.")
    else:
        print("적재할 유효한 데이터가 없습니다.")

# 파이프라인 실행
if __name__ == "__main__":
    #run_analysis_pipeline('KR')
    # 실행 인자에서 날짜를 가져옵니다 (python run_pipeline.py --target_date 2026-06-26)
    # 런타임에 인자가 전달되지 않으면 None으로 설정하여 오늘 날짜가 사용되게 합니다.
    target_date = None
    if len(sys.argv) > 1:
        # 명령행 인자에서 target_date 값을 추출 (간단한 예시)
        for i in range(len(sys.argv)):
            if sys.argv[i] == "--target_date" and i + 1 < len(sys.argv):
                target_date = sys.argv[i+1]
    
    run_analysis_pipeline('KR', target_date=target_date)
