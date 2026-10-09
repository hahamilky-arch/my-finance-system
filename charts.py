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
    개별 종목 및 지수/거래량 통합 기술적 차트 (3단 vconcat)
    - 1단: 종목 주가 + MA20 + 모멘텀 순위(우측 Y축)
    - 2단: 시장 지수 (^KS11 코스피 또는 ^GSPC S&P500) 추세 및 MA20
    - 3단: 거래량 (Volume)
    """
    ticker_name_map = ticker_name_map or {}
    
    # 1. DB 개별 종목 시계열 조회
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
    
    # 날짜 포맷 표준화
    df_chart["date_str"] = df_chart["price_date"].dt.strftime("%Y-%m-%d")
    df_chart["close_price"] = pd.to_numeric(df_chart["close_price"], errors="coerce")
    df_chart["volume"] = pd.to_numeric(df_chart["volume"], errors="coerce").fillna(0)
    df_chart["ma20"] = pd.to_numeric(df_chart["ma20"], errors="coerce")
    df_chart.loc[df_chart["ma20"] == 0, "ma20"] = None

    # 2. 시장 지수 데이터 조회 (^KS11 및 ^GSPC 대응)
    index_display_name = "코스피 (^KS11)" if market_type == "KR" else "S&P 500 (^GSPC)"
    try:
        idx_res = (
            supabase.table("market_regime")
            .select("*")
            .order("trade_date", desc=True)
            .limit(300)
            .execute()
        )
        if idx_res.data:
            df_idx = pd.DataFrame(idx_res.data)
            
            # DB 심볼 매칭 기준 (^KS11 및 ^GSPC)
            target_keys = ["^KS11", "KOSPI", "KOSPI200"] if market_type == "KR" else ["^GSPC", "SP500", "S&P500", "SPY"]
            
            idx_col = "index_name" if "index_name" in df_idx.columns else ("ticker" if "ticker" in df_idx.columns else None)
            
            if idx_col:
                df_idx = df_idx[df_idx[idx_col].astype(str).str.upper().isin(target_keys)]
            
            if not df_idx.empty:
                df_idx["date_str"] = pd.to_datetime(df_idx["trade_date"]).dt.strftime("%Y-%m-%d")
                close_col = "index_close" if "index_close" in df_idx.columns else "close_price"
                df_idx["index_close"] = pd.to_numeric(df_idx[close_col], errors="coerce")
                
                if "ma20" in df_idx.columns:
                    df_idx["index_ma20"] = pd.to_numeric(df_idx["ma20"], errors="coerce")
                else:
                    df_idx["index_ma20"] = None

                df_chart = pd.merge(
                    df_chart,
                    df_idx[["date_str", "index_close", "index_ma20"]].drop_duplicates("date_str"),
                    on="date_str",
                    how="left",
                )
            else:
                df_chart["index_close"] = None
                df_chart["index_ma20"] = None
        else:
            df_chart["index_close"] = None
            df_chart["index_ma20"] = None
    except Exception as e:
        print(f"지수 데이터 조인 실패: {e}")
        df_chart["index_close"] = None
        df_chart["index_ma20"] = None

    stock_name = ticker_name_map.get(selected_chart_ticker, selected_chart_ticker)

    # 공유 X축
    x_scale_ordinal = alt.X("date_str:N", title=None, axis=alt.Axis(labelAngle=-45, tickCount=10))

    # 우측 Y축 보정용 더미
    dummy_right_axis = (
        alt.Chart(df_chart)
        .mark_line(opacity=0)
        .encode(
            x=x_scale_ordinal,
            y=alt.Y("momentum_rank:Q", title=None, axis=alt.Axis(orient="right", labels=False, ticks=False, titlePadding=10)),
        )
    )

    # 1단: 종목 주가 & MA20 & 순위
    area_stock = alt.Chart(df_chart).mark_area(color="#87CEEB", opacity=0.15).encode(
        x=x_scale_ordinal, y=alt.Y("close_price:Q", title="주가", scale=alt.Scale(zero=False, padding=15))
    )
    line_stock = alt.Chart(df_chart).mark_line(color="#00BFFF", strokeWidth=2.5).encode(
        x=x_scale_ordinal, y=alt.Y("close_price:Q", title="주가", scale=alt.Scale(zero=False, padding=15)),
        tooltip=[
            alt.Tooltip("date_str:N", title="날짜"),
            alt.Tooltip("close_price:Q", title="종가", format=",.2f" if market_type == "US" else ",.0f"),
            alt.Tooltip("volume:Q", title="거래량", format=",.0f"),
        ]
    )
    line_ma20 = alt.Chart(df_chart).mark_line(color="#ff7f0e", strokeDash=[4, 4], strokeWidth=1.5).encode(
        x=x_scale_ordinal, y=alt.Y("ma20:Q", title=None, scale=alt.Scale(zero=False, padding=15))
    )
    line_rank = alt.Chart(df_chart).mark_line(color="#808080", opacity=0.3, strokeWidth=1.2).encode(
        x=x_scale_ordinal,
        y=alt.Y("momentum_rank:Q", title="순위", scale=alt.Scale(domain=[100, 1], clamp=True), axis=alt.Axis(orient="right", titlePadding=10, tickCount=5)),
        tooltip=[alt.Tooltip("date_str:N", title="날짜"), alt.Tooltip("momentum_rank:Q", title="모멘텀 순위")]
    )

    chart_price = alt.layer(area_stock, line_stock, line_ma20)

    if supply_dates:
        valid_supply_dates = [str(d) for d in supply_dates if str(d) in df_chart["date_str"].values]
        if valid_supply_dates:
            df_supply_chart = df_chart[df_chart["date_str"].isin(valid_supply_dates)].copy()
            rule_supply = alt.Chart(df_supply_chart).mark_rule(color="#ff9800", strokeWidth=1, strokeDash=[2, 2], opacity=0.8).encode(x=x_scale_ordinal)
            chart_price = alt.layer(chart_price, rule_supply)

    trade_elements = []
    if buy_date and str(buy_date) in df_chart["date_str"].values:
        df_buy = pd.DataFrame([{"date_str": str(buy_date), "price": float(buy_price) if buy_price else df_chart["close_price"].mean()}])
        trade_elements.extend([
            alt.Chart(df_buy).mark_rule(color="#d62728", strokeWidth=1.5, strokeDash=[3, 3]).encode(x="date_str:N"),
            alt.Chart(df_buy).mark_point(shape="triangle-up", size=150, color="#d62728", filled=True).encode(x="date_str:N", y="price:Q")
        ])
    if sell_date and str(sell_date) in df_chart["date_str"].values:
        df_sell = pd.DataFrame([{"date_str": str(sell_date), "price": float(sell_price) if sell_price else df_chart["close_price"].mean()}])
        trade_elements.extend([
            alt.Chart(df_sell).mark_rule(color="#1f77b4", strokeWidth=1.5, strokeDash=[3, 3]).encode(x="date_str:N"),
            alt.Chart(df_sell).mark_point(shape="triangle-down", size=150, color="#1f77b4", filled=True).encode(x="date_str:N", y="price:Q")
        ])

    if trade_elements:
        chart_price = alt.layer(chart_price, *trade_elements)

    chart_top = alt.layer(chart_price, line_rank).resolve_scale(y="independent").properties(height=260)

    # 2단: 지수 추세 차트 (보라색 선)
    line_idx_main = alt.Chart(df_chart).mark_line(color="#9467bd", strokeWidth=1.8).encode(
        x=x_scale_ordinal,
        y=alt.Y("index_close:Q", title=f"지수", scale=alt.Scale(zero=False)),
        tooltip=[alt.Tooltip("date_str:N", title="날짜"), alt.Tooltip("index_close:Q", title=f"{index_display_name}", format=",.2f")]
    )
    line_idx_ma = alt.Chart(df_chart).mark_line(color="#ff7f0e", strokeDash=[3, 3], strokeWidth=1.2).encode(
        x=x_scale_ordinal, y=alt.Y("index_ma20:Q", title=None, scale=alt.Scale(zero=False))
    )
    chart_middle = alt.layer(line_idx_main, line_idx_ma, dummy_right_axis).resolve_scale(y="independent").properties(height=110)

    # 3단: 거래량 바 차트
    bar_volume = alt.Chart(df_chart).mark_bar(color="#87CEFA", opacity=0.7).encode(
        x=x_scale_ordinal,
        y=alt.Y("volume:Q", title="거래량", axis=alt.Axis(format="~s")),
        tooltip=[alt.Tooltip("date_str:N", title="날짜"), alt.Tooltip("volume:Q", title="거래량", format=",.0f")]
    )
    chart_bottom = alt.layer(bar_volume, dummy_right_axis).resolve_scale(y="independent").properties(height=100)

    # 3단 통합 vconcat 결합
    combined_chart = alt.vconcat(chart_top, chart_middle, chart_bottom).resolve_scale(x="shared").configure_concat(spacing=12)

    legend_text = f"[{stock_name}] 하늘색 주가 추세선 | --- MA20 | ━ 모멘텀 순위 | 보라색 {index_display_name} 지수선"
    if supply_dates:
        legend_text += " | --- 수급 유입일"
    if buy_date or sell_date:
        legend_text += " | ▲ 🔴 매수타점 | ▼ 🔵 매도타점"

    st.caption(legend_text)
    st.altair_chart(combined_chart, use_container_width=True)


def draw_attribution_charts(df_hist, market_type="KR"):
    if df_hist.empty:
        return

    df_grouped = df_hist.groupby(["ticker", "종목명"])["profit_amount"].sum().reset_index()
    top5 = df_grouped.nlargest(5, "profit_amount")
    worst5 = df_grouped.nsmallest(5, "profit_amount")

    df_top_worst = pd.concat([top5, worst5]).drop_duplicates()
    df_top_worst["color"] = df_top_worst["profit_amount"].apply(lambda x: "#00BFFF" if x > 0 else "#d62728")
    df_top_worst["display_name"] = df_top_worst.apply(lambda r: f"{r['종목명']} ({r['ticker']})", axis=1)

    bar_chart = alt.Chart(df_top_worst).mark_bar().encode(
        y=alt.Y("display_name:N", sort=alt.EncodingSortField(field="profit_amount", order="descending"), title=None),
        x=alt.X("profit_amount:Q", title="총 실현 손익"),
        color=alt.Color("color:N", scale=None),
        tooltip=[alt.Tooltip("display_name:N", title="종목"), alt.Tooltip("profit_amount:Q", title="손익", format=",.0f" if market_type == "KR" else ",.2f")]
    ).properties(height=260, title="기여도 Top 5 & Worst 5")

    scatter_chart = alt.Chart(df_hist).mark_circle(size=60, opacity=0.6).encode(
        x=alt.X("holding_days:Q", title="보유 기간 (일)"),
        y=alt.Y("profit_rate:Q", title="수익률 (%)", scale=alt.Scale(zero=True)),
        color=alt.condition(alt.datum.profit_rate > 0, alt.value("#00BFFF"), alt.value("#d62728")),
        tooltip=[
            alt.Tooltip("종목명:N", title="종목"),
            alt.Tooltip("holding_days:Q", title="보유일수"),
            alt.Tooltip("profit_rate:Q", title="수익률(%)", format=".2f"),
            alt.Tooltip("profit_amount:Q", title="손익", format=",.0f" if market_type == "KR" else ",.2f")
        ]
    ).properties(height=260, title="보유 기간 대비 수익률 분포")

    col1, col2 = st.columns(2)
    with col1:
        st.altair_chart(bar_chart, use_container_width=True)
    with col2:
        st.altair_chart(scatter_chart, use_container_width=True)
