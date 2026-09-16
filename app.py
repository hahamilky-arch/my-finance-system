import streamlit as st
import pandas as pd
import streamlit.components.v1 as components
from db import supabase, get_holdings_table, update_holdings, get_market_regime, get_available_dates
from strategy import get_data
from charts import draw_integrated_chart, draw_attribution_charts
from gemini_analyzer import analyze_stock_with_gemini, get_remaining_quota, MAX_DAILY_QUOTA

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
    .backup-tag {
        background-color: #fff3cd; color: #856404; font-size: 0.8em; font-weight: bold;
        padding: 2px 8px; border-radius: 10px; border: 1px solid #ffeeba; margin-left: 6px;
    }
    </style>
    <a href="#top-section" class="floating-btn-left"><span>⬆️</span> <span>위로</span></a>
""", unsafe_allow_html=True)

def scroll_to_chart():
    components.html("<script>setTimeout(function(){const el=window.parent.document.getElementById('chart-section');if(el)el.scrollIntoView({behavior:'smooth'});},100);</script>", height=0)

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

def display_trade_list(data, title, button_label, key_prefix, target_date, is_latest_date, market_type, holdings_df, top_n_cfg, account_total=0.0, strategy_engine_mode="strat3_top7"):
    with st.expander(f"🚨 {title} ({len(data)}개)", expanded=True):
        if data.empty:
            st.write(f"해당되는 {button_label} 종목이 없습니다.")
            return
        
        target_amount = account_total * ((100.0 / top_n_cfg) / 100.0) if top_n_cfg > 0 else 0.0
        fmt_str = f"${target_amount:,.2f}" if market_type == "US" else f"{target_amount:,.0f}원"
        
        current_holdings_count = len(holdings_df) if not holdings_df.empty else 0
        is_slot_full = current_holdings_count >= top_n_cfg

        if button_label == '매수':
            primary_data = data.iloc[:top_n_cfg]
            backup_data = data.iloc[top_n_cfg:top_n_cfg + 2]
            
            if is_slot_full:
                st.warning(f"⚠️ 현재 포트폴리오 슬롯이 만석입니다 ({current_holdings_count}/{top_n_cfg}개 보유 중). 하단의 후순위 예비 종목을 대체/대기 매수용으로 참고하세요.")
        else:
            primary_data = data
            backup_data = pd.DataFrame()

        for _, row in primary_data.iterrows():
            ticker = row['ticker']
            c1, c2 = st.columns([4, 1])
            
            rank_val = int(row.get('순위', 0)) if pd.notna(row.get('순위')) else '-'
            rec_rank_val = row.get('추천순위', row.get('매수추천순위', ''))
            rec_rank_display = f"{rec_rank_val}위" if rec_rank_val != '' else '-'
            
            if '매도' in title:
                if strategy_engine_mode == "strat3_top7":
                    reason_desc = f"레짐전환 현금화, ATR손절(-2.5x) 또는 트레일링스톱 도달"
                elif strategy_engine_mode == "short_term":
                    reason_desc = f"목표 수익률(+15%) 도달, 손절(-5%) 또는 14일 타임스탑 청산"
                else:
                    reason_desc = f"추세선 이탈, 손절 임계값 혹은 타임스탑 조건 도달"
                position_info = ""
            else:
                if strategy_engine_mode == "strat3_top7":
                    reason_desc = f"전략 3 진입 조건 충족 [추천순위: {rec_rank_display}] (이격도 최소 우선)"
                elif strategy_engine_mode == "short_term":
                    reason_desc = f"단기 타점 조건 충족 [추천순위: {rec_rank_display}] (Rank≤200)"
                else:
                    reason_desc = f"Ultimate 듀얼 모멘텀 조건 충족 [추천순위: {rec_rank_display}]"
                target_pct = (100.0 / top_n_cfg) if top_n_cfg > 0 else 0.0
                atr_val = row.get('atr', 0.0)
                position_info = f"<br><span style='font-size: 0.85em; color: #1b5e20; font-weight: bold;'>📊 추천 분산 금액: {fmt_str} (목표 비중 {target_pct:.1f}%) | ATR: {atr_val:,.2f if market_type=='US' else atr_val:,.0f}</span>"

            card_html = (
                f"<div style='line-height: 1.6; margin-top: 4px;'>"
                f"<strong style='font-size: 1.1em; color: #111111;'>{row['종목명']}</strong> "
                f"<span style='font-size: 0.8em; color: #888888; margin-left: 4px;'>({ticker})</span> "
                f"<span style='font-size: 0.8em; color: #1565c0; font-weight: bold; margin-left: 6px;'>[모멘텀순위: {rank_val}위 | 추천순위: {rec_rank_display}]</span>"
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
                        st.number_input("운용계좌 총액", value=account_total, step=100.0 if market_type=="US" else 1000000.0, key=acc_key)
                        calc_qty = max(1.0, (target_amount / input_price) if input_price > 0 else 1.0)
                        
                        atr_v = float(row.get('atr', 0.0))
                        if atr_v > 0 and input_price > 0:
                            atr_suggest_qty = max(1.0, float(int((account_total * 0.02) / (2 * atr_v))))
                            st.caption(f"💡 자금관리(ATR 변동성) 추천 수량: {atr_suggest_qty:,.2f if market_type=='US' else atr_suggest_qty:,.0f}주")
                            
                        input_qty = st.number_input("매수수량", value=calc_qty if market_type=="US" else float(int(calc_qty)), min_value=0.0, key=q_key)
                    else:
                        matched_h = holdings_df[holdings_df['ticker'].astype(str).str.strip().str.upper() == ticker.strip().upper()] if not holdings_df.empty else pd.DataFrame()
                        def_qty = float(matched_h.iloc[0].get('quantity', 1.0)) if not matched_h.empty else 1.0
                        input_qty = st.number_input("매도수량", value=def_qty, min_value=0.0, key=q_key)
                        
                    if st.button("확인", key=f"btn_{key_prefix}_{ticker}"):
                        update_holdings(ticker, 'SELL' if '매도' in title else 'BUY', input_price, target_date, input_qty, market_type)
            else:
                c2.markdown("<div style='color:#999999; font-size:0.85em; margin-top:8px; text-align:right;'>과거일 매매불가</div>", unsafe_allow_html=True)

        if not backup_data.empty:
            st.markdown("---")
            st.markdown("###### 💡 후순위 예비 추천 종목 (슬롯 만석/미체결 시 교체 매수용)")
            for backup_idx, (_, row) in enumerate(backup_data.iterrows(), 1):
                ticker = row['ticker']
                c1, c2 = st.columns([4, 1])
                
                rank_val = int(row.get('순위', 0)) if pd.notna(row.get('순위')) else '-'
                rec_rank_val = row.get('추천순위', row.get('매수추천순위', ''))
                rec_rank_display = f"{rec_rank_val}위" if rec_rank_val != '' else '-'
                reason_desc = f"후순위 조건 충족 [추천순위: {rec_rank_display}] (예비 {backup_idx}순위 대체 종목)"
                target_pct = (100.0 / top_n_cfg) if top_n_cfg > 0 else 0.0
                atr_val = row.get('atr', 0.0)
                position_info = f"<br><span style='font-size: 0.85em; color: #856404; font-weight: bold;'>📊 예비 분산 금액: {fmt_str} | ATR: {atr_val:,.2f if market_type=='US' else atr_val:,.0f}</span>"

                backup_html = (
                    f"<div style='line-height: 1.6; margin-top: 4px; background-color: #fffde7; padding: 8px 12px; border-radius: 6px; border-left: 4px solid #fbc02d;'>"
                    f"<strong style='font-size: 1.05em; color: #111111;'>{row['종목명']}</strong> "
                    f"<span style='font-size: 0.8em; color: #888888; margin-left: 4px;'>({ticker})</span> "
                    f"<span class='backup-tag'>💡 예비 {backup_idx}순위 [모멘텀순위: {rank_val}위 | 추천순위: {rec_rank_display}]</span>"
                    f"<br><span style='font-size: 0.85em; color: #e65100; font-weight: bold;'>📌 사유: {reason_desc}</span>"
                    f"{position_info}"
                    f"<br><span style='font-size: 0.85em; color: #444444;'>MOT: {row['MOT']:.2f} | RS(90): {row['RS(90)']:.2f} | 이격도: {row['이격도']:+.2f}%</span>"
                    f"</div>"
                )
                c1.markdown(backup_html, unsafe_allow_html=True)
                
                if is_latest_date:
                    with c2.popover(f"예비매수"):
                        st.write(f"**[예비 {backup_idx}순위] {row['종목명']}**")
                        p_key, q_key, acc_key = f"p_bk_{key_prefix}_{ticker}", f"q_bk_{key_prefix}_{ticker}", f"acc_bk_{key_prefix}_{ticker}"
                        input_price = st.number_input(f"매수가", value=float(row['종가']), key=p_key)
                        st.number_input("운용계좌 총액", value=account_total, step=100.0 if market_type=="US" else 1000000.0, key=acc_key)
                        calc_qty = max(1.0, (target_amount / input_price) if input_price > 0 else 1.0)
                        input_qty = st.number_input("매수수량", value=calc_qty if market_type=="US" else float(int(calc_qty)), min_value=0.0, key=q_key)
                            
                        if st.button("예비 매수 실행", key=f"btn_bk_{key_prefix}_{ticker}"):
                            update_holdings(ticker, 'BUY', input_price, target_date, input_qty, market_type)
                else:
                    c2.markdown("<div style='color:#999999; font-size:0.85em; margin-top:8px; text-align:right;'>과거일 매매불가</div>", unsafe_allow_html=True)

st.markdown("##### 📈 Quant Alpha Strategy")

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
    
    strategy_engine_mode = st.radio(
        "💡 전략 엔진 선택",
        [
            "🔥 전략 3: Top 7 레짐+ATR",
            "🚀 단기 타점 모멘텀 (15%+ 랠리)", 
            "🌐 Ultimate 듀얼 모멘텀 (추세)"
        ],
        index=0 if st.session_state.get('strategy_engine_mode', 'strat3_top7') == 'strat3_top7' else (1 if st.session_state.get('strategy_engine_mode') == 'short_term' else 2)
    )
    
    if "전략 3" in strategy_engine_mode:
        current_engine_key = "strat3_top7"
    elif "단기" in strategy_engine_mode:
        current_engine_key = "short_term"
    else:
        current_engine_key = "ultimate_dual"
        
    st.session_state['strategy_engine_mode'] = current_engine_key
    
    st.divider()

    market_type = st.radio("Market", ["KR", "US"], horizontal=True)
    selected_date = st.date_input("Date", value=latest_date_default)
    target_date_str = pd.to_datetime(selected_date).strftime('%Y-%m-%d') if selected_date else ""
    
    market_safe, stop_new_buy, reduce_holdings = get_market_regime(market_type, target_date_str)
    strategy_mode = st.radio("운용 모드 선택", ["자동 감지 모드", "상승장 세팅 (Bull)", "하락장 세팅 (Bear)"], index=0)
    is_bull = True if strategy_mode == "상승장 세팅 (Bull)" else (False if strategy_mode == "하락장 세팅 (Bear)" else market_safe)
    rebalance_cycle = st.selectbox("리밸런싱 주기", ["상시 (빈자리 즉시 채우기)", "주기 (매주 수요일)"])

    if current_engine_key == "strat3_top7":
        st.success("🔥 전략 3 모드: Top 7 / Rank≤15 / ATR 2.5x손절 / 트레일링스톱")
        top_n_cfg = 7
        sl_cfg = -2.5
        rank_exit_limit = 15
    elif current_engine_key == "short_term":
        st.info("🚀 단기 타점 모드: 상위 200위 / 15% 목표익절 / -5% 손절 / 14일 타임컷")
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

cap_key = "us_capital" if market_type == "US" else "kr_capital"
default_cap = st.session_state.get(cap_key, 6000.0 if market_type == "US" else 20000000.0)
account_total_input = float(default_cap)

df_display = get_data(selected_date, all_dates, market_type, top_n_cfg, sl_cfg, rebalance_cycle, is_bull, stop_new_buy, reduce_holdings, strategy_engine_mode=current_engine_key)

if df_display is not None:
    if '매수추천순위' in df_display.columns:
        df_display = df_display.rename(columns={'매수추천순위': '추천순위'})

    is_latest_date = (target_date_str == max(all_dates)) if all_dates and target_date_str else False
    
    # 기본 3개 탭 구성
    tab1, tab4, tab5 = st.tabs(["Overview", "🚀 알파 시그널", "📊 성과 분석"])
    
    with tab1:
        st.markdown("###### 📊 시장 및 시그널 요약")
        
        c1, c2, c3, c4 = st.columns(4)
        c1.metric("현재 전략 모드", "🔥 전략 3 (Top 7)" if current_engine_key == "strat3_top7" else ("🚀 단기 타점 모드" if current_engine_key == "short_term" else ("🟢 강세장" if is_bull else "🔴 약세장")))
        c2.metric("신규 매수 상태", "🛑 중지 (MA20 3일하회)" if stop_new_buy else ("⚠️ 비중축소 (MA20하회)" if reduce_holdings else "✅ 허용"))
        
        buy_cnt = len(df_display[df_display['매매상태'] == '매수추천'])
        sell_cnt = len(df_display[df_display['매매상태'] == '매도필요'])
        c3.metric("오늘의 매수 추천", f"{buy_cnt} 종목")
        c4.metric("오늘의 매도 필요", f"{sell_cnt} 종목")
        
        st.write("")
        
        st.markdown("###### 📋 알파 시그널 전체 목록 (상위 200위)")
        filter_opt = st.radio("빠른 필터", ["전체보기", "🔴 매수 추천 종목만", "🔵 매도 필요 종목만", "🟢 현재 보유 종목만"], horizontal=True, label_visibility="collapsed")
        
        col_order = ['순위', '추천순위', '변동', '매매상태', '종목명', '이격도', 'MOT', 'RS(90)', 'RS(10)', 'MA20', '제외사유', '종가', '상승금액', '상승률', 'ticker'] 
        df_target = df_display.head(200)[col_order].copy()
        
        if filter_opt == "🔴 매수 추천 종목만":
            df_target = df_target[df_target['매매상태'] == '매수추천']
        elif filter_opt == "🔵 매도 필요 종목만":
            df_target = df_target[df_target['매매상태'] == '매도필요']
        elif filter_opt == "🟢 현재 보유 종목만":
            df_target = df_target[df_target['매매상태'] == '보유중']
        
        if df_target.empty:
            st.info("해당되는 종목이 없습니다.")
        else:
            fmt_dict = {
                '이격도': lambda x: f"{x:+.2f}%" if x != 0 else "-", 
                'MOT': '{:.2f}', 'RS(90)': '{:.2f}', 'RS(10)': '{:.2f}',
                'MA20': '{:,.2f}' if market_type=='US' else '{:,.0f}',
                '종가': '{:,.2f}' if market_type=='US' else '{:,.0f}',
                '상승금액': '{:+,.2f}' if market_type=='US' else '{:+,.0f}',
                '상승률': '{:+.2f}%'
            }
            event = st.dataframe(
                df_target.style.apply(apply_styles, axis=None).format(fmt_dict), 
                hide_index=True, use_container_width=True, on_select="rerun", selection_mode="single-row"
            )
            if event and event.get("selection", {}).get("rows"):
                st.session_state['selected_ticker_from_table'] = df_target.iloc[event["selection"]["rows"][0]]['ticker']
                st.session_state['trigger_scroll'] = True

    with tab4:
        st.markdown("##### 🚀 시스템 매매 지시서 & 알파 시그널 자금 설정")
        
        if not st.session_state.get('trade_authenticated', False):
            st.info("🔒 실제 매매 신호 및 운용자금 설정을 위해 비밀번호를 입력해 주십시오.")
            col_pwd1, col_pwd2 = st.columns([3, 1])
            with col_pwd1:
                input_pwd_4 = st.text_input("매매 비밀번호", type="password", key="pwd_tab4", label_visibility="collapsed")
            with col_pwd2:
                if st.button("잠금 해제", key="btn_unlock_tab4", use_container_width=True):
                    if input_pwd_4 == st.secrets.get("TRADE_PASSWORD", "1234"):
                        st.session_state['trade_authenticated'] = True
                        st.rerun()
                    else:
                        st.error("비밀번호가 일치하지 않습니다.")
        else:
            col_header1, col_header2 = st.columns([5, 1])
            with col_header2:
                if st.button("🔒 다시 잠금", key="btn_lock_tab4", use_container_width=True):
                    st.session_state['trade_authenticated'] = False
                    st.rerun()

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
                    if st.button("운용 자금 저장", key=f"btn_save_cap_{market_type}", use_container_width=True, type="primary"):
                        st.session_state[cap_key] = new_capital_input
                        try:
                            res_existing = supabase.table("strategy_settings").select("*").eq("id", 1).execute()
                            existing_data = res_existing.data[0] if res_existing.data else {}
                            
                            existing_data["id"] = 1
                            existing_data[cap_key] = float(new_capital_input)
                            existing_data["strategy_engine_mode"] = current_engine_key
                            
                            supabase.table("strategy_settings").upsert(existing_data).execute()
                            cap_disp = f"${new_capital_input:,.2f}" if market_type == "US" else f"{new_capital_input:,.0f}원"
                            st.success(f"✅ [{market_type}] 총 운용자금이 {cap_disp}으로 성공적으로 업데이트되었습니다.")
                            st.rerun()
                        except Exception as e:
                            st.error(f"❌ DB 저장 실패: {e}")

                max_risk_per_stock = new_capital_input * 0.02
                risk_fmt = f"${max_risk_per_stock:,.2f}" if market_type == "US" else f"{max_risk_per_stock:,.0f}원"
                st.caption(f"🔒 **단일 종목 최대 허용 손실 (2% Rule)**: {risk_fmt}")
                account_total_input = new_capital_input

            st.write("")
            current_table_name = get_holdings_table(market_type)
            try:
                holdings_res = supabase.table(current_table_name).select("*").is_("sell_date", "null").execute()
                holdings_db = pd.DataFrame(holdings_res.data) if holdings_res.data else pd.DataFrame()
            except Exception:
                holdings_db = pd.DataFrame()

            with st.expander(f"💼 현재 {market_type} 시장 보유 종목 ({len(holdings_db)}개)", expanded=True):
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
                    total_risk_amount = 0.0
                    risk_violations = []
                    
                    for _, h_row in holdings_merged.iterrows():
                        ticker = h_row['ticker']
                        raw_name = h_row.get('name', ticker)
                        buy_price = float(h_row.get('buy_price', 0.0))
                        qty = float(h_row.get('quantity', 1.0))
                        
                        curr_row = df_display[df_display['ticker'].str.strip().str.upper() == str(ticker).strip().upper()]
                        curr_price = float(curr_row['종가'].values[0]) if not curr_row.empty else buy_price
                        
                        eval_val = curr_price * qty
                        total_holdings_val += eval_val
                        profit_rate = ((curr_price / buy_price) - 1) * 100 if buy_price > 0 else 0.0
                        stop_loss = buy_price * (1 + (sl_cfg / 100.0))
                        
                        risk_amt = eval_val * (abs(sl_cfg) / 100.0)
                        total_risk_amount += risk_amt
                        
                        stock_risk_pct = (risk_amt / account_total_input) * 100 if account_total_input > 0 else 0.0
                        if stock_risk_pct > 2.0:
                            risk_violations.append(f"{ticker} ({stock_risk_pct:.1f}%)")
                            
                        status = "🚨 손절 이탈" if curr_price <= stop_loss else "정상"
                        
                        holdings_list.append({
                            '종목명': f"[{ticker}] {raw_name}" if market_type == "US" else f"{raw_name}",
                            '종목코드': ticker,
                            '수량': qty,
                            '평단가': buy_price,
                            '현재가': curr_price,
                            '수익률(%)': profit_rate,
                            '평가금액': eval_val,
                            '상태': status
                        })
                    
                    total_risk_pct = (total_risk_amount / account_total_input) * 100 if account_total_input > 0 else 0.0
                    
                    st.markdown("###### 🛡️ 포트폴리오 자금 관리 및 리스크 노출도")
                    risk_col1, risk_col2 = st.columns([3, 1])
                    with risk_col1:
                        st.progress(min(total_risk_pct / 100.0, 1.0))
                    with risk_col2:
                        st.markdown(f"**총 리스크 노출: {total_risk_pct:.2f}%**")
                    
                    risk_amt_fmt = f"${total_risk_amount:,.2f}" if market_type == "US" else f"{total_risk_amount:,.0f}원"
                    st.caption(f"※ 전 종목 손절선 도달 시 포트폴리오 예상 최대 손실금액: **{risk_amt_fmt}**")
                    if risk_violations:
                        st.warning(f"⚠️ 단일 종목 최대 허용 손실(계좌 대비 2.0%) 초과 종목: {', '.join(risk_violations)}")
                        
                    st.write("")
                    df_h = pd.DataFrame(holdings_list)
                    calc_base_total = account_total_input if account_total_input > 0 else total_holdings_val
                    df_h['비중(%)'] = (df_h['평가금액'] / calc_base_total) * 100
                    
                    df_h = df_h[['종목명', '종목코드', '수량', '평단가', '현재가', '수익률(%)', '비중(%)', '평가금액', '상태']]
                    
                    price_fmt_str = '{:,.2f}' if market_type == "US" else '{:,.0f}'
                    st.dataframe(
                        df_h.style.format({
                            '수량': '{:,.2f}' if market_type == "US" else '{:,.0f}', 
                            '평단가': price_fmt_str, '현재가': price_fmt_str,
                            '수익률(%)': '{:+.2f}%', '비중(%)': '{:.1f}%', '평가금액': price_fmt_str
                        }).map(lambda x: 'color: red; font-weight: bold;' if x == '🚨 손절 이탈' else '', subset=['상태'])
                          .map(lambda x: 'color: red;' if float(x) > 0 else 'color: blue;', subset=['수익률(%)']),
                        hide_index=True, use_container_width=True
                    )

            df_rebal = df_display[df_display['매매상태'].isin(['매도필요', '매수추천'])]
            
            display_trade_list(df_rebal[df_rebal['매매상태'] == '매도필요'], "시스템 매도 필요 종목", "매도", "sys_s", target_date_str, is_latest_date, market_type, holdings_db, top_n_cfg, account_total_input, current_engine_key)
            display_trade_list(df_rebal[df_rebal['매매상태'] == '매수추천'], "시스템 매수 추천 종목 (주추천 + 예비추천 2개)", "매수", "sys_b", target_date_str, is_latest_date, market_type, holdings_db, top_n_cfg, account_total_input, current_engine_key)

            st.markdown("---")
            col_m_left, col_m_right = st.columns(2)
            with col_m_left:
                st.markdown("###### ➕ 수동 매수 (Manual Buy)")
                with st.container(border=True):
                    m_ticker = st.text_input("종목코드 (Ticker)", key="m_ticker").strip().upper()
                    c1, c2 = st.columns(2)
                    m_price = c1.number_input("매수가", min_value=0.0, value=0.0, step=0.01 if market_type=="US" else 100.0, format="%.2f" if market_type=="US" else "%.0f", key="m_price")
                    m_qty = c2.number_input("매수 수량", min_value=0.0, value=1.0, step=0.01 if market_type=="US" else 1.0, format="%.2f" if market_type=="US" else "%.0f", key="m_qty")
                    m_date = st.date_input("매수일", value=selected_date, key="m_date")
                    if st.button("수동 매수 실행", use_container_width=True, type="primary"):
                        if m_ticker and m_price > 0 and m_qty > 0:
                            update_holdings(m_ticker, 'BUY', m_price, m_date, m_qty, market_type)
                        else:
                            st.warning("종목코드, 매수가, 수량을 확인하세요.")
            with col_m_right:
                st.markdown("###### 🗑️ 수동 매도 (Manual Sell)")
                with st.container(border=True):
                    ms_ticker = st.text_input("매도 종목코드", key="ms_ticker").strip().upper()
                    c1, c2 = st.columns(2)
                    ms_price = c1.number_input("매도가", min_value=0.0, value=0.0, step=0.01 if market_type=="US" else 100.0, format="%.2f" if market_type=="US" else "%.0f", key="ms_price")
                    ms_qty = c2.number_input("매도 수량", min_value=0.0, value=1.0, step=0.01 if market_type=="US" else 1.0, format="%.2f" if market_type=="US" else "%.0f", key="ms_qty")
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
            * **야간/애프터마켓 매수 규칙**:
                1. **-1% 미만 하락**: 노이즈 구간, 계획대로 100% 체결
                2. **-1% ~ -2.5% 하락**: 체결 강도 약화, **50% 분할 매수** 후 잔량은 익일 아침 체결
                3. **-2.5% 초과 급락 / MA20 이탈**: 추세 훼손, **매수 보류(취소)** 후 예비 2~3위 종목 교체
            * **청산 룰**:
                1. **손절**: 진입가 - 2.5 × ATR
                2. **트레일링스톱**: 수익 +10% 도달 후 고점 대비 -5% 하락
                3. **추세 이탈**: MA20 2일 연속 이탈 시 청산
                4. **레짐 전환**: KOSPI < MA20 시 즉시 전량 현금화
            """)
        elif current_engine_key == "short_term":
            st.info(f"""
            📌 **단기 타점 모멘텀 매매 전략 가이드 (15%+ 랠리 타점)**
            * **초기 자본 세팅**: 2,000만 원 (4개 슬롯 분할 / 종목당 500만 원)
            * **주추천 종목**: 슬롯 개수({top_n_cfg}개)에 맞춰 실시간 선별
            * **후순위 예비 추천**: 상위 200위 조건 만족 종목 중 **예비 2개 종목** 상시 노출
            * **매수 타점 조건**: 모멘텀 순위 **Rank 200위 이내**, 이격도 **-5% ~ +7%**, 가중 모멘텀 **+0.9 이상**
            * **목표 익절 (Take Profit)**: **+15% 도달 시 즉시 청산**
            * **손절 한도 (Stop Loss)**: **-5% 도달 시 즉시 손절**
            * **시간 손절 (Time Stop)**: **보유일 14일 경과 시 미달성 종목 교체 매도**
            """)
        else:
            st.info(f"""
            📌 **하이브리드 듀얼 알파 매매 전략 시스템 가이드 (Ultimate)**
            * **시장 필터**: 지수 종가 기준 MA20 3일 연속 하회 시 신규 매수 전면 중지 (MA20 하회 시 보유 종목 최대 3개로 비중 축소)
            * **자금 관리 룰**: 단일 종목 손실 한도 계좌 자산 대비 최대 2% 제한 & ATR 변동성 수량 산출
            * **리밸런싱 주기**: {rebalance_cycle}
            * **강세장 매수 조건**: 모멘텀 순위 **상위 30위 이내**, RS(90) > 0, 종가 > MA20
            * **약세장 매수 조건**: 모멘텀 순위 **상위 50위 이내**, RS(90) 0.5~1.5 구간, 이격도 -5% ~ +5%
            * **보유 종목 수**: 조건 충족 상위 **{top_n_cfg}개** 분산 투자 (시장 경보 시 최대 3개 제한)
            * **매도 조건** (하나라도 충족 시 익일 매도):
                1. 종가 < MA20 하향 이탈 혹은, 순위 이탈 ({rank_exit_limit}위 밖으로 밀림)
                2. 고정 손절선 이탈 ({sl_cfg}%)
                3. **타임 스탑**: 보유일 10일 이상 & 수익률 +3% 미만 시 자동 청산
            """)

    with tab5:
        st.markdown(f"##### 📊 {market_type} 시장 성과 분석")
        
        if not st.session_state.get('trade_authenticated', False):
            st.info("🔒 상세 성과 내역 확인을 위해 비밀번호를 입력해 주십시오.")
            col_pwd1, col_pwd2 = st.columns([3, 1])
            with col_pwd1:
                input_pwd_5 = st.text_input("매매 비밀번호", type="password", key="pwd_tab5", label_visibility="collapsed")
            with col_pwd2:
                if st.button("잠금 해제", key="btn_unlock_tab5", use_container_width=True):
                    if input_pwd_5 == st.secrets.get("TRADE_PASSWORD", "1234"):
                        st.session_state['trade_authenticated'] = True
                        st.rerun()
                    else:
                        st.error("비밀번호가 일치하지 않습니다.")
        else:
            col_header1, col_header2 = st.columns([5, 1])
            with col_header2:
                if st.button("🔒 다시 잠금", key="btn_lock_tab5", use_container_width=True):
                    st.session_state['trade_authenticated'] = False
                    st.rerun()

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
                    avg_holding_days = df_hist['holding_days'].mean()
                    
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
                    
                    df_hist['is_win'] = df_hist['profit_amount'] > 0
                    streak = df_hist['is_win'].groupby((df_hist['is_win'] != df_hist['is_win'].shift()).cumsum()).cumsum()
                    max_consecutive_wins = streak[df_hist['is_win']].max() if win_trades > 0 else 0
                    
                    df_hist['is_loss'] = df_hist['profit_amount'] < 0
                    streak_loss = df_hist['is_loss'].groupby((df_hist['is_loss'] != df_hist['is_loss'].shift()).cumsum()).cumsum()
                    max_consecutive_losses = streak_loss[df_hist['is_loss']].max() if loss_trades > 0 else 0
                    
                    std_dev = df_hist['profit_rate'].std()
                    total_return_pct = (total_profit / account_total_input) * 100 if account_total_input > 0 else 0.0
                    
                    profit_fmt = lambda x: f"${x:,.2f}" if market_type == "US" else f"{x:,.0f}원"
                    price_fmt = "{:,.2f}" if market_type == "US" else "{:,.0f}"
                    
                    st.markdown("###### 📈 핵심 성과 지표 (KPI)")
                    
                    m1, m2, m3, m4 = st.columns(4)
                    m1.metric("총 실현 손익", profit_fmt(total_profit))
                    m2.metric("누적 자금 수익률", f"{total_return_pct:+.2f}%")
                    m3.metric("성공률 / 실패율", f"{win_rate:.1f}% / {loss_rate:.1f}%")
                    m4.metric("매매 기대 수익 (Expectancy)", profit_fmt(expectancy))
                    
                    m5, m6, m7, m8 = st.columns(4)
                    m5.metric("평균 익절 금액", profit_fmt(avg_win_amt))
                    m6.metric("평균 손절 금액", profit_fmt(avg_loss_amt))
                    m7.metric("평균 수익률 / 변동성(SD)", f"{df_hist['profit_rate'].mean():+.2f}% / {std_dev:.2f}%")
                    m8.metric("손익비 (Profit Factor)", f"{profit_factor:.2f}" if profit_factor < 999 else "무한")
                    
                    m9, m10, m11, m12 = st.columns(4)
                    m9.metric("총 매매 건수", f"{total_trades} 건")
                    m10.metric("평균 보유 기간", f"{avg_holding_days:.1f} 일" if pd.notna(avg_holding_days) else "- 일")
                    m11.metric("최대 연속 수익 횟수", f"{max_consecutive_wins} 연승")
                    m12.metric("최대 연속 손실 횟수", f"{max_consecutive_losses} 연패")
                    
                    st.write("")
                    st.markdown("###### 📅 월별 성과 종합")
                    df_hist['sell_month'] = df_hist['sell_date_dt'].dt.strftime('%Y-%m')
                    df_monthly = df_hist.groupby('sell_month').agg(
                        월간손익=('profit_amount', 'sum'),
                        매매건수=('id', 'count'),
                        평균수익률=('profit_rate', 'mean')
                    ).reset_index().sort_values('sell_month', ascending=False)
                    st.dataframe(df_monthly.style.format({'월간손익': profit_fmt, '평균수익률': '{:+.2f}%'}), hide_index=True, use_container_width=True)
                    
                    st.write("")
                    st.markdown("###### 🔍 수익 기여도 및 보유 기간 분석 차트")
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
    st.markdown("##### 📉 통합 추이 차트")
    if st.session_state.get('trigger_scroll'):
        scroll_to_chart()
        st.session_state['trigger_scroll'] = False 

    top200_tickers = df_display.head(200)['ticker'].tolist()
    if st.session_state.get('selected_ticker_from_table') and st.session_state['selected_ticker_from_table'] not in top200_tickers:
        top200_tickers.append(st.session_state['selected_ticker_from_table'])
        
    ticker_name_map = dict(zip(df_display['ticker'], df_display['종목명']))
    default_ticker = st.session_state.get('selected_ticker_from_table', top200_tickers[0] if top200_tickers else None)
    
    sel_ticker = st.selectbox("분석할 종목 선택 (상위 200위)", options=top200_tickers, index=top200_tickers.index(default_ticker) if default_ticker in top200_tickers else 0, format_func=lambda x: f"[{x}] {ticker_name_map.get(x, x)}")
    if sel_ticker:
        draw_integrated_chart(sel_ticker, market_type, ticker_name_map)
else:
    st.warning("데이터를 불러오는 중입니다. (또는 선택한 날짜에 데이터가 없습니다.)")
