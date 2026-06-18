import os
from datetime import datetime, timedelta
from supabase import create_client
from dotenv import load_dotenv

load_dotenv()
supabase = create_client(os.getenv("SUPABASE_URL"), os.getenv("SUPABASE_KEY"))

# 1. 삭제 기준 날짜 계산 (오늘 기준 13개월 전)
delete_threshold = (datetime.now() - timedelta(days=13*30)).strftime('%Y-%m-%d')
print(f"기준 날짜: {delete_threshold} 이전 데이터 삭제 시작...")

# 2. 삭제 실행
try:
    # price_date가 delete_threshold보다 작은(과거인) 행 삭제
    response = supabase.table("stock_prices") \
        .delete() \
        .lt("price_date", delete_threshold) \
        .execute()
                                    
    print(f"삭제 완료! 삭제된 데이터 건수: {len(response.data) if response.data else '확인 필요'}")
except Exception as e:
    print(f"삭제 중 오류 발생: {e}")
