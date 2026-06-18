import os
import pandas as pd
import yfinance as yf
from datetime import datetime
from dateutil.relativedelta import relativedelta
from supabase import create_client
from dotenv import load_dotenv

# 설정 로드
load_dotenv()
supabase = create_client(os.getenv("SUPABASE_URL"), os.getenv("SUPABASE_KEY"))

def run_analysis():
    today = datetime.now().strftime('%Y-%m-%d')
    stocks = supabase.table("stocks").select("*").execute().data
    benchmarks = {"KR": "^KS11", "US": "SPY"}

    for stock in stocks:
        ticker, market = stock['ticker'], stock['market']
            
        # 1. 데이터 수집
        yf_ticker = f"{ticker}.KS" if market == "KR" else ticker
        df = yf.Ticker(yf_ticker).history(period="15mo")
        df_idx = yf.Ticker(benchmarks[ market]).history(period="15mo")
                                                    
        if df.empty or df_idx.empty: continue
                                                                    
        # 2. 가중 모멘텀 및 RS 계산
        periods = {'1m': 1, '2m': 2, '4m': 4, '6m': 6, '12m': 12}
        weights = {'1m': 12, '2m': 6, '4m': 4, '6m': 2, '12m': 1}
                                                                                                    
        weighted_mom, rs_sum = 0, 0

        for label, m in periods.items():
            past_date = datetime.now() - relativedelta(months=m)
            past_price = df[df.index <= past_date]['Close'].iloc[-1]
            past_data = df[df.index <= past_date]
            idx_past_data = df_idx[df_idx.index <= past_date]
            # 데이터가 있는지 확인하는 조건문 추가
            if past_data.empty or idx_past_data.empty:
                print(f"[{ticker}] {m}개월 전 데이터가 없습니다. 건너뜁니다.")
                continue # 해당 기간 계산을 건너뜀

            past_price = past_data['Close'].iloc[-1]
            idx_past = idx_past_data['Close'].iloc[-1]

            mom = (df['Close'].iloc[-1] / past_price) - 1
            idx_mom = (df_idx['Close'].iloc[-1] / idx_past) - 1
                                                            
            weighted_mom += (mom * weights[label])
            rs_sum += (mom - idx_mom)
        

            # 3. DB 적재
            data = {
                "ticker": ticker, 
                "price_date": today, 
                "market": market,
                "weighted_momentum": float(weighted_mom),
                "rs_score": float(rs_sum / len(periods))
            }
            supabase.table("daily_analysis").upsert(data).execute()
    
    # 4. 순위 산출 (시장별)
    update_rankings(today)

def update_rankings(date):
    data = supabase.table("daily_analysis").select("*").eq("price_date", date).execute().data
    df = pd.DataFrame(data)
    df['momentum_rank'] = df.groupby('market')['weighted_momentum'].rank(ascending=False).astype(int)
                    
    for _, row in df.iterrows():
        supabase.table("daily_analysis").update({"momentum_rank": int(row['momentum_rank'])}) \
            .eq("ticker", row['ticker']).eq("price_date", date).execute()

if __name__ == "__main__":
    run_analysis()
                                                                                            
                                                        




