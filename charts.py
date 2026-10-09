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
    """개별 종목 기술적 차트 + 거래량 + 최하단 지수 차트 통합 차트"""
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

        # 2. 시장 지수 시계열 데이터 조회 (최근 150영업일)
        res_index = (
            supabase.table("daily_analysis")
            .select("price_date, close_price, ma20, ma50, ma200")
            .eq("ticker", index_symbol)
            .order("price_date", desc=True)
            .limit(150)
            .execute()
        )

        if not res_stock.data:
            st.warning(f"[{ticker}] 종목의 차트 데이터가 존재하지 않습니다.")
            return

        # --- 종목 데이터 전처리 ---
        df_stock = pd.DataFrame(res_stock.data)
        df_stock["price_date_dt"] = pd.to_datetime(df_stock["price_date"])
        df_stock = df_stock.sort_values("price_date_dt").reset_index(drop=True)

        for col in ["close_price", "open_price", "high_price", "low_price", "volume", "ma20", "ma50", "ma200"]:
            if col in df_stock.columns:
                df_stock[col] = pd.to_numeric(df_stock[col], errors="coerce")

        df_stock = df_stock[
            (df_stock["close_price"] > 0) &
            (df_stock["open_price"] > 0) &
            (df_stock["high_price"] > 0) &
            (df_stock["low_price"] > 0)
        ].reset_index(drop=True)

        df_stock["date_str"] = df_stock["price_date_dt"].dt.strftime("%Y-%m-%d")

        # --- 지수 데이터 전처리 ---
        df_index = pd.DataFrame(res_index.data) if res_index.data else pd.DataFrame()
        if not df_index.empty:
            df_index["price_date_dt"] = pd.to_datetime(df_index["price_date"])
            df_index = df_index.sort_values("price_date_dt").reset_index(drop=True)
            for col in ["close_price", "ma20", "ma50", "ma200"]:
                if col in df_index.columns:
                    df_index[col] = pd.to_numeric(df_index[col], errors="coerce")
            
            df_merged = pd.merge(
                df_stock[["price_date", "date_str"]],
                df_index[["price_date", "close_price", "ma20", "ma50", "ma200"]],
                on="price_date",
                how="left"
            )
        else:
            df_merged = pd.DataFrame()

        # 📌 3개 행 서브플롯 생성
        fig = make_subplots(
            rows=3,
            cols=1,
            shared_xaxes=True,
            vertical_spacing=0.06,
            row_heights=[0.50, 0.18, 0.32],
            subplot_titles=(
                f"[{ticker}] {stock_name} 주가 추이",
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

        if "ma20" in df_stock.columns and df_stock["ma20"].notna().any():
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

        # --- Row 2: 거래량 ---
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
                showlegend=False,
            ),
            row=2,
            col=1,
        )

        # --- Row 3: 최하단 지수 차트 ---
        if not df_merged.empty:
            fig.add_trace(
                go.Scatter(
                    x=df_merged["date_str"],
                    y=df_merged["close_price"],
                    mode="lines",
                    name="지수종가",
                    line=dict(color="#9467bd", width=2),
                    connectgaps=True,
                ),
                row=3,
                col=1,
            )

            if "ma20" in df_merged.columns and df_merged["ma20"].notna().any():
                fig.add_trace(
                    go.Scatter(
                        x=df_merged["date_str"],
                        y=df_merged["ma20"],
                        mode="lines",
                        name="지수 MA20",
                        line=dict(color="#ff7f0e", width=1.2, dash="dash"),
                        showlegend=False,
                        connectgaps=True,
                    ),
                    row=3,
                    col=1,
                )

            if "ma50" in df_merged.columns and df_merged["ma50"].notna().any():
                fig.add_trace(
                    go.Scatter(
                        x=df_merged["date_str"],
                        y=df_merged["ma50"],
                        mode="lines",
                        name="지수 MA50",
                        line=dict(color="#2ca02c", width=1.2, dash="dot"),
                        showlegend=False,
                        connectgaps=True,
                    ),
                    row=3,
                    col=1,
                )

            if "ma200" in df_merged.columns and df_merged["ma200"].notna().any():
                fig.add_trace(
                    go.Scatter(
                        x=df_merged["date_str"],
                        y=df_merged["ma200"],
                        mode="lines",
                        name="지수 MA200",
                        line=dict(color="#d62728", width=1.2, dash="dashdot"),
                        showlegend=False,
                        connectgaps=True,
                    ),
                    row=3,
                    col=1,
                )

        # 📌 전체 차트를 관통하는 관통 세로 점선 설정 (shapes)
        v_shapes = []

        # 1. 수급 포착 세로 점선 (초록색 점선)
        if supply_dates:
            supp_df = df_stock[df_stock["price_date"].isin(supply_dates)]
            for _, s_row in supp_df.iterrows():
                v_shapes.append(
                    dict(
                        type="line",
                        xref="x",
                        yref="paper",
                        x0=s_row["date_str"],
                        x1=s_row["date_str"],
                        y0=0,
                        y1=1,
                        line=dict(color="#2e7d32", width=1.5, dash="dash"),
                    )
                )

        # 2. 매수 타점 세로 점선 (빨간색 점선)
        if buy_date and buy_date in df_stock["price_date"].values:
            b_row = df_stock[df_stock["price_date"] == buy_date].iloc[0]
            v_shapes.append(
                dict(
                    type="line",
                    xref="x",
                    yref="paper",
                    x0=b_row["date_str"],
                    x1=b_row["date_str"],
                    y0=0,
                    y1=1,
                    line=dict(color="#d62728", width=2, dash="dash"),
                )
            )

        # 3. 매도 타점 세로 점선 (파란색 점선)
        if sell_date and sell_date in df_stock["price_date"].values:
            s_row = df_stock[df_stock["price_date"] == sell_date].iloc[0]
            v_shapes.append(
                dict(
                    type="line",
                    xref="x",
                    yref="paper",
                    x0=s_row["date_str"],
                    x1=s_row["date_str"],
                    y0=0,
                    y1=1,
                    line=dict(color="#1f77b4", width=2, dash="dash"),
                )
            )

        # 레이아웃 설정
        fig.update_layout(
            height=850,
            margin=dict(l=10, r=10, t=60, b=20),
            xaxis_rangeslider_visible=False,
            shapes=v_shapes,  # 관통 세로선 적용
            legend=dict(
                orientation="h",
                yanchor="bottom",
                y=1.06,
                xanchor="center",
                x=0.5,
                font=dict(size=11),
            ),
        )

        fig.update_xaxes(type="category", tickangle=-45)
        fig.update_yaxes(autorange=True, fixedrange=False, row=1, col=1)
        fig.update_yaxes(autorange=True, fixedrange=False, row=2, col=1)
        fig.update_yaxes(autorange=True, fixedrange=False, row=3, col=1)

        st.plotly_chart(fig, use_container_width=True)

    except Exception as e:
        st.error(f"통합 차트 그리기 오류: {e}")


def draw_attribution_charts(df_hist, market_type):
    """성과 분석 탭용 수익 기여도 막대 그래프 + 수익률/보유기간 분포도(산점도)"""
    if df_hist.empty:
        return

    fmt_unit = "$" if market_type == "US" else "원"

    col_chart1, col_chart2 = st.columns(2)

    with col_chart1:
        profit_by_stock = (
            df_hist.groupby("종목명")["profit_amount"]
            .sum()
            .reset_index()
            .sort_values("profit_amount", ascending=False)
        )

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
            height=360,
            margin=dict(l=20, r=20, t=40, b=20),
            xaxis=dict(tickangle=-45),
        )
        st.plotly_chart(fig_bar, use_container_width=True)

    with col_chart2:
        fig_scatter = go.Figure()

        df_hist["holding_days_val"] = pd.to_numeric(df_hist.get("holding_days", 0), errors="coerce").fillna(0)
        df_hist["profit_rate_val"] = pd.to_numeric(df_hist.get("profit_rate", 0), errors="coerce").fillna(0)

        fig_scatter.add_trace(
            go.Scatter(
                x=df_hist["holding_days_val"],
                y=df_hist["profit_rate_val"],
                mode="markers",
                marker=dict(
                    size=10,
                    color=["#d62728" if r > 0 else "#1f77b4" for r in df_hist["profit_rate_val"]],
                    line=dict(width=1, color="DarkSlateGrey")
                ),
                text=df_hist["종목명"],
                hovertemplate="<b>%{text}</b><br>보유일수: %{x}일<br>수익률: %{y:+.2f}%<extra></extra>",
            )
        )
        fig_scatter.add_hline(y=0, line_dash="dash", line_color="gray")

        fig_scatter.update_layout(
            title="보유기간 대비 수익률 분포도",
            xaxis_title="보유일수 (일)",
            yaxis_title="수익률 (%)",
            height=360,
            margin=dict(l=20, r=20, t=40, b=20),
        )
        st.plotly_chart(fig_scatter, use_container_width=True)
