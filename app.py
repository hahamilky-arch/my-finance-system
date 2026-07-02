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
# 보유 종목 리스트 가져오기
def get_current_holdings():
    res = supabase.table("current_holdings").select("ticker").execute()
    return [item['ticker'] for item in res.data]

# 보유 종목 갱신 (버튼 클릭 시 작동)
def update_holdings(ticker, action):
    if action == 'BUY':
        supabase.table("current_holdings").insert({"ticker": ticker}).execute()
        st.success(f"✅ {ticker} 보유 종목 추가 완료!")
    elif action == 'SELL':
        supabase.table("current_holdings").delete().eq("ticker", ticker).execute()
        st.error(f"🗑️ {ticker} 보유 종목에서 제외 완료!")
    st.rerun()

def get_market_regime():
    """시장이 안전한지 판단 (지수 > MA20)"""
    res = supabase.table("daily_analysis").select("close_price").eq("ticker", "^GSPC").order("price_date", desc=True).limit(20).execute()
    df_idx = pd.DataFrame(res.data)
    if df_idx.empty: return True
    ma20 = df_idx['close_price'].mean()
    current_price = df_idx.iloc[0]['close_price']
    return current_price >= ma20

def get_available_dates():
    response = supabase.rpc("get_all_dates").execute()
    return [item['price_date'] for item in response.data] if response.data else []

def get_data(target_date, all_dates, market_type):
    target_date_ts = pd.Timestamp(target_date).normalize()
    target_date_str = target_date_ts.strftime('%Y-%m-%d')
    if target_date_str not in all_dates: return None

    # DB에서 MA10, MA20 직접 조회
    res_curr = supabase.table("daily_analysis") \
        .select("ticker, momentum_rank, weighted_momentum, rs_score, close_price, ma10, ma20") \
        .eq("price_date", target_date_str) \
        .eq("market", market_type) \
        .execute()
    
    df_final = pd.DataFrame(res_curr.data)
    if df_final.empty: return None
    
    # 타입 변환
    df_final['close_price'] = pd.to_numeric(df_final['close_price'], errors='coerce').astype('float64')
    df_final['ma10'] = pd.to_numeric(df_final['ma10'], errors='coerce').astype('float64')
    df_final['ma20'] = pd.to_numeric(df_final['ma20'], errors='coerce').astype('float64')
    df_final['ticker'] = df_final['ticker'].astype(str).str.strip()
    
    # 이전 날짜 데이터 병합
    target_idx = all_dates.index(target_date_str)
    prev_date = all_dates[min(target_idx + 1, len(all_dates)-1)]
    res_prev = supabase.table("daily_analysis").select("ticker, momentum_rank").eq("price_date", prev_date).execute()
    df_prev = pd.DataFrame(res_prev.data).rename(columns={'momentum_rank': '순위_prev'})
    
    df_final = pd.merge(df_final, df_prev, on="ticker", how='left')
    df_final = df_final.rename(columns={'momentum_rank': '순위', 'weighted_momentum': 'MOT', 'rs_score': 'RS', 'close_price': '종가', 'ma10': 'MA10', 'ma20': 'MA20'})
    
    # 지표 계산
    df_final['변동'] = df_final['순위_prev'].fillna(999) - df_final['순위']
    df_final['is_new_top30'] = (df_final['순위'] <= 30) & (df_final['순위_prev'] > 30)
    df_final['is_pullback'] = (df_final['순위'] <= 100) & (df_final['RS'] > 0) & (df_final['변동'] > 0)
    df_final['MA20'] = df_final['MA20'].fillna(0)
    df_final['is_no6_opt'] = (df_final['순위'] <= 30) & (df_final['RS'] > 0) & (df_final['종가'] > df_final['MA20']) & (df_final['MA20'] > 0)
    
    df_stocks = pd.DataFrame(supabase.table("stocks").select("ticker, name").execute().data)
    df_stocks['ticker'] = df_stocks['ticker'].astype(str).str.strip()

    my_holdings = get_current_holdings()
    
    def classify_status(row):
        is_in_holdings = row['ticker'] in my_holdings
        # No.6 전략 조건이 True인 경우 (매수/보유 추천)
        if row['is_no6_opt']:
            return '보유중' if is_in_holdings else '매수추천'
        # 전략 조건이 False인 경우 (매도 필요/관망)
        else:
            return '매도필요' if is_in_holdings else '관망'

    df_final['매매상태'] = df_final.apply(classify_status, axis=1)
    
    return pd.merge(df_final, df_stocks, on="ticker", how="left").rename(columns={'name': '종목명'}).sort_values('순위')

# --- 2. UI 로직 ---
st.set_page_config(layout="wide")
st.markdown("##### 📈 Momentum Dashboard v1.3.11")
market_safe = get_market_regime()

if not market_safe:
    st.warning("⚠️ 시장 주의보: 지수가 MA20 아래입니다. 리스크 관리에 집중하세요.")

with st.sidebar:
    market_type = st.radio("Market", ["KR", "US"], horizontal=True)
    all_dates = get_available_dates()
    selected_date = st.date_input("Date", value=pd.to_datetime(all_dates[0]) if all_dates else None)
    if st.button("Refresh"): st.rerun()

df_display = get_data(selected_date, all_dates, market_type)

if df_display is not None:
    tab1, tab2, tab3, tab4, tab5 = st.tabs(["Overview", "New Entries", "🎯 Pullback", "🚀 No.6 최적화", "🔄 Rebalancing"])
    
    col_order = ['순위', '변동', '종목명', 'MOT', 'RS', '종가', 'MA20']
    tab_dfs = [df_display.head(100), df_display[df_display['is_new_top30']], df_display[df_display['is_pullback']], df_display[df_display['is_no6_opt']]]
    
    for i, tab in enumerate([tab1, tab2, tab3]):
        with tab:
            st.dataframe(tab_dfs[i][col_order].style.apply(apply_styles, axis=None).format({
                    'MOT': '{:.2f}', 'RS': '{:.2f}', '종가': '{:,.0f}', 'MA20': '{:,.0f}', '변동': '{:+.0f}'
                }), hide_index=True, use_container_width=True)
            
    with tab4:
        # st.markdown("### 🚀 No.6 전략 실전 매매 지시서")
        st.caption("전략 신호와 실제 보유 종목을 비교하여 즉각적인 리밸런싱을 수행하세요.")
        
        # 신호가 있는 종목만 필터링
        df_actions = df_display[df_display['매매상태'] != '관망'].copy()
        
        if df_actions.empty:
            st.info("현재 No.6 전략상 매매할 종목이 없습니다. 시장을 관망하세요.")
        else:
            # 매매상태별로 섹션을 나누어 가독성 확보
            for status in ['매도필요', '매수추천', '보유중']:
                subset = df_actions[df_actions['매매상태'] == status]
                if subset.empty: continue
                
                # 상태별 컬러 컨테이너
                with st.container(border=True):
                    st.subheader(f"{'🚨' if status == '매도필요' else '✅' if status == '매수추천' else '💼'} {status}")
                    
                    for _, row in subset.iterrows():
                        cols = st.columns([2, 2, 2, 1])
                        cols[0].write(f"**{row['종목명']}**")
                        cols[1].caption(f"{row['ticker']}")
                        cols[2].write(f"{row['순위']}위 / RS: {row['RS']:.2f}")
                        
                        # 버튼 영역
                        if status == '매도필요':
                            if cols[3].button("매도", key=f"s_{row['ticker']}"): update_holdings(row['ticker'], 'SELL')
                        elif status == '매수추천':
                            if cols[3].button("매수", key=f"b_{row['ticker']}"): update_holdings(row['ticker'], 'BUY')
                        else:
                            cols[3].write("유지")
        # 2. 구분선 추가
        st.divider()
        # 3. 전략 조건 설명 (표 바로 아래 배치)
        # st.markdown("#### 🔍 No.6 전략 필터링 조건")
        st.caption("이 전략은 모멘텀이 강하고 추세가 확인된 최적의 종목을 선별합니다.")
        
        c1, c2 = st.columns(2)
        with c1:
            st.success("**[매수 조건]**")
            st.markdown("""
            * **모멘텀 순위:** 전체 30위 이내
            * **상대 강도(RS):** 0 초과 (시장 대비 우위)
            * **추세 확인:** 종가 > 20일 이동평균선(MA20)
            """)
        with c2:
            st.error("**[매도(제외) 조건]**")
            st.markdown("""
            * **순위 이탈:** 30위권 밖으로 하락
            * **추세 이탈:** 종가 < MA20 또는 시장 주의보 발령
            """)

    with tab5:
        st.markdown("### 📋 오늘의 매매 지시서 (No.6 전략 기준)")
        # --- 추가: 보유 종목 현황 표 ---
        st.markdown("### 💼 현재 보유 종목 현황")
        holdings_df = df_display[df_display['매매상태'] == '보유중'].copy()
        
        if holdings_df.empty:
            st.info("현재 보유 중인 종목이 없습니다.")
        else:
            # 깔끔하게 필요한 정보만 추출
            display_cols = ['종목명', '순위', '종가', 'RS']
            st.dataframe(
                holdings_df[display_cols].style.format({'종가': '{:,.0f}', 'RS': '{:.2f}'}),
                hide_index=True, 
                use_container_width=True
            )
        
        st.divider() # 보유 표와 매매 지시서 구분
        
        # 전략 기준 매매 대상만 필터링
        df_rebal = df_display[df_display['매매상태'].isin(['매도필요', '매수추천'])].copy()
        
        if df_rebal.empty:
            st.success("✅ 모든 종목이 전략 상태와 일치합니다. 리밸런싱이 필요 없습니다.")
        else:
            c1, c2 = st.columns(2)
            
            # 좌측: 매도 (SELL)
            with c1:
                st.error("### 🚨 매도 (SELL)")
                sell_list = df_rebal[df_rebal['매매상태'] == '매도필요']
                if sell_list.empty:
                    st.write("매도할 종목이 없습니다.")
                else:
                    for _, row in sell_list.iterrows():
                        with st.container(border=True):
                            cols = st.columns([2, 1])
                            cols[0].write(f"**{row['종목명']}**\n{row['ticker']}")
                            if cols[1].button("매도 완료", key=f"tab5_sell_{row['ticker']}"):
                                update_holdings(row['ticker'], 'SELL')
            
            # 우측: 매수 (BUY)
            with c2:
                st.success("### ✅ 매수 (BUY)")
                buy_list = df_rebal[df_rebal['매매상태'] == '매수추천']
                if buy_list.empty:
                    st.write("매수할 종목이 없습니다.")
                else:
                    for _, row in buy_list.iterrows():
                        with st.container(border=True):
                            cols = st.columns([2, 1])
                            cols[0].write(f"**{row['종목명']}**\n{row['ticker']}")
                            if cols[1].button("매수 완료", key=f"tab5_buy_{row['ticker']}"):
                                update_holdings(row['ticker'], 'BUY')

else:
    st.warning("데이터를 불러오는 중입니다.")
