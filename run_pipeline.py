import argparse
import sys
from core.scraper.index_sync import sync_index
from core.scraper.kr_stock_sync import sync_kr_stocks
from core.scraper.us_stock_sync import sync_us_stocks
from core.analysis_pipeline import run_analysis_pipeline
from core.cleanup import cleanup_old_data

def main():
    parser = argparse.ArgumentParser(description="Market Data Pipeline Execution")
    parser.add_argument("--market", choices=["KR", "US"], required=True, help="Specify market to sync and analyze")
    parser.add_argument("--target_date", help="Specific date to re-run (YYYY-MM-DD)")

    args = parser.parse_args()
    market = args.market
    
    print(f"=== Starting Pipeline for {market} ===")

    # 1. 지수 데이터 수집
    try:
        #sync_index(market)
        sync_index(market, start_date=args.target_date, end_date=args.target_date)
    except Exception as e:
        print(f"Index sync failed: {e}")
        sys.exit(1)

    # 2. 개별 종목 데이터 수집 (변수명 args.target_date로 통일)
    if market == "KR":
        if args.target_date:
            print(f"--- KR 특정 날짜 재실행 모드: {args.target_date} ---")
            sync_kr_stocks(start_date=args.target_date, end_date=args.target_date)
        else:
            sync_kr_stocks()
    else: # US
        if args.target_date:
            print(f"--- US 특정 날짜 재실행 모드: {args.target_date} ---")
            sync_us_stocks(start_date=args.target_date, end_date=args.target_date)
        else:
            sync_us_stocks()

    # 3. RS 계산 및 분석 수행
    run_analysis_pipeline(market)

    # 4. 데이터 정리
    cleanup_old_data(months=13)  
    
    print(f"=== Pipeline for {market} completed successfully ===")

if __name__ == "__main__":
    main()
