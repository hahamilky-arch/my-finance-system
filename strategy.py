import pandas as pd
from db import supabase, get_holdings_table, get_recently_sold_info

def get_data(target_date, all_dates, market_type, top_n_cfg, sl_cfg, rebalance_cycle, is_bull_mode, stop_new_buy):
    target_date_str = pd.to_datetime(target_date).strftime('%Y-%m-%d')
    res_curr = supabase.table("daily_analysis") \
        .select("ticker, momentum_rank, weighted_momentum, rs_score, rs_score_10, close_price, ma10, ma20, atr, high_price, low_price, ma200") \
        .eq("price_date", target_date_str).eq("market", market_type).limit(5000).execute()
    
    df_final = pd.DataFrame(res_curr.data)
    if df_final.empty: return None
    
    num_cols = ['close_price', 'ma10', 'ma20', 'atr', 'high_price', 'low_price', 'ma200']
    for col in num_cols:
        if col in df_final.columns:
            df_final[col] = pd.to_numeric(df_final[col], errors='coerce').astype('float64')
            
    df_final['ticker'] = df_final['ticker'].astype(str).str.strip().str.upper()
    
    prev_date_res = supabase.table("daily_analysis").select("price_date") \
        .eq("market", market_type).lt("price_date", target_date_str).order("price_date", desc=True).limit(1).execute()
        
    df_prev = pd.DataFrame()
    if prev_date_res.data:
        res_prev = supabase.table("daily_analysis").select("ticker, momentum_rank, close_price, ma20") \
            .eq("price_date", prev_date_res.data[0]['price_date']).eq("market", market_type).limit(5000).execute()
        if res_prev.data: df_prev = pd.DataFrame(res_prev.data)

    if not df_prev.empty:
        df_prev = df_prev.rename(columns={'momentum_rank': '순위_prev', 'close_price': '종가_prev', 'ma20': 'MA20_prev'})
        df_prev['ticker'] = df_prev['ticker'].astype(str).str.strip().str.upper()
        df_final = pd.merge(df_final, df_prev[['ticker', '순위_prev', '종가_prev', 'MA20_prev']], on="ticker", how='left')
    else:
        df_final['순위_prev'] = df_final['종가_prev'] = df_final['MA20_prev'] = None

    df_final = df_final.rename(columns={'momentum_rank': '순위', 'weighted_momentum': 'MOT', 'rs_score': 'RS(90)', 'rs_score_10': 'RS(10)', 'close_price': '종가'})
    df_final[['순위_prev', '종가_prev', 'MA20_prev']] = df_final[['순위_prev', '종가_prev', 'MA20_prev']].apply(pd.to_numeric, errors='coerce')
    
    df_final['상승금액'] = df_final.apply(lambda r: r['종가'] - r['종가_prev'] if pd.notna(r['종가_prev']) else 0.0, axis=1)
    df_final['상승률'] = df_final.apply(lambda r: (r['상승금액'] / r['종가_prev'] * 100) if pd.notna(r['종가_prev']) and r['종가_prev'] > 0 else 0.0, axis=1)
    df_final['변동'] = df_final.apply(lambda r: int(r['순위_prev'] - r['순위']) if (pd.notna(r['순위_prev']) and pd.notna(r['순위'])) else 0.0, axis=1)
    df_final['이격도'] = df_final.apply(lambda r: ((r['종가'] / r['ma20']) - 1) * 100 if (r['순위'] <= 50 and pd.notna(r['ma20']) and r['ma20'] > 0) else 0.0, axis=1)
    df_final['ma20'] = df_final['ma20'].fillna(0)
    df_final = df_final.rename(columns={'ma20': 'MA20', 'ma10': 'MA10'})

    cycle_passed = True if rebalance_cycle == "상시 (빈자리 즉시 채우기)" else pd.Timestamp(target_date).day_name() == 'Wednesday'
    
    df_stocks = pd.DataFrame(supabase.table("stocks").select("ticker, name").execute().data)
    if not df_stocks.empty: df_stocks['ticker'] = df_stocks['ticker'].astype(str).str.strip().str.upper()
    
    df_final = pd.merge(df_final, df_stocks, on="ticker", how="left").rename(columns={'name': '종목명'})
    df_final['종목명'] = df_final['종목명'].fillna(df_final['ticker'])
    if market_type == "US": df_final['종목명'] = df_final.apply(lambda r: f"[{r['ticker']}] {r['종목명']}", axis=1)

    table_name = get_holdings_table(market_type)
    try:
        h_res = supabase.table(table_name).select("*").is_("sell_date", "null").execute()
        holdings_df = pd.DataFrame(h_res.data) if h_res.data else pd.DataFrame()
    except Exception: holdings_df = pd.DataFrame()

    my_holdings_clean = [str(t).strip().upper() for t in (holdings_df['ticker'].tolist() if not holdings_df.empty else [])]
    sold_info = get_recently_sold_info(market_type, target_date_str, cooldown_days=3)
    sell_list = set()
    rank_exit_limit = 60 if is_bull_mode else 30
    
    for _, row in df_final.iterrows():
        ticker_upper = str(row['ticker']).strip().upper()
        if ticker_upper in my_holdings_clean:
            c_price, ma20, mom_rank = row['종가'], row['MA20'], row['순위']
            if (c_price < ma20) or (mom_rank > rank_exit_limit):
                sell_list.add(ticker_upper)
                continue
            h_row = holdings_df[holdings_df['ticker'].astype(str).str.strip().str.upper() == ticker_upper]
            if not h_row.empty:
                if c_price <= float(h_row.iloc[0]['buy_price']) * (1 + (sl_cfg / 100.0)):
                    sell_list.add(ticker_upper)

    slots_available = int(top_n_cfg) - len([t for t in my_holdings_clean if t not in sell_list])
    buy_list = set()
    
    if cycle_passed and (not stop_new_buy) and slots_available > 0:
        tech_cond = ((df_final['순위'] <= 30) & (df_final['RS(90)'] > 0) & (df_final['MA20'] > 0) & (df_final['종가'] > df_final['MA20'])) if is_bull_mode else \
                    ((df_final['순위'] <= 50) & (df_final['RS(90)'] >= 0.5) & (df_final['RS(90)'] <= 1.5) & (df_final['이격도'] >= -5.0) & (df_final['이격도'] <= 5.0))
        candidates = df_final[tech_cond].sort_values(by='순위' if is_bull_mode else ['disp_abs', '순위']) if is_bull_mode else df_final[tech_cond].assign(disp_abs=lambda x: x['이격도'].abs()).sort_values(by=['disp_abs', '순위'])
        
        for idx, row in candidates.iterrows():
            if len(buy_list) >= slots_available: break
            ticker_upper = str(row['ticker']).strip().upper()
            if ticker_upper in my_holdings_clean or (ticker_upper in sold_info and row['종가'] <= sold_info[ticker_upper]): continue
            buy_list.add(ticker_upper)

    def assign_status_and_reason(row):
        t = str(row['ticker']).strip().upper()
        if t in sell_list: return '매도필요', '추세이탈/손절조건'
        if t in my_holdings_clean: return '보유중', '기보유'
        if t in buy_list: return '매수추천', '조건충족'
        
        reasons = []
        if stop_new_buy: reasons.append("시장경보(MA50하회)")
        if not cycle_passed: reasons.append("리밸런싱일 미해당")
        if slots_available <= 0: reasons.append("보유슬롯 가득참")
        if is_bull_mode:
            if row['순위'] > 30: reasons.append("순위30위초과")
            if row['RS(90)'] <= 0: reasons.append("RS(90)<=0")
            if row['MA20'] <= 0 or row['종가'] <= row['MA20']: reasons.append("MA20하회")
        else: 
            if row['순위'] > 50: reasons.append("순위50위초과")
            if not (0.5 <= row['RS(90)'] <= 1.5): reasons.append(f"RS범위초과({row['RS(90)']:.2f})")
            if not (-5.0 <= row['이격도'] <= 5.0): reasons.append(f"이격도초과({row['이격도']:+.1f}%)")
        if t in sold_info and row['종가'] <= sold_info[t]: reasons.append("최근매도 쿨다운")
        return '', ", ".join(reasons) if reasons else "선순위밀림"

    status_reason = df_final.apply(assign_status_and_reason, axis=1)
    df_final['매매상태'] = [x[0] for x in status_reason]
    df_final['제외사유'] = [x[1] for x in status_reason]
    return df_final.sort_values('순위')
