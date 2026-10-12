import pandas as pd
import plotly.graph_objects as gg
from plotly.subplots import make_subplots
import streamlit as st
from db import supabase


def draw_integrated_chart(
    ticker,
    market_type,
    ticker_name_map,
    buy_date=None,
    sell_date=None,
    supply_dates=None,
):
    try:
        # DB에서 시계열 데이터 조회 (최신 120일)
        res = (
            supabase.table("daily_analysis")
            .select("*")
            .eq("ticker", ticker)
            .order("price_date", desc=True)
            .limit(120)
            .execute()
        )
        if not res.data:
            st.info(f"[{ticker}] 차트 시계열 데이터가 존재하지 않습니다.")
            return

        df = pd.DataFrame(res.data)
        df["price_date_dt"] = pd.to_datetime(df["price_date"])
        df = df.sort_values("price_date_dt").reset_index(drop=True)

        # 📌 데이터 원본(price_date)은 YYYY-MM-DD 유지, 시각화 전용 X축 컬럼만 MM-DD로 가공
        df["date_display"] = df["price_date_dt"].dt.strftime("%m-%d")

        # 수치형 변환
        for col in ["close_price", "ma20", "ma50", "ma200"]:
            if col in df.columns:
                df[col] = pd.to_numeric(df[col], errors="coerce")

        stock_name = ticker_name_map.get(ticker, ticker)

        # 서브플롯 생성 (상단: 주가 및 이동평균선, 하단: 거래량)
        fig = make_subplots(
            rows=2,
            cols=1,
            shared_xaxes=True,
            vertical_spacing=0.03,
            row_heights=[0.75, 0.25],
        )

        # 1) 주가 추이 (종가) - X축에 date_display 사용
        fig.add_trace(
            gg.Scatter(
                x=df["date_display"],
                y=df["close_price"],
                mode="lines",
                name="주가",
                line=dict(color="#2962FF", width=2),
            ),
            row=1,
            col=1,
        )

        # 2) 이동평균선 추가
        if "ma20" in df.columns and df["ma20"].notna().any():
            fig.add_trace(
                gg.Scatter(
                    x=df["date_display"],
                    y=df["ma20"],
                    mode="lines",
                    name="MA20",
                    line=dict(color="#FF6D00", width=1.2, dash="dash"),
                ),
                row=1,
                col=1,
            )
        if "ma50" in df.columns and df["ma50"].notna().any():
            fig.add_trace(
                gg.Scatter(
                    x=df["date_display"],
                    y=df["ma50"],
                    mode="lines",
                    name="MA50",
                    line=dict(color="#00C853", width=1.2, dash="dot"),
                ),
                row=1,
                col=1,
            )
        if "ma200" in df.columns and df["ma200"].notna().any():
            fig.add_trace(
                gg.Scatter(
                    x=df["date_display"],
                    y=df["ma200"],
                    mode="lines",
                    name="MA200",
                    line=dict(color="#D50000", width=1.2, dash="dashdot"),
                ),
                row=1,
                col=1,
            )

        # 3) 매수/매도 복기 타점 표시 (지정된 경우)
        if buy_date:
            buy_dt = pd.to_datetime(buy_date).strftime("%m-%d")
            buy_row = df[df["date_display"] == buy_dt]
            if not buy_row.empty:
                fig.add_trace(
                    gg.Scatter(
                        x=[buy_dt],
                        y=[buy_row["close_price"].values[0]],
                        mode="markers+text",
                        name="매수 타점",
                        marker=dict(symbol="triangle-up", size=14, color="red"),
                        text=["매수"],
                        textposition="bottom center",
                    ),
                    row=1,
                    col=1,
                )

        if sell_date:
            sell_dt = pd.to_datetime(sell_date).strftime("%m-%d")
            sell_row = df[df["date_display"] == sell_dt]
            if not sell_row.empty:
                fig.add_trace(
                    gg.Scatter(
                        x=[sell_dt],
                        y=[sell_row["close_price"].values[0]],
                        mode="markers+text",
                        name="매도 타점",
                        marker=dict(
                            symbol="triangle-down", size=14, color="blue"
                        ),
                        text=["매도"],
                        textposition="top center",
                    ),
                    row=1,
                    col=1,
                )

        # 4) 거래량 차트 (하단)
        if "volume" in df.columns:
            df["volume"] = pd.to_numeric(df["volume"], errors="coerce")
            fig.add_trace(
                gg.Bar(
                    x=df["date_display"],
                    y=df["volume"],
                    name="거래량",
                    marker_color="#78909C",
                ),
                row=2,
                col=1,
            )

        # 📌 X축 레이아웃 최적화 (텍스트 직각, fixedrange 적용)
        fig.update_xaxes(type="category", tickangle=0, fixedrange=True)
        fig.update_yaxes(fixedrange=True)

        fig.update_layout(
            title=f"[{ticker}] {stock_name} 기술적 차트",
            height=420,
            margin=dict(l=10, r=10, t=35, b=10),
            legend=dict(
                orientation="h",
                yanchor="bottom",
                y=1.02,
                xanchor="right",
                x=1,
            ),
            hovermode="x unified",
        )

        st.plotly_chart(
            fig, use_container_width=True, config={"scrollZoom": False}
        )

    except Exception as e:
        st.error(f"차트 출력 중 오류 발생: {e}")


def draw_attribution_charts(df_hist, market_type):
    if df_hist.empty:
        return

    df_h = df_hist.copy()
    df_h["sell_date_dt"] = pd.to_datetime(df_h["sell_date"])
    df_h = df_h.sort_values("sell_date_dt").reset_index(drop=True)

    # 📌 시각화 직전에만 MM-DD 변환
    df_h["date_display"] = df_h["sell_date_dt"].dt.strftime("%m-%d")
    df_h["cum_profit"] = df_h["profit_amount"].cumsum()

    fig = make_subplots(
        rows=1,
        cols=2,
        subplot_titles=("누적 실현 손익 추이", "종목별 손익 기여도"),
    )

    # 1) 누적 손익 꺾은선 차트
    fig.add_trace(
        gg.Scatter(
            x=df_h["date_display"],
            y=df_h["cum_profit"],
            mode="lines+markers",
            name="누적 손익",
            line=dict(color="#2962FF", width=2),
        ),
        row=1,
        col=1,
    )

    # 2) 종목별 손익 바 차트
    colors = [
        "#D50000" if v < 0 else "#2E7D32" for v in df_h["profit_amount"]
    ]
    fig.add_trace(
        gg.Bar(
            x=df_h["종목명"],
            y=df_h["profit_amount"],
            name="건별 손익",
            marker_color=colors,
        ),
        row=1,
        col=2,
    )

    fig.update_xaxes(fixedrange=True, tickangle=0)
    fig.update_yaxes(fixedrange=True)

    fig.update_layout(
        height=300,
        margin=dict(l=10, r=10, t=30, b=10),
        showlegend=False,
    )

    st.plotly_chart(fig, use_container_width=True, config={"scrollZoom": False})
