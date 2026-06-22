
import os
import pandas as pd
from supabase import create_client
from datetime import datetime
from dotenv import load_dotenv

load_dotenv()
url = os.getenv("SUPABASE_URL")
key = os.getenv("SUPABASE_KEY")
supabase = create_client(url, key)

def calculate_weighted_momentum(df):
    periods = {12: 252, 6: 126, 4: 84, 2: 42, 1: 21}
    weights = {12: 1, 6: 2, 4: 4, 2: 6, 1: 12}
    total_weight = sum(weights.values())

    results = []

    # 단일 종목 데이터프레임이 들어올 것이므로 groupby 대신 바로 처리
    group = df.sort_values('price_date')
    print(f"group length {len(group)}")
    if len(group) < 21: return None

    current_price = group['close_price'].iloc[-1]
    score_sum = 0

    for m, p in periods.items():
        if len(group) >= p:
            past_price = group['close_price'].iloc[-p]
            ret = (current_price / past_price) - 1
            score_sum += (ret * weights[m])

    results.append({
        'ticker': group['ticker'].iloc[0],
        'weighted_momentum': score_sum / total_weight
    })
    return pd.DataFrame(results)

def update_momentum(market):
    print(f"[{market}] 업데이트 시작...")

    # 1. 대상 티커 조회
    stocks_res = supabase.table("stocks").select("ticker").eq("market", market).execute()
    tickers = [str(item['ticker']).zfill(6) for item in stocks_res.data]
    print(f"대상 티커 개수: {len(tickers)}")

    if not tickers: return
    today = datetime.now().strftime('%Y-%m-%d')
    ##today = '2026-06-15'
    print(f"기준 일자 : {today}")
    all_momentum_results = []

    # 2. 티커별로 루프를 돌며 개별 조회 및 계산
    for ticker in tickers:
        res = supabase.table("stock_prices").select("*").eq("ticker", ticker).lte("price_date", today).order("price_date", desc=False).execute()
        ticker_df = pd.DataFrame(res.data)
        print(f"ticker_df len >> [{len(ticker_df)}]")
        if ticker_df.empty: continue

        ticker_df['price_date'] = pd.to_datetime(ticker_df['price_date'])
        ticker_df['close_price'] = ticker_df['close_price'].astype(float)

        # 모멘텀 계산
        momentum_df = calculate_weighted_momentum(ticker_df)

        if momentum_df is not None:
        # Upsert 실행 (개별 혹은 리스트로 처리)
            
            print(f"[{momentum_df}]")
            data = {
                "ticker": momentum_df.iloc[0]['ticker'],
                "price_date": today,
                "weighted_momentum": float(momentum_df.iloc[0]['weighted_momentum']),
                "market": market
            }

            supabase.table("daily_analysis").upsert(data, on_conflict="ticker,price_date").execute()
        print(f"{ticker} 완료")

    print(f"[{market}] 업데이트 완료")



# 실행 시 market 값을 전달
update_momentum("KR")
# update_momentum("US") # US 실행 시 주석 해제

