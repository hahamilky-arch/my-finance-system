"""Quant Alpha 전략 백테스트 (strategy.py 의 전략 3: Top 7 Regime 과 같은 규칙).

실행 예:
    python backtest.py --market KR --start 2026-01-01 --end 2026-09-30
    python backtest.py --market KR --compare            # 기본 전략 vs 보완 옵션 비교표
    python backtest.py --market US --staged --recov --save_db

특징
- 지수 레짐(MA20 3일 연속 이탈 = 약세 전량 청산)·재진입 쿨다운 3일·ATR 2.5배 손절·+8% 트레일링·MA20 이탈 청산을 라이브와 동일하게 적용
- 순위 밖으로 밀린 보유 종목도 전체 종목 데이터에서 가격을 찾아 청산 규칙 적용 (상위 N개만 읽던 이전 버전의 결함 제거)
- 수수료/슬리피지 반영, 벤치마크(지수) 대비 성과, 월별 수익률, 청산 사유별 통계
- 결과는 콘솔 + backtest_out/ (summary.md, trades.csv, equity.csv). GitHub Actions 에서는 Step Summary 로도 출력
"""
import argparse
import os
import sys

import numpy as np
import pandas as pd

TOP_N = 7
RANK_CUT = 15
ATR_STOP_MULT = 2.5
TRAIL_TRIGGER = 1.08
TRAIL_KEEP = 0.92
COOLDOWN_DAYS = 3


# ───────────────────────── 데이터 로드 ─────────────────────────
def get_client():
    from supabase import create_client

    url = os.environ.get("SUPABASE_URL")
    key = os.environ.get("SUPABASE_KEY")
    if not url or not key:
        sys.exit("SUPABASE_URL / SUPABASE_KEY 환경변수가 필요합니다.")
    return create_client(url, key)


def _fetch_all(build_query, page=1000):
    rows, start = [], 0
    while True:
        res = build_query().range(start, start + page - 1).execute()
        data = res.data or []
        rows.extend(data)
        if len(data) < page:
            break
        start += page
    return rows


def load_data(client, market, start, end):
    """(전체 종목 일봉 DataFrame, 지수 DataFrame, 이름 맵) 반환."""
    index_symbol = "^KS11" if market == "KR" else "^GSPC"

    idx_rows = _fetch_all(
        lambda: client.table("daily_analysis")
        .select("price_date, close_price, ma20, ma200")
        .eq("ticker", index_symbol)
        .gte("price_date", start)
        .lte("price_date", end)
        .order("price_date")
    )
    idx = pd.DataFrame(idx_rows)
    if idx.empty:
        sys.exit(f"{index_symbol} 지수 데이터가 {start}~{end} 기간에 없습니다.")
    for c in ["close_price", "ma20", "ma200"]:
        idx[c] = pd.to_numeric(idx[c], errors="coerce")
    idx["price_date"] = pd.to_datetime(idx["price_date"]).dt.strftime("%Y-%m-%d")
    idx = idx.drop_duplicates("price_date").sort_values("price_date").reset_index(drop=True)

    cols = "price_date, ticker, momentum_rank, weighted_momentum, rs_score, rs_score_10, close_price, volume, ma20, ma50, atr"
    all_rows = []
    dates = idx["price_date"].tolist()
    print(f"📅 {len(dates)}영업일 데이터 수집 중...")
    for i, d in enumerate(dates, 1):
        all_rows.extend(
            _fetch_all(
                lambda d=d: client.table("daily_analysis")
                .select(cols)
                .eq("market", market)
                .eq("price_date", d)
                .order("ticker")
            )
        )
        if i % 40 == 0:
            print(f"   … {i}/{len(dates)}")
    df = pd.DataFrame(all_rows)
    if df.empty:
        sys.exit("종목 데이터가 없습니다.")
    df["price_date"] = pd.to_datetime(df["price_date"]).dt.strftime("%Y-%m-%d")
    df["ticker"] = df["ticker"].astype(str).str.strip().str.upper()
    df = df[~df["ticker"].str.startswith("^")]
    for c in ["momentum_rank", "weighted_momentum", "rs_score", "rs_score_10", "close_price", "volume", "ma20", "ma50", "atr"]:
        df[c] = pd.to_numeric(df[c], errors="coerce")

    # 거래량 가중 100일선(VWMA100): 시작일 이전 워밍업 구간을 별도로 읽어 100거래일을 채운다
    try:
        warm_from = (pd.to_datetime(start) - pd.Timedelta(days=170)).strftime("%Y-%m-%d")
        w_idx = _fetch_all(
            lambda: client.table("daily_analysis").select("price_date")
            .eq("ticker", index_symbol).gte("price_date", warm_from).lt("price_date", start).order("price_date")
        )
        w_dates = sorted({r["price_date"] for r in w_idx})
        print(f"📅 VWMA 워밍업 {len(w_dates)}영업일 수집 중...")
        w_rows = []
        for d in w_dates:
            w_rows.extend(_fetch_all(
                lambda d=d: client.table("daily_analysis").select("price_date, ticker, close_price, volume")
                .eq("market", market).eq("price_date", d).order("ticker")
            ))
        warm = pd.DataFrame(w_rows)
        if not warm.empty:
            warm["price_date"] = pd.to_datetime(warm["price_date"]).dt.strftime("%Y-%m-%d")
            warm["ticker"] = warm["ticker"].astype(str).str.strip().str.upper()
            for c in ["close_price", "volume"]:
                warm[c] = pd.to_numeric(warm[c], errors="coerce")
        else:
            warm = pd.DataFrame(columns=["price_date", "ticker", "close_price", "volume"])
    except Exception as e:
        print(f"⚠️ VWMA 워밍업 로드 실패: {e}")
        warm = pd.DataFrame(columns=["price_date", "ticker", "close_price", "volume"])
    allv = pd.concat([warm[["price_date", "ticker", "close_price", "volume"]],
                      df[["price_date", "ticker", "close_price", "volume"]]]).drop_duplicates(["price_date", "ticker"])
    pc = allv.pivot_table(index="price_date", columns="ticker", values="close_price").sort_index()
    pv = allv.pivot_table(index="price_date", columns="ticker", values="volume").sort_index().reindex(pc.index).fillna(0)
    den = pv.rolling(100, min_periods=100).sum()
    vw = ((pc * pv).rolling(100, min_periods=100).sum() / den).where(den > 0)
    above = (pc > vw).where(vw.notna())
    was_below = pd.concat([(above.shift(k) == False) for k in (1, 2, 3)]).groupby(level=0).any()
    cross = (above == True) & was_below.reindex(above.index).fillna(False)
    gap = (pc / vw - 1) * 100
    keys = pd.MultiIndex.from_frame(df[["price_date", "ticker"]])
    df["vwma100"] = vw.stack().reindex(keys).to_numpy()
    df["vw_gap"] = gap.stack().reindex(keys).to_numpy()
    df["vw_cross"] = cross.stack().reindex(keys).fillna(False).to_numpy().astype(bool)
    print(f"   VWMA100 유효 {int(df['vwma100'].notna().sum()):,}/{len(df):,}건")

    names, sectors = {}, {}
    try:
        for r in (client.table("stocks").select("ticker, name, sector").limit(10000).execute().data or []):
            t = str(r["ticker"]).strip().upper()
            names[t] = r["name"]
            if r.get("sector") and str(r["sector"]).strip():
                sectors[t] = str(r["sector"]).strip()
    except Exception:
        pass
    print(f"✅ 종목 데이터 {len(df):,}건 수집 완료 (섹터 {len(sectors)}종목)")
    return df, idx, names, sectors


# ───────────────────────── 시뮬레이션 ─────────────────────────
def simulate(df, idx, names, cfg):
    """cfg: dict(capital, fee_pct, slip_pct, staged, recov, breadth, breadth_th, rs_accel, corr, corr_th,
    atr_size, regime). 반환: (metrics dict, trades DataFrame, equity DataFrame)"""
    capital = float(cfg.get("capital", 20_000_000))
    fee = float(cfg.get("fee_pct", 0.0)) / 100.0
    slip = float(cfg.get("slip_pct", 0.0)) / 100.0

    dates = idx["price_date"].tolist()
    idx_close = dict(zip(idx["price_date"], idx["close_price"]))
    idx_ma20 = dict(zip(idx["price_date"], idx["ma20"]))
    idx_ma200 = dict(zip(idx["price_date"], idx["ma200"]))
    below = {d: (idx_ma20[d] or 0) > 0 and idx_close[d] < idx_ma20[d] for d in dates}

    by_date = {d: g.set_index("ticker") for d, g in df.groupby("price_date")}
    close_pivot = df.pivot_table(index="price_date", columns="ticker", values="close_price").sort_index()
    ret_pivot = close_pivot.pct_change()

    # 시장 폭: MA20 위 종목 비율
    breadth = {}
    for d, g in by_date.items():
        v = g[g["ma20"] > 0]
        breadth[d] = float((v["close_price"] > v["ma20"]).mean() * 100) if len(v) else np.nan

    cash = capital
    pos = {}  # ticker -> dict
    sold_recent = {}  # ticker -> (sell_date, sell_price)
    trades, equity = [], []
    TOPN = int(cfg.get("top_n", TOP_N))
    RCUT = cfg.get("rank_cut", RANK_CUT)
    sort_mode = cfg.get("sort", "gap")  # gap(이격도 오름차순, 현행) | rank(모멘텀 순위) | rs90(RS90 내림차순)
    nextday = bool(cfg.get("nextday"))  # True: 신호일 다음 거래일 종가에 체결
    pend_buys = []  # nextday 모드: 체결 대기 매수 [{t, amt, atr}]
    vmode = cfg.get("vwma_mode")  # None | "above" | "pullback" | "breakout"

    def do_sell(t, c, d, reason):
        nonlocal cash
        p = pos[t]
        px = c * (1 - slip)
        cash += px * p["qty"] * (1 - fee)
        trades.append({
            "ticker": t, "name": names.get(t, t), "buy_date": p["date"], "sell_date": d,
            "buy_price": p["buy"], "sell_price": px, "qty": p["qty"],
            "profit_amt": (px - p["buy"]) * p["qty"] - (p["buy"] * p["qty"] * fee) - (px * p["qty"] * fee),
            "profit_rate": (px / p["buy"] - 1) * 100, "reason": reason,
        })
        sold_recent[t] = (d, px)
        del pos[t]

    def do_buy(t, c, atr, amt, d):
        nonlocal cash
        px = c * (1 + slip)
        if amt > cash or px <= 0:
            return False
        qty = amt / (px * (1 + fee))
        cash -= amt
        pos[t] = {"buy": px, "qty": qty, "date": d, "high": c, "atr": atr}
        return True

    for di, d in enumerate(dates):
        g = by_date.get(d)
        if g is None:
            continue
        prices = g["close_price"].to_dict()

        # (다음 거래일 체결 모드) 전일 신호의 주문을 오늘 종가로 체결: 매도 먼저, 매수는 그 다음
        if nextday:
            for t in list(pos.keys()):
                c = prices.get(t)
                if pos[t].get("exit") and c is not None and pd.notna(c):
                    pos[t]["high"] = max(pos[t]["high"], c)
                    do_sell(t, c, d, pos[t]["exit"])
            for pb in pend_buys:
                c = prices.get(pb["t"])
                if pb["t"] in pos or len(pos) >= TOPN or c is None or pd.isna(c):
                    continue
                do_buy(pb["t"], float(c), pb["atr"], pb["amt"], d)
            pend_buys = []

        # 레짐 판정 (db.get_market_regime 과 동일: 최근 3거래일이 모두 MA20 아래면 약세)
        reduce = below[d]
        stop_new = di >= 2 and all(below[x] for x in dates[di - 2: di + 1])
        use_regime = cfg.get("regime", True)
        is_bull = (not reduce) if use_regime else True
        if use_regime and cfg.get("staged"):
            is_bull = not stop_new
        liquidate = use_regime and (stop_new or not is_bull)

        no_new_buy = False
        if cfg.get("idx200", True) and (idx_ma200.get(d) or 0) > 0 and idx_close[d] < idx_ma200[d]:
            no_new_buy = True
        if use_regime and cfg.get("staged") and reduce and not stop_new:
            no_new_buy = True
        if cfg.get("recov") and di >= 1 and not all(not below[x] for x in dates[max(0, di - 1): di + 1]):
            no_new_buy = True
        if cfg.get("breadth") and pd.notna(breadth.get(d)) and breadth[d] < cfg.get("breadth_th", 40):
            no_new_buy = True

        # 전일 종가가 MA20 아래였던 종목 (MA20 2일 연속 이탈 판정용)
        prev_below = {}
        if di >= 1 and by_date.get(dates[di - 1]) is not None:
            pg = by_date[dates[di - 1]]
            prev_below = ((pg["ma20"] > 0) & (pg["close_price"] < pg["ma20"])).to_dict()

        # 1) 청산
        for t in list(pos.keys()):
            p = pos[t]
            c = prices.get(t)
            if c is None or pd.isna(c):
                continue
            p["high"] = max(p["high"], c)
            if p.get("exit"):  # 이미 청산 신호가 나서 다음 거래일 체결 대기 중
                continue
            reason = None
            ma20 = g["ma20"].get(t, np.nan)
            if liquidate:
                reason = "레짐 전환"
            elif c <= p["buy"] - ATR_STOP_MULT * p["atr"]:
                reason = "ATR 손절"
            elif p["high"] >= p["buy"] * TRAIL_TRIGGER and c <= max(p["high"] * TRAIL_KEEP, p["buy"]):
                reason = "트레일링스탑"
            elif pd.notna(ma20) and ma20 > 0 and c < ma20 and prev_below.get(t, False):
                reason = "MA20 2일 연속 이탈"
            if reason:
                if nextday:
                    p["exit"] = reason
                else:
                    do_sell(t, c, d, reason)

        # 2) 신규 매수
        if (not no_new_buy) and (not stop_new) and is_bull and len(pos) < TOPN:
            cond = (
                (g["momentum_rank"] <= RCUT) & (g["rs_score"] > 0) & (g["rs_score_10"] > 0)
                & (g["ma20"] > 0) & (g["close_price"] > g["ma20"])
            )
            if vmode and "vw_gap" in g.columns:
                if vmode == "above":
                    cond = cond & (g["vw_gap"] > 0)
                elif vmode == "pullback":  # 100선 위 0~3% 이내로 눌려 지지받는 종목
                    cond = cond & (g["vw_gap"] >= 0) & (g["vw_gap"] <= cfg.get("vw_band", 3.0))
                elif vmode == "breakout":  # 최근 3거래일 내 100선 아래 → 위로 돌파
                    cond = cond & (g["vw_cross"] == True)
            cand = g[cond].copy()
            cand["gap"] = (cand["close_price"] / cand["ma20"] - 1) * 100
            if sort_mode == "rank":
                cand = cand.sort_values(["momentum_rank", "gap"])
            elif sort_mode == "rs90":
                cand = cand.sort_values(["rs_score", "gap"], ascending=[False, True])
            else:
                cand = cand.sort_values("gap")
            if cfg.get("rs_accel") and len(cand) > 1:
                gr = cand["gap"].rank(method="first")
                ar = (cand["rs_score_10"] - cand["rs_score"]).rank(ascending=False, method="first")
                cand = cand.assign(_s=gr + ar).sort_values(["_s", "gap"]).drop(columns="_s")

            corr = None
            if cfg.get("corr") and len(cand):
                hist = ret_pivot.loc[:d].tail(60)
                use = list(dict.fromkeys(t for t in list(cand.index) + list(pos.keys()) if t in hist.columns))
                if len(use) > 1:
                    corr = hist[use].corr(min_periods=20)

            equity_now = cash + sum(prices.get(t, p["buy"]) * p["qty"] for t, p in pos.items())
            budget = equity_now / TOPN
            chosen = []
            queued = [pb["t"] for pb in pend_buys]
            for t, row in cand.iterrows():
                if len(pos) + len(queued) + len(chosen) >= TOPN:
                    break
                if t in pos or t in queued:
                    continue
                if t in sold_recent:
                    sd, sp = sold_recent[t]
                    if (pd.to_datetime(d) - pd.to_datetime(sd)).days <= COOLDOWN_DAYS and row["close_price"] <= sp:
                        continue
                if corr is not None and t in corr.index:
                    others = list(pos.keys()) + queued + chosen
                    if any(o in corr.columns and o != t and pd.notna(corr.loc[t, o]) and corr.loc[t, o] >= cfg.get("corr_th", 0.85) for o in others):
                        continue
                cap_n = int(cfg.get("sector_cap", 0) or 0)
                sec_map = cfg.get("sectors", {})
                if cap_n > 0 and sec_map.get(t):
                    same = sum(1 for o in list(pos.keys()) + queued + chosen if sec_map.get(o) == sec_map[t])
                    if same >= cap_n:
                        continue
                chosen.append(t)
                c = float(row["close_price"])
                atr = float(row["atr"]) if pd.notna(row["atr"]) else 0.0
                amt = budget
                if cfg.get("atr_size") and atr > 0 and c > 0:
                    amt = min(amt, equity_now * 0.02 / (ATR_STOP_MULT * atr / c))
                if nextday:
                    pend_buys.append({"t": t, "amt": amt, "atr": atr})
                    continue
                if not do_buy(t, c, atr, amt, d):
                    chosen.pop()

        eq = cash + sum(prices.get(t, p["buy"]) * p["qty"] for t, p in pos.items())
        equity.append({"date": d, "equity": eq, "positions": len(pos)})

    eqdf = pd.DataFrame(equity)
    trdf = pd.DataFrame(trades)
    if eqdf.empty:
        return {}, trdf, eqdf

    final = float(eqdf["equity"].iloc[-1])
    peak = eqdf["equity"].cummax()
    mdd = float(((eqdf["equity"] - peak) / peak * 100).min())
    _ic = idx["close_price"].dropna()
    first_i, last_i = (_ic.iloc[0], _ic.iloc[-1]) if len(_ic) else (np.nan, np.nan)
    n = len(trdf)
    wins = trdf[trdf["profit_amt"] > 0] if n else trdf
    losses = trdf[trdf["profit_amt"] < 0] if n else trdf
    pf = (wins["profit_amt"].sum() / abs(losses["profit_amt"].sum())) if n and len(losses) and losses["profit_amt"].sum() != 0 else np.nan
    m = {
        "최종자산": final,
        "수익률(%)": (final / capital - 1) * 100,
        "벤치마크(%)": (last_i / first_i - 1) * 100,
        "MDD(%)": mdd,
        "거래수": n,
        "승률(%)": (len(wins) / n * 100) if n else 0.0,
        "평균수익률(%)": float(trdf["profit_rate"].mean()) if n else 0.0,
        "손익비(PF)": pf,
        "평균보유종목": float(eqdf["positions"].mean()),
    }
    return m, trdf, eqdf


# ───────────────────────── 리포트 ─────────────────────────
def fmt_metrics_table(rows):
    cols = ["시나리오", "수익률(%)", "벤치마크(%)", "MDD(%)", "거래수", "승률(%)", "손익비(PF)", "최종자산"]
    out = ["| " + " | ".join(cols) + " |", "|" + "|".join(["---"] * len(cols)) + "|"]
    for name, m in rows:
        if not m:
            continue
        out.append(
            f"| {name} | {m['수익률(%)']:+.2f} | {m['벤치마크(%)']:+.2f} | {m['MDD(%)']:.2f} | {m['거래수']} | "
            f"{m['승률(%)']:.1f} | {m['손익비(PF)']:.2f} | {m['최종자산']:,.0f} |"
        )
    return "\n".join(out)


def _md(df):
    try:
        return df.to_markdown()
    except Exception:
        return "```\n" + df.to_string() + "\n```"


def detail_report(m, trdf, eqdf):
    lines = []
    if trdf is not None and len(trdf):
        lines.append("### 청산 사유별")
        g = trdf.groupby("reason").agg(건수=("ticker", "count"), 평균수익률=("profit_rate", "mean"), 손익합=("profit_amt", "sum")).round(2)
        lines.append(_md(g))
        e = eqdf.copy()
        e["month"] = e["date"].str[:7]
        mm = e.groupby("month")["equity"].agg(["first", "last"])
        mm["월수익률(%)"] = ((mm["last"] / mm["first"]) - 1) * 100
        lines.append("\n### 월별 수익률(월 첫 평가 대비)")
        mt = mm[["월수익률(%)"]].round(2)
        lines.append(_md(mt))
    return "\n".join(lines)


def ma200_diagnostic(idx):
    v = idx[(idx["ma200"].notna()) & (idx["ma200"] > 0)]
    below = int((v["close_price"] < v["ma200"]).sum()) if len(v) else 0
    return (f"- 지수 MA200 데이터: {len(v)}/{len(idx)}일 유효, 종가<MA200 인 날 {below}일"
            + (" ⚠️ MA200 값이 비어 있어 조건이 작동하지 않습니다" if len(v) < len(idx) * 0.5 else ""))


def top_trade_share(trdf, k=3):
    """총 이익 중 상위 k개 거래가 차지하는 비중(%) — 소수 대박 거래 의존도."""
    if trdf is None or trdf.empty:
        return np.nan
    gains = trdf[trdf["profit_amt"] > 0]["profit_amt"].sort_values(ascending=False)
    return float(gains.head(k).sum() / gains.sum() * 100) if gains.sum() > 0 else np.nan


def run_robust(df, idx, names, base, breadth_ths, segments):
    """기간 분할 + 기준값 민감도. 구간마다 초기자금으로 다시 시작해 비교한다."""
    n = len(idx)
    cuts = [round(i * n / segments) for i in range(segments + 1)]
    segs = [("전체", idx.reset_index(drop=True))]
    for i in range(segments):
        sub = idx.iloc[cuts[i]: cuts[i + 1]].reset_index(drop=True)
        if len(sub) >= 20:
            segs.append((f"{sub['price_date'].iloc[0][5:]}~{sub['price_date'].iloc[-1][5:]}", sub))

    scen = [("기본(현행)", base), ("레짐 끔(참고)", dict(base, regime=False)), ("3단계 레짐", dict(base, staged=True))]
    for th in breadth_ths:
        scen.append((f"시장 폭<{th:g}%", dict(base, breadth=True, breadth_th=th)))
    for th in breadth_ths:
        scen.append((f"3단계+시장 폭<{th:g}%", dict(base, staged=True, breadth=True, breadth_th=th)))
    scen.append(("지수 2일 안착 단독", dict(base, recov=True)))
    scen.append(("RS 가속 단독", dict(base, rs_accel=True)))
    scen.append(("2일 안착+RS 가속", dict(base, recov=True, rs_accel=True)))
    scen.append(("2일 안착+RS 가속+폭40", dict(base, recov=True, rs_accel=True, breadth=True, breadth_th=40)))
    scen.append(("섹터 상한 3 단독", dict(base, sector_cap=3)))
    scen.append(("3단계+폭40+섹터2", dict(base, staged=True, breadth=True, breadth_th=40, sector_cap=2)))
    scen.append(("섹터 상한 2 단독", dict(base, sector_cap=2)))
    scen.append(("3단계+폭40+RS가속", dict(base, staged=True, breadth=True, breadth_th=40, rs_accel=True)))
    scen.append(("보완 전부(폭40)", dict(base, staged=True, recov=True, breadth=True, breadth_th=40,
                                      rs_accel=True, corr=True, corr_th=0.85, atr_size=True)))

    ret = {name: {} for name, _ in scen}
    mdd = {name: {} for name, _ in scen}
    share = {}
    bench = {}
    for sname, sidx in segs:
        bench[sname] = (sidx["close_price"].iloc[-1] / sidx["close_price"].iloc[0] - 1) * 100
        for name, cfg in scen:
            m, tr, _ = simulate(df, sidx, names, cfg)
            ret[name][sname] = m.get("수익률(%)", np.nan) if m else np.nan
            mdd[name][sname] = m.get("MDD(%)", np.nan) if m else np.nan
            if sname == "전체" and name in ("기본(현행)", "3단계 레짐", "보완 전부(폭40)"):
                share[name] = top_trade_share(tr)

    cols = [c for c, _ in segs]
    r = pd.DataFrame(ret).T[cols]
    r.loc["(벤치마크 지수)"] = pd.Series(bench)
    d = pd.DataFrame(mdd).T[cols]
    out = ["## 기간 분할 · 수익률(%)", _md(r.round(1)), "", "## 기간 분할 · MDD(%)", _md(d.round(1))]
    # 구간 중 현행 대비 이긴 구간 수
    base_row = r.loc["기본(현행)"]
    wins = {nm: int((r.loc[nm, cols[1:]] > base_row[cols[1:]]).sum()) for nm in r.index if nm not in ("기본(현행)", "(벤치마크 지수)")}
    out += ["", f"## 현행 대비 수익률이 더 높았던 구간 수 (총 {len(cols) - 1}개 구간)", _md(pd.Series(wins, name="이긴 구간").to_frame())]
    out += ["", "## 총 이익 중 상위 3개 거래 비중(%) — 높을수록 소수 거래 의존",
            _md(pd.Series(share, name="상위3 비중").round(1).to_frame())]
    return "\n".join(out)


def save_trades_to_db(client, trades):
    if trades is None or trades.empty:
        return
    try:
        client.table("backtest_trades").delete().neq("id", 0).execute()
        recs = [
            {
                "ticker": r["ticker"], "name": r["name"], "buy_date": r["buy_date"], "sell_date": r["sell_date"],
                "buy_price": float(r["buy_price"]), "sell_price": float(r["sell_price"]), "quantity": float(r["qty"]),
                "profit_amount": float(r["profit_amt"]), "profit_rate": float(r["profit_rate"]), "exit_reason": r["reason"],
            }
            for _, r in trades.iterrows()
        ]
        for i in range(0, len(recs), 100):
            client.table("backtest_trades").insert(recs[i: i + 100]).execute()
        print(f"✅ backtest_trades 에 {len(recs)}건 저장")
    except Exception as e:
        print(f"⚠️ DB 저장 실패: {e}")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--market", default="KR", choices=["KR", "US"])
    ap.add_argument("--start", default="2026-01-01")
    ap.add_argument("--end", default="2026-12-31")
    ap.add_argument("--capital", type=float, default=None)
    ap.add_argument("--fee_pct", type=float, default=None, help="편도 수수료+세금 %% (기본 KR 0.1 / US 0.05)")
    ap.add_argument("--slip_pct", type=float, default=0.1, help="편도 슬리피지 %% (기본 0.1)")
    ap.add_argument("--no_idx200", action="store_true", help="지수 MA200 아래 신규매수 금지 조건 끄기")
    ap.add_argument("--no_regime", action="store_true", help="지수 레짐 필터 끄기")
    ap.add_argument("--staged", action="store_true")
    ap.add_argument("--recov", action="store_true")
    ap.add_argument("--breadth", action="store_true")
    ap.add_argument("--breadth_th", type=float, default=40)
    ap.add_argument("--rs_accel", action="store_true")
    ap.add_argument("--corr", action="store_true")
    ap.add_argument("--sector_cap", type=int, default=0, help="같은 섹터 최대 보유 종목 수(0=제한 없음)")
    ap.add_argument("--corr_th", type=float, default=0.85)
    ap.add_argument("--atr_size", action="store_true")
    ap.add_argument("--robust", action="store_true", help="기간 분할 + 시장 폭 기준 민감도 분석")
    ap.add_argument("--segments", type=int, default=3, help="--robust 기간 분할 개수")
    ap.add_argument("--compare", action="store_true", help="기본 전략과 각 보완 옵션을 한 표로 비교")
    ap.add_argument("--next_day", action="store_true", help="신호일 다음 거래일 종가에 체결(기본은 신호일 종가)")
    ap.add_argument("--vwma_mode", default="", choices=["", "above", "pullback", "breakout"], help="거래량가중 100선 매수 조건")
    ap.add_argument("--fill_compare", action="store_true", help="체결 가정(당일/다음날) × 거래량가중 100선 매수조건 비교표")
    ap.add_argument("--save_db", action="store_true", help="결과 매매를 backtest_trades 에 저장(기존 내용 삭제)")
    # 이전 버전 호환: python backtest.py 2026-01-01 2026-09-30
    argv = sys.argv[1:]
    if len(argv) >= 2 and not argv[0].startswith("-"):
        argv = ["--start", argv[0], "--end", argv[1]] + argv[2:]
    a = ap.parse_args(argv)

    capital = a.capital or (20_000_000 if a.market == "KR" else 6000.0)
    fee = a.fee_pct if a.fee_pct is not None else (0.1 if a.market == "KR" else 0.05)

    client = get_client()
    df, idx, names, sectors = load_data(client, a.market, a.start, a.end)

    base = dict(capital=capital, fee_pct=fee, slip_pct=a.slip_pct, regime=not a.no_regime, idx200=not a.no_idx200, sectors=sectors,
                nextday=a.next_day, vwma_mode=(a.vwma_mode or None))
    user = dict(base, staged=a.staged, recov=a.recov, breadth=a.breadth, breadth_th=a.breadth_th,
                rs_accel=a.rs_accel, corr=a.corr, corr_th=a.corr_th, atr_size=a.atr_size, sector_cap=a.sector_cap)

    os.makedirs("backtest_out", exist_ok=True)
    head = (f"# Quant Alpha 백테스트 · {a.market} · {idx['price_date'].iloc[0]} ~ {idx['price_date'].iloc[-1]}\n"
            f"- 초기자금 {capital:,.0f}, 편도 비용 {fee}% + 슬리피지 {a.slip_pct}%, Top{TOP_N}, 순위≤{RANK_CUT}\n"
            f"- 벤치마크: {'KOSPI(^KS11)' if a.market == 'KR' else 'S&P500(^GSPC)'}\n")

    if a.robust and not a.fill_compare:
        md = head + "\n" + ma200_diagnostic(idx) + "\n\n" + run_robust(df, idx, names, base, [30, 40, 50], max(2, a.segments))
        m, trdf, eqdf = simulate(df, idx, names, base)
    elif a.fill_compare:
        b0 = dict(base, nextday=False, vwma_mode=None)
        names_v = [("", None), (" + VWMA100 위", "above"), (" + VWMA100 눌림(0~3%)", "pullback"), (" + VWMA100 돌파(3일내)", "breakout")]
        rows = []
        for tag, nd in [("[신호일 종가] ", False), ("[다음날 종가] ", True)]:
            for suffix, vm in names_v:
                m, _, _ = simulate(df, idx, names, dict(b0, nextday=nd, vwma_mode=vm))
                rows.append((tag + ("기본 전략" if not vm else "기본" ) + suffix, m))
        md = (head + "\n" + ma200_diagnostic(idx) + "\n\n## 체결 가정 × 거래량가중 100선 매수조건 비교\n" + fmt_metrics_table(rows)
              + "\n\n- VWMA100 위: 종가 > 거래량가중 100일선 / 눌림: 선 위 0~3% 이내 / 돌파: 최근 3거래일 내 선 아래→위 돌파"
              + "\n- 모든 시나리오는 기본 후보 조건(순위≤15, RS>0, 종가>MA20)을 유지하고 위 조건만 추가, 정렬은 기존 이격도 오름차순\n")
        m, trdf, eqdf = simulate(df, idx, names, b0)
    elif a.compare:
        scen = [
            ("기본(현행 전략)", base),
            ("레짐 끔(참고)", dict(base, regime=False)),
            ("지수 MA200 조건 끔(참고)", dict(base, idx200=False)),
            ("+3단계 레짐", dict(base, staged=True)),
            ("+지수 2일 안착", dict(base, recov=True)),
            (f"+시장 폭<{a.breadth_th:.0f}% 보류", dict(base, breadth=True, breadth_th=a.breadth_th)),
            ("+RS 가속 우선", dict(base, rs_accel=True)),
            (f"+상관≥{a.corr_th} 제외", dict(base, corr=True, corr_th=a.corr_th)),
            ("+섹터 상한 2", dict(base, sector_cap=2)),
            ("+섹터 상한 3", dict(base, sector_cap=3)),
            ("+ATR 변동성 비중", dict(base, atr_size=True)),
            ("보완 전부", dict(base, staged=True, recov=True, breadth=True, breadth_th=a.breadth_th,
                              rs_accel=True, corr=True, corr_th=a.corr_th, atr_size=True)),
        ]
        rows = []
        for name, cfg in scen:
            m, _, _ = simulate(df, idx, names, cfg)
            rows.append((name, m))
        md = head + "\n" + ma200_diagnostic(idx) + "\n\n## 시나리오 비교\n" + fmt_metrics_table(rows)
        m, trdf, eqdf = simulate(df, idx, names, base)
    else:
        m, trdf, eqdf = simulate(df, idx, names, user)
        md = head + "\n## 결과\n" + fmt_metrics_table([("선택 옵션", m)]) + "\n\n" + detail_report(m, trdf, eqdf)

    fill_note = "시나리오별로 표기된 체결 가정" if a.fill_compare else ("다음 거래일 종가" if a.next_day else "신호일 종가") + " 체결을 가정합니다."
    md += "\n\n> 주의: 과거 성과이며 미래를 보장하지 않습니다. " + fill_note + "\n"
    print(md)
    open("backtest_out/summary.md", "w", encoding="utf-8").write(md)
    if trdf is not None and len(trdf):
        trdf.to_csv("backtest_out/trades.csv", index=False, encoding="utf-8-sig")
    if eqdf is not None and len(eqdf):
        eqdf.to_csv("backtest_out/equity.csv", index=False)
    step = os.environ.get("GITHUB_STEP_SUMMARY")
    if step:
        with open(step, "a", encoding="utf-8") as f:
            f.write(md)
    if a.save_db:
        save_trades_to_db(client, trdf)


if __name__ == "__main__":
    main()
