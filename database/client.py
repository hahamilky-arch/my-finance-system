from supabase import create_client
import os

supabase = create_client(os.getenv("SUPABASE_URL"), os.getenv("SUPABASE_KEY"))

# 데이터를 DB에서 가져오고 결과를 daily_analysis에 upsert하는 함수입니다.

def upsert_analysis(data_list):
    """
    data_list: [{'ticker': '...', 'rs_score': ..., 'price_date': '...'}, ...]
    """
    return supabase.table("daily_analysis").upsert(data_list).execute()
