import argparse
import sys
from datetime import datetime, timedelta
from core.analysis_pipeline import run_analysis_pipeline

def main():
    parser = argparse.ArgumentParser(description="Analysis Pipeline Only Execution")
    parser.add_argument("--market", choices=["KR", "US"], required=True, help="Specify market to analyze")
    parser.add_argument("--target_date", help="Specific date to re-run (YYYY-MM-DD)")
    parser.add_argument("--start_date", help="Start date for period execution (YYYY-MM-DD)")
    parser.add_argument("--end_date", help="End date for period execution (YYYY-MM-DD)")

    args = parser.parse_args()
    market = args.market
    
    # 날짜 범위 또는 단일 날짜 리스트 생성
    if args.start_date and args.end_date:
        start_dt = datetime.strptime(args.start_date, '%Y-%m-%d')
        end_dt = datetime.strptime(args.end_date, '%Y-%m-%d')
        date_list = [(start_dt + timedelta(days=x)).strftime('%Y-%m-%d') for x in range((end_dt - start_dt).days + 1)]
        print(f"=== Starting Period Analysis for {market} ({args.start_date} ~ {args.end_date}) ===")
    elif args.start_date:
        date_list = [args.start_date]
        print(f"=== Starting Analysis for {market} on {args.start_date} ===")
    elif args.target_date:
        date_list = [args.target_date]
        print(f"=== Starting Analysis for {market} on {args.target_date} ===")
    else:
        # 인자가 없으면 오늘 날짜 기준 실행
        date_list = [datetime.now().strftime('%Y-%m-%d')]
        print(f"=== Starting Daily Analysis for {market} ===")

    # 기간 루프를 돌며 분석 파이프라인만 실행
    for d_str in date_list:
        print(f"\n--- [Target Date: {d_str}] 분석 작업 시작 ---")
        try:
            run_analysis_pipeline(market, target_date=d_str)
        except Exception as e:
            print(f"Analysis failed for {d_str}: {e}")
            if len(date_list) == 1:
                sys.exit(1)
            continue

    print(f"\n=== Analysis Pipeline for {market} completed successfully ===")

if __name__ == "__main__":
    main()
