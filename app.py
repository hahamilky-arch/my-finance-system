import streamlit as st
import pandas as pd
from supabase import create_client
import altair as alt
import streamlit.components.v1 as components
import time

# 백지화 방지를 위해 최상단 배치
st.set_page_config(layout="wide")

# 최상단 앵커 (플로팅 버튼 클릭 시 이동할 타겟)
st.markdown("<div id='top-section'></div>", unsafe_allow_html=True)

# 상단 여백 조정 및 왼쪽 하단 플로팅 버튼 CSS
st.markdown("""
    <style>
    .block-container {
        padding-top: 3rem !important;
        padding-bottom: 2rem !important;
    }
    html, body, [class*="st-"] {
        font-size: 14px !important;
    }
    h5 {
        font-size: 1.2rem !important;
        margin-bottom: 0.5rem !important;
    }
    .floating-btn-left {
        position: fixed;
        bottom: 25px;
        left: 25px;
        background: linear-gradient(135deg, #2b5876 0%, #4e4376 100%);
        color: white !important;
        border-radius: 30px;
        padding: 10px 18px;
        font-size: 13px;
        font-weight: bold;
        box-shadow: 0 4px 15px rgba(0,0,0,0.2);
        cursor: pointer;
        z-index: 99999;
        text-decoration: none;
        display: flex;
        align-items: center;
        gap: 6px;
        transition: all 0.3s ease;
        border: 1px solid rgba(255,255,255,0.2);
    }
    .floating-btn-left:hover {
        transform: translateY(-3px);
        box-shadow: 0 6px 20px rgba(0,0,0,0.3);
        background: linear-gradient(135deg, #1e3c72 0%, #2a5298 100%);
    }
    </style>
    <a href="#top-section" class="floating-btn-left" title="상단 표로 이동">
        <span>⬆️</span> <span>상단 표로 이동</span>
    </a>
""", unsafe_allow_html=True)

# Supabase 연결
supabase = create_client(st.secrets["SUPABASE_URL"], st.secrets["SUPABASE_KEY"])

# JS 자동 스크롤 함수
def scroll_to_chart():
    js = f"""
    <script>
        /* Timestamp for cache busting: {time.time()} */
        setTimeout(function() {{
            const el = window.parent.document.getElementById('chart-section');
            if (el) {{
                el.scrollIntoView({{behavior: 'smooth', block: 'start'}});
            }}
        }}, 100);
    </script>
    """
    components.html(js, height=0)

# --- 1. 데이터 처리 및 스타일 함수 ---
def apply_styles(df):
    df_styles = pd.DataFrame('', index=df.index, columns=df.columns)
    
    if '변동' in df.columns:
        df_styles.loc[df['변동'] > 0, '변동'] += 'color: red;'
        df_styles.loc[df['변동'] < 0, '변동'] += 'color: blue;'
    if '상승금액' in df.columns:
        df_styles.loc[df['상승금액'] > 0, '상승금액'] += 'color: red;'
        df_styles.loc[df['상승금액'] < 0, '상승금액'] += 'color: blue;'
    
    if '매매상태' in df.columns:
        df_styles.loc[df['매매상태'] == '매수추천', '매매상태'] += 'color: #d62728; font-weight: bold;'
        df_styles.loc[df['매매상태'] == '매도필요', '매매상태'] += 'color: #1f77b4; font-weight: bold;'
        df_styles.loc[df['매매상태'] == '보유중', '매매상태'] += 'color: #2ca02c; font-weight: bold;'

    if 'RS(90)' in df.columns:
        df_styles.loc[df['RS(90)'] > 0, 'RS(90)'] += 'color: #d62728; font-weight: bold;'
        df_styles.loc[df['RS(90)'] <= 0, 'RS(90)'] += 'color: #bbbbbb;'
    if 'RS(10)' in df.columns:
        df_styles.loc[df['RS(10)'] > 0, 'RS(10)'] += 'color: #d62728; font-weight: bold;'
        df_styles.loc[df['RS(10)'] <= 0, 'RS(10)'] += 'color: #bbbbbb;'

    # 💡 [요구사항 반영] 주가가 MA20보다 위인 경우에는 MA20 강조, 아니면 흐리게
    if '종가' in df.columns and 'MA20' in df.columns:
        above_ma20 = (df['MA20'] > 0) & (df['종가'] > df['MA20'])
        df_styles.loc[above_ma20, 'MA20'] += 'color: #d62728; font-weight: bold;'
        df_styles.loc[~above_ma20, 'MA20'] += 'color: #aaaaaa;'

    if '순위' in df.columns:
        for idx, rank in df['순위'].items():
            if pd.notna(rank):
                if rank <= 10:
                    df_styles.loc[idx, :] = df_styles.loc[idx, :] + 'background-color: rgba(255, 235, 156, 0.4);' 
                elif rank <= 20:
                    df_styles.loc[idx, :] = df_styles.loc[idx, :] + 'background-color: rgba(198, 239, 206, 0.4);' 
                elif rank <= 30:
                    df_styles.loc[idx, :] = df_styles.loc[idx, :] + 'background-color: rgba(189, 215, 238, 0.4);' 
                    
    return df_styles

def get_holdings_table(market_type):
    return "current_holdings_us" if market_type == "US" else "current_holdings"

def get_current_holdings(market_type):
    table_name = get_holdings_table(market_type)
    try:
        res = supabase.table(table_name).select("ticker").is_("sell_date", "null").execute()
        return [item['ticker'] for item in res.data] if res.data else []
    except Exception as e:
        return []

def update_holdings(ticker, action, price, trade_date, quantity, market_type):
    table_name = get_holdings_table(market_type)
    trade_date_str = trade_date.strftime('%Y-%m-%d')
    
    if action == 'BUY':
        try:
            supabase.table(table_name).insert({
                "ticker": str(ticker).strip(),
                "buy_date": trade_date_str,
                "buy_price": float(price),
                "quantity": float(quantity)
            }).execute()
            st.success(f"✅ [{ticker}] 매수 기록 완료! (저장경로: {table_name})")
        except Exception as e:
            st.error(f"❌ 매수 DB 저장 실패 ({table_name} 테이블 확인 요망): {str(e)}")
            return
        
    elif action == 'SELL':
        try:
            res = supabase.table(table_name).select("*").eq("ticker", ticker).is_("sell_date", "null").execute()
            
            if res.data:
                holding = res.data[0]
                row_id = holding.get('id')
                
                raw_bp = holding.get('buy_price')
                buy_price = float(raw_bp) if pd.notna(raw_bp) and raw_bp is not None else 0.0
                
                raw_qty = holding.get('quantity')
                db_quantity = float(raw_qty) if pd.notna(raw_qty) and raw_qty is not None else float(quantity)
                
                profit_amount = 0.0
                profit_rate = 0.0
                if buy_price > 0:
                    profit_amount = (float(price) - buy_price) * db_quantity
                    profit_rate = ((float(price) / buy_price) - 1) * 100
                
                supabase.table(table_name).update({
                    "sell_date": trade_date_str,
                    "sell_price": float(price),
                    "profit_amount": float(profit_amount),
                    "profit_rate": round(float(profit_rate), 2)
                }).eq("id", row_id).execute()
                
                st.error(f"🗑️ [{ticker}] 매도 처리 및 정보 업데이트 완료!")
            else:
                supabase.table(table_name).insert({
                    "ticker": str(ticker).strip(),
                    "sell_date": trade_date_str,
                    "sell_price": float(price),
                    "quantity": float(quantity)
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
    
    # 💡 백테스트 최적화 조건: 모멘텀 30위 이내 + RS(90) > 0 + RS(10) > 0 + 종가 > MA20
    df_final['is_no6_opt'] = (df_final['순위'] <= 30) & (df_final['RS(90)'] > 0) & (df_final['RS(10)'] > 0) & (df_final['MA20'] > 0) & (df_final['종가'] > df_final['MA20'])
    
    df_stocks = pd.DataFrame(supabase.table("stocks").select("ticker, name").execute().data)
    if not df_stocks.empty:
        df_stocks['ticker'] = df_stocks['ticker'].astype(str).str.strip()
    else:
        df_stocks = pd.DataFrame(columns=['ticker', 'name'])

    df_final = pd.merge(df_final, df_stocks, on="ticker", how="left").rename(columns={'name': '종목명'})
    df_final['종목명'] = df_final['종목명'].fillna(df_final['ticker'])

    if market_type == "US":
        df_final['종목명'] = df_final.apply(lambda r: f"[{r['ticker']}] {r['종목명']}", axis=1)

    my_holdings = get_current_holdings(market_type)

    # 💡 보유 여부 및 매매 조건에 따른 상태 분류 (매도: 20일선 이탈 OR RS(10) <= 0 OR 순위 30위 밖)
    def classify_status(row):
        is_in_holdings = row['ticker'] in my_holdings
        if is_in_holdings:
            if (row['MA20'] > 0 and row['종가'] < row['MA20']) or (row['RS(10)'] <= 0) or (row['순위'] > 30):
                return '매도필요'
            return '보유중'
        else:
            if row['is_no6_opt']:
                return '매수추천'
            return ''

    df_final['매매상태'] = df_final.apply(classify_status, axis=1)
    
    return df_final.sort_values('순위')

def display_trade_list(data, title, button_label, key_prefix, target_date, is_latest_date, market_type, holdings_df):
    with st.expander(f"🚨 {title} ({len(data)}개)", expanded=True):
        if data.empty:
            st.write(f"해당되는 {button_label} 종목이 없습니다.")
        else:
            for _, row in data.iterrows():
                ticker = row['ticker']
                c1, c2 = st.columns([4, 1])
                
                c1.markdown(f"""
                <div style="line-height: 1.6; margin-top: 4px;">
                    <strong style="font-size: 1.1em; color: #111111;">{row['종목명']}</strong> 
                    <span style="font-size: 0.8em; color: #888888; margin-left: 4px;">({ticker})</span>
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
                        input_price = st.number_input(f"{button_label}가", value=float(row['종가']), key=f"p_{key_prefix}_{ticker}")
                        
                        default_qty = 1.0
                        if button_label == '매도' and not holdings_df.empty:
                            matched_h = holdings_df[holdings_df['ticker'] == ticker]
                            if not matched_h.empty:
                                val = matched_h.iloc[0].get('quantity', 1.0)
                                default_qty = float(val) if pd.notna(val) else 1.0
                        if default_qty <= 0:
                            default_qty = 0.000001

                        input_qty = st.number_input("수량", value=default_qty, min_value=0.0, format="%.6f", key=f"q_{key_prefix}_{ticker}")

                        if st.button("확인", key=f"btn_{key_prefix}_{ticker}"):
                            action_type = 'SELL' if '매도' in title else 'BUY'
                            update_holdings(ticker, action_type, input_price, target_date, input_qty, market_type)
                else:
                    c2.markdown("<div style='color:#999999; font-size:0.85em; margin-top:8px; text-align:right;'>과거일 매매불가</div>", unsafe_allow_html=True)

# --- 2. UI 메인 실행 파트 ---
st.markdown("##### 📈 Momentum Dashboard v1.7.8")
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

if 'trigger_scroll' not in st.session_state:
    st.session_state['trigger_scroll'] = False

if df_display is not None:
    tab1, tab2, tab3, tab4, tab5 = st.tabs(["Overview", "New Entries", "🎯 Pullback", "🚀 No.6 최적화", "📊 성과 분석"])
    
    col_order = ['순위', '변동', '매매상태', '종목명', 'MOT', 'RS(90)', 'RS(10)', '종가', '상승금액', 'MA20', 'ticker'] 
    tab_dfs = [df_display.head(100), df_display[df_display['is_new_top30']], df_display[df_display['is_pullback']], df_display[df_display['is_no6_opt']]]

    tab_descriptions = [
        "📌 **조회 기준**: 선택한 시장의 전체 종목 중 모멘텀 순위 **상위 100개 종목** (1위~100위 오름차순 정렬)",
        "📌 **조회 기준**: 직전 거래일 30위 밖에서 당일 **상위 30위(Top 30) 이내로 새롭게 진입**한 종목",
        "📌 **조회 기준**: 모멘텀 순위 100위 이내, RS(90) 0 초과 조건에서 직전 대비 **순위가 상승 중(숫자 감소)인 눌림목 종목**"
    ]

    for i, tab in enumerate([tab1, tab2, tab3]):
        with tab:
            st.markdown(f"<span style='color: #555555; font-size: 0.95em;'>{tab_descriptions[i]}</span>", unsafe_allow_html=True)
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
                    "MOT": st.column_config.NumberColumn("MOT", help="가중 모멘텀(Weighted Momentum)"),
                    "RS(90)": st.column_config.NumberColumn("RS(90)", help="중장기 상대강도(Relative Strength 90D)"),
                    "RS(10)": st.column_config.NumberColumn("RS(10)", help="단기 상대강도(Relative Strength 10D)")
                },
                key=f"df_tab_{i}"
            )
            
            if event and "rows" in event.get("selection", {}) and event["selection"]["rows"]:
                selected_row_idx = event["selection"]["rows"][0]
                clicked_ticker = df_target.iloc[selected_row_idx]['ticker']
                
                st.session_state['selected_ticker_from_table'] = clicked_ticker
                st.session_state['trigger_scroll'] = True

    # --- Tab 4 (백테스트 최적화 매매 지시서 구역) ---
    with tab4:
        st.markdown("##### 📋 백테스트 최적화 기반 매매 지시서")
        
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

            current_table_name = get_holdings_table(market_type)
            try:
                holdings_res = supabase.table(current_table_name).select("*").is_("sell_date", "null").execute()
                holdings_db = pd.DataFrame(holdings_res.data) if holdings_res.data else pd.DataFrame()
            except Exception as e:
                holdings_db = pd.DataFrame()

            # 💼 보유 종목 현황 및 -5% 손절 감지 알림
            with st.expander(f"💼 현재 {market_type} 시장 보유 종목 ({len(holdings_db)}개)", expanded=True):
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
                        
                        if market_type == "US":
                            name = f"[{ticker}] {name}"
                        
                        buy_date = h_row.get('buy_date', '-')
                        raw_bp = h_row.get('buy_price', 0.0)
                        buy_price = float(raw_bp) if pd.notna(raw_bp) and raw_bp is not None else 0.0
                        
                        raw_qty = h_row.get('quantity', 1.0)
                        qty = float(raw_qty) if pd.notna(raw_qty) and raw_qty is not None else 1.0
                        if qty <= 0: qty = 0.000001
                        
                        curr_row = df_display[df_display['ticker'] == ticker]
                        curr_price = float(curr_row['종가'].values[0]) if not curr_row.empty else buy_price
                        
                        profit_amount = (curr_price - buy_price) * qty if buy_price > 0 else 0.0
                        profit_rate = ((curr_price / buy_price) - 1) * 100 if buy_price > 0 else 0.0
                        
                        # 💡 -5% 이하 손절 이탈 감지 알림 표시
                        stop_loss_warning = ""
                        if profit_rate <= -5.0:
                            stop_loss_warning = " 🚨 [손절 경고: -5% 이탈]"
                            p_color = "#d62728"
                        elif profit_rate > 0:
                            p_color = "#d62728"
                        else:
                            p_color = "#1f77b4"
                        
                        c1, c2 = st.columns([4, 1])
                        
                        c1.markdown(f"""
                        <div style="line-height: 1.6;">
                            <strong style="font-size: 1.1em; color: #111111;">{name}</strong> 
                            <span style="font-size: 0.95em; font-weight: bold; color: {p_color}; margin-left: 12px;">
                                {profit_rate:+.2f}% ({profit_amount:+,.0f}원){stop_loss_warning}
                            </span>
                            <br>
                            <span style="color: #555555; font-size: 0.85em;">
                                매수일: <span style="background-color: #f1f3f6; padding: 2px 6px; border-radius: 4px; font-family: monospace;">{buy_date}</span> | 
                                매수가: <span style="background-color: #f1f3f6; padding: 2px 6px; border-radius: 4px; font-family: monospace;">{buy_price:,.0f}</span> | 
                                현재가: <span style="background-color: #f1f3f6; padding: 2px 6px; border-radius: 4px; font-family: monospace;">{curr_price:,.0f}</span> | 
                                수량: <span style="background-color: #f1f3f6; padding: 2px 6px; border-radius: 4px; font-family: monospace;">{qty:,.6f}</span>
                            </span>
                        </div>
                        """, unsafe_allow_html=True)
                        
                        if is_latest_date:
                            with c2.popover("개별 매도"):
                                st.write(f"**{name}** 수동 매도")
                                input_price = st.number_input("매도가", value=curr_price, key=f"p_force_{ticker}")
                                input_qty = st.number_input("수량", value=float(qty), min_value=0.000001, format="%.6f", key=f"q_force_{ticker}")

                                if st.button("매도 확정", key=f"btn_force_{ticker}"):
                                    update_holdings(ticker, 'SELL', input_price, selected_date, input_qty, market_type)
                        else:
                            c2.markdown("<div style='color:#999999; font-size:0.85em; margin-top:8px; text-align:right;'>과거일 매매불가</div>", unsafe_allow_html=True)
            
            st.write("") 
            df_rebal = df_display[df_display['매매상태'].isin(['매도필요', '매수추천'])]
            
            display_trade_list(df_rebal[df_rebal['매매상태'] == '매도필요'], "시스템 매도 필요 종목", "매도", "sys_s", selected_date, is_latest_date, market_type, holdings_db)
            display_trade_list(df_rebal[df_rebal['매매상태'] == '매수추천'], "시스템 매수 추천 종목", "매수", "sys_b", selected_date, is_latest_date, market_type, holdings_db)
        
            st.divider()
            # 💡 [매매 조건 안내 사항 표시 구역]
            with st.expander("🔍 백테스트 검증 최적 매매 전략 및 필터링 조건 안내", expanded=True):
                c1, c2 = st.columns(2)
                with c1: 
                    st.markdown("""
                    **[매수 조건 (Entry Rule)]**
                    - **모멘텀 순위:** 상위 30위 이내 (`순위 <= 30`)
                    - **중장기 강세:** `RS(90) > 0`
                    - **단기 수급:** `RS(10) > 0` (단기 탄력성 확보)
                    - **추세 정배열:** 현재가 > 20일 이동평균선 (`종가 > MA20`, MA20 정상 산출 필수)
                    """)
                with c2: 
                    st.markdown("""
                    **[매도 조건 (Exit Rule)]**
                    - **추세 이탈:** 현재가 < 20일 이동평균선 (`종가 < MA20`)
                    - **단기 수급 이탈:** `RS(10) <= 0` 전환 시
                    - **순위 하락:** 모멘텀 순위 30위 밖으로 이탈
                    - **손절 라인:** 보유 종목 손익률 **-5.0% 이탈 시 즉시 손절**
                    """)

    # --- Tab 5 (성과 분석 구역 - 💡 기간 조회 기능 추가) ---
    with tab5:
        st.markdown(f"##### 📊 {market_type} 시장 매매 성과 분석")
        
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

            current_table_name = get_holdings_table(market_type)
            try:
                history_res = supabase.table(current_table_name).select("*").not_.is_("sell_date", "null").execute()
            except Exception as e:
                history_res = type('obj', (object,), {'data': []})

            if not history_res.data:
                st.info("청산된 매매 이력이 존재하지 않습니다.")
            else:
                df_hist_raw = pd.DataFrame(history_res.data)
                df_hist_raw['sell_date_dt'] = pd.to_datetime(df_hist_raw['sell_date'])
                
                # 💡 [요구사항 반영] 성과 분석 기간 조회 필터 추가
                st.markdown("###### 📅 성과 분석 기간 설정")
                min_sell_date = df_hist_raw['sell_date_dt'].min().date()
                max_sell_date = df_hist_raw['sell_date_dt'].max().date()
                
                col_d1, col_d2 = st.columns(2)
                with col_d1:
                    start_date_perf = st.date_input("조회 시작일", value=min_sell_date, key="perf_start_date")
                with col_d2:
                    end_date_perf = st.date_input("조회 종료일", value=max_sell_date, key="perf_end_date")
                
                # 선택된 기간에 따른 데이터 필터링
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

                    if market_type == "US":
                        df_hist['종목명'] = df_hist.apply(lambda r: f"[{r['ticker']}] {r['종목명']}", axis=1)

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
                            'buy_price': '{:,.0f}', 'sell_price': '{:,.0f}', 'quantity': '{:,.6f}',
                            'profit_amount': '{:,.0f}', 'profit_rate': '{:+.2f}%'
                        }),
                        hide_index=True, use_container_width=True
                    )

    # --- 📉 하단 주가 및 모멘텀 순위 시계열 차트 구역 ---
    st.divider()
    
    st.markdown("<div id='chart-section'></div>", unsafe_allow_html=True)
    st.markdown("##### 📉 종목별 최근 주가 및 시장 흐름 통합 추이")
    
    if st.session_state.get('trigger_scroll'):
        scroll_to_chart()
        st.session_state['trigger_scroll'] = False 
    
    df_top100 = df_display.head(100)
    top100_tickers = df_top100['ticker'].tolist()
    
    if 'selected_ticker_from_table' in st.session_state:
        target_ticker = st.session_state['selected_ticker_from_table']
        if target_ticker not in top100_tickers:
            top100_tickers.append(target_ticker)

    ticker_name_map = dict(zip(df_display['ticker'], df_display['종목명']))
    
    default_ticker = None
    if not df_top100.empty:
        default_ticker = df_top100.loc[df_top100['순위'].idxmin(), 'ticker']
    
    if 'selected_ticker_from_table' in st.session_state:
        target_ticker = st.session_state['selected_ticker_from_table']
        if target_ticker in top100_tickers:
            default_ticker = target_ticker
            
    default_index = top100_tickers.index(default_ticker) if default_ticker in top100_tickers else 0
            
    selected_chart_ticker = st.selectbox(
        "분석할 종목을 선택하세요 (위 표에서 종목 행을 직접 클릭해도 자동으로 변경됩니다)", 
        options=top100_tickers, 
        index=default_index,
        format_func=lambda x: f"{ticker_name_map.get(x, x)}"
    )
    
    if selected_chart_ticker:
        chart_res = supabase.table("daily_analysis") \
            .select("price_date, close_price, momentum_rank, ma20") \
            .eq("ticker", selected_chart_ticker) \
            .order("price_date", desc=True) \
            .limit(20).execute()
            
        benchmark_ticker = "^KS11" if market_type == "KR" else "^GSPC"
        index_res = supabase.table("daily_analysis") \
            .select("price_date, close_price") \
            .eq("ticker", benchmark_ticker) \
            .order("price_date", desc=True) \
            .limit(20).execute()
            
        if not chart_res.data:
            st.info("해당 종목의 시계열 차트 데이터가 존재하지 않습니다.")
        else:
            df_chart = pd.DataFrame(chart_res.data)
            df_chart['price_date'] = pd.to_datetime(df_chart['price_date'])
            df_chart = df_chart.sort_values('price_date', ascending=True)
            df_chart['price_date_str'] = df_chart['price_date'].dt.strftime('%m-%d')
            df_chart['close_price'] = pd.to_numeric(df_chart['close_price'], errors='coerce')
            
            df_chart['ma20'] = pd.to_numeric(df_chart['ma20'], errors='coerce')
            df_chart.loc[df_chart['ma20'] == 0, 'ma20'] = None
            
            if index_res.data:
                df_idx_chart = pd.DataFrame(index_res.data).rename(columns={'close_price': 'index_price'})
                df_idx_chart['price_date'] = pd.to_datetime(df_idx_chart['price_date'])
                df_idx_chart['index_price'] = pd.to_numeric(df_idx_chart['index_price'], errors='coerce')
                df_merged = pd.merge(df_chart, df_idx_chart, on='price_date', how='left')
            else:
                df_merged = df_chart
                df_merged['index_price'] = None

            idx_name = "KOSPI" if market_type == "KR" else "S&P 500"
            stock_name = ticker_name_map.get(selected_chart_ticker, selected_chart_ticker)

            base_top = alt.Chart(df_merged).encode(
                x=alt.X('price_date_str:N', title=None, axis=alt.Axis(labelAngle=-45))
            ).properties(height=350)

            line_stock = base_top.mark_line(color='#1f77b4', strokeWidth=2.5).encode(
                y=alt.Y('close_price:Q', title=f'주가', scale=alt.Scale(zero=False)),
                tooltip=[alt.Tooltip('price_date_str:N', title='날짜'), alt.Tooltip('close_price:Q', title='종가', format=',.0f')]
            )

            line_ma20 = base_top.mark_line(color='#ff4b4b', strokeDash=[4, 4]).encode(
                y=alt.Y('ma20:Q', title=None, scale=alt.Scale(zero=False)) 
            )

            line_rank = base_top.mark_line(color='#ff7f0e', point=True).encode(
                y=alt.Y('momentum_rank:Q', title='모멘텀 순위 (1~100)', scale=alt.Scale(domain=[100, 0])),
                tooltip=[alt.Tooltip('momentum_rank:Q', title='모멘텀 순위')]
            )

            chart_price_layer = alt.layer(line_stock, line_ma20)
            chart_top = alt.layer(chart_price_layer, line_rank).resolve_scale(y='independent')

            base_bottom = alt.Chart(df_merged).encode(
                x=alt.X('price_date_str:N', title=None, axis=alt.Axis(labelAngle=-45))
            ).properties(height=150)

            chart_bottom = base_bottom.mark_line(color='#2ca02c', strokeWidth=2).encode(
                y=alt.Y('index_price:Q', title=f'{idx_name} 지수', scale=alt.Scale(zero=False)),
                tooltip=[alt.Tooltip('price_date_str:N', title='날짜'), alt.Tooltip('index_price:Q', title='지수', format=',.2f')]
            )

            st.markdown(f"""
            <div style="text-align: center; margin-bottom: 10px; font-size: 0.9em; color: #555555;">
                <span style="color:#1f77b4; font-weight:bold;">━</span> {stock_name} 주가 | 
                <span style="color:#ff4b4b; font-weight:bold;">---</span> MA20 | 
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
