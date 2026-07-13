import streamlit as st
import pandas as pd
from supabase import create_client
import altair as alt  

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
    if '상승금액' in df.columns:
        df_styles.loc[df['상승금액'] > 0, '상승금액'] = 'color: red;'
        df_styles.loc[df['상승금액'] < 0, '상승금액'] = 'color: blue;'
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
        .select("ticker, momentum_rank, weighted_momentum, rs_score, rs_score_10, close_price, ma10, ma20") \
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
    
    res_prev = supabase.table("daily_analysis").select("ticker, momentum_rank, close_price").eq("price_date", prev_date).execute()
    df_prev = pd.DataFrame(res_prev.data).rename(columns={'momentum_rank': '순위_prev', 'close_price': '종가_prev'})
    
    df_final = pd.merge(df_final, df_prev, on="ticker", how='left')
    df_final = df_final.rename(columns={
        'momentum_rank': '순위', 
        'weighted_momentum': 'MOT', 
        'rs_score': 'RS(90)', 
        'rs_score_10': 'RS(10)', 
        'close_price': '종가', 
        'ma10': 'MA10', 
        'ma20': 'MA20'
    })
    
    df_final['종가_prev'] = pd.to_numeric(df_final['종가_prev'], errors='coerce')
    df_final['상승금액'] = df_final['종가'] - df_final['종가_prev']
    
    df_final['변동'] = df_final['순위_prev'].fillna(999) - df_final['순위']
    df_final['is_new_top30'] = (df_final['순위'] <= 30) & (df_final['순위_prev'] > 30)
    df_final['is_pullback'] = (df_final['순위'] <= 100) & (df_final['RS(90)'] > 0) & (df_final['변동'] > 0)
    df_final['MA20'] = df_final['MA20'].fillna(0)
    df_final['is_no6_opt'] = (df_final['순위'] <= 30) & (df_final['RS(90)'] > 0) & (df_final['종가'] > df_final['MA20']) & (df_final['MA20'] > 0)
    
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

def display_trade_list(data, title, button_label, key_prefix, target_date, is_latest_date):
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
                        | RS(90): <span style="color: #137333; font-weight: bold; font-family: monospace; background-color: #e6f4ea; padding: 2px 5px; border-radius: 4px;">{row['RS(90)']:.2f}</span>
                        | RS(10): <span style="color: #b06000; font-weight: bold; font-family: monospace; background-color: #fdf2e9; padding: 2px 5px; border-radius: 4px;">{row['RS(10)']:.2f}</span>
                    </span>
                </div>
                """, unsafe_allow_html=True)
            
                if is_latest_date:
                    with c2.popover(button_label):
                        st.write(f"**{row['종목명']}**")
                        input_price = st.number_input(f"{button_label}가", value=float(row['종가']), key=f"p_{key_prefix}_{row['ticker']}")
                        input_qty = st.number_input("수량", value=1, min_value=1, step=1, key=f"q_{key_prefix}_{row['ticker']}")
                        
                        if st.button("확인", key=f"btn_{key_prefix}_{row['ticker']}"):
                            action_type = 'SELL' if '매도' in title else 'BUY'
                            update_holdings(row['ticker'], action_type, input_price, target_date, input_qty)
                else:
                    c2.markdown("<div style='color:#999999; font-size:0.85em; margin-top:8px; text-align:right;'>과거일 매매불가</div>", unsafe_allow_html=True)

# --- 2. UI 메인 실행 파트 ---
st.markdown("##### 📈 Momentum Dashboard v1.6.4")
market_safe = get_market_regime()

if not market_safe:
    st.warning("⚠️ 시장 주의보: 지수가 MA20 아래입니다. 리스크 관리에 집중하세요.")

with st.sidebar:
    market_type = st.radio("Market", ["KR", "US"], horizontal=True)
    all_dates = get_available_dates()
    selected_date = st.date_input("Date", value=pd.to_datetime(all_dates[0]) if all_dates else None)
    if st.button("Refresh"): st.rerun()

is_latest_date = False
if all_dates and selected_date:
    latest_date_str = max(all_dates)
    selected_date_str = selected_date.strftime('%Y-%m-%d')
    if selected_date_str == latest_date_str:
        is_latest_date = True

df_display = get_data(selected_date, all_dates, market_type)

if 'trade_authenticated' not in st.session_state:
    st.session_state['trade_authenticated'] = False

if df_display is not None:
    tab1, tab2, tab3, tab4, tab5 = st.tabs(["Overview", "New Entries", "🎯 Pullback", "🚀 No.6 최적화", "📊 성과 분석"])
    
    col_order = ['순위', '변동', '종목명', 'MOT', 'RS(90)', 'RS(10)', '종가', '상승금액', 'MA20', 'ticker'] 
    tab_dfs = [df_display.head(100), df_display[df_display['is_new_top30']], df_display[df_display['is_pullback']], df_display[df_display['is_no6_opt']]]

    tab_descriptions = [
        "📌 **조회 기준**: 선택한 시장의 전체 종목 중 모멘텀 순위 **상위 100개 종목** (1위~100위 오름차순 정렬)",
        "📌 **조회 기준**: 직전 거래일 30위 밖에서 당일 **상위 30위(Top 30) 이내로 새롭게 진입**한 종목",
        "📌 **조회 기준**: 모멘텀 순위 100위 이내, RS(90) 0 초과 조건에서 직전 대비 **순위가 상승 중(숫자 감소)인 눌림목 종목**"
    ]

    clicked_ticker = None
    
    for i, tab in enumerate([tab1, tab2, tab3]):
        with tab:
            st.markdown(f"<span style='color: #555555; font-size: 0.9em;'>{tab_descriptions[i]}</span>", unsafe_allow_html=True)
            st.write("")
            
            df_target = tab_dfs[i][col_order].copy()
            event = st.dataframe(
                df_target.style.apply(apply_styles, axis=None).format({
                    'MOT': '{:.2f}', 'RS(90)': '{:.2f}', 'RS(10)': '{:.2f}', '종가': '{:,.0f}', '상승금액': '{:+,.0f}', 'MA20': '{:,.0f}', '변동': '{:+.0f}'
                }, na_rep='-'), 
                hide_index=True, 
                use_container_width=True,
                on_select="rerun",  
                selection_mode="single-row",
                column_config={
                    "MOT": st.column_config.NumberColumn(
                        "MOT",
                        help="가중 모멘텀(Weighted Momentum): 1, 2, 4, 6, 12개월 수익률에 각각 12, 6, 4, 2, 1의 가중치를 곱해 합산한 수치입니다."
                    ),
                    "RS(90)": st.column_config.NumberColumn(
                        "RS(90)",
                        help="중장기 상대강도(Relative Strength 90D): 벤치마크 지수 대비 최근 90일간의 강도를 의미하며 주도주 판별에 쓰입니다."
                    ),
                    "RS(10)": st.column_config.NumberColumn(
                        "RS(10)",
                        help="단기 상대강도(Relative Strength 10D): 벤치마크 지수 대비 최근 10일간의 강도를 의미하며, 눌림목 후 단기 수급 유입 전환을 포착하기에 좋습니다."
                    )
                },
                key=f"df_tab_{i}"
            )
            
            if event and "rows" in event.get("selection", {}) and event["selection"]["rows"]:
                selected_row_idx = event["selection"]["rows"][0]
                clicked_ticker = df_target.iloc[selected_row_idx]['ticker']

    if clicked_ticker:
        st.session_state['selected_ticker_from_table'] = clicked_ticker

    # --- Tab 4 (매매 지시서 구역) ---
    with tab4:
        st.markdown("##### 📋 오늘의 매매 지시서")
        
        if not is_latest_date:
            st.warning("⚠️ 과거 영업일의 데이터를 조회 중입니다. 시스템 및 개별 매매는 가장 최근 영업일에만 활성화됩니다.")
        
        if not st.session_state['trade_authenticated']:
            st.info("🔒 실제 매매 및 보유 종목 확인을 위해 비밀번호를 입력해 주십시오.")
            col_pwd1, col_pwd2 = st.columns([3, 1])
            with col_pwd1:
                input_pwd_4 = st.text_input("매매 비밀번호", type="password", key="pwd_tab4", label_visibility="collapsed")
            with col_pwd2:
                if st.button("잠금 해제", key="btn_unlock_tab4", use_container_width=True):
                    valid_pwd = st.secrets.get("TRADE_PASSWORD", "1234")
                    if input_pwd_4 == valid_pwd:
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

            holdings_res = supabase.table("current_holdings").select("*").is_("sell_date", "null").execute()
            holdings_db = pd.DataFrame(holdings_res.data) if holdings_res.data else pd.DataFrame()

            with st.expander(f"💼 현재 보유 종목 ({len(holdings_db)}개)", expanded=True):
                if holdings_db.empty:
                    st.info("보유 종목이 없습니다.")
                else:
                    df_stocks = pd.DataFrame(supabase.table("stocks").select("ticker, name").execute().data)
                    if not df_stocks.empty:
                        df_stocks['ticker'] = df_stocks['ticker'].astype(str).str.strip()
                        holdings_merged = pd.merge(holdings_db, df_stocks, on="ticker", how="left")
                    else:
                        holdings_merged = holdings_db
                        holdings_merged['name'] = holdings_merged['ticker']
                    
                    for _, h_row in holdings_merged.iterrows():
                        ticker = h_row['ticker']
                        name = h_row.get('name', ticker)
                        if pd.isna(name): name = ticker
                        
                        buy_date = h_row.get('buy_date')
                        buy_date = buy_date if pd.notna(buy_date) and buy_date is not None else '-'
                        
                        raw_bp = h_row.get('buy_price')
                        buy_price = float(raw_bp) if pd.notna(raw_bp) and raw_bp is not None else 0.0
                        
                        raw_qty = h_row.get('quantity')
                        qty = int(raw_qty) if pd.notna(raw_qty) and raw_qty is not None else 1
                        
                        curr_row = df_display[df_display['ticker'] == ticker]
                        curr_price = float(curr_row['종가'].values[0]) if not curr_row.empty else buy_price
                        
                        profit_amount = (curr_price - buy_price) * qty if buy_price > 0 else 0.0
                        profit_rate = ((curr_price / buy_price) - 1) * 100 if buy_price > 0 else 0.0
                        
                        if profit_rate > 0:
                            p_color = "#d62728"
                        elif profit_rate < 0:
                            p_color = "#1f77b4"
                        else:
                            p_color = "#555555"
                        
                        c1, c2 = st.columns([4, 1])
                        
                        c1.markdown(f"""
                        <div style="line-height: 1.6;">
                            <strong style="font-size: 1.1em; color: #111111;">{name}</strong> 
                            <span style="font-size: 0.8em; color: #888888; margin-left: 4px;">({ticker})</span>
                            <span style="font-size: 0.95em; font-weight: bold; color: {p_color}; margin-left: 12px;">
                                {profit_rate:+.2f}% ({profit_amount:+,.0f}원)
                            </span>
                            <br>
                            <span style="color: #555555; font-size: 0.85em;">
                                매수일: <span style="background-color: #f1f3f6; padding: 2px 6px; border-radius: 4px; font-family: monospace;">{buy_date}</span> | 
                                매수가: <span style="background-color: #f1f3f6; padding: 2px 6px; border-radius: 4px; font-family: monospace;">{buy_price:,.0f}원</span> | 
                                현재가: <span style="background-color: #f1f3f6; padding: 2px 6px; border-radius: 4px; font-family: monospace;">{curr_price:,.0f}원</span> | 
                                수량: <span style="background-color: #f1f3f6; padding: 2px 6px; border-radius: 4px; font-family: monospace;">{qty}주</span>
                            </span>
                        </div>
                        """, unsafe_allow_html=True)
                        
                        if is_latest_date:
                            with c2.popover("개별 매도"):
                                st.write(f"**{name}** 수동 매도")
                                input_price = st.number_input("매도가", value=curr_price, key=f"p_force_{ticker}")
                                input_qty = st.number_input("수량", value=qty, min_value=1, step=1, key=f"q_force_{ticker}")
                                if st.button("매도 확정", key=f"btn_force_{ticker}"):
                                    update_holdings(ticker, 'SELL', input_price, selected_date, input_qty)
                        else:
                            c2.markdown("<div style='color:#999999; font-size:0.85em; margin-top:8px; text-align:right;'>과거일 매매불가</div>", unsafe_allow_html=True)
            
            st.write("") 
            df_rebal = df_display[df_display['매매상태'].isin(['매도필요', '매수추천'])]
            display_trade_list(df_rebal[df_rebal['매매상태'] == '매도필요'], "시스템 매도 필요", "매도", "sys_s", selected_date, is_latest_date)
            display_trade_list(df_rebal[df_rebal['매매상태'] == '매수추천'], "시스템 매수 추천", "매수", "sys_b", selected_date, is_latest_date)
        
            st.divider()
            with st.expander("🔍 No.6 전략 필터링 조건 보기"):
                c1, c2 = st.columns(2)
                with c1: st.markdown("**[매수 조건]**\n- 순위: 30위 이내\n- RS: 0 초과\n- 추세: 종가 > MA20")
                with c2: st.markdown("**[매도 조건]**\n- 순위: 30위 밖\n- 추세: 종가 < MA20")

    # --- Tab 5 (성과 분석 구역) ---
    with tab5:
        st.markdown("##### 📊 단일 테이블 기반 매매 성과 분석")
        
        if not st.session_state['trade_authenticated']:
            st.info("🔒 상세 성과 내역 확인을 위해 비밀번호를 입력해 주십시오.")
            col_pwd1, col_pwd2 = st.columns([3, 1])
            with col_pwd1:
                input_pwd_5 = st.text_input("매매 비밀번호", type="password", key="pwd_tab5", label_visibility="collapsed")
            with col_pwd2:
                if st.button("잠금 해제", key="btn_unlock_tab5", use_container_width=True):
                    valid_pwd = st.secrets.get("TRADE_PASSWORD", "1234")
                    if input_pwd_5 == valid_pwd:
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

            history_res = supabase.table("current_holdings").select("*").not_.is_("sell_date", "null").execute()
            
            if not history_res.data:
                st.info("청산된 매매 이력이 존재하지 않습니다.")
            else:
                df_hist = pd.DataFrame(history_res.data)
                df_stocks_info = pd.DataFrame(supabase.table("stocks").select("ticker, name").execute().data)
                if not df_stocks_info.empty:
                    df_stocks_info['ticker'] = df_stocks_info['ticker'].astype(str).str.strip()
                    df_hist = pd.merge(df_hist, df_stocks_info, on="ticker", how="left")
                    df_hist['종목명'] = df_hist['name'].fillna(df_hist['ticker'])
                else:
                    df_hist['종목명'] = df_hist['ticker']

                df_hist['profit_amount'] = pd.to_numeric(df_hist['profit_amount'], errors='coerce').fillna(0.0)
                df_hist['profit_rate'] = pd.to_numeric(df_hist['profit_rate'], errors='coerce').fillna(0.0)
                
                total_profit = df_hist['profit_amount'].sum()
                total_trades = len(df_hist)
                win_trades = len(df_hist[df_hist['profit_amount'] > 0])
                win_rate = (win_trades / total_trades * 100) if total_trades > 0 else 0.0
                avg_return = df_hist['profit_rate'].mean()
                
                m1, m2, m3, m4 = st.columns(4)
                m1.metric("총 실현 손익", f"{total_profit:,.0f} 원")
                m2.metric("총 매매 회수", f"{total_trades} 건")
                m3.metric("승률", f"{win_rate:.1f} %")
                m4.metric("평균 수익률", f"{avg_return:+.2f} %")
                
                st.write("")
                st.markdown("###### 📅 월별 성과 종합")
                df_hist['sell_month'] = pd.to_datetime(df_hist['sell_date']).dt.strftime('%Y-%m')
                df_monthly = df_hist.groupby('sell_month').agg(
                    월간손익=('profit_amount', 'sum'),
                    매매건수=('id', 'count'),
                    평균수익률=('profit_rate', 'mean')
                ).reset_index().sort_values('sell_month', ascending=False)
                
                st.dataframe(
                    df_monthly.style.format({'월간손익': '{:,.0f}', '평균수익률': '{:+.2f}%'}),
                    hide_index=True, use_container_width=True
                )
                
                st.write("")
                st.markdown("###### 📜 상세 매매 완료 내역")
                display_hist_cols = ['sell_date', 'ticker', '종목명', 'buy_date', 'buy_price', 'sell_price', 'quantity', 'profit_amount', 'profit_rate']
                df_hist_sorted = df_hist.sort_values('sell_date', ascending=False)
                
                st.dataframe(
                    df_hist_sorted[display_hist_cols].style.format({
                        'buy_price': '{:,.0f}', 'sell_price': '{:,.0f}', 'quantity': '{:,.0f}',
                        'profit_amount': '{:,.0f}', 'profit_rate': '{:+.2f}%'
                    }),
                    hide_index=True, use_container_width=True
                )

    # --- 📉 하단 주가 및 모멘텀 순위 시계열 차트 구역 ---
    st.divider()
    st.markdown("##### 📉 종목별 최근 주가 및 시장 흐름 통합 추이")
    
    distinct_tickers = sorted(df_display['ticker'].unique())
    ticker_name_map = dict(zip(df_display['ticker'], df_display['종목명']))
    
    default_index = 0
    if 'selected_ticker_from_table' in st.session_state:
        target_ticker = st.session_state['selected_ticker_from_table']
        if target_ticker in distinct_tickers:
            default_index = distinct_tickers.index(target_ticker)
            
    selected_chart_ticker = st.selectbox(
        "분석할 종목을 선택하세요 (위 표에서 종목 행을 직접 클릭해도 자동으로 변경됩니다)", 
        options=distinct_tickers, 
        index=default_index,
        format_func=lambda x: f"{ticker_name_map.get(x, x)} ({x})"
    )
    
    if selected_chart_ticker:
        # 1. 개별 종목 데이터 조회
        chart_res = supabase.table("daily_analysis") \
            .select("price_date, close_price, momentum_rank, ma20") \
            .eq("ticker", selected_chart_ticker) \
            .order("price_date", desc=True) \
            .limit(20).execute()
            
        # 2. 시장 벤치마크 지수 데이터 조회
        benchmark_ticker = "^KS11" if market_type == "KR" else "^GSPC"
        index_res = supabase.table("daily_analysis") \
            .select("price_date, close_price") \
            .eq("ticker", benchmark_ticker) \
            .order("price_date", desc=True) \
            .limit(20).execute()
            
        if not chart_res.data:
            st.info("해당 종목의 시계열 차트 데이터가 존재하지 않습니다.")
        else:
            # 개별 종목 DF 전처리
            df_chart = pd.DataFrame(chart_res.data)
            df_chart['price_date'] = pd.to_datetime(df_chart['price_date'])
            df_chart = df_chart.sort_values('price_date', ascending=True)
            df_chart['price_date_str'] = df_chart['price_date'].dt.strftime('%m-%d')
            df_chart['close_price'] = pd.to_numeric(df_chart['close_price'], errors='coerce')
            df_chart['ma20'] = pd.to_numeric(df_chart['ma20'], errors='coerce')
            
            # 지수 DF 전처리 후 머지
            if index_res.data:
                df_idx_chart = pd.DataFrame(index_res.data).rename(columns={'close_price': 'index_price'})
                df_idx_chart['price_date'] = pd.to_datetime(df_idx_chart['price_date'])
                df_idx_chart['index_price'] = pd.to_numeric(df_idx_chart['index_price'], errors='coerce')
                df_merged = pd.merge(df_chart, df_idx_chart, on='price_date', how='left')
            else:
                df_merged = df_chart
                df_merged['index_price'] = 0.0

            idx_name = "KOSPI" if market_type == "KR" else "S&P 500"
            stock_name = ticker_name_map.get(selected_chart_ticker, selected_chart_ticker)

            base = alt.Chart(df_merged).encode(
                x=alt.X('price_date_str:N', title=None, axis=alt.Axis(labelAngle=-45))
            )

            # [상단 차트] 개별 종목 주가 + MA20 + 모멘텀 순위
            line_stock = base.mark_line(color='#1f77b4', strokeWidth=2.5).encode(
                y=alt.Y('close_price:Q', title=f'{stock_name} 주가', scale=alt.Scale(zero=False)),
                tooltip=[alt.Tooltip('price_date_str:N', title='날짜'), alt.Tooltip('close_price:Q', title='종가', format=',.0f')]
            )

            line_ma20 = base.mark_line(color='#ff4b4b', strokeDash=[4, 4]).encode(
                y=alt.Y('ma20:Q')
            )

            line_rank = base.mark_line(color='#ff7f0e', point=True).encode(
                y=alt.Y('momentum_rank:Q', title='모멘텀 순위 (1~100)', scale=alt.Scale(domain=[100, 0])),
                tooltip=[alt.Tooltip('momentum_rank:Q', title='모멘텀 순위')]
            )

            chart_top = alt.layer(line_stock, line_ma20, line_rank).resolve_scale(y='independent').properties(height=350)

            # [하단 차트] 시장 지수
            chart_bottom = base.mark_line(color='#2ca02c', strokeWidth=2).encode(
                y=alt.Y('index_price:Q', title=f'{idx_name} 지수', scale=alt.Scale(zero=False)),
                tooltip=[alt.Tooltip('price_date_str:N', title='날짜'), alt.Tooltip('index_price:Q', title='지수', format=',.2f')]
            ).properties(height=150)

            # 레이아웃 렌더링
            st.markdown(f"""
            <div style="text-align: center; margin-bottom: 10px; font-size: 0.9em; color: #555555;">
                <span style="color:#1f77b4; font-weight:bold;">━</span> {stock_name} 주가 | 
                <span style="color:#ff4b4b; font-weight:bold;">---</span> {stock_name} MA20 | 
                <span style="color:#ff7f0e; font-weight:bold;">━●━</span> 모멘텀 순위 (우측 Y축 반전)
            </div>
            """, unsafe_allow_html=True)
            
            st.altair_chart(chart_top, use_container_width=True)
            
            st.markdown(f"""
            <div style="text-align: center; margin-top: 5px; margin-bottom: 10px; font-size: 0.9em; color: #555555;">
                <span style="color:#2ca02c; font-weight:bold;">━</span> {idx_name} 지수 흐름
            </div>
            """, unsafe_allow_html=True)
            
            st.altair_chart(chart_bottom, use_container_width=True)
else:
    st.warning("데이터를 불러오는 중입니다.")
