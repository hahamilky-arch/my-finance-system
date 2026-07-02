import time
import yfinance as yf
from database.client import supabase

def check_incorrect_names():
    """
    market 값(KR, US, INDEX)에 따라 yfinance에서 올바른 종목명을 가져와
    DB의 name과 비교하고 불일치하는 건만 출력합니다.
    """
    try:
        print("stocks 테이블에서 종목 정보를 조회합니다...")
        response = supabase.table("stocks").select("ticker, market, name").execute()
        db_stocks = response.data

        if not db_stocks:
            print("조회된 종목 데이터가 없습니다.")
            return

        print(f"총 {len(db_stocks)}개의 종목 검증을 시작합니다.\n")

        mismatch_count = 0
        match_count = 0
        not_found_count = 0

        for stock in db_stocks:
            ticker = stock.get('ticker')
            market = stock.get('market')
            current_db_name = stock.get('name', '')
            
            if current_db_name is None:
                current_db_name = ""

            actual_name = None

            try:
                # 1. Market 분류에 따른 yfinance 데이터 조회
                if market == "KR":
                    # 한국 주식: KOSPI(.KS) 먼저 확인
                    yf_stock = yf.Ticker(f"{ticker}.KS")
                    actual_name = yf_stock.info.get("longName") or yf_stock.info.get("shortName")
                    
                    # KOSPI에서 이름을 찾지 못한 경우 KOSDAQ(.KQ) 확인
                    if not actual_name:
                        yf_stock = yf.Ticker(f"{ticker}.KQ")
                        actual_name = yf_stock.info.get("longName") or yf_stock.info.get("shortName")

                elif market in ["US", "INDEX"]:
                    # 미국 주식 및 지수: 티커 그대로 사용 (지수는 ^GSPC, ^IXIC 등 기호가 포함되어 있다고 가정)
                    yf_stock = yf.Ticker(ticker)
                    actual_name = yf_stock.info.get("longName") or yf_stock.info.get("shortName")
                
                else:
                    print(f"[알림] 정의되지 않은 Market 값입니다: {ticker} ({market})")
                    continue

                # 2. yfinance 조회 결과 확인
                if not actual_name:
                    print(f"[알림] {ticker} ({market}): yfinance에서 이름을 찾을 수 없습니다.")
                    not_found_count += 1
                    continue

                actual_name = actual_name.strip()
                current_db_name = current_db_name.strip()

                # 3. 데이터 비교 및 불일치 건 출력
                if current_db_name == actual_name:
                    match_count += 1
                else:
                    print(f"⚠️ [불일치 발견] {ticker} ({market})")
                    print(f"   - DB 저장 이름: '{current_db_name}'")
                    print(f"   - 실제 이름(yf): '{actual_name}'\n")
                    mismatch_count += 1

                # yfinance API 호출 제한 방지
                time.sleep(0.5)

            except Exception as e:
                print(f"❌ [오류] {ticker} ({market}) 정보 조회 실패: {e}")

        print("=== 검증 완료 ===")
        print(f"일치: {match_count}건")
        print(f"불일치: {mismatch_count}건")
        print(f"조회 실패: {not_found_count}건")

    except Exception as e:
        print(f"데이터베이스 처리 중 오류가 발생했습니다: {e}")

if __name__ == "__main__":
    check_incorrect_names()
