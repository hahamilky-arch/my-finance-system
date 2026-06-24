# core/cleanup.py
from datetime import datetime, timedelta
from database.client import supabase

def cleanup_old_data(months=13):
    """
    지정된 개월 수보다 오래된 stock_prices 데이터를 삭제합니다.
    """
    delete_threshold = (datetime.now() - timedelta(days=months * 30)).strftime('%Y-%m-%d')
    print(f"[{delete_threshold} 이전 데이터 삭제 시작]")
    
    try:
        response = supabase.table("stock_prices") \
            .delete() \
            .lt("price_date", delete_threshold) \
            .execute()
        print(f"삭제 완료. 데이터 정리 성공.")
    except Exception as e:
        print(f"데이터 정리 중 오류 발생: {e}")
