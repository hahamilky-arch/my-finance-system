import os
import pandas as pd
import streamlit as st
from supabase import create_client, Client

# 1. Supabase 클라이언트 초기화
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
    지수 심볼(^KS11 / ^GSPC)의 daily_analysis 최근 3거래일로 Market Regime을 판정하는 단일 함수.
    신호 엔진(strategy.get_data)과 화면(오늘의 행동 카드)이 모두 이 값을 사용한다.

    반환: (market_safe, stop_new_buy, reduce_holdings)
    - market_safe     : 최신 종가 >= MA20 (MA20 데이터가 없으면 True)
    - reduce_holdings : 최신 종가 <  MA20  → 경계(Caution)
    - stop_new_buy    : 최근 3거래일 종가가 모두 MA20 미만 → 하락(Bear), 신규 매수 중지
    """
    target_symbol = "^KS11" if market_type == "KR" else "^GSPC"
    try:
        query = supabase.table("daily_analysis").select("close_price, ma20").eq("ticker", target_symbol)
        if target_date_str:
            query = query.lte("price_date", target_date_str)

        res = query.order("price_date", desc=True).limit(3).execute()
        rows = res.data or []
        if not rows:
            return True, False, False

        def _below(r):
            close_p = float(r.get("close_price", 0.0) or 0.0)
            ma20_p = float(r.get("ma20", 0.0) or 0.0)
            return ma20_p > 0 and close_p < ma20_p

        reduce_holdings = _below(rows[0])
        market_safe = not reduce_holdings
        stop_new_buy = len(rows) >= 3 and all(_below(r) for r in rows[:3])
        return market_safe, stop_new_buy, reduce_holdings
    except Exception as e:
        print(f"Market Regime 조회 실패: {e}")
        return True, False, False


def get_market_breadth(market_type="KR", target_date_str=None, days=10):
    """
    시장 폭(breadth): 해당 시장 전체 종목 중 20/50/200일선 위에 있는 종목 비율(%)을 최근 N거래일 산출.
    반환: DataFrame[date, n, pct20, pct50, pct200] (오래된 날짜 → 최신 순). 실패/데이터 없음이면 빈 DataFrame.
    """
    target_symbol = "^KS11" if market_type == "KR" else "^GSPC"
    try:
        q = supabase.table("daily_analysis").select("price_date").eq("ticker", target_symbol)
        if target_date_str:
            q = q.lte("price_date", target_date_str)
        dates = [r["price_date"] for r in (q.order("price_date", desc=True).limit(days).execute().data or [])]
        rows = []
        for d in dates:
            res = (
                supabase.table("daily_analysis")
                .select("ticker, close_price, ma20, ma50, ma200")
                .eq("price_date", d)
                .eq("market", market_type)
                .limit(5000)
                .execute()
            )
            df = pd.DataFrame(res.data or [])
            if df.empty:
                continue
            df = df[~df["ticker"].astype(str).str.startswith("^")]
            for c in ["close_price", "ma20", "ma50", "ma200"]:
                df[c] = pd.to_numeric(df[c], errors="coerce")

            def _pct(col):
                v = df[df[col] > 0]
                return float((v["close_price"] > v[col]).mean() * 100) if len(v) else None

            rows.append({"date": d, "n": int(len(df)), "pct20": _pct("ma20"), "pct50": _pct("ma50"), "pct200": _pct("ma200")})
        return pd.DataFrame(rows).sort_values("date").reset_index(drop=True) if rows else pd.DataFrame()
    except Exception as e:
        print(f"시장 폭 조회 실패: {e}")
        return pd.DataFrame()


def get_index_recovery_ok(market_type="KR", target_date_str=None, days=2):
    """지수 종가가 최근 N거래일 연속 MA20 위인지 (신규 매수 재개 조건). 데이터가 없으면 True."""
    target_symbol = "^KS11" if market_type == "KR" else "^GSPC"
    try:
        q = supabase.table("daily_analysis").select("close_price, ma20").eq("ticker", target_symbol)
        if target_date_str:
            q = q.lte("price_date", target_date_str)
        rows = q.order("price_date", desc=True).limit(max(1, int(days))).execute().data or []
        if len(rows) < days:
            return True
        return all(float(r.get("ma20") or 0) > 0 and float(r.get("close_price") or 0) >= float(r.get("ma20") or 0) for r in rows)
    except Exception as e:
        print(f"지수 복귀 조건 조회 실패: {e}")
        return True


def get_recently_sold_info(market_type="KR", target_date_str=None, cooldown_days=3):
    """
    최근 N일 이내 매도 완료된 종목 및 매도가 조회 (재진입 쿨다운 필터용)
    strategy.py의 호출 규격 (market_type, target_date_str, cooldown_days)과 완벽 호환
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
    - 수량(quantity) 변환 처리로 DB Integer 타입 에러(22P02) 완전 방지
    """
    table_name = get_holdings_table(market_type)
    ticker_code = str(ticker).strip().upper()
    trade_date_str = str(trade_date)

    # 수량 데이터 타입 안전 변환 (한국장의 경우 정수형 int 변환)
    try:
        if market_type == "KR":
            qty_val = int(float(quantity))
        else:
            qty_val = float(quantity) if float(quantity) % 1 != 0 else int(float(quantity))
    except Exception:
        qty_val = float(quantity)

    try:
        if trade_type == "BUY":
            data = {
                "ticker": ticker_code,
                "buy_date": trade_date_str,
                "buy_price": float(price),
                "quantity": qty_val,
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
                
                profit_amt = (s_price - b_price) * float(qty_val)
                profit_rate = ((s_price / b_price) - 1.0) * 100.0 if b_price > 0 else 0.0

                update_data = {
                    "sell_date": trade_date_str,
                    "sell_price": s_price,
                    "quantity": qty_val,
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
