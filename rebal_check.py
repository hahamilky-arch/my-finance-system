"""후보 전략 확인: RS90 상위 N종목 · R일마다 교체 · 지수 MA20 3일 연속 이탈 시 현금 (다음 거래일 종가 체결).

2차 검증에서 KR/US 모두 통과한 후보를 같은 가정으로 더 넓게 확인한다.
- 교체주기를 격자 끝값(20일)을 넘어 15/20/25/30일까지, 보유수 5/7/10
- 비용 1배 / 2배 민감도, 기간 3분할·4분할 폴드
- 지수 보유 대비 초과수익, MDD, 오늘 기준 보유 후보(페이퍼 트레이딩용)
실행: python rebal_check.py --market both --start 2025-12-01 --drop_outliers
"""
import argparse
import os
import sys

import numpy as np
import pandas as pd

NS = [5, 7, 10]
RS_ = [15, 20, 25, 30]


def fmt(x, d=1, sign=True):
    if x is None or (isinstance(x, float) and not np.isfinite(x)):
        return "-"
    return f"{x:+.{d}f}" if sign else f"{x:.{d}f}"


def analyze(rs, p, cost_base):
    T = len(p.dates)
    below = (p.idx_ma20 > 0) & (p.idx_close < p.idx_ma20)
    b3 = below & np.roll(below, 1) & np.roll(below, 2)
    b3[:2] = False
    p.regime = ~b3
    full = (0, T - 1)
    out = []
    for n in NS:
        sel = rs.make_selector("rs90", n, p)
        for r in RS_:
            rec = dict(n=n, r=r)
            for tag, mult in (("c1", 1.0), ("c2", 2.0)):
                rec[tag] = rs.metrics(rs.run_curve(sel, r, p, *full, cost_base * mult), p, *full)
            rec["f3"] = [rs.metrics(rs.run_curve(sel, r, p, a, b, cost_base), p, a, b)["excess"] for a, b in rs.folds(T, 3)]
            rec["f4"] = [rs.metrics(rs.run_curve(sel, r, p, a, b, cost_base), p, a, b)["excess"] for a, b in rs.folds(T, 4)]
            out.append(rec)
    key = {(r["n"], r["r"]): r for r in out}
    for r in out:
        nb = []
        for dn in (-1, 1):
            j = NS.index(r["n"]) + dn
            if 0 <= j < len(NS):
                nb.append(key[(NS[j], r["r"])]["c1"]["excess"])
        for dr in (-1, 1):
            j = RS_.index(r["r"]) + dr
            if 0 <= j < len(RS_):
                nb.append(key[(r["n"], RS_[j])]["c1"]["excess"])
        r["nb"] = float(np.mean(nb))
    return out


def current_picks(rs, p, n, names):
    sel = rs.make_selector("rs90", n, p)
    t = len(p.dates) - 1
    picks = sel(t)
    rows = []
    for i in picks:
        tk = p.tickers[i]
        rows.append(f"{tk} {names.get(tk, '')} (RS90 {p.rs90[t][i]:.2f}, 순위 {int(p.rank[t][i]) if np.isfinite(p.rank[t][i]) else '-'})")
    return p.dates[t], bool(p.regime[t]), rows


def main():
    sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
    import backtest as bt
    import research as rs
    import research2 as r2

    ap = argparse.ArgumentParser()
    ap.add_argument("--market", default="both", choices=["KR", "US", "both"])
    ap.add_argument("--start", default="2025-12-01")
    ap.add_argument("--end", default="2026-12-31")
    ap.add_argument("--drop_outliers", action="store_true")
    a = ap.parse_args()

    client = bt.get_client()
    md = ["# RS90 상위 보유 · 주기 교체 · 지수 MA20 3일 이탈 현금 — 후보 확인 (다음날 종가 체결)\n"]
    for m in (["KR", "US"] if a.market == "both" else [a.market]):
        df, idx, names, sectors = bt.load_data(client, m, a.start, a.end)
        idx = idx[idx["close_price"] > 0].reset_index(drop=True)
        df = df.copy()
        df.loc[df["close_price"] <= 0, "close_price"] = np.nan
        df = df.dropna(subset=["close_price"])
        txt, bad = r2.outlier_check(df)
        md.append(f"### 데이터 점검 · {m}\n{txt}\n- 이상치 종목 제외: {'예' if a.drop_outliers else '아니오'}")
        if a.drop_outliers and bad:
            df = df[~df["ticker"].isin(bad)]
        p = rs.build_panel(df, idx)
        cost = (0.2 if m == "KR" else 0.15) / 100.0
        res = analyze(rs, p, cost)
        bench = (p.idx_close[-1] / p.idx_close[0] - 1) * 100
        md.append(f"\n## {m} · {p.dates[0]} ~ {p.dates[-1]} ({len(p.dates)}영업일) · 지수 보유 {fmt(bench)}%")
        md.append("| 보유 | 교체주기 | 수익률 | 초과 | MDD | 칼마 | 비용2배 초과 | 3분할 초과 | 4분할 초과 | 이웃평균 |")
        md.append("|" + "|".join(["---"] * 10) + "|")
        for r in res:
            md.append(f"| {r['n']} | {r['r']}일 | {fmt(r['c1']['ret'])} | {fmt(r['c1']['excess'])} | {fmt(r['c1']['mdd'])} | {fmt(r['c1']['calmar'], 2, False)} | "
                      f"{fmt(r['c2']['excess'])} | " + " / ".join(fmt(x) for x in r["f3"]) + " | " + " / ".join(fmt(x) for x in r["f4"]) + f" | {fmt(r['nb'])} |")
        pos = [r for r in res if r["c1"]["excess"] > 0]
        pos2 = [r for r in res if r["c2"]["excess"] > 0]
        md.append(f"\n- 초과수익 > 0: {len(pos)}/{len(res)}개 (비용 2배에서도 > 0: {len(pos2)}개)")
        md.append(f"- 폴드 3분할 중 2곳 이상 초과: {sum(1 for r in res if sum(x > 0 for x in r['f3']) >= 2)}개 / 4분할 중 3곳 이상: {sum(1 for r in res if sum(x > 0 for x in r['f4']) >= 3)}개")
        d, ok, rows = current_picks(rs, p, 7, names)
        md.append(f"\n**{d} 기준 이 전략의 보유 후보 (보유 7종목, 지수 레짐 {'정상' if ok else '약세 → 현금'})**")
        md.extend(["- " + x for x in rows] or ["- 없음"])
        md.append("")
    md.append("""### 해석 기준
- 교체주기 15~30일 전 구간에서 초과수익이 대부분 플러스이고 비용 2배에서도 유지되면 '고원'으로 본다. 20일에서만 좋으면 우연 가능성이 크다.
- 4분할 폴드는 구간이 짧아 흔들린다. 3분할과 같이 일관된지 본다.
- 보유 후보 목록은 페이퍼 트레이딩 비교용이며 매수 권유가 아니다.
> 과거 성과이며 미래를 보장하지 않습니다. 투자 조언이 아닙니다.""")
    text = "\n".join(md)
    print(text)
    os.makedirs("rebal_out", exist_ok=True)
    open("rebal_out/summary.md", "w", encoding="utf-8").write(text)
    step = os.environ.get("GITHUB_STEP_SUMMARY")
    if step:
        open(step, "a", encoding="utf-8").write(text)


if __name__ == "__main__":
    main()
