import FinanceDataReader as fdr
# database 디렉토리 내부의 client.py에서 supabase 객체를 가져옵니다.
from database.client import supabase

def get_krx_name_dict():
    """
    FinanceDataReader를 이용해 KRX(코스피/코스닥/코넥스) 전체 종목의 
    티커와 한글 종목명 매핑 딕셔너리를 생성합니다.
    """
    try:
        print("KRX 상장 종목 한글 마스터 데이터를 가져오는 중...")
        df_krx = fdr.StockListing('KRX')
        return dict(zip(df_krx['Code'], df_krx['Name']))
    except Exception as e:
        print(f"❌ KRX 종목 마스터 로드 실패: {e}")
        return {}

def update_incorrect_kr_names():
    """
    market이 KR인 종목만 대상으로 FinanceDataReader의 한글 이름과 
    DB의 name 컬럼을 비교하여, 다를 경우 올바른 이름으로 업데이트합니다.
    """
    try:
        # 1. KRX 한글 종목명 딕셔너리 확보
        krx_names = get_krx_name_dict()
        if not krx_names:
            return

        # 2. stocks 테이블에서 market이 KR인 데이터만 필터링하여 조회
        print("stocks 테이블에서 한국 주식(KR) 정보를 조회합니다...")
        response = supabase.table("stocks") \
            .select("ticker, market, name") \
            .eq("market", "KR") \
            .execute()
        
        db_stocks = response.data

        if not db_stocks:
            print("조회된 한국 주식(KR) 데이터가 없습니다.")
            return

        print(f"총 {len(db_stocks)}개의 한국 주식 종목 검증 및 업데이트를 시작합니다.\n")

        updated_count = 0
        skip_count = 0
        not_found_count = 0

        # 3. 각 종목별 데이터 비교 및 업데이트
        for stock in db_stocks:
            ticker = stock.get('ticker')
            market = stock.get('market')
            current_db_name = stock.get('name', '')
            
            if current_db_name is None:
                current_db_name = ""

            # FinanceDataReader 마스터 데이터에서 한글명 조회
            actual_name = krx_names.get(ticker)
            
            if not actual_name:
                print(f"[알림] {ticker} ({market}): KRX 마스터 데이터에 존재하지 않아 업데이트를 건너뜁니다.")
                not_found_count += 1
                continue

            # 양끝 공백 제거
            actual_name = actual_name.strip()
            current_db_name = current_db_name.strip()

            if current_db_name == actual_name:
                skip_count += 1
            else:
                # 4. 데이터베이스 이름 수정 실행
                supabase.table("stocks") \
                    .update({"name": actual_name}) \
                    .eq("ticker", ticker) \
                    .eq("market", market) \
                    .execute()
                
                print(f"🔧 [이름수정] {ticker}: '{current_db_name}' -> '{actual_name}'")
                updated_count += 1

        print("\n=== 업데이트 완료 ===")
        print(f"일치 (기존 유지): {skip_count}건")
        print(f"수정 (DB 업데이트): {updated_count}건")
        print(f"건너뜀 (KRX 미존재): {not_found_count}건")

    except Exception as e:
        print(f"데이터베이스 처리 중 오류가 발생했습니다: {e}")

if __name__ == "__main__":
    update_incorrect_kr_names()
