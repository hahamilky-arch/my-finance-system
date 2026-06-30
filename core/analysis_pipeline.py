import pandas as pd
from datetime import datetime
from database.client import supabase
from core.indicators import get_rs_score

def calculate_weighted_momentum(pivot_df):
    """
    12(1M) + 6(2M) + 4(4M) + 2(6M) + 1(12M) 가중 모멘텀 계산
    거래일 기준: 1M(20), 2M(40), 4M(80), 6M(120), 12M(240)
    """
    # 기간별 수익률 계산 (데이터 부족 시 NaN 발생할 수 있음)
    r1 = pivot_df.pct_change(20).iloc[-1]
    r2 = pivot_df.pct_change(40).iloc[-1]
    r4 = pivot_df.pct_change(80).iloc[-1]
    r6 = pivot_df.pct_change(120).iloc[-1]
    r12 = pivot_df.pct_change(240).iloc[-1]
    
    # 공식 적용 (fillna로 결측치를 0으로 처리)
    weighted_score = (r1.fillna(0) * 12) + (r2.fillna(0) * 6) + \
                     (r4.fillna(0) * 4) + (r6.fillna(0) * 2) + \
                     (r12.fillna(0) * 1)
                     
    return weighted_score

def run_analysis_pipeline(market='KR'):
    benchmark_ticker = "^KS11" if market == "KR" else "^GSPC"
    
    target_tickers = supabase.table("stocks").select("ticker").or_(f"market.eq.{market},market.eq.INDEX").execute().data
    if not target_tickers: return
        
    ticker_list = [t["ticker"] for t in target_tickers]
    
    prices = []
    for ticker in ticker_list:
        try:
            # 12개월(약 250일) 이상의 데이터가 필요하므로 limit를 300으로 유지
            response = supabase.table("stock_prices").select("ticker, price_date, close_price").eq("ticker", ticker).order("price_date", desc=False).limit(300).execute()
            if response.data: 
                prices.extend(response.data)
        except Exception as e: 
            print(f"[{ticker}] 조회 실패: {e}")
        
    if not prices: return

    df = pd.DataFrame(prices)
    pivot_df = df.pivot(index='price_date', columns='ticker', values='close_price').sort_index().ffill()

    if benchmark_ticker not in pivot_df.columns: return
        
    # RS 점수 계산
    rs_map = get_rs_score(pivot_df, benchmark_ticker=benchmark_ticker, window=90)
    
    # 가중 모멘텀 계산 및 순위 매기기
    momentum_scores = calculate_weighted_momentum(pivot_df)
    rank_map = momentum_scores.rank(ascending=False)
    
    today = datetime.now().strftime('%Y-%m-%d')
    analysis_data = []
    
    for ticker in ticker_list:
        if ticker == benchmark_ticker: continue
            
        current_close = pivot_df.loc[pivot_df.index[-1], ticker] if ticker in pivot_df.columns else 0.0
        
        analysis_data.append({
            "ticker": ticker,
            "rs_score": float(rs_map.get(ticker, 0.0)),
            "momentum_rank": int(rank_map.get(ticker, 999)),
            "weighted_momentum": float(momentum_scores.get(ticker, 0.0)), # 계산된 가중 점수 저장
            "close_price": float(current_close),
            "price_date": today,
            "market": market
        })
    
    if analysis_data:
        supabase.table("daily_analysis").upsert(analysis_data, on_conflict="ticker,price_date").execute()
        print(f"[{market}] 가중 모멘텀 분석 완료 및 {len(analysis_data)}건 DB 적재 완료.")

if __name__ == "__main__":
    run_analysis_pipeline('KR')
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
