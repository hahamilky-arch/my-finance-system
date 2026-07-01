import streamlit as st
import pandas as pd
import numpy as np
from supabase import create_client
import plotly.express as px
from plotly.subplots import make_subplots

# Supabase Connection
supabase = create_client(st.secrets["SUPABASE_URL"], st.secrets["SUPABASE_KEY"])

def apply_styles(df):
    df_styles = pd.DataFrame('', index=df.index, columns=df.columns)
    if '변동' in df.columns:
        df_styles.loc[df['변동'] > 0, '변동'] = 'color: red'
        df_styles.loc[df['변동'] < 0, '변동'] = 'color: blue'
    return df_styles

def get_available_dates():
    response = supabase.rpc("get_all_dates").execute()
    return [item['price_date'] for item in response.data] if response.data else []

def get_data(target_date, all_dates, market_type):
    target_date_str = str(target_date)
    if target_date_str not in all_dates: return None
        
    target_idx = all_dates.index(target_date_str)
    # 이전 날짜와 5일 전 날짜를 가져와 추세 분석 (눌림목 포착용)
    prev_idx = target_idx + 1 if target_idx + 1 < len(all_dates) else target_idx
    days5_idx = min(target_idx + 5, len(all_dates) - 1)
    
    prev_date = all_dates[prev_idx]
    days5_date = all_dates[days5_idx]

    # 현재 데이터
    df_curr = pd.DataFrame(supabase.table("daily_analysis").select("ticker, momentum_rank, weighted_momentum, rs_score, close_price").eq("price_date", target_date_str).eq("market", market_type).execute().data)
    # 5일 전 데이터
    df_days5 = pd.DataFrame(supabase.table("daily_analysis").select("ticker, momentum_rank, close_price").eq("price_date", days5_date).eq("market", market_type).execute().data)
    
    if df_curr.empty: return None

    # 데이터 병합 및 계산
    df_curr = df_curr.rename(columns={'momentum_rank': '순위', 'weighted_momentum': 'MOT', 'rs_score': 'RS', 'close_price': '종가'})
    df_days5 = df_days5.rename(columns={'momentum_rank': '순위_5일전', 'close_price': '종가_5일전'})
    
    df_final = pd.merge(df_curr, df_days5, on="ticker", how="left")
    df_final['변동'] = df_final['순위_5일전'] - df_final['순위'] # 순위 변화 (양수면 상승)
    df_final['주가변동률'] = (df_final['종가'] - df_final['종가_5일전']) / df_final['종가_5일전']
    
    # 눌림목 조건: 주가는 하락(-5% 이내) but 순위는 상승(0 이상)
    df_final['is_pullback'] = (df_final['주가변동률'] < 0) & (df_final['주가변동률'] > -0.05) & (df_final['변동'] > 0)

    # 종목명 병합
    df_stocks = pd.DataFrame(supabase.table("stocks").select("ticker, name").execute().data)
    df_final = pd.merge(df_final, df_stocks, on="ticker", how="left")
    
    return df_final.rename(columns={'name': '종목명'})

# UI 구성
st.set_page_config(layout="wide")
with st.sidebar:
    market_type = st.radio("시장 선택", ["KR", "US"], horizontal=True)
    all_dates = get_available_dates()
    selected_date = st.date_input("기준일 선택", value=pd.to_datetime(all_dates[0]) if all_dates else None)
    if st.button("새로고침"): st.rerun()

st.markdown('<p style="font-size:24px; font-weight:bold;">📈 Momentum Analysis</p>', unsafe_allow_html=True)

df_display = get_data(selected_date, all_dates, market_type)

if df_display is not None:
    col_order = ['순위', '변동', '종목명', 'MOT', 'RS', '종가']
    tab1, tab2, tab3 = st.tabs(["전체 보기", "신규 진입주", "🎯 눌림목/추세추종 포착"])

    with tab1:
        st.dataframe(df_display.style.apply(apply_styles, axis=None), hide_index=True, use_container_width=True)
    with tab2:
        st.dataframe(df_display[df_display['순위'] <= 30], hide_index=True, use_container_width=True)
    with tab3:
        st.info("주가는 단기 조정 중(-5% 이내)이나 모멘텀 순위가 상승하는 주도주 후보군입니다.")
        df_pullback = df_display[df_display['is_pullback'] == True]
        st.dataframe(df_pullback[col_order].style.apply(apply_styles, axis=None), hide_index=True, use_container_width=True)
else:
    st.warning("데이터가 없습니다.")
