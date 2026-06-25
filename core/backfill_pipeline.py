import pandas as pd
import os
from datetime import datetime, timedelta
from core.indicators import get_rs_score
from supabase import create_client
from dotenv import load_dotenv

load_dotenv()
supabase = create_client(os.getenv("SUPABASE_URL"), os.getenv("SUPABASE_KEY"))

def backfill_pipeline(start_date_str, end_date_str, market='KR'):
    start_date = datetime.strptime(start_date_str, '%Y-%m-%d')
    end_date = datetime.strptime(end_date_str, '%Y-%m-%d')
    date_range = [start_date + timedelta(days=x) for x in range((end_date - start_date).days + 1)]
    
    benchmark_ticker = "^KS11" if market == "KR" else "^GSPC"
    
    # 분석 대상 티커 리스트
    target_tickers = [t["ticker"] for t in supabase.table("stocks").select("ticker").or_(f"market.eq.{market},market.eq.INDEX").execute().data]
    
    # 1. 종목별 루프를 돌며 주가 데이터 수집 (건수 제한 회피)
    print(f"총 {len(target_tickers)}개 종목의 과거 데이터 수집 시작...")
    limit_date = (start_date - timedelta(days=300)).strftime('%Y-%m-%d')
    
    all_prices = []
    for ticker in target_tickers:
        try:
            response = supabase.table("stock_prices") \
                .select("ticker, price_date, close_price") \
                .eq("ticker", ticker) \
                .gte("price_date", limit_date) \
                .lte("price_date", end_date_str) \
                .execute()
            if response.data:
                all_prices.extend(response.data)
        except Exception as e:
            print(f"[{ticker}] 조회 실패: {e}")
            
    df_all = pd.DataFrame(all_prices)
    print(f"데이터 수집 완료. 총 {len(df_all)} 행.")
    
    # 2. 날짜별 루프 실행
    for current_date in date_range:
        d_str = current_date.strftime('%Y-%m-%d')
        sub_df = df_all[df_all['price_date'] <= d_str]
        pivot_df = sub_df.pivot(index='price_date', columns='ticker', values='close_price').sort_index().ffill()
        
        if benchmark_ticker not in pivot_df.columns:
            continue
            
        # 3. RS 및 모멘텀 계산
        rs_map = get_rs_score(pivot_df, benchmark_ticker=benchmark_ticker, window=90)
        returns_90d = pivot_df.pct_change(90).iloc[-1]
        rank_map = returns_90d.rank(ascending=False)
        
        # 4. 저장용 데이터 생성
        analysis_data = []
        for ticker in target_tickers:
            if ticker == benchmark_ticker or ticker not in pivot_df.columns:
                continue
            
            current_close = pivot_df.loc[pivot_df.index[-1], ticker]
            rs_val = rs_map.get(ticker, 0.0)
            rank_val = rank_map.get(ticker, 999)
            
            analysis_data.append({
                "ticker": ticker,
                "rs_score": float(rs_val) if pd.notna(rs_val) else 0.0,
                "momentum_rank": int(rank_val) if pd.notna(rank_val) else 999,
                "weighted_momentum": float(returns_90d[ticker]) if pd.notna(returns_90d[ticker]) else 0.0,
                "close_price": float(current_close) if pd.notna(current_close) else 0.0,
                "price_date": d_str,
                "market": market
            })
            
        # 5. DB 적재
        if analysis_data:
            supabase.table("daily_analysis").upsert(analysis_data, on_conflict="ticker,price_date").execute()
            print(f"[{d_str}] 완료: {len(analysis_data)}개 종목 적재")
        
    print("모든 날짜 분석 및 적재 완료.")
