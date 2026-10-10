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
        # 1. 개별 종목 시계열 데이터 조회
        res_stock = (
            supabase.table("daily_analysis")
            .select("price_date, close_price, open_price, high_price, low_price, volume, ma20, ma50, ma200, momentum_rank")
            .eq("ticker", ticker)
            .order("price_date", desc=True)
            .limit(120)
            .execute()
        )

        # 2. 시장 지수 시계열 데이터 조회
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

        for col in ["close_price", "open_price", "high_price", "low_price", "volume", "ma20", "ma50", "ma200", "momentum_rank"]:
            if col in df_stock.columns:
                df_stock[col] = pd.to_numeric(df_stock[col], errors="coerce")

        df_stock = df_stock[
            (df_stock["close_price"] > 0) &
            (df_stock["open_price"] > 0) &
            (df_stock["high_price"] > 0) &
            (df_stock["low_price"] > 0)
        ].reset_index(drop=True)

        # 📌 x축 라벨용 YYYY-MM-DD 규격화 문자열 생성
        df_stock["date_str"] = df_stock["price_date_dt"].dt.strftime("%Y-%m-%d")

        latest_rank = "-"
        if "momentum_rank" in df_stock.columns and df_stock["momentum_rank"].notna().any():
            latest_rank_val = df_stock["momentum_rank"].iloc[-1]
            if pd.notna(latest_rank_val) and latest_rank_val > 0:
                latest_rank = f"{int(latest_rank_val)}위"

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
            vertical_spacing=0.05,
            row_heights=[0.52, 0.18, 0.30],
            subplot_titles=(
                f"[{ticker}] {stock_name} 주가 추이 (모멘텀 순위: {latest_rank})",
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
                increasing_line_color="#e53935" if market_type == "KR" else "#2e7d32",
                increasing_fillcolor="#e53935" if market_type == "KR" else "#2e7d32",
                decreasing_line_color="#1e88e5" if market_type == "KR" else "#e53935",
                decreasing_fillcolor="#1e88e5" if market_type == "KR" else "#e53935",
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
                    name="MA20 (20일선)",
                    line=dict(color="#f57c00", width=1.8),
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
                    name="MA50 (50일선)",
                    line=dict(color="#388e3c", width=1.4, dash="dash"),
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
                    name="MA200 (200일선)",
                    line=dict(color="#8e24aa", width=1.4, dash="dashdot"),
                ),
                row=1,
                col=1,
            )

        # --- Row 2: 거래량 ---
        colors = [
            "#e53935" if c >= o else "#1e88e5"
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
                    name="지수 종가",
                    line=dict(color="#5e35b1", width=1.8),
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
                        line=dict(color="#f57c00", width=1.2, dash="dash"),
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
                        line=dict(color="#388e3c", width=1.2, dash="dot"),
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
                        line=dict(color="#8e24aa", width=1.2, dash="dashdot"),
                        showlegend=False,
                        connectgaps=True,
                    ),
                    row=3,
                    col=1,
                )

        # 📌 세로 점선(shapes) 정확한 날짜 매칭 생성
        v_shapes = []

        # 1. 수급 포착 날짜 매칭 (YYYY-MM-DD 날짜 포맷 통일)
        if supply_dates:
            # supply_dates 리스트 내의 날짜들을 pd.to_datetime으로 표준 YYYY-MM-DD 스트링 변환
            clean_supp_dates = [pd.to_datetime(d).strftime("%Y-%m-%d") for d in supply_dates if pd.notna(d)]
            
            # 차트에 실제로 존재하는 날짜에만 세로선 생성
            supp_df = df_stock[df_stock["date_str"].isin(clean_supp_dates)]
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
                        line=dict(color="#2e7d32", width=1.2, dash="dash"),
                    )
                )

        # 2. 매수 타점 세로 점선
        if buy_date:
            clean_buy_date = pd.to_datetime(buy_date).strftime("%Y-%m-%d")
            if clean_buy_date in df_stock["date_str"].values:
                v_shapes.append(
                    dict(
                        type="line",
                        xref="x",
                        yref="paper",
                        x0=clean_buy_date,
                        x1=clean_buy_date,
                        y0=0,
                        y1=1,
                        line=dict(color="#e53935", width=1.8, dash="dash"),
                    )
                )

        # 3. 매도 타점 세로 점선
        if sell_date:
            clean_sell_date = pd.to_datetime(sell_date).strftime("%Y-%m-%d")
            if clean_sell_date in df_stock["date_str"].values:
                v_shapes.append(
                    dict(
                        type="line",
                        xref="x",
                        yref="paper",
                        x0=clean_sell_date,
                        x1=clean_sell_date,
                        y0=0,
                        y1=1,
                        line=dict(color="#1e88e5", width=1.8, dash="dash"),
                    )
                )

        # 레이아웃 스타일 설정
        fig.update_layout(
            height=850,
            margin=dict(l=10, r=10, t=60, b=20),
            xaxis_rangeslider_visible=False,
            shapes=v_shapes,
            legend=dict(
                orientation="h",
                yanchor="bottom",
                y=1.05,
                xanchor="center",
                x=0.5,
                font=dict(size=11),
            ),
            plot_bgcolor="#ffffff",
        )

        fig.update_xaxes(type="category", tickangle=-45, gridcolor="#f0f0f0")
        fig.update_yaxes(autorange=True, fixedrange=False, gridcolor="#f0f0f0", row=1, col=1)
        fig.update_yaxes(autorange=True, fixedrange=False, gridcolor="#f0f0f0", row=2, col=1)
        fig.update_yaxes(autorange=True, fixedrange=False, gridcolor="#f0f0f0", row=3, col=1)

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
                    "#e53935" if v > 0 else "#1e88e5"
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
            plot_bgcolor="#ffffff",
        )
        fig_bar.update_xaxes(gridcolor="#f0f0f0")
        fig_bar.update_yaxes(gridcolor="#f0f0f0")
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
                    color=["#e53935" if r > 0 else "#1e88e5" for r in df_hist["profit_rate_val"]],
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
            plot_bgcolor="#ffffff",
        )
        fig_scatter.update_xaxes(gridcolor="#f0f0f0")
        fig_scatter.update_yaxes(gridcolor="#f0f0f0")
        st.plotly_chart(fig_scatter, use_container_width=True)
