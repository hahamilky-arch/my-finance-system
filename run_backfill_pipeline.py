import argparse
import sys
from core.backfill_pipeline import backfill_pipeline

def main():
    parser = argparse.ArgumentParser(description="Manual Backfill Pipeline Execution")
    parser.add_argument("--start", required=True, help="Start date for backfill (YYYY-MM-DD)")
    parser.add_argument("--end", required=True, help="End date for backfill (YYYY-MM-DD)")
    parser.add_argument("--market", default="KR", choices=["KR", "US"], help="Target market (KR or US)")

    args = parser.parse_args()
    
    start_date = args.start
    end_date = args.end
    market = args.market
    
    print(f"=== [수동 액션] 백필 파이프라인 시작 ({market} 시장, 기간: {start_date} ~ {end_date}) ===")
    
    try:
        backfill_pipeline(start_date, end_date, market=market)
        print(f"=== [수동 액션] 백필 파이프라인 성공적으로 완료됨 ===")
    except Exception as e:
        print(f"❌ 백필 실행 중 오류 발생: {e}")
        sys.exit(1)

if __name__ == "__main__":
    main()
