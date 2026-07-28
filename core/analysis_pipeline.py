import pandas as pd
import numpy as np
import sys
from datetime import datetime
from database.client import supabase
from core.indicators import get_rs_score

def safe_float(val):
    try:
        val = float(val)
        if not np.isfinite(val):
            return 0.0
        return val
    except (TypeError, ValueError):
        return 0.0

def run_analysis_pipeline(market='KR', target_date=None):
    analysis_date = target_date if target_date else datetime.now().strftime('%Y-%m-%d')
    print(f"DEBUG: 파이프라인 실행일 -> {analysis_date}")
    
    benchmark_ticker = "^KS11" if market == "KR" else "^GSPC"
    
    # 1. 대상 티커와 market 정보 함께 가져오기
    target_tickers = supabase.table("stocks") \
        .select("ticker, market") \
        .or_(f"market.eq.{market},market.eq.INDEX") \
        .execute().data
    
    if not target_tickers:
        print("대상 티커 목록이 없습니다.")
        return
        
    ticker_market_map = {t["ticker"]: t["market"] for t in target_tickers}
    ticker_list = list(ticker_market_map.keys())
    
    # 2. 데이터 가져오기 (stock_prices 테이블에 존재하는 OHLCV 컬럼만 조회)
    prices = []
    for ticker in ticker_list:
        try:
            response = supabase.table("stock_prices") \
                .select("ticker, price_date, open_price, high_price, low_price, close_price, volume") \
                .eq("ticker", ticker) \
                .order("price_date", desc=False) \
                .limit(300) \
                .execute()
            if response.data:
                prices.extend(response.data)
        except Exception as e:
            print(f"[{ticker}] 조회 실패: {e}")
        
    if not prices:
        print("분석할 가격 데이터가 없습니다.")
        return

    df = pd.DataFrame(prices)
    df['price_date'] = pd.to_datetime(df['price_date']).dt.strftime('%Y-%m-%d')
    df['close_price'] = pd.to_numeric(df['close_price'], errors='coerce')
    df['high_price'] = pd.to_numeric(df['high_price'], errors='coerce')
    df['low_price'] = pd.to_numeric(df['low_price'], errors='coerce')
    df['open_price'] = pd.to_numeric(df['open_price'], errors='coerce')
    df['volume'] = pd.to_numeric(df['volume'], errors='coerce').fillna(0)
    
    # 3. 데이터 피벗 (종가, 고가, 저가 등)
    pivot_df = df.pivot(index='price_date', columns='ticker', values='close_price') \
                 .sort_index() \
                 .ffill()

    if analysis_date in pivot_df.index:
        pivot_df = pivot_df.loc[:analysis_date]
    else:
        print(f"경고: {analysis_date} 데이터가 없습니다. 마지막 가용 데이터를 사용합니다.")
        analysis_date = pivot_df.index[-1] if not pivot_df.empty else analysis_date

    # 4. 각종 지표 계산
    if benchmark_ticker not in pivot_df.columns:
        print(f"에러: 벤치마크 데이터({benchmark_ticker})가 없습니다.")
        return
        
    ma10_series = pivot_df.rolling(window=10, min_periods=1).mean().iloc[-1]
    ma20_series = pivot_df.rolling(window=20, min_periods=1).mean().iloc[-1]
    ma50_series = pivot_df.rolling(window=50, min_periods=1).mean().iloc[-1]
    ma200_series = pivot_df.rolling(window=200, min_periods=1).mean().iloc[-1]
    
    # 90일 중장기 RS와 10일 단기 RS 계산
    rs_map_90 = get_rs_score(pivot_df, benchmark_ticker=benchmark_ticker, window=90)
    rs_map_10 = get_rs_score(pivot_df, benchmark_ticker=benchmark_ticker, window=10)
    
    r1 = pivot_df.pct_change(20).iloc[-1]
    r2 = pivot_df.pct_change(40).iloc[-1]
    r4 = pivot_df.pct_change(80).iloc[-1]
    r6 = pivot_df.pct_change(120).iloc[-1]
    r12 = pivot_df.pct_change(240).iloc[-1]
    
    weighted_momentum_series = (r1.fillna(0) * 12) + (r2.fillna(0) * 6) + \
                               (r4.fillna(0) * 4) + (r6.fillna(0) * 2) + \
                               (r12.fillna(0) * 1)
    
    rank_map = weighted_momentum_series.rank(ascending=False)
    
    # 분석일 기준 원본 데이터 맵 (당일 OHLCV 추출용)
    df_analysis_day = df[df['price_date'] == analysis_date].set_index('ticker')
    
    # 피벗 기반 ATR(14) 계산용 데이터프레임 준비
    try:
        high_pivot = df.pivot(index='price_date', columns='ticker', values='high_price').sort_index().ffiling() if 'high_price' in df.columns else pivot_df
        low_pivot = df.pivot(index='price_date', columns='ticker', values='low_price').sort_index().ffill() if 'low_price' in df.columns else pivot_df
        prev_close = pivot_df.shift(1)
        tr1 = high_pivot - low_pivot
        tr2 = (high_pivot - prev_close).abs()
        tr3 = (low_pivot - prev_close).abs()
        true_range = pd.concat([tr1, tr2, tr3], axis=1).max(level=1, axis=1) if hasattr(pd.concat([tr1, tr2, tr3], axis=1), 'max') else pd.maximum(tr1, pd.maximum(tr2, tr3))
        atr_series = true_range.rolling(window=14, min_periods=1).mean().iloc[-1]
    except Exception:
        atr_series = pd.Series(0.0, index=pivot_df.columns)

    # 5. 결과 DB 적재 데이터 생성
    analysis_data = []
    for ticker in ticker_list:
        current_close = pivot_df.loc[analysis_date, ticker] if ticker in pivot_df.columns and analysis_date in pivot_df.index else 0.0
        row_info = df_analysis_day.loc[ticker] if ticker in df_analysis_day.index else {}
        
        analysis_data.append({
            "ticker": ticker,
            "rs_score": safe_float(rs_map_90.get(ticker, 0.0)),
            "rs_score_10": safe_float(rs_map_10.get(ticker, 0.0)),
            "momentum_rank": int(rank_map.get(ticker, 999)),
            "weighted_momentum": safe_float(weighted_momentum_series.get(ticker, 0.0)),
            "close_price": safe_float(current_close),
            "open_price": safe_float(row_info.get('open_price', 0.0)),
            "high_price": safe_float(row_info.get('high_price', 0.0)),
            "low_price": safe_float(row_info.get('low_price', 0.0)),
            "volume": int(row_info.get('volume', 0)) if pd.notna(row_info.get('volume', 0)) else 0,
            "atr": safe_float(atr_series.get(ticker, 0.0)),
            "ma10": safe_float(ma10_series.get(ticker, 0.0)),
            "ma20": safe_float(ma20_series.get(ticker, 0.0)),
            "ma50": safe_float(ma50_series.get(ticker, 0.0)),
            "ma200": safe_float(ma200_series.get(ticker, 0.0)),
            "price_date": analysis_date,
            "market": ticker_market_map.get(ticker, market)
        })
    
    if analysis_data:
        # 500건씩 분할 업서트 처리로 대용량 안전성 확보
        chunk_size = 500
        for i in range(0, len(analysis_data), chunk_size):
            chunk = analysis_data[i:i + chunk_size]
            supabase.table("daily_analysis").upsert(chunk, on_conflict="ticker,price_date").execute()
            
        print(f"[{analysis_date}] {market} 분석 완료 및 DB 적재 완료. (OHLCV, ATR, MA 및 90일/10일 RS 포함)")
    else:
        print("적재할 유효한 데이터가 없습니다.")

if __name__ == "__main__":
    target_date = None
    if len(sys.argv) > 2 and sys.argv[1] == "--target_date":
        target_date = sys.argv[2]
    
    run_analysis_pipeline('KR', target_date=target_date)
