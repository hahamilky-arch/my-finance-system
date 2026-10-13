import plotly.express as px
import plotly.graph_objects as gg
from plotly.subplots import make_subplots
import pandas as pd
import streamlit as st
from db import supabase


def draw_market_supply_chart(target_date_str):
    """
    1번 탭(시장 & 수급 종합) 전용: 시장 전체 주체별(외인/기관/개인) 및 프로그램(비차익) 매매동향 추이 차트
    """
    try:
        # 최근 60영업일 수급 시계열 데이터 조회
        res_inv = (
            supabase.table("market_investor_trends")
            .select("*")
            .lte("trade_date", target_date_str)
            .order("trade_date", desc=True)
            .limit(120)
            .execute()
        )
        res_prog = (
            supabase.table("market_program_trends")
            .select("*")
            .lte("trade_date", target_date_str)
            .order("trade_date", desc=True)
            .limit(60)
            .execute()
        )

        df_inv = pd.DataFrame(res_inv.data) if res_inv.data else pd.DataFrame()
        df_prog = pd.DataFrame(res_prog.data) if res_prog.data else pd.DataFrame()

        if df_inv.empty and df_prog.empty:
            st.info("시장에 대한 수급 추이 데이터가 존재하지 않습니다.")
            return

        # KOSPI 기준 주체별 동향 정리
        df_k = df_inv[df_inv["market_type"] == "KOSPI"].copy() if not df_inv.empty else pd.DataFrame()
        
        if not df_k.empty:
            df_k["trade_date_dt"] = pd.to_datetime(df_k["trade_date"])
            df_k = df_k.sort_values("trade_date_dt").reset_index(drop=True)
            
            for col in ["foreign_net", "institution_net", "individual_net"]:
                df_k[col] = pd.to_numeric(df_k[col], errors="coerce").fillna(0)
            
            df_k["foreign_cum"] = df_k["foreign_net"].cumsum()
            df_k["inst_cum"] = df_k["institution_net"].cumsum()
            df_k["ind_cum"] = df_k["individual_net"].cumsum()

        # 프로그램 동향 정리
        if not df_prog.empty:
            df_prog["trade_date_dt"] = pd.to_datetime(df_prog["trade_date"])
            df_prog = df_prog.sort_values("trade_date_dt").reset_index(drop=True)
            for col in ["non_arbitrage_net", "arbitrage_net", "total_net"]:
                if col in df_prog.columns:
                    df_prog[col] = pd.to_numeric(df_prog[col], errors="coerce").fillna(0)
                else:
                    df_prog[col] = 0.0
            df_prog["non_arb_cum"] = df_prog["non_arbitrage_net"].cumsum()

        # 2개 서브플롯 구성 (1행: 주체별 누적 수급, 2행: 프로그램 비차익 누적 수급)
        fig_m = make_subplots(
            rows=2,
            cols=1,
            shared_xaxes=True,
            vertical_spacing=0.08,
            subplot_titles=(
                "KOSPI 주체별 누적 매매 동향 (백만원)",
                "프로그램 비차익 누적 매매 동향 (백만원)",
            ),
        )

        if not df_k.empty:
            fig_m.add_trace(
                gg.Scatter(x=df_k["trade_date_dt"], y=df_k["foreign_cum"], mode="lines", name="외국인", line=dict(color="#d62728", width=2)),
                row=1, col=1
            )
            fig_m.add_trace(
                gg.Scatter(x=df_k["trade_date_dt"], y=df_k["inst_cum"], mode="lines", name="기관", line=dict(color="#2ca02c", width=2)),
                row=1, col=1
            )
            fig_m.add_trace(
                gg.Scatter(x=df_k["trade_date_dt"], y=df_k["ind_cum"], mode="lines", name="개인", line=dict(color="#1f77b4", width=1.5, dash="dot")),
                row=1, col=1
            )

        if not df_prog.empty:
            fig_m.add_trace(
                gg.Scatter(x=df_prog["trade_date_dt"], y=df_prog["non_arb_cum"], mode="lines", name="비차익 순매수", line=dict(color="#ff7f0e", width=2)),
                row=2, col=1
            )

        fig_m.update_xaxes(tickformat="%m-%d", nticks=8, fixedrange=True)
        fig_m.update_yaxes(fixedrange=True)
        fig_m.update_layout(
            height=380,
            margin=dict(l=10, r=10, t=30, b=10),
            legend=dict(orientation="h", yanchor="bottom", y=1.02, xanchor="right", x=1),
        )

        st.plotly_chart(fig_m, use_container_width=True, config={"scrollZoom": False})

    except Exception as e:
        st.error(f"수급 동향 차트 생성 중 오류: {e}")


def draw_integrated_chart(
    ticker,
    market_type="KR",
    ticker_name_map=None,
    buy_date=None,
    sell_date=None,
    supply_dates=None,
):
    """
    알파 시그널(2번 탭) 개별 종목 기술적 캔들/이평선 차트 (기존 원본 스펙 그대로 복원)
    """
    ticker_clean = str(ticker).strip().upper()
    stock_name = (
        ticker_name_map.get(ticker_clean, ticker_clean)
        if ticker_name_map
        else ticker_clean
    )

    try:
        # 최근 180영업일 일봉 데이터 조회
        res = (
            supabase.table("daily_analysis")
            .select("price_date, open_price, high_price, low_price, close_price, volume, ma20, ma50, ma200")
            .eq("ticker", ticker_clean)
            .order("price_date", desc=True)
            .limit(180)
            .execute()
        )
        if not res.data:
            st.info(f"[{ticker_clean}] 차트 데이터를 찾을 수 없습니다.")
            return

        df = pd.DataFrame(res.data)
        df["price_date_dt"] = pd.to_datetime(df["price_date"])
        df = df.sort_values("price_date_dt").reset_index(drop=True)

        for col in ["open_price", "high_price", "low_price", "close_price", "volume", "ma20", "ma50", "ma200"]:
            df[col] = pd.to_numeric(df[col], errors="coerce")

        # 서브플롯 구성: 1행(캔들/이평선/타점), 2행(거래량) - 기존 원본 2행 구조 복원
        fig = make_subplots(
            rows=2,
            cols=1,
            shared_xaxes=True,
            vertical_spacing=0.03,
            row_heights=[0.70, 0.30],
            subplot_titles=(
                f"[{stock_name} ({ticker_clean})] 주가 추이",
                "거래량",
            ),
        )

        # 1행: 캔들스틱 차트
        fig.add_trace(
            gg.Candlestick(
                x=df["price_date_dt"],
                open=df["open_price"],
                high=df["high_price"],
                low=df["low_price"],
                close=df["close_price"],
                name="주가",
                increasing_line_color="#d62728",
                decreasing_line_color="#1f77b4",
            ),
            row=1,
            col=1,
        )

        # 1행: 이동평균선 (MA20, MA50, MA200)
        if df["ma20"].notna().any():
            fig.add_trace(
                gg.Scatter(x=df["price_date_dt"], y=df["ma20"], mode="lines", name="MA20", line=dict(color="#ff7f0e", width=1.5)),
                row=1, col=1
            )
        if df["ma50"].notna().any():
            fig.add_trace(
                gg.Scatter(x=df["price_date_dt"], y=df["ma50"], mode="lines", name="MA50", line=dict(color="#2ca02c", width=1.5, dash="dot")),
                row=1, col=1
            )
        if df["ma200"].notna().any():
            fig.add_trace(
                gg.Scatter(x=df["price_date_dt"], y=df["ma200"], mode="lines", name="MA200", line=dict(color="#d62728", width=1.5, dash="dashdot")),
                row=1, col=1
            )

        # 타점 표기 (매수/매도일)
        if buy_date:
            b_dt = pd.to_datetime(buy_date)
            b_row = df[df["price_date_dt"] == b_dt]
            if not b_row.empty:
                fig.add_trace(
                    gg.Scatter(
                        x=[b_dt],
                        y=[b_row["low_price"].values[0] * 0.98],
                        mode="markers+text",
                        name="매수타점",
                        marker=dict(symbol="triangle-up", size=14, color="#2e7d32"),
                        text=["▲ 매수"],
                        textposition="bottom center",
                    ),
                    row=1, col=1
                )

        if sell_date:
            s_dt = pd.to_datetime(sell_date)
            s_row = df[df["price_date_dt"] == s_dt]
            if not s_row.empty:
                fig.add_trace(
                    gg.Scatter(
                        x=[s_dt],
                        y=[s_row["high_price"].values[0] * 1.02],
                        mode="markers+text",
                        name="매도타점",
                        marker=dict(symbol="triangle-down", size=14, color="#c62828"),
                        text=["▼ 매도"],
                        textposition="top center",
                    ),
                    row=1, col=1
                )

        # 2행: 거래량
        colors = ["#d62728" if c >= o else "#1f77b4" for c, o in zip(df["close_price"], df["open_price"])]
        fig.add_trace(
            gg.Bar(x=df["price_date_dt"], y=df["volume"], name="거래량", marker_color=colors, opacity=0.7),
            row=2, col=1
        )

        # 레이아웃 보정
        fig.update_xaxes(tickformat="%m-%d", nticks=10, fixedrange=True, rangeslider_visible=False)
        fig.update_yaxes(fixedrange=True)
        fig.update_layout(
            height=460,
            margin=dict(l=10, r=10, t=30, b=20),
            legend=dict(orientation="h", yanchor="bottom", y=1.02, xanchor="right", x=1),
        )

        st.plotly_chart(fig, use_container_width=True, config={"scrollZoom": False})

    except Exception as e:
        st.error(f"차트 출력 중 오류 발생: {e}")


def draw_attribution_charts(df_hist, market_type="KR"):
    """
    성과 분석(Tab 4) 누적 손익 및 종목별 손익 기여도 차트 시각화
    """
    if df_hist.empty:
        st.info("시각화할 매매 내역이 없습니다.")
        return

    df_h = df_hist.copy()
    df_h["sell_date_dt"] = pd.to_datetime(df_h["sell_date"])
    df_h = df_h.sort_values("sell_date_dt").reset_index(drop=True)
    df_h["cum_profit"] = df_h["profit_amount"].cumsum()

    col1, col2 = st.columns(2)

    with col1:
        # 누적 손익 추이 차트
        fig_cum = gg.Figure()
        fig_cum.add_trace(
            gg.Scatter(
                x=df_h["sell_date_dt"],
                y=df_h["cum_profit"],
                mode="lines+markers",
                name="누적 손익",
                line=dict(color="#2e7d32", width=2.5),
                fill="tozeroy",
                fillcolor="rgba(46, 125, 50, 0.1)",
            )
        )
        fig_cum.update_xaxes(tickformat="%m-%d", nticks=6, fixedrange=True)
        fig_cum.update_yaxes(fixedrange=True)
        fig_cum.update_layout(
            title="일자별 누적 실현 손익 추이",
            height=260,
            margin=dict(l=10, r=10, t=30, b=10),
        )
        st.plotly_chart(fig_cum, use_container_width=True, config={"scrollZoom": False})

    with col2:
        # 종목별 실현 손익 기여도 차트
        df_by_stock = (
            df_h.groupby("종목명")["profit_amount"]
            .sum()
            .reset_index()
            .sort_values("profit_amount", ascending=True)
        )
        colors = ["#2e7d32" if v >= 0 else "#c62828" for v in df_by_stock["profit_amount"]]

        fig_bar = gg.Figure()
        fig_bar.add_trace(
            gg.Bar(
                x=df_by_stock["profit_amount"],
                y=df_by_stock["종목명"],
                orientation="h",
                marker_color=colors,
            )
        )
        fig_bar.update_xaxes(fixedrange=True)
        fig_bar.update_yaxes(fixedrange=True)
        fig_bar.update_layout(
            title="종목별 손익 기여도",
            height=260,
            margin=dict(l=10, r=10, t=30, b=10),
        )
        st.plotly_chart(fig_bar, use_container_width=True, config={"scrollZoom": False})
