import numpy as np
import pandas as pd
from db import get_holdings_table, get_recently_sold_info, supabase


def get_data(
    selected_date,
    all_dates,
    market_type="KR",
    top_n_cfg=7,
    sl_cfg=-2.5,
    rebalance_cycle="상시 (빈자리 즉시 채우기)",
    is_bull=True,
    stop_new_buy=False,
    reduce_holdings=False,
    strategy_engine_mode="strat3_top7",
):
    target_date_str = pd.to_datetime(selected_date).strftime("%Y-%m-%d")

    # 1. 당일 수급/모멘텀 분석 데이터 로드
    try:
        res = (
            supabase.table("daily_analysis")
            .select("*")
            .eq("market", market_type)
            .eq("price_date", target_date_str)
            .order("momentum_rank", desc=False)
            .limit(200)
            .execute()
        )
        if not res.data:
            return None
        df = pd.DataFrame(res.data)
    except Exception as e:
        print(f"❌ 데이터 로드 오류: {e}")
        return None

    # 데이터 타입 변환
    df["ticker"] = df["ticker"].astype(str).str.strip().str.upper()
    df["종가"] = pd.to_numeric(df["close_price"], errors="coerce").fillna(0.0)
    df["MA20"] = pd.to_numeric(df["ma20"], errors="coerce").fillna(0.0)
    df["atr"] = pd.to_numeric(df["atr"], errors="coerce").fillna(0.0)
    df["MOT"] = pd.to_numeric(
        df["weighted_momentum"], errors="coerce"
    ).fillna(0.0)
    df["RS(90)"] = pd.to_numeric(df["rs_score"], errors="coerce").fillna(0.0)
    df["RS(10)"] = pd.to_numeric(df["rs_score_10"], errors="coerce").fillna(
        0.0
    )
    df["순위"] = pd.to_numeric(df["momentum_rank"], errors="coerce")

    # 종목명 맵핑
    try:
        stocks_res = (
            supabase.table("stocks").select("ticker, name").execute()
        )
        name_map = (
            {
                str(r["ticker"]).strip().upper(): r["name"]
                for r in stocks_res.data
            }
            if stocks_res.data
            else {}
        )
    except Exception:
        name_map = {}

    df["종목명"] = df["ticker"].map(lambda t: name_map.get(t, t))

    # 이격도 계산
    df["이격도"] = np.where(
        df["MA20"] > 0, ((df["종가"] / df["MA20"]) - 1.0) * 100, 0.0
    )

    # 2. 보유 종목 데이터 로드
    holdings_table = get_holdings_table(market_type)
    try:
        holdings_res = (
            supabase.table(holdings_table)
            .select("*")
            .is_("sell_date", "null")
            .execute()
        )
        holdings_data = holdings_res.data if holdings_res.data else []
    except Exception:
        holdings_data = []

    holdings_dict = {
        str(h["ticker"]).strip().upper(): h for h in holdings_data
    }

    # 3. 매매 상태 및 개별 세부 사유 판정
    status_list = []
    reason_list = []

    for _, row in df.iterrows():
        t_code = row["ticker"]
        c_price = row["종가"]
        ma20 = row["MA20"]
        atr = row["atr"]
        rank = row["순위"]

        is_holding = t_code in holdings_dict

        if is_holding:
            h_info = holdings_dict[t_code]
            buy_price = float(h_info.get("buy_price", c_price))
            highest_price = float(h_info.get("highest_price", c_price))

            # 📌 청산 개별 조건 검사 (가장 먼저 발동된 실제 조건만 부여)
            # 조건 1: ATR 손절 (-2.5x)
            if atr > 0 and c_price <= (buy_price - 2.5 * atr):
                status_list.append("매도필요")
                reason_list.append("ATR 손절 (-2.5x ATR 하회)")

            # 조건 2: +8% 달성 후 트레일링 스탑 (최소 본절 보장)
            elif highest_price >= buy_price * 1.08 and c_price <= max(
                highest_price * 0.92, buy_price
            ):
                status_list.append("매도필요")
                if max(highest_price * 0.92, buy_price) == buy_price:
                    reason_list.append(
                        "트레일링 스탑 (본절 보장 라인 이탈)"
                    )
                else:
                    reason_list.append(
                        "익절 스탑 (+8% 달성 후 고점 대비 -8% 하락)"
                    )

            # 조건 3: MA20 이탈
            elif ma20 > 0 and c_price < ma20:
                status_list.append("매도필요")
                reason_list.append("MA20 이탈 (20일 이동평균선 하회)")

            # 조건 4: 단기 타점 모멘텀 모드 손절(-5%) / 목표익절(+15%)
            elif (
                strategy_engine_mode == "short_term"
                and c_price >= buy_price * 1.15
            ):
                status_list.append("매도필요")
                reason_list.append("목표익절 달성 (+15%)")
            elif (
                strategy_engine_mode == "short_term"
                and c_price <= buy_price * 0.95
            ):
                status_list.append("매도필요")
                reason_list.append("단기 손절선 이탈 (-5%)")

            # 조건 5: 레짐 전환 (신규 매수 중지 또는 비중 축소)
            elif stop_new_buy or reduce_holdings or not is_bull:
                status_list.append("매도필요")
                reason_list.append("레짐 전환 (시장 하락장/리스크 관리 모드)")

            else:
                status_list.append("보유중")
                reason_list.append("보유 조건 유지")

        else:
            # 신규 매수 조건 판단
            if stop_new_buy or reduce_holdings or not is_bull:
                status_list.append("매수불가")
                reason_list.append("하락장/리스크 관리 (신규 매수 중지)")
            elif rank <= (15 if strategy_engine_mode == "strat3_top7" else 200):
                if (
                    row["RS(90)"] > 0
                    and row["RS(10)"] > 0
                    and ma20 > 0
                    and c_price > ma20
                ):
                    status_list.append("매수추천")
                    reason_list.append("조건충족")
                else:
                    status_list.append("매수불가")
                    reason_list.append("모멘텀/이격도 조건 미달")
            else:
                status_list.append("매수불가")
                reason_list.append("순위 범위 초과")

    df["매매상태"] = status_list
    df["제외사유"] = reason_list

    # 순위 및 변동폭 가공
    df["변동"] = 0
    df["상승금액"] = 0.0
    df["상승률"] = 0.0

    # 매수 추천 순위 할당
    buys = df[df["매매상태"] == "매수추천"].copy()
    buys["이격도_차이"] = (buys["종가"] / buys["MA20"]) - 1.0
    buys = buys.sort_values(by="이격도_차이", ascending=True)

    buy_ranks = {
        ticker: i + 1 for i, ticker in enumerate(buys["ticker"].tolist())
    }
    df["매수추천순위"] = df["ticker"].map(lambda t: buy_ranks.get(t, ""))

    return df
