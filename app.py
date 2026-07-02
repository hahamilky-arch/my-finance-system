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

# 보유 종목 리스트 (티커만) 가져오기
def get_current_holdings():
    res = supabase.table("current_holdings").select("ticker").execute()
    return [item['ticker'] for item in res.data]

# 매수/매도 처리 및 수익률 자동 계산 로직
def update_holdings(ticker, action, price, trade_date, quantity):
    trade_date_str = trade_date.strftime('%Y-%m-%d')
    
    if action == 'BUY':
        supabase.table("current_holdings").insert({
            "ticker": ticker,
            "buy_date": trade_date_str,
            "buy_price": float(price),
            "quantity": int(quantity)
        }).execute()
        st.success(f"✅ [{ticker}] 매수 기록 완료!")
        
    elif action == 'SELL':
        res = supabase.table("current_holdings").select("*").eq("ticker", ticker).execute()
        
        if res.data:
            holding = res.data[0]
            buy_price = float(holding.get('buy_price', 0))
            buy_date = holding.get('buy_date', trade_date_str)
            db_quantity = int(holding.get('quantity', quantity))
            
            if buy_price > 0:
                profit_amount = (float(price) - buy_price) * db_quantity
                profit_rate = ((float(price) / buy_price) - 1) * 100
                
                supabase.table("trade_history").insert({
                    "ticker": ticker,
                    "buy_date": buy_date,
                    "buy_price": buy_price,
                    "sell_date": trade_date_str,
                    "sell_price": float(price),
                    "profit_amount": float(profit_amount),
                    "profit_rate": round(profit_rate, 2)
                }).execute()
        
        supabase.table("current_holdings").delete().eq("ticker", ticker).execute()
        st.error(f"🗑️ [{ticker}] 매도 처리 완료!")
        
    st.rerun()

def get_market_regime():
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

    res_curr = supabase.table("daily_analysis") \
        .select("ticker, momentum_rank, weighted_momentum, rs_score, close_price, ma10, ma20") \
        .eq("price_date", target_date_str) \
        .eq("market", market_type) \
        .execute()
    
    df_final = pd.DataFrame(res_curr.data)
    if df_final.empty: return None
    
    df_final['close_price'] = pd.to_numeric(df_final['close_price'], errors='coerce').astype('float64')
    df_final['ma10'] = pd.to_numeric(df_final['ma10'], errors='coerce').astype('float64')
    df_final['ma20'] = pd.to_numeric(df_final['ma20'], errors='coerce').astype('float64')
    df_final['ticker'] = df_final['ticker'].astype(str).str.strip()
    
    target_idx = all_dates.index(target_date_str)
    prev_date = all_dates[min(target_idx + 1, len(all_dates)-1)]
    res_prev = supabase.table("daily_analysis").select("ticker, momentum_rank").eq("price_date", prev_date).execute()
    df_prev = pd.DataFrame(res_prev.data).rename(columns={'momentum_rank': '순위_prev'})
    
    df_final = pd.merge(df_final, df_prev, on="ticker", how='left')
    df_final = df_final.rename(columns={'momentum_rank': '순위', 'weighted_momentum': 'MOT', 'rs_score': 'RS', 'close_price': '종가', 'ma10': 'MA10', 'ma20': 'MA20'})
    
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
        if row['is_no6_opt']:
            return '보유중' if is_in_holdings else '매수추천'
        else:
            return '매도필요' if is_in_holdings else '관망'

    df_final['매매상태'] = df_final.apply(classify_status, axis=1)
    
    return pd.merge(df_final, df_stocks, on="ticker", how="left").rename(columns={'name': '종목명'}).sort_values('순위')

# --- 2. UI 로직 ---
st.set_page_config(layout="wide")
st.markdown("##### 📈 Momentum Dashboard v1.3.12")
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

    for i, tab in enumerate([tab1, tab2, tab3]):
        with tab:
            st.dataframe(tab_dfs[i][col_order].style.apply(apply_styles, axis=None).format({
                    'MOT': '{:.2f}', 'RS': '{:.2f}', '종가': '{:,.0f}', 'MA20': '{:,.0f}', '변동': '{:+.0f}'
                }), hide_index=True, use_container_width=True)

    # --- Tab 4(매매 지시서) 가독성 최적화 ---
    with tab4:
        st.markdown("##### 📋 오늘의 매매 지시서")
    
        # 1. 💼 보유 종목 (인덱스 삭제, 매수정보 노출, 개별 매도 버튼 포함)
        holdings_res = supabase.table("current_holdings").select("*").execute()
        holdings_db = pd.DataFrame(holdings_res.data) if holdings_res.data else pd.DataFrame()

        with st.expander(f"💼 현재 보유 종목 ({len(holdings_db)}개)", expanded=True):
            if holdings_db.empty:
                st.info("보유 종목이 없습니다.")
            else:
                # 종목명 매핑을 위한 주식 마스터 데이터
                df_stocks = pd.DataFrame(supabase.table("stocks").select("ticker, name").execute().data)
                df_stocks['ticker'] = df_stocks['ticker'].astype(str).str.strip()
                holdings_merged = pd.merge(holdings_db, df_stocks, on="ticker", how="left")
                
                # 리스트 형태로 깔끔하게 렌더링
                for _, h_row in holdings_merged.iterrows():
                    ticker = h_row['ticker']
                    name = h_row.get('name', ticker)
                    buy_date = h_row.get('buy_date')
                    buy_date = buy_date if pd.notna(buy_date) and buy_date is not None else '-'

                    raw_bp = h_row.get('buy_price')
                    buy_price = float(raw_bp) if pd.notna(raw_bp) and raw_bp is not None else 0.0

                    raw_qty = h_row.get('quantity')
                    qty = int(raw_qty) if pd.notna(raw_qty) and raw_qty is not None else 1
                    
                    # 현재 가격 매핑
                    curr_row = df_display[df_display['ticker'] == ticker]
                    curr_price = float(curr_row['종가'].values[0]) if not curr_row.empty else buy_price
                    
                    c1, c2 = st.columns([4, 1])
                    
                    # 가독성 높은 2줄 마크다운 (인덱스 없음)
                    c1.markdown(f"""
                    **{name}** <small>({ticker})</small><br>
                    <span style='color:gray; font-size:0.9em;'>매수일: `{buy_date}` | 매수가: `{buy_price:,.0f}원` | 수량: `{qty}주`</span>
                    """, unsafe_allow_html=True)
                    
                    # 매도 신호에 안 떠도 언제든 강제 매도 가능한 팝오버 버튼
                    with c2.popover("개별 매도"):
                        st.write(f"**{name}** 수동 매도")
                        input_price = st.number_input("매도가", value=curr_price, key=f"p_force_{ticker}")
                        input_qty = st.number_input("수량", value=qty, min_value=1, step=1, key=f"q_force_{ticker}")
                        if st.button("매도 확정", key=f"btn_force_{ticker}"):
                            update_holdings(ticker, 'SELL', input_price, selected_date, input_qty)
        
        st.write("") # 간격 띄우기

        # 2. 🚨 시스템 매매 신호 (추천 리스트)
        df_rebal = df_display[df_display['매매상태'].isin(['매도필요', '매수추천'])]
    
        def display_trade_list(data, title, button_label, key_prefix, target_date):
            with st.expander(f"🚨 {title} ({len(data)}개)", expanded=True):
                if data.empty:
                    st.write(f"해당되는 {button_label} 종목이 없습니다.")
                else:
                    for _, row in data.iterrows():
                        c1, c2 = st.columns([4, 1])
                        c1.markdown(f"**{row['종목명']}** <small>({row['ticker']})</small> | MOT: `{row['MOT']:.2f}` | RS: :color[green](**{row['RS']:.2f}**)")
                    
                        with c2.popover(button_label):
                            st.write(f"**{row['종목명']}**")
                            input_price = st.number_input(f"{button_label}가", value=float(row['종가']), key=f"p_{key_prefix}_{row['ticker']}")
                            input_qty = st.number_input("수량", value=1, min_value=1, step=1, key=f"q_{key_prefix}_{row['ticker']}")
                            
                            if st.button("확인", key=f"btn_{key_prefix}_{row['ticker']}"):
                                action_type = 'SELL' if '매도' in title else 'BUY'
                                update_holdings(row['ticker'], action_type, input_price, target_date, input_qty)

        # 시스템 추천 매도/매수
        display_trade_list(df_rebal[df_rebal['매매상태'] == '매도필요'], "시스템 매도 필요", "매도", "sys_s", selected_date)
        display_trade_list(df_rebal[df_rebal['매매상태'] == '매수추천'], "시스템 매수 추천", "매수", "sys_b", selected_date)
    
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
