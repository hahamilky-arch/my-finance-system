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
        # 📌 1. DB에서 최근 120영업일 시계열 데이터 조회
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

        # 수치형 변환
        for col in ["close_price", "ma20", "ma50", "ma200", "volume", "mot", "rs_90", "rank"]:
            if col in df.columns:
                df[col] = pd.to_numeric(df[col], errors="coerce")

        stock_name = ticker_name_map.get(ticker, ticker)
        latest_row = df.iloc[-1]

        # 📌 2. 최신 모멘텀/순위 지표 헤더 캡션 생성
        rank_val = int(latest_row.get("rank", 0)) if pd.notna(latest_row.get("rank")) else "-"
        mot_val = float(latest_row.get("mot", 0.0)) if pd.notna(latest_row.get("mot")) else 0.0
        rs90_val = float(latest_row.get("rs_90", 0.0)) if pd.notna(latest_row.get("rs_90")) else 0.0

        st.caption(
            f"📊 **[{ticker}] {stock_name}** | 최신 모멘텀 순위: **{rank_val}위** | MOT: **{mot_val:.2f}** | RS(90): **{rs90_val:.2f}**"
        )

        # 📌 3. 서브플롯 생성 (상단 75%: 주가/이동평균선/타점/수급일, 하단 25%: 거래량)
        fig = make_subplots(
            rows=2,
            cols=1,
            shared_xaxes=True,
            vertical_spacing=0.03,
            row_heights=[0.75, 0.25],
        )

        # 1) 주가 추이 (datetime 객체 직접 전달하여 X축 자동 간격 조절)
        fig.add_trace(
            gg.Scatter(
                x=df["price_date_dt"],
                y=df["close_price"],
                mode="lines",
                name="주가",
                line=dict(color="#2962FF", width=2),
            ),
            row=1,
            col=1,
        )

        # 2) 이동평균선 (MA20, MA50, MA200)
        if "ma20" in df.columns and df["ma20"].notna().any():
            fig.add_trace(
                gg.Scatter(
                    x=df["price_date_dt"],
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
                    x=df["price_date_dt"],
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
                    x=df["price_date_dt"],
                    y=df["ma200"],
                    mode="lines",
                    name="MA200",
                    line=dict(color="#D50000", width=1.2, dash="dashdot"),
                ),
                row=1,
                col=1,
            )

        # 📌 4. 수급(외국인/기관 순매수) 포착일 세로선 표시
        if supply_dates:
            for s_date in supply_dates:
                s_dt = pd.to_datetime(s_date)
                if df["price_date_dt"].min() <= s_dt <= df["price_date_dt"].max():
                    fig.add_vline(
                        x=s_dt,
                        line_width=1,
                        line_dash="dot",
                        line_color="#AB47BC",
                        opacity=0.6,
                        row=1,
                        col=1,
                    )

        # 📌 5. 매수 / 매도 복기 타점 아이콘 표시
        if buy_date:
            buy_dt = pd.to_datetime(buy_date)
            buy_row = df[df["price_date_dt"] == buy_dt]
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
            sell_dt = pd.to_datetime(sell_date)
            sell_row = df[df["price_date_dt"] == sell_dt]
            if not sell_row.empty:
                fig.add_trace(
                    gg.Scatter(
                        x=[sell_dt],
                        y=[sell_row["close_price"].values[0]],
                        mode="markers+text",
                        name="매도 타점",
                        marker=dict(symbol="triangle-down", size=14, color="blue"),
                        text=["매도"],
                        textposition="top center",
                    ),
                    row=1,
                    col=1,
                )

        # 6) 하단 거래량 바 차트
        if "volume" in df.columns:
            fig.add_trace(
                gg.Bar(
                    x=df["price_date_dt"],
                    y=df["volume"],
                    name="거래량",
                    marker_color="#78909C",
                ),
                row=2,
                col=1,
            )

        # 📌 6. X축 날짜 겹침 방지 및 포맷 최적화 설정
        fig.update_xaxes(
            tickformat="%m-%d",  # X축 표시는 MM-DD 형식으로 유지
            nticks=8,            # 텍스트가 겹치지 않도록 적절히 8개 내외로 자동 솎아냄
            tickangle=0,
            fixedrange=True,
        )
        fig.update_yaxes(fixedrange=True)

        fig.update_layout(
            title=f"[{ticker}] {stock_name} 통합 기술적 차트",
            height=430,
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
    df_h["cum_profit"] = df_h["profit_amount"].cumsum()

    fig = make_subplots(
        rows=1,
        cols=2,
        subplot_titles=("누적 실현 손익 추이", "종목별 손익 기여도"),
    )

    # 1) 누적 손익 꺾은선 차트
    fig.add_trace(
        gg.Scatter(
            x=df_h["sell_date_dt"],
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

    fig.update_xaxes(
        tickformat="%m-%d",
        nticks=6,
        fixedrange=True,
        tickangle=0,
        row=1,
        col=1,
    )
    fig.update_xaxes(fixedrange=True, row=1, col=2)
    fig.update_yaxes(fixedrange=True)

    fig.update_layout(
        height=300,
        margin=dict(l=10, r=10, t=30, b=10),
        showlegend=False,
    )

    st.plotly_chart(fig, use_container_width=True, config={"scrollZoom": False})
