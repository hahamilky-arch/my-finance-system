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
    개별 종목 기술적 차트 (Altair 기반)
    - 주가: 하늘색 라인 + 영역 (또는 캔들)
    - 하단: 거래량 바 차트
    - 휴장일 공백 제거 및 기존 날짜 포맷 유지
    """
    ticker_name_map = ticker_name_map or {}
    
    # 1. DB 데이터 조회 (price_date, open, high, low, close, volume, ma20)
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
    
    # 기존 YYYY-MM-DD 날짜 포맷 유지 및 범주형 X축 생성 (휴장일 갭 자동 제거)
    df_chart["date_str"] = df_chart["price_date"].dt.strftime("%Y-%m-%d")
    df_chart["close_price"] = pd.to_numeric(df_chart["close_price"], errors="coerce")
    df_chart["open_price"] = pd.to_numeric(df_chart["open_price"], errors="coerce")
    df_chart["high_price"] = pd.to_numeric(df_chart["high_price"], errors="coerce")
    df_chart["low_price"] = pd.to_numeric(df_chart["low_price"], errors="coerce")
    df_chart["volume"] = pd.to_numeric(df_chart["volume"], errors="coerce").fillna(0)
    df_chart["ma20"] = pd.to_numeric(df_chart["ma20"], errors="coerce")
    df_chart.loc[df_chart["ma20"] == 0, "ma20"] = None

    stock_name = ticker_name_map.get(selected_chart_ticker, selected_chart_ticker)

    # X축 범주 설정 (휴장일 공백 완전히 제거)
    x_scale_ordinal = alt.X("date_str:N", title=None, axis=alt.Axis(labelAngle=-45, tickCount=10))

    # ----------------------------------------------------
    # 1. 상단 차트: 하늘색 주가 라인 & MA20
    # ----------------------------------------------------
    # 하늘색 영역 (Area)
    area_stock = (
        alt.Chart(df_chart)
        .mark_area(color="#87CEEB", opacity=0.25)
        .encode(
            x=x_scale_ordinal,
            y=alt.Y("close_price:Q", title="주가", scale=alt.Scale(zero=False, padding=15)),
        )
    )

    # 하늘색 선 (Line)
    line_stock = (
        alt.Chart(df_chart)
        .mark_line(color="#00BFFF", strokeWidth=2.5) # 선명한 하늘색(Deep Sky Blue)
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

    # MA20 이동평균선 (주황색 점선)
    line_ma20 = (
        alt.Chart(df_chart)
        .mark_line(color="#ff7f0e", strokeDash=[4, 4], strokeWidth=1.5)
        .encode(
            x=x_scale_ordinal,
            y=alt.Y("ma20:Q", title=None, scale=alt.Scale(zero=False, padding=15)),
        )
    )

    # 모멘텀 순위 선 (우측 Y축 반전)
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

    # 수급 유입일이 있을 경우 주황색 미세 세로선만 표시 (불 아이콘 제거)
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

    # 매수 / 매도 타점 표시
    trade_elements = []
    if buy_date and str(buy_date) in df_chart["date_str"].values:
        buy_date_str = str(buy_date)
        df_buy = pd.DataFrame([{
            "date_str": buy_date_str,
            "price": float(buy_price) if buy_price else df_chart["close_price"].mean(),
            "label": "🔴 매수",
        }])
        rule_buy = alt.Chart(df_buy).mark_rule(color="#d62728", strokeWidth=1.5, strokeDash=[3, 3]).encode(x="date_str:N")
        marker_buy = alt.Chart(df_buy).mark_point(shape="triangle-up", size=150, color="#d62728", filled=True).encode(x="date_str:N", y="price:Q")
        trade_elements.extend([rule_buy, marker_buy])

    if sell_date and str(sell_date) in df_chart["date_str"].values:
        sell_date_str = str(sell_date)
        df_sell = pd.DataFrame([{
            "date_str": sell_date_str,
            "price": float(sell_price) if sell_price else df_chart["close_price"].mean(),
            "label": "🔵 매도",
        }])
        rule_sell = alt.Chart(df_sell).mark_rule(color="#1f77b4", strokeWidth=1.5, strokeDash=[3, 3]).encode(x="date_str:N")
        marker_sell = alt.Chart(df_sell).mark_point(shape="triangle-down", size=150, color="#1f77b4", filled=True).encode(x="date_str:N", y="price:Q")
        trade_elements.extend([rule_sell, marker_sell])

    if trade_elements:
        chart_price = alt.layer(chart_price, *trade_elements)

    chart_top = (
        alt.layer(chart_price, line_rank)
        .resolve_scale(y="independent")
        .properties(height=320)
        .interactive(bind_y=False)
    )

    # ----------------------------------------------------
    # 2. 하단 차트: 거래량 바 차트 (Volume)
    # ----------------------------------------------------
    bar_volume = (
        alt.Chart(df_chart)
        .mark_bar(color="#87CEFA", opacity=0.7) # 거래량 하늘색 바
        .encode(
            x=x_scale_ordinal,
            y=alt.Y("volume:Q", title="거래량", axis=alt.Axis(format="~s")),
            tooltip=[
                alt.Tooltip("date_str:N", title="날짜"),
                alt.Tooltip("volume:Q", title="거래량", format=",.0f"),
            ],
        )
        .properties(height=130)
        .interactive(bind_y=False)
    )

    # 안내 레이블 및 대시보드 렌더링
    st.markdown(
        f"""
    <div style="text-align: center; margin-bottom: 6px; font-size: 0.85em; color: #555555;">
        <span style="color:#00BFFF; font-weight:bold;">━</span> [{stock_name}] 하늘색 주가 추세선 | 
        <span style="color:#ff7f0e; font-weight:bold;">---</span> MA20 | 
        <span style="color:#808080; font-weight:bold;">━</span> 모멘텀 순위
        {" | <span style='color:#ff9800; font-weight:bold;'>--- 수급 유입일</span>" if supply_dates else ""}
    </div>
    """,
        unsafe_allow_html=True,
    )

    st.altair_chart(chart_top, use_container_width=True)
    st.altair_chart(bar_volume, use_container_width=True)


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
        lambda x: "#00BFFF" if x > 0 else "#d62728"
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
        .properties(height=260, title="기여도 Top 5 & Worst 5")
    )

    scatter_chart = (
        alt.Chart(df_hist)
        .mark_circle(size=60, opacity=0.6)
        .encode(
            x=alt.X("holding_days:Q", title="보유 기간 (일)"),
            y=alt.Y("profit_rate:Q", title="수익률 (%)", scale=alt.Scale(zero=True)),
            color=alt.condition(alt.datum.profit_rate > 0, alt.value("#00BFFF"), alt.value("#d62728")),
            tooltip=[
                alt.Tooltip("종목명:N", title="종목"),
                alt.Tooltip("holding_days:Q", title="보유일수"),
                alt.Tooltip("profit_rate:Q", title="수익률(%)", format=".2f"),
                alt.Tooltip("profit_amount:Q", title="손익", format=",.0f" if market_type == "KR" else ",.2f"),
            ],
        )
        .properties(height=260, title="보유 기간 대비 수익률 분포")
    )

    col1, col2 = st.columns(2)
    with col1:
        st.altair_chart(bar_chart, use_container_width=True)
    with col2:
        st.altair_chart(scatter_chart, use_container_width=True)
