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
    tab1, tab2, tab3, tab4 = st.tabs(["Overview", "New Entries", "🎯 Pullback", "🚀 No.6 최적화"])
    
    col_order = ['순위', '변동', '종목명', 'MOT', 'RS', '종가', 'MA20']
    tab_dfs = [df_display.head(100), df_display[df_display['is_new_top30']], df_display[df_display['is_pullback']], df_display[df_display['is_no6_opt']]]

    # --- Tab 1, 2, 3
    for i, tab in enumerate([tab1, tab2, tab3]):
        with tab:
            st.dataframe(tab_dfs[i][col_order].style.apply(apply_styles, axis=None).format({
                    'MOT': '{:.2f}', 'RS': '{:.2f}', '종가': '{:,.0f}', 'MA20': '{:,.0f}', '변동': '{:+.0f}'
                }), hide_index=True, use_container_width=True)

    # --- Tab 4(매매 지시서) 모바일 최적화 코드 ---
    with tab4:
        st.markdown("##### 📋 오늘의 매매 지시서")
        
        # 1. 보유 종목 현황 (접기/펼치기) / 포맷팅 적용
        holdings = df_display[df_display['매매상태'] == '보유중'].copy()
        with st.expander(f"💼 현재 보유 종목 ({len(holdings)}개)", expanded=False):
            if holdings.empty:
                st.info("보유 종목 없음")
            else:
                # 데이터 복사 후 포맷팅
                display_holdings = holdings[['순위', '종목명', '종가']].copy()
                display_holdings['종가'] = display_holdings['종가'].apply(lambda x: f"{int(x):,}")
                
                st.table(display_holdings,hide_index=True)


        # 2. 매매 신호 (매수/매도 리스트)
        df_rebal = df_display[df_display['매매상태'].isin(['매도필요', '매수추천'])]
        
        # 매도 리스트
        sell_list = df_rebal[df_rebal['매매상태'] == '매도필요']
        with st.expander(f"🚨 매도 필요 ({len(sell_list)}개)", expanded=True):
            if sell_list.empty:
                st.write("매도할 종목이 없습니다.")
            else:
                for _, row in sell_list.iterrows():
                    c1, c2 = st.columns([4, 1])
                    c1.write(f"[{row['ticker']}] {row['종목명']}  MOT:{row['MOT']:.2f}  RS:{row['RS']:.2f}")
                    with c2.popover("매도"):
                        st.write(f"**{row['종목명']}** 매도하시겠습니까?")
                        if st.button("확인", key=f"conf_s_{row['ticker']}"):
                            update_holdings(row['ticker'], 'SELL')

        # 매수 리스트
        buy_list = df_rebal[df_rebal['매매상태'] == '매수추천']
        with st.expander(f"✅ 매수 추천 ({len(buy_list)}개)", expanded=True):
            if buy_list.empty:
                st.write("매수할 종목이 없습니다.")
            else:
                for _, row in buy_list.iterrows():
                    c1, c2 = st.columns([4, 1])
                    #c1.write(f"**{row['종목명']}** ({row['ticker']})")
                    c1.write(f"[{row['ticker']}] {row['종목명']}  MOT:{row['MOT']:.2f}  RS:{row['RS']:.2f}")
                    with c2.popover("매수"):
                        st.write(f"**{row['종목명']}** 매수하시겠습니까?")
                        if st.button("확인", key=f"conf_b_{row['ticker']}"):
                            update_holdings(row['ticker'], 'BUY')

        # 3. 전략 상세 설명
        st.divider()
        with st.expander("🔍 No.6 전략 필터링 조건 보기"):
            c1, c2 = st.columns(2)
            with c1:
                st.markdown("**[매수 조건]**\n- 순위: 30위 이내\n- RS: 0 초과\n- 추세: 종가 > MA20")
            with c2:
                st.markdown("**[매도 조건]**\n- 순위: 30위 밖\n- 추세: 종가 < MA20")
else:
    st.warning("데이터를 불러오는 중입니다.")
