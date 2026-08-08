import pandas as pd
import FinanceDataReader as fdr
import os
from supabase import create_client
from dotenv import load_dotenv

# 환경 변수 로드 및 Supabase 클라이언트 초기화
load_dotenv()
supabase = create_client(os.getenv("SUPABASE_URL"), os.getenv("SUPABASE_KEY"))

def cleanup_kr_and_ks11_closed_days(start_date='2025-01-01', end_date='2026-12-31'):
    print("=== 🇰🇷 KR 시장 및 ^KS11(코스피) 휴장일 데이터 클린업 시작 ===")
    
    # 1. 삭제 대상 티커 목록 명확히 조회 (KR 전체 + ^KS11만 추가)
    print("1. KR 종목 및 ^KS11 티커 목록 조합 중 (미국 지수/주식 완벽 보호)...")
    kr_stocks_resp = supabase.table("stocks").select("ticker").eq("market", "KR").execute()
    
    # KR 시장 종목 리스트 추출 후 ^KS11만 수동으로 추가
    target_tickers = [t['ticker'] for t in kr_stocks_resp.data]
    if "^KS11" not in target_tickers:
        target_tickers.append("^KS11")
        
    if not target_tickers:
        print("대상이 되는 KR 주식이나 ^KS11 티커가 없습니다.")
        return

    # 2. 껍데기 데이터(NULL) 1차 쾌속 삭제 (타겟 티커 단위로 진행)
    print("2. 지표가 계산되지 않은 NULL 데이터 1차 삭제 중 (KR 및 ^KS11 한정)...")
    chunk_size = 100
    for i in range(0, len(target_tickers), chunk_size):
        ticker_chunk = target_tickers[i:i+chunk_size]
        try:
            supabase.table("daily_analysis").delete().is_("ma200", "null").in_("ticker", ticker_chunk).execute()
        except Exception as e:
            print(f" -> NULL 데이터 삭제 중 예외 발생 (무시 가능): {e}")

    # 3. FinanceDataReader를 이용해 KOSPI 실제 개장일 달력 생성
    print(f"3. {start_date} ~ {end_date} 기간의 실제 코스피 개장일 조회 중...")
    ks11 = fdr.DataReader('KS11', start_date, end_date)
    valid_trading_days = set(ks11.index.strftime('%Y-%m-%d').tolist())

    # 4. DB에 적재된 해당 종목들의 날짜 목록 조회
    # 효율성을 위해 대표격인 ^KS11의 날짜들만 조회하여 휴장일 유무를 판단합니다.
    print("4. DB에 적재된 날짜 검사 중...")
    response = supabase.table("daily_analysis").select("price_date").eq("ticker", "^KS11").execute()
    
    db_dates = set([row['price_date'] for row in response.data]) if response.data else set()
    
    # 만약 ^KS11 날짜가 조회되지 않았다면, 삼성전자(005930)를 기준으로 조회
    if not db_dates and "005930" in target_tickers:
        response = supabase.table("daily_analysis").select("price_date").eq("ticker", "005930").execute()
        db_dates = set([row['price_date'] for row in response.data]) if response.data else set()

    # 5. 휴장일(개장달력에 없는 날짜) 필터링
    invalid_dates = db_dates - valid_trading_days
    
    if not invalid_dates:
        print("삭제할 휴장일 데이터가 없습니다. 모두 정상 개장일입니다! ✅")
        return
        
    invalid_dates_list = sorted(list(invalid_dates))
    print(f"🚨 총 {len(invalid_dates_list)}개의 KR 휴장일(주말/한국 공휴일) 데이터 발견!")
    print(f"삭제 대상 날짜: {invalid_dates_list}")

    # 6. DB에서 휴장일 데이터 안전하게 삭제
    print("5. DB에서 휴장일 데이터 일괄 삭제 시작...")
    
    # Supabase URL 길이 제한(Payload Too Large) 방지를 위해 티커를 청크(Chunk) 단위로 분할하여 삭제
    for date_str in invalid_dates_list:
        print(f" -> {date_str} (휴장일) 데이터 삭제 중...")
        
        for i in range(0, len(target_tickers), chunk_size):
            ticker_chunk = target_tickers[i:i+chunk_size]
            
            # [A] daily_analysis 테이블에서 삭제
            supabase.table("daily_analysis").delete().eq("price_date", date_str).in_("ticker", ticker_chunk).execute()
            
            # [B] stock_prices 테이블에서 삭제
            supabase.table("stock_prices").delete().eq("price_date", date_str).in_("ticker", ticker_chunk).execute()
            
    print("=== 🧹 🇰🇷 KR 시장 및 ^KS11 휴장일 쓰레기 데이터 정리 완료! ===")

if __name__ == "__main__":
    # 본인이 데이터를 적재한 대략적인 기간을 입력하세요.
    cleanup_kr_and_ks11_closed_days(start_date='2025-01-01', end_date='2026-12-31')
