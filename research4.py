"""4차 — 하락장 전용 단기 매매 탐색 (과매도 반등 중심, 사전 고정 후보).

질문: 지수가 MA20 아래(=현행 전략이 현금으로 대기하는 구간)에서도 플러스 수익을 내는 규칙이 있는가?

설계 (과최적화 방지)
- 하락장 정의 하나만 사용: 지수 종가 < 지수 MA20  (현행 앱 레짐과 동일)
- 후보는 코드에 고정: 8개 신호 × 보유일 {3,5,10} × 보유수 {5,10} = 48개. 결과를 보고 후보를 추가하지 않는다.
- 하락장일 때만 진입(신호일 종가 판단 → 다음 거래일 종가 체결), 보유일이 지나면 청산, 그 외 구간은 현금.
- 편도 비용(수수료+슬리피지) 반영, KR은 저가주(2천원 미만) 제외.
- 검증 장치
  1) 하락장 일수를 시간순 3분할(폴드)해 폴드별 수익 부호 확인
  2) 같은 조건(보유수·보유일·하락장 진입)의 무작위 종목 선택 대비 백분위
  3) 이웃 설정(보유일·보유수 한 칸 옆) 평균 수익
- 통과 = 전체 수익 > 0, 폴드 n-1개 이상 플러스, 무작위 백분위 ≥ 80, 이웃 평균 > 0
주의: 하락장 표본은 한 번의 장기 하락 에피소드라서 결론이 약하다. 통과해도 '후보'일 뿐이다.

실행: python research4.py --market KR --start 2026-01-02 --end 2026-12-31
"""
import argparse
import os
import sys

import numpy as np
import pandas as pd

SIGNALS = ["gap_low", "ret5_low", "drop20", "gap_low_q", "bounce", "capitulation", "lowvol_rs", "rs_strong"]
SIG_NAME = {
    "gap_low": "MA20 이격 최저(가장 눌림)",
    "ret5_low": "5일 수익률 최저",
    "drop20": "20일 고점 대비 낙폭 최대",
    "gap_low_q": "순위 100위 내 이격 최저(질 필터)",
    "bounce": "5일 낙폭 하위 + 당일 양봉(반등 확인)",
    "capitulation": "거래량 급증 + 5일 낙폭 하위",
    "lowvol_rs": "저변동(ATR/종가) + RS90>0 (방어)",
    "rs_strong": "RS90 최상위(상대강도 추종)",
}
HOLDS = [3, 5, 10]
NS = [5, 10]
N_SIMS = 100


class Panel:
    pass


def build_panel(df, idx, min_price):
    p = Panel()
    dates = [d for d in idx["price_date"].tolist() if d in set(df["price_date"])]
    p.dates = dates
    ix = idx.set_index("price_date").reindex(dates)
    p.idx_close = ix["close_price"].to_numpy(float)
    p.idx_ma20 = ix["ma20"].to_numpy(float)

    def piv(col):
        return df.pivot_table(index="price_date", columns="ticker", values=col).reindex(dates)

    C = piv("close_price")
    p.tickers = list(C.columns)
    p.C = C.to_numpy(float)
    p.R = np.nan_to_num(C.ffill(limit=5).pct_change().to_numpy(float), nan=0.0, posinf=0.0, neginf=0.0)
    p.rank = piv("momentum_rank").to_numpy(float)
    p.rs90 = piv("rs_score").to_numpy(float)
    p.ma20 = piv("ma20").to_numpy(float)
    p.atr = piv("atr").to_numpy(float)
    V = piv("volume") if "volume" in df.columns else pd.DataFrame(np.nan, index=dates, columns=p.tickers)
    p.volratio = (V / V.shift(1).rolling(20, min_periods=10).mean()).to_numpy(float)
    Cf = C.ffill(limit=5)
    p.ret5 = (Cf / Cf.shift(5) - 1).to_numpy(float)
    p.drop20 = (Cf / Cf.rolling(20, min_periods=10).max() - 1).to_numpy(float)
    p.min_price = min_price
    return p


def _pick(score, mask, n, ascending):
    s = np.where(mask & np.isfinite(score), score, np.nan)
    ok = np.where(np.isfinite(s))[0]
    if len(ok) == 0:
        return []
    order = ok[np.argsort(s[ok])]
    if not ascending:
        order = order[::-1]
    return list(order[:n])


def make_selector(sig, n, p):
    def sel(t):
        base = np.isfinite(p.C[t]) & (p.C[t] >= p.min_price) & (p.ma20[t] > 0)
        gap = p.C[t] / p.ma20[t] - 1
        if sig == "gap_low":
            return _pick(gap, base, n, True)
        if sig == "ret5_low":
            return _pick(p.ret5[t], base, n, True)
        if sig == "drop20":
            return _pick(p.drop20[t], base, n, True)
        if sig == "gap_low_q":
            return _pick(gap, base & (p.rank[t] <= 100), n, True)
        if sig == "bounce":
            r5 = p.ret5[t]
            ok = np.isfinite(r5)
            if ok.sum() < 10:
                return []
            cut = np.nanpercentile(r5[ok], 20)
            return _pick(r5, base & (r5 <= cut) & (p.R[t] > 0), n, True)
        if sig == "capitulation":
            r5 = p.ret5[t]
            ok = np.isfinite(r5)
            if ok.sum() < 10:
                return []
            cut = np.nanpercentile(r5[ok], 30)
            return _pick(p.volratio[t], base & (r5 <= cut), n, False)
        if sig == "lowvol_rs":
            return _pick(p.atr[t] / p.C[t], base & (p.rs90[t] > 0) & (p.atr[t] > 0), n, True)
        if sig == "rs_strong":
            return _pick(p.rs90[t], base, n, False)
        return []
    return sel


def make_random_selector(n, p, rng):
    def sel(t):
        base = np.where(np.isfinite(p.C[t]) & (p.C[t] >= p.min_price) & (p.ma20[t] > 0))[0]
        if len(base) <= n:
            return list(base)
        return list(rng.choice(base, n, replace=False))
    return sel


def run_bear(sel, H, p, lo, hi, cost, bear):
    """하락장(bear[t]) 신호일에만 진입. 신호일 종가 판단 → 다음 거래일 종가 체결 → H일 보유 후 종가 청산.
    반환: (일별 수익률 배열, 거래 수익률 리스트)"""
    n_t = p.C.shape[1]
    w = np.zeros(n_t)
    pending = None
    hold = 0
    rets, trades = [], []
    cur_trade = 1.0
    for t in range(lo, hi + 1):
        r = 0.0
        if w.any():
            r = float((w * p.R[t]).sum())
            if r > -0.999:
                w = w * (1 + p.R[t]) / (1 + r)
            cur_trade *= (1 + r)
            hold -= 1
            if hold <= 0:
                r -= cost * float(w.sum())
                cur_trade *= (1 - cost)
                trades.append(cur_trade - 1.0)
                w = np.zeros(n_t)
        if pending is not None:
            r -= cost
            w = pending
            hold = H
            pending = None
            cur_trade = 1 - cost
        rets.append(r)
        if (not w.any()) and pending is None and bear[t] and t < hi:
            pk = sel(t)
            if len(pk):
                nw = np.zeros(n_t)
                nw[pk] = 1.0 / len(pk)
                pending = nw
    return np.array(rets), trades


def curve_stats(rets, trades, p, lo, hi, bear):
    eq = np.cumprod(1 + rets)
    tot = (eq[-1] - 1) * 100
    peak = np.maximum.accumulate(eq)
    mdd = float(((eq - peak) / peak).min() * 100)
    idx_r = np.zeros(hi - lo + 1)
    for j, t in enumerate(range(lo, hi + 1)):
        if t > lo:
            idx_r[j] = p.idx_close[t] / p.idx_close[t - 1] - 1
    bmask = bear[lo:hi + 1]
    idx_bear = (np.prod(1 + idx_r[bmask]) - 1) * 100
    tr = np.array(trades) if trades else np.array([])
    return dict(
        ret=tot, mdd=mdd, idx_bear=idx_bear,
        n_trades=len(tr),
        win=float((tr > 0).mean() * 100) if len(tr) else np.nan,
        avg_trade=float(tr.mean() * 100) if len(tr) else np.nan,
    )


def fold_ranges(bear_days, n_folds):
    """하락장 일자를 시간순으로 n등분한 (시작일, 종료일) 인덱스 구간."""
    d = np.where(bear_days)[0]
    if len(d) < n_folds * 3:
        return []
    cuts = np.array_split(d, n_folds)
    return [(int(c[0]), int(c[-1])) for c in cuts]


def analyze(df, idx, market, cost, n_folds=3, n_sims=N_SIMS, since=None, min_price=0):
    p = build_panel(df, idx, min_price)
    T = len(p.dates)
    bear = (p.idx_ma20 > 0) & (p.idx_close < p.idx_ma20)
    lo = 0
    if since:
        cand = [i for i, d in enumerate(p.dates) if d >= since]
        lo = cand[0] if cand else 0
    hi = T - 1
    fr = fold_ranges(bear[lo:hi + 1], n_folds)
    fr = [(a + lo, b + lo) for a, b in fr]
    rng = np.random.default_rng(11)

    rows = []
    for sg in SIGNALS:
        for n in NS:
            for H in HOLDS:
                sel = make_selector(sg, n, p)
                rets, trades = run_bear(sel, H, p, lo, hi, cost, bear)
                full = curve_stats(rets, trades, p, lo, hi, bear)
                fm = []
                for a, b in fr:
                    r2, t2 = run_bear(sel, H, p, a, b, cost, bear)
                    fm.append(curve_stats(r2, t2, p, a, b, bear)["ret"])
                sims = []
                for _ in range(n_sims):
                    rr, tt = run_bear(make_random_selector(n, p, rng), H, p, lo, hi, cost, bear)
                    sims.append(curve_stats(rr, tt, p, lo, hi, bear)["ret"])
                pct = float((np.array(sims) < full["ret"]).mean() * 100)
                rows.append(dict(sig=sg, n=n, H=H, full=full, folds=fm, rand_pct=pct, rand_med=float(np.median(sims))))

    key = {(r["sig"], r["n"], r["H"]): r for r in rows}
    for r in rows:
        nb = []
        for dh in (-1, 1):
            j = HOLDS.index(r["H"]) + dh
            if 0 <= j < len(HOLDS):
                nb.append(key[(r["sig"], r["n"], HOLDS[j])]["full"]["ret"])
        for dn in (-1, 1):
            j = NS.index(r["n"]) + dn
            if 0 <= j < len(NS):
                nb.append(key[(r["sig"], NS[j], r["H"])]["full"]["ret"])
        r["nb"] = float(np.mean(nb))
    return dict(p=p, rows=rows, bear=bear, lo=lo, hi=hi, folds=fr)


def fmt(x, d=1, sign=True):
    if x is None or (isinstance(x, float) and not np.isfinite(x)):
        return "-"
    return f"{x:+.{d}f}" if sign else f"{x:.{d}f}"


def passed(r, n_folds):
    pos = sum(1 for x in r["folds"] if np.isfinite(x) and x > 0)
    need = max(1, n_folds - 1)
    return r["full"]["ret"] > 0 and len(r["folds"]) > 0 and pos >= need and r["rand_pct"] >= 80 and r["nb"] > 0


def report(res, market, n_folds):
    p, rows, bear, lo, hi, fr = res["p"], res["rows"], res["bear"], res["lo"], res["hi"], res["folds"]
    out = []
    d0, d1 = p.dates[lo], p.dates[hi]
    nb_days = int(bear[lo:hi + 1].sum())
    ic = p.idx_close
    out.append(f"## {market} · {d0} ~ {d1}")
    out.append(f"- 전체 {hi - lo + 1}거래일 중 하락장(지수<MA20) {nb_days}일 ({nb_days / (hi - lo + 1) * 100:.0f}%)")
    out.append(f"- 기간 지수 수익률 {(ic[hi] / ic[lo] - 1) * 100:+.1f}% / 하락장 일수만 이어붙인 지수 수익률 {rows[0]['full']['idx_bear']:+.1f}%")
    out.append("- 하락장 폴드(시간순): " + ", ".join(f"{p.dates[a]}~{p.dates[b]}" for a, b in fr) if fr else "- 하락장 폴드를 만들 일수가 부족합니다.")
    out.append("")
    out.append("### 신호별 요약 (6개 설정 평균)")
    out.append("| 신호 | 평균 수익(%) | 수익>0 설정 | 평균 거래당 수익(%) | 평균 무작위 백분위 | 평균 MDD(%) |")
    out.append("|---|---|---|---|---|---|")
    for s in SIGNALS:
        rr = [r for r in rows if r["sig"] == s]
        out.append(f"| {SIG_NAME[s]} | {fmt(np.mean([r['full']['ret'] for r in rr]))} | {sum(1 for r in rr if r['full']['ret'] > 0)}/{len(rr)} | "
                   f"{fmt(np.nanmean([r['full']['avg_trade'] for r in rr]), 2)} | {np.mean([r['rand_pct'] for r in rr]):.0f} | {fmt(np.mean([r['full']['mdd'] for r in rr]))} |")
    out.append("")
    out.append("### 전체 후보 (전체 수익 순, 상위 20)")
    out.append("| 신호 | 보유수 | 보유일 | 전체 수익(%) | MDD(%) | 거래 | 승률(%) | 거래당(%) | 폴드별 수익(%) | 무작위 백분위 | 이웃 평균(%) | 통과 |")
    out.append("|---|---|---|---|---|---|---|---|---|---|---|---|")
    for r in sorted(rows, key=lambda r: -r["full"]["ret"])[:20]:
        f = r["full"]
        out.append(f"| {r['sig']} | {r['n']} | {r['H']}일 | {fmt(f['ret'])} | {fmt(f['mdd'])} | {f['n_trades']} | {fmt(f['win'], 0, False)} | "
                   f"{fmt(f['avg_trade'], 2)} | {' / '.join(fmt(x, 1) for x in r['folds'])} | {r['rand_pct']:.0f} | {fmt(r['nb'])} | {'✅' if passed(r, n_folds) else ''} |")
    ok = [r for r in rows if passed(r, n_folds)]
    out.append("")
    out.append(f"### 통과 후보: {len(ok)}개 / {len(rows)}개")
    for r in sorted(ok, key=lambda r: -r["full"]["ret"]):
        out.append(f"- {SIG_NAME[r['sig']]} · 보유 {r['n']}종목 · {r['H']}일: 수익 {fmt(r['full']['ret'])}%, 폴드 {' / '.join(fmt(x, 1) for x in r['folds'])}, 무작위 {r['rand_pct']:.0f}백분위")
    if not ok:
        out.append("- 없음: 하락장 반등 매수 후보 중 검증 기준을 모두 넘은 규칙이 없다는 뜻이며, 현금 대기가 더 낫다는 근거가 된다.")
    return "\n".join(out)


def outlier_check(df, thr=0.30):
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
    ap.add_argument("--since", default="", help="이 날짜 이후만 평가 (예: 2026-05-01)")
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
            bad = outlier_check(df)
            df = df[~df["ticker"].isin(bad)]
        cost = (0.1 + 0.1) / 100.0 if m == "KR" else (0.05 + 0.1) / 100.0
        min_price = 2000 if m == "KR" else 3
        res = analyze(df, idx, m, cost, a.folds, since=a.since or None, min_price=min_price)
        parts.append(report(res, m, a.folds))
    md = "# Quant Alpha 4차 — 하락장 반등 매수 탐색 (고정 후보 48개 · 다음날 종가 체결)\n\n" + "\n\n".join(parts) + """

### 해석 기준
- 통과 = 전체 수익 > 0, 폴드 n-1개 이상 플러스, 무작위 선택 대비 80백분위 이상, 이웃 설정 평균 > 0
- 하락장 표본이 사실상 한 번의 장기 하락이라 폴드가 같은 국면의 일부일 뿐이다. 통과해도 소액·관찰용 후보로 본다.
- 수익은 하락장 진입 신호일에만 거래한 결과(나머지는 현금). 지수 수익률 비교는 '하락장 일수만 이어붙인' 값이다.
> 과거 성과이며 미래를 보장하지 않습니다. 투자 조언이 아닙니다.
"""
    print(md)
    os.makedirs("research4_out", exist_ok=True)
    open("research4_out/summary.md", "w", encoding="utf-8").write(md)
    step = os.environ.get("GITHUB_STEP_SUMMARY")
    if step:
        with open(step, "a", encoding="utf-8") as f:
            f.write(md)


if __name__ == "__main__":
    main()
