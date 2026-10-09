import altair as alt
import pandas as pd
import streamlit as st
from db import supabase


def draw_integrated_chart(
    selected_chart_ticker,
    market_type="KR",
    ticker_name_map=None,
    buy_date=None,
    sell_date=None,
    buy_price=None,
    sell_price=None,
    supply_dates=None,
):
    """
    개별 종목 및 매매 복기용 기술적 차트 (Altair 기반 - 가로 넓이 완벽 동기화)
    """
    ticker_name_map = ticker_name_map or {}
    
    # 1. DB 주가 및 지표 조회
    chart_res = (
        supabase.table("daily_analysis")
        .select("price_date, open_price, high_price, low_price, close_price, volume, momentum_rank, ma20")
        .eq("ticker", selected_chart_ticker)
        .order("price_date", desc=True)
        .limit(125)
        .execute()
    )

    if not chart_res.data:
        st.info("해당 종목의 시계열 차트 데이터가 존재하지 않습니다.")
        return

    df_chart = pd.DataFrame(chart_res.data)
    df_chart["price_date"] = pd.to_datetime(df_chart["price_date"])
    df_chart = df_chart.sort_values("price_date", ascending=True).reset_index(drop=True)
    
    # X축 범주형 날짜 문자열
    df_chart["date_str"] = df_chart["price_date"].dt.strftime("%Y-%m-%d")
    df_chart["close_price"] = pd.to_numeric(df_chart["close_price"], errors="coerce")
    df_chart["volume"] = pd.to_numeric(df_chart["volume"], errors="coerce").fillna(0)
    df_chart["ma20"] = pd.to_numeric(df_chart["ma20"], errors="coerce")
    df_chart.loc[df_chart["ma20"] == 0, "ma20"] = None

    stock_name = ticker_name_map.get(selected_chart_ticker, selected_chart_ticker)

    # X축 공유
    x_scale_ordinal = alt.X("date_str:N", title=None, axis=alt.Axis(labelAngle=-45, tickCount=10))

    # ----------------------------------------------------
    # 1. 상단 차트: 주가 + MA20 + 모멘텀 순위(우측 Y축)
    # ----------------------------------------------------
    area_stock = (
        alt.Chart(df_chart)
        .mark_area(color="#87CEEB", opacity=0.2)
        .encode(
            x=x_scale_ordinal,
            y=alt.Y("close_price:Q", title="주가", scale=alt.Scale(zero=False, padding=15)),
        )
    )

    line_stock = (
        alt.Chart(df_chart)
        .mark_line(color="#00BFFF", strokeWidth=2.5)
        .encode(
            x=x_scale_ordinal,
            y=alt.Y("close_price:Q", title="주가", scale=alt.Scale(zero=False, padding=15)),
            tooltip=[
                alt.Tooltip("date_str:N", title="날짜"),
                alt.Tooltip("close_price:Q", title="종가", format=",.2f" if market_type == "US" else ",.0f"),
                alt.Tooltip("volume:Q", title="거래량", format=",.0f"),
            ],
        )
    )

    line_ma20 = (
        alt.Chart(df_chart)
        .mark_line(color="#ff7f0e", strokeDash=[4, 4], strokeWidth=1.5)
        .encode(
            x=x_scale_ordinal,
            y=alt.Y("ma20:Q", title=None, scale=alt.Scale(zero=False, padding=15)),
        )
    )

    # 우측 Y축 (모멘텀 순위)
    line_rank = (
        alt.Chart(df_chart)
        .mark_line(color="#808080", opacity=0.3, strokeWidth=1.2)
        .encode(
            x=x_scale_ordinal,
            y=alt.Y(
                "momentum_rank:Q",
                title="순위",
                scale=alt.Scale(domain=[100, 1], clamp=True),
                axis=alt.Axis(orient="right", titlePadding=10, tickCount=5),
            ),
            tooltip=[
                alt.Tooltip("date_str:N", title="날짜"),
                alt.Tooltip("momentum_rank:Q", title="모멘텀 순위"),
            ],
        )
    )

    chart_price = alt.layer(area_stock, line_stock, line_ma20)

    # 수급 유입일 점선
    if supply_dates:
        valid_supply_dates = [str(d) for d in supply_dates if str(d) in df_chart["date_str"].values]
        if valid_supply_dates:
            df_supply_chart = df_chart[df_chart["date_str"].isin(valid_supply_dates)].copy()
            rule_supply = (
                alt.Chart(df_supply_chart)
                .mark_rule(color="#ff9800", strokeWidth=1, strokeDash=[2, 2], opacity=0.8)
                .encode(x=x_scale_ordinal)
            )
            chart_price = alt.layer(chart_price, rule_supply)

    # 매수/매도 타점
    trade_elements = []
    if buy_date and str(buy_date) in df_chart["date_str"].values:
        buy_date_str = str(buy_date)
        df_buy = pd.DataFrame([{
            "date_str": buy_date_str,
            "price": float(buy_price) if buy_price else df_chart["close_price"].mean(),
        }])
        rule_buy = alt.Chart(df_buy).mark_rule(color="#d62728", strokeWidth=1.5, strokeDash=[3, 3]).encode(x="date_str:N")
        marker_buy = alt.Chart(df_buy).mark_point(shape="triangle-up", size=150, color="#d62728", filled=True).encode(x="date_str:N", y="price:Q")
        trade_elements.extend([rule_buy, marker_buy])

    if sell_date and str(sell_date) in df_chart["date_str"].values:
        sell_date_str = str(sell_date)
        df_sell = pd.DataFrame([{
            "date_str": sell_date_str,
            "price": float(sell_price) if sell_price else df_chart["close_price"].mean(),
        }])
        rule_sell = alt.Chart(df_sell).mark_rule(color="#1f77b4", strokeWidth=1.5, strokeDash=[3, 3]).encode(x="date_str:N")
        marker_sell = alt.Chart(df_sell).mark_point(shape="triangle-down", size=150, color="#1f77b4", filled=True).encode(x="date_str:N", y="price:Q")
        trade_elements.extend([rule_sell, marker_sell])

    if trade_elements:
        chart_price = alt.layer(chart_price, *trade_elements)

    chart_top = (
        alt.layer(chart_price, line_rank)
        .resolve_scale(y="independent")
        .properties(height=280)
    )

    # ----------------------------------------------------
    # 2. 하단 차트: 거래량 (우측 여백 맞춤용 Dummy Y축 추가)
    # ----------------------------------------------------
    bar_volume = (
        alt.Chart(df_chart)
        .mark_bar(color="#87CEFA", opacity=0.7)
        .encode(
            x=x_scale_ordinal,
            y=alt.Y("volume:Q", title="거래량", axis=alt.Axis(format="~s")),
            tooltip=[
                alt.Tooltip("date_str:N", title="날짜"),
                alt.Tooltip("volume:Q", title="거래량", format=",.0f"),
            ],
        )
    )

    # 📌 핵심: 상단 순위 Y축과 동일한 라벨 넓이를 확보하기 위한 빈 우측 축 생성
    dummy_right_axis = (
        alt.Chart(df_chart)
        .mark_line(opacity=0)
        .encode(
            x=x_scale_ordinal,
            y=alt.Y(
                "momentum_rank:Q",
                title=None,
                axis=alt.Axis(orient="right", labels=False, ticks=False, titlePadding=10),
            ),
        )
    )

    chart_bottom = (
        alt.layer(bar_volume, dummy_right_axis)
        .resolve_scale(y="independent")
        .properties(height=110)
    )

    # ----------------------------------------------------
    # 3. vconcat 및 정렬(align='all', bounds='flush')
    # ----------------------------------------------------
    combined_chart = (
        alt.vconcat(chart_top, chart_bottom)
        .resolve_scale(x="shared")
        .configure_concat(spacing=15)
        .bounds("flush")
    )

    legend_text = f"[{stock_name}] 하늘색 주가 추세선 | --- MA20 | ━ 모멘텀 순위"
    if supply_dates:
        legend_text += " | --- 수급 유입일"
    if buy_date or sell_date:
        legend_text += " | ▲ 🔴 매수타점 | ▼ 🔵 매도타점"

    st.caption(legend_text)
    st.altair_chart(combined_chart, use_container_width=True)
