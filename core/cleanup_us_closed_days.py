import pandas as pd
import FinanceDataReader as fdr
import os
from supabase import create_client
from dotenv import load_dotenv

# 환경 변수 로드 및 Supabase 클라이언트 초기화
load_dotenv()
supabase = create_client(os.getenv("SUPABASE_URL"), os.getenv("SUPABASE_KEY"))

def cleanup_us_closed_days(start_date='2025-01-01', end_date='2026-12-31'):
    print("=== 🇺🇸 US 시장 및 미국 지수(^GSPC, ^IXIC, ^DJI) 휴장일 데이터 클린업 시작 ===")
    
    # 1. 삭제 대상 티커 목록 조회 (US 전체 + 주요 미국 지수)
    print("1. US 종목 및 미국 지수 티커 목록 조합 중 (한국 시장 데이터 완벽 보호)...")
    us_stocks_resp = supabase.table("stocks").select("ticker").eq("market", "US").execute()
    
    # US 시장 종목 리스트 추출 후 미국 대표 지수 추가
    target_tickers = [t['ticker'] for t in us_stocks_resp.data] if us_stocks_resp.data else []
    
    us_indices = ["^GSPC", "^IXIC", "^DJI"]
    for idx in us_indices:
        if idx not in target_tickers:
            target_tickers.append(idx)
        
    if not target_tickers:
        print("대상이 되는 US 주식이나 미국 지수 티커가 없습니다.")
        return

    print(f" -> 총 {len(target_tickers)}개 티커 검사 대상 지정 완료.")

    # 2. 껍데기 데이터(NULL) 1차 삭제 (US 티커 한정)
    print("2. 지표가 계산되지 않은 NULL 데이터 1차 삭제 중 (US 및 미국 지수 한정)...")
    chunk_size = 100
    for i in range(0, len(target_tickers), chunk_size):
        ticker_chunk = target_tickers[i:i+chunk_size]
        try:
            supabase.table("daily_analysis").delete().is_("ma200", "null").in_("ticker", ticker_chunk).execute()
        except Exception as e:
            print(f" -> NULL 데이터 삭제 중 예외 발생 (무시 가능): {e}")

    # 3. FinanceDataReader를 이용해 S&P 500(US500) 실제 개장일 달력 생성
    print(f"3. {start_date} ~ {end_date} 기간의 실제 미국 증시(S&P 500) 개장일 조회 중...")
    try:
        us_cal = fdr.DataReader('US500', start_date, end_date)
    except Exception:
        # US500 조회가 안 될 경우 S&P500 심볼 대체
        us_cal = fdr.DataReader('S&P500', start_date, end_date)
        
    valid_trading_days = set(us_cal.index.strftime('%Y-%m-%d').tolist())

    # 4. DB에 적재된 해당 미국 종목들의 날짜 목록 조회
    # 대표격인 ^GSPC(S&P 500) 또는 AAPL/NVDA 기준 날짜 조회
    print("4. DB에 적재된 US 날짜 검사 중...")
    response = supabase.table("daily_analysis").select("price_date").eq("ticker", "^GSPC").execute()
    
    db_dates = set([row['price_date'] for row in response.data]) if response.data else set()
    
    # ^GSPC 데이터가 없으면 NVDA, AAPL 등 대형주 기준으로 검사
    if not db_dates:
        for fallback_ticker in ["NVDA", "AAPL", "MSFT"]:
            if fallback_ticker in target_tickers:
                response = supabase.table("daily_analysis").select("price_date").eq("ticker", fallback_ticker).execute()
                if response.data:
                    db_dates = set([row['price_date'] for row in response.data])
                    break

    # 5. 휴장일(미국 개장 달력에 없는 날짜) 필터링
    invalid_dates = db_dates - valid_trading_days
    
    if not invalid_dates:
        print("삭제할 US 휴장일 데이터가 없습니다. 모두 정상 개장일입니다! ✅")
        return
        
    invalid_dates_list = sorted(list(invalid_dates))
    print(f"🚨 총 {len(invalid_dates_list)}개의 US 휴장일(주말/미국 공휴일) 데이터 발견!")
    print(f"삭제 대상 날짜: {invalid_dates_list}")

    # 6. DB에서 US 휴장일 데이터 삭제
    print("5. DB에서 US 휴장일 데이터 일괄 삭제 시작...")
    
    for date_str in invalid_dates_list:
        print(f" -> {date_str} (US 휴장일) 데이터 삭제 중...")
        
        for i in range(0, len(target_tickers), chunk_size):
            ticker_chunk = target_tickers[i:i+chunk_size]
            
            # [A] daily_analysis 테이블에서 삭제
            supabase.table("daily_analysis").delete().eq("price_date", date_str).in_("ticker", ticker_chunk).execute()
            
            # [B] stock_prices 테이블에서 삭제
            supabase.table("stock_prices").delete().eq("price_date", date_str).in_("ticker", ticker_chunk).execute()
            
    print("=== 🧹 🇺🇸 US 시장 및 미국 지수 휴장일 쓰레기 데이터 정리 완료! ===")

if __name__ == "__main__":
    cleanup_us_closed_days(start_date='2025-01-01', end_date='2026-12-31')
