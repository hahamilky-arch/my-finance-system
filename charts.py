import altair as alt
import pandas as pd
import streamlit as st
from db import supabase


def draw_integrated_chart(
    selected_chart_ticker,
    market_type,
    ticker_name_map,
    buy_date=None,
    sell_date=None,
    buy_price=None,
    sell_price=None,
):
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
    df_chart = df_chart.sort_values("price_date", ascending=True)
    df_chart["close_price"] = pd.to_numeric(
        df_chart["close_price"], errors="coerce"
    )
    df_chart["ma20"] = pd.to_numeric(df_chart["ma20"], errors="coerce")
    df_chart.loc[df_chart["ma20"] == 0, "ma20"] = None

    if index_res.data:
        df_idx_chart = pd.DataFrame(index_res.data).rename(
            columns={"close_price": "index_price", "ma50": "index_ma50"}
        )
        df_idx_chart["price_date"] = pd.to_datetime(df_idx_chart["price_date"])
        df_idx_chart["index_price"] = pd.to_numeric(
            df_idx_chart["index_price"], errors="coerce"
        )
        df_idx_chart["index_ma50"] = pd.to_numeric(
            df_idx_chart["index_ma50"], errors="coerce"
        )
        df_merged = pd.merge(
            df_chart, df_idx_chart, on="price_date", how="left"
        )
    else:
        df_merged = df_chart
        df_merged["index_price"] = df_merged["index_ma50"] = None

    idx_name = "KOSPI" if market_type == "KR" else "S&P 500"
    stock_name = ticker_name_map.get(
        selected_chart_ticker, selected_chart_ticker
    )

    # 1. 주가 선
    line_stock = (
        alt.Chart(df_merged)
        .mark_line(color="#1f77b4", strokeWidth=3)
        .encode(
            x=alt.X(
                "price_date:T",
                title=None,
                axis=alt.Axis(
                    format="%m/%d",
                    labelAngle=0,
                    tickCount=6,
                    labelOverlap=True,
                    grid=False,
                ),
            ),
            y=alt.Y(
                "close_price:Q",
                title="주가",
                scale=alt.Scale(zero=False, padding=15),
            ),
            tooltip=[
                alt.Tooltip("price_date:T", title="날짜", format="%Y-%m-%d"),
                alt.Tooltip(
                    "close_price:Q", title="종가", format=",..2f"
                ),
            ],
        )
    )

    # 2. MA20 점선
    line_ma20 = (
        alt.Chart(df_merged)
        .mark_line(color="#d62728", strokeDash=[5, 5], strokeWidth=1.5)
        .encode(
            x=alt.X("price_date:T", title=None),
            y=alt.Y(
                "ma20:Q", title=None, scale=alt.Scale(zero=False, padding=15)
            ),
        )
    )

    # 3. 모멘텀 순위 선 (우측 Y축 반전)
    line_rank = (
        alt.Chart(df_merged)
        .mark_line(color="#ff7f0e", opacity=0.3, strokeWidth=1.5)
        .encode(
            x=alt.X("price_date:T", title=None),
            y=alt.Y(
                "momentum_rank:Q",
                title="순위",
                scale=alt.Scale(domain=[100, 1], clamp=True),
                axis=alt.Axis(orient="right", titlePadding=10, tickCount=5),
            ),
            tooltip=[
                alt.Tooltip("price_date:T", title="날짜", format="%Y-%m-%d"),
                alt.Tooltip("momentum_rank:Q", title="모멘텀 순위"),
            ],
        )
    )

    chart_price = alt.layer(line_stock, line_ma20)

    # 📌 4. 매수 / 매도 타점 표시 (수직선 및 마커 추가)
    trade_elements = []
    if buy_date:
        df_buy = pd.DataFrame([{
            "price_date": pd.to_datetime(buy_date),
            "price": buy_price
            if buy_price
            else df_chart["close_price"].mean(),
            "label": "🔴 매수",
        }])

        vline_buy = (
            alt.Chart(df_buy)
            .mark_rule(color="#d62728", strokeWidth=2, strokeDash=[3, 3])
            .encode(x="price_date:T")
        )

        marker_buy = (
            alt.Chart(df_buy)
            .mark_point(
                shape="triangle-up",
                size=180,
                color="#d62728",
                filled=True,
                opacity=1.0,
            )
            .encode(
                x="price_date:T",
                y="price:Q",
                tooltip=[
                    alt.Tooltip("label:N", title="타점"),
                    alt.Tooltip("price_date:T", title="매수일", format="%Y-%m-%d"),
                    alt.Tooltip("price:Q", title="매수가", format=",..2f"),
                ],
            )
        )
        trade_elements.extend([vline_buy, marker_buy])

    if sell_date:
        df_sell = pd.DataFrame([{
            "price_date": pd.to_datetime(sell_date),
            "price": sell_price
            if sell_price
            else df_chart["close_price"].mean(),
            "label": "🔵 매도",
        }])

        vline_sell = (
            alt.Chart(df_sell)
            .mark_rule(color="#1f77b4", strokeWidth=2, strokeDash=[3, 3])
            .encode(x="price_date:T")
        )

        marker_sell = (
            alt.Chart(df_sell)
            .mark_point(
                shape="triangle-down",
                size=180,
                color="#1f77b4",
                filled=True,
                opacity=1.0,
            )
            .encode(
                x="price_date:T",
                y="price:Q",
                tooltip=[
                    alt.Tooltip("label:N", title="타점"),
                    alt.Tooltip(
                        "price_date:T", title="매도일", format="%Y-%m-%d"
                    ),
                    alt.Tooltip("price:Q", title="매도가", format=",..2f"),
                ],
            )
        )
        trade_elements.extend([vline_sell, marker_sell])

    if trade_elements:
        chart_price = alt.layer(chart_price, *trade_elements)

    chart_top = (
        alt.layer(chart_price, line_rank)
        .resolve_scale(y="independent")
        .properties(height=350)
        .interactive(bind_y=False)
    )

    # 지수 차트
    line_idx = (
        alt.Chart(df_merged)
        .mark_line(color="#2ca02c", strokeWidth=2.5)
        .encode(
            x=alt.X(
                "price_date:T",
                title=None,
                axis=alt.Axis(
                    format="%m/%d",
                    labelAngle=0,
                    tickCount=6,
                    labelOverlap=True,
                    grid=False,
                ),
            ),
            y=alt.Y(
                "index_price:Q",
                title=f"{idx_name} 지수",
                scale=alt.Scale(zero=False, padding=10),
            ),
            tooltip=[
                alt.Tooltip("price_date:T", title="날짜", format="%Y-%m-%d"),
                alt.Tooltip(
                    "index_price:Q", title="지수 종가", format=",..2f"
                ),
            ],
        )
    )

    line_idx_ma50 = (
        alt.Chart(df_merged)
        .mark_line(color="#d62728", strokeDash=[5, 5], strokeWidth=1.5)
        .encode(
            x=alt.X("price_date:T", title=None),
            y=alt.Y(
                "index_ma50:Q",
                title=None,
                scale=alt.Scale(zero=False, padding=10),
            ),
            tooltip=[alt.Tooltip("index_ma50:Q", title="MA50", format=",..2f")],
        )
    )

    chart_bottom = (
        alt.layer(line_idx, line_idx_ma50)
        .resolve_scale(y="shared")
        .properties(height=400)
        .interactive(bind_y=False)
    )

    st.markdown(
        f"""
    <div style="text-align: center; margin-bottom: 10px; font-size: 0.9em; color: #555555;">
        <span style="color:#1f77b4; font-weight:bold;">━</span> {stock_name} 주가 | 
        <span style="color:#d62728; font-weight:bold;">---</span> MA20 | 
        <span style="color:rgba(255, 127, 14, 0.5); font-weight:bold;">━</span> 모멘텀 순위 (우측 Y축 반전)
        {" | <span style='color:#d62728; font-weight:bold;'>▲ 🔴 매수타점</span> | <span style='color:#1f77b4; font-weight:bold;'>▼ 🔵 매도타점</span>" if buy_date or sell_date else ""}
    </div>
    """,
        unsafe_allow_html=True,
    )

    st.altair_chart(chart_top, use_container_width=True)

    st.markdown(
        f"""
    <div style="text-align: center; margin-top: 5px; margin-bottom: 10px; font-size: 0.9em; color: #555555;">
        <span style="color:#2ca02c; font-weight:bold;">━</span> {idx_name} 지수 종가 | 
        <span style="color:#d62728; font-weight:bold;">---</span> MA50
    </div>
    """,
        unsafe_allow_html=True,
    )

    st.altair_chart(chart_bottom, use_container_width=True)


def draw_attribution_charts(df_hist, market_type):
    if df_hist.empty:
        return

    df_grouped = (
        df_hist.groupby(["ticker", "종목명"])["profit_amount"]
        .sum()
        .reset_index()
    )

    top5 = df_grouped.nlargest(5, "profit_amount")
    worst5 = df_grouped.nsmallest(5, "profit_amount")

    df_top_worst = pd.concat([top5, worst5])
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
            y=alt.Y(
                "display_name:N",
                sort=alt.EncodingSortField(
                    field="profit_amount", order="descending"
                ),
                title=None,
            ),
            x=alt.X("profit_amount:Q", title="총 실현 손익"),
            color=alt.Color("color:N", scale=None),
            tooltip=[
                alt.Tooltip("display_name:N", title="종목"),
                alt.Tooltip(
                    "profit_amount:Q",
                    title="손익",
                    format=",..0f" if market_type == "KR" else ",..2f",
                ),
            ],
        )
        .properties(height=300, title="기여도 Top 5 & Worst 5")
    )

    scatter_chart = (
        alt.Chart(df_hist)
        .mark_circle(size=60, opacity=0.6)
        .encode(
            x=alt.X("holding_days:Q", title="보유 기간 (일)"),
            y=alt.Y(
                "profit_rate:Q", title="수익률 (%)", scale=alt.Scale(zero=True)
            ),
            color=alt.condition(
                alt.datum.profit_rate > 0,
                alt.value("#1f77b4"),
                alt.value("#d62728"),
            ),
            tooltip=[
                alt.Tooltip("종목명:N", title="종목"),
                alt.Tooltip("holding_days:Q", title="보유일수"),
                alt.Tooltip("profit_rate:Q", title="수익률(%)", format=".2f"),
                alt.Tooltip(
                    "profit_amount:Q",
                    title="손익",
                    format=",..0f" if market_type == "KR" else ",..2f",
                ),
            ],
        )
        .properties(height=300, title="보유 기간 대비 수익률 분포")
    )

    col1, col2 = st.columns(2)
    with col1:
        st.altair_chart(bar_chart, use_container_width=True)
    with col2:
        st.altair_chart(scatter_chart, use_container_width=True)
