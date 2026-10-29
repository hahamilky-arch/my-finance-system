"""전략 탐색 (과최적화 방지 설계).

원칙
- 후보는 코드에 미리 고정한 소수(단순 규칙 7개 계열 × 보유수 2 × 교체주기 2 = 28개). 결과를 보고 후보를 추가하지 않는다.
- 현실적 체결: 신호일 다음 거래일 종가, 편도 비용(수수료+슬리피지) 반영, 지수 MA20 아래면 현금(레짐).
- 검증 3중 장치
  1) 기간 3분할(폴드)별 벤치마크 대비 초과수익 — 한 구간 운이 아닌지
  2) 워크포워드: 앞 구간에서 1등으로 뽑은 후보를 '뒤 구간'에서만 평가 (선택이 가치가 있었는지)
  3) 무작위 종목 선택(같은 보유수·교체주기·레짐) 200회 대비 백분위 — 종목 선택 규칙이 우연보다 나은지
- KR/US 모두에서 통과한 규칙만 '생존'으로 표시

실행: python research.py --market both --start 2025-01-01 --end 2026-12-31
"""
import argparse
import os
import sys

import numpy as np
import pandas as pd

N_SIMS = 200
FAMILIES = ["mom_rank", "rs90", "rs_accel", "pullback", "trend_q", "lowvol_mom", "vol_surge"]
HOLDS = [7, 15]
REBALS = [5, 10]


# ───────────────────────── 준비 ─────────────────────────
class Panel:
    pass


def build_panel(df, idx):
    p = Panel()
    dates = [d for d in idx["price_date"].tolist() if d in set(df["price_date"])]
    p.dates = dates
    ix = idx.set_index("price_date").reindex(dates)
    p.idx_close = ix["close_price"].to_numpy(float)
    p.idx_ma20 = ix["ma20"].to_numpy(float)
    p.regime = (p.idx_close >= p.idx_ma20) | ~(p.idx_ma20 > 0)

    def piv(col):
        return df.pivot_table(index="price_date", columns="ticker", values=col).reindex(dates)

    C = piv("close_price")
    p.tickers = list(C.columns)
    p.C = C.to_numpy(float)
    p.R = np.nan_to_num(C.pct_change().to_numpy(float), nan=0.0, posinf=0.0, neginf=0.0)
    p.rank = piv("momentum_rank").to_numpy(float)
    p.rs90 = piv("rs_score").to_numpy(float)
    p.rs10 = piv("rs_score_10").to_numpy(float)
    p.ma20 = piv("ma20").to_numpy(float)
    p.ma50 = piv("ma50").to_numpy(float)
    p.atr = piv("atr").to_numpy(float)
    p.vw = piv("vwma100").to_numpy(float) if "vwma100" in df.columns else np.full_like(p.C, np.nan)
    V = piv("volume") if "volume" in df.columns else pd.DataFrame(np.nan, index=dates, columns=p.tickers)
    p.volratio = (V / V.shift(1).rolling(20, min_periods=10).mean()).to_numpy(float)
    return p


def _top(score, mask, n, ascending=False):
    s = np.where(mask & np.isfinite(score), score, np.nan)
    ok = np.where(np.isfinite(s))[0]
    if len(ok) == 0:
        return []
    order = ok[np.argsort(s[ok])]
    if not ascending:
        order = order[::-1]
    return list(order[:n])


def make_selector(fam, n, p):
    def sel(t):
        base = np.isfinite(p.C[t]) & (p.ma20[t] > 0)
        top30 = base & (p.rank[t] <= 30)
        if fam == "mom_rank":
            return _top(p.rank[t], base, n, ascending=True)
        if fam == "rs90":
            return _top(p.rs90[t], base & (p.rs10[t] > 0), n)
        if fam == "rs_accel":
            return _top(p.rs10[t] - p.rs90[t], top30, n)
        if fam == "pullback":
            gap = p.C[t] / p.ma20[t] - 1
            return _top(gap, top30 & (p.C[t] > p.ma20[t]), n, ascending=True)
        if fam == "trend_q":
            m = top30 & (p.C[t] > p.ma50[t]) & (p.C[t] > p.vw[t])
            return _top(p.rs90[t], m, n)
        if fam == "lowvol_mom":
            return _top(p.atr[t] / p.C[t], top30 & (p.atr[t] > 0), n, ascending=True)
        if fam == "vol_surge":
            return _top(p.volratio[t], top30, n)
        return []
    return sel


def make_random_selector(n, p, rng):
    def sel(t):
        base = np.where(np.isfinite(p.C[t]) & (p.ma20[t] > 0))[0]
        if len(base) <= n:
            return list(base)
        return list(rng.choice(base, n, replace=False))
    return sel


# ───────────────────────── 엔진 ─────────────────────────
def run_curve(sel_fn, k, p, lo, hi, cost, use_regime=True):
    """lo..hi(포함) 구간 일별 수익률 배열. 신호일 종가 판단 → 다음 거래일 종가 체결."""
    n_t = p.C.shape[1]
    w = np.zeros(n_t)
    pending = None
    cur = []
    rets = []
    for t in range(lo, hi + 1):
        r = float((w * p.R[t]).sum()) if t > lo else 0.0
        if r > -0.999:
            w = w * (1 + p.R[t]) / (1 + r) if w.any() else w
        # 전일 신호 체결
        if pending is not None:
            neww = pending
            turn = float(np.abs(neww - w).sum())
            r -= turn * cost
            w = neww
            pending = None
        rets.append(r)
        # 오늘 신호
        if (t - lo) % k == 0:
            cur = sel_fn(t)
        target = cur if (not use_regime or p.regime[t]) else []
        if set(np.where(w > 0)[0]) != set(target):
            nw = np.zeros(n_t)
            if len(target):
                nw[list(target)] = 1.0 / len(target)
            pending = nw
    return np.array(rets)


def metrics(rets, p, lo, hi):
    eq = np.cumprod(1 + rets)
    tot = (eq[-1] - 1) * 100
    bench = (p.idx_close[hi] / p.idx_close[lo] - 1) * 100
    peak = np.maximum.accumulate(eq)
    mdd = float(((eq - peak) / peak).min() * 100)
    sd = rets.std()
    sharpe = float(rets.mean() / sd * np.sqrt(252)) if sd > 0 else 0.0
    return dict(ret=tot, bench=bench, excess=tot - bench, mdd=mdd, sharpe=sharpe,
                calmar=(tot / abs(mdd)) if mdd < 0 else np.nan)


def folds(n_days, n_folds):
    edges = np.linspace(0, n_days - 1, n_folds + 1).astype(int)
    return [(int(edges[i]), int(edges[i + 1])) for i in range(n_folds)]


# ───────────────────────── 분석 ─────────────────────────
def analyze_market(df, idx, market, cost, n_folds=3, n_sims=N_SIMS, seed=7):
    p = build_panel(df, idx)
    T = len(p.dates)
    fl = folds(T, n_folds)
    full = (0, T - 1)
    rng = np.random.default_rng(seed)

    rows = []  # 후보별 결과
    for fam in FAMILIES:
        for n in HOLDS:
            for k in REBALS:
                sel = make_selector(fam, n, p)
                rec = dict(name=f"{fam}|N{n}|R{k}", fam=fam, n=n, k=k)
                rec["full"] = metrics(run_curve(sel, k, p, *full, cost), p, *full)
                rec["folds"] = [metrics(run_curve(sel, k, p, a, b, cost), p, a, b) for a, b in fl]
                # 무작위 종목 선택 대비 백분위(전체 구간 초과수익)
                sims = []
                for _ in range(n_sims):
                    rs = make_random_selector(n, p, rng)
                    sims.append(metrics(run_curve(rs, k, p, *full, cost), p, *full)["excess"])
                rec["rand_pct"] = float((np.array(sims) < rec["full"]["excess"]).mean() * 100)
                rec["rand_med"] = float(np.median(sims))
                rows.append(rec)

    # 지수 + 레짐 기준선(종목 선택 없이 지수만 보유, MA20 아래면 현금)
    def idx_curve(a, b):
        r = np.zeros(b - a + 1)
        for j, t in enumerate(range(a, b + 1)):
            if t > a and p.regime[t - 1]:
                r[j] = p.idx_close[t] / p.idx_close[t - 1] - 1
        return r
    base_idx = dict(full=metrics(idx_curve(*full), p, *full), folds=[metrics(idx_curve(a, b), p, a, b) for a, b in fl])

    # 워크포워드: 이전 폴드 평균 초과수익 1등 → 다음 폴드에서만 평가
    wf = []
    for j in range(1, n_folds):
        prior = lambda r: np.mean([r["folds"][i]["excess"] for i in range(j)])
        best = max(rows, key=prior)
        oos_all = np.mean([r["folds"][j]["excess"] for r in rows])
        wf.append(dict(fold=j + 1, pick=best["name"], pick_prior=prior(best), oos=best["folds"][j]["excess"], oos_avg_all=oos_all))

    return dict(market=market, p=p, folds_idx=fl, rows=rows, base_idx=base_idx, wf=wf, T=T)


def survives(rec, n_folds):
    beat = sum(1 for f in rec["folds"] if f["excess"] > 0)
    return beat >= n_folds - 1 and rec["full"]["excess"] > 0 and rec["rand_pct"] >= 90


def fmt(x, d=1, sign=True):
    if x is None or (isinstance(x, float) and not np.isfinite(x)):
        return "-"
    return f"{x:+.{d}f}" if sign else f"{x:.{d}f}"


def report(results, n_folds):
    out = []
    surv = {}
    for res in results:
        m = res["market"]
        p = res["p"]
        out.append(f"## {m} · {p.dates[0]} ~ {p.dates[-1]} ({res['T']}영업일, 종목 {len(p.tickers)}개)")
        out.append(f"- 폴드 {n_folds}개: " + ", ".join(f"{p.dates[a]}~{p.dates[b]}({b - a}일)" for a, b in res["folds_idx"]))
        bf = res["base_idx"]
        out.append(f"- 지수 보유(벤치마크) {fmt(bf['full']['bench'])}% / 지수+레짐 현금화 {fmt(bf['full']['ret'])}% (MDD {fmt(bf['full']['mdd'])}%)\n")
        head = "| 후보 | 수익률 | 초과 | MDD | 칼마 | 폴드별 초과(%p) | 폴드통과 | 무작위대비 백분위 | 생존 |"
        out.append(head)
        out.append("|" + "|".join(["---"] * 9) + "|")
        for r in sorted(res["rows"], key=lambda r: -r["full"]["excess"]):
            beat = sum(1 for f in r["folds"] if f["excess"] > 0)
            s = survives(r, n_folds)
            surv.setdefault(r["name"], {})[m] = s
            out.append(
                f"| {r['name']} | {fmt(r['full']['ret'])} | {fmt(r['full']['excess'])} | {fmt(r['full']['mdd'])} | {fmt(r['full']['calmar'], 2, False)} | "
                + " / ".join(fmt(f["excess"]) for f in r["folds"])
                + f" | {beat}/{n_folds} | {r['rand_pct']:.0f}% | {'✅' if s else ''} |"
            )
        out.append("\n**워크포워드** (앞 구간 1등 후보를 뒤 구간에서만 평가)")
        out.append("| 평가 폴드 | 앞 구간에서 고른 후보 | 앞 구간 평균초과 | 뒤 구간 초과 | (참고) 전 후보 평균 뒤 구간 초과 |")
        out.append("|---|---|---|---|---|")
        for w in res["wf"]:
            out.append(f"| {w['fold']} | {w['pick']} | {fmt(w['pick_prior'])} | {fmt(w['oos'])} | {fmt(w['oos_avg_all'])} |")
        out.append("")
    if len(results) > 1:
        out.append("## KR/US 동시 생존 후보")
        both = [n for n, v in surv.items() if len(v) == len(results) and all(v.values())]
        out.append(("- " + "\n- ".join(both)) if both else "- 없음 (두 시장 모두에서 기준을 통과한 후보가 없습니다)")
    out.append("""
### 해석 기준
- 생존 = (폴드 중 n-1개 이상에서 벤치마크 초과) AND (전체 초과수익 > 0) AND (무작위 종목 선택 대비 90% 이상)
- 후보 28개를 비교했으므로 그중 최고는 운으로도 좋아 보일 수 있다. 워크포워드 '뒤 구간 초과'가 '전 후보 평균'보다 나을 때만 선택이 의미 있었다고 본다.
- 데이터가 짧으면(약 1년 이하) 구간 수가 적어 결론이 약하다. 생존 후보가 있어도 소액 실거래/페이퍼 트레이딩으로 추가 검증이 필요하다.
> 과거 성과이며 미래를 보장하지 않습니다. 투자 조언이 아닙니다.""")
    return "\n".join(out)


def main():
    sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
    import backtest as bt

    ap = argparse.ArgumentParser()
    ap.add_argument("--market", default="both", choices=["KR", "US", "both"])
    ap.add_argument("--start", default="2025-01-01")
    ap.add_argument("--end", default="2026-12-31")
    ap.add_argument("--folds", type=int, default=3)
    ap.add_argument("--sims", type=int, default=N_SIMS)
    a = ap.parse_args()

    client = bt.get_client()
    results = []
    for m in (["KR", "US"] if a.market == "both" else [a.market]):
        df, idx, names, sectors = bt.load_data(client, m, a.start, a.end)
        cost = (0.2 if m == "KR" else 0.15) / 100.0  # 편도 수수료+슬리피지
        results.append(analyze_market(df, idx, m, cost, a.folds, a.sims))
    md = "# Quant Alpha 전략 탐색 (후보 28개 · 다음날 종가 체결 · 지수 MA20 레짐)\n\n" + report(results, a.folds)
    print(md)
    os.makedirs("research_out", exist_ok=True)
    open("research_out/summary.md", "w", encoding="utf-8").write(md)
    step = os.environ.get("GITHUB_STEP_SUMMARY")
    if step:
        with open(step, "a", encoding="utf-8") as f:
            f.write(md)


if __name__ == "__main__":
    main()
