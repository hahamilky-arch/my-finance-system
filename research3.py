"""3차 검증 — 청산 규칙 분해(ablation).

현행 Top7 틀(후보 순위≤15·RS>0·종가>MA20, 다음날 종가 체결, 비용 반영)에서 청산/진입 제약을 하나씩 빼서
어떤 규칙이 수익을 깎거나 도와주는지 본다. 정렬은 {모멘텀 순위, 이격도} × 보유수 {5,7,10}.

시나리오(사전 고정 8개): 기준 / ATR 손절 제거 / 트레일링 제거 / MA20 2일 이탈 청산 제거 /
  세 청산 모두 제거(레짐 청산만) / 재진입 쿨다운 제거 / 지수 MA200 금지 제거 / 지수 레짐 끔
판정: 평균 초과수익 변화(Δ)가 +3%p 이상이고, 보유수 3개 중 2개 이상과 구간 3개 중 2개 이상에서 개선되면 '제거가 도움'.
"""
import argparse
import os
import sys

import numpy as np
import pandas as pd

SCEN = [
    ("기준(현행)", {}),
    ("ATR 손절 제거", dict(exit_atr=False)),
    ("트레일링 제거", dict(exit_trail=False)),
    ("MA20 2일 이탈 청산 제거", dict(exit_ma20=False)),
    ("세 청산 모두 제거", dict(exit_atr=False, exit_trail=False, exit_ma20=False)),
    ("재진입 쿨다운 제거", dict(cooldown_days=0)),
    ("지수 MA200 금지 제거", dict(idx200=False)),
    ("지수 레짐 끔", dict(regime=False)),
]
SORTS = [("rank", "모멘텀순위"), ("gap", "이격도")]
NS = [5, 7, 10]


def fmt(x, d=1, sign=True):
    if x is None or (isinstance(x, float) and not np.isfinite(x)):
        return "-"
    return f"{x:+.{d}f}" if sign else f"{x:.{d}f}"


def run_market(bt, r2, df, idx, names, base, n_folds=3):
    fr = r2.fold_ranges(idx, n_folds)
    res = {}
    for sort, _ in SORTS:
        for sname, extra in SCEN:
            for n in NS:
                cfg = dict(base, sort=sort, top_n=n, rank_cut=15, nextday=True, **extra)
                m, _, _ = bt.simulate(df, idx, names, cfg)
                folds = []
                for a, b in fr:
                    d2, i2 = r2.slice_range(df, idx, a, b)
                    mf, _, _ = bt.simulate(d2, i2, names, cfg)
                    folds.append(r2.excess_of(mf, i2))
                res[(sort, sname, n)] = dict(ret=m["수익률(%)"], excess=r2.excess_of(m, idx), mdd=m["MDD(%)"], trades=m["거래수"], folds=folds)
    return res


def summarize(res):
    rows = []
    for sort, sl in SORTS:
        b = {n: res[(sort, "기준(현행)", n)] for n in NS}
        b_avg = np.mean([b[n]["excess"] for n in NS])
        b_fold = np.mean([b[n]["folds"] for n in NS], axis=0)
        for sname, _ in SCEN:
            r = {n: res[(sort, sname, n)] for n in NS}
            avg = np.mean([r[n]["excess"] for n in NS])
            fold = np.mean([r[n]["folds"] for n in NS], axis=0)
            n_better = sum(r[n]["excess"] > b[n]["excess"] for n in NS)
            f_better = int(np.sum(fold > b_fold))
            rows.append(dict(sort=sl, scen=sname, avg=avg, d=avg - b_avg, mdd=np.mean([r[n]["mdd"] for n in NS]),
                             ret=np.mean([r[n]["ret"] for n in NS]), n_better=n_better, f_better=f_better,
                             folds=fold, trades=np.mean([r[n]["trades"] for n in NS])))
    return rows


def report(markets):
    out = []
    for m, res in markets.items():
        rows = summarize(res)
        out.append(f"## {m} · 청산 규칙 분해 (보유 5/7/10 평균)")
        out.append("| 정렬 | 시나리오 | 평균 수익률 | 평균 초과 | 기준 대비 Δ | 평균 MDD | 평균 거래수 | 보유수 개선 | 구간별 평균 초과 | 구간 개선 | 판정 |")
        out.append("|" + "|".join(["---"] * 11) + "|")
        for r in rows:
            if r["scen"] == "기준(현행)":
                verdict = "기준"
            elif r["d"] >= 3 and r["n_better"] >= 2 and r["f_better"] >= 2:
                verdict = "제거가 도움"
            elif r["d"] <= -3 and r["n_better"] <= 1 and r["f_better"] <= 1:
                verdict = "규칙이 도움"
            else:
                verdict = "불분명"
            out.append(f"| {r['sort']} | {r['scen']} | {fmt(r['ret'])} | {fmt(r['avg'])} | {fmt(r['d'])} | {fmt(r['mdd'])} | {r['trades']:.0f} | {r['n_better']}/3 | "
                       + " / ".join(fmt(x) for x in r["folds"]) + f" | {r['f_better']}/3 | {verdict} |")
        out.append("")
    out.append("""### 해석 기준
- 'Δ'는 같은 정렬·보유수 평균에서 그 규칙만 뺐을 때 평균 초과수익이 얼마나 변하는지다. +면 규칙을 빼는 게 낫다.
- '제거가 도움'은 Δ≥+3%p, 보유수 3개 중 2개 이상, 구간 3개 중 2개 이상에서 모두 개선된 경우만 표시한다. 그 외는 '불분명'이므로 규칙을 바꾸지 않는다.
- 시나리오 8개는 사전 고정했고, 결과를 보고 추가하지 않는다. 약 1년 데이터라 한 번에 한 규칙만 바꿔야 한다.
> 과거 성과이며 미래를 보장하지 않습니다. 투자 조언이 아닙니다.""")
    return "\n".join(out)


def main():
    sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
    import backtest as bt
    import research2 as r2

    ap = argparse.ArgumentParser()
    ap.add_argument("--market", default="both", choices=["KR", "US", "both"])
    ap.add_argument("--start", default="2025-12-01")
    ap.add_argument("--end", default="2026-12-31")
    ap.add_argument("--folds", type=int, default=3)
    ap.add_argument("--drop_outliers", action="store_true")
    a = ap.parse_args()

    client = bt.get_client()
    markets, dq = {}, []
    for m in (["KR", "US"] if a.market == "both" else [a.market]):
        df, idx, names, sectors = bt.load_data(client, m, a.start, a.end)
        idx = idx[idx["close_price"] > 0].reset_index(drop=True)
        df = df.copy()
        df.loc[df["close_price"] <= 0, "close_price"] = np.nan
        df = df.dropna(subset=["close_price"])
        txt, bad = r2.outlier_check(df)
        dq.append(f"### 데이터 점검 · {m}\n{txt}\n- 이상치 종목 제외: {'예' if a.drop_outliers else '아니오'}")
        if a.drop_outliers and bad:
            df = df[~df["ticker"].isin(bad)]
        capital = 20_000_000 if m == "KR" else 6000.0
        fee = 0.1 if m == "KR" else 0.05
        base = dict(capital=capital, fee_pct=fee, slip_pct=0.1, regime=True, idx200=True, sectors=sectors)
        markets[m] = run_market(bt, r2, df, idx, names, base, a.folds)
    md = "# Quant Alpha 3차 검증 — 청산 규칙 분해 (다음날 종가 체결)\n\n" + "\n\n".join(dq) + "\n\n" + report(markets)
    print(md)
    os.makedirs("research3_out", exist_ok=True)
    open("research3_out/summary.md", "w", encoding="utf-8").write(md)
    step = os.environ.get("GITHUB_STEP_SUMMARY")
    if step:
        open(step, "a", encoding="utf-8").write(md)


if __name__ == "__main__":
    main()
