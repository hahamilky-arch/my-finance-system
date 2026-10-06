import os
import sys
import numpy as np
import pandas as pd
from db import supabase
from strategy import get_data


def run_backtest(start_date="2026-01-01", end_date="2026-09-30", market_type="KR"):
    print("=" * 65)
    print(f"🚀 Quant Alpha [Top 7 Regime] 백테스트 실행")
    print(f"• 테스트 기간: {start_date} ~ {end_date}")
    print(f"• 대상 시장: {market_type}")
    print(f"• 핵심 수식: +8% 달성 시 트레일링 스탑 (max(최고가*0.92, 평단가))")
    print("=" * 65)

    # 1. Supabase에서 해당 기간 내 전체 영업일 조회
    try:
        res_dates = (
            supabase.table("daily_analysis")
            .select("price_date")
            .eq("market", market_type)
            .gte("price_date", start_date)
            .lte("price_date", end_date)
            .order("price_date", ascending=True)
            .execute()
        )
    except Exception as e:
        print(f"❌ DB 접속 및 날짜 조회 실패: {e}")
        return

    if not res_dates.data:
        print(f"❌ {start_date} ~ {end_date} 기간 내 백테스트 데이터가 존재하지 않습니다.")
        return

    all_dates = sorted(list(set(row["price_date"] for row in res_dates.data)))
    print(f"📅 총 {len(all_dates)}영업일 데이터 수집 완료\n")

    # 2. 백테스트 계좌 상태 초기화
    initial_capital = 20000000.0  # 초기 자본금 (2,000만원)
    current_cash = initial_capital
    portfolio = {}  # {ticker: {'buy_price': float, 'qty': float, 'buy_date': str, 'highest_price': float, 'name': str}}
    closed_trades = []  # 청산 내역 저장
    daily_equity_history = []  # 일별 계좌 총 자산 기록

    top_n_cfg = 7
    sl_cfg = -2.5

    # 3. 일별 백테스트 시뮬레이션 루프 실행
    for target_date in all_dates:
        # 매일 매일 Top7 전략 엔진 실행
        df_daily = get_data(
            target_date=target_date,
            all_dates=all_dates,
            market_type=market_type,
            top_n_cfg=top_n_cfg,
            sl_cfg=sl_cfg,
            rebalance_cycle="상시 (빈자리 즉시 채우기)",
            is_bull_mode=True,
            stop_new_buy=False,
            reduce_holdings=False,
            strategy_engine_mode="strat3_top7",
        )

        if df_daily is None or df_daily.empty:
            continue

        # 3-1. 현재 보유 종목의 평가금액 및 최고가 갱신
        holdings_eval_total = 0.0
        daily_prices = dict(zip(df_daily["ticker"], df_daily["종가"]))
        daily_names = dict(zip(df_daily["ticker"], df_daily["종목명"]))

        for t_code, p_info in list(portfolio.items()):
            curr_price = daily_prices.get(t_code, p_info["buy_price"])
            p_info["highest_price"] = max(p_info["highest_price"], curr_price)
            holdings_eval_total += curr_price * p_info["qty"]

        # 3-2. 매도 필요 종목 청산 처리 (기존 보유 종목 중 매도필요 판정 종목)
        sells = df_daily[df_daily["매매상태"] == "매도필요"]
        for _, sell_row in sells.iterrows():
            sticker = sell_row["ticker"]
            if sticker in portfolio:
                p_item = portfolio.pop(sticker)
                sell_price = float(sell_row["종가"])
                profit_amt = (sell_price - p_item["buy_price"]) * p_item["qty"]
                profit_rate = (
                    ((sell_price / p_item["buy_price"]) - 1.0) * 100
                    if p_item["buy_price"] > 0
                    else 0.0
                )

                current_cash += sell_price * p_item["qty"]

                closed_trades.append({
                    "ticker": sticker,
                    "name": p_item["name"],
                    "buy_date": p_item["buy_date"],
                    "sell_date": target_date,
                    "buy_price": p_item["buy_price"],
                    "sell_price": sell_price,
                    "highest_price": p_item["highest_price"],
                    "qty": p_item["qty"],
                    "profit_amt": profit_amt,
                    "profit_rate": profit_rate,
                })

        # 3-3. 신규 매수 추천 종목 진입 처리
        buys = df_daily[df_daily["매매상태"] == "매수추천"]
        empty_slots = top_n_cfg - len(portfolio)

        if empty_slots > 0 and not buys.empty:
            target_buys = buys.head(empty_slots)
            total_account_val = current_cash + holdings_eval_total
            slot_budget = total_account_val / top_n_cfg  # 슬롯 당 등가 분산

            for _, buy_row in target_buys.iterrows():
                bticker = buy_row["ticker"]
                buy_price = float(buy_row["종가"])

                if buy_price > 0 and current_cash >= slot_budget:
                    buy_qty = slot_budget / buy_price
                    current_cash -= slot_budget

                    portfolio[bticker] = {
                        "buy_price": buy_price,
                        "qty": buy_qty,
                        "buy_date": target_date,
                        "highest_price": buy_price,
                        "name": daily_names.get(bticker, bticker),
                    }

        # 3-4. 당일 총 자산 기록
        daily_total_equity = current_cash + sum(
            daily_prices.get(t, info["buy_price"]) * info["qty"]
            for t, info in portfolio.items()
        )
        daily_equity_history.append({
            "date": target_date,
            "equity": daily_total_equity,
        })

    # 4. 종합 백테스트 성과 지표 계산
    df_equity = pd.DataFrame(daily_equity_history)
    if df_equity.empty:
        print("❌ 성과 데이터를 집계할 수 없습니다.")
        return

    final_equity = df_equity.iloc[-1]["equity"]
    cumulative_return = (
        (final_equity - initial_capital) / initial_capital
    ) * 100

    # MDD (최대 낙폭) 계산
    df_equity["peak"] = df_equity["equity"].cummax()
    df_equity["drawdown"] = (
        (df_equity["equity"] - df_equity["peak"]) / df_equity["peak"]
    ) * 100
    mdd = df_equity["drawdown"].min()

    # 청산 거래 성과 집계
    df_trades = pd.DataFrame(closed_trades)
    total_trades_count = len(df_trades)

    if total_trades_count > 0:
        wins = df_trades[df_trades["profit_amt"] > 0]
        losses = df_trades[df_trades["profit_amt"] < 0]

        win_rate = (len(wins) / total_trades_count) * 100
        avg_profit = (
            wins["profit_amt"].mean() if not wins.empty else 0.0
        )
        avg_loss = (
            abs(losses["profit_amt"].mean()) if not losses.empty else 0.0
        )
        profit_factor = (
            (avg_profit / avg_loss) if avg_loss > 0 else 999.0
        )
        avg_return_per_trade = df_trades["profit_rate"].mean()
    else:
        win_rate = avg_return_per_trade = profit_factor = 0.0

    # 5. 백테스트 결과 리포트 출력
    print("\n" + "=" * 65)
    print("📊 Top 7 전략 백테스트 종합 성과 리포트")
    print("=" * 65)
    print(f"• 테스트 기간       : {start_date} ~ {end_date}")
    print(f"• 총 영업일 수     : {len(all_dates)}일")
    print(f"• 초기 자본금       : {initial_capital:,.0f}원")
    print(f"• 최종 평가 자산    : {final_equity:,.0f}원")
    print(
        f"• 누적 수익률       : {cumulative_return:+.2f}%"
    )
    print(f"• 최대 낙폭 (MDD)  : {mdd:.2f}%")
    print("-" * 65)
    print(f"• 총 청산 거래 건수 : {total_trades_count}건")
    print(f"• 승률 (Win Rate)   : {win_rate:.1f}%")
    print(
        f"• 건당 평균 수익률  : {avg_return_per_trade:+.2f}%"
    )
    print(
        f"• 손익비 (Profit Factor): {profit_factor:.2f}"
    )
    print("=" * 65)


if __name__ == "__main__":
    # 터미널 실행 인자 처리 (예: python backtest.py 2026-01-01 2026-09-30)
    s_date = sys.argv[1] if len(sys.argv) > 1 else "2026-01-01"
    e_date = sys.argv[2] if len(sys.argv) > 2 else "2026-09-30"

    run_backtest(start_date=s_date, end_date=e_date)
