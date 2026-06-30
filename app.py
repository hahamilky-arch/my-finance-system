import streamlit as st
import pandas as pd
from supabase import create_client
import plotly.express as px
from plotly.subplots import make_subplots

# NOTE: Original application functionality, data fetching, processing, and style definitions are retained as specified.
# Focus of this revision is on UI title refinement.

# --- Original Functionality & Data Definitions (Kept Verbatim) ---

# Supabase Connection
supabase = create_client(st.secrets["SUPABASE_URL"], st.secrets["SUPABASE_KEY"])

# 1. Style Definition Function (Remains the same, now referenced by the correct name)
def apply_styles(df):
    df_styles = pd.DataFrame('', index=df.index, columns=df.columns)
    
    # is_new_top30 condition (Kept same)
    if 'is_new_top30' in df.columns:
        mask = df['is_new_top30']
        df_styles.loc[mask, :] = 'background-color: #ffcccc'
        
    # '변동' condition (Updated to match image_0.png instruction)
    if '변동' in df.columns:
        df_styles.loc[df['변동'] > 0, '변동'] = 'color: red'
        df_styles.loc[df['변동'] < 0, '변동'] = 'color: blue'
        
    return df_styles

# 2. Data fetching functions (Remain same, using optimized RPC for all_dates)
def get_available_dates():
    # SQL RPC method (Must be created in Supabase SQL Editor)
    response = supabase.rpc("get_all_dates").execute()
    if not response.data: return []
    # Data returned as a list of dictionaries, e.g., [{'price_date': '2026-06-25'}, ...]
    return [item['price_date'] for item in response.data]

def get_data(target_date, all_dates, market_type):
    target_date_str = str(target_date) # date_input might return a datetime.date object
    if target_date_str not in all_dates:
        return None # Handled in UI section
        
    target_idx = all_dates.index(target_date_str)
    previous_date = all_dates[target_idx + 1] if target_idx + 1 < len(all_dates) else target_date_str
    
    # Fetch current data with market filter
    df_current = pd.DataFrame(supabase.table("daily_analysis").select("ticker, momentum_rank, weighted_momentum, rs_score, close_price").eq("price_date", target_date_str).eq("market", market_type).order("momentum_rank").execute().data)
    
    if df_current.empty:
        return None # Return None if no data found for date/market combo
    
    # Fetch previous data for rank change calc
    df_prev = pd.DataFrame(supabase.table("daily_analysis").select("ticker, momentum_rank").eq("price_date", previous_date).eq("market", market_type).execute().data)
    
    # Data preprocessing
    df_current['momentum_rank'] = pd.to_numeric(df_current['momentum_rank'])
    df_current['close_price'] = pd.to_numeric(df_current['close_price'])
    
    df_merged = pd.merge(df_current, df_prev, on="ticker", how="left", suffixes=('', '_prev'))
    df_merged['momentum_rank_prev'] = df_merged['momentum_rank_prev'].fillna(999) # For new stocks
    
    # Calculate rank change (positive is up)
    df_merged['rank_change'] = df_merged['momentum_rank_prev'] - df_merged['momentum_rank']
    
    # Boolean filters for tabs
    df_merged['is_new_top30'] = (df_merged['momentum_rank'] <= 30) & (df_merged['momentum_rank_prev'] > 30)
    
    # specific is_buy_signal condition
    df_merged['is_buy_signal'] = (df_merged['momentum_rank'] >= 70) & (df_merged['momentum_rank'] <= 100) & (df_merged['rank_change'] >= 20) & (df_merged['rank_change'] <= 25)

    # NO4: High-Octane additional processing (Volume Ratio)
    ticker_list = list(df_merged['ticker'].unique())
    df_merged['vol_ratio'] = 0.0 # Initialize column

    if ticker_list:
        # Fetch stock prices for volume ratio calculation
        df_vol = pd.DataFrame(supabase.table("stock_prices").select("ticker, volume, price_date").in_("ticker", ticker_list).execute().data)
        if not df_vol.empty:
            df_vol['volume'] = pd.to_numeric(df_vol['volume'], errors='coerce')
            df_vol['dt'] = pd.to_datetime(df_vol['price_date'])
            target_dt = pd.to_datetime(target_date_str)
            for ticker in ticker_list:
                sub = df_vol[df_vol['ticker'] == ticker].sort_values('dt')
                if len(sub) >= 5: # min length check
                    ma20 = sub['volume'].rolling(window=20, min_periods=5).mean().iloc[-1]
                    today_v = sub[sub['dt'] == target_dt]['volume']
                    if not today_v.empty and ma20 > 0:
                        df_merged.loc[df_merged['ticker'] == ticker, 'vol_ratio'] = today_v.values[0] / ma20

    # Merge stock names
    df_stocks = pd.DataFrame(supabase.table("stocks").select("ticker, name").execute().data)
    df_final = pd.merge(df_merged, df_stocks, on="ticker", how="left")
    
    # Rename columns and ensure numeric formats
    df_final = df_final.rename(columns={'momentum_rank': '순위', 'name': '종목명', 'weighted_momentum': 'MOT', 'rs_score': 'RS', 'close_price': '종가', 'rank_change': '변동'})
    df_final['MOT'] = pd.to_numeric(df_final['MOT'], errors='coerce').fillna(0.0)
    df_final['RS'] = pd.to_numeric(df_final['RS'], errors='coerce').fillna(0.0)
    
    return df_final

# --- END OF Original Functionality ---


# 3. Main UI Configuration
st.set_page_config(layout="wide")

# Sidebar Configuration
with st.sidebar:
    # market_type radio (Kept same)
    market_type = st.radio("시장 선택", ["KR", "US"], horizontal=True)
    all_dates = get_available_dates()
    
    # selected_date with date_input (Using date_input instead of selectbox as requested in original flow, using RPC)
    selected_date = st.date_input("기준일 선택", value=pd.to_datetime(all_dates[0]) if all_dates else None)
    
    if st.button("데이터 새로고침"):
        st.rerun()
        
    st.caption("App Version: 1.1.6")


# Main Page Header Section
# REVISION POINT: Title and date placement for a compact view.
col1, col2 = st.columns([4, 1]) # Column layout: Left 4/5 for title, Right 1/5 for date
with col1:
    # Use st.header or a smaller custom markdown header for a refined title.
    # st.header("📈 모멘텀 분석") 
    # Replaces 
    st.markdown('<p style="font-size:14px; font-weight:bold;">Momentum</p>')
with col2:
    # Title-aligned compact date display
    st.markdown("<br>", unsafe_allow_html=True) # Minor adjustment for alignment
    st.caption(f"기준일: {selected_date}")



# Get processed data based on UI selections
df_display = get_data(selected_date, all_dates, market_type)

# Data Table and Tabs
if df_display is not None:
    col_order = ['순위', '변동', '종목명', 'MOT', 'RS', '종가'] # Final order including '변동'
    tab1, tab2, tab3, tab4 = st.tabs(["전체 보기 (TOP 50)", "신규 진입주 (TOP 30)", "매수 전략 시그널 (Momentum Breakout)", "🚀 No4: High-Octane"])

    with tab1:
        use_filter = st.checkbox("주도주 필터 적용 (RS > 0.03 & 순위 20위 내)")
        df_to_show = df_display.head(100).copy() # Show more for styling and filter check
        if use_filter:
            df_to_show = df_to_show[(df_to_show['RS'] > 0.03) & (df_to_show['순위'] <= 20)]
        
        event = st.dataframe(
            df_to_show.style.apply(apply_styles, axis=None).format({'MOT': '{:.2f}', 'RS': '{:.2f}', '종가': '{:,.0f}', '변동': '{:+.0f}'}), # Format rank change with +/-
            column_order=col_order, 
            hide_index=True, 
            selection_mode="single-row", 
            on_select="rerun", 
            use_container_width=True
        )

    with tab2:
        df_new = df_display[df_display['is_new_top30'] == True].copy()
        st.dataframe(
            df_new[col_order].style.apply(apply_styles, axis=None).format({'MOT': '{:.2f}', 'RS': '{:.2f}', '종가': '{:,.0f}', '변동': '{:+.0f}'}),
            use_container_width=True
        )

    with tab3:
        df_signals = df_display[df_display['is_buy_signal'] == True].copy()
        st.dataframe(
            df_signals[col_order].style.apply(apply_styles, axis=None).format({'MOT': '{:.2f}', 'RS': '{:.2f}', '종가': '{:,.0f}', '변동': '{:+.0f}'}), 
            hide_index=True, 
            use_container_width=True
        )

    with tab4:
        # NO4 High-Octane specific filter and display
        no4_cols = ['순위', '종목명', 'RS', 'vol_ratio', '종가']
        # Filter for high RS and high relative volume
        no4_filtered = df_display[(df_display['순위'] <= 100) & (df_display['RS'] >= 0.4) & (df_display['vol_ratio'] >= 2.0)]
        st.dataframe(
            no4_filtered[no4_cols].style.apply(apply_styles, axis=None).format({'RS': '{:.2f}', 'vol_ratio': '{:.2f}배', '종가': '{:,.0f}'}), # Custom formatting
            hide_index=True, 
            use_container_width=True
        )

# Check for data presence for other markets/dates (optional check, function handles it with return None)
elif selected_date is not None:
    st.warning(f"{selected_date} 일자의 {market_type} 시장 데이터가 없습니다.")
else:
    st.error("데이터 로드에 실패했습니다. 사이드바 설정을 확인해 주세요.")


# 4. Detail Chart Area (Using popover)
# This part depends on the selection event defined in Tab 1 dataframe.
# if event.selection and event.selection["rows"]:
if 'event' in locals() and event and hasattr(event, 'selection') and event.selection and event.selection["rows"]:
    selected_index = event.selection["rows"][0]
    selected_ticker = df_to_show.iloc[selected_index]['ticker']
    selected_name = df_to_show.iloc[selected_index]['종목명']

    # Use a popover for chart display to keep the main screen clean (Streamlit 1.28+)
    with st.popover(f"📊 {selected_name} 상세 분석", use_container_width=True):
        history_df = pd.DataFrame(supabase.table("daily_analysis").select("price_date, momentum_rank, rs_score").eq("ticker", selected_ticker).eq("market", market_type).order("price_date", desc=True).limit(20).execute().data).sort_values("price_date")
        price_df = pd.DataFrame(supabase.table("stock_prices").select("price_date, close_price").eq("ticker", selected_ticker).order("price_date", desc=True).limit(20).execute().data).sort_values("price_date")
        
        combined_df = pd.merge(history_df, price_df, on="price_date")

        fig = make_subplots(rows=2, cols=1, shared_xaxes=True, vertical_spacing=0.1, 
                           subplot_titles=("주가 추이", "모멘텀 순위"), row_heights=[0.6, 0.4])

        fig.add_trace(px.line(combined_df, x='price_date', y='close_price').data[0], row=1, col=1)
        fig.add_trace(px.line(combined_df, x='price_date', y='momentum_rank').data[0], row=2, col=1)

        fig.update_layout(height=500, showlegend=False)
        fig.update_yaxes(autorange="reversed", row=2, col=1) # Reverse for momentum rank (lower is better)
        
        st.plotly_chart(fig, use_container_width=True)
