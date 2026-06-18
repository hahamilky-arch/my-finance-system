import os
import yfinance as yf
from datetime import datetime, timedelta
from supabase import create_client
from dotenv import load_dotenv

load_dotenv()
supabase = create_client(os.getenv("SUPABASE_URL"), os.getenv("SUPABASE_KEY"))

def get_market_date(market):
    # 한국은 당일, 미국은 전일 데이터 기준
    if market == "KR":
        return datetime.now().strftime('%Y-%m-%d')
    else:
        return (datetime.now() - timedelta(days=1)).strftime('%Y-%m-%d')


stocks = supabase.table("stocks").select("*").execute().data

for stock in stocks:
    ticker = stock["ticker"]
    market = stock["market"]
    #yf_ticker = f"{ticker}.KS" if market == "KR" else ticker
    #6자리로 강제 변환 후 .KS를 붙임
    yf_ticker = f"{str(ticker).zfill(6)}.KS" if market == "KR" else ticker
    # 1. 마켓 구분 및 티커 포맷팅 (6자리 + .KS/.KQ/.US)
    market = "KR" if market == "KR" else "US"
    
    print(f"{yf_ticker} >> ")
    target_date = get_market_date(market)
    print(f"{target_date} >> 기준 일자")


    # 1. 마지막으로 적재된 날짜 확인 (DB에서 가장 최신 날짜 조회)
    latest_price = supabase.table("stock_prices") \
        .select("price_date") \
        .eq("ticker", ticker) \
        .order("price_date", desc=True) \
        .limit(1) \
        .execute().data

    print(f"lastest price -> {latest_price}")

    # 2. 당일 데이터 확인 로직 추가
    #today_str = datetime.now().strftime('%Y-%m-%d')
            
    if latest_price and latest_price[0]["price_date"] == target_date:
        print(f"[{name}] {target_date} 데이터 있음. 수집 건너뜀.")
        continue # 다음 종목으로 즉시 이동
                                    
    # 3. 데이터가 없거나 최신이 아닐 때만 아래 로직 실행
    # (기존의 수집 및 적재 코드 실행)

    # 4. 적재 시작일 설정
    if latest_price:
        # 마지막 데이터의 다음 날부터 수집
        start_date = (datetime.strptime(latest_price[0]["price_date"], '%Y-%m-%d') + timedelta(days=1)).strftime('%Y-%m-%d')
    else:
        # 데이터가 없으면 1년 전부터 시작
        start_date = (datetime.now() - timedelta(days=365)).strftime('%Y-%m-%d')

    print(f"start_date -> {start_date}") 

    # 5. 데이터 수집 (start_date부터 현재까지)
    df = yf.Ticker(yf_ticker).history(start=start_date)
                                                                                                                                
    # 6. DB 적재 (upsert)
    for date, row in df.iterrows():
        data = {
            "ticker": ticker,
            "price_date": date.strftime('%Y-%m-%d'),
            "close_price": float(row['Close']),                                                                         
            "volume": int(row['Volume'])                    
        }
        try:                                                                                                                                                                      
            #supabase.table("stock_prices").upsert(data).execute()
            response = supabase.table("stock_prices").upsert(
                    data, 
                    on_conflict="ticker,price_date" 
                ).execute()

        except Exception as e:
            print(f" 2: {e}")
    print(f"-> [{ticker}] {len(df)}건 적재 완료.")
print("주가 데이터 동기화 완료!")                                                                                               