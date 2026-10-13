import os
import pandas as pd
from supabase import create_client, Client
import streamlit as st

# 1. Supabase 접속 정보 및 클라이언트 초기화
SUPABASE_URL = st.secrets.get("SUPABASE_URL", os.getenv("SUPABASE_URL", ""))
SUPABASE_KEY = st.secrets.get("SUPABASE_KEY", os.getenv("SUPABASE_KEY", ""))

if not SUPABASE_URL or not SUPABASE_KEY:
    st.error("Supabase 접속 정보(URL / Key)가 설정되지 않았습니다.")

supabase: Client = create_client(SUPABASE_URL, SUPABASE_KEY)

def get_available_dates():
    """
    daily_analysis 테이블에서 데이터 조회가 가능한 고유 거래일 목록 반환 (내림차순)
    """
    try:
        res = (
            supabase.table("daily_analysis")
            .select("price_date")
            .order("price_date", desc=True)
            .execute()
        )
        if res.data:
            df_dates = pd.DataFrame(res.data)
            return sorted(df_dates["price_date"].unique().tolist(), reverse=True)
        return []
    except Exception as e:
        st.error(f"거래일 목록 조회 실패: {e}")
        return []

def get_holdings_table(market_type):
    """
    마켓 구분(KR/US)에 따른 데이터베이스 보유 종목 테이블명 반환
    """
    return "us_holdings" if market_type == "US" else "kr_holdings"

def get_market_regime(market_type, target_date_str):
    """
    시장 국면(Regime) 상태 판정
    반환값: (market_safe, stop_new_buy, reduce_holdings)
    """
    try:
        res = (
            supabase.table("market_regimes")
            .select("*")
            .eq("market_type", market_type)
            .lte("regime_date", target_date_str)
            .order("regime_date", desc=True)
            .limit(1)
            .execute()
        )
        if res.data:
            r_data = res.data[0]
            market_safe = r_data.get("is_bull", True)
            stop_new_buy = r_data.get("stop_new_buy", False)
            reduce_holdings = r_data.get("reduce_holdings", False)
            return market_safe, stop_new_buy, reduce_holdings
        return True, False, False
    except Exception:
        return True, False, False

def get_recently_sold_info(market_type, days_limit=5):
    """
    최근 N일 이내에 청산(매도) 완료된 종목들의 티커 및 매도 정보 반환
    strategy.py 모듈에서 참조하는 함수입니다.
    """
    table_name = get_holdings_table(market_type)
    try:
        res = (
            supabase.table(table_name)
            .select("*")
            .not_.is_("sell_date", "null")
            .order("sell_date", desc=True)
            .limit(100)
            .execute()
        )
        if res.data:
            df_sold = pd.DataFrame(res.data)
            return df_sold
        return pd.DataFrame()
    except Exception as e:
        return pd.DataFrame()

def update_holdings(ticker, trade_type, price, trade_date, quantity, market_type, exit_reason=None):
    """
    매수/매도 주문 실행 시 포트폴리오(holdings) DB 업데이트 및 실현 손익 기록
    - 수량(quantity) 정수 변환을 통해 'invalid input syntax for type integer' 에러 방지
    """
    table_name = get_holdings_table(market_type)
    ticker_clean = str(ticker).strip().upper()
    trade_date_str = str(trade_date)

    # 📌 수량 데이터 타입 안전 변환 (한국장 정수 int 캐스팅)
    try:
        if market_type == "KR":
            qty_val = int(float(quantity))
        else:
            qty_val = float(quantity) if float(quantity) % 1 != 0 else int(float(quantity))
    except Exception:
        qty_val = int(float(quantity))

    try:
        if trade_type == "BUY":
            # 신규 보유 종목 레코드 추가
            data = {
                "ticker": ticker_clean,
                "buy_date": trade_date_str,
                "buy_price": float(price),
                "quantity": qty_val,
                "created_at": "now()",
            }
            supabase.table(table_name).insert(data).execute()
            st.success(f"[{ticker_clean}] 매수 등록 완료 (가격: {price:,.2f}, 수량: {qty_val})")

        elif trade_type == "SELL":
            # 기존 미청산 보유 종목 조회
            res = (
                supabase.table(table_name)
                .select("*")
                .eq("ticker", ticker_clean)
                .is_("sell_date", "null")
                .execute()
            )
            if res.data:
                holding_row = res.data[0]
                row_id = holding_row["id"]
                b_price = float(holding_row["buy_price"])
                s_price = float(price)

                # 손익금액 및 수익률 산출
                profit_amt = (s_price - b_price) * float(qty_val)
                profit_rate = ((s_price - b_price) / b_price) * 100.0 if b_price > 0 else 0.0

                update_data = {
                    "sell_date": trade_date_str,
                    "sell_price": float(s_price),
                    "profit_amount": float(profit_amt),
                    "profit_rate": float(profit_rate),
                    "exit_reason": exit_reason or "사용자 매도",
                }
                
                # DB 업데이트 실행
                supabase.table(table_name).update(update_data).eq("id", row_id).execute()
                st.success(f"[{ticker_clean}] 매도 청산 완료 (손익: {profit_amt:+,.2f}, 수익률: {profit_rate:+.2f}%)")
            else:
                st.warning(f"[{ticker_clean}] 매도할 보유 종목 내역을 찾을 수 없습니다.")
        st.rerun()

    except Exception as e:
        st.error(f"매매 내역 업데이트 실패: {e}")
