import os
import pandas as pd
import streamlit as st
from supabase import Client, create_client

# Supabase 클라이언트 초기화
SUPABASE_URL = os.environ.get("SUPABASE_URL") or st.secrets.get("SUPABASE_URL", "")
SUPABASE_KEY = os.environ.get("SUPABASE_KEY") or st.secrets.get("SUPABASE_KEY", "")

if not SUPABASE_URL or not SUPABASE_KEY:
    st.error("Supabase URL 및 API Key 설정이 올바르지 않습니다.")

supabase: Client = create_client(SUPABASE_URL, SUPABASE_KEY)


def get_holdings_table(market_type="KR"):
    """
    시장 타입(KR/US)에 따른 holdings 테이블명 반환
    """
    return "holdings_us" if market_type == "US" else "holdings"


def get_available_dates():
    """
    daily_analysis 테이블에서 데이터가 존재하는 날짜 목록(내림차순) 조회
    """
    try:
        res = (
            supabase.table("daily_analysis")
            .select("price_date")
            .order("price_date", desc=True)
            .limit(300)
            .execute()
        )
        if res.data:
            dates = sorted(
                list(set([r["price_date"] for r in res.data if r.get("price_date")])),
                reverse=True,
            )
            return dates
        return []
    except Exception as e:
        st.error(f"날짜 목록 조회 중 오류 발생: {e}")
        return []


def get_market_regime(market_type="KR", target_date_str=None):
    """
    시장 국면(Regime) 판정 함수
    - market_safe: 지수가 MA20 위에 위치하는지 여부
    - stop_new_buy: 신규 매수 금지 여부 (지수가 MA20 하회 시 즉시 True)
    - reduce_holdings: 보유 비중 축소 여부
    """
    index_name = "KOSPI" if market_type == "KR" else "SP500"
    try:
        query = (
            supabase.table("market_regime")
            .select("trade_date, index_close, ma20, status")
            .eq("index_name", index_name)
        )
        
        if target_date_str:
            query = query.lte("trade_date", target_date_str)
            
        res = query.order("trade_date", desc=True).limit(5).execute()
        
        if not res.data:
            return True, False, False

        df_reg = pd.DataFrame(res.data)
        latest_row = df_reg.iloc[0]
        
        c_price = float(latest_row.get("index_close", 0))
        ma20_price = float(latest_row.get("ma20", 0))
        
        if ma20_price <= 0:
            return True, False, False

        # 지수와 MA20 비교
        market_safe = c_price >= ma20_price
        
        # 지수 이탈 시 즉시 매수 차단 및 비중 축소
        stop_new_buy = not market_safe
        reduce_holdings = not market_safe

        return market_safe, stop_new_buy, reduce_holdings
    except Exception as e:
        print(f"Market Regime 조회 실패: {e}")
        return True, False, False


def get_recently_sold_info(market_type="KR", target_date_str=None, cooldown_days=3, days=None):
    """
    최근 N일(cooldown_days) 이내에 청산(매도) 완료된 종목 코드 조회
    """
    table_name = get_holdings_table(market_type)
    effective_days = cooldown_days if cooldown_days is not None else (days if days is not None else 3)
    
    try:
        query = (
            supabase.table(table_name)
            .select("ticker, sell_date")
            .not_.is_("sell_date", "null")
        )
        
        if target_date_str:
            query = query.lte("sell_date", str(target_date_str))
            
        res = query.order("sell_date", desc=True).limit(100).execute()
        
        if res.data:
            df_sold = pd.DataFrame(res.data)
            df_sold["sell_date"] = pd.to_datetime(df_sold["sell_date"])
            
            base_date = pd.to_datetime(target_date_str) if target_date_str else pd.Timestamp.now()
            cutoff_date = base_date - pd.Timedelta(days=effective_days)
            
            recent_sold_tickers = df_sold[df_sold["sell_date"] >= cutoff_date]["ticker"].tolist()
            return set(recent_sold_tickers)
        return set()
    except Exception as e:
        print(f"최근 매도 종목 조회 실패: {e}")
        return set()


def update_holdings(
    ticker,
    trade_type,
    price,
    trade_date,
    quantity,
    market_type="KR",
    exit_reason=None,
):
    """
    보유 종목(Holdings) 매수/매도 CRUD 업데이트
    """
    table_name = get_holdings_table(market_type)
    ticker_str = str(ticker).strip().upper()
    
    try:
        if trade_type == "BUY":
            exist_res = (
                supabase.table(table_name)
                .select("*")
                .eq("ticker", ticker_str)
                .is_("sell_date", "null")
                .execute()
            )
            
            if exist_res.data:
                curr_row = exist_res.data[0]
                old_qty = float(curr_row.get("quantity", 0))
                old_price = float(curr_row.get("buy_price", 0))
                
                new_qty = old_qty + float(quantity)
                new_price = ((old_price * old_qty) + (float(price) * float(quantity))) / new_qty if new_qty > 0 else float(price)
                
                supabase.table(table_name).update({
                    "buy_price": new_price,
                    "quantity": new_qty,
                    "highest_price": max(float(curr_row.get("highest_price", 0)), float(price)),
                }).eq("id", curr_row["id"]).execute()
            else:
                supabase.table(table_name).insert({
                    "ticker": ticker_str,
                    "buy_date": str(trade_date),
                    "buy_price": float(price),
                    "quantity": float(quantity),
                    "highest_price": float(price),
                    "created_at": pd.Timestamp.now().isoformat(),
                }).execute()
                
            st.success(f"[{ticker_str}] 매수 등록이 완료되었습니다.")
            st.rerun()

        elif trade_type == "SELL":
            exist_res = (
                supabase.table(table_name)
                .select("*")
                .eq("ticker", ticker_str)
                .is_("sell_date", "null")
                .execute()
            )
            
            if not exist_res.data:
                st.warning(f"[{ticker_str}] 매도할 보유 종목 내역이 존재하지 않습니다.")
                return

            curr_row = exist_res.data[0]
            b_price = float(curr_row.get("buy_price", 0))
            s_price = float(price)
            s_qty = float(quantity)
            
            profit_amt = (s_price - b_price) * s_qty
            profit_rate = ((s_price / b_price) - 1.0) * 100.0 if b_price > 0 else 0.0

            supabase.table(table_name).update({
                "sell_date": str(trade_date),
                "sell_price": s_price,
                "profit_amount": profit_amt,
                "profit_rate": profit_rate,
                "exit_reason": exit_reason or "사용자 수동 청산",
            }).eq("id", curr_row["id"]).execute()

            st.success(f"[{ticker_str}] 청산 처리가 완료되었습니다. (손익: {profit_rate:+.2f}%)")
            st.rerun()

    except Exception as e:
        st.error(f"보유 종목 업데이트 실패: {e}")
