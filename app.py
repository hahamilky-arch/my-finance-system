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
    # 💡 상승금액 컬럼에도 색상 적용
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
    
    # 💡 [핵심 변경] 전일자 데이터를 가져올 때 close_price를 추가로 불러와 상승금액 계산
    res_prev = supabase.table("daily_analysis").select("ticker, momentum_rank, close_price").eq("price_date", prev_date).execute()
    df_prev = pd.DataFrame(res_prev.data).rename(columns={'momentum_rank': '순위_prev', 'close_price': '종가_prev'})
    
    df_final = pd.merge(df_final, df_prev, on="ticker", how='left')
    df_final = df_final.rename(columns={'momentum_rank': '순위', 'weighted_momentum': 'MOT', 'rs_score': 'RS', 'close_price': '종가', 'ma10': 'MA10', 'ma20': 'MA20'})
    
    # 상승금액 산출 로직
    df_final['종가_prev'] = pd.to_numeric(df_final['종가_prev'], errors='coerce')
    df_final['상승금액'] = df_final['종가'] - df_final['종가_prev']
    
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
st.markdown("##### 📈 Momentum Dashboard v1.4.9")
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
    
    # 💡 [핵심 변경] 표의 컬럼 순서에 '상승금액' 추가
    col_order = ['순위', '변동', '종목명', 'MOT', 'RS', '종가', '상승금액', 'MA20', 'ticker'] 
    tab_dfs = [df_display.head(100), df_display[df_display['is_new_top30']], df_display[df_display['is_pullback']], df_display[df_display['is_no6_opt']]]

    clicked_ticker = None
    
    for i, tab in enumerate([tab1, tab2, tab3]):
        with tab:
            df_target = tab_dfs[i][col_order].copy()
            event = st.dataframe(
                # 💡 [핵심 변경] format 사전값에 '상승금액'을 +1,000 형태로 포맷팅 추가
                df_target.style.apply(apply_styles, axis=None).format({
                    'MOT': '{:.2f}', 'RS': '{:.2f}', '종가': '{:,.0f}', '상승금액': '{:+,.0f}', 'MA20': '{:,.0f}', '변동': '{:+.0f}'
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
        st.session_state['selected_ticker_from_table'] = clicked_ticker

    # --- Tab 4(매매 지시서 구역) ---
    with tab4:
        st.markdown("##### 📋 오늘의 매매 지시서")
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
                    
                    c1, c2 = st.columns([4, 1])
                    c1.markdown(f"""
                    <div style="line-height: 1.6;">
                        <strong style="font-size: 1.1em; color: #111111;">{name}</strong> 
                        <span style="font-size: 0.8em; color: #888888; margin-left: 4px;">({ticker})</span>
                        <br>
                        <span style="color: #555555; font-size: 0.85em;">
                            매수일: <span style="background-color: #f1f3f6; padding: 2px 6px; border-radius: 4px; font-family: monospace;">{buy_date}</span> | 
                            매수가: <span style="background-color: #f1f3f6; padding: 2px 6px; border-radius: 4px; font-family: monospace;">{buy_price:,.0f}원</span> | 
                            수량: <span style="background-color: #f1f3f6; padding: 2px 6px; border-radius: 4px; font-family: monospace;">{qty}주</span>
                        </span>
                    </div>
                    """, unsafe_allow_html=True)
                    
                    with c2.popover("개별 매도"):
                        st.write(f"**{name}** 수동 매도")
                        input_price = st.number_input("매도가", value=curr_price, key=f"p_force_{ticker}")
                        input_qty = st.number_input("수량", value=qty, min_value=1, step=1, key=f"q_force_{ticker}")
                        if st.button("매도 확정", key=f"btn_force_{ticker}"):
                            update_holdings(ticker, 'SELL', input_price, selected_date, input_qty)
        
        st.write("") 
        df_rebal = df_display[df_display['매매상태'].isin(['매도필요', '매수추천'])]
        display_trade_list(df_rebal[df_rebal['매매상태'] == '매도필요'], "시스템 매도 필요", "매도", "sys_s", selected_date)
        display_trade_list(df_rebal[df_rebal['매매상태'] == '매수추천'], "시스템 매수 추천", "매수", "sys_b", selected_date)
    
        st.divider()
        with st.expander("🔍 No.6 전략 필터링 조건 보기"):
            c1, c2 = st.columns(2)
            with c1: st.markdown("**[매수 조건]**\n- 순위: 30위 이내\n- RS: 0 초과\n- 추세: 종가 > MA20")
            with c2: st.markdown("**[매도 조건]**\n- 순위: 30위 밖\n- 추세: 종가 < MA20")

    # --- Tab 5(성과 분석 구역) ---
    with tab5:
        st.markdown("##### 📊 단일 테이블 기반 매매 성과 분석")
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
    st.markdown("##### 📉 종목별 최근 주가 및 모멘텀 순위 변동 추이")
    
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
        # 최근 20일(약 1달) 데이터 추출 (ma20 추가)
        chart_res = supabase.table("daily_analysis") \
            .select("price_date, close_price, momentum_rank, ma20") \
            .eq("ticker", selected_chart_ticker) \
            .order("price_date", desc=True) \
            .limit(20).execute()
            
        if not chart_res.data:
            st.info("해당 종목의 시계열 차트 데이터가 존재하지 않습니다.")
        else:
            df_chart = pd.DataFrame(chart_res.data)
            df_chart['price_date'] = pd.to_datetime(df_chart['price_date'])
            df_chart = df_chart.sort_values('price_date', ascending=True)
            df_chart['price_date'] = df_chart['price_date'].dt.strftime('%m-%d')
            
            # 숫자 데이터 안전 변환
            df_chart['close_price'] = pd.to_numeric(df_chart['close_price'], errors='coerce')
            df_chart['ma20'] = pd.to_numeric(df_chart['ma20'], errors='coerce')
            
            c_left, c_right = st.columns(2)
            
            # 왼쪽: 주가 및 MA20 복합 차트
            with c_left:
                st.markdown(f"<p style='text-align:center; font-weight:bold;'>📈 최근 주가 & MA20 ({ticker_name_map.get(selected_chart_ticker, selected_chart_ticker)})</p>", unsafe_allow_html=True)
                
                # 인덱스를 날짜로 설정하고, 종가와 MA20 컬럼만 선택하여 시각화 데이터프레임 구성
                df_price_chart = df_chart[['price_date', 'close_price', 'ma20']].set_index('price_date')
                df_price_chart.columns = ['종가 (Close)', '20일선 (MA20)']
                
                # 색상 분리 (종가: 파란색, MA20: 빨간색)
                st.line_chart(df_price_chart, color=["#1f77b4", "#ff4b4b"], use_container_width=True)
                
            # 오른쪽: 모멘텀 순위 차트
            with c_right:
                st.markdown("<p style='text-align:center; font-weight:bold;'>🏅 모멘텀 순위 (상단일수록 고순위)</p>", unsafe_allow_html=True)
                
                momentum_chart = alt.Chart(df_chart).mark_line(color='#ff7f0e', point=True).encode(
                    x=alt.X('price_date:N', title=None, axis=alt.Axis(labelAngle=-45)),
                    y=alt.Y('momentum_rank:Q', title='순위 (1~100)', scale=alt.Scale(domain=[100, 0])),
                    tooltip=['price_date', 'momentum_rank']
                )
                st.altair_chart(momentum_chart, use_container_width=True)
else:
    st.warning("데이터를 불러오는 중입니다.")
