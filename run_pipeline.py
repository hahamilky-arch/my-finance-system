import argparse
import sys
from datetime import datetime, timedelta
from core.scraper.index_sync import sync_index
from core.scraper.kr_stock_sync import sync_kr_stocks
from core.scraper.us_stock_sync import sync_us_stocks
from core.analysis_pipeline import run_analysis_pipeline
from core.cleanup import cleanup_old_data

def main():
    parser = argparse.ArgumentParser(description="Market Data Pipeline Execution")
    parser.add_argument("--market", choices=["KR", "US"], required=True, help="Specify market to sync and analyze")
    parser.add_argument("--target_date", help="Specific date to re-run (YYYY-MM-DD)")
    parser.add_argument("--start_date", help="Start date for period execution (YYYY-MM-DD)")
    parser.add_argument("--end_date", help="End date for period execution (YYYY-MM-DD)")

    args = parser.parse_args()
    market = args.market
    
    # 💡 기간(start_date ~ end_date) 혹은 단일 날짜(target_date) 혹은 당일 실행 결정
    if args.start_date and args.end_date:
        start_dt = datetime.strptime(args.start_date, '%Y-%m-%d')
        end_dt = datetime.strptime(args.end_date, '%Y-%m-%d')
        date_list = [(start_dt + timedelta(days=x)).strftime('%Y-%m-%d') for x in range((end_dt - start_dt).days + 1)]
        print(f"=== Starting Period Pipeline for {market} ({args.start_date} ~ {args.end_date}) ===")
    elif args.start_date: # start_date만 들어온 경우 단일 날짜로 취급
        date_list = [args.start_date]
        print(f"=== Starting Pipeline for {market} on {args.start_date} ===")
    elif args.target_date:
        date_list = [args.target_date]
        print(f"=== Starting Pipeline for {market} on {args.target_date} ===")
    else:
        # 인자가 없는 경우 오늘 하루 실행 (또는 스크립트 내부 기본 로직 위임)
        date_list = [None]
        print(f"=== Starting Daily Pipeline for {market} ===")

    # 기간 루프 실행
    for d_str in date_list:
        if d_str:
            print(processing_msg := f"\n--- [Target Date: {d_str}] 작업 시작 ---")
        
        # 1. 지수 데이터 수집
        try:
            sync_index(market, start_date=d_str, end_date=d_str)
        except Exception as e:
            print(f"Index sync failed for {d_str}: {e}")
            if len(date_list) == 1:
                sys.exit(1)
            continue

        # 2. 개별 종목 데이터 수집
        try:
            if market == "KR":
                sync_kr_stocks(start_date=d_str, end_date=d_str)
            else: # US
                sync_us_stocks(start_date=d_str, end_date=d_str)
        except Exception as e:
            print(f"Stock sync failed for {d_str}: {e}")
            if len(date_list) == 1:
                sys.exit(1)
            continue

        # 3. RS 계산 및 분석 수행
        try:
            run_analysis_pipeline(market, target_date=d_str)
        except Exception as e:
            print(f"Analysis failed for {d_str}: {e}")
            if len(date_list) == 1:
                sys.exit(1)
            continue

    # 4. 데이터 정리 (전체 기간 작업 완료 후 1회 수행)
    try:
        cleanup_old_data(months=13)  
    except Exception as e:
        print(f"Cleanup failed: {e}")
    
    print(f"\n=== Pipeline for {market} completed successfully ===")

if __name__ == "__main__":
    main()
