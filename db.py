import os
import pandas as pd
import streamlit as st
from supabase import create_client, Client

# Supabase 클라이언트 초기화
SUPABASE_URL = st.secrets.get("SUPABASE_URL", os.environ.get("SUPABASE_URL", ""))
SUPABASE_KEY = st.secrets.get("SUPABASE_KEY", os.environ.get("SUPABASE_KEY", ""))

if not SUPABASE_URL or not SUPABASE_KEY:
    st.error("Supabase URL 또는 KEY 설정이 올바르지 않습니다.")

supabase: Client = create_client(SUPABASE_URL, SUPABASE_KEY)


def get_holdings_table(market_type="KR"):
    """
    Supabase DB 스펙 기준 보유 테이블 매핑
    - KR: current_holdings
    - US: current_holdings_us
    """
    if market_type == "US":
        return "current_holdings_us"
    return "current_holdings"


def get_available_dates():
    """
    daily_analysis 테이블에서 데이터가 존재하는 날짜 목록 조회
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
            df = pd.DataFrame(res.data)
            df["price_date"] = pd.to_datetime(df["price_date"]).dt.strftime("%Y-%m-%d")
            return sorted(df["price_date"].unique().tolist(), reverse=True)
        return []
    except Exception as e:
        print(f"날짜 목록 조회 실패: {e}")
        return []


def get_market_regime(market_type="KR", target_date_str=None):
    """
    daily_analysis 테이블의 지수 심볼(^KS11 / ^GSPC) 데이터로 Market Regime 판정
    """
    target_symbol = "^KS11" if market_type == "KR" else "^GSPC"
    try:
        query = supabase.table("daily_analysis").select("close_price, ma20").eq("ticker", target_symbol)
        if target_date_str:
            query = query.lte("price_date", target_date_str)
            
        res = query.order("price_date", desc=True).limit(5).execute()
        if res.data:
            df = pd.DataFrame(res.data)
            if not df.empty:
                latest = df.iloc[0]
                close_p = float(latest.get("close_price", 0.0) or 0.0)
                ma20_p = float(latest.get("ma20", 0.0) or 0.0)
                
                market_safe = close_p >= ma20_p if ma20_p > 0 else True
                return market_safe, False, False
        return True, False, False
    except Exception as e:
        print(f"Market Regime 조회 실패: {e}")
        return True, False, False


def get_recently_sold_info(market_type="KR", target_date_str=None, cooldown_days=3):
    """
    최근 N일 이내 매도 완료된 종목 및 매도가 조회 (재진입 쿨다운 필터용)
    """
    table_name = get_holdings_table(market_type)
    if not target_date_str:
        return {}

    try:
        target_dt = pd.to_datetime(target_date_str)
        min_sell_dt = (target_dt - pd.Timedelta(days=cooldown_days)).strftime("%Y-%m-%d")

        res = (
            supabase.table(table_name)
            .select("ticker, sell_date, sell_price")
            .not_.is_("sell_date", "null")
            .gte("sell_date", min_sell_dt)
            .lte("sell_date", target_date_str)
            .execute()
        )
        
        sold_dict = {}
        if res.data:
            for row in res.data:
                tk = str(row["ticker"]).strip().upper()
                s_price = float(row.get("sell_price", 0.0) or 0.0)
                sold_dict[tk] = s_price
        return sold_dict
    except Exception as e:
        print(f"최근 매도 내역 조회 실패: {e}")
        return {}


def update_holdings(ticker, trade_type, price, trade_date, quantity, market_type="KR", exit_reason=None):
    """
    매수/매도 실행 시 holdings 테이블 기록
    """
    table_name = get_holdings_table(market_type)
    ticker_code = str(ticker).strip().upper()
    trade_date_str = str(trade_date)

    try:
        if trade_type == "BUY":
            data = {
                "ticker": ticker_code,
                "buy_date": trade_date_str,
                "buy_price": float(price),
                "quantity": float(quantity),
                "sell_date": None,
                "sell_price": None,
                "profit_amount": None,
                "profit_rate": None,
                "exit_reason": None,
            }
            supabase.table(table_name).insert(data).execute()
            st.success(f"[{ticker_code}] 매수 기록이 등록되었습니다.")
        elif trade_type == "SELL":
            res = (
                supabase.table(table_name)
                .select("*")
                .eq("ticker", ticker_code)
                .is_("sell_date", "null")
                .execute()
            )
            if res.data:
                target_id = res.data[0]["id"]
                b_price = float(res.data[0]["buy_price"])
                s_price = float(price)
                
                profit_amt = (s_price - b_price) * float(quantity)
                profit_rate = ((s_price / b_price) - 1.0) * 100.0 if b_price > 0 else 0.0

                update_data = {
                    "sell_date": trade_date_str,
                    "sell_price": s_price,
                    "quantity": float(quantity),
                    "profit_amount": profit_amt,
                    "profit_rate": profit_rate,
                    "exit_reason": exit_reason or "사용자 매도 실행",
                }
                supabase.table(table_name).update(update_data).eq("id", target_id).execute()
                st.success(f"[{ticker_code}] 매도 처리가 완료되었습니다.")
            else:
                st.warning(f"[{ticker_code}] 청산할 미결제 보유 내역이 존재하지 않습니다.")
    except Exception as e:
        st.error(f"매매 내역 업데이트 실패: {e}")
