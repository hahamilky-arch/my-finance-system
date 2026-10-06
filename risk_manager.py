import pandas as pd


def calculate_holdings_risk(
    holdings_db,
    df_display,
    market_type,
    account_total_input,
    current_engine_key,
    sl_cfg,
    target_date_str,
):
    """보유 종목의 1번(익절)/2번(손절) 스톱가 및 포트폴리오 리스크 노출도(2% Rule)를 계산합니다."""
    if holdings_db.empty:
        return [], 0.0, []

    holdings_list = []
    risk_violations = []
    target_date_dt = pd.to_datetime(target_date_str)

    for _, h_row in holdings_db.iterrows():
        ticker = h_row["ticker"]
        raw_name = h_row.get("name", ticker)
        buy_price = float(h_row.get("buy_price", 0.0))
        qty = float(h_row.get("quantity", 1.0))

        buy_date_raw = h_row.get("buy_date")
        holding_days = (
            max(0, (target_date_dt - pd.to_datetime(buy_date_raw)).days)
            if pd.notna(buy_date_raw) and buy_date_raw
            else 0
        )

        raw_highest = h_row.get("highest_price")
        prev_highest = (
            buy_price
            if (
                pd.isna(raw_highest)
                or raw_highest is None
                or float(raw_highest) == 0
            )
            else float(raw_highest)
        )

        curr_row = df_display[
            df_display["ticker"].astype(str).str.strip().str.upper()
            == str(ticker).strip().upper()
        ]

        if not curr_row.empty:
            curr_price = float(curr_row["종가"].values[0])
            engine_status = curr_row["매매상태"].values[0]
            atr_val = (
                float(curr_row.get("atr", 0.0).values[0])
                if "atr" in curr_row.columns
                else 0.0
            )
        else:
            curr_price, engine_status, atr_val = buy_price, "보유", 0.0

        highest_price = max(prev_highest, curr_price, buy_price)
        eval_val = curr_price * qty
        profit_amt = (curr_price - buy_price) * qty
        profit_rate = (
            ((curr_price / buy_price) - 1) * 100 if buy_price > 0 else 0.0
        )

        # 📌 1번 / 2번 스톱기준 산출 (+8% 이상 시 최소 본절 보장)
        max_return = (
            (highest_price / buy_price) - 1.0 if buy_price > 0 else 0.0
        )
        tp_stop_price = max(highest_price * 0.92, buy_price)  # 1번: 익절/본절 스탑가

        if atr_val > 0 and current_engine_key == "strat3_top7":
            atr_stop_price = max(
                buy_price - (2.5 * atr_val), highest_price - (2.5 * atr_val)
            )  # 2번: ATR 손절 스탑가
        else:
            atr_stop_price = max(
                buy_price * (1 + (sl_cfg / 100.0)), highest_price * 0.95
            )

        if max_return >= 0.08:
            stop_type_label = "🎯 1번(익절)"
            effective_stop_price = tp_stop_price
        else:
            stop_type_label = "🛡️ 2번(손절)"
            effective_stop_price = atr_stop_price

        max_loss_amt = max(0.0, (buy_price - effective_stop_price) * qty)
        stock_risk_pct = (
            (max_loss_amt / account_total_input * 100)
            if account_total_input > 0
            else 0.0
        )
        if stock_risk_pct > 2.0:
            risk_violations.append(f"{ticker} ({stock_risk_pct:.1f}%)")

        if max_return >= 0.08 and curr_price <= tp_stop_price:
            status = "🎯 익절 이탈 (+8% 도달 후 반락)"
        elif engine_status == "매도" or curr_price <= atr_stop_price:
            status = "🟢 익절 이탈" if profit_rate > 0 else "🚨 손절 이탈"
        else:
            status = "보유"

        holdings_list.append({
            "종목명": f"[{ticker}] {raw_name}"
            if market_type == "US"
            else f"{raw_name}",
            "종목코드": ticker,
            "수량": qty,
            "평단가": buy_price,
            "최고가": highest_price,
            "현재가": curr_price,
            "평가금액": eval_val,
            "손익금액": profit_amt,
            "수익률(%)": profit_rate,
            "비중(%)": 0.0,
            "ATR": atr_val,
            "스톱기준": stop_type_label,
            "손절/스톱가": effective_stop_price,
            "보유일수": holding_days,
            "상태": status,
        })

    total_risk_amount = sum(
        max(0.0, (item["평단가"] - item["손절/스톱가"]) * item["수량"])
        for item in holdings_list
    )
    total_risk_pct = (
        (total_risk_amount / account_total_input) * 100
        if account_total_input > 0
        else 0.0
    )

    return holdings_list, total_risk_pct, risk_violations
