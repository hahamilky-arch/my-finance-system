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
    args = parser.parse_args()
    
    market = args.market
    print(f"=== Starting Pipeline for {market} ===")

    # 1. 지수 데이터 수집 (분석 기준점 확보)
    try:
        sync_index(market)
    except Exception as e:
        print(f"Index sync failed: {e}")
        sys.exit(1)

    # 2. 개별 종목 데이터 수집
    if market == "KR":
        sync_kr_stocks()
    else:
        sync_us_stocks()

    # 3. RS 계산 및 분석 수행
    run_analysis_pipeline(market)

    # 4. 데이터 정리 (항상 마지막에 실행)
    cleanup_old_data(months=13)  
    
    print(f"=== Pipeline for {market} completed successfully ===")

if __name__ == "__main__":
    main()
