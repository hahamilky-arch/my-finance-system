"""5차 — 추세 돌파 계열 두 전략 검증 (사전 고정 후보 96개).

전략 A: 돈치안 돌파 — 종가가 직전 N일 고가를 넘으면 매수, 직전 M일 저가를 이탈하면 매도.
        N ∈ {20, 50, 55}, M ∈ {10, 20}  (6개)
전략 B: 추세 전환 확인 — 50일선 > 200일선 상태에서 종가가 20일선을 아래→위로 돌파하면 매수,
        종가가 50일선 아래(1일 / 2일 연속)로 떨어지면 매도  (2개)
공통
- 동시 보유 상한 P ∈ {5, 7, 10}, 슬롯당 1/P 균등 투자, 신호가 많으면 모멘텀 순위 높은 순
- 레짐 {끔, 켬}: 켬 = 지수<MA20 또는 지수<MA200이면 신규 매수 금지, 지수가 MA20 아래 3일 연속이면 전량 청산
- ATR 손절 {끔, 켬}: 켬 = 종가 ≤ 진입가 − 2.5 × 진입 당시 ATR
- 신호일 종가 판단 → 다음 거래일 종가 체결, 편도 비용 반영
- 모든 설정을 같은 시작일(가장 긴 N일 워밍업 이후)부터 평가
검증: 지수 대비 초과수익, 기간 3분할 폴드, 이웃 설정(파라미터 한 칸 옆) 평균 초과수익, 현행 전략(Top7 Regime)·유니버스 동일가중 보유 비교,
      '하락장 이후(--since)' 구간 수익 별도 표시.
통과 = 전체 초과수익 > 0, 폴드 n-1개 이상 초과수익 > 0, 이웃 평균 초과수익 > 0

실행: python research5.py --market KR --start 2026-01-02 --end 2026-12-31 --since 2026-05-01
"""
import argparse
import os
import sys

import numpy as np
import pandas as pd

DON_N = [20, 50, 55]
DON_M = [10, 20]
MA_EXIT = [1, 2]
PS = [5, 7, 10]
REGS = ["off", "on"]
ATRS = ["off", "on"]


class Panel:
    pass


def fetch_extra(client, bt, dates, market):
    rows = []
    for i, d in enumerate(dates, 1):
        rows.extend(bt._fetch_all(
            lambda d=d: client.table("daily_analysis").select("price_date, ticker, high_price, low_price, ma200")
            .eq("market", market).eq("price_date", d).order("ticker")
        ))
        if i % 40 == 0:
            print(f"   … 추가 컬럼 {i}/{len(dates)}")
    ex = pd.DataFrame(rows)
    if ex.empty:
        return pd.DataFrame(columns=["price_date", "ticker", "high_price", "low_price", "ma200"])
    ex["price_date"] = pd.to_datetime(ex["price_date"]).dt.strftime("%Y-%m-%d")
    ex["ticker"] = ex["ticker"].astype(str).str.strip().str.upper()
    for c in ["high_price", "low_price", "ma200"]:
        ex[c] = pd.to_numeric(ex[c], errors="coerce")
    return ex


def build_panel(df, idx):
    p = Panel()
    dates = [d for d in idx["price_date"].tolist() if d in set(df["price_date"])]
    p.dates = dates
    ix = idx.set_index("price_date").reindex(dates)
    p.idx_close = ix["close_price"].to_numpy(float)
    p.idx_ma20 = ix["ma20"].to_numpy(float)
    p.idx_ma200 = ix["ma200"].to_numpy(float)

    def piv(col):
        return df.pivot_table(index="price_date", columns="ticker", values=col).reindex(dates)

    C = piv("close_price")
    H = piv("high_price")
    L = piv("low_price")
    p.tickers = list(C.columns)
    p.C = C.to_numpy(float)
    p.R = np.nan_to_num(C.ffill(limit=5).pct_change().to_numpy(float), nan=0.0, posinf=0.0, neginf=0.0)
    p.rank = piv("momentum_rank").to_numpy(float)
    p.atr = piv("atr").to_numpy(float)
    ma20 = piv("ma20")
    ma50 = piv("ma50")
    ma200 = piv("ma200")
    p.ma20, p.ma50, p.ma200 = ma20.to_numpy(float), ma50.to_numpy(float), ma200.to_numpy(float)

    # 돈치안 신호 (직전 N일 고가/저가는 오늘 제외)
    p.don_entry = {}
    for n in DON_N:
        hh = H.shift(1).rolling(n, min_periods=n).max()
        p.don_entry[n] = (C > hh).to_numpy(bool)
    p.don_exit = {}
    for m in DON_M:
        ll = L.shift(1).rolling(m, min_periods=m).min()
        p.don_exit[m] = (C < ll).to_numpy(bool)
    # 전략 B 신호
    cross20 = (C > ma20) & (C.shift(1) <= ma20.shift(1))
    p.ma_entry = (cross20 & (ma50 > ma200)).to_numpy(bool)
    below50 = (C < ma50)
    p.ma_exit = {1: below50.to_numpy(bool), 2: (below50 & below50.shift(1, fill_value=False)).to_numpy(bool)}

    # 지수 레짐
    below = (p.idx_ma20 > 0) & (p.idx_close < p.idx_ma20)
    b3 = below & np.roll(below, 1) & np.roll(below, 2)
    b3[:2] = False
    p.block = below | ((p.idx_ma200 > 0) & (p.idx_close < p.idx_ma200))
    p.liq = b3
    p.warm = max(DON_N) + 1
    return p


def rule_arrays(rule, p):
    if rule[0] == "don":
        return p.don_entry[rule[1]], p.don_exit[rule[2]]
    return p.ma_entry, p.ma_exit[rule[1]]


def simulate(p, rule, P, reg, atr_stop, lo, hi, cost):
    """반환: (일별 수익률 배열, 거래 수익률 리스트, 평균 투자비중)"""
    entry, exit_ = rule_arrays(rule, p)
    K = p.C.shape[1]
    val = np.zeros(K)  # 종목별 평가금액(자기자본 1 기준 비율)
    held = np.zeros(K, bool)
    entry_px = np.full(K, np.nan)
    entry_atr = np.full(K, np.nan)
    cash = 1.0
    pend_buy, pend_sell = [], []
    rets, trades, expo = [], [], []
    ent_val = np.zeros(K)
    prev_total = 1.0
    for t in range(lo, hi + 1):
        # 1) 일일 평가 갱신
        if t > lo:
            val = val * (1 + p.R[t])
        # 2) 전일 신호 체결 (매도 먼저)
        for k in pend_sell:
            if held[k]:
                cash += val[k] * (1 - cost)
                trades.append(val[k] * (1 - cost) / ent_val[k] - 1.0)
                val[k] = 0.0
                held[k] = False
        pend_sell = []
        total_pre = cash + val.sum()
        for k in pend_buy:
            if held[k] or not np.isfinite(p.C[t, k]):
                continue
            slot = total_pre / P
            amt = min(slot, cash)
            if amt <= 1e-9:
                continue
            cash -= amt
            val[k] = amt * (1 - cost)
            ent_val[k] = amt
            held[k] = True
            entry_px[k] = p.C[t, k]
            entry_atr[k] = p.atr[t, k]
        pend_buy = []
        total = cash + val.sum()
        rets.append(total / prev_total - 1.0)
        expo.append(val.sum() / total if total > 0 else 0.0)
        prev_total = total
        if t == hi:
            break
        # 3) 오늘 종가 기준 신호
        hk = np.where(held)[0]
        sells = []
        liq = reg == "on" and p.liq[t]
        for k in hk:
            c = p.C[t, k]
            if not np.isfinite(c):
                continue
            if liq or exit_[t, k]:
                sells.append(k)
            elif atr_stop == "on" and np.isfinite(entry_atr[k]) and entry_atr[k] > 0 and c <= entry_px[k] - 2.5 * entry_atr[k]:
                sells.append(k)
        free = P - (len(hk) - len(sells))
        buys = []
        if free > 0 and not (reg == "on" and p.block[t]):
            cand = np.where(entry[t] & ~held & np.isfinite(p.C[t]) & np.isfinite(p.rank[t]))[0]
            if len(cand):
                cand = cand[np.argsort(p.rank[t, cand])]
                buys = list(cand[:free])
        pend_sell, pend_buy = sells, buys
    return np.array(rets), trades, float(np.mean(expo))


def stats(rets, trades, expo, p, lo, hi):
    eq = np.cumprod(1 + rets)
    tot = (eq[-1] - 1) * 100
    peak = np.maximum.accumulate(eq)
    mdd = float(((eq - peak) / peak).min() * 100)
    ic = p.idx_close
    bench = (ic[hi] / ic[lo] - 1) * 100
    tr = np.array(trades) if trades else np.array([])
    return dict(ret=tot, bench=bench, excess=tot - bench, mdd=mdd, n_trades=len(tr),
                win=float((tr > 0).mean() * 100) if len(tr) else np.nan,
                avg_trade=float(tr.mean() * 100) if len(tr) else np.nan, expo=expo * 100)


def fold_ranges(lo, hi, n):
    edges = np.linspace(lo, hi, n + 1).astype(int)
    return [(int(edges[i]), int(edges[i + 1])) for i in range(n)]


def all_rules():
    rs = [("don", n, m) for n in DON_N for m in DON_M]
    rs += [("ma", e) for e in MA_EXIT]
    return rs


def rule_label(r):
    if r[0] == "don":
        return f"돈치안 진입 {r[1]}일 고가 / 청산 {r[2]}일 저가"
    return f"MA 골든+20일선 돌파 / 50일선 {r[1]}일 이탈 청산"


def neighbors(cfg):
    rule, P, reg, atr = cfg
    out = []
    for dp in (-1, 1):
        j = PS.index(P) + dp
        if 0 <= j < len(PS):
            out.append((rule, PS[j], reg, atr))
    if rule[0] == "don":
        for dn in (-1, 1):
            j = DON_N.index(rule[1]) + dn
            if 0 <= j < len(DON_N):
                out.append((("don", DON_N[j], rule[2]), P, reg, atr))
        for dm in (-1, 1):
            j = DON_M.index(rule[2]) + dm
            if 0 <= j < len(DON_M):
                out.append((("don", rule[1], DON_M[j]), P, reg, atr))
    else:
        for de in (-1, 1):
            j = MA_EXIT.index(rule[1]) + de
            if 0 <= j < len(MA_EXIT):
                out.append((("ma", MA_EXIT[j]), P, reg, atr))
    return out


def analyze(p, cost, n_folds, since):
    lo = min(p.warm, len(p.dates) - 2)
    hi = len(p.dates) - 1
    fr = fold_ranges(lo, hi, n_folds)
    si = None
    if since:
        cand = [i for i, d in enumerate(p.dates) if d >= since]
        si = cand[0] if cand and cand[0] > lo else None
    res = {}
    for rule in all_rules():
        for P in PS:
            for reg in REGS:
                for atr in ATRS:
                    cfg = (rule, P, reg, atr)
                    r, tr, ex = simulate(p, rule, P, reg, atr, lo, hi, cost)
                    full = stats(r, tr, ex, p, lo, hi)
                    fm = []
                    for a, b in fr:
                        rf, tf, ef = simulate(p, rule, P, reg, atr, a, b, cost)
                        fm.append(stats(rf, tf, ef, p, a, b)["excess"])
                    sc = None
                    if si is not None:
                        rs_, ts_, es_ = simulate(p, rule, P, reg, atr, si, hi, cost)
                        sm = stats(rs_, ts_, es_, p, si, hi)
                        sc = (sm["ret"], sm["bench"])
                    res[cfg] = dict(full=full, folds=fm, since=sc)
    for cfg, v in res.items():
        nb = [res[c]["full"]["excess"] for c in neighbors(cfg) if c in res]
        v["nb"] = float(np.mean(nb)) if nb else np.nan
    return res, lo, hi, fr, si


def passed(v, n_folds):
    pos = sum(1 for x in v["folds"] if np.isfinite(x) and x > 0)
    return v["full"]["excess"] > 0 and pos >= max(1, n_folds - 1) and np.isfinite(v["nb"]) and v["nb"] > 0


def fmt(x, d=1, sign=True):
    if x is None or (isinstance(x, float) and not np.isfinite(x)):
        return "-"
    return f"{x:+.{d}f}" if sign else f"{x:.{d}f}"


def universe_hold(p, lo, hi):
    """보유 가능한 전 종목 동일가중, 매일 리밸런싱 없이 시작일 균등 매수 후 보유 (참고선)."""
    r = p.R[lo + 1:hi + 1]
    alive = np.isfinite(p.C[lo])
    if alive.sum() == 0:
        return np.nan
    cum = np.prod(1 + r[:, alive], axis=0)
    return float((cum.mean() - 1) * 100)


def report(res, p, lo, hi, fr, si, n_folds, base_row, market):
    out = []
    ic = p.idx_close
    out.append(f"## {market} · 평가 {p.dates[lo]} ~ {p.dates[hi]} ({hi - lo + 1}거래일, 앞 {lo}일은 신호 워밍업)")
    out.append(f"- 지수 {fmt((ic[hi] / ic[lo] - 1) * 100)}% / 전 종목 동일가중 보유 {fmt(universe_hold(p, lo, hi))}%")
    if base_row:
        out.append(f"- 현행 전략(Top7 Regime, 순위 정렬) 같은 기간: 수익 {fmt(base_row['ret'])}%, 초과 {fmt(base_row['excess'])}%p, MDD {fmt(base_row['mdd'])}%")
    out.append("- 폴드: " + ", ".join(f"{p.dates[a]}~{p.dates[b]}" for a, b in fr))
    if si is not None:
        out.append(f"- '{p.dates[si]} 이후' 구간 지수 {fmt((ic[hi] / ic[si] - 1) * 100)}%")
    out.append("")
    out.append("### 규칙별 요약 (P3 × 레짐2 × ATR2 = 12개 평균)")
    out.append("| 규칙 | 평균 수익(%) | 평균 초과(%p) | 초과>0 설정 | 평균 MDD(%) | 평균 거래수 | 평균 승률(%) |")
    out.append("|---|---|---|---|---|---|---|")
    for rule in all_rules():
        vs = [v for c, v in res.items() if c[0] == rule]
        out.append(f"| {rule_label(rule)} | {fmt(np.mean([v['full']['ret'] for v in vs]))} | {fmt(np.mean([v['full']['excess'] for v in vs]))} | "
                   f"{sum(1 for v in vs if v['full']['excess'] > 0)}/{len(vs)} | {fmt(np.mean([v['full']['mdd'] for v in vs]))} | "
                   f"{np.mean([v['full']['n_trades'] for v in vs]):.0f} | {fmt(np.nanmean([v['full']['win'] for v in vs]), 0, False)} |")
    out.append("")
    out.append("### 레짐·ATR 효과 (96개 평균)")
    out.append("| 구분 | 평균 수익(%) | 평균 초과(%p) | 평균 MDD(%) |")
    out.append("|---|---|---|---|")
    for reg in REGS:
        vs = [v for c, v in res.items() if c[2] == reg]
        out.append(f"| 레짐 {reg} | {fmt(np.mean([v['full']['ret'] for v in vs]))} | {fmt(np.mean([v['full']['excess'] for v in vs]))} | {fmt(np.mean([v['full']['mdd'] for v in vs]))} |")
    for a in ATRS:
        vs = [v for c, v in res.items() if c[3] == a]
        out.append(f"| ATR 손절 {a} | {fmt(np.mean([v['full']['ret'] for v in vs]))} | {fmt(np.mean([v['full']['excess'] for v in vs]))} | {fmt(np.mean([v['full']['mdd'] for v in vs]))} |")
    out.append("")
    out.append("### 상위 20개 (초과수익 순)")
    out.append("| 규칙 | P | 레짐 | ATR | 수익(%) | 초과(%p) | MDD(%) | 거래 | 승률(%) | 폴드 초과(%p) | 이웃 평균(%p) | 이후 구간 수익(지수) | 통과 |")
    out.append("|---|---|---|---|---|---|---|---|---|---|---|---|---|")
    for cfg, v in sorted(res.items(), key=lambda kv: -kv[1]["full"]["excess"])[:20]:
        f = v["full"]
        sc = f"{fmt(v['since'][0])} ({fmt(v['since'][1])})" if v["since"] else "-"
        out.append(f"| {rule_label(cfg[0])} | {cfg[1]} | {cfg[2]} | {cfg[3]} | {fmt(f['ret'])} | {fmt(f['excess'])} | {fmt(f['mdd'])} | {f['n_trades']} | "
                   f"{fmt(f['win'], 0, False)} | {' / '.join(fmt(x) for x in v['folds'])} | {fmt(v['nb'])} | {sc} | {'✅' if passed(v, n_folds) else ''} |")
    ok = [(c, v) for c, v in res.items() if passed(v, n_folds)]
    out.append("")
    out.append(f"### 통과 후보: {len(ok)}개 / {len(res)}개")
    for c, v in sorted(ok, key=lambda kv: -kv[1]["full"]["excess"]):
        out.append(f"- {rule_label(c[0])} · P{c[1]} · 레짐 {c[2]} · ATR {c[3]}: 수익 {fmt(v['full']['ret'])}%, 초과 {fmt(v['full']['excess'])}%p, 폴드 {' / '.join(fmt(x) for x in v['folds'])}")
    if not ok:
        out.append("- 없음")
    return "\n".join(out)


def outlier_set(df, thr=0.30):
    piv = df.pivot_table(index="price_date", columns="ticker", values="close_price").sort_index()
    st = piv.pct_change().stack()
    bad = st[st.abs() > thr]
    return set(bad.index.get_level_values(1)) if len(bad) else set()


def main():
    sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
    import backtest as bt

    ap = argparse.ArgumentParser()
    ap.add_argument("--market", default="KR", choices=["KR", "US", "both"])
    ap.add_argument("--start", default="2026-01-02")
    ap.add_argument("--end", default="2026-12-31")
    ap.add_argument("--since", default="", help="하락장 이후 구간 평가 시작일 (예: 2026-05-01)")
    ap.add_argument("--folds", type=int, default=3)
    ap.add_argument("--drop_outliers", action="store_true")
    a = ap.parse_args()

    client = bt.get_client()
    parts = []
    for m in (["KR", "US"] if a.market == "both" else [a.market]):
        df, idx, names, sectors = bt.load_data(client, m, a.start, a.end)
        idx = idx[idx["close_price"] > 0].reset_index(drop=True)
        df = df.copy()
        df.loc[df["close_price"] <= 0, "close_price"] = np.nan
        df = df.dropna(subset=["close_price"])
        if a.drop_outliers:
            df = df[~df["ticker"].isin(outlier_set(df))]
        ex = fetch_extra(client, bt, idx["price_date"].tolist(), m)
        df = df.merge(ex, on=["price_date", "ticker"], how="left")
        cost = (0.1 + 0.1) / 100.0 if m == "KR" else (0.05 + 0.1) / 100.0
        p = build_panel(df, idx)
        res, lo, hi, fr, si = analyze(p, cost, a.folds, a.since or None)

        base_row = None
        try:
            d0 = p.dates[lo]
            i2 = idx[idx["price_date"] >= d0].reset_index(drop=True)
            d2 = df[df["price_date"] >= d0]
            capital = 20_000_000 if m == "KR" else 6000.0
            fee = 0.1 if m == "KR" else 0.05
            cfg = dict(capital=capital, fee_pct=fee, slip_pct=0.1, regime=True, idx200=True, sectors=sectors,
                       sort="rank", top_n=7, rank_cut=15, nextday=True)
            mt, _, _ = bt.simulate(d2, i2, names, cfg)
            c = i2["close_price"][i2["close_price"] > 0].dropna()
            base_row = dict(ret=mt["수익률(%)"], mdd=mt["MDD(%)"], excess=mt["수익률(%)"] - (c.iloc[-1] / c.iloc[0] - 1) * 100)
        except Exception as e:
            print(f"⚠️ 현행 전략 비교 실패: {e}")
        parts.append(report(res, p, lo, hi, fr, si, a.folds, base_row, m))

    md = "# Quant Alpha 5차 — 돈치안 돌파 / MA 골든크로스+20일선 돌파 (고정 후보 96개 · 다음날 종가 체결)\n\n" + "\n\n".join(parts) + """

### 해석 기준
- 통과 = 전체 초과수익 > 0, 폴드 n-1개 이상 초과수익 > 0, 이웃 설정 평균 초과수익 > 0
- 현행 전략 줄은 같은 기간·같은 비용으로 돌린 참고값이다. 후보가 현행과 지수를 모두 못 넘으면 채택할 이유가 없다.
- 평가 기간이 앞쪽 워밍업(최대 56일)을 뺀 약 5~8개월이라 거래 수가 적고 결론이 약하다. 통과해도 후보일 뿐이다.
> 과거 성과이며 미래를 보장하지 않습니다. 투자 조언이 아닙니다.
"""
    print(md)
    os.makedirs("research5_out", exist_ok=True)
    open("research5_out/summary.md", "w", encoding="utf-8").write(md)
    step = os.environ.get("GITHUB_STEP_SUMMARY")
    if step:
        with open(step, "a", encoding="utf-8") as f:
            f.write(md)


if __name__ == "__main__":
    main()
