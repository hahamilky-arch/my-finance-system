import streamlit as st
import pandas as pd
from supabase import create_client
import altair as alt
import streamlit.components.v1 as components
import time

st.set_page_config(layout="wide")

st.markdown("<div id='top-section'></div>", unsafe_allow_html=True)

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
    </style>
    <a href="#top-section" class="floating-btn-left" title="상단 표로 이동">
        <span>⬆️</span> <span>상단 표로 이동</span>
    </a>
""", unsafe_allow_html=True)

supabase = create_client(st.secrets["SUPABASE_URL"], st.secrets["SUPABASE_KEY"])

def scroll_to_chart():
    js = f"""
    <script>
        setTimeout(function() {{
            const el = window.parent.document.getElementById('chart-section');
            if (el) {{
                el.scrollIntoView({{behavior: 'smooth', block: 'start'}});
            }}
        }}, 100);
    </script>
    """
    components.html(js, height=0)

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
            st.success(f"✅ [{ticker}] 매수 기록 완료!")
        except Exception as e:
            st.error(f"❌ 매수 DB 저장 실패: {str(e)}")
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
                
                profit_amount = (float(price) - buy_price) * db_quantity if buy_price > 0 else 0.0
                profit_rate = ((float(price) / buy_price) - 1) * 100 if buy_price > 0 else 0.0
                
                supabase.table(table_name).update({
                    "sell_date": trade_date_str,
                    "sell_price": float(price),
                    "profit_amount": float(profit_amount),
                    "profit_rate": round(float(profit_rate), 2)
                }).eq("id", row_id).execute()
                st.error(f"🗑️ [{ticker}] 매도 처리 완료!")
            else:
                supabase.table(table_name).insert({
                    "ticker": str(ticker).strip(),
                    "sell_date": trade_date_str,
                    "sell_price": float(price),
                    "quantity": float(quantity)
                }).execute()
                st.error(f"🗑️ [{ticker}] 매도 기록 생성 완료!")
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

def get_data(target_date, all_dates, market_type, top_n_cfg, sl_cfg):
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
    
    # 사이드바 설정 기반 백테스트 최적화 종목 필터링
    df_final['is_no6_opt'] = (df_final['순위'] <= top_n_cfg) & (df_final['RS(90)'] > 0) & (df_final['MA20'] > 0) & (df_final['종가'] > df_final['MA20'])
    
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

    def classify_status(row):
        is_in_holdings = row['ticker'] in my_holdings
        if is_in_holdings:
            if (row['MA20'] > 0 and row['종가'] < row['MA20']) or (row['순위'] > 30):
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
                
                # 매수/매도 사유 출력
                if '매도' in title:
                    reason_desc = "20일 이동평균선 이탈 (`종가 < MA20`) 또는 순위 밀림 발생"
                else:
                    reason_desc = f"모멘텀 상위 {row['순위']}위, RS(90) {row['RS(90)']:.2f} (0 초과) 및 20일선 정배열 충족"

                c1.markdown(f"""
                <div style="line-height: 1.6; margin-top: 4px;">
                    <strong style="font-size: 1.1em; color: #111111;">{row['종목명']}</strong> 
                    <span style="font-size: 0.8em; color: #888888; margin-left: 4px;">({ticker})</span>
                    <br>
                    <span style="font-size: 0.85em; color: #d62728; font-weight: bold;">
                        📌 사유: {reason_desc}
                    </span>
                    <br>
                    <span style="font-size: 0.85em; color: #444444;">
                        MOT: {row['MOT']:.2f} | RS(90): {row['RS(90)']:.2f} | RS(10): {row['RS(10)']:.2f}
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
                        if default_qty <= 0: default_qty = 0.000001

                        input_qty = st.number_input("수량", value=default_qty, min_value=0.0, format="%.6f", key=f"q_{key_prefix}_{ticker}")

                        if st.button("확인", key=f"btn_{key_prefix}_{ticker}"):
                            action_type = 'SELL' if '매도' in title else 'BUY'
                            update_holdings(ticker, action_type, input_price, target_date, input_qty, market_type)
                else:
                    c2.markdown("<div style='color:#999999; font-size:0.85em; margin-top:8px; text-align:right;'>과거일 매매불가</div>", unsafe_allow_html=True)

# UI 실행 파트
st.markdown("##### 📈 Momentum Dashboard v1.8.1")
market_safe = get_market_regime()

# 사이드바 매매 전략 조건 설정 구역
with st.sidebar:
    st.markdown("### ⚙️ 전략 매매 조건 설정")
    market_type = st.radio("Market", ["KR", "US"], horizontal=True)
    all_dates = get_available_dates()
    selected_date = st.date_input("Date", value=pd.to_datetime(all_dates[0]) if all_dates else None)
    
    st.divider()
    st.markdown("#### 🎯 전략 세팅 모드 선택")
    strategy_mode = st.radio("운용 모드 선택", ["자동 감지 모드", "상승장 세팅 (1구간)", "하락장 세팅 (2구간)"], index=0)
    
    # 세팅 모드별 디폴트 파라미터 제어
    if strategy_mode == "상승장 세팅 (1구간)":
        is_bull = True
    elif strategy_mode == "하락장 세팅 (2구간)":
        is_bull = False
    else:
        is_bull = market_safe

    if is_bull:
        st.success("🟢 상승장 모드 (Bull Market)")
        top_n_cfg = st.number_input("편입 종목 수 (Top N)", value=3, min_value=1, max_value=10)
        sl_cfg = st.number_input("손절 임계값 (%)", value=-3.0, step=0.5)
        trig_cfg = st.number_input("트레일링 익절 트리거 (%)", value=20.0, step=1.0)
        stop_cfg = st.number_input("고점 대비 반락 익절폭 (%)", value=-10.0, step=1.0)
    else:
        st.error("🔴 하락장 모드 (Bear Market)")
        top_n_cfg = st.number_input("편입 종목 수 (Top N)", value=1, min_value=1, max_value=5)
        sl_cfg = st.number_input("손절 임계값 (%)", value=-1.0, step=0.1)
        trig_cfg = st.number_input("트레일링 익절 트리거 (%)", value=5.0, step=0.5)
        stop_cfg = st.number_input("고점 대비 반락 익절폭 (%)", value=-3.0, step=0.5)

    if st.button("Refresh"): st.rerun()

is_latest_date = False
if all_dates and selected_date:
    latest_date_str = max(all_dates)
    selected_date_str = selected_date.strftime('%Y-%m-%d')
    if selected_date_str == latest_date_str:
        is_latest_date = True

df_display = get_data(selected_date, all_dates, market_type, top_n_cfg, sl_cfg)

if df_display is not None:
    tab1, tab2, tab3, tab4, tab5 = st.tabs(["Overview", "New Entries", "🎯 Pullback", "🚀 백테스트 최적화", "📊 성과 분석"])
    
    col_order = ['순위', '변동', '매매상태', '종목명', 'MOT', 'RS(90)', 'RS(10)', '종가', '상승금액', 'MA20', 'ticker'] 
    tab_dfs = [df_display.head(100), df_display[df_display['is_new_top30']], df_display[df_display['is_pullback']], df_display[df_display['is_no6_opt']]]

    for i, tab in enumerate([tab1, tab2, tab3]):
        with tab:
            df_target = tab_dfs[i][col_order].copy()
            st.dataframe(
                df_target.style.apply(apply_styles, axis=None).format({
                    'MOT': '{:.2f}', 'RS(90)': '{:.2f}', 'RS(10)': '{:.2f}', '종가': '{:,.0f}', '상승금액': '{:+,.0f}', 'MA20': '{:,.0f}', '변동': '{:+.0f}'
                }, na_rep='-'), 
                hide_index=True, use_container_width=True
            )

    with tab4:
        st.markdown("##### 📋 백테스트 최적화 기반 매매 지시서")
        current_table_name = get_holdings_table(market_type)
        try:
            holdings_res = supabase.table(current_table_name).select("*").is_("sell_date", "null").execute()
            holdings_db = pd.DataFrame(holdings_res.data) if holdings_res.data else pd.DataFrame()
        except Exception as e:
            holdings_db = pd.DataFrame()

        # 보유 종목 현황 및 US 마켓 [티커] 표기 반영
        with st.expander(f"💼 현재 {market_type} 시장 보유 종목 ({len(holdings_db)}개)", expanded=True):
            if not holdings_db.empty:
                df_stocks = pd.DataFrame(supabase.table("stocks").select("ticker, name").execute().data)
                if not df_stocks.empty:
                    df_stocks['ticker'] = df_stocks['ticker'].astype(str).str.strip()
                    holdings_merged = pd.merge(holdings_db, df_stocks, on="ticker", how="left")
                else:
                    holdings_merged = holdings_db
                    holdings_merged['name'] = holdings_merged['ticker']
                
                for _, h_row in holdings_merged.iterrows():
                    ticker = h_row['ticker']
                    raw_name = h_row.get('name', ticker)
                    if pd.isna(raw_name): raw_name = ticker
                    
                    # [요청 1 반영] US 마켓 보유 종목명 앞에 [티커] 표시
                    if market_type == "US":
                        display_name = f"[{ticker}] {raw_name}"
                    else:
                        display_name = f"{raw_name} ({ticker})"
                        
                    buy_price = float(h_row.get('buy_price', 0.0))
                    qty = float(h_row.get('quantity', 1.0))
                    
                    curr_row = df_display[df_display['ticker'] == ticker]
                    curr_price = float(curr_row['종가'].values[0]) if not curr_row.empty else buy_price
                    profit_rate = ((curr_price / buy_price) - 1) * 100 if buy_price > 0 else 0.0
                    
                    # 경고 문구 사유 표시
                    warning_desc = ""
                    if profit_rate <= sl_cfg:
                        warning_desc = f" 🚨 [손절 경고: {sl_cfg}% 이탈 - 매도 권장]"
                    elif profit_rate >= trig_cfg:
                        warning_desc = f" 🎯 [트레일링 스탑: 고점 대비 {stop_cfg}% 반락 시 익절]"

                    st.markdown(f"**{display_name}** | Profit: {profit_rate:+.2f}%{warning_desc}")

        df_rebal = df_display[df_display['매매상태'].isin(['매도필요', '매수추천'])]
        display_trade_list(df_rebal[df_rebal['매매상태'] == '매도필요'], "시스템 매도 필요 종목", "매도", "sys_s", selected_date, is_latest_date, market_type, holdings_db)
        display_trade_list(df_rebal[df_rebal['매매상태'] == '매수추천'], "시스템 매수 추천 종목", "매수", "sys_b", selected_date, is_latest_date, market_type, holdings_db)
