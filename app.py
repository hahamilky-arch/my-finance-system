import streamlit as st
import pandas as pd
import streamlit.components.v1 as components
import time
from db import supabase, get_holdings_table, update_holdings, get_market_regime, get_available_dates
from strategy import get_data
from charts import draw_integrated_chart

st.set_page_config(layout="wide")

st.markdown("<div id='top-section'></div>", unsafe_allow_html=True)
st.markdown("""
    <style>
    .block-container { padding-top: 3rem !important; padding-bottom: 2rem !important; }
    html, body, [class*="st-"] { font-size: 14px !important; }
    h5 { font-size: 1.2rem !important; margin-bottom: 0.5rem !important; }
    .floating-btn-left {
        position: fixed; bottom: 25px; left: 25px;
        background: linear-gradient(135deg, #2b5876 0%, #4e4376 100%);
        color: white !important; border-radius: 30px; padding: 10px 18px;
        font-weight: bold; box-shadow: 0 4px 15px rgba(0,0,0,0.2);
        cursor: pointer; z-index: 99999; text-decoration: none;
    }
    </style>
    <a href="#top-section" class="floating-btn-left"><span>⬆️</span> <span>상단 표로 이동</span></a>
""", unsafe_allow_html=True)

def scroll_to_chart():
    components.html("<script>setTimeout(function(){const el=window.parent.document.getElementById('chart-section');if(el)el.scrollIntoView({behavior:'smooth'});},100);</script>", height=0)

def calc_buy_qty_atr(ack, qk, atr_v):
    acc = st.session_state.get(ack, 0.0)
    if atr_v > 0: st.session_state[qk] = float(int((acc * 0.02) / (2 * atr_v)))

def apply_styles(df):
    df_s = pd.DataFrame('', index=df.index, columns=df.columns)
    for col in ['변동', '상승금액', '상승률']:
        if col in df.columns:
            df_s.loc[df[col] > 0, col] += 'color: red;'
            df_s.loc[df[col] < 0, col] += 'color: blue;'
    if '매매상태' in df.columns:
        df_s.loc[df['매매상태'] == '매수추천', '매매상태'] += 'color: #d62728; font-weight: bold;'
        df_s.loc[df['매매상태'] == '매도필요', '매매상태'] += 'color: #1f77b4; font-weight: bold;'
        df_s.loc[df['매매상태'] == '보유중', '매매상태'] += 'color: #2ca02c; font-weight: bold;'
    if '제외사유' in df.columns:
        df_s.loc[df['제외사유'] != '', '제외사유'] += 'color: #888888; font-size: 0.9em;'
        df_s.loc[df['제외사유'] == '조건충족', '제외사유'] += 'color: #d62728; font-weight: bold;'
    for col in ['RS(90)', 'RS(10)']:
        if col in df.columns:
            df_s.loc[df[col] > 0, col] += 'color: #d62728; font-weight: bold;'
            df_s.loc[df[col] <= 0, col] += 'color: #bbbbbb;'
    if '순위' in df.columns:
        for idx, rank in df['순위'].items():
            if pd.notna(rank):
                if rank <= 10: df_s.loc[idx, :] += 'background-color: rgba(255, 235, 156, 0.4);' 
                elif rank <= 20: df_s.loc[idx, :] += 'background-color: rgba(198, 239, 206, 0.4);' 
                elif rank <= 30: df_s.loc[idx, :] += 'background-color: rgba(189, 215, 238, 0.4);' 
    return df_s

def display_trade_list(data, title, button_label, key_prefix, target_date, is_latest_date, market_type, holdings_df, top_n_cfg, account_total=0.0):
    with st.expander(f"🚨 {title} ({len(data)}개)", expanded=True):
        if data.empty:
            st.write(f"해당 종목이 없습니다.")
            return
        target_amount = account_total * ((100.0 / top_n_cfg) / 100.0) if top_n_cfg > 0 else 0.0
        for _, row in data.iterrows():
            ticker = row['ticker']
            c1, c2 = st.columns([4, 1])
            c1.markdown(f"**{row['종목명']} ({ticker})** - 이격도: {row['이격도']:+.2f}%", unsafe_allow_html=True)
            if is_latest_date:
                with c2.popover(button_label):
                    p_key, q_key, acc_key = f"p_{key_prefix}_{ticker}", f"q_{key_prefix}_{ticker}", f"acc_{key_prefix}_{ticker}"
                    input_price = st.number_input(f"{button_label}가", value=float(row['종가']), key=p_key)
                    if button_label == '매수':
                        st.number_input("운용계좌 총액", value=account_total, step=1000000.0, key=acc_key, on_change=calc_buy_qty_atr, args=(acc_key, q_key, row.get('atr', 0)))
                        calc_qty = max(1.0, (target_amount / input_price) if input_price > 0 else 1.0)
                        input_qty = st.number_input("매수수량", value=float(int(calc_qty)) if market_type=="KR" else calc_qty, min_value=0.0, key=q_key)
                    else:
                        matched_h = holdings_df[holdings_df['ticker'].str.strip().str.upper() == ticker]
                        def_qty = float(matched_h.iloc[0].get('quantity', 1.0)) if not matched_h.empty else 1.0
                        input_qty = st.number_input("매도수량", value=def_qty, min_value=0.0, key=q_key)
                        
                    if st.button("확인", key=f"btn_{key_prefix}_{ticker}"):
                        update_holdings(ticker, 'SELL' if '매도' in title else 'BUY', input_price, target_date, input_qty, market_type)

st.markdown("##### 📈 Hybrid Dual Alpha Dashboard")

if 'db_settings_loaded' not in st.session_state:
    try:
        res = supabase.table("strategy_settings").select("*").eq("id", 1).execute()
        if res.data:
            db_cfg = res.data[0]
            st.session_state.update(db_cfg)
    except: pass
    st.session_state['db_settings_loaded'] = True

with st.sidebar:
    st.markdown("### ⚙️ 알파 매매전략 설정")
    market_type = st.radio("Market", ["KR", "US"], horizontal=True)
    all_dates = get_available_dates()
    selected_date = st.date_input("Date", value=pd.to_datetime(all_dates[0]) if all_dates else None)
    target_date_str = pd.to_datetime(selected_date).strftime('%Y-%m-%d') if selected_date else ""
    
    market_safe, stop_new_buy = get_market_regime(market_type, target_date_str)
    strategy_mode = st.radio("운용 모드 선택", ["자동 감지 모드", "상승장 세팅 (Bull)", "하락장 세팅 (Bear)"], index=0)
    is_bull = True if strategy_mode == "상승장 세팅 (Bull)" else (False if strategy_mode == "하락장 세팅 (Bear)" else market_safe)
    rebalance_cycle = st.selectbox("리밸런싱 주기", ["상시 (빈자리 즉시 채우기)", "주기 (매주 수요일)"])

    if is_bull:
        st.success("🟢 상승장 모드 (Bull Market)")
        top_n_cfg = st.number_input("편입 종목 수", value=st.session_state.get('bull_top_n', 5))
        sl_cfg = st.number_input("손절 임계값 (%)", value=st.session_state.get('bull_sl', -10.0))
    else:
        st.error("🔴 하락장 모드 (Bear Market)")
        top_n_cfg = st.number_input("편입 종목 수", value=st.session_state.get('bear_top_n', 3))
        sl_cfg = st.number_input("손절 임계값 (%)", value=st.session_state.get('bear_sl', -6.0))

    if stop_new_buy: st.warning("⚠️ MA50 3일 연속 하회 감지: 신규 매수 중지")

    cap_key = "us_capital" if market_type == "US" else "kr_capital"
    account_total_input = st.number_input(f"💰 [{market_type}] 총 운용 자금", value=float(st.session_state.get(cap_key, 20000000.0)), step=500000.0)
    st.session_state[cap_key] = account_total_input

df_display = get_data(selected_date, all_dates, market_type, top_n_cfg, sl_cfg, rebalance_cycle, is_bull, stop_new_buy)

if df_display is not None:
    tab1, tab4, tab5 = st.tabs(["Overview", "🚀 알파 시그널", "📊 성과 분석"])
    
    with tab1:
        # 💡 수정 1: 제외사유를 MA20 뒤로 이동
        col_order = ['순위', '변동', '매매상태', '종목명', '이격도', 'MOT', 'RS(90)', 'RS(10)', 'MA20', '제외사유', '종가', '상승금액', '상승률', 'ticker'] 
        df_target = df_display.head(100)[col_order].copy()
        
        # 💡 수정 2: format 설정을 통해 모든 값 소수점 2자리로 통일 (종가, MA20, 상승금액 등 포함)
        event = st.dataframe(
            df_target.style.apply(apply_styles, axis=None).format({
                '이격도': lambda x: f"{x:+.2f}%" if x != 0 else "-", 
                'MOT': '{:.2f}',
                'RS(90)': '{:.2f}',
                'RS(10)': '{:.2f}',
                '종가': '{:,.2f}', 
                'MA20': '{:,.2f}',
                '상승금액': '{:+,.2f}', 
                '상승률': '{:+.2f}%'
            }), 
            hide_index=True, use_container_width=True, on_select="rerun", selection_mode="single-row"
        )
        if event and event.get("selection", {}).get("rows"):
            st.session_state['selected_ticker_from_table'] = df_target.iloc[event["selection"]["rows"][0]]['ticker']
            st.session_state['trigger_scroll'] = True

    with tab4:
        st.markdown("##### 📋 시스템 매매 지시서")
        # (이하 생략: 기존 tab4 코드와 동일)
        pass 

    with tab5:
        st.markdown(f"##### 📊 {market_type} 시장 성과 분석")
        # (이하 생략: 기존 tab5 코드와 동일)
        pass

    st.divider()
    st.markdown("<div id='chart-section'></div>", unsafe_allow_html=True)
    st.markdown("##### 📉 통합 추이 차트")
    if st.session_state.get('trigger_scroll'):
        scroll_to_chart()
        st.session_state['trigger_scroll'] = False 

    top100_tickers = df_display.head(100)['ticker'].tolist()
    if st.session_state.get('selected_ticker_from_table') and st.session_state['selected_ticker_from_table'] not in top100_tickers:
        top100_tickers.append(st.session_state['selected_ticker_from_table'])
        
    ticker_name_map = dict(zip(df_display['ticker'], df_display['종목명']))
    default_ticker = st.session_state.get('selected_ticker_from_table', top100_tickers[0] if top100_tickers else None)
    
    sel_ticker = st.selectbox("분석할 종목 선택", options=top100_tickers, index=top100_tickers.index(default_ticker) if default_ticker in top100_tickers else 0, format_func=lambda x: ticker_name_map.get(x, x))
    if sel_ticker:
        draw_integrated_chart(sel_ticker, market_type, ticker_name_map)
