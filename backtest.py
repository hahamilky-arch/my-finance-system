import os
import sys
import numpy as np
import pandas as pd
from supabase import create_client, Client

# 📌 1. db.py 및 strategy.py 로드 시 st.secrets 에러 방지를 위한 주입
import streamlit as st

url = os.environ.get("SUPABASE_URL")
key = os.environ.get("SUPABASE_KEY")

if url and key:
    if not hasattr(st.secrets, "_secrets") or st.secrets._secrets is None:
        st.secrets._secrets = {}
    st.secrets._secrets["SUPABASE_URL"] = url
    st.secrets._secrets["SUPABASE_KEY"] = key

from db import supabase


def save_trades_to_db(closed_trades):
    """백테스트 매매이력을 Supabase DB(backtest_trades)에 저장합니다."""
    if not closed_trades:
        print("💡 저장할 매매이력이 없습니다.")
        return

    print("\n💾 Supabase DB에 백테스트 매매이력을 저장 중입니다...")
    try:
        # 기존 백테스트 매매이력 삭제 (초기화)
        supabase.table("backtest_trades").delete().neq("id", 0).execute()

        # 새로 생성된 매매이력 저장 데이터 가공
        db_records = []
        for trade in closed_trades:
            db_records.append({
                "ticker": trade["ticker"],
                "name": trade["name"],
                "buy_date": trade["buy_date"],
                "sell_date": trade["sell_date"],
                "buy_price": float(trade["buy_price"]),
                "sell_price": float(trade["sell_price"]),
                "quantity": float(trade["qty"]),
                "profit_amount": float(trade["profit_amt"]),
                "profit_rate": float(trade["profit_rate"]),
                "exit_reason": trade["reason"],
            })

        # 100건씩 분할 배치(Batch) 저장
        batch_size = 100
        for i in range(0, len(db_records), batch_size):
            batch = db_records[i : i + batch_size]
            supabase.table("backtest_trades").insert(batch).execute()

        print(f"✅ 총 {len(db_records)}건의 매매이력이 DB에 저장되었습니다.")
    except Exception as e:
        print(f"⚠️ DB 저장 중 오류 발생 (테이블 'backtest_trades' 존재 여부 확인): {e}")


def run_backtest(
    start_date="2026-01-01",
    end_date="2026-09-30",
    market_type="KR",
    save_to_db=True,
):
    print("=" * 75)
    print(f"🚀 Quant Alpha [Top 7 Regime] 1월~9월 백테스트 & 매매이력 출력")
    print(f"• 테스트 기간       : {start_date} ~ {end_date}")
    print(f"• 대상 시장         : {market_type}")
    print(f"• 핵심 수식         : +8% 달성 시 트레일링 스탑 (max(최고가*0.92, 평단가))")
    print("=" * 75)

    # 1. 1월~9월 사이의 실제 존재하는 전체 영업일(price_date) 날짜 수집
    print("📅 영업일 목록 수집 중...")
    date_range = pd.date_range(start=start_date, end=end_date, freq="B")
    all_dates = []

    for dt in date_range:
        d_str = dt.strftime("%Y-%m-%d")
        res_chk = (
            supabase.table("daily_analysis")
            .select("price_date")
            .eq("market", market_type)
            .eq("price_date", d_str)
            .limit(1)
            .execute()
        )
        if res_chk.data:
            all_dates.append(d_str)

    if not all_dates:
        print(f"❌ {start_date} ~ {end_date} 기간 내 영업일 데이터가 없습니다.")
        return

    print(f"📅 총 {len(all_dates)}영업일 확인 완료!")

    # 2. 영업일별로 상위 50개(momentum_rank <= 50) 종목만 순차 수집
    print("⚡ 영업일별 상위 50개 종목 데이터 수집 중...")
    all_data_list = []

    for d_str in all_dates:
        try:
            res_daily = (
                supabase.table("daily_analysis")
                .select(
                    "price_date, ticker, momentum_rank, weighted_momentum, rs_score, rs_score_10, close_price, ma20, atr"
                )
                .eq("market", market_type)
                .eq("price_date", d_str)
                .lte("momentum_rank", 50)
                .order("momentum_rank", desc=False)
                .execute()
            )
            if res_daily.data:
                all_data_list.extend(res_daily.data)
        except Exception as e:
            print(f"⚠️ {d_str} 데이터 수집 실패: {e}")

    if not all_data_list:
        print("❌ 수집된 종목 데이터가 없습니다.")
        return

    df_all = pd.DataFrame(all_data_list)
    df_all["price_date"] = pd.to_datetime(df_all["price_date"]).dt.strftime(
        "%Y-%m-%d"
    )
    df_all["ticker"] = df_all["ticker"].astype(str).str.strip().str.upper()

    num_cols = [
        "momentum_rank",
        "weighted_momentum",
        "rs_score",
        "rs_score_10",
        "close_price",
        "ma20",
        "atr",
    ]
    for col in num_cols:
        df_all[col] = pd.to_numeric(df_all[col], errors="coerce")

    print(
        f"✅ 총 {len(df_all):,d}건 데이터 수집 완료 (총 {len(all_dates)}영업일 × 상위 50개)\n"
    )

    # 종목 한글명 맵핑 로드
    try:
        stocks_res = (
            supabase.table("stocks").select("ticker, name").execute()
        )
        stock_name_map = (
            {
                str(r["ticker"]).strip().upper(): r["name"]
                for r in stocks_res.data
            }
            if stocks_res.data
            else {}
        )
    except Exception:
        stock_name_map = {}

    # 3. 백테스트 계좌 상태 초기화
    initial_capital = 20000000.0  # 초기 자본금 (2,000만원)
    current_cash = initial_capital
    portfolio = {}  # {ticker: {'buy_price', 'qty', 'buy_date', 'highest_price', 'entry_atr', 'name'}}
    closed_trades = []
    daily_equity_history = []
    top_n_cfg = 7

    # 4. 일별 백테스트 시뮬레이션
    for target_date in all_dates:
        df_daily = df_all[df_all["price_date"] == target_date].copy()
        if df_daily.empty:
            continue

        daily_prices = dict(zip(df_daily["ticker"], df_daily["close_price"]))
        daily_ma20 = dict(zip(df_daily["ticker"], df_daily["ma20"]))

        # 4-1. 보유 종목 평가액 & 최고가 갱신 및 청산 조건 검사
        sell_list = []
        for t_code, p_info in list(portfolio.items()):
            c_price = daily_prices.get(t_code, p_info["buy_price"])
            ma20 = daily_ma20.get(t_code, 0.0)

            p_info["highest_price"] = max(p_info["highest_price"], c_price)
            b_price = p_info["buy_price"]
            h_price = p_info["highest_price"]
            e_atr = p_info["entry_atr"]

            # 청산 규칙 1: ATR 손절 (-2.5x)
            if c_price <= (b_price - 2.5 * e_atr):
                sell_list.append((t_code, "ATR 손절"))
                continue

            # 청산 규칙 2: +8% 이상 달성 시 트레일링 스탑 (최소 본절 보장)
            if h_price >= b_price * 1.08:
                ts_price = max(h_price * 0.92, b_price)
                if c_price <= ts_price:
                    sell_list.append((t_code, "익절/본절 트레일링스탑"))
                    continue

            # 청산 규칙 3: MA20 이탈
            if ma20 > 0 and c_price < ma20:
                sell_list.append((t_code, "MA20 이탈"))
                continue

        # 4-2. 매도 정산
        for sticker, reason in sell_list:
            if sticker in portfolio:
                p_item = portfolio.pop(sticker)
                sell_price = daily_prices.get(sticker, p_item["buy_price"])
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
                    "qty": p_item["qty"],
                    "profit_amt": profit_amt,
                    "profit_rate": profit_rate,
                    "reason": reason,
                })

        # 4-3. 신규 매수 스크리닝 (전략 3: 순위<=15, RS>0, 종가>MA20)
        cond_buy = (
            (df_daily["momentum_rank"] <= 15)
            & (df_daily["rs_score"] > 0)
            & (df_daily["rs_score_10"] > 0)
            & (df_daily["ma20"] > 0)
            & (df_daily["close_price"] > df_daily["ma20"])
        )
        candidates = df_daily[cond_buy].copy()
        candidates["이격도"] = (
            (candidates["close_price"] / candidates["ma20"]) - 1.0
        ) * 100
        candidates = candidates.sort_values(by="이격도", ascending=True)

        empty_slots = top_n_cfg - len(portfolio)

        if empty_slots > 0 and not candidates.empty:
            eval_total = current_cash + sum(
                daily_prices.get(t, info["buy_price"]) * info["qty"]
                for t, info in portfolio.items()
            )
            slot_budget = eval_total / top_n_cfg

            for _, buy_row in candidates.iterrows():
                bticker = buy_row["ticker"]
                if bticker in portfolio:
                    continue
                if empty_slots <= 0:
                    break

                b_price = float(buy_row["close_price"])
                b_atr = float(buy_row["atr"]) if pd.notna(buy_row["atr"]) else 0.0

                if b_price > 0 and current_cash >= slot_budget:
                    b_qty = slot_budget / b_price
                    current_cash -= slot_budget

                    portfolio[bticker] = {
                        "buy_price": b_price,
                        "qty": b_qty,
                        "buy_date": target_date,
                        "highest_price": b_price,
                        "entry_atr": b_atr,
                        "name": stock_name_map.get(bticker, bticker),
                    }
                    empty_slots -= 1

        # 4-4. 당일 총 평가 자산 집계
        daily_total_equity = current_cash + sum(
            daily_prices.get(t, info["buy_price"]) * info["qty"]
            for t, info in portfolio.items()
        )
        daily_equity_history.append({
            "date": target_date,
            "equity": daily_total_equity,
        })

    # 5. 종합 성과 리포트 산출
    df_equity = pd.DataFrame(daily_equity_history)
    if df_equity.empty:
        print("❌ 성과 데이터를 집계할 수 없습니다.")
        return

    final_equity = df_equity.iloc[-1]["equity"]
    cumulative_return = (
        (final_equity - initial_capital) / initial_capital
    ) * 100

    df_equity["peak"] = df_equity["equity"].cummax()
    df_equity["drawdown"] = (
        (df_equity["equity"] - df_equity["peak"]) / df_equity["peak"]
    ) * 100
    mdd = df_equity["drawdown"].min()

    df_trades = pd.DataFrame(closed_trades)
    total_trades_count = len(df_trades)

    if total_trades_count > 0:
        wins = df_trades[df_trades["profit_amt"] > 0]
        losses = df_trades[df_trades["profit_amt"] < 0]

        win_rate = (len(wins) / total_trades_count) * 100
        avg_profit = wins["profit_amt"].mean() if not wins.empty else 0.0
        avg_loss = (
            abs(losses["profit_amt"].mean()) if not losses.empty else 0.0
        )
        profit_factor = (avg_profit / avg_loss) if avg_loss > 0 else 999.0
        avg_return_per_trade = df_trades["profit_rate"].mean()
    else:
        win_rate = avg_return_per_trade = profit_factor = 0.0

    print("\n" + "=" * 75)
    print("📊 Top 7 전략 [1월~9월 전체] 백테스트 종합 성과 리포트")
    print("=" * 75)
    print(f"• 테스트 기간       : {start_date} ~ {end_date}")
    print(f"• 총 영업일 수       : {len(all_dates)}일")
    print(f"• 초기 자본금       : {initial_capital:,.0f}원")
    print(f"• 최종 평가 자산    : {final_equity:,.0f}원")
    print(f"• 누적 수익률       : {cumulative_return:+.2f}%")
    print(f"• 최대 낙폭 (MDD)    : {mdd:.2f}%")
    print("-" * 75)
    print(f"• 총 청산 거래 건수 : {total_trades_count}건")
    print(f"• 승률 (Win Rate)   : {win_rate:.1f}%")
    print(f"• 건당 평균 수익률  : {avg_return_per_trade:+.2f}%")
    print(f"• 손익비 (PF)       : {profit_factor:.2f}")
    print("=" * 75)

    # 6. 상세 매매 이력 콘솔 출력
    if total_trades_count > 0:
        print("\n📜 [상세 청산 매매 이력]")
        print("-" * 75)
        for idx, t in enumerate(closed_trades, 1):
            sign = "+" if t["profit_rate"] >= 0 else ""
            print(
                f"{idx:02d}. [{t['buy_date']} ~ {t['sell_date']}] {t['name']}({t['ticker']})"
            )
            print(
                f"    - 매수가: {t['buy_price']:,.0f}원 | 매도가: {t['sell_price']:,.0f}원"
            )
            print(
                f"    - 손익금: {t['profit_amt']:+,.0f}원 ({sign}{t['profit_rate']:.2f}%) | 사유: {t['reason']}"
            )
        print("-" * 75)

    # 7. Supabase DB에 저장 처리
    if save_to_db:
        save_trades_to_db(closed_trades)


if __name__ == "__main__":
    s_date = sys.argv[1] if len(sys.argv) > 1 else "2026-01-01"
    e_date = sys.argv[2] if len(sys.argv) > 2 else "2026-09-30"

    run_backtest(start_date=s_date, end_date=e_date, save_to_db=True)
