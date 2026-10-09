import pandas as pd
import plotly.express as px
import plotly.graph_objects as go
from plotly.subplots import make_subplots
import streamlit as st
from db import supabase


def draw_integrated_chart(
    ticker,
    market_type="KR",
    ticker_name_map=None,
    buy_date=None,
    sell_date=None,
    buy_price=None,
    sell_price=None,
    supply_dates=None,
):
    """
    개별 종목 기술적 차트 (휴장일 공백 제거 & 깔끔한 수급/타점 시각화)
    """
    stock_name = (
        ticker_name_map.get(ticker, ticker) if ticker_name_map else ticker
    )

    try:
        # DB 스키마 기준 안전 조회
        res = (
            supabase.table("daily_analysis")
            .select("price_date, open_price, high_price, low_price, close_price, volume, ma20, ma50, ma200")
            .eq("ticker", ticker)
            .order("price_date", desc=True)
            .limit(120)
            .execute()
        )
        df_chart = pd.DataFrame(res.data) if res.data else pd.DataFrame()
    except Exception as e:
        st.error(f"차트 데이터 조회 중 오류가 발생했습니다: {e}")
        return

    if df_chart.empty:
        st.info(f"[{ticker}] 종목의 차트 데이터가 존재하지 않습니다.")
        return

    # 날짜 오름차순 정렬
    df_chart = df_chart.sort_values("price_date").reset_index(drop=True)
    
    # 📌 휴장일 공백을 없애기 위해 'YYYY-MM-DD' 문자열 카테고리 컬럼 생성
    df_chart["date_str"] = pd.to_datetime(df_chart["price_date"]).dt.strftime("%Y-%m-%d")

    # 서브플롯 구성 (Row 1: 캔들스틱 + MA, Row 2: 거래량)
    fig = make_subplots(
        rows=2,
        cols=1,
        shared_xaxes=True,
        vertical_spacing=0.06,
        subplot_titles=(f"[{ticker}] {stock_name} 일봉 차트", "거래량"),
        row_width=[0.25, 0.75],
    )

    # 1. 캔들스틱 차트
    fig.add_trace(
        go.Candlestick(
            x=df_chart["date_str"],
            open=df_chart["open_price"],
            high=df_chart["high_price"],
            low=df_chart["low_price"],
            close=df_chart["close_price"],
            name="주가",
            increasing_line_color="#d62728",  # 양봉 빨강
            decreasing_line_color="#1f77b4",  # 음봉 파랑
            whiskerwidth=0.3,
        ),
        row=1,
        col=1,
    )

    # 2. 이동평균선 (MA20, MA50, MA200 - 존재하는 컬럼만)
    if "ma20" in df_chart.columns and df_chart["ma20"].notna().any():
        fig.add_trace(
            go.Scatter(
                x=df_chart["date_str"],
                y=df_chart["ma20"],
                mode="lines",
                name="MA20",
                line=dict(color="#ff7f0e", width=1.5),
            ),
            row=1,
            col=1,
        )

    if "ma50" in df_chart.columns and df_chart["ma50"].notna().any():
        fig.add_trace(
            go.Scatter(
                x=df_chart["date_str"],
                y=df_chart["ma50"],
                mode="lines",
                name="MA50",
                line=dict(color="#2ca02c", width=1.2),
            ),
            row=1,
            col=1,
        )

    if "ma200" in df_chart.columns and df_chart["ma200"].notna().any():
        fig.add_trace(
            go.Scatter(
                x=df_chart["date_str"],
                y=df_chart["ma200"],
                mode="lines",
                name="MA200",
                line=dict(color="#9467bd", width=1.0, dash="dot"),
            ),
            row=1,
            col=1,
        )

    # 3. 거래량 바 차트
    colors = [
        "#d62728" if c >= o else "#1f77b4"
        for c, o in zip(df_chart["close_price"], df_chart["open_price"])
    ]
    fig.add_trace(
        go.Bar(
            x=df_chart["date_str"],
            y=df_chart["volume"],
            name="거래량",
            marker_color=colors,
            opacity=0.6,
        ),
        row=2,
        col=1,
    )

    # 📌 4. 수급 유입일 표기 개선 (얇은 세로 점선 + 깔끔한 뱃지)
    if supply_dates:
        chart_dates_set = set(df_chart["date_str"].unique())
        for s_date in supply_dates:
            s_date_str = str(s_date)
            if s_date_str in chart_dates_set:
                # 얇고 선명한 주황색 세로 점선
                fig.add_vline(
                    x=s_date_str,
                    line_width=1,
                    line_dash="dot",
                    line_color="rgba(255, 112, 67, 0.6)",
                    row=1,
                    col=1,
                )
                # 차트 최상단 깔끔한 🔥 배지
                fig.add_annotation(
                    x=s_date_str,
                    y=0.98,
                    yref="paper",
                    text="🔥",
                    showarrow=False,
                    font=dict(size=11),
                    row=1,
                    col=1,
                )

    # 📌 5. 매수 / 매도 타점 표시
    if buy_date and str(buy_date) in df_chart["date_str"].values:
        buy_date_str = str(buy_date)
        fig.add_vline(
            x=buy_date_str,
            line_width=1.5,
            line_dash="dash",
            line_color="#d62728",
            row=1,
            col=1,
        )
        if buy_price:
            fig.add_trace(
                go.Scatter(
                    x=[buy_date_str],
                    y=[buy_price],
                    mode="markers+text",
                    name="매수타점",
                    marker=dict(symbol="triangle-up", size=12, color="#d62728"),
                    text=[f"매수: {buy_price:,.0f}" if market_type == "KR" else f"매수: ${buy_price:,.2f}"],
                    textposition="bottom center",
                ),
                row=1,
                col=1,
            )

    if sell_date and str(sell_date) in df_chart["date_str"].values:
        sell_date_str = str(sell_date)
        fig.add_vline(
            x=sell_date_str,
            line_width=1.5,
            line_dash="dash",
            line_color="#1f77b4",
            row=1,
            col=1,
        )
        if sell_price:
            fig.add_trace(
                go.Scatter(
                    x=[sell_date_str],
                    y=[sell_price],
                    mode="markers+text",
                    name="매도타점",
                    marker=dict(symbol="triangle-down", size=12, color="#1f77b4"),
                    text=[f"매도: {sell_price:,.0f}" if market_type == "KR" else f"매도: ${sell_price:,.2f}"],
                    textposition="top center",
                ),
                row=1,
                col=1,
            )

    # 📌 레이아웃 & 가독성 최적화
    fig.update_layout(
        height=500,
        margin=dict(l=10, r=10, t=35, b=10),
        xaxis_rangeslider_visible=False,
        legend=dict(
            orientation="h",
            yanchor="bottom",
            y=1.02,
            xanchor="right",
            x=1,
            font=dict(size=10),
        ),
        hovermode="x unified",
    )

    # 📌 휴장일 완전히 제거: X축을 범주형(category)으로 강제 고정
    fig.update_xaxes(
        type="category",
        nticks=10,
        tickangle=-45,
        gridcolor="#f0f0f0",
    )
    fig.update_yaxes(gridcolor="#f0f0f0")

    st.plotly_chart(fig, use_container_width=True)


def draw_attribution_charts(df_hist, market_type="KR"):
    """
    성과 분석(TAB 4)용 수익 기여도 및 누적 실현손익 차트
    """
    if df_hist.empty:
        return

    col_chart1, col_chart2 = st.columns(2)

    # 1. 누적 실현손익 추이 차트
    with col_chart1:
        df_hist_sorted = df_hist.sort_values("sell_date_dt").copy()
        df_hist_sorted["cum_profit"] = df_hist_sorted["profit_amount"].cumsum()
        df_hist_sorted["sell_date_str"] = df_hist_sorted["sell_date_dt"].dt.strftime("%Y-%m-%d")

        fig_cum = go.Figure()
        fig_cum.add_trace(
            go.Scatter(
                x=df_hist_sorted["sell_date_str"],
                y=df_hist_sorted["cum_profit"],
                mode="lines+markers",
                name="누적 실현손익",
                line=dict(color="#d62728", width=2.5),
                fill="tozeroy",
                fillcolor="rgba(214, 39, 40, 0.1)",
            )
        )
        fig_cum.update_layout(
            title="누적 실현손익 추이",
            height=300,
            margin=dict(l=10, r=10, t=35, b=20),
            xaxis=dict(type="category", tickangle=-45),
        )
        st.plotly_chart(fig_cum, use_container_width=True)

    # 2. 종목별 수익 기여도 TOP 7 바 차트
    with col_chart2:
        df_contrib = (
            df_hist.groupby("종목명")["profit_amount"]
            .sum()
            .reset_index()
            .sort_values("profit_amount", ascending=False)
            .head(7)
        )

        colors = [
            "#d62728" if p > 0 else "#1f77b4" for p in df_contrib["profit_amount"]
        ]

        fig_contrib = go.Figure()
        fig_contrib.add_trace(
            go.Bar(
                x=df_contrib["종목명"],
                y=df_contrib["profit_amount"],
                marker_color=colors,
                name="종목별 손익",
            )
        )
        fig_contrib.update_layout(
            title="상위 종목별 수익 기여도 TOP 7",
            height=300,
            margin=dict(l=10, r=10, t=35, b=20),
            xaxis=dict(tickangle=-30),
        )
        st.plotly_chart(fig_contrib, use_container_width=True)
