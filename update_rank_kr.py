import pandas as pd
from supabase import create_client
import os
from datetime import datetime
from dotenv import load_dotenv

load_dotenv()
# Supabase 연결
supabase = create_client(os.environ.get("SUPABASE_URL"), os.environ.get("SUPABASE_KEY"))

def update_momentum_rank():
    today = datetime.now().strftime('%Y-%m-%d')
    
    today = '2026-06-11'

    print(f"기준 일자 : {today}")
    
    # 1. 오늘 날짜의 데이터를 조회 (weighted_momentum 순으로 정렬 준비)
    response = supabase.table("daily_analysis")\
        .select("ticker, weighted_momentum")\
        .eq("price_date", today)\
        .execute()
    
    df = pd.DataFrame(response.data)
    
    if df.empty:
        print(f"{today} 데이터가 없습니다.")
        return

    # 2. weighted_momentum 기준으로 내림차순 랭킹 부여 (1등부터 순차적)
    df['momentum_rank'] = df['weighted_momentum'].rank(ascending=False, method='min')
    
    # 3. 랭킹을 DB에 업데이트
    for _, row in df.iterrows():
        supabase.table("daily_analysis").update(
            {"momentum_rank": int(row['momentum_rank'])}
        ).eq("ticker", row['ticker']).eq("price_date", today).execute()
        
    print(f"랭킹 업데이트 완료: {today}")

if __name__ == "__main__":
    update_momentum_rank()