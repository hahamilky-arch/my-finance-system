import pandas as pd
import altair as alt
import streamlit as st
from db import supabase

def draw_integrated_chart(selected_chart_ticker, market_type, ticker_name_map):
    chart_res = supabase.table("daily_analysis") \
        .select("price_date, close_price, momentum_rank, ma20") \
        .eq("ticker", selected_chart_ticker).order("price_date", desc=True).limit(20).execute()
        
    benchmark_ticker = "^KS11" if market_type == "KR" else "^GSPC"
    index_res = supabase.table("daily_analysis") \
        .select("price_date, close_price, ma50") \
        .eq("ticker", benchmark_ticker).order("price_date", desc=True).limit(20).execute()
        
    if not chart_res.data:
        st.info("해당 종목의 시계열 차트 데이터가 존재하지 않습니다.")
        return

    df_chart = pd.DataFrame(chart_res.data)
    df_chart['price_date'] = pd.to_datetime(df_chart['price_date'])
    df_chart = df_chart.sort_values('price_date', ascending=True)
    df_chart['price_date_str'] = df_chart['price_date'].dt.strftime('%m-%d')
    df_chart['close_price'] = pd.to_numeric(df_chart['close_price'], errors='coerce')
    df_chart['ma20'] = pd.to_numeric(df_chart['ma20'], errors='coerce')
    df_chart.loc[df_chart['ma20'] == 0, 'ma20'] = None
    
    if index_res.data:
        df_idx_chart = pd.DataFrame(index_res.data).rename(columns={'close_price': 'index_price', 'ma50': 'index_ma50'})
        df_idx_chart['price_date'] = pd.to_datetime(df_idx_chart['price_date'])
        df_merged = pd.merge(df_chart, df_idx_chart, on='price_date', how='left')
    else:
        df_merged = df_chart
        df_merged['index_price'] = df_merged['index_ma50'] = None

    idx_name = "KOSPI" if market_type == "KR" else "S&P 500"
    stock_name = ticker_name_map.get(selected_chart_ticker, selected_chart_ticker)

    line_stock = alt.Chart(df_merged).mark_line(color='#1f77b4', strokeWidth=2.5).encode(
        x=alt.X('price_date_str:N', title=None, axis=alt.Axis(labelAngle=-45)),
        y=alt.Y('close_price:Q', title='주가', scale=alt.Scale(zero=False, padding=15)),
        tooltip=[alt.Tooltip('price_date_str:N', title='날짜'), alt.Tooltip('close_price:Q', title='종가', format=',.0f')]
    )

    line_ma20 = alt.Chart(df_merged).mark_line(color='#ff4b4b', strokeDash=[4, 4]).encode(
        x=alt.X('price_date_str:N', title=None),
        y=alt.Y('ma20:Q', title=None, scale=alt.Scale(zero=False, padding=15)) 
    )

    line_rank = alt.Chart(df_merged).mark_line(color='#ff7f0e', point=True).encode(
        x=alt.X('price_date_str:N', title=None),
        y=alt.Y('momentum_rank:Q', title='순위', scale=alt.Scale(domain=[100, 1], clamp=True), axis=alt.Axis(orient='right', titlePadding=10)),
        tooltip=[alt.Tooltip('momentum_rank:Q', title='모멘텀 순위')]
    )

    chart_top = alt.layer(line_stock, line_ma20, line_rank).resolve_scale(y='independent').properties(height=350)

    line_idx = alt.Chart(df_merged).mark_line(color='#2ca02c', strokeWidth=2).encode(
        x=alt.X('price_date_str:N', title=None, axis=alt.Axis(labelAngle=-45)),
        y=alt.Y('index_price:Q', title=f'{idx_name} 지수', scale=alt.Scale(zero=False, padding=10))
    )
    line_idx_ma50 = alt.Chart(df_merged).mark_line(color='#ff4b4b', strokeDash=[4, 4]).encode(
        x=alt.X('price_date_str:N', title=None),
        y=alt.Y('index_ma50:Q', title=None, scale=alt.Scale(zero=False, padding=10))
    )

    chart_bottom = alt.layer(line_idx, line_idx_ma50).resolve_scale(y='shared').properties(height=140)

    st.markdown(f"""
    <div style="text-align: center; margin-bottom: 10px; font-size: 0.9em; color: #555555;">
        <span style="color:#1f77b4; font-weight:bold;">━</span> {stock_name} 주가 | 
        <span style="color:#ff4b4b; font-weight:bold;">---</span> MA20 | 
        <span style="color:#ff7f0e; font-weight:bold;">━●━</span> 모멘텀 순위 (우측 Y축 반전)
    </div>
    """, unsafe_allow_html=True)
    st.altair_chart(chart_top, use_container_width=True)
    
    st.markdown(f"""
    <div style="text-align: center; margin-top: 5px; margin-bottom: 10px; font-size: 0.9em; color: #555555;">
        <span style="color:#2ca02c; font-weight:bold;">━</span> {idx_name} 지수 종가 | 
        <span style="color:#ff4b4b; font-weight:bold;">---</span> MA50
    </div>
    """, unsafe_allow_html=True)
    st.altair_chart(chart_bottom, use_container_width=True)
