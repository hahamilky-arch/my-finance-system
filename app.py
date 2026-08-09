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

def calc_buy_qty_atr(ack, qk, atr_v):
    acc = st.session_state.get(ack, 0.0)
    if atr_v > 0:
        st.session_state[qk] = float(int((acc * 0.02) / (2 * atr_v)))

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

def get_recently_sold_info(market_type, target_date, cooldown_days=3):
    table_name = get_holdings_table(market_type)
    try:
        res = supabase.table(table_name).select("ticker, sell_date, sell_price").not_.is_("sell_date", "null").execute()
        if not res.data:
            return {}
        
        df_sold = pd.DataFrame(res.data)
        df_sold['sell_date'] = pd.to_datetime(df_sold['sell_date'])
        
        target_dt = pd.to_datetime(target_date)
        recent_limit = target_dt - pd.Timedelta(days=cooldown_days)
        
        recent_df = df_sold[(df_sold['sell_date'] >= recent_limit) & (df_sold['sell_date'] <= target_dt)]
        
        sold_dict = {}
        for _, r in recent_df.sort_values('sell_date').iterrows():
            sold_dict[str(r['ticker']).strip().upper()] = float(r['sell_price']) if pd.notna(r['sell_price']) else 0.0
            
        return sold_dict
    except Exception:
        return {}

def update_holdings(ticker, action, price, trade_date, quantity, market_type):
    table_name = get_holdings_table(market_type)
    trade_date_str = trade_date.strftime('%Y-%m-%d')
    
    qty_val = float(quantity)
    if qty_val.is_integer():
        qty_val = int(qty_val)
    
    if action == 'BUY':
        try:
            supabase.table(table_name).insert({
                "ticker": str(ticker).strip(),
                "buy_date": trade_date_str,
                "buy_price": float(price),
                "quantity": qty_val
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
                    "quantity": qty_val
                }).execute()
                st.error(f"🗑️ [{ticker}] 매도 기록 생성 완료!")
        except Exception as e:
            st.error(f"❌ 매도 데이터 업데이트 에러: {str(e)}")
            return
        
    st.rerun()

def get_market_regime(market_type):
    idx_ticker = "^KS11" if market_type == "KR" else "^GSPC"
    res = supabase.table("daily_analysis").select("close_price").eq("ticker", idx_ticker).order("price_date", desc=True).limit(20).execute()
    df_idx = pd.DataFrame(res.data)
    if df_idx.empty: return True
    ma20 = df_idx['close_price'].mean()
    current_price = df_idx.iloc[0]['close_price']
    return current_price >= ma20

def get_available_dates():
    response = supabase.rpc("get_all_dates").execute()
    return [item['price_date'] for item in response.data] if response.data else []

def get_data(target_date, all_dates, market_type, top_n_cfg, sl_cfg, rebalance_cycle, stop_cfg, trig_cfg):
    target_date_ts = pd.Timestamp(target_date).normalize()
    target_date_str = target_date_ts.strftime('%Y-%m-%d')
    if target_date_str not in all_dates: return None

    res_curr = supabase.table("daily_analysis") \
        .select("ticker, momentum_rank, weighted_momentum, rs_score, rs_score_10, close_price, ma10, ma20, atr, high_price, low_price, ma200") \
        .eq("price_date", target_date_str) \
        .eq("market", market_type) \
        .execute()
    
    df_final = pd.DataFrame(res_curr.data)
    if df_final.empty: return None
    
    num_cols = ['close_price', 'ma10', 'ma20', 'atr', 'high_price', 'low_price', 'ma200']
    for col in num_cols:
        if col in df_final.columns:
            df_final[col] = pd.to_numeric(df_final[col], errors='coerce').astype('float64')
            
    df_final['ticker'] = df_final['ticker'].astype(str).str.strip()
    
    target_idx = all_dates.index(target_date_str)
    prev_date = all_dates[min(target_idx + 1, len(all_dates)-1)]
    
    res_prev = supabase.table("daily_analysis").select("ticker, momentum_rank, close_price, ma20").eq("price_date", prev_date).execute()
    df_prev = pd.DataFrame(res_prev.data).rename(columns={'momentum_rank': '순위_prev', 'close_price': '종가_prev', 'ma20': 'MA20_prev'})
    
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
    df_final['MA20_prev'] = pd.to_numeric(df_final['MA20_prev'], errors='coerce')
    df_final['상승금액'] = df_final['종가'] - df_final['종가_prev']
    df_final['변동'] = df_final['순위_prev'].fillna(999) - df_final['순위']
    df_final['is_new_top30'] = (df_final['순위'] <= 30) & (df_final['순위_prev'] > 30)
    df_final['is_pullback'] = (df_final['순위'] <= 100) & (df_final['RS(90)'] > 0) & (df_final['변동'] > 0)
    df_final['MA20'] = df_final['MA20'].fillna(0)
    
    # 시장 필터 검증 (KOSPI > MA200)
    idx_ticker = "^KS11" if market_type == "KR" else "^GSPC"
    idx_res = supabase.table("daily_analysis").select("close_price, ma200").eq("ticker", idx_ticker).eq("price_date", target_date_str).execute()
    market_passed = True
    if idx_res.data:
        idx_close = pd.to_numeric(idx_res.data[0].get('close_price', 0), errors='coerce')
        idx_ma200 = pd.to_numeric(idx_res.data[0].get('ma200', 0), errors='coerce')
        if pd.notna(idx_close) and pd.notna(idx_ma200) and idx_ma200 > 0:
            market_passed = idx_close > idx_ma200

    is_wednesday = target_date_ts.day_name() == 'Wednesday'
    cycle_passed = True if rebalance_cycle == "상시 (빈자리 즉시 채우기)" else is_wednesday
    
    df_stocks = pd.DataFrame(supabase.table("stocks").select("ticker, name").execute().data)
    if not df_stocks.empty:
        df_stocks['ticker'] = df_stocks['ticker'].astype(str).str.strip()
    else:
        df_stocks = pd.DataFrame(columns=['ticker', 'name'])

    df_final = pd.merge(df_final, df_stocks, on="ticker", how="left").rename(columns={'name': '종목명'})
    df_final['종목명'] = df_final['종목명'].fillna(df_final['ticker'])

    if market_type == "US":
        df_final['종목명'] = df_final.apply(lambda r: f"[{r['ticker']}] {r['종목명']}", axis=1)

    table_name = get_holdings_table(market_type)
    try:
        h_res = supabase.table(table_name).select("*").is_("sell_date", "null").execute()
        holdings_df = pd.DataFrame(h_res.data) if h_res.data else pd.DataFrame()
    except Exception:
        holdings_df = pd.DataFrame()

    my_holdings = holdings_df['ticker'].tolist() if not holdings_df.empty else []
    my_holdings_clean = [str(t).strip().upper() for t in my_holdings]
    
    peak_metrics = {}
    if not holdings_df.empty:
        for _, r in holdings_df.iterrows():
            tk = r['ticker']
            bd = r['buy_date']
            p_res = supabase.table("daily_analysis").select("high_price").eq("ticker", tk).gte("price_date", bd).lte("price_date", target_date_str).execute()
            if p_res.data:
                highs = [pd.to_numeric(x['high_price'], errors='coerce') for x in p_res.data]
                peak_metrics[str(tk).strip().upper()] = max([h for h in highs if pd.notna(h)] + [0])
            else:
                peak_metrics[str(tk).strip().upper()] = float(r['buy_price'])

    sold_info = get_recently_sold_info(market_type, target_date_str, cooldown_days=3)

    sell_list = set()
    
    # 1. 보유 종목 매도 조건 점검
    for _, row in df_final.iterrows():
        ticker_upper = str(row['ticker']).strip().upper()
        if ticker_upper in my_holdings_clean:
            c_price = row['종가']
            ma20 = row['MA20']
            mom_rank = row['순위']
            
            # 매도 조건 1: MA20 2일 연속 이탈 또는 모멘텀 30위 밖
            today_breach = (ma20 > 0) and (c_price < ma20)
            prev_ma20 = row.get('MA20_prev')
            prev_close = row.get('종가_prev')
            prev_breach = pd.notna(prev_ma20) and prev_ma20 > 0 and pd.notna(prev_close) and prev_close < prev_ma20
            ma20_confirmed_exit = today_breach and prev_breach

            if ma20_confirmed_exit or (mom_rank > 30):
                sell_list.add(ticker_upper)
                continue
                
            h_row = holdings_df[holdings_df['ticker'].astype(str).str.strip().str.upper() == ticker_upper]
            if not h_row.empty:
                buy_price = float(h_row.iloc[0]['buy_price'])
                
                # 매도 조건 2: 고정 손절선 (-6%)
                stop_loss = buy_price * (1 + (sl_cfg / 100.0))
                if c_price <= stop_loss:
                    sell_list.add(ticker_upper)
                    continue
                
                # 매도 조건 3: 트레일링 스탑 (+12% 달성 후 -5% 반락)
                peak = peak_metrics.get(ticker_upper, buy_price)
                if peak >= buy_price * (1 + trig_cfg / 100.0):
                    if c_price <= peak * (1.0 - abs(stop_cfg) / 100.0):
                        sell_list.add(ticker_upper)
                        continue

    # 2. 슬롯 계산
    actual_keep_count = len([t for t in my_holdings_clean if t not in sell_list])
    slots_available = int(top_n_cfg) - actual_keep_count
    
    buy_list = set()
    df_final['is_no6_opt'] = False
    
    # 3. 매수 추천 스크리닝 (백테스트 최적화 적용)
    if cycle_passed and market_passed and slots_available > 0:
        max_disparity = 1.08  # MA20 대비 +8% 이내에서만 매수 (과열 종목 제외)
        
        tech_cond = (
            (df_final['순위'] <= 20) & 
            (df_final['RS(90)'] > 0) & 
            (df_final['RS(10)'] > 0) & 
            (df_final['MA20'] > 0) & 
            (df_final['종가'] > df_final['MA20']) & 
            (df_final['종가'] <= df_final['MA20'] * max_disparity)
        )
        candidates = df_final[tech_cond].sort_values('순위')
        
        for idx, row in candidates.iterrows():
            if len(buy_list) >= slots_available:
                break
                
            ticker_upper = str(row['ticker']).strip().upper()
            
            if ticker_upper in my_holdings_clean:
                continue
                
            # 쿨다운 통과 여부
            if ticker_upper in sold_info:
                last_sell_price = sold_info[ticker_upper]
                if row['종가'] <= last_sell_price:
                    continue 
                    
            buy_list.add(ticker_upper)
            df_final.at[idx, 'is_no6_opt'] = True

    # 4. 상태 적용
    def assign_status(row):
        t_upper = str(row['ticker']).strip().upper()
        if t_upper in sell_list:
            return '매도필요'
        elif t_upper in my_holdings_clean:
            return '보유중'
        elif t_upper in buy_list:
            return '매수추천'
        return ''

    df_final['매매상태'] = df_final.apply(assign_status, axis=1)
    
    return df_final.sort_values('순위')

def display_trade_list(data, title, button_label, key_prefix, target_date, is_latest_date, market_type, holdings_df, top_n_cfg):
    with st.expander(f"🚨 {title} ({len(data)}개)", expanded=True):
        if data.empty:
            st.write(f"해당되는 {button_label} 종목이 없습니다.")
        else:
            for _, row in data.iterrows():
                ticker = row['ticker']
                c1, c2 = st.columns([4, 1])
                
                if '매도' in title:
                    reason_desc = f"MA20 2일 연속 이탈, 순위 30위 밖, 고정 손절 이탈, 또는 트레일링 스탑 충족"
                else:
                    reason_desc = f"Top {top_n_cfg} 편입 (순위<=20), RS>0, MA20 정배열, 이격도 8% 이내"

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
                        
                        p_key = f"p_{key_prefix}_{ticker}"
                        q_key = f"q_{key_prefix}_{ticker}"
                        
                        if button_label == '매수':
                            input_price = st.number_input(f"{button_label}가", value=float(row['종가']), key=p_key)
                            
                            atr_val = row.get('atr', 0)
                            if pd.isna(atr_val): atr_val = 0
                            account_key = f"acc_{key_prefix}_{ticker}"
                            
                            st.number_input("운용 계좌 총액", value=0.0, min_value=0.0, step=1000000.0, key=account_key, on_change=calc_buy_qty_atr, args=(account_key, q_key, atr_val))
                            
                            if q_key not in st.session_state:
                                input_qty = st.number_input("매수 수량", value=1.0, min_value=0.0, format="%.6f", key=q_key)
                            else:
                                input_qty = st.number_input("매수 수량", min_value=0.0, format="%.6f", key=q_key)
                        else:
                            input_price = st.number_input(f"{button_label}가", value=float(row['종가']), key=p_key)
                            
                            default_qty = 1.0
                            if not holdings_df.empty:
                                matched_h = holdings_df[holdings_df['ticker'].astype(str).str.strip().str.upper() == str(ticker).strip().upper()]
                                if not matched_h.empty:
                                    val = matched_h.iloc[0].get('quantity', 1.0)
                                    default_qty = float(val) if pd.notna(val) else 1.0
                            if default_qty <= 0: default_qty = 0.000001
                            
                            input_qty = st.number_input("수량", value=default_qty, min_value=0.0, format="%.6f", key=q_key)

                        if st.button("확인", key=f"btn_{key_prefix}_{ticker}"):
                            action_type = 'SELL' if '매도' in title else 'BUY'
                            update_holdings(ticker, action_type, input_price, target_date, input_qty, market_type)
                else:
                    c2.markdown("<div style='color:#999999; font-size:0.85em; margin-top:8px; text-align:right;'>과거일 매매불가</div>", unsafe_allow_html=True)

# UI 실행 파트
st.markdown("##### 📈 Momentum Dashboard v2.5 (Alpha Optimizer)")

if 'trigger_scroll' not in st.session_state:
    st.session_state['trigger_scroll'] = False

if 'db_settings_loaded' not in st.session_state:
    try:
        res = supabase.table("strategy_settings").select("*").eq("id", 1).execute()
        if res.data:
            db_cfg = res.data[0]
            st.session_state['bull_top_n'] = int(db_cfg.get('bull_top_n', 3))
            st.session_state['bull_sl'] = float(db_cfg.get('bull_sl', -6.0))
            st.session_state['bull_trig'] = float(db_cfg.get('bull_trig', 12.0))
            st.session_state['bull_stop'] = float(db_cfg.get('bull_stop', -5.0))
            
            st.session_state['bear_top_n'] = int(db_cfg.get('bear_top_n', 2)) 
            st.session_state['bear_sl'] = float(db_cfg.get('bear_sl', -6.0))
            st.session_state['bear_trig'] = float(db_cfg.get('bear_trig', 12.0))
            st.session_state['bear_stop'] = float(db_cfg.get('bear_stop', -5.0))
    except Exception as e:
        st.session_state['bull_top_n'], st.session_state['bull_sl'], st.session_state['bull_trig'], st.session_state['bull_stop'] = 3, -6.0, 12.0, -5.0
        st.session_state['bear_top_n'], st.session_state['bear_sl'], st.session_state['bear_trig'], st.session_state['bear_stop'] = 2, -6.0, 12.0, -5.0
        
    st.session_state['db_settings_loaded'] = True

with st.sidebar:
    st.markdown("### ⚙️ 알파 매매전략 설정")
    market_type = st.radio("Market", ["KR", "US"], horizontal=True)
    all_dates = get_available_dates()
    selected_date = st.date_input("Date", value=pd.to_datetime(all_dates[0]) if all_dates else None)
    
    market_safe = get_market_regime(market_type)
    
    st.divider()
    st.markdown("#### 🎯 전략 세팅 모드 선택")
    strategy_mode = st.radio("운용 모드 선택", ["자동 감지 모드", "상승장 세팅 (1구간)", "하락장 세팅 (2구간)"], index=0)
    
    if strategy_mode == "상승장 세팅 (1구간)":
        is_bull = True
    elif strategy_mode == "하락장 세팅 (2구간)":
        is_bull = False
    else:
        is_bull = market_safe

    rebalance_cycle = st.selectbox("리밸런싱 주기", ["상시 (빈자리 즉시 채우기)", "주기 (매주 수요일)"], index=0)

    if is_bull:
        st.success("🟢 상승장 모드 (Bull Market)")
        top_n_cfg = st.number_input("편입 종목 수 (Top N)", value=st.session_state.get('bull_top_n', 3), min_value=1, max_value=10)
        sl_cfg = st.number_input("손절 임계값 (%)", value=st.session_state.get('bull_sl', -6.0), step=0.5)
        trig_cfg = st.number_input("트레일링 익절 트리거 (%)", value=st.session_state.get('bull_trig', 12.0), step=1.0)
        stop_cfg = st.number_input("고점 대비 반락 익절폭 (%)", value=st.session_state.get('bull_stop', -5.0), step=1.0)
    else:
        st.error("🔴 하락장 모드 (Bear Market)")
        top_n_cfg = st.number_input("편입 종목 수 (Top N)", value=st.session_state.get('bear_top_n', 2), min_value=0, max_value=5)
        sl_cfg = st.number_input("손절 임계값 (%)", value=st.session_state.get('bear_sl', -6.0), step=0.5)
        trig_cfg = st.number_input("트레일링 익절 트리거 (%)", value=st.session_state.get('bear_trig', 12.0), step=0.5)
        stop_cfg = st.number_input("고점 대비 반락 익절폭 (%)", value=st.session_state.get('bear_stop', -5.0), step=0.5)

    st.divider()
    
    with st.expander("💾 설정값 DB 저장 / 초기화", expanded=False):
        config_pwd = st.text_input("매매 비밀번호 입력", type="password", key="pwd_config")
        
        col_btn1, col_btn2 = st.columns(2)
        with col_btn1:
            if st.button("설정 저장", use_container_width=True):
                if config_pwd == st.secrets.get("TRADE_PASSWORD", "1234"):
                    if is_bull:
                        st.session_state['bull_top_n'] = top_n_cfg
                        st.session_state['bull_sl'] = sl_cfg
                        st.session_state['bull_trig'] = trig_cfg
                        st.session_state['bull_stop'] = stop_cfg
                    else:
                        st.session_state['bear_top_n'] = top_n_cfg
                        st.session_state['bear_sl'] = sl_cfg
                        st.session_state['bear_trig'] = trig_cfg
                        st.session_state['bear_stop'] = stop_cfg
                    
                    settings_data = {
                        "id": 1,
                        "bull_top_n": int(st.session_state.get('bull_top_n', 3)),
                        "bull_sl": float(st.session_state.get('bull_sl', -6.0)),
                        "bull_trig": float(st.session_state.get('bull_trig', 12.0)),
                        "bull_stop": float(st.session_state.get('bull_stop', -5.0)),
                        "bear_top_n": int(st.session_state.get('bear_top_n', 2)),
                        "bear_sl": float(st.session_state.get('bear_sl', -6.0)),
                        "bear_trig": float(st.session_state.get('bear_trig', 12.0)),
                        "bear_stop": float(st.session_state.get('bear_stop', -5.0))
                    }
                    
                    try:
                        supabase.table("strategy_settings").upsert(settings_data).execute()
                        st.success("✅ 현재 설정값이 Supabase DB에 저장되었습니다.")
                    except Exception as e:
                        st.error(f"❌ DB 저장 실패: {e}")
                else:
                    st.error("❌ 비밀번호 불일치")
                    
        with col_btn2:
            if st.button("🔄 기본값 초기화", use_container_width=True):
                if config_pwd == st.secrets.get("TRADE_PASSWORD", "1234"):
                    # 백테스트 기반 최적 기본값 세팅
                    default_settings = {
                        "id": 1,
                        "bull_top_n": 3,
                        "bull_sl": -6.0,
                        "bull_trig": 12.0,
                        "bull_stop": -5.0,
                        "bear_top_n": 2,
                        "bear_sl": -6.0,
                        "bear_trig": 12.0,
                        "bear_stop": -5.0
                    }
                    try:
                        supabase.table("strategy_settings").upsert(default_settings).execute()
                        
                        st.session_state['bull_top_n'] = 3
                        st.session_state['bull_sl'] = -6.0
                        st.session_state['bull_trig'] = 12.0
                        st.session_state['bull_stop'] = -5.0
                        
                        st.session_state['bear_top_n'] = 2
                        st.session_state['bear_sl'] = -6.0
                        st.session_state['bear_trig'] = 12.0
                        st.session_state['bear_stop'] = -5.0
                        
                        st.success("✅ 전략 설정이 기본값으로 초기화되었습니다.")
                        st.rerun()
                    except Exception as e:
                        st.error(f"❌ 초기화 중 오류 발생: {e}")
                else:
                    st.error("❌ 비밀번호 불일치")

    if st.button("Refresh", use_container_width=True): 
        st.rerun()

is_latest_date = False
if all_dates and selected_date:
    latest_date_str = max(all_dates)
    selected_date_str = selected_date.strftime('%Y-%m-%d')
    if selected_date_str == latest_date_str:
        is_latest_date = True

df_display = get_data(selected_date, all_dates, market_type, top_n_cfg, sl_cfg, rebalance_cycle, stop_cfg, trig_cfg)

if df_display is not None:
    tab1, tab2, tab3, tab4, tab5 = st.tabs(["Overview", "New Entries", "🎯 Pullback", "🚀 알파 시그널", "📊 성과 분석"])
    
    col_order = ['순위', '변동', '매매상태', '종목명', 'MOT', 'RS(90)', 'RS(10)', 'MA20', '종가', '상승금액', 'ticker'] 
    tab_dfs = [df_display.head(100), df_display[df_display['is_new_top30']], df_display[df_display['is_pullback']], df_display[df_display['is_no6_opt']]]

    for i, tab in enumerate([tab1, tab2, tab3]):
        with tab:
            df_target = tab_dfs[i][col_order].copy()
            event = st.dataframe(
                df_target.style.apply(apply_styles, axis=None).format({
                    'MOT': '{:.2f}', 'RS(90)': '{:.2f}', 'RS(10)': '{:.2f}', '종가': '{:,.0f}', '상승금액': '{:+,.0f}', 'MA20': '{:,.0f}', '변동': '{:+.0f}'
                }, na_rep='-'), 
                hide_index=True, use_container_width=True,
                on_select="rerun",
                selection_mode="single-row",
                key=f"df_tab_{i}"
            )
            
            if event and "rows" in event.get("selection", {}) and event["selection"]["rows"]:
                selected_row_idx = event["selection"]["rows"][0]
                clicked_ticker = df_target.iloc[selected_row_idx]['ticker']
                st.session_state['selected_ticker_from_table'] = clicked_ticker
                st.session_state['trigger_scroll'] = True

    # --- 4번 탭: 알파 시그널 구역 ---
    with tab4:
        st.markdown("##### 📋 알파 시스템 매매 지시서")
        
        if not st.session_state.get('trade_authenticated', False):
            st.info("🔒 실제 매매 신호 및 보유 종목 확인을 위해 비밀번호를 입력해 주십시오.")
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
                        
                        if market_type == "US":
                            display_name = f"[{ticker}] {raw_name}"
                        else:
                            display_name = f"{raw_name} ({ticker})"
                            
                        buy_price = float(h_row.get('buy_price', 0.0))
                        buy_date = h_row.get('buy_date')
                        
                        curr_row = df_display[df_display['ticker'].astype(str).str.strip().str.upper() == str(ticker).strip().upper()]
                        curr_price = float(curr_row['종가'].values[0]) if not curr_row.empty else buy_price
                        
                        p_res = supabase.table("daily_analysis").select("high_price").eq("ticker", ticker).gte("price_date", buy_date).lte("price_date", selected_date_str).execute()
                        peak = buy_price
                        if p_res.data:
                            highs = [pd.to_numeric(x['high_price'], errors='coerce') for x in p_res.data]
                            peak = max([h for h in highs if pd.notna(h)] + [buy_price])
                        
                        profit_rate = ((curr_price / buy_price) - 1) * 100 if buy_price > 0 else 0.0
                        stop_loss = buy_price * (1 + (sl_cfg / 100.0))
                        warning_desc = ""
                        
                        if curr_price <= stop_loss:
                            warning_desc = f" 🚨 <span style='color:red;'>[손절가({stop_loss:,.0f}) 이탈 권고]</span>"
                        elif peak >= buy_price * (1 + trig_cfg/100.0) and curr_price <= peak * (1.0 - abs(stop_cfg)/100.0):
                            warning_desc = f" 🎯 <span style='color:#1f77b4;'>[트레일링 익절 도달]</span>"
                        elif peak >= buy_price * (1 + trig_cfg/100.0):
                            warning_desc = f" ✨ <span style='color:#2ca02c;'>[트레일링 활성화 (최고점: {peak:,.0f})]</span>"

                        st.markdown(f"**{display_name}** | 수익률: {profit_rate:+.2f}% | 현재가: {curr_price:,.0f}{warning_desc}", unsafe_allow_html=True)

            df_rebal = df_display[df_display['매매상태'].isin(['매도필요', '매수추천'])]
            display_trade_list(df_rebal[df_rebal['매매상태'] == '매도필요'], "시스템 매도 필요 종목", "매도", "sys_s", selected_date, is_latest_date, market_type, holdings_db, top_n_cfg)
            display_trade_list(df_rebal[df_rebal['매매상태'] == '매수추천'], "시스템 매수 추천 종목", "매수", "sys_b", selected_date, is_latest_date, market_type, holdings_db, top_n_cfg)

            # --- 수동 매수 기능 섹션 ---
            st.markdown("---")
            st.markdown("###### ➕ 수동 종목 편입 (Manual Buy)")
            with st.expander("시스템 추천 외 종목 수동 매수", expanded=False):
                col_m1, col_m2, col_m3, col_m4 = st.columns(4)
                with col_m1:
                    m_ticker = st.text_input("종목코드 (Ticker)", key="m_ticker").strip().upper()
                with col_m2:
                    m_price = st.number_input("매수가", min_value=0.0, value=0.0, step=100.0, key="m_price")
                with col_m3:
                    m_qty = st.number_input("매수 수량", min_value=0.0, value=1.0, step=1.0, format="%.6f", key="m_qty")
                with col_m4:
                    m_date = st.date_input("매수일", value=selected_date, key="m_date")
                
                if st.button("수동 매수 실행", use_container_width=True, type="primary"):
                    if m_ticker and m_price > 0 and m_qty > 0:
                        update_holdings(m_ticker, 'BUY', m_price, m_date, m_qty, market_type)
                    else:
                        st.warning("종목코드, 매수가, 매수 수량을 올바르게 입력해주세요.")

        st.info(f"""
        📌 **알파 매매 전략 시스템 가이드 (백테스트 최적화 적용)**
        * **시장 필터**: 지수 종가 > 200일선 유지 시에만 신규 매수 스크리닝 허용
        * **리밸런싱 주기**: `{rebalance_cycle}`
        * **매수 조건**: 모멘텀 순위 **20위 이하**, RS(90) > 0, RS(10) > 0, 종가 > MA20, **20일선 이격도 8% 이내**
        * **보유 종목 수**: 조건 충족 상위 **{top_n_cfg}개** (하락장 세팅 시 2개 매수)
        * **포지션 사이징**: 종목당 자산의 균등 비중 배분 (Top {top_n_cfg} 집중 투자)
        * **매도 조건** (하나라도 충족 시 익일 매도):
            1. 종가 < MA20 하향 이탈이 **2거래일 연속** 확인되거나, 순위 30위 밖 이탈
            2. 고정 손절선 이탈 (`{sl_cfg}%`)
            3. 트레일링 스탑: `{trig_cfg}%` 수익 도달 후, 최고점 대비 `{stop_cfg}%` 반락 시
        * **쿨다운 룰**: 매도 후 3거래일 신규 편입 금지 (단, 종가가 직전 매도가를 재돌파하면 쿨다운 해제)
        """)

    # --- 5번 탭: 성과 분석 구역 ---
    with tab5:
        st.markdown(f"##### 📊 {market_type} 시장 매매 성과 분석")
        
        if not st.session_state.get('trade_authenticated', False):
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

                    if market_type == "US":
                        df_hist['종목명'] = df_hist.apply(lambda r: f"[{r['ticker']}] {r['종목명']}", axis=1)

                    df_hist['profit_amount'] = pd.to_numeric(df_hist['profit_amount'], errors='coerce').fillna(0.0)
                    df_hist['profit_rate'] = pd.to_numeric(df_hist['profit_rate'], errors='coerce').fillna(0.0)
                    
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
                    
                    profit_factor = (avg_win_amt / avg_loss_amt) if avg_loss_amt > 0 else (999.0 if avg_win_amt > 0 else 0.0)
                    
                    if market_type == "US":
                        profit_fmt = lambda x: f"${x:,.2f}"
                        price_fmt = "{:,.2f}"
                        zero_str = "$0.00"
                    else:
                        profit_fmt = lambda x: f"{x:,.0f} 원"
                        price_fmt = "{:,.0f}"
                        zero_str = "0 원"
                    
                    m1, m2, m3, m4 = st.columns(4)
                    m1.metric("총 실현 손익", profit_fmt(total_profit))
                    m2.metric("총 매매 건수", f"{total_trades} 건 (성공 {win_trades} / 실패 {loss_trades})")
                    m3.metric("성공률 / 실패율", f"{win_rate:.1f}% / {loss_rate:.1f}%")
                    m4.metric("손익비 (Profit Factor)", f"{profit_factor:.2f}" if profit_factor < 999 else "무제한")
                    
                    m5, m6, m7, m8 = st.columns(4)
                    m5.metric("평균 익절 금액", profit_fmt(avg_win_amt))
                    m6.metric("평균 손절 금액", profit_fmt(avg_loss_amt))
                    m7.metric("평균 수익률", f"{df_hist['profit_rate'].mean():+.2f} %")
                    m8.metric("최대 단일 수익금", profit_fmt(df_hist['profit_amount'].max()) if total_trades > 0 else zero_str)
                    
                    st.write("")
                    st.markdown("###### 📅 월별 성과 종합")
                    df_hist['sell_month'] = pd.to_datetime(df_hist['sell_date']).dt.strftime('%Y-%m')
                    df_monthly = df_hist.groupby('sell_month').agg(
                        월간손익=('profit_amount', 'sum'),
                        매매건수=('id', 'count'),
                        평균수익률=('profit_rate', 'mean')
                    ).reset_index().sort_values('sell_month', ascending=False)
                    
                    st.dataframe(
                        df_monthly.style.format({'월간손익': profit_fmt, '평균수익률': '{:+.2f}%'}),
                        hide_index=True, use_container_width=True
                    )
                    
                    st.write("")
                    st.markdown("###### 📜 상세 매매 완료 내역")
                    display_hist_cols = ['sell_date', 'ticker', '종목명', 'buy_date', 'buy_price', 'sell_price', 'quantity', 'profit_amount', 'profit_rate']
                    df_hist_sorted = df_hist.sort_values('sell_date', ascending=False)
                    
                    st.dataframe(
                        df_hist_sorted[display_hist_cols].style.format({
                            'buy_price': price_fmt, 'sell_price': price_fmt, 'quantity': '{:,.6f}',
                            'profit_amount': profit_fmt, 'profit_rate': '{:+.2f}%'
                        }),
                        hide_index=True, use_container_width=True
                    )

    # --- 📉 시계열 차트 구역 ---
    st.divider()
    st.markdown("<div id='chart-section'></div>", unsafe_allow_html=True)
    st.markdown("##### 📉 종목별 최근 주가 및 시장 흐름 통합 추이")
    
    if st.session_state.get('trigger_scroll'):
        scroll_to_chart()
        st.session_state['trigger_scroll'] = False 
    
    df_top100 = df_display.head(100)
    top100_tickers = df_top100['ticker'].tolist() if not df_top100.empty else []
    
    if 'selected_ticker_from_table' in st.session_state:
        target_ticker = st.session_state['selected_ticker_from_table']
        if target_ticker not in top100_tickers:
            top100_tickers.append(target_ticker)

    ticker_name_map = dict(zip(df_display['ticker'], df_display['종목명']))
    
    default_ticker = top100_tickers[0] if top100_tickers else None
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
                y=alt.Y('close_price:Q', title='주가', scale=alt.Scale(zero=False)),
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
