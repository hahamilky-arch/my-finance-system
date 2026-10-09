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
    개별 종목 및 지수 통합 차트 (Altair 기반 - 원래 날짜 포맷 유지 및 휴장일 갭 완전히 제거)
    """
    ticker_name_map = ticker_name_map or {}
    
    # 1. 개별 종목 주가 및 퀀트 데이터 조회 (최근 125영업일)
    chart_res = (
        supabase.table("daily_analysis")
        .select("price_date, close_price, momentum_rank, ma20")
        .eq("ticker", selected_chart_ticker)
        .order("price_date", desc=True)
        .limit(125)
        .execute()
    )

    benchmark_ticker = "^KS11" if market_type == "KR" else "^GSPC"
    index_res = (
        supabase.table("daily_analysis")
        .select("price_date, close_price, ma50")
        .eq("ticker", benchmark_ticker)
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
    
    # 📌 휴장일(공백) 없이 거래일만 1, 2, 3... 서순대로 붙이기 위한 문자열 날짜 컬럼 (기존 날짜 포맷 유지)
    df_chart["date_str"] = df_chart["price_date"].dt.strftime("%Y-%m-%d")
    df_chart["close_price"] = pd.to_numeric(df_chart["close_price"], errors="coerce")
    df_chart["ma20"] = pd.to_numeric(df_chart["ma20"], errors="coerce")
    df_chart.loc[df_chart["ma20"] == 0, "ma20"] = None

    if index_res.data:
        df_idx_chart = pd.DataFrame(index_res.data).rename(
            columns={"close_price": "index_price", "ma50": "index_ma50"}
        )
        df_idx_chart["price_date"] = pd.to_datetime(df_idx_chart["price_date"])
        df_idx_chart["index_price"] = pd.to_numeric(df_idx_chart["index_price"], errors="coerce")
        df_idx_chart["index_ma50"] = pd.to_numeric(df_idx_chart["index_ma50"], errors="coerce")
        df_merged = pd.merge(df_chart, df_idx_chart, on="price_date", how="left")
    else:
        df_merged = df_chart
        df_merged["index_price"] = df_merged["index_ma50"] = None

    idx_name = "KOSPI" if market_type == "KR" else "S&P 500"
    stock_name = ticker_name_map.get(selected_chart_ticker, selected_chart_ticker)

    # X축 범주 고정 (X축 휴장일 공백 완벽 제거)
    x_scale_ordinal = alt.X("date_str:N", title=None, axis=alt.Axis(labelAngle=-45, tickCount=10))

    # 1. 주가 선
    line_stock = (
        alt.Chart(df_merged)
        .mark_line(color="#1f77b4", strokeWidth=2.5)
        .encode(
            x=x_scale_ordinal,
            y=alt.Y("close_price:Q", title="주가", scale=alt.Scale(zero=False, padding=15)),
            tooltip=[
                alt.Tooltip("date_str:N", title="날짜"),
                alt.Tooltip("close_price:Q", title="종가", format=",.2f" if market_type == "US" else ",.0f"),
            ],
        )
    )

    # 2. MA20 이동평균선
    line_ma20 = (
        alt.Chart(df_merged)
        .mark_line(color="#d62728", strokeDash=[4, 4], strokeWidth=1.5)
        .encode(
            x=x_scale_ordinal,
            y=alt.Y("ma20:Q", title=None, scale=alt.Scale(zero=False, padding=15)),
        )
    )

    # 3. 모멘텀 순위 선 (우측 Y축 반전)
    line_rank = (
        alt.Chart(df_merged)
        .mark_line(color="#ff7f0e", opacity=0.35, strokeWidth=1.5)
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

    chart_price = alt.layer(line_stock, line_ma20)

    # 📌 4. 수급 유입일 표기 (🔥 수급 아이콘 및 깔끔한 주황 점선)
    if supply_dates:
        valid_supply_dates = [str(d) for d in supply_dates if str(d) in df_merged["date_str"].values]
        if valid_supply_dates:
            df_supply_chart = df_merged[df_merged["date_str"].isin(valid_supply_dates)].copy()
            
            # 수급일 주황색 세로선
            rule_supply = (
                alt.Chart(df_supply_chart)
                .mark_rule(color="#ff9800", strokeWidth=1, strokeDash=[2, 2], opacity=0.7)
                .encode(x=x_scale_ordinal)
            )
            
            # 주가 위 🔥 이모지 표기
            text_supply = (
                alt.Chart(df_supply_chart)
                .mark_text(text="🔥", dy=-12, size=13)
                .encode(
                    x=x_scale_ordinal,
                    y=alt.Y("close_price:Q"),
                    tooltip=[
                        alt.Tooltip("date_str:N", title="수급포착일"),
                        alt.Tooltip("close_price:Q", title="종가"),
                    ]
                )
            )
            chart_price = alt.layer(chart_price, rule_supply, text_supply)

    # 5. 매수/매도 타점 수직선 & 삼각형 마커
    trade_elements_stock = []
    trade_elements_index = []

    if buy_date and str(buy_date) in df_merged["date_str"].values:
        buy_date_str = str(buy_date)
        df_buy = pd.DataFrame([{
            "date_str": buy_date_str,
            "price": float(buy_price) if buy_price else df_chart["close_price"].mean(),
            "label": "🔴 매수",
        }])

        vline_buy_stock = alt.Chart(df_buy).mark_rule(color="#d62728", strokeWidth=2, strokeDash=[3, 3]).encode(x="date_str:N")
        vline_buy_index = alt.Chart(df_buy).mark_rule(color="#d62728", strokeWidth=2, strokeDash=[3, 3]).encode(x="date_str:N")

        marker_buy = (
            alt.Chart(df_buy)
            .mark_point(shape="triangle-up", size=180, color="#d62728", filled=True, opacity=1.0)
            .encode(
                x="date_str:N",
                y="price:Q",
                tooltip=[
                    alt.Tooltip("label:N", title="타점"),
                    alt.Tooltip("date_str:N", title="매수일"),
                    alt.Tooltip("price:Q", title="매수가", format=",.2f" if market_type == "US" else ",.0f"),
                ],
            )
        )
        trade_elements_stock.extend([vline_buy_stock, marker_buy])
        trade_elements_index.append(vline_buy_index)

    if sell_date and str(sell_date) in df_merged["date_str"].values:
        sell_date_str = str(sell_date)
        df_sell = pd.DataFrame([{
            "date_str": sell_date_str,
            "price": float(sell_price) if sell_price else df_chart["close_price"].mean(),
            "label": "🔵 매도",
        }])

        vline_sell_stock = alt.Chart(df_sell).mark_rule(color="#1f77b4", strokeWidth=2, strokeDash=[3, 3]).encode(x="date_str:N")
        vline_sell_index = alt.Chart(df_sell).mark_rule(color="#1f77b4", strokeWidth=2, strokeDash=[3, 3]).encode(x="date_str:N")

        marker_sell = (
            alt.Chart(df_sell)
            .mark_point(shape="triangle-down", size=180, color="#1f77b4", filled=True, opacity=1.0)
            .encode(
                x="date_str:N",
                y="price:Q",
                tooltip=[
                    alt.Tooltip("label:N", title="타점"),
                    alt.Tooltip("date_str:N", title="매도일"),
                    alt.Tooltip("price:Q", title="매도가", format=",.2f" if market_type == "US" else ",.0f"),
                ],
            )
        )
        trade_elements_stock.extend([vline_sell_stock, marker_sell])
        trade_elements_index.append(vline_sell_index)

    if trade_elements_stock:
        chart_price = alt.layer(chart_price, *trade_elements_stock)

    chart_top = (
        alt.layer(chart_price, line_rank)
        .resolve_scale(y="independent")
        .properties(height=350)
        .interactive(bind_y=False)
    )

    # 6. 지수 차트
    line_idx = (
        alt.Chart(df_merged)
        .mark_line(color="#2ca02c", strokeWidth=2.0)
        .encode(
            x=x_scale_ordinal,
            y=alt.Y("index_price:Q", title=f"{idx_name} 지수", scale=alt.Scale(zero=False, padding=10)),
            tooltip=[
                alt.Tooltip("date_str:N", title="날짜"),
                alt.Tooltip("index_price:Q", title="지수 종가", format=",.2f"),
            ],
        )
    )

    line_idx_ma50 = (
        alt.Chart(df_merged)
        .mark_line(color="#d62728", strokeDash=[4, 4], strokeWidth=1.5)
        .encode(
            x=x_scale_ordinal,
            y=alt.Y("index_ma50:Q", title=None, scale=alt.Scale(zero=False, padding=10)),
            tooltip=[alt.Tooltip("index_ma50:Q", title="MA50", format=",.2f")],
        )
    )

    chart_index = alt.layer(line_idx, line_idx_ma50)
    if trade_elements_index:
        chart_index = alt.layer(chart_index, *trade_elements_index)

    chart_bottom = (
        chart_index.resolve_scale(y="shared")
        .properties(height=220)
        .interactive(bind_y=False)
    )

    st.markdown(
        f"""
    <div style="text-align: center; margin-bottom: 8px; font-size: 0.85em; color: #555555;">
        <span style="color:#1f77b4; font-weight:bold;">━</span> {stock_name} 주가 | 
        <span style="color:#d62728; font-weight:bold;">---</span> MA20 | 
        <span style="color:rgba(255, 127, 14, 0.6); font-weight:bold;">━</span> 모멘텀 순위 (우측 Y축 반전)
        {" | <span style='color:#ff9800; font-weight:bold;'>🔥 수급포착</span>" if supply_dates else ""}
        {" | <span style='color:#d62728; font-weight:bold;'>▲ 🔴 매수타점</span> | <span style='color:#1f77b4; font-weight:bold;'>▼ 🔵 매도타점</span>" if buy_date or sell_date else ""}
    </div>
    """,
        unsafe_allow_html=True,
    )

    st.altair_chart(chart_top, use_container_width=True)

    st.markdown(
        f"""
    <div style="text-align: center; margin-top: 2px; margin-bottom: 8px; font-size: 0.85em; color: #555555;">
        <span style="color:#2ca02c; font-weight:bold;">━</span> {idx_name} 지수 종가 | 
        <span style="color:#d62728; font-weight:bold;">---</span> MA50
    </div>
    """,
        unsafe_allow_html=True,
    )

    st.altair_chart(chart_bottom, use_container_width=True)


def draw_attribution_charts(df_hist, market_type="KR"):
    """
    성과 분석(TAB 4)용 수익 기여도 차트 (Altair 기반)
    """
    if df_hist.empty:
        return

    df_grouped = (
        df_hist.groupby(["ticker", "종목명"])["profit_amount"]
        .sum()
        .reset_index()
    )

    top5 = df_grouped.nlargest(5, "profit_amount")
    worst5 = df_grouped.nsmallest(5, "profit_amount")

    df_top_worst = pd.concat([top5, worst5]).drop_duplicates()
    df_top_worst["color"] = df_top_worst["profit_amount"].apply(
        lambda x: "#1f77b4" if x > 0 else "#d62728"
    )
    df_top_worst["display_name"] = df_top_worst.apply(
        lambda r: f"{r['종목명']} ({r['ticker']})", axis=1
    )

    bar_chart = (
        alt.Chart(df_top_worst)
        .mark_bar()
        .encode(
            y=alt.Y("display_name:N", sort=alt.EncodingSortField(field="profit_amount", order="descending"), title=None),
            x=alt.X("profit_amount:Q", title="총 실현 손익"),
            color=alt.Color("color:N", scale=None),
            tooltip=[
                alt.Tooltip("display_name:N", title="종목"),
                alt.Tooltip("profit_amount:Q", title="손익", format=",.0f" if market_type == "KR" else ",.2f"),
            ],
        )
        .properties(height=280, title="기여도 Top 5 & Worst 5")
    )

    scatter_chart = (
        alt.Chart(df_hist)
        .mark_circle(size=60, opacity=0.6)
        .encode(
            x=alt.X("holding_days:Q", title="보유 기간 (일)"),
            y=alt.Y("profit_rate:Q", title="수익률 (%)", scale=alt.Scale(zero=True)),
            color=alt.condition(alt.datum.profit_rate > 0, alt.value("#1f77b4"), alt.value("#d62728")),
            tooltip=[
                alt.Tooltip("종목명:N", title="종목"),
                alt.Tooltip("holding_days:Q", title="보유일수"),
                alt.Tooltip("profit_rate:Q", title="수익률(%)", format=".2f"),
                alt.Tooltip("profit_amount:Q", title="손익", format=",.0f" if market_type == "KR" else ",.2f"),
            ],
        )
        .properties(height=280, title="보유 기간 대비 수익률 분포")
    )

    col1, col2 = st.columns(2)
    with col1:
        st.altair_chart(bar_chart, use_container_width=True)
    with col2:
        st.altair_chart(scatter_chart, use_container_width=True)
