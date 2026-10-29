"""2차 검증 — 현행 전략 규칙 그대로(손절/트레일링/쿨다운/지수 MA200 금지, 다음 거래일 종가 체결)에서
'정렬 기준'만 바꿔 비교하고(A), 단순 순위 보유 전략은 설정을 넓게 흔들어 '고원(plateau)'이 있는지 본다(B).

사전 고정 후보
 A) 정렬 {이격도↑(현행), 모멘텀순위↑, RS90↓} × 보유수 {5,7,10} × 후보 순위컷 {15,30}  (+ 레짐 끔 참고 3개)
 B) {모멘텀순위, RS90} × 보유수 {5,7,10} × 교체주기 {5,10,15,20일} × 레짐 {없음, MA20, MA20 3일 이탈}
판정(통과): 전체 초과수익 > 0 AND 폴드 n-1개 이상 벤치마크 초과 AND 이웃 설정(보유수/주기/순위컷 한 칸 옆) 평균 초과수익 > 0
"""
import argparse
import os
import sys

import numpy as np
import pandas as pd


def excess_of(m, idx_slice):
    """벤치마크는 backtest.py 버전과 무관하게 지수 종가의 첫/마지막 유효값으로 직접 계산."""
    c = idx_slice["close_price"].dropna()
    if not m or len(c) < 2:
        return np.nan
    return m["수익률(%)"] - (c.iloc[-1] / c.iloc[0] - 1) * 100


def slice_range(df, idx, d0, d1):
    i2 = idx[(idx["price_date"] >= d0) & (idx["price_date"] <= d1)].reset_index(drop=True)
    d2 = df[(df["price_date"] >= d0) & (df["price_date"] <= d1)]
    return d2, i2


def fold_ranges(idx, n_folds):
    dates = idx["price_date"].tolist()
    edges = np.linspace(0, len(dates) - 1, n_folds + 1).astype(int)
    return [(dates[edges[i]], dates[edges[i + 1]]) for i in range(n_folds)]


def fmt(x, d=1, sign=True):
    if x is None or (isinstance(x, float) and not np.isfinite(x)):
        return "-"
    return f"{x:+.{d}f}" if sign else f"{x:.{d}f}"


# ───────────────────────── A: 현행 규칙 + 정렬 기준 ─────────────────────────
def part_a(bt, df, idx, names, base, n_folds):
    fr = fold_ranges(idx, n_folds)
    d_all = (idx["price_date"].iloc[0], idx["price_date"].iloc[-1])
    rows = []
    for sort in ["gap", "rank", "rs90"]:
        for n in [5, 7, 10]:
            for cut in [15, 30]:
                cfg = dict(base, sort=sort, top_n=n, rank_cut=cut, nextday=True)
                m, _, _ = bt.simulate(df, idx, names, cfg)
                fm = []
                for a, b in fr:
                    d2, i2 = slice_range(df, idx, a, b)
                    mf, _, _ = bt.simulate(d2, i2, names, cfg)
                    fm.append(excess_of(mf, i2))
                rows.append(dict(sort=sort, n=n, cut=cut, ret=m["수익률(%)"], excess=excess_of(m, idx), mdd=m["MDD(%)"],
                                 trades=m["거래수"], win=m["승률(%)"], folds=fm))
    ref = []
    for sort in ["gap", "rank", "rs90"]:
        cfg = dict(base, sort=sort, top_n=7, rank_cut=15, nextday=True, regime=False)
        m, _, _ = bt.simulate(df, idx, names, cfg)
        ref.append(dict(sort=sort, ret=m["수익률(%)"], excess=excess_of(m, idx), mdd=m["MDD(%)"]))
    # 이웃 평균(보유수, 순위컷 한 칸)
    ns, cuts = [5, 7, 10], [15, 30]
    key = {(r["sort"], r["n"], r["cut"]): r for r in rows}
    for r in rows:
        nb = []
        for dn in (-1, 1):
            j = ns.index(r["n"]) + dn
            if 0 <= j < len(ns):
                nb.append(key[(r["sort"], ns[j], r["cut"])]["excess"])
        for dc in (-1, 1):
            j = cuts.index(r["cut"]) + dc
            if 0 <= j < len(cuts):
                nb.append(key[(r["sort"], r["n"], cuts[j])]["excess"])
        r["nb"] = float(np.mean(nb))
    return rows, ref, d_all, fr


# ───────────────────────── B: 단순 순위 보유 · 고원 탐색 ─────────────────────────
def part_b(res_mod, df, idx, cost, n_folds):
    p = res_mod.build_panel(df, idx)
    T = len(p.dates)
    fl = res_mod.folds(T, n_folds)
    full = (0, T - 1)
    ic, im = p.idx_close, p.idx_ma20
    below = (im > 0) & (ic < im)
    below3 = below & np.roll(below, 1) & np.roll(below, 2)
    below3[:2] = False
    regimes = {"없음": np.ones(T, bool), "MA20": ~below, "MA20 3일 이탈": ~below3}
    ns, ks = [5, 7, 10], [5, 10, 15, 20]
    out = []
    for fam in ["mom_rank", "rs90"]:
        for rg, arr in regimes.items():
            p.regime = arr
            for n in ns:
                sel = res_mod.make_selector(fam, n, p)
                for k in ks:
                    f = res_mod.metrics(res_mod.run_curve(sel, k, p, *full, cost), p, *full)
                    fm = [res_mod.metrics(res_mod.run_curve(sel, k, p, a, b, cost), p, a, b)["excess"] for a, b in fl]
                    out.append(dict(fam=fam, rg=rg, n=n, k=k, ret=f["ret"], excess=f["excess"], mdd=f["mdd"], folds=fm))
    key = {(r["fam"], r["rg"], r["n"], r["k"]): r for r in out}
    for r in out:
        nb = []
        for dn in (-1, 1):
            j = ns.index(r["n"]) + dn
            if 0 <= j < len(ns):
                nb.append(key[(r["fam"], r["rg"], ns[j], r["k"])]["excess"])
        for dk in (-1, 1):
            j = ks.index(r["k"]) + dk
            if 0 <= j < len(ks):
                nb.append(key[(r["fam"], r["rg"], r["n"], ks[j])]["excess"])
        r["nb"] = float(np.mean(nb))
    return out, p, fl


def passed(r, n_folds):
    beat = sum(1 for x in r["folds"] if np.isfinite(x) and x > 0)
    return r["excess"] > 0 and beat >= n_folds - 1 and r["nb"] > 0


SORT_NAME = {"gap": "이격도↑(현행)", "rank": "모멘텀순위↑", "rs90": "RS90↓"}


def report(markets, n_folds):
    out = []
    pass_a, pass_b = {}, {}
    for m, (A, B) in markets.items():
        rows, ref, d_all, fr = A
        bout, p, fl = B
        out.append(f"## {m} · {d_all[0]} ~ {d_all[1]}")
        out.append("### A. 현행 규칙(손절·트레일링·쿨다운·MA200 금지, 다음날 종가) + 정렬 기준 비교")
        out.append("**정렬 기준별 요약** (보유수 3 × 순위컷 2 = 6개 설정)")
        out.append("| 정렬 | 평균 초과(%p) | 초과>0 설정 | 평균 MDD | 평균 수익률 |")
        out.append("|---|---|---|---|---|")
        for s in ["gap", "rank", "rs90"]:
            rr = [r for r in rows if r["sort"] == s]
            out.append(f"| {SORT_NAME[s]} | {fmt(np.mean([r['excess'] for r in rr]))} | {sum(r['excess'] > 0 for r in rr)}/{len(rr)} | "
                       f"{fmt(np.mean([r['mdd'] for r in rr]))} | {fmt(np.mean([r['ret'] for r in rr]))} |")
        out.append("\n**전체 설정**")
        out.append("| 정렬 | 보유 | 순위컷 | 수익률 | 초과 | MDD | 거래수 | 승률 | 폴드별 초과 | 이웃평균 | 통과 |")
        out.append("|" + "|".join(["---"] * 11) + "|")
        for r in rows:
            ok = passed(r, n_folds)
            pass_a.setdefault((r["sort"], r["n"], r["cut"]), {})[m] = ok
            out.append(f"| {SORT_NAME[r['sort']]} | {r['n']} | ≤{r['cut']} | {fmt(r['ret'])} | {fmt(r['excess'])} | {fmt(r['mdd'])} | {r['trades']} | {r['win']:.0f}% | "
                       + " / ".join(fmt(x) for x in r["folds"]) + f" | {fmt(r['nb'])} | {'✅' if ok else ''} |")
        out.append("\n참고(지수 레짐 끔, 보유 7·순위≤15): " + ", ".join(f"{SORT_NAME[x['sort']]} {fmt(x['ret'])}% (초과 {fmt(x['excess'])}, MDD {fmt(x['mdd'])})" for x in ref))

        out.append("\n### B. 단순 순위 보유 전략 · 설정 고원 탐색 (72개)")
        out.append("| 계열 | 레짐 | 설정 평균 초과 | 초과>0 비율 | 통과 개수 |")
        out.append("|---|---|---|---|---|")
        for fam in ["mom_rank", "rs90"]:
            for rg in ["없음", "MA20", "MA20 3일 이탈"]:
                rr = [r for r in bout if r["fam"] == fam and r["rg"] == rg]
                out.append(f"| {fam} | {rg} | {fmt(np.mean([r['excess'] for r in rr]))} | {sum(r['excess'] > 0 for r in rr)}/{len(rr)} | {sum(passed(r, n_folds) for r in rr)} |")
        out.append("\n**통과 설정**")
        ps = [r for r in bout if passed(r, n_folds)]
        if ps:
            out.append("| 계열 | 레짐 | 보유 | 주기 | 수익률 | 초과 | MDD | 폴드별 초과 | 이웃평균 |")
            out.append("|" + "|".join(["---"] * 9) + "|")
            for r in sorted(ps, key=lambda r: -r["excess"]):
                out.append(f"| {r['fam']} | {r['rg']} | {r['n']} | {r['k']}일 | {fmt(r['ret'])} | {fmt(r['excess'])} | {fmt(r['mdd'])} | " + " / ".join(fmt(x) for x in r["folds"]) + f" | {fmt(r['nb'])} |")
        else:
            out.append("- 없음")
        for r in bout:
            pass_b.setdefault((r["fam"], r["rg"], r["n"], r["k"]), {})[m] = passed(r, n_folds)
        out.append(f"\n(지수 보유 벤치마크 {fmt((p.idx_close[-1] / p.idx_close[0] - 1) * 100)}%)\n")

    if len(markets) > 1:
        out.append("## KR/US 동시 통과")
        ba = [k for k, v in pass_a.items() if len(v) == len(markets) and all(v.values())]
        bb = [k for k, v in pass_b.items() if len(v) == len(markets) and all(v.values())]
        out.append("- A(현행 규칙): " + (", ".join(f"{SORT_NAME[s]}·보유{n}·≤{c}" for s, n, c in ba) if ba else "없음"))
        out.append("- B(단순 순위 보유): " + (", ".join(f"{f}·{rg}·보유{n}·{k}일" for f, rg, n, k in bb) if bb else "없음"))
    out.append("""
### 해석 기준
- 통과 = 전체 초과수익 > 0, 폴드 중 n-1개 이상 벤치마크 초과, 이웃 설정(보유수/주기/순위컷 한 칸 옆) 평균 초과수익 > 0
- 이웃 평균이 음수면 한 점만 튀어나온 설정이라 과최적화 가능성이 높다. '정렬 기준별 요약'의 평균이 설정 하나의 우승보다 더 믿을 만한 비교다.
- 총 설정 수: A 18(+참고 3) + B 72. 기간이 짧으면(약 1년) 결론이 약하다.
> 과거 성과이며 미래를 보장하지 않습니다. 투자 조언이 아닙니다.""")
    return "\n".join(out)


def outlier_check(df, thr=0.30):
    """일간 등락 ±thr 초과 관측(분할/단위 오류 의심) 목록과 해당 종목 집합."""
    piv = df.pivot_table(index="price_date", columns="ticker", values="close_price").sort_index()
    ret = piv.pct_change()
    st = ret.stack()
    bad = st[st.abs() > thr].sort_values(key=lambda x: -x.abs())
    lines = [f"- 일간 ±{thr * 100:.0f}% 초과 관측 {len(bad)}건, 종목 {bad.index.get_level_values(1).nunique() if len(bad) else 0}개"]
    for (d, t), v in bad.head(15).items():
        lines.append(f"  - {t} {d} {v * 100:+.0f}%")
    return "\n".join(lines), set(bad.index.get_level_values(1)) if len(bad) else set()


def main():
    sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
    import backtest as bt
    import research as rs

    ap = argparse.ArgumentParser()
    ap.add_argument("--market", default="both", choices=["KR", "US", "both"])
    ap.add_argument("--start", default="2025-01-01")
    ap.add_argument("--end", default="2026-12-31")
    ap.add_argument("--folds", type=int, default=3)
    ap.add_argument("--drop_outliers", action="store_true", help="일간 ±30% 초과 변동이 있는 종목을 제외하고 분석")
    a = ap.parse_args()

    client = bt.get_client()
    markets = {}
    dq = []
    for m in (["KR", "US"] if a.market == "both" else [a.market]):
        df, idx, names, sectors = bt.load_data(client, m, a.start, a.end)
        n_zero = int((df["close_price"] <= 0).sum())
        if n_zero:
            zt = df.loc[df["close_price"] <= 0, "ticker"].nunique()
            df = df.copy()
            df.loc[df["close_price"] <= 0, "close_price"] = np.nan  # 0원 종가는 데이터 결측으로 처리
            df = df.dropna(subset=["close_price"])
            dq.append(f"### 0원 종가 정리 · {m}\n- 종가 0 이하 {n_zero}건(종목 {zt}개)을 결측으로 제거")
        txt, bad_t = outlier_check(df)
        dq.append(f"### 데이터 점검 · {m}\n{txt}" + (f"\n- 해당 종목 제외하고 분석: {'예' if a.drop_outliers else '아니오'}" if bad_t else ""))
        if a.drop_outliers and bad_t:
            df = df[~df["ticker"].isin(bad_t)]
        capital = 20_000_000 if m == "KR" else 6000.0
        fee = 0.1 if m == "KR" else 0.05
        base = dict(capital=capital, fee_pct=fee, slip_pct=0.1, regime=True, idx200=True, sectors=sectors)
        A = part_a(bt, df, idx, names, base, a.folds)
        B = part_b(rs, df, idx, (fee + 0.1) / 100.0, a.folds)
        markets[m] = (A, B)
    md = "# Quant Alpha 2차 검증 (고정 후보 · 다음날 종가 체결)\n\n" + "\n\n".join(dq) + "\n\n" + report(markets, a.folds)
    print(md)
    os.makedirs("research2_out", exist_ok=True)
    open("research2_out/summary.md", "w", encoding="utf-8").write(md)
    step = os.environ.get("GITHUB_STEP_SUMMARY")
    if step:
        with open(step, "a", encoding="utf-8") as f:
            f.write(md)


if __name__ == "__main__":
    main()
