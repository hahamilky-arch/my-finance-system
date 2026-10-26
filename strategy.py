import numpy as np
import pandas as pd
from db import get_holdings_table, get_index_ma200_ok, get_recently_sold_info, supabase


def _build_corr_matrix(market_type, target_date_str, tickers, lookback=60):
    """최근 lookback거래일 종가 수익률 상관행렬. 실패하면 None."""
    try:
        tickers = sorted({str(t).strip().upper() for t in tickers if str(t).strip()})
        if len(tickers) < 2:
            return None
        res = (
            supabase.table("daily_analysis")
            .select("ticker, price_date, close_price")
            .in_("ticker", tickers)
            .eq("market", market_type)
            .lte("price_date", target_date_str)
            .order("price_date", desc=True)
            .limit(5000)
            .execute()
        )
        df = pd.DataFrame(res.data or [])
        if df.empty:
            return None
        df["ticker"] = df["ticker"].astype(str).str.strip().str.upper()
        df["close_price"] = pd.to_numeric(df["close_price"], errors="coerce")
        px = df.pivot_table(index="price_date", columns="ticker", values="close_price").sort_index().tail(lookback + 1)
        return px.pct_change().dropna(how="all").corr(min_periods=20)
    except Exception as e:
        print(f"상관행렬 계산 실패: {e}")
        return None


def get_data(
    target_date,
    all_dates,
    market_type,
    top_n_cfg,
    sl_cfg,
    rebalance_cycle,
    is_bull_mode,
    stop_new_buy,
    reduce_holdings,
    strategy_engine_mode="strat3_top7",
    adv_opts=None,
):
    adv_opts = adv_opts or {}
    target_date_str = pd.to_datetime(target_date).strftime("%Y-%m-%d")

    # 1. 당일 데이터 조회
    res_curr = (
        supabase.table("daily_analysis")
        .select(
            "ticker, momentum_rank, weighted_momentum, rs_score, rs_score_10, close_price, ma10, ma20, atr, high_price, low_price, ma200"
        )
        .eq("price_date", target_date_str)
        .eq("market", market_type)
        .limit(5000)
        .execute()
    )

    df_final = pd.DataFrame(res_curr.data)
    if df_final.empty:
        return None

    num_cols = [
        "close_price",
        "ma10",
        "ma20",
        "atr",
        "high_price",
        "low_price",
        "ma200",
    ]
    for col in num_cols:
        if col in df_final.columns:
            df_final[col] = pd.to_numeric(
                df_final[col], errors="coerce"
            ).astype("float64")

    df_final["ticker"] = (
        df_final["ticker"].astype(str).str.strip().str.upper()
    )
    df_final["atr"] = df_final["atr"].fillna(0.0)

    # 2. 전일 데이터 조회 (상승금액 / 상승률 계산용)
    prev_date_res = (
        supabase.table("daily_analysis")
        .select("price_date")
        .eq("market", market_type)
        .lt("price_date", target_date_str)
        .order("price_date", desc=True)
        .limit(1)
        .execute()
    )

    df_prev = pd.DataFrame()
    if prev_date_res.data:
        res_prev = (
            supabase.table("daily_analysis")
            .select("ticker, momentum_rank, close_price, ma20")
            .eq("price_date", prev_date_res.data[0]["price_date"])
            .eq("market", market_type)
            .limit(5000)
            .execute()
        )
        if res_prev.data:
            df_prev = pd.DataFrame(res_prev.data)

    if not df_prev.empty:
        df_prev = df_prev.rename(
            columns={
                "momentum_rank": "순위_prev",
                "close_price": "종가_prev",
                "ma20": "MA20_prev",
            }
        )
        df_prev["ticker"] = (
            df_prev["ticker"].astype(str).str.strip().str.upper()
        )
        df_final = pd.merge(
            df_final,
            df_prev[["ticker", "순위_prev", "종가_prev", "MA20_prev"]],
            on="ticker",
            how="left",
        )
    else:
        df_final["순위_prev"] = df_final["종가_prev"] = df_final[
            "MA20_prev"
        ] = None

    df_final = df_final.rename(
        columns={
            "momentum_rank": "순위",
            "weighted_momentum": "MOT",
            "rs_score": "RS(90)",
            "rs_score_10": "RS(10)",
            "close_price": "종가",
        }
    )
    df_final[["순위_prev", "종가_prev", "MA20_prev"]] = df_final[
        ["순위_prev", "종가_prev", "MA20_prev"]
    ].apply(pd.to_numeric, errors="coerce")

    # 전일 대비 상승금액 / 상승률 / 순위변동 산출
    df_final["상승금액"] = df_final.apply(
        lambda r: r["종가"] - r["종가_prev"]
        if pd.notna(r["종가_prev"])
        else 0.0,
        axis=1,
    )
    df_final["상승률"] = df_final.apply(
        lambda r: (r["상승금액"] / r["종가_prev"] * 100)
        if pd.notna(r["종가_prev"]) and r["종가_prev"] > 0
        else 0.0,
        axis=1,
    )
    df_final["변동"] = df_final.apply(
        lambda r: int(r["순위_prev"] - r["순위"])
        if (pd.notna(r["순위_prev"]) and pd.notna(r["순위"]))
        else 0,
        axis=1,
    )

    df_final["ma20"] = df_final["ma20"].fillna(0)
    df_final["이격도"] = df_final.apply(
        lambda r: ((r["종가"] / r["ma20"]) - 1) * 100
        if (pd.notna(r["ma20"]) and r["ma20"] > 0)
        else 0.0,
        axis=1,
    )
    df_final = df_final.rename(columns={"ma20": "MA20", "ma10": "MA10"})

    cycle_passed = (
        True
        if rebalance_cycle == "상시 (빈자리 즉시 채우기)"
        else pd.Timestamp(target_date).day_name() == "Wednesday"
    )

    df_stocks = pd.DataFrame(
        supabase.table("stocks").select("ticker, name").execute().data
    )
    if not df_stocks.empty:
        df_stocks["ticker"] = (
            df_stocks["ticker"].astype(str).str.strip().str.upper()
        )

    df_final = pd.merge(df_final, df_stocks, on="ticker", how="left").rename(
        columns={"name": "종목명"}
    )
    df_final["종목명"] = df_final["종목명"].fillna(df_final["ticker"])
    if market_type == "US":
        df_final["종목명"] = df_final.apply(
            lambda r: f"[{r['ticker']}] {r['종목명']}", axis=1
        )

    table_name = get_holdings_table(market_type)
    try:
        h_res = (
            supabase.table(table_name)
            .select("*")
            .is_("sell_date", "null")
            .execute()
        )
        holdings_df = (
            pd.DataFrame(h_res.data) if h_res.data else pd.DataFrame()
        )
    except Exception:
        holdings_df = pd.DataFrame()

    my_holdings_clean = [
        str(t).strip().upper()
        for t in (holdings_df["ticker"].tolist() if not holdings_df.empty else [])
    ]
    sold_info = get_recently_sold_info(
        market_type, target_date_str, cooldown_days=3
    )

    sell_dict = {}  # {ticker: "구체적 매도 사유"}
    target_dt = pd.to_datetime(target_date)

    # 3. 전략별 보유 종목 청산 검사
    for _, row in df_final.iterrows():
        ticker_upper = str(row["ticker"]).strip().upper()
        if ticker_upper in my_holdings_clean:
            c_price, ma20, mom_rank = row["종가"], row["MA20"], row["순위"]
            h_row = holdings_df[
                holdings_df["ticker"].astype(str).str.strip().str.upper()
                == ticker_upper
            ]

            if not h_row.empty:
                buy_dt = pd.to_datetime(h_row.iloc[0]["buy_date"])
                buy_price = float(h_row.iloc[0]["buy_price"])
                highest_price = float(
                    h_row.iloc[0].get("highest_price", buy_price)
                )
                _ea = h_row.iloc[0].get("entry_atr", None)
                entry_atr = float(_ea) if (_ea is not None and pd.notna(_ea) and float(_ea) > 0) else float(row["atr"])
                days_held = (target_dt - buy_dt).days
                profit_rate_pos = (
                    ((c_price / buy_price) - 1) * 100 if buy_price > 0 else 0.0
                )
                max_profit_rate = (
                    ((highest_price / buy_price) - 1) * 100
                    if buy_price > 0
                    else 0.0
                )

                if strategy_engine_mode == "strat3_top7":
                    if stop_new_buy or not is_bull_mode:
                        sell_dict[ticker_upper] = "레짐 전환 (시장 하락장 모드)"
                        continue
                    if c_price <= (buy_price - 2.5 * entry_atr):
                        sell_dict[ticker_upper] = "ATR 손절 (-2.5x ATR 하회)"
                        continue
                    if highest_price >= buy_price * 1.08:
                        ts_price = max(highest_price * 0.92, buy_price)
                        if c_price <= ts_price:
                            sell_dict[ticker_upper] = (
                                "익절 트레일링스탑 (+8% 달성 후 수익보존)"
                            )
                            continue
                    # MA20 이탈: 2거래일 연속 종가가 20일선 아래일 때만 청산
                    _prev_below = (
                        pd.notna(row["종가_prev"]) and pd.notna(row["MA20_prev"])
                        and row["MA20_prev"] > 0 and row["종가_prev"] < row["MA20_prev"]
                    )
                    if ma20 > 0 and c_price < ma20 and _prev_below:
                        sell_dict[ticker_upper] = "MA20 2일 연속 이탈"
                        continue

                elif strategy_engine_mode == "short_term":
                    if max_profit_rate >= 15.0:
                        ts_price = max(highest_price * 0.97, buy_price * 1.15)
                        if c_price <= ts_price:
                            sell_dict[ticker_upper] = (
                                f"익절 트레일링스탑 (+15% 달성 후 최고가 {highest_price:,.2f} 대비 하락)"
                            )
                            continue

                    if c_price <= buy_price * (1 + (sl_cfg / 100.0)):
                        sell_dict[ticker_upper] = "단기 손절선 이탈 (-5%)"
                        continue
                    if c_price < ma20:
                        sell_dict[ticker_upper] = "MA20 이탈"
                        continue
                    if mom_rank > 200:
                        sell_dict[ticker_upper] = "순위 200위 초과"
                        continue
                    if days_held >= 14 and profit_rate_pos < 5.0:
                        sell_dict[ticker_upper] = (
                            f"보유기간 초과 (14일 경과 / 수익률 {profit_rate_pos:+.1f}% 미달)"
                        )
                        continue

                else:
                    rank_limit = 60 if is_bull_mode else 30
                    if c_price <= buy_price * (1 + (sl_cfg / 100.0)):
                        sell_dict[ticker_upper] = "손절선 이탈"
                        continue
                    if c_price < ma20:
                        sell_dict[ticker_upper] = "MA20 이탈"
                        continue
                    if mom_rank > rank_limit:
                        sell_dict[ticker_upper] = f"순위 {rank_limit}위 초과"
                        continue
                    if days_held >= 10 and profit_rate_pos < 3.0:
                        sell_dict[ticker_upper] = (
                            f"시간 손절 (10일 경과 / 수익률 {profit_rate_pos:+.1f}% 미달)"
                        )
                        continue

    # 4. 매수추천순위(Buy Rank) 산출
    buy_rank_map = {}
    if strategy_engine_mode == "strat3_top7":
        cond_rank = (
            (df_final["순위"] <= 15)
            & (df_final["RS(90)"] > 0)
            & (df_final["RS(10)"] > 0)
            & (df_final["MA20"] > 0)
            & (df_final["종가"] > df_final["MA20"])
        )
        candidates = df_final[cond_rank].sort_values(
            by="이격도", ascending=True
        )
        # [옵션] RS 가속 우선: 이격도 순위(낮을수록 좋음)와 RS 가속도(RS(10)-RS(90), 클수록 좋음) 순위를 평균
        if adv_opts.get("rs_accel") and len(candidates) > 1:
            _gap_rank = candidates["이격도"].rank(ascending=True, method="first")
            _acc_rank = (candidates["RS(10)"] - candidates["RS(90)"]).rank(ascending=False, method="first")
            candidates = candidates.assign(_score=_gap_rank + _acc_rank).sort_values(
                by=["_score", "이격도"], ascending=[True, True]
            ).drop(columns=["_score"])
    elif strategy_engine_mode == "short_term":
        cond_rank = (
            (df_final["순위"] <= 200)
            & (df_final["MOT"] >= 0.9)
            & (df_final["이격도"] >= -5.0)
            & (df_final["이격도"] <= 7.0)
        )
        candidates = df_final[cond_rank].sort_values(
            by="순위", ascending=True
        )
    else:
        cond_rank = (
            (df_final["순위"] <= 30)
            & (df_final["RS(90)"] > 0)
            & (df_final["MA20"] > 0)
            & (df_final["종가"] > df_final["MA20"])
        )
        candidates = df_final[cond_rank].sort_values(
            by="순위", ascending=True
        )

    for rank_idx, (idx, row) in enumerate(candidates.iterrows(), 1):
        ticker_upper = str(row["ticker"]).strip().upper()
        buy_rank_map[ticker_upper] = int(rank_idx)

    # 5. 실제 매수 추천 목록 선정
    effective_max_slots = (
        7
        if strategy_engine_mode == "strat3_top7"
        else (min(top_n_cfg, 3) if reduce_holdings else top_n_cfg)
    )
    slots_available = int(effective_max_slots) - len(
        [t for t in my_holdings_clean if t not in sell_dict]
    )
    total_needed = max(0, slots_available) + 2

    # [옵션] 상관관계 상한: 보유/선정 종목과 최근 60거래일 수익률 상관이 임계치 이상이면 제외
    corr_matrix = None
    corr_th = float(adv_opts.get("corr_th", 0.0) or 0.0)
    corr_skipped = {}
    if adv_opts.get("corr_cap") and corr_th > 0:
        corr_matrix = _build_corr_matrix(
            market_type, target_date_str,
            list(candidates["ticker"].astype(str).str.strip().str.upper()) + my_holdings_clean,
        )

    no_new_buy = bool(adv_opts.get("no_new_buy", False))
    # 지수 MA200 조건: 지수 종가가 200일선 아래면 신규 매수 금지 (전략 3)
    idx200_ok = True
    if strategy_engine_mode == "strat3_top7":
        idx200_ok = get_index_ma200_ok(market_type, target_date_str)
        if not idx200_ok:
            no_new_buy = True
    buy_list = set()
    if cycle_passed and (not stop_new_buy) and is_bull_mode and not no_new_buy:
        kept = [t for t in my_holdings_clean if t not in sell_dict]
        for idx, row in candidates.iterrows():
            if len(buy_list) >= total_needed:
                break
            ticker_upper = str(row["ticker"]).strip().upper()
            if (
                ticker_upper in my_holdings_clean
                or (
                    ticker_upper in sold_info
                    and row["종가"] <= sold_info[ticker_upper]
                )
            ):
                continue
            if corr_matrix is not None and ticker_upper in corr_matrix.index:
                hit = [
                    o for o in (kept + list(buy_list))
                    if o in corr_matrix.columns and o != ticker_upper
                    and pd.notna(corr_matrix.loc[ticker_upper, o])
                    and corr_matrix.loc[ticker_upper, o] >= corr_th
                ]
                if hit:
                    corr_skipped[ticker_upper] = f"상관 {corr_th:.2f} 이상({hit[0]})"
                    continue
            buy_list.add(ticker_upper)

    # 6. 상태 및 개별 세부 제외사유 부여
    def assign_status_and_reason(row):
        t = str(row["ticker"]).strip().upper()
        b_rank = buy_rank_map.get(t, "")

        if t in sell_dict:
            return "매도필요", sell_dict[t], b_rank

        if t in my_holdings_clean:
            return "보유중", "보유 조건 유지", b_rank

        if t in buy_list:
            return "매수추천", "조건충족", b_rank

        reasons = []
        if no_new_buy and adv_opts.get("no_new_buy_reason"):
            reasons.append(str(adv_opts["no_new_buy_reason"]))
        if strategy_engine_mode == "strat3_top7" and not idx200_ok:
            reasons.append("지수 < MA200")
        if t in corr_skipped:
            reasons.append(corr_skipped[t])
        if stop_new_buy:
            reasons.append("시장경보(" + ("KOSPI" if market_type == "KR" else "S&P500") + " < MA20 3일 연속)")
        if not is_bull_mode:
            reasons.append("하락장 레짐")
        if not cycle_passed:
            reasons.append("리밸런싱일 미해당")

        if strategy_engine_mode == "strat3_top7":
            if row["순위"] > 15:
                reasons.append("순위 15위 초과")
            if row["RS(90)"] <= 0:
                reasons.append("RS(90) <= 0")
            if row["RS(10)"] <= 0:
                reasons.append("RS(10) <= 0")
            if row["MA20"] <= 0 or row["종가"] <= row["MA20"]:
                reasons.append("MA20 하회")
        elif strategy_engine_mode == "short_term":
            if row["순위"] > 200:
                reasons.append("순위 200위 초과")
            if row["MOT"] < 0.9:
                reasons.append("MOT < 0.9")
            if not (-5.0 <= row["이격도"] <= 7.0):
                reasons.append("이격도 범위 초과")

        if t in sold_info and row["종가"] <= sold_info[t]:
            reasons.append("매도 쿨다운")

        return "", ", ".join(reasons) if reasons else "선순위 밀림", b_rank

    status_reason = df_final.apply(assign_status_and_reason, axis=1)
    df_final["매매상태"] = [x[0] for x in status_reason]
    df_final["제외사유"] = [x[1] for x in status_reason]
    df_final["매수추천순위"] = [x[2] for x in status_reason]

    return df_final.sort_values("순위")
