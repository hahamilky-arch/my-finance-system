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
    시장 종류에 따른 보유/청산 내역 테이블명 반환
    - KR: current_holdings
    - US: us_current_holdings
    """
    if market_type == "US":
        return "us_current_holdings"
    return "current_holdings"


def get_available_dates():
    """
    daily_analysis 테이블에서 데이터가 있는 날짜 목록을 최신순으로 조회
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
    market_regime 테이블에서 지수 추세 및 상승/하락장 판정 조회
    """
    target_symbol = "^KS11" if market_type == "KR" else "^GSPC"
    try:
        query = supabase.table("market_regime").select("*")
        if target_date_str:
            query = query.lte("trade_date", target_date_str)
            
        # ticker 또는 index_name 컬럼 대응
        res = query.order("trade_date", desc=True).limit(10).execute()
        if res.data:
            df = pd.DataFrame(res.data)
            
            # 지수 심볼 매칭
            symbol_col = "ticker" if "ticker" in df.columns else ("index_name" if "index_name" in df.columns else None)
            if symbol_col:
                df = df[df[symbol_col].astype(str).str.upper() == target_symbol]
                
            if not df.empty:
                latest = df.iloc[0]
                # is_safe, stop_buy, reduce_holdings 등의 플래그 확인
                market_safe = bool(latest.get("is_safe", True))
                stop_new_buy = bool(latest.get("stop_new_buy", False))
                reduce_holdings = bool(latest.get("reduce_holdings", False))
                return market_safe, stop_new_buy, reduce_holdings
        return True, False, False
    except Exception as e:
        print(f"Market Regime 조회 실패: {e}")
        return True, False, False


def update_holdings(ticker, trade_type, price, trade_date, quantity, market_type="KR", exit_reason=None):
    """
    매수/매도 발생 시 holdings 테이블 업데이트
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
            # 매도되지 않은 기존 보유 건 찾기
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
