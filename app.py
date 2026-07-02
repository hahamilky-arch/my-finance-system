import streamlit as st
import pandas as pd
from supabase import create_client

# Supabase 연결
supabase = create_client(st.secrets["SUPABASE_URL"], st.secrets["SUPABASE_KEY"])

# --- 1. 데이터 처리 및 스타일 ---
def apply_styles(df):
    df_styles = pd.DataFrame('', index=df.index, columns=df.columns)
    if 'is_new_top30' in df.columns:
        df_styles.loc[df['is_new_top30'], :] = 'background-color: #ffcccc'
    if '변동' in df.columns:
        df_styles.loc[df['변동'] > 0, '변동'] = 'color: red'
        df_styles.loc[df['변동'] < 0, '변동'] = 'color: blue'
    return df_styles

def get_available_dates():
    response = supabase.rpc("get_all_dates").execute()
    return [item['price_date'] for item in response.data] if response.data else []

def get_data(target_date, all_dates, market_type):
    # 날짜 필터링을 위한 문자열 (RPC 호출용)
    target_date_str = pd.to_datetime(target_date).strftime('%Y-%m-%d')
    if target_date_str not in all_dates: return None

    # [수정 핵심 1] 타겟 날짜를 타임스탬프 객체로 변환 (시/분/초 제거)
    target_date_ts = pd.Timestamp(target_date).normalize()
    
    # 1. 메인 데이터 로드
    res_curr = supabase.table("daily_analysis").select("ticker, momentum_rank, weighted_momentum, rs_score, close_price").eq("price_date", target_date_str).eq("market", market_type).execute()
    df_curr = pd.DataFrame(res_curr.data)
    
    # 타입 강제 변환 (에러 방지용 float64)
    df_curr['close_price'] = pd.to_numeric(df_curr['close_price'], errors='coerce').astype('float64')
    df_curr['ticker'] = df_curr['ticker'].astype(str).str.strip()
    
    # 2. 이동평균 계산을 위한 과거 데이터 로드
    res_hist = supabase.table("daily_analysis").select("ticker, price_date, close_price").eq("market", market_type).execute()
    df_hist = pd.DataFrame(res_hist.data)
    
    # [수정 핵심 2] price_date를 임시 타임스탬프 객체로 변환 (ffill과 MA20 계산용)
    df_hist['price_date_raw'] = pd.to_datetime(df_hist['price_date'], errors='coerce')
    df_hist['close_price'] = pd.to_numeric(df_hist['close_price'], errors='coerce').astype('float64')
    df_hist['ticker'] = df_hist['ticker'].astype(str).str.strip()
    
    # 결측치 보간
    df_hist = df_hist.sort_values(['ticker', 'price_date_raw'])
    df_hist['close_price'] = df_hist.groupby('ticker')['close_price'].ffill()
    
    # MA20 계산 (lambda 내에서 타입 변환 제외하고 밖에서 안전하게 처리)
    df_hist['MA20'] = df_hist.groupby('ticker')['close_price'].transform(lambda x: x.rolling(window=20, min_periods=1).mean())
    df_hist['MA20'] = df_hist['MA20'].astype('float64')

    # [수정 핵심 3] 데이터 병합 전, price_date를 표준 타임스탬프 객체로 변환 (시/분/초 제거)
    df_hist['price_date_ts'] = df_hist['price_date_raw'].dt.normalize()
    
    # 3. 타겟 날짜 MA20 추출
    # [수정 핵심 4] 문자열 비교 대신 타임스탬프 객체끼리 비교 (미세 시간차 무시)
    ma20_today = df_hist[df_hist['price_date_ts'] == target_date_ts][['ticker', 'MA20']].copy()
    ma20_today['ticker'] = ma20_today['ticker'].astype(str).str.strip()
    
    # --- 🚨 X-ray 진단 화면 출력 (수정됨) 🚨 ---
    st.info(f"선택한 날짜: {target_date_str}")
    st.info(f"전체 과거 데이터 수: {len(df_hist)}건 / 타임스탬프 매칭으로 추출된 MA20 데이터: {len(ma20_today)}건")
    if not ma20_today.empty:
        st.success(f"정상 계산된 MA20 샘플값: {ma20_today['MA20'].dropna().iloc[0]:.2f}")
    else:
        st.error(f"🚨 추출된 MA20 데이터가 0건입니다! (Supabase 데이터의 날짜/시간 포맷 문제)")
    # ----------------------------------------
    
    # 메인 데이터와 MA20 병합
    df_final = pd.merge(df_curr, ma20_today, on='ticker', how='left')
    
    # --- 🚨 X-ray 병합 결과 진단 (수정됨) 🚨 ---
    nan_count = df_final['MA20'].isna().sum()
    if nan_count > 0:
        st.error(f"🚨 병합 직후 MA20 값이 누락된 종목 수: {nan_count}건 (Ticker 매칭 문제)")
    # ---------------------------------
    
    # 4. 이전 날짜 순위 데이터 병합
    target_idx = all_dates.index(target_date_str)
    prev_date = all_dates[min(target_idx + 1, len(all_dates)-1)]
    df_prev = pd.DataFrame(supabase.table("daily_analysis").select("ticker, momentum_rank").eq("price_date", prev_date).eq("market", market_type).execute().data)
    
    df_prev['ticker'] = df_prev['ticker'].astype(str).str.strip()
    df_prev = df_prev.rename(columns={'momentum_rank': '순위_prev'})
    
    df_final = pd.merge(df_final, df_prev, on="ticker", how='left')
    df_final = df_final.rename(columns={'momentum_rank': '순위', 'weighted_momentum': 'MOT', 'rs_score': 'RS', 'close_price': '종가'})
    
    # 5. 최적화 지표 계산
    df_final['변동'] = df_final['순위_prev'].fillna(999) - df_final['순위']
    df_final['is_new_top30'] = (df_final['순위'] <= 30) & (df_final['순위_prev'] > 30)
    df_final['is_pullback'] = (df_final['순위'] <= 100) & (df_final['RS'] > 0) & (df_final['변동'] > 0)
    
    # MA20 결측치 처리 (병합 실패 등으로 비어있을 경우 0으로 처리)
    df_final['MA20'] = df_final['MA20'].fillna(0)
    df_final['is_no6_opt'] = (df_final['순위'] <= 30) & (df_final['RS'] > 0) & (df_final['종가'] > df_final['MA20']) & (df_final['MA20'] > 0)
    
    # 종목명 병합
    df_stocks = pd.DataFrame(supabase.table("stocks").select("ticker, name").execute().data)
    df_stocks['ticker'] = df_stocks['ticker'].astype(str).str.strip()
    return pd.merge(df_final, df_stocks, on="ticker", how="left").rename(columns={'name': '종목명'}).sort_values('순위')

# --- 2. UI 및 메인 로직 ---
st.set_page_config(layout="wide")
st.markdown("##### 📈 Momentum Dashboard v1.3.9") 

with st.sidebar:
    market_type = st.radio("Market", ["KR", "US"], horizontal=True)
    all_dates = get_available_dates()
    # 사이드바에도 타임스탬프 기반 날짜로 표시
    selected_date = st.date_input("Date", value=pd.to_datetime(all_dates[0]) if all_dates else None)
    if st.button("Refresh"): st.rerun()

df_display = get_data(selected_date, all_dates, market_type)

if df_display is not None:
    tab1, tab2, tab3, tab4, tab5 = st.tabs(["Overview", "New Entries", "🎯 Pullback", "🚀 No.6 최적화", "🔄 Rebalancing"])
    
    col_order = ['순위', '변동', '종목명', 'MOT', 'RS', '종가', 'MA20']
    tab_dfs = [df_display.head(100), df_display[df_display['is_new_top30']], df_display[df_display['is_pullback']], df_display[df_display['is_no6_opt']]]
    
    for i, tab in enumerate([tab1, tab2, tab3, tab4]):
        with tab:
            st.dataframe(tab_dfs[i][col_order].style.apply(apply_styles, axis=None).format({
                    'MOT': '{:.2f}', 'RS': '{:.2f}', '종가': '{:,.0f}', 'MA20': '{:,.0f}', '변동': '{:+.0f}'
                }), hide_index=True, use_container_width=True)
    
    with tab5:
        st.markdown("###### 📋 오늘의 리밸런싱 지시서")
        c1, c2 = st.columns(2)
        sell_df = df_display[(df_display['순위'] > 30) & (df_display['순위_prev'] <= 30)]
        with c1:
            st.error(f"SELL (30위권 이탈): {len(sell_df)}종목")
            if not sell_df.empty: st.dataframe(sell_df[['종목명', '순위', '순위_prev']], use_container_width=True)
        buy_df = df_display[df_display['is_new_top30']]
        with c2:
            st.success(f"BUY (신규 진입): {len(buy_df)}종목")
            if not buy_df.empty: st.dataframe(buy_df[['종목명', '순위']], use_container_width=True)
else:
    st.warning("데이터를 불러오는 중입니다.")
