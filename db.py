import streamlit as st
import pandas as pd
from supabase import create_client

@st.cache_resource
def get_supabase():
    return create_client(st.secrets["SUPABASE_URL"], st.secrets["SUPABASE_KEY"])

supabase = get_supabase()

def get_holdings_table(market_type):
    return "current_holdings_us" if market_type == "US" else "current_holdings"

def update_capital_after_sell(market_type, profit_amount):
    col_name = "us_capital" if market_type == "US" else "kr_capital"
    session_key = f"{market_type.lower()}_capital"
    
    try:
        res = supabase.table("strategy_settings").select(col_name).eq("id", 1).execute()
        current_cap = float(res.data[0].get(col_name, 6000000.0 if market_type == "US" else 20000000.0)) if res.data else (6000000.0 if market_type == "US" else 20000000.0)
        new_cap = current_cap + profit_amount
        
        supabase.table("strategy_settings").update({col_name: new_cap}).eq("id", 1).execute()
        st.session_state[session_key] = new_cap
        st.info(f"💡 자금 변동 반영: {current_cap:,.0f} ➔ {new_cap:,.0f} (손익: {profit_amount:+,.0f})")
    except Exception as e:
        st.error(f"❌ DB 자금 업데이트 오류: {e}")

def update_holdings(ticker, action, price, trade_date, quantity, market_type):
    table_name = get_holdings_table(market_type)
    trade_date_str = pd.to_datetime(trade_date).strftime('%Y-%m-%d')
    
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
            profit_amount = 0.0
            
            if res.data:
                holding = res.data[0]
                row_id = holding.get('id')
                buy_price = float(holding.get('buy_price', 0.0) or 0.0)
                db_quantity = float(holding.get('quantity', quantity) or quantity)
                
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
                
            update_capital_after_sell(market_type, profit_amount)
            
        except Exception as e:
            st.error(f"❌ 매도 데이터 업데이트 에러: {str(e)}")
            return
        
    st.rerun()

def get_market_regime(market_type, target_date_str):
    idx_ticker = "^KS11" if market_type == "KR" else "^GSPC"
    res = supabase.table("daily_analysis").select("price_date, close_price, ma20, ma50") \
        .eq("ticker", idx_ticker) \
        .lte("price_date", target_date_str) \
        .order("price_date", desc=True) \
        .limit(10).execute()
        
    df_idx = pd.DataFrame(res.data)
    if df_idx.empty: return True, False
    
    df_idx['close_price'] = pd.to_numeric(df_idx['close_price'], errors='coerce')
    df_idx['ma20'] = pd.to_numeric(df_idx['ma20'], errors='coerce')
    df_idx['ma50'] = pd.to_numeric(df_idx['ma50'], errors='coerce')
    df_idx = df_idx.sort_values('price_date').reset_index(drop=True)
    
    current_row = df_idx.iloc[-1]
    is_bull = current_row['close_price'] >= current_row['ma20']
    
    df_idx['is_below_ma50'] = df_idx['close_price'] < df_idx['ma50']
    df_idx['below_ma50_cnt'] = df_idx['is_below_ma50'].groupby((~df_idx['is_below_ma50']).cumsum()).cumsum()
    stop_new_buy = df_idx.iloc[-1]['below_ma50_cnt'] >= 3
    
    return is_bull, stop_new_buy

def get_available_dates():
    try:
        response = supabase.rpc("get_all_dates").execute()
        if response.data:
            return [pd.to_datetime(item['price_date']).strftime('%Y-%m-%d') for item in response.data]
    except Exception:
        pass
        
    try:
        res = supabase.table("daily_analysis").select("price_date").order("price_date", desc=True).limit(10000).execute()
        if res.data:
            parsed_dates = [pd.to_datetime(item['price_date']).strftime('%Y-%m-%d') for item in res.data if item['price_date']]
            return sorted(list(set(parsed_dates)), reverse=True)
        return []
    except Exception:
        return []

def get_recently_sold_info(market_type, target_date, cooldown_days=3):
    table_name = get_holdings_table(market_type)
    try:
        res = supabase.table(table_name).select("ticker, sell_date, sell_price").neq("sell_date", "null").execute()
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
