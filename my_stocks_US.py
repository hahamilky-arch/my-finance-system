import os
import pandas as pd
from supabase import create_client
from dotenv import load_dotenv

load_dotenv()
supabase = create_client(os.getenv("SUPABASE_URL"), os.getenv("SUPABASE_KEY"))

# CSV 파일 읽기
df = pd.read_csv('watchlist_US.csv')

for _, row in df.iterrows():
    data = {
        "ticker": str(row['ticker']),
        "name": str(row['name']),
        "market": "US"
    }
    
    # 데이터베이스 등록
    supabase.table("stocks").upsert(data).execute()

print("파일에서 관심 종목 등록 완료!")