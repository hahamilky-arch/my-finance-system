import streamlit as st
import pandas as pd
from supabase import create_client

# 백지화 방지를 위해 최상단 배치
st.set_page_config(layout="wide")

# Supabase 연결
supabase = create_client(st.secrets["SUPABASE_URL"], st.secrets["SUPABASE_KEY"])

# --- 1. 데이터 처리 및 스타일 함수 ---
def apply_styles(df):
    df_styles = pd.DataFrame('', index=df.index, columns=df.columns)
    if '변동' in df.columns:
        df_styles.loc[df['변동'] > 0, '변동'] = 'color: red;'
        df_styles.loc[df['변동'] < 0, '변동'] = 'color: blue;'
    return df_styles

# 보유 종목 리스트 (매도일이 없는 '진짜 보유 중'인 종목의 티커만) 가져오기
def get_current_holdings():
    res = supabase.table("current_holdings").select("ticker").is_("sell_date", "null").execute()
    return [item['ticker'] for item in res.data] if res.data else []

# 매수/매도 처리 및 단일 테이블(current_holdings) 업데이트 로직
def update_holdings(ticker, action, price, trade_date, quantity):
    trade_date_str = trade_date.strftime('%Y-%m-%d')
    
    if action == 'BUY':
        try:
            supabase.table("current_holdings").insert({
                "ticker": str(ticker).strip(),
                "buy_date": trade_date_str,
                "buy_price": float(price),
                "quantity": int(quantity)
            }).execute()
            st.success(f"✅ [{ticker}] 매수 기록 완료!")
        except Exception as e:
            st.error(f"❌ 매수 DB 저장 실패: {str(e)}")
            return
        
    elif action == 'SELL':
        try:
            res = supabase.table("current_holdings").select("*").eq("ticker", ticker).is_("sell_date", "null").execute()
            
            if res.data:
                holding = res.data[0]
                row_id = holding.get('id')
                
                raw_bp = holding.get('buy_price')
                buy_price = float(raw_bp) if pd.notna(raw_bp) and raw_bp is not None else 0.0
                
                raw_qty = holding.get('quantity')
                db_quantity = int(raw_qty) if pd.notna(raw_qty) and raw_qty is not None else int(quantity)
                
                profit_amount = 0.0
                profit_rate = 0.0
                if buy_price > 0:
                    profit_amount = (float(price) - buy_price) * db_quantity
                    profit_rate = ((float(price) / buy_price) - 1) * 100
                
                supabase.table("current_holdings").update({
                    "sell_date": trade_date_str,
                    "sell_price": float(price),
                    "profit_amount": float(profit_amount),
                    "profit_rate": round(float(profit_rate), 2)
                }).eq("id", row_id).execute()
                
                st.error(f"🗑️ [{ticker}] 매도 처리 및 정보 업데이트 완료!")
            else:
                supabase.table("current_holdings").insert({
                    "ticker": str(ticker).strip(),
                    "sell_date": trade_date_str,
                    "sell_price": float(price),
                    "quantity": int(quantity)
                }).execute()
                st.error(f"🗑️ [{ticker}] 매수 정보 없이 매도 기록만 생성 완료!")
                
        except Exception as e:
            st.error(f"❌ 매도 데이터 업데이트 에러: {str(e)}")
            return
        
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
    if not df_stocks.empty:
        df_stocks['ticker'] = df_stocks['ticker'].astype(str).str.strip()
    else:
        df_stocks = pd.DataFrame(columns=['ticker', 'name'])

    my_holdings = get_current_holdings()
    
    def classify_status(row):
        is_in_holdings = row['ticker'] in my_holdings
        if row['is_no6_opt']:
            return '보유중' if is_in_holdings else '매수추천'
        else:
            return '매도필요' if is_in_holdings else '관망'

    df_final['매매상태'] = df_final.apply(classify_status, axis=1)
    
    return pd.merge(df_final, df_stocks, on="ticker", how="left").rename(columns={'name': '종목명'}).sort_values('순위')

def display_trade_list(data, title, button_label, key_prefix, target_date):
    with st.expander(f"🚨 {title} ({len(data)}개)", expanded=True):
        if data.empty:
            st.write(f"해당되는 {button_label} 종목이 없습니다.")
        else:
            for _, row in data.iterrows():
                c1, c2 = st.columns([4, 1])
                
                c1.markdown(f"""
                <div style="line-height: 1.6; margin-top: 4px;">
                    <strong style="font-size: 1.1em; color: #111111;">{row['종목명']}</strong> 
                    <span style="font-size: 0.8em; color: #888888; margin-left: 4px;">({row['ticker']})</span>
                    <span style="font-size: 0.9em; margin-left: 12px; color: #444444;">
                        | MOT: <span style="font-family: monospace; background-color: #f1f3f6; padding: 2px 5px; border-radius: 4px;">{row['MOT']:.2f}</span> 
                        | RS: <span style="color: #137333; font-weight: bold; font-family: monospace; background-color: #e6f4ea; padding: 2px 5px; border-radius: 4px;">{row['RS']:.2f}</span>
                    </span>
                </div>
                """, unsafe_allow_html=True)
            
                with c2.popover(button_label):
                    st.write(f"**{row['종목명']}**")
                    input_price = st.number_input(f"{button_label}가", value=float(row['종가']), key=f"p_{key_prefix}_{row['ticker']}")
                    input_qty = st.number_input("수량", value=1, min_value=1, step=1, key=f"q_{key_prefix}_{row['ticker']}")
                    
                    if st.button("확인", key=f"btn_{key_prefix}_{row['ticker']}"):
                        action_type = 'SELL' if '매도' in title else 'BUY'
                        update_holdings(row['ticker'], action_type, input_price, target_date, input_qty)

# --- 2. UI 메인 실행 파트 ---
st.markdown("##### 📈 Momentum Dashboard v1.4.5")
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
    tab1, tab2, tab3, tab4, tab5 = st.tabs(["Overview", "New Entries", "🎯 Pullback", "🚀 No.6 최적화", "📊 성과 분석"])
    
    col_order = ['순위', '변동', '종목명', 'MOT', 'RS', '종가', 'MA20', 'ticker'] 
    tab_dfs = [df_display.head(100), df_display[df_display['is_new_top30']], df_display[df_display['is_pullback']], df_display[df_display['is_no6_opt']]]

    clicked_ticker = None
    
    for i, tab in enumerate([tab1, tab2, tab3]):
        with tab:
            df_target = tab_dfs[i][col_order].copy()
            # 🛠️ [에러 수정 포인트] selection_mode="single-row" (하이픈 사용)
            event = st.dataframe(
                df_target.style.apply(apply_styles, axis=None).format({
                    'MOT': '{:.2f}', 'RS': '{:.2f}', '종가': '{:,.0f}', 'MA20': '{:,.0f}', '변동': '{:+.0f}'
                }, na_rep='-'), 
                hide_index=True, 
                use_container_width=True,
                on_select="rerun",  
                selection_mode="single-row",
                key=f"df_tab_{i}"
            )
            
            if event and "rows" in event.get("selection", {}) and event["selection"]["rows"]:
                selected_row_idx = event["selection"]["rows"][0]
                clicked_ticker = df_target.iloc[selected_row_idx]['ticker']

    if clicked_ticker:
        st.
