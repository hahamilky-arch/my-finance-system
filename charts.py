import numpy as np
import pandas as pd
import plotly.graph_objects as go
from plotly.subplots import make_subplots
import streamlit as st

# db 모듈에서 supabase 객체 불러오기
from db import supabase


def draw_integrated_chart(
    ticker,
    market_type,
    ticker_name_map,
    buy_date=None,
    sell_date=None,
    buy_price=None,
    sell_price=None,
    supply_dates=None,
):
    """개별 종목 기술적 차트 + 수급 포착 표시 + 거래량 + 최하단 지수 차트(MA20, MA50, MA200) 통합 그리기"""
    stock_name = ticker_name_map.get(ticker, ticker)
    index_symbol = "^KS11" if market_type == "KR" else "^GSPC"
    index_name = "코스피 (^KS11)" if market_type == "KR" else "S&P 500 (^GSPC)"

    try:
        # 1. 개별 종목 시계열 데이터 조회 (최근 120영업일)
        res_stock = (
            supabase.table("daily_analysis")
            .select("price_date, close_price, open_price, high_price, low_price, volume, ma20, ma50, ma200")
            .eq("ticker", ticker)
            .order("price_date", desc=True)
            .limit(120)
            .execute()
        )

        # 2. 시장 지수 시계열 데이터 조회 (최근 120영업일)
        res_index = (
            supabase.table("daily_analysis")
            .select("price_date, close_price, ma20, ma50, ma200")
            .eq("ticker", index_symbol)
            .order("price_date", desc=True)
            .limit(120)
            .execute()
        )

        if not res_stock.data:
            st.warning(f"[{ticker}] 종목의 차트 데이터가 존재하지 않습니다.")
            return

        # 데이터프레임 변환 및 날짜 정렬
        df_stock = pd.DataFrame(res_stock.data)
        df_stock["price_date_dt"] = pd.to_datetime(df_stock["price_date"])
        df_stock = df_stock.sort_values("price_date_dt").reset_index(drop=True)
        df_stock["date_str"] = df_stock["price_date_dt"].dt.strftime("%Y-%m-%d")

        # 수치형 변환
        for col in ["close_price", "open_price", "high_price", "low_price", "volume", "ma20", "ma50", "ma200"]:
            if col in df_stock.columns:
                df_stock[col] = pd.to_numeric(df_stock[col], errors="coerce")

        # 지수 데이터 정리
        df_index = pd.DataFrame(res_index.data) if res_index.data else pd.DataFrame()
        if not df_index.empty:
            df_index["price_date_dt"] = pd.to_datetime(df_index["price_date"])
            df_index = df_index.sort_values("price_date_dt").reset_index(drop=True)
            df_index["date_str"] = df_index["price_date_dt"].dt.strftime("%Y-%m-%d")
            for col in ["close_price", "ma20", "ma50", "ma200"]:
                if col in df_index.columns:
                    df_index[col] = pd.to_numeric(df_index[col], errors="coerce")

        # 📌 3개 행 서브플롯 생성 (Row 1: 종목 차트, Row 2: 거래량, Row 3: 최하단 지수 차트)
        fig = make_subplots(
            rows=3,
            cols=1,
            shared_xaxes=True,
            vertical_spacing=0.05,
            row_heights=[0.50, 0.20, 0.30],
            subplot_titles=(
                f"[{ticker}] {stock_name} 주가 및 이동평균선",
                "거래량",
                f"{index_name} 지수 추이 (20/50/200일선)",
            ),
        )

        # --- Row 1: 개별 종목 캔들스틱 및 이동평균선 ---
        fig.add_trace(
            go.Candlestick(
                x=df_stock["date_str"],
                open=df_stock["open_price"],
                high=df_stock["high_price"],
                low=df_stock["low_price"],
                close=df_stock["close_price"],
                name="주가",
                increasing_line_color="#d62728" if market_type == "KR" else "#2ca02c",
                decreasing_line_color="#1f77b4" if market_type == "KR" else "#d62728",
            ),
            row=1,
            col=1,
        )

        if df_stock["ma20"].notna().any():
            fig.add_trace(
                go.Scatter(
                    x=df_stock["date_str"],
                    y=df_stock["ma20"],
                    mode="lines",
                    name="MA20",
                    line=dict(color="#ff7f0e", width=1.5),
                ),
                row=1,
                col=1,
            )

        if "ma50" in df_stock.columns and df_stock["ma50"].notna().any():
            fig.add_trace(
                go.Scatter(
                    x=df_stock["date_str"],
                    y=df_stock["ma50"],
                    mode="lines",
                    name="MA50",
                    line=dict(color="#2ca02c", width=1.5, dash="dot"),
                ),
                row=1,
                col=1,
            )

        if "ma200" in df_stock.columns and df_stock["ma200"].notna().any():
            fig.add_trace(
                go.Scatter(
                    x=df_stock["date_str"],
                    y=df_stock["ma200"],
                    mode="lines",
                    name="MA200",
                    line=dict(color="#d62728", width=1.5, dash="dashdot"),
                ),
                row=1,
                col=1,
            )

        # 수급 포착 마커
        if supply_dates:
            supp_df = df_stock[df_stock["price_date"].isin(supply_dates)]
            if not supp_df.empty:
                fig.add_trace(
                    go.Scatter(
                        x=supp_df["date_str"],
                        y=supp_df["high_price"] * 1.02,
                        mode="markers",
                        name="수급포착",
                        marker=dict(symbol="triangle-down", size=10, color="#2e7d32"),
                    ),
                    row=1,
                    col=1,
                )

        # 매수/매도 타점 표시 (복기용)
        if buy_date and buy_date in df_stock["price_date"].values:
            b_row = df_stock[df_stock["price_date"] == buy_date].iloc[0]
            fig.add_trace(
                go.Scatter(
                    x=[b_row["date_str"]],
                    y=[buy_price if buy_price else b_row["close_price"]],
                    mode="markers+text",
                    name="매수타점",
                    text=["매수"],
                    textposition="bottom center",
                    marker=dict(symbol="circle", size=12, color="red"),
                ),
                row=1,
                col=1,
            )

        if sell_date and sell_date in df_stock["price_date"].values:
            s_row = df_stock[df_stock["price_date"] == sell_date].iloc[0]
            fig.add_trace(
                go.Scatter(
                    x=[s_row["date_str"]],
                    y=[sell_price if sell_price else s_row["close_price"]],
                    mode="markers+text",
                    name="매도타점",
                    text=["매도"],
                    textposition="top center",
                    marker=dict(symbol="x", size=12, color="blue"),
                ),
                row=1,
                col=1,
            )

        # --- Row 2: 거래량 (가운데) ---
        colors = [
            "#d62728" if c >= o else "#1f77b4"
            for c, o in zip(df_stock["close_price"], df_stock["open_price"])
        ]
        fig.add_trace(
            go.Bar(
                x=df_stock["date_str"],
                y=df_stock["volume"],
                name="거래량",
                marker_color=colors,
            ),
            row=2,
            col=1,
        )

        # --- Row 3: 최하단 지수 차트 (거래량 아래) ---
        if not df_index.empty:
            # 지수 종가
            fig.add_trace(
                go.Scatter(
                    x=df_index["date_str"],
                    y=df_index["close_price"],
                    mode="lines",
                    name=f"{index_name} 종가",
                    line=dict(color="#9467bd", width=2),
                ),
                row=3,
                col=1,
            )

            # 지수 MA20
            if "ma20" in df_index.columns and df_index["ma20"].notna().any():
                fig.add_trace(
                    go.Scatter(
                        x=df_index["date_str"],
                        y=df_index["ma20"],
                        mode="lines",
                        name="지수 MA20",
                        line=dict(color="#ff7f0e", width=1.2, dash="dash"),
                    ),
                    row=3,
                    col=1,
                )

            # 지수 MA50
            if "ma50" in df_index.columns and df_index["ma50"].notna().any():
                fig.add_trace(
                    go.Scatter(
                        x=df_index["date_str"],
                        y=df_index["ma50"],
                        mode="lines",
                        name="지수 MA50",
                        line=dict(color="#2ca02c", width=1.2, dash="dot"),
                    ),
                    row=3,
                    col=1,
                )

            # 지수 MA200
            if "ma200" in df_index.columns and df_index["ma200"].notna().any():
                fig.add_trace(
                    go.Scatter(
                        x=df_index["date_str"],
                        y=df_index["ma200"],
                        mode="lines",
                        name="지수 MA200",
                        line=dict(color="#d62728", width=1.2, dash="dashdot"),
                    ),
                    row=3,
                    col=1,
                )

        # 레이아웃 설정
        fig.update_layout(
            height=720,
            margin=dict(l=20, r=20, t=40, b=20),
            xaxis_rangeslider_visible=False,
            xaxis3=dict(type="category", tickangle=-45),
            legend=dict(
                orientation="h",
                yanchor="bottom",
                y=1.01,
                xanchor="right",
                x=1,
            ),
        )

        # Y축 스케일 설정
        fig.update_yaxes(autorange=True, fixedrange=False, row=1, col=1)
        fig.update_yaxes(autorange=True, fixedrange=False, row=2, col=1)
        fig.update_yaxes(autorange=True, fixedrange=False, row=3, col=1)

        st.plotly_chart(fig, use_container_width=True)

    except Exception as e:
        st.error(f"통합 차트 그리기 오류: {e}")


def draw_attribution_charts(df_hist, market_type):
    """성과 분석 탭용 수익 기여도 시각화 차트"""
    if df_hist.empty:
        return

    profit_by_stock = (
        df_hist.groupby("종목명")["profit_amount"]
        .sum()
        .reset_index()
        .sort_values("profit_amount", ascending=False)
    )

    fmt_unit = "$" if market_type == "US" else "원"

    fig_bar = go.Figure()
    fig_bar.add_trace(
        go.Bar(
            x=profit_by_stock["종목명"],
            y=profit_by_stock["profit_amount"],
            marker_color=[
                "#d62728" if v > 0 else "#1f77b4"
                for v in profit_by_stock["profit_amount"]
            ],
            text=[f"{v:+,.0f}{fmt_unit}" for v in profit_by_stock["profit_amount"]],
            textposition="auto",
        )
    )
    fig_bar.update_layout(
        title="종목별 누적 실현 손익 기여도",
        height=300,
        margin=dict(l=20, r=20, t=40, b=20),
        xaxis=dict(tickangle=-45),
    )

    st.plotly_chart(fig_bar, use_container_width=True)
