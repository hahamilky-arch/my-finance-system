import streamlit as st
import pandas as pd
import numpy as np
import plotly.graph_objects as gg
import plotly.express as px
import streamlit.components.v1 as components
from db import supabase, get_holdings_table, update_holdings, get_market_regime, get_available_dates
from strategy import get_data
from charts import draw_integrated_chart, draw_attribution_charts
from gemini_analyzer import analyze_stock_with_gemini, get_remaining_quota, MAX_DAILY_QUOTA

st.set_page_config(layout="wide")

st.markdown("<div id='top-section'></div>", unsafe_allow_html=True)
st.markdown("""
    <style>
    .block-container { padding-top: 2rem !important; padding-bottom: 2rem !important; }
    html, body, [class*="st-"] { font-size: 14px !important; }
    h5 { font-size: 1.2rem !important; margin-bottom: 0.5rem !important; }
    .floating-btn-left {
        position: fixed; bottom: 25px; left: 25px;
        background: linear-gradient(135deg, #2b5876 0%, #4e4376 100%);
        color: white !important; border-radius: 30px; padding: 10px 18px;
        font-weight: bold; box-shadow: 0 4px 15px rgba(0,0,0,0.2);
        cursor: pointer; z-index: 99999; text-decoration: none;
    }
    .backup-tag {
        background-color: #fff3cd; color: #856404; font-size: 0.85em; font-weight: bold;
        padding: 2px 8px; border-radius: 6px; border: 1px solid #ffeeba; margin-left: 6px;
        display: inline-block;
    }
    .primary-tag {
        background-color: #e3f2fd; color: #0d47a1; font-size: 0.85em; font-weight: bold;
        padding: 2px 8px; border-radius: 6px; border: 1px solid #bbdefb; margin-left: 6px;
        display: inline-block;
    }
    </style>
    <a href="#top-section" class="floating-btn-left"><span>⬆️</span> <span>위로</span></a>
""", unsafe_allow_html=True)

def scroll_to_chart():
    components.html("<script>setTimeout(function(){const el=window.parent.document.getElementById('chart-section');if(el)el.scrollIntoView({behavior:'smooth'});},100);</script>", height=0)

# 수급 및 매매상태 스타일링 적용 함수
def apply_styles(df):
    df_s = pd.DataFrame('', index=df.index, columns=df.columns)
    
    for col in ['변동', '상승금액', '상승률']:
        if col in df.columns:
            df_s.loc[df[col] > 0, col] += 'color: red;'
            df_s.loc[df[col] < 0, col] += 'color: blue;'
    if '상태' in df.columns:
        df_s.loc[df['상태'] == '추천', '상태'] += 'color: #d62728; font-weight: bold;'
        df_s.loc[df['상태'] == '매도', '상태'] += 'color: #1f77b4; font-weight: bold;'
        df_s.loc[df['상태'] == '보유', '상태'] += 'color: #2ca02c; font-weight: bold;'
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

    if '수급' in df.columns:
        matched_mask = df['수급'] == '🔥 수급'
        df_s.loc[matched_mask, :] += 'background-color: rgba(200, 230, 201, 0.7); font-weight: bold;'
        df_s.loc[matched_mask, '수급'] += 'color: #2e7d32; font-weight: bold;'

    return df_s

def display_trade_list(data, title, button_label, key_prefix, target_date, is_latest_date, market_type, holdings_df, top_n_cfg, account_total=0.0, strategy_engine_mode="strat3_top7"):
    current_holdings_count = len(holdings_df) if not holdings_df.empty else 0
    needed_slots = max(0, top_n_cfg - current_holdings_count)
    
    with st.expander(f"🚨 {title} (보유: {current_holdings_count}/{top_n_cfg}개 | 필요: {needed_slots}개)", expanded=True):
        if data.empty:
            st.write(f"해당되는 {button_label} 종목이 없습니다.")
            return
        
        target_amount = account_total * ((100.0 / top_n_cfg) / 100.0) if top_n_cfg > 0 else 0.0
        fmt_str = f"${target_amount:,.2f}" if market_type == "US" else f"{target_amount:,.0f}원"

        if button_label == '매수':
            primary_data = data.iloc[:needed_slots] if needed_slots > 0 else pd.DataFrame()
            backup_data = data.iloc[needed_slots:needed_slots + 2]
            
            if needed_slots == 0:
                st.warning(f"⚠️ 현재 슬롯 만석입니다 ({current_holdings_count}/{top_n_cfg}개 보유 중). 하단 예비 종목을 참고하세요.")
        else:
            primary_data = data
            backup_data = pd.DataFrame()

        for p_idx, (_, row) in enumerate(primary_data.iterrows(), 1):
            ticker = row['ticker']
            c1, c2 = st.columns([4, 1])
            
            rank_val = int(row.get('순위', 0)) if pd.notna(row.get('순위')) else '-'
            rec_rank_val = row.get('추천순위', row.get('매수추천순위', ''))
            rec_rank_display = f"{rec_rank_val}위" if rec_rank_val != '' else '-'
            
            if '매도' in title:
                reason_desc = "레짐전환 현금화, ATR손절(-2.5x) 또는 트레일링스톱 도달"
                position_info = ""
                tag_html = ""
            else:
                reason_desc = f"진입 조건 충족 [추천순위: {rec_rank_display}]"
                target_pct = (100.0 / top_n_cfg) if top_n_cfg > 0 else 0.0
                atr_val = row.get('atr', 0.0)
                atr_str = f"{atr_val:,.2f}" if market_type == "US" else f"{atr_val:,.0f}"
                position_info = f"<br><span style='font-size: 0.85em; color: #1b5e20; font-weight: bold;'>📊 분산 금액: {fmt_str} (비중 {target_pct:.1f}%) | ATR: {atr_str}</span>"
                tag_html = f"<span class='primary-tag'>🎯 추천 {p_idx}</span>"

            card_html = (
                f"<div style='line-height: 1.6; margin-top: 4px;'>"
                f"<strong style='font-size: 1.1em; color: #111111;'>{row['종목명']}</strong> "
                f"<span style='font-size: 0.8em; color: #888888; margin-left: 4px;'>({ticker})</span> "
                f"{tag_html} "
                f"<span style='font-size: 0.8em; color: #1565c0; font-weight: bold; margin-left: 6px;'>[순위: {rank_val}위 | 추천: {rec_rank_display}]</span>"
                f"<br><span style='font-size: 0.85em; color: #d62728; font-weight: bold;'>📌 사유: {reason_desc}</span>"
                f"{position_info}"
                f"<br><span style='font-size: 0.85em; color: #444444;'>MOT: {row['MOT']:.2f} | RS(90): {row['RS(90)']:.2f} | 이격도: {row['이격도']:+.2f}%</span>"
                f"</div>"
            )
            c1.markdown(card_html, unsafe_allow_html=True)
            
            if is_latest_date:
                with c2.popover(button_label):
                    st.write(f"**{row['종목명']}**")
                    p_key, q_key, acc_key = f"p_{key_prefix}_{ticker}", f"q_{key_prefix}_{ticker}", f"acc_{key_prefix}_{ticker}"
                    input_price = st.number_input(f"{button_label}가", value=float(row['종가']), key=p_key)
                    if button_label == '매수':
                        st.number_input("계좌 총액", value=account_total, step=100.0 if market_type=="US" else 1000000.0, key=acc_key)
                        calc_qty = max(1.0, (target_amount / input_price) if input_price > 0 else 1.0)
                        
                        atr_v = float(row.get('atr', 0.0))
                        if atr_v > 0 and input_price > 0:
                            atr_suggest_qty = max(1.0, float(int((account_total * 0.02) / (2 * atr_v))))
                            atr_qty_str = f"{atr_suggest_qty:,.2f}" if market_type == "US" else f"{atr_suggest_qty:,.0f}"
                            st.caption(f"💡 자금관리 추천 수량: {atr_qty_str}주")
                            
                        input_qty = st.number_input("수량", value=calc_qty if market_type=="US" else float(int(calc_qty)), min_value=0.0, key=q_key)
                    else:
                        matched_h = holdings_df[holdings_df['ticker'].astype(str).str.strip().str.upper() == ticker.strip().upper()] if not holdings_df.empty else pd.DataFrame()
                        def_qty = float(matched_h.iloc[0].get('quantity', 1.0)) if not matched_h.empty else 1.0
                        input_qty = st.number_input("수량", value=def_qty, min_value=0.0, key=q_key)
                        
                    if st.button("확인", key=f"btn_{key_prefix}_{ticker}"):
                        update_holdings(ticker, 'SELL' if '매도' in title else 'BUY', input_price, target_date, input_qty, market_type)
            else:
                c2.markdown("<div style='color:#999999; font-size:0.85em; margin-top:8px; text-align:right;'>과거일 불가</div>", unsafe_allow_html=True)

        if not backup_data.empty:
            st.markdown("---")
            st.markdown("###### 💡 예비 목록 (대기/교체용)")
            for backup_idx, (_, row) in enumerate(backup_data.iterrows(), 1):
                ticker = row['ticker']
                c1, c2 = st.columns([4, 1])
                
                rank_val = int(row.get('순위', 0)) if pd.notna(row.get('순위')) else '-'
                rec_rank_val = row.get('추천순위', row.get('매수추천순위', ''))
                rec_rank_display = f"{rec_rank_val}위" if rec_rank_val != '' else '-'
                reason_desc = f"후순위 대체 종목 [추천순위: {rec_rank_display}]"
                
                atr_val = row.get('atr', 0.0)
                atr_str = f"{atr_val:,.2f}" if market_type == "US" else f"{atr_val:,.0f}"
                position_info = f"<br><span style='font-size: 0.85em; color: #856404; font-weight: bold;'>📊 예비 분산 금액: {fmt_str} | ATR: {atr_str}</span>"

                backup_html = (
                    f"<div style='line-height: 1.6; margin-top: 4px; background-color: #fffde7; padding: 8px 12px; border-radius: 6px; border-left: 4px solid #fbc02d;'>"
                    f"<strong style='font-size: 1.05em; color: #111111;'>{row['종목명']}</strong> "
                    f"<span style='font-size: 0.8em; color: #888888; margin-left: 4px;'>({ticker})</span> "
                    f"<span class='backup-tag'>💡 예비{backup_idx}</span> "
                    f"<span style='font-size: 0.8em; color: #d7ccc8; font-weight: bold; margin-left: 4px;'>[순위: {rank_val}위 | 추천: {rec_rank_display}]</span>"
                    f"<br><span style='font-size: 0.85em; color: #e65100; font-weight: bold;'>📌 사유: {reason_desc}</span>"
                    f"{position_info}"
                    f"<br><span style='font-size: 0.85em; color: #444444;'>MOT: {row['MOT']:.2f} | RS(90): {row['RS(90)']:.2f} | 이격도: {row['이격도']:+.2f}%</span>"
                    f"</div>"
                )
                c1.markdown(backup_html, unsafe_allow_html=True)
                
                if is_latest_date:
                    with c2.popover(f"예비매수"):
                        st.write(f"**[예비{backup_idx}] {row['종목명']}**")
                        p_key, q_key, acc_key = f"p_bk_{key_prefix}_{ticker}", f"q_bk_{key_prefix}_{ticker}", f"acc_bk_{key_prefix}_{ticker}"
                        input_price = st.number_input(f"매수가", value=float(row['종가']), key=p_key)
                        st.number_input("계좌 총액", value=account_total, step=100.0 if market_type=="US" else 1000000.0, key=acc_key)
                        calc_qty = max(1.0, (target_amount / input_price) if input_price > 0 else 1.0)
                        input_qty = st.number_input("수량", value=calc_qty if market_type=="US" else float(int(calc_qty)), min_value=0.0, key=q_key)
                            
                        if st.button("예비 매수 실행", key=f"btn_bk_{key_prefix}_{ticker}"):
                            update_holdings(ticker, 'BUY', input_price, target_date, input_qty, market_type)
                else:
                    c2.markdown("<div style='color:#999999; font-size:0.85em; margin-top:8px; text-align:right;'>과거일 불가</div>", unsafe_allow_html=True)

if 'db_settings_loaded' not in st.session_state:
    try:
        res = supabase.table("strategy_settings").select("*").eq("id", 1).execute()
        if res.data:
            db_cfg = res.data[0]
            st.session_state['kr_capital'] = float(db_cfg.get('kr_capital', 20000000.0))
            st.session_state['us_capital'] = float(db_cfg.get('us_capital', 6000.0))
            st.session_state['bull_top_n'] = int(db_cfg.get('bull_top_n', 7))
            st.session_state['bull_sl'] = float(db_cfg.get('bull_sl', -5.0))
            st.session_state['bear_top_n'] = int(db_cfg.get('bear_top_n', 4)) 
            st.session_state['bear_sl'] = float(db_cfg.get('bear_sl', -5.0))
            st.session_state['strategy_engine_mode'] = db_cfg.get('strategy_engine_mode', 'strat3_top7')
    except Exception:
        pass
    st.session_state['db_settings_loaded'] = True

all_dates = get_available_dates()
latest_date_default = pd.to_datetime(all_dates[0]) if all_dates else None

with st.sidebar:
    st.markdown("### ⚙️ 알파 매매전략 설정")
    
    market_type = st.radio("Market", ["KR", "US"], horizontal=True)
    selected_date = st.date_input("Date", value=latest_date_default)
    target_date_str = pd.to_datetime(selected_date).strftime('%Y-%m-%d') if selected_date else ""
    
    st.divider()

    default_engine_idx = 1 if market_type == "US" else 0

    strategy_engine_mode = st.radio(
        "💡 전략 엔진 선택",
        [
            "🔥 전략 3: Top 7 레짐+ATR",
            "🚀 단기 타점 모멘텀 (15%+ 랠리)", 
            "🌐 Ultimate 듀얼 모멘텀 (추세)"
        ],
        index=default_engine_idx
    )
    
    if "전략 3" in strategy_engine_mode:
        current_engine_key = "strat3_top7"
    elif "단기" in strategy_engine_mode:
        current_engine_key = "short_term"
    else:
        current_engine_key = "ultimate_dual"
        
    st.session_state['strategy_engine_mode'] = current_engine_key

    market_safe, stop_new_buy, reduce_holdings = get_market_regime(market_type, target_date_str)
    strategy_mode = st.radio("운용 모드 선택", ["자동 감지 모드", "상승장 세팅 (Bull)", "하락장 세팅 (Bear)"], index=0)
    is_bull = True if strategy_mode == "상승장 세팅 (Bull)" else (False if strategy_mode == "하락장 세팅 (Bear)" else market_safe)
    rebalance_cycle = st.selectbox("리밸런싱 주기", ["상시 (빈자리 즉시 채우기)", "주기 (매주 수요일)"])

    if current_engine_key == "strat3_top7":
        st.success("🔥 전략 3 모드: Top 7 / Rank≤15 / ATR 2.5x손절")
        top_n_cfg = 7
        sl_cfg = -2.5
        rank_exit_limit = 15
    elif current_engine_key == "short_term":
        st.info("🚀 단기 타점 모드: 상위 200위 / 15% 목표익절 / -5% 손절")
        top_n_cfg = st.session_state.get('bull_top_n', 4)
        sl_cfg = st.session_state.get('bull_sl', -5.0)
        rank_exit_limit = 200
    else:
        if is_bull:
            st.success("🟢 상승장 모드 (Bull Market)")
            top_n_cfg = st.session_state.get('bull_top_n', 5)
            sl_cfg = st.session_state.get('bull_sl', -10.0)
            rank_exit_limit = 60
        else:
            st.error("🔴 하락장 모드 (Bear Market)")
            top_n_cfg = st.session_state.get('bear_top_n', 3)
            sl_cfg = st.session_state.get('bear_sl', -6.0)
            rank_exit_limit = 30

    if stop_new_buy: 
        st.warning("⚠️ MA20 3일 연속 하회 감지: 신규 매수 중지")
    elif reduce_holdings:
        st.warning("⚠️ MA20 하회 감지: 보유 종목 비중 축소")
        
    st.divider()

    try:
        df_kr_chk = get_data(selected_date, all_dates, "KR", top_n_cfg, sl_cfg, rebalance_cycle, is_bull, stop_new_buy, reduce_holdings, strategy_engine_mode=current_engine_key)
        kr_buy_count = len(df_kr_chk[df_kr_chk['매매상태'] == '매수추천']) if df_kr_chk is not None else 0
    except Exception:
        kr_buy_count = 0

    try:
        df_us_chk = get_data(selected_date, all_dates, "US", top_n_cfg, sl_cfg, rebalance_cycle, is_bull, stop_new_buy, reduce_holdings, strategy_engine_mode=current_engine_key)
        us_buy_count = len(df_us_chk[df_us_chk['매매상태'] == '매수추천']) if df_us_chk is not None else 0
    except Exception:
        us_buy_count = 0

    col_side_kr, col_side_us = st.columns(2)
    col_side_kr.metric("KR추천", f"{kr_buy_count}개")
    col_side_us.metric("US추천", f"{us_buy_count}개")

col_title, col_auth_status = st.columns([3, 1])
with col_title:
    st.markdown("##### 📈 Quant Alpha Strategy")

with col_auth_status:
    if not st.session_state.get('trade_authenticated', False):
        with st.popover("🔑 잠금 해제", use_container_width=True):
            input_pwd_global = st.text_input("매매 비밀번호", type="password", key="global_pwd_input")
            if st.button("해제", key="btn_global_unlock", type="primary", use_container_width=True):
                if input_pwd_global == st.secrets.get("TRADE_PASSWORD", "1234"):
                    st.session_state['trade_authenticated'] = True
                    st.rerun()
                else:
                    st.error("비밀번호 불일치")
    else:
        if st.button("🔒 다시 잠금", key="btn_global_lock", use_container_width=True):
            st.session_state['trade_authenticated'] = False
            st.rerun()

cap_key = "us_capital" if market_type == "US" else "kr_capital"
default_cap = st.session_state.get(cap_key, 6000.0 if market_type == "US" else 20000000.0)
account_total_input = float(default_cap)

df_display = get_data(selected_date, all_dates, market_type, top_n_cfg, sl_cfg, rebalance_cycle, is_bull, stop_new_buy, reduce_holdings, strategy_engine_mode=current_engine_key)

if df_display is not None:
    if '매수추천순위' in df_display.columns:
        df_display = df_display.rename(columns={'매수추천순위': '추천순위'})

    if '매매상태' in df_display.columns:
        df_display['매매상태'] = df_display['매매상태'].replace({
            '매수추천': '추천',
            '매수필요': '매수',
            '매도필요': '매도',
            '보유중': '보유'
        })

    is_latest_date = (target_date_str == max(all_dates)) if all_dates and target_date_str else False
    is_authenticated = st.session_state.get('trade_authenticated', False)

    current_table_name = get_holdings_table(market_type)
    try:
        holdings_res = supabase.table(current_table_name).select("*").is_("sell_date", "null").execute()
        holdings_db = pd.DataFrame(holdings_res.data) if holdings_res.data else pd.DataFrame()
    except Exception:
        holdings_db = pd.DataFrame()

    current_holdings_count = len(holdings_db) if not holdings_db.empty else 0
    needed_slots = max(0, top_n_cfg - current_holdings_count)

    tab1, tab2, tab4, tab5 = st.tabs(["Overview", "📊 매매동향 분석", "🚀 알파 시그널", "📈 성과 분석"])
    
    with tab1:
        st.markdown("###### 📊 시장 및 시그널 요약")
        
        c1, c2, c3, c4 = st.columns(4)
        c1.metric("전략 모드", "🔥 전략 3 (Top 7)" if current_engine_key == "strat3_top7" else ("🚀 단기 타점" if current_engine_key == "short_term" else ("🟢 강세장" if is_bull else "🔴 약세장")))
        c2.metric("신규 매수 상태", "🛑 중지" if stop_new_buy else ("⚠️ 비중축소" if reduce_holdings else "✅ 허용"))
        
        buy_cnt = len(df_display[df_display['매매상태'] == '추천'])
        buy_cnt_display = min(buy_cnt, needed_slots)
        c3.metric("오늘의 추천 종목", f"{buy_cnt_display}개", delta=f"슬롯 잔여: {needed_slots}/{top_n_cfg}")
        
        sell_cnt = len(df_display[df_display['매매상태'] == '매도'])
        c4.metric("오늘의 매도 종목", f"{sell_cnt}개")
        
        matched_liq_stock_names = set()
        
        if market_type == "KR":
            with st.expander("💵 실시간 수급 스냅샷 (기본 접힘)", expanded=False):
                try:
                    liq_res = supabase.table("daily_top_liquidity").select("*").order("trade_date", desc=True).limit(300).execute()
                    df_liq_all = pd.DataFrame(liq_res.data) if liq_res.data else pd.DataFrame()
                except Exception:
                    df_liq_all = pd.DataFrame()

                if not df_liq_all.empty:
                    df_liq_all['trade_date_str'] = df_liq_all['trade_date'].astype(str)
                    available_liq_dates = sorted(df_liq_all['trade_date_str'].unique(), reverse=True)
                    latest_available_date = pd.to_datetime(available_liq_dates[0]).date() if available_liq_dates else selected_date
                    
                    sel_liq_date_input = st.date_input("조회일자", value=latest_available_date, key="sel_liq_date_calendar")
                    sel_liq_date_str = pd.to_datetime(sel_liq_date_input).strftime('%Y-%m-%d')
                    
                    df_target_liq = df_liq_all[df_liq_all['trade_date_str'] == sel_liq_date_str].sort_values('rank')
                    
                    if not df_target_liq.empty:
                        matched_liq_stock_names = set(df_target_liq['name'].astype(str).str.strip().tolist())

                        st.markdown(f"###### 🔥 {sel_liq_date_str} 수급 TOP 4")
                        m_cols = st.columns(4)
                        for i, (_, r) in enumerate(df_target_liq.head(4).iterrows()):
                            with m_cols[i]:
                                net_tot_val = float(r.get('net_total', 0.0))
                                chg_val = float(r.get('change_rate', 0.0))
                                close_p = float(r.get('close_price', 0.0))
                                st.metric(
                                    label=f"{r['rank']}위 {r['name']}", 
                                    value=f"{close_p:,.0f}원", 
                                    delta=f"{chg_val:+.2f}% (합계 {net_tot_val:,.0f})"
                                )
                        
                        st.write("")
                        col_left_liq, col_right_liq = st.columns([1, 1.2])
                        
                        with col_left_liq:
                            st.markdown("###### 🏆 수급 자주 노출 종목 (누적)")
                            freq_df = df_liq_all.groupby('name').agg(
                                노출횟수=('trade_date', 'nunique'),
                                최근순위=('rank', 'min'),
                                평균등락률=('change_rate', 'mean')
                            ).reset_index().sort_values(by=['노출횟수', '최근순위'], ascending=[False, True]).head(10)
                            freq_df = freq_df.rename(columns={'name': '종목명'})
                            
                            st.dataframe(
                                freq_df.style.format({'평균등락률': '{:+.2f}%'}), 
                                hide_index=True, use_container_width=True
                            )

                        with col_right_liq:
                            st.markdown(f"###### 📋 당일 수급 상세")
                            disp_liq_cols = ['rank', 'name', 'close_price', 'change_rate', 'net_total', 'foreign_net', 'inst_net', 'large_volume', 'volume_power']
                            disp_liq = df_target_liq[disp_liq_cols].copy()
                            disp_liq = disp_liq.rename(columns={
                                'rank': '순위', 'name': '종목명', 'close_price': '현재가', 
                                'change_rate': '등락률', 'net_total': '합계(A+B)', 
                                'foreign_net': '외인(A)', 'inst_net': '기관(B)', 
                                'large_volume': '대량체결', 'volume_power': '거래강도'
                            })
                            
                            st.dataframe(
                                disp_liq.style.format({
                                    '현재가': '{:,.0f}', '등락률': '{:+.2f}%', 
                                    '합계(A+B)': '{:,.0f}', '외인(A)': '{:,.0f}', '기관(B)': '{:,.0f}', 
                                    '대량체결': '{:,.0f}', '거래강도': '{:.2f}'
                                }).map(lambda x: 'color: red;' if float(x) > 0 else 'color: blue;', subset=['등락률']),
                                hide_index=True, use_container_width=True
                            )
                    else:
                        st.warning(f"⚠️ {sel_liq_date_str} 데이터가 없습니다.")
                else:
                    st.info("💡 저장된 수급 데이터가 없습니다.")

        st.write("")
        
        with st.expander("📋 알파 시그널 전체 목록 (모멘텀 순위 상위 200위)", expanded=True):
            filter_opt = st.radio("빠른 필터", ["전체보기", "🔥 수급 종목만", "🔴 추천 종목만", "🔵 매도 종목만", "🟢 보유 종목만"], horizontal=True, label_visibility="collapsed")
            
            df_target = df_display.head(200).copy()
            df_target['수급포착'] = df_target['종목명'].apply(lambda nm: '🔥 수급' if str(nm).strip() in matched_liq_stock_names else '-')
            
            col_order = ['순위', '추천순위', '수급포착', '변동', '매매상태', '종목명', '이격도', 'MOT', 'RS(90)', 'RS(10)', 'MA20', '제외사유', '종가', '상승금액', '상승률', 'ticker'] 
            df_target = df_target[col_order].rename(columns={
                '추천순위': '추천순위',
                '수급포착': '수급',
                '매매상태': '상태',
                '이격도': '이격(%)'
            })
            
            if filter_opt == "🔥 수급 종목만":
                df_target = df_target[df_target['수급'] == '🔥 수급']
            elif filter_opt == "🔴 추천 종목만":
                df_target = df_target[df_target['상태'] == '추천']
            elif filter_opt == "🔵 매도 종목만":
                df_target = df_target[df_target['상태'] == '매도']
            elif filter_opt == "🟢 보유 종목만":
                df_target = df_target[df_target['상태'] == '보유']
            
            if df_target.empty:
                st.info("해당되는 종목이 없습니다.")
            else:
                fmt_dict = {
                    '이격(%)': lambda x: f"{x:+.2f}%" if x != 0 else "-", 
                    'MOT': '{:.2f}', 'RS(90)': '{:.2f}', 'RS(10)': '{:.2f}',
                    'MA20': '{:,.2f}' if market_type=='US' else '{:,.0f}',
                    '종가': '{:,.2f}' if market_type=='US' else '{:,.0f}',
                    '상승금액': '{:+,.2f}' if market_type=='US' else '{:+,.0f}',
                    '상승률': '{:+.2f}%'
                }
                
                column_config_cfg = {
                    "순위": st.column_config.NumberColumn("순위", width=40),
                    "추천순위": st.column_config.TextColumn("추천", width=40),
                    "수급": st.column_config.TextColumn("수급", width=65),
                    "변동": st.column_config.TextColumn("변동", width=40),
                    "상태": st.column_config.TextColumn("상태", width=55),
                    "종목명": st.column_config.TextColumn("종목명", width=110),
                    "이격(%)": st.column_config.TextColumn("이격(%)", width=75),
                    "MOT": st.column_config.NumberColumn("MOT", width=60),
                    "RS(90)": st.column_config.NumberColumn("RS(90)", width=65),
                    "RS(10)": st.column_config.NumberColumn("RS(10)", width=65),
                    "MA20": st.column_config.NumberColumn("MA20", width=80),
                    "제외사유": st.column_config.TextColumn("제외사유", width=95),
                    "종가": st.column_config.NumberColumn("종가", width=80),
                    "상승금액": st.column_config.NumberColumn("상승금액", width=80),
                    "상승률": st.column_config.NumberColumn("상승률", width=70),
                    "ticker": st.column_config.TextColumn("코드", width=65),
                }
                
                event = st.dataframe(
                    df_target.style.apply(apply_styles, axis=None).format(fmt_dict), 
                    column_config=column_config_cfg,
                    hide_index=True, 
                    use_container_width=False, 
                    on_select="rerun", 
                    selection_mode="single-row"
                )
                if event and event.get("selection", {}).get("rows"):
                    st.session_state['selected_ticker_from_table'] = df_target.iloc[event["selection"]["rows"][0]]['ticker']
                    st.session_state['trigger_scroll'] = True

    # ----------------------------------------------------
    # TAB 2: 매매동향 분석 (수급 지표 분석 & 정량 출력 고도화)
    # ----------------------------------------------------
    with tab2:
        col_t2_head, col_t2_date = st.columns([3, 1])
        with col_t2_head:
            st.markdown("##### 🏛️ 투자자별 & 프로그램 매매동향 분석 리포트")
        with col_t2_date:
            trend_target_date = st.date_input("조회일자", value=selected_date, key="trend_target_date_picker")
            trend_date_str = pd.to_datetime(trend_target_date).strftime('%Y-%m-%d')
        
        if not is_authenticated:
            st.info("🔒 상세 매매동향 및 수급 AI 분석은 우측 상단 **[🔑 잠금 해제]** 후 조회가 가능합니다.")
        else:
            try:
                res_inv_all = supabase.table("market_investor_trends").select("*").lte("trade_date", trend_date_str).order("trade_date", desc=True).limit(60).execute()
                df_inv_all = pd.DataFrame(res_inv_all.data) if res_inv_all.data else pd.DataFrame()
            except Exception:
                df_inv_all = pd.DataFrame()

            try:
                res_prog_all = supabase.table("market_program_trends").select("*").lte("trade_date", trend_date_str).order("trade_date", desc=True).limit(60).execute()
                df_prog_all = pd.DataFrame(res_prog_all.data) if res_prog_all.data else pd.DataFrame()
            except Exception:
                df_prog_all = pd.DataFrame()

            df_inv = df_inv_all[df_inv_all['trade_date'] == trend_date_str] if not df_inv_all.empty else pd.DataFrame()
            df_prog = df_prog_all[df_prog_all['trade_date'] == trend_date_str] if not df_prog_all.empty else pd.DataFrame()

            k_row = df_inv[df_inv['market_type'] == 'KOSPI'].iloc[0] if not df_inv.empty and not df_inv[df_inv['market_type'] == 'KOSPI'].empty else {}
            kq_row = df_inv[df_inv['market_type'] == 'KOSDAQ'].iloc[0] if not df_inv.empty and not df_inv[df_inv['market_type'] == 'KOSDAQ'].empty else {}
            p_row = df_prog.iloc[0] if not df_prog.empty else {}

            # ----------------------------------------------------
            # 파생 수급 지표 계산 (누적 수급, Z-Score, 연속성, 다이버전스)
            # ----------------------------------------------------
            df_k_all = df_inv_all[df_inv_all['market_type'] == 'KOSPI'].sort_values('trade_date', ascending=False) if not df_inv_all.empty else pd.DataFrame()
            df_kq_all = df_inv_all[df_inv_all['market_type'] == 'KOSDAQ'].sort_values('trade_date', ascending=False) if not df_inv_all.empty else pd.DataFrame()
            df_p_sorted = df_prog_all.sort_values('trade_date', ascending=False) if not df_prog_all.empty else pd.DataFrame()

            # 1. N일 누적 수급
            k_f_5d = int(df_k_all.head(5)['foreign_net'].sum()) if not df_k_all.empty else 0
            k_f_10d = int(df_k_all.head(10)['foreign_net'].sum()) if not df_k_all.empty else 0
            k_f_20d = int(df_k_all.head(20)['foreign_net'].sum()) if not df_k_all.empty else 0
            
            k_inst_5d = int(df_k_all.head(5)['institution_net'].sum()) if not df_k_all.empty else 0
            k_inst_10d = int(df_k_all.head(10)['institution_net'].sum()) if not df_k_all.empty else 0
            k_inst_20d = int(df_k_all.head(20)['institution_net'].sum()) if not df_k_all.empty else 0

            kq_f_5d = int(df_kq_all.head(5)['foreign_net'].sum()) if not df_kq_all.empty else 0
            kq_f_10d = int(df_kq_all.head(10)['foreign_net'].sum()) if not df_kq_all.empty else 0
            kq_f_20d = int(df_kq_all.head(20)['foreign_net'].sum()) if not df_kq_all.empty else 0

            p_non_5d = int(df_p_sorted.head(5)['non_arbitrage_net'].sum()) if not df_p_sorted.empty else 0
            p_non_10d = int(df_p_sorted.head(10)['non_arbitrage_net'].sum()) if not df_p_sorted.empty else 0
            p_non_20d = int(df_p_sorted.head(20)['non_arbitrage_net'].sum()) if not df_p_sorted.empty else 0

            # 2. 수급 연속성 (최근 5영업일 중 매수 유입 일수)
            k_f_days = int((df_k_all.head(5)['foreign_net'] > 0).sum()) if not df_k_all.empty else 0
            p_non_days = int((df_p_sorted.head(5)['non_arbitrage_net'] > 0).sum()) if not df_p_sorted.empty else 0

            # 3. 비차익 수급 Z-Score (20일 기준 유동성 강도)
            if not df_p_sorted.empty and len(df_p_sorted) >= 5:
                p_non_20_series = df_p_sorted.head(20)['non_arbitrage_net'].astype(float)
                mean_20 = p_non_20_series.mean()
                std_20 = p_non_20_series.std()
                p_non_val = float(p_row.get('non_arbitrage_net', 0)) if not p_row.empty else 0.0
                p_zscore = ((p_non_val - mean_20) / std_20) if std_20 > 0 else 0.0
            else:
                p_zscore = 0.0

            if p_zscore >= 1.5:
                z_tag = "🔥 강한 수급 유입 (Z ≥ +1.5)"
            elif p_zscore <= -1.5:
                z_tag = "❄️ 강한 수급 이탈 (Z ≤ -1.5)"
            else:
                z_tag = "⚖️ 정상 수급 범위"

            # 4. 수급 다이버전스 감지 (지수 리시빙 조건)
            divergence_msg = ""
            if market_safe and p_non_5d < 0 and k_f_5d < 0:
                divergence_msg = "⚠️ [약세 다이버전스] 지수는 MA20 위에 있으나, 최근 5일 비차익/외국인 누적 수급이 연속 유출 중입니다. (단기 상단 경계)"
            elif not market_safe and p_non_5d > 0 and k_f_5d > 0:
                divergence_msg = "💡 [강세 다이버전스] 지수는 MA20 밑에 있으나, 최근 5일 스마트머니(외인/비차익)가 지속 저점 매수 중입니다. (반등 가능성)"

            # ----------------------------------------------------
            # 영역 1: 당일 매매동향 및 수급 강도 요약
            # ----------------------------------------------------
            with st.expander(f"📊 [{trend_date_str}] 당일 매매동향 & 스마트머니 수급 지표", expanded=True):
                if divergence_msg:
                    st.warning(divergence_msg)

                st.markdown("###### 1. 당일 투자자별/프로그램 순매수 (백만원)")
                col_dt1, col_dt2 = st.columns(2)
                
                with col_dt1:
                    disp_inv_summary = pd.DataFrame([
                        {
                            "시장": "KOSPI",
                            "외국인": int(k_row.get('foreign_net', 0)),
                            "개인": int(k_row.get('individual_net', 0)),
                            "기관계": int(k_row.get('institution_net', 0))
                        },
                        {
                            "시장": "KOSDAQ",
                            "외국인": int(kq_row.get('foreign_net', 0)),
                            "개인": int(kq_row.get('individual_net', 0)),
                            "기관계": int(kq_row.get('institution_net', 0))
                        }
                    ])
                    st.dataframe(
                        disp_inv_summary.style.format({"외국인": "{:+,d}", "개인": "{:+,d}", "기관계": "{:+,d}"})
                        .map(lambda v: 'color: red;' if v > 0 else ('color: blue;' if v < 0 else ''), subset=['외국인', '개인', '기관계']),
                        hide_index=True, use_container_width=True
                    )

                with col_dt2:
                    p_tot_val = int(p_row.get('total_net', 0)) if not df_prog.empty and not p_row.empty else 0
                    p_arb_val = int(p_row.get('arbitrage_net', 0)) if not df_prog.empty and not p_row.empty else 0
                    p_non_val_int = int(p_row.get('non_arbitrage_net', 0)) if not df_prog.empty and not p_row.empty else 0

                    disp_prog_summary = pd.DataFrame([
                        {
                            "구분": "프로그램",
                            "차익": p_arb_val,
                            "비차익": p_non_val_int,
                            "전체": p_tot_val
                        }
                    ])
                    st.dataframe(
                        disp_prog_summary.style.format({"차익": "{:+,d}", "비차익": "{:+,d}", "전체": "{:+,d}"})
                        .map(lambda v: 'color: red;' if v > 0 else ('color: blue;' if v < 0 else ''), subset=['차익', '비차익', '전체']),
                        hide_index=True, use_container_width=True
                    )

                st.markdown("###### 2. 수급 강도 & 연속성 지표 (20일 기준)")
                m_sq1, m_sq2, m_sq3, m_sq4 = st.columns(4)
                m_sq1.metric("비차익 수급 Z-Score", f"{p_zscore:+.2f}", delta=z_tag, delta_color="off")
                m_sq2.metric("비차익 5일 누적", f"{p_non_5d:+,d} 백만원", delta=f"5일 중 {p_non_days}일 순매수")
                m_sq3.metric("KOSPI 외인 5일 누적", f"{k_f_5d:+,d} 백만원", delta=f"5일 중 {k_f_days}일 순매수")
                m_sq4.metric("KOSDAQ 외인 5일 누적", f"{kq_f_5d:+,d} 백만원")

            # ----------------------------------------------------
            # 영역 2: 누적 수급 추세 지표 (5일 / 10일 / 20일)
            # ----------------------------------------------------
            with st.expander("📈 기간별 누적 수급 추세 (5일 / 10일 / 20일)", expanded=True):
                df_cum_summary = pd.DataFrame([
                    {
                        "구분": "KOSPI 외국인",
                        "5일 누적": k_f_5d, "10일 누적": k_f_10d, "20일 누적": k_f_20d
                    },
                    {
                        "구분": "KOSPI 기관계",
                        "5일 누적": k_inst_5d, "10일 누적": k_inst_10d, "20일 누적": k_inst_20d
                    },
                    {
                        "구분": "KOSDAQ 외국인",
                        "5일 누적": kq_f_5d, "10일 누적": kq_f_10d, "20일 누적": kq_f_20d
                    },
                    {
                        "구분": "비차익 프로그램",
                        "5일 누적": p_non_5d, "10일 누적": p_non_10d, "20일 누적": p_non_20d
                    }
                ])
                st.dataframe(
                    df_cum_summary.style.format({
                        "5일 누적": "{:+,d} 백만원", "10일 누적": "{:+,d} 백만원", "20일 누적": "{:+,d} 백만원"
                    }).map(lambda v: 'color: red;' if isinstance(v, (int, float)) and v > 0 else ('color: blue;' if isinstance(v, (int, float)) and v < 0 else ''), subset=["5일 누적", "10일 누적", "20일 누적"]),
                    hide_index=True, use_container_width=True
                )

                if not df_inv_all.empty:
                    df_k_trend = df_inv_all[df_inv_all['market_type'] == 'KOSPI'].sort_values('trade_date').copy()
                    df_kq_trend = df_inv_all[df_inv_all['market_type'] == 'KOSDAQ'].sort_values('trade_date').copy()

                    col_ch1, col_ch2 = st.columns(2)
                    with col_ch1:
                        fig_k_tr = gg.Figure()
                        fig_k_tr.add_trace(gg.Scatter(x=df_k_trend['trade_date'], y=df_k_trend['foreign_net'], mode='lines+markers', name='외국인', line=dict(color='#d62728')))
                        fig_k_tr.add_trace(gg.Scatter(x=df_k_trend['trade_date'], y=df_k_trend['institution_net'], mode='lines+markers', name='기관계', line=dict(color='#2ca02c')))
                        fig_k_tr.add_trace(gg.Scatter(x=df_k_trend['trade_date'], y=df_k_trend['individual_net'], mode='lines+markers', name='개인', line=dict(color='#1f77b4')))
                        fig_k_tr.update_layout(title="KOSPI 주체별 매매 추이 (백만원)", height=300, margin=dict(l=10, r=10, t=35, b=10), legend=dict(orientation="h", yanchor="bottom", y=1.02, xanchor="right", x=1))
                        st.plotly_chart(fig_k_tr, use_container_width=True)

                    with col_ch2:
                        fig_kq_tr = gg.Figure()
                        fig_kq_tr.add_trace(gg.Scatter(x=df_kq_trend['trade_date'], y=df_kq_trend['foreign_net'], mode='lines+markers', name='외국인', line=dict(color='#d62728')))
                        fig_kq_tr.add_trace(gg.Scatter(x=df_kq_trend['trade_date'], y=df_kq_trend['institution_net'], mode='lines+markers', name='기관계', line=dict(color='#2ca02c')))
                        fig_kq_tr.add_trace(gg.Scatter(x=df_kq_trend['trade_date'], y=df_kq_trend['individual_net'], mode='lines+markers', name='개인', line=dict(color='#1f77b4')))
                        fig_kq_tr.update_layout(title="KOSDAQ 주체별 매매 추이 (백만원)", height=300, margin=dict(l=10, r=10, t=35, b=10), legend=dict(orientation="h", yanchor="bottom", y=1.02, xanchor="right", x=1))
                        st.plotly_chart(fig_kq_tr, use_container_width=True)

                if not df_prog_all.empty:
                    df_p_trend = df_prog_all.sort_values('trade_date').copy()
                    fig_p_tr = gg.Figure()
                    fig_p_tr.add_trace(gg.Bar(x=df_p_trend['trade_date'], y=df_p_trend['non_arbitrage_net'], name='비차익', marker_color='#ff7f0e'))
                    fig_p_tr.add_trace(gg.Bar(x=df_p_trend['trade_date'], y=df_p_trend['arbitrage_net'], name='차익', marker_color='#1f77b4'))
                    fig_p_tr.update_layout(title="프로그램 매매 추이 (백만원)", barmode='group', height=280, margin=dict(l=10, r=10, t=35, b=10), legend=dict(orientation="h", yanchor="bottom", y=1.02, xanchor="right", x=1))
                    st.plotly_chart(fig_p_tr, use_container_width=True)

            # ----------------------------------------------------
            # 영역 3: Gemini AI 수급 흐름 분석 프롬프트 (파생 지표 포함)
            # ----------------------------------------------------
            with st.expander("🤖 Gemini AI 수급 분석 및 고도화 프롬프트", expanded=True):
                kf_val = int(k_row.get('foreign_net', 0)) if not df_inv.empty and not k_row.empty else 0
                ki_val = int(k_row.get('individual_net', 0)) if not df_inv.empty and not k_row.empty else 0
                kin_val = int(k_row.get('institution_net', 0)) if not df_inv.empty and not k_row.empty else 0
                
                kqf_val = int(kq_row.get('foreign_net', 0)) if not df_inv.empty and not kq_row.empty else 0
                kqi_val = int(kq_row.get('individual_net', 0)) if not df_inv.empty and not kq_row.empty else 0
                kqin_val = int(kq_row.get('institution_net', 0)) if not df_inv.empty and not kq_row.empty else 0

                prompt_text = f"""[당일 및 수급 파생 지표 종합 분석 요청]
- 분석 일자: {trend_date_str}

1. 당일 수급 현황 (백만원):
  * KOSPI: 외국인({kf_val:+,d}), 개인({ki_val:+,d}), 기관계({kin_val:+,d})
  * KOSDAQ: 외국인({kqf_val:+,d}), 개인({kqi_val:+,d}), 기관계({kqin_val:+,d})
  * 비차익 프로그램: 당일({int(p_non_val):+,d})

2. 수급 강도 및 연속성 파생 지표:
  * 비차익 수급 Z-Score (20일 기준): {p_zscore:+.2f} ({z_tag})
  * KOSPI 외국인 연속성: 최근 5영업일 중 {k_f_days}일 순매수 유입
  * 비차익 프로그램 연속성: 최근 5영업일 중 {p_non_days}일 순매수 유입
  * 지수-수급 다이버전스: {divergence_msg if divergence_msg else "특이사항 없음 (지수 수급 일치)"}

3. N일 누적 수급 동향 (5일 / 10일 / 20일) (백만원):
  * KOSPI 외국인: 5일({k_f_5d:+,d}), 10일({k_f_10d:+,d}), 20일({k_f_20d:+,d})
  * KOSPI 기관계: 5일({k_inst_5d:+,d}), 10일({k_inst_10d:+,d}), 20일({k_inst_20d:+,d})
  * KOSDAQ 외국인: 5일({kq_f_5d:+,d}), 10일({kq_f_10d:+,d}), 20일({kq_f_20d:+,d})
  * 비차익 프로그램: 5일({p_non_5d:+,d}), 10일({p_non_10d:+,d}), 20일({p_non_20d:+,d})

[분석 요구사항]
1. 당일 스마트머니 수급 특이점 및 외국인/기관 매수·매도 배경 심층 분석
2. 5일/10일/20일 누적 수급 흐름을 통한 주체별 자금 이동의 지속성 판단
3. 비차익 Z-Score 및 연속성 지표가 가리키는 현 시장의 유동성 레벨 판별
4. 현 수급 환경에 맞춰 포트폴리오 관찰 시 주의해야 할 주도 업종 및 수급 리스크 요인 정리"""

                st.code(prompt_text, language="markdown")

                if st.button("✨ Gemini AI 수급 종합 분석 실행", type="primary", use_container_width=True):
                    with st.spinner("🤖 당일 수급 지표 및 N일 누적 수급 흐름을 종합 분석 중입니다..."):
                        analysis_res = analyze_stock_with_gemini("MARKET_TREND", "코스피/코스닥 수급동향", {"MOT": 0, "RS(90)": 0, "이격도": 0, "종가": 0}, prompt_text)
                    st.success("✅ 수급 분석 완료")
                    st.markdown(analysis_res)

            # ----------------------------------------------------
            # 영역 4: 수동 매매동향 데이터 입력창
            # ----------------------------------------------------
            with st.expander(f"📝 [{trend_date_str}] 매매동향 수동 등록/수정 (기본 접힘)", expanded=False):
                col_in1, col_in2 = st.columns(2)
                with col_in1:
                    st.markdown("###### 📊 코스피 (단위: 백만원)")
                    kospi_foreign = st.number_input("코스피 외국인", value=kf_val, step=1000, key="in_kp_f")
                    kospi_individual = st.number_input("코스피 개인", value=ki_val, step=1000, key="in_kp_i")
                    kospi_institution = st.number_input("코스피 기관계", value=kin_val, step=1000, key="in_kp_inst")

                with col_in2:
                    st.markdown("###### 📊 코스닥 (단위: 백만원)")
                    kosdaq_foreign = st.number_input("코스닥 외국인", value=kqf_val, step=1000, key="in_kq_f")
                    kosdaq_individual = st.number_input("코스닥 개인", value=kqi_val, step=1000, key="in_kq_i")
                    kosdaq_institution = st.number_input("코스닥 기관계", value=kqin_val, step=1000, key="in_kq_inst")

                st.markdown("###### ⚡ 프로그램 매매 (단위: 백만원)")
                col_pr1, col_pr2, col_pr3 = st.columns(3)
                prog_arb = col_pr1.number_input("차익 순매수", value=p_arb_val, step=1000, key="in_pr_arb")
                prog_non_arb = col_pr2.number_input("비차익 순매수", value=p_non_val_int, step=1000, key="in_pr_non_arb")
                prog_tot = col_pr3.number_input("전체 순매수", value=p_tot_val, step=1000, key="in_pr_tot")

                if st.button("💾 매매동향 DB 저장", type="primary", use_container_width=True):
                    try:
                        inv_data = [
                            {"trade_date": trend_date_str, "market_type": "KOSPI", "foreign_net": kospi_foreign, "individual_net": kospi_individual, "institution_net": kospi_institution},
                            {"trade_date": trend_date_str, "market_type": "KOSDAQ", "foreign_net": kosdaq_foreign, "individual_net": kosdaq_individual, "institution_net": kosdaq_institution}
                        ]
                        supabase.table("market_investor_trends").upsert(inv_data).execute()
                        
                        prog_data = {"trade_date": trend_date_str, "arbitrage_net": prog_arb, "non_arbitrage_net": prog_non_arb, "total_net": prog_tot}
                        supabase.table("market_program_trends").upsert(prog_data).execute()
                        
                        st.success(f"✅ [{trend_date_str}] 매매동향 데이터가 성공적으로 저장되었습니다.")
                        st.rerun()
                    except Exception as e:
                        st.error(f"❌ 저장 실패: {e}")

    with tab4:
        st.markdown(f"##### 🚀 시스템 매매 지시서 [보유 현황: {current_holdings_count} / {top_n_cfg}개]")
        
        if not is_authenticated:
            st.info("🔒 실제 매매 신호 및 운용자금 설정을 위해 우측 상단 **[🔑 잠금 해제]** 버튼을 클릭해 주십시오.")
        else:
            with st.expander(f"💰 [{market_type}] 총 운용 자금 설정 / DB 저장", expanded=True):
                col_cap1, col_cap2 = st.columns([3, 1])
                with col_cap1:
                    new_capital_input = st.number_input(
                        f"[{market_type}] 총 운용 자금 설정", 
                        value=account_total_input, 
                        step=100.0 if market_type == "US" else 1000000.0,
                        format="%.2f" if market_type == "US" else "%.0f",
                        key=f"tab4_cap_input_{market_type}"
                    )
                with col_cap2:
                    st.write("")
                    st.write("")
                    if st.button("자금 저장", key=f"btn_save_cap_{market_type}", use_container_width=True, type="primary"):
                        st.session_state[cap_key] = new_capital_input
                        try:
                            res_existing = supabase.table("strategy_settings").select("*").eq("id", 1).execute()
                            existing_data = res_existing.data[0] if res_existing.data else {}
                            
                            existing_data["id"] = 1
                            existing_data[cap_key] = float(new_capital_input)
                            existing_data["strategy_engine_mode"] = current_engine_key
                            
                            supabase.table("strategy_settings").upsert(existing_data).execute()
                            cap_disp = f"${new_capital_input:,.2f}" if market_type == "US" else f"{new_capital_input:,.0f}원"
                            st.success(f"✅ 총 운용자금이 {cap_disp}으로 업데이트되었습니다.")
                            st.rerun()
                        except Exception as e:
                            st.error(f"❌ DB 저장 실패: {e}")

                max_risk_per_stock = new_capital_input * 0.02
                risk_fmt = f"${max_risk_per_stock:,.2f}" if market_type == "US" else f"{max_risk_per_stock:,.0f}원"
                st.caption(f"🔒 **단일 종목 최대 허용 손실 (2% Rule)**: {risk_fmt}")
                account_total_input = new_capital_input

            st.write("")

            with st.expander(f"💼 현재 보유 종목 ({current_holdings_count}/{top_n_cfg}개 슬롯)", expanded=True):
                if not holdings_db.empty:
                    df_stocks = pd.DataFrame(supabase.table("stocks").select("ticker, name").execute().data)
                    if not df_stocks.empty:
                        df_stocks['ticker'] = df_stocks['ticker'].astype(str).str.strip()
                        holdings_merged = pd.merge(holdings_db, df_stocks, on="ticker", how="left")
                    else:
                        holdings_merged = holdings_db
                        holdings_merged['name'] = holdings_merged['ticker']
                    
                    holdings_list = []
                    total_holdings_val = 0.0
                    risk_violations = []
                    
                    for _, h_row in holdings_merged.iterrows():
                        ticker = h_row['ticker']
                        raw_name = h_row.get('name', ticker)
                        buy_price = float(h_row.get('buy_price', 0.0))
                        qty = float(h_row.get('quantity', 1.0))
                        
                        curr_row = df_display[df_display['ticker'].str.strip().str.upper() == str(ticker).strip().upper()]
                        
                        if not curr_row.empty:
                            curr_price = float(curr_row['종가'].values[0])
                            engine_status = curr_row['매매상태'].values[0]
                            atr_val = float(curr_row.get('atr', 0.0).values[0]) if 'atr' in curr_row.columns else 0.0
                        else:
                            curr_price = buy_price
                            engine_status = '보유'
                            atr_val = 0.0
                        
                        eval_val = curr_price * qty
                        total_holdings_val += eval_val
                        profit_rate = ((curr_price / buy_price) - 1) * 100 if buy_price > 0 else 0.0
                        
                        if atr_val > 0 and current_engine_key == "strat3_top7":
                            stop_loss_price = buy_price - (2.5 * atr_val)
                        else:
                            stop_loss_price = buy_price * (1 + (sl_cfg / 100.0))
                        
                        stop_loss_amount = max(0.0, (buy_price - stop_loss_price) * qty)
                        
                        stock_risk_pct = (stop_loss_amount / account_total_input) * 100 if account_total_input > 0 else 0.0
                        if stock_risk_pct > 2.0:
                            risk_violations.append(f"{ticker} ({stock_risk_pct:.1f}%)")
                            
                        if engine_status == '매도' or curr_price <= stop_loss_price:
                            status = "🚨 손절 이탈"
                        else:
                            status = "보유"
                        
                        holdings_list.append({
                            '종목명': f"[{ticker}] {raw_name}" if market_type == "US" else f"{raw_name}",
                            '종목코드': ticker,
                            '수량': qty,
                            '평단가': buy_price,
                            '현재가': curr_price,
                            '수익률(%)': profit_rate,
                            '손절가': stop_loss_price,
                            '손절금액': stop_loss_amount,
                            '평가금액': eval_val,
                            '상태': status
                        })
                    
                    total_risk_amount = sum(item['손절금액'] for item in holdings_list)
                    total_risk_pct = (total_risk_amount / account_total_input) * 100 if account_total_input > 0 else 0.0
                    
                    st.markdown("###### 🛡️ 포트폴리오 리스크 노출도")
                    risk_col1, risk_col2 = st.columns([3, 1])
                    with risk_col1:
                        st.progress(min(total_risk_pct / 100.0, 1.0))
                    with risk_col2:
                        st.markdown(f"**총 리스크: {total_risk_pct:.2f}%**")
                    
                    risk_amt_fmt = f"${total_risk_amount:,.2f}" if market_type == "US" else f"{total_risk_amount:,.0f}원"
                    st.caption(f"※ 전 종목 손절선 도달 시 예상 최대 손실: **{risk_amt_fmt}**")
                    if risk_violations:
                        st.warning(f"⚠️ 단일 종목 손실 한도(2.0%) 초과: {', '.join(risk_violations)}")
                        
                    st.write("")
                    df_h = pd.DataFrame(holdings_list)
                    calc_base_total = account_total_input if account_total_input > 0 else total_holdings_val
                    df_h['비중(%)'] = (df_h['평가금액'] / calc_base_total) * 100
                    
                    df_h = df_h[['종목명', '종목코드', '수량', '평단가', '현재가', '손절가', '손절금액', '수익률(%)', '비중(%)', '평가금액', '상태']]
                    
                    price_fmt_str = '{:,.2f}' if market_type == "US" else '{:,.0f}'
                    st.dataframe(
                        df_h.style.format({
                            '수량': '{:,.2f}' if market_type == "US" else '{:,.0f}', 
                            '평단가': price_fmt_str, '현재가': price_fmt_str,
                            '손절가': price_fmt_str, '손절금액': price_fmt_str,
                            '수익률(%)': '{:+.2f}%', '비중(%)': '{:.1f}%', '평가금액': price_fmt_str
                        }).map(lambda x: 'color: red; font-weight: bold;' if x == '🚨 손절 이탈' else '', subset=['상태'])
                          .map(lambda x: 'color: red;' if float(x) > 0 else 'color: blue;', subset=['수익률(%)']),
                        hide_index=True, use_container_width=True
                    )

            df_rebal = df_display[df_display['매매상태'].isin(['매도', '추천'])]
            
            display_trade_list(df_rebal[df_rebal['매매상태'] == '매도'], "시스템 매도 필요 종목", "매도", "sys_s", target_date_str, is_latest_date, market_type, holdings_db, top_n_cfg, account_total_input, current_engine_key)
            display_trade_list(df_rebal[df_rebal['매매상태'] == '추천'], "시스템 매수 추천 종목", "매수", "sys_b", target_date_str, is_latest_date, market_type, holdings_db, top_n_cfg, account_total_input, current_engine_key)

            st.markdown("---")
            show_manual_trade = st.toggle("🔄 보유 종목 수동 매수/매도 입력창 펼치기", value=False)
            
            if show_manual_trade:
                col_m_left, col_m_right = st.columns(2)
                with col_m_left:
                    st.markdown("###### ➕ 수동 매수")
                    with st.container(border=True):
                        m_ticker = st.text_input("종목코드 (Ticker)", key="m_ticker").strip().upper()
                        c1, c2 = st.columns(2)
                        m_price = c1.number_input("매수가", min_value=0.0, value=0.0, step=0.01 if market_type=="US" else 100.0, format="%.2f" if market_type=="US" else "%.0f", key="m_price")
                        m_qty = c2.number_input("수량", min_value=0.0, value=1.0, step=0.01 if market_type=="US" else 1.0, format="%.2f" if market_type=="US" else "%.0f", key="m_qty")
                        m_date = st.date_input("매수일", value=selected_date, key="m_date")
                        if st.button("수동 매수 실행", use_container_width=True, type="primary"):
                            if m_ticker and m_price > 0 and m_qty > 0:
                                update_holdings(m_ticker, 'BUY', m_price, m_date, m_qty, market_type)
                            else:
                                st.warning("종목코드, 매수가, 수량을 확인하세요.")
                with col_m_right:
                    st.markdown("###### 🗑️ 수동 매도")
                    with st.container(border=True):
                        ms_ticker = st.text_input("매도 종목코드", key="ms_ticker").strip().upper()
                        c1, c2 = st.columns(2)
                        ms_price = c1.number_input("매도가", min_value=0.0, value=0.0, step=0.01 if market_type=="US" else 100.0, format="%.2f" if market_type=="US" else "%.0f", key="ms_price")
                        ms_qty = c2.number_input("수량", min_value=0.0, value=1.0, step=0.01 if market_type=="US" else 1.0, format="%.2f" if market_type=="US" else "%.0f", key="ms_qty")
                        ms_date = st.date_input("매도일", value=selected_date, key="ms_date")
                        if st.button("수동 매도 실행", use_container_width=True, type="secondary"):
                            if ms_ticker and ms_price > 0 and ms_qty > 0:
                                update_holdings(ms_ticker, 'SELL', ms_price, ms_date, ms_qty, market_type)
                            else:
                                st.warning("종목코드, 매도가, 수량을 확인하세요.")

            st.markdown("---")
            st.markdown("##### 🤖 Google Gemini AI 종목 분석")

            used_cnt, remain_cnt = get_remaining_quota()
            col_q1, col_q2 = st.columns([3, 1])
            with col_q1:
                st.caption("선택한 종목의 수치 지표와 분석 옵션에 따라 AI가 맞춤 리포트를 생성합니다.")
            with col_q2:
                st.metric("Gemini 잔여 사용량", f"{remain_cnt}/{MAX_DAILY_QUOTA}회")

            col_sel1, col_sel2 = st.columns([1, 1])
            with col_sel1:
                selected_target_ticker = st.selectbox(
                    "분석할 종목 선택", 
                    options=df_display['ticker'].tolist(),
                    format_func=lambda x: f"[{x}] {dict(zip(df_display['ticker'], df_display['종목명'])).get(x, x)}"
                )

            with col_sel2:
                analysis_option = st.selectbox(
                    "분석 요청할 항목 선택",
                    [
                        "📋 종합 기본적 분석",
                        "📈 ROE 듀퐁 분석 (DuPont Analysis)",
                        "🏢 사업 구조 및 수익 모델",
                        "📊 퀀트 지표 기반 밸류에이션",
                        "⚠️ 주요 리스크 및 억제 요인",
                        "🎯 단기/중기 매매 시나리오"
                    ]
                )

            if st.button("✨ Gemini 분석 실행", type="primary", use_container_width=True):
                target_row = df_display[df_display['ticker'] == selected_target_ticker].iloc[0]
                stock_nm = target_row['종목명']
                
                with st.spinner(f"🤖 '{stock_nm}' 종목의 [{analysis_option}] 분석을 진행 중입니다..."):
                    analysis_result = analyze_stock_with_gemini(selected_target_ticker, stock_nm, target_row, analysis_option)
                    
                st.success("✅ 분석 완료")
                st.markdown(analysis_result)

        if current_engine_key == "strat3_top7":
            st.info(f"""
            📌 **전략 3 (Top 7 레짐+ATR 트레일링) 가이드**
            * **운용 슬롯**: 최대 **{top_n_cfg}개** 균등 분산 (동적 복리 적용)
            * **레짐 필터**: KOSPI 종가 > MA20 상승장일 때만 매수, 하락 시 전량 현금화
            * **매수 조건**: 모멘텀 순위 **Rank ≤ 15**, RS(90) > 0, RS(10) > 0, 종가 > MA20 (이격도 최소 우선)
            * **청산 룰**: 진입가 - 2.5 × ATR 손절, 고점 대비 -5% 트레일링스톱
            """)
        elif current_engine_key == "short_term":
            st.info(f"""
            📌 **단기 타점 모멘텀 매매 전략 가이드 (15%+ 랠리 타점)**
            * **운용 슬롯**: 최대 {top_n_cfg}개 분할
            * **매수 타점 조건**: 모멘텀 순위 **Rank 200위 이내**, 이격도 **-5% ~ +7%**
            * **목표/손절**: +15% 목표익절, -5% 손절, 14일 타임컷
            """)
        else:
            st.info(f"""
            📌 **하이브리드 듀얼 알파 매매 전략 시스템 가이드 (Ultimate)**
            * **운용 슬롯**: 최대 {top_n_cfg}개 분할
            * **매도 조건**: 종가 < MA20 이탈, 순위 이탈({rank_exit_limit}위 밖), 손절({sl_cfg}%)
            """)

    with tab5:
        st.markdown(f"##### 📊 {market_type} 시장 성과 분석")
        
        if not is_authenticated:
            st.info("🔒 상세 성과 내역 확인을 위해 우측 상단 **[🔑 잠금 해제]** 버튼을 클릭해 주십시오.")
        else:
            current_table_name = get_holdings_table(market_type)
            try:
                history_res = supabase.table(current_table_name).select("*").not_.is_("sell_date", "null").execute()
            except Exception:
                history_res = type('obj', (object,), {'data': []})

            if not history_res.data:
                st.info("청산 완료된 매매 이력이 존재하지 않습니다.")
            else:
                df_hist_raw = pd.DataFrame(history_res.data)
                df_hist_raw['sell_date_dt'] = pd.to_datetime(df_hist_raw['sell_date'])
                
                st.markdown("###### 📅 성과 분석 기간 설정")
                min_sell_date = df_hist_raw['sell_date_dt'].min().date()
                max_sell_date = df_hist_raw['sell_date_dt'].max().date()
                
                col_d1, col_d2 = st.columns(2)
                with col_d1:
                    start_date_perf = st.date_input("조회 시작일", value=min_sell_date, key="perf_start_date")
                with col_d2:
                    end_date_perf = st.date_input("조회 종료일", value=max_sell_date, key="perf_end_date")
                
                mask_period = (df_hist_raw['sell_date_dt'].dt.date >= start_date_perf) & (df_hist_raw['sell_date_dt'].dt.date <= end_date_perf)
                df_hist = df_hist_raw[mask_period].copy()
                
                if df_hist.empty:
                    st.warning("선택하신 기간 내에 매도 완료된 거래 내역이 없습니다.")
                else:
                    df_stocks_info = pd.DataFrame(supabase.table("stocks").select("ticker, name").execute().data)
                    if not df_stocks_info.empty:
                        df_stocks_info['ticker'] = df_stocks_info['ticker'].astype(str).str.strip()
                        df_hist = pd.merge(df_hist, df_stocks_info, on="ticker", how="left")
                        df_hist['종목명'] = df_hist['name'].fillna(df_hist['ticker'])
                    else:
                        df_hist['종목명'] = df_hist['ticker']

                    if market_type == "US": df_hist['종목명'] = df_hist.apply(lambda r: f"[{r['ticker']}] {r['종목명']}", axis=1)

                    df_hist['profit_amount'] = pd.to_numeric(df_hist['profit_amount'], errors='coerce').fillna(0.0)
                    df_hist['profit_rate'] = pd.to_numeric(df_hist['profit_rate'], errors='coerce').fillna(0.0)
                    
                    df_hist['buy_date_dt'] = pd.to_datetime(df_hist['buy_date'], errors='coerce')
                    df_hist['holding_days'] = (df_hist['sell_date_dt'] - df_hist['buy_date_dt']).dt.days
                    
                    df_hist = df_hist.sort_values('sell_date_dt')
                    
                    total_profit = df_hist['profit_amount'].sum()
                    total_trades = len(df_hist)
                    win_df = df_hist[df_hist['profit_amount'] > 0]
                    loss_df = df_hist[df_hist['profit_amount'] < 0]
                    
                    win_trades = len(win_df)
                    loss_trades = len(loss_df)
                    
                    win_rate = (win_trades / total_trades * 100) if total_trades > 0 else 0.0
                    loss_rate = (loss_trades / total_trades * 100) if total_trades > 0 else 0.0
                    
                    avg_win_amt = win_df['profit_amount'].mean() if win_trades > 0 else 0.0
                    avg_loss_amt = abs(loss_df['profit_amount'].mean()) if loss_trades > 0 else 0.0
                    
                    profit_factor = (avg_win_amt / avg_loss_amt) if avg_loss_amt > 0 else 999.0
                    expectancy = ( (win_rate/100) * avg_win_amt ) - ( (loss_rate/100) * avg_loss_amt )
                    
                    std_dev = df_hist['profit_rate'].std()
                    total_return_pct = (total_profit / account_total_input) * 100 if account_total_input > 0 else 0.0
                    
                    profit_fmt = lambda x: f"${x:,.2f}" if market_type == "US" else f"{x:,.0f}원"
                    price_fmt = "{:,.2f}" if market_type == "US" else "{:,.0f}"
                    
                    st.markdown("###### 📈 핵심 성과 지표 (KPI)")
                    
                    m1, m2, m3, m4 = st.columns(4)
                    m1.metric("총 실현 손익", profit_fmt(total_profit))
                    m2.metric("누적 수익률", f"{total_return_pct:+.2f}%")
                    m3.metric("승률 / 패율", f"{win_rate:.1f}% / {loss_rate:.1f}%")
                    m4.metric("기대 수익", profit_fmt(expectancy))
                    
                    m5, m6, m7, m8 = st.columns(4)
                    m5.metric("평균 익절", profit_fmt(avg_win_amt))
                    m6.metric("평균 손절", profit_fmt(avg_loss_amt))
                    m7.metric("평균 수익률 / 변동성", f"{df_hist['profit_rate'].mean():+.2f}% / {std_dev:.2f}%")
                    m8.metric("손익비", f"{profit_factor:.2f}" if profit_factor < 999 else "무한")
                    
                    st.write("")
                    st.markdown("###### 📅 월별 성과")
                    df_hist['sell_month'] = df_hist['sell_date_dt'].dt.strftime('%Y-%m')
                    df_monthly = df_hist.groupby('sell_month').agg(
                        월간손익=('profit_amount', 'sum'),
                        매매건수=('id', 'count'),
                        평균수익률=('profit_rate', 'mean')
                    ).reset_index().sort_values('sell_month', ascending=False)
                    st.dataframe(df_monthly.style.format({'월간손익': profit_fmt, '평균수익률': '{:+.2f}%'}), hide_index=True, use_container_width=True)
                    
                    st.write("")
                    st.markdown("###### 🔍 수익 기여도 차트")
                    draw_attribution_charts(df_hist, market_type)

                    st.write("")
                    st.markdown("###### 📜 상세 매매 내역")
                    df_hist_sorted = df_hist.sort_values('sell_date', ascending=False)
                    disp_cols = ['sell_date', 'ticker', '종목명', 'buy_date', 'buy_price', 'sell_price', 'quantity', 'profit_amount', 'profit_rate', 'holding_days']
                    
                    df_hist_sorted = df_hist_sorted.rename(columns={'holding_days': '보유일수'})
                    disp_cols[-1] = '보유일수'
                    
                    st.dataframe(
                        df_hist_sorted[disp_cols].style.format({
                            'buy_price': price_fmt, 'sell_price': price_fmt, 
                            'quantity': '{:,.2f}' if market_type=="US" else '{:,.0f}',
                            'profit_amount': profit_fmt, 'profit_rate': '{:+.2f}%', '보유일수': '{:.0f}일'
                        }), hide_index=True, use_container_width=True
                    )

    st.divider()
    st.markdown("<div id='chart-section'></div>", unsafe_allow_html=True)
    if is_authenticated:
        with st.expander("📉 개별 종목 통합 차트", expanded=True):
            if st.session_state.get('trigger_scroll'):
                scroll_to_chart()
                st.session_state['trigger_scroll'] = False 

            top200_tickers = df_display.head(200)['ticker'].tolist()
            if st.session_state.get('selected_ticker_from_table') and st.session_state['selected_ticker_from_table'] not in top200_tickers:
                top200_tickers.append(st.session_state['selected_ticker_from_table'])
                
            ticker_name_map = dict(zip(df_display['ticker'], df_display['종목명']))
            default_ticker = st.session_state.get('selected_ticker_from_table', top200_tickers[0] if top200_tickers else None)
            
            sel_ticker = st.selectbox(
                "종목별 차트 분석", 
                options=top200_tickers, 
                index=top200_tickers.index(default_ticker) if default_ticker in top200_tickers else 0, 
                format_func=lambda x: f"[{x}] {ticker_name_map.get(x, x)}"
            )
            if sel_ticker:
                draw_integrated_chart(sel_ticker, market_type, ticker_name_map)
    else:
        st.info("🔒 개별 종목 차트는 우측 상단 **[🔑 잠금 해제]** 후 조회가 가능합니다.")
else:
    st.warning("데이터를 불러오는 중입니다.")
