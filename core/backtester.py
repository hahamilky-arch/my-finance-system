import pandas as pd
from database.client import supabase

def run_backtest(days_to_hold=5):
    # 1. 과거 분석 데이터 가져오기 (전체 기간)
    analysis_data = pd.DataFrame(supabase.table("daily_analysis").select("*").execute().data)
    
    # 2. 필터 적용 (RS > 0.03 & 순위 20위 이내)
    filtered_signals = analysis_data[(analysis_data['rs_score'] > 0.03) & (analysis_data['momentum_rank'] <= 20)]
    
    # 3. 매수 시점별 수익률 계산 루프
    results = []
    for _, signal in filtered_signals.iterrows():
        ticker = signal['ticker']
        buy_date = signal['price_date']
        
        # 매수일 이후 데이터 조회
        price_data = pd.DataFrame(supabase.table("stock_prices")
                                  .select("price_date, close_price")
                                  .eq("ticker", ticker)
                                  .gt("price_date", buy_date)
                                  .order("price_date", asc=True)
                                  .limit(days_to_hold)
                                  .execute().data)
        
        if len(price_data) >= days_to_hold:
            buy_price = signal['close_price'] # 이 부분을 위해 테이블에 close_price 추가 필요
            sell_price = price_data.iloc[-1]['close_price']
            profit = (sell_price - buy_price) / buy_price
            results.append(profit)
            
    return pd.Series(results).mean() * 100 # 평균 수익률(%)
