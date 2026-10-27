"""stocks.sector 채우기 (KR: FinanceDataReader 업종, US: yfinance GICS 섹터).

    python core/scraper/sector_sync.py --market ALL            # 비어 있는 종목만 채움
    python core/scraper/sector_sync.py --market KR --force     # 이미 값이 있어도 덮어씀
    python core/scraper/sector_sync.py --market US --dry_run   # DB 수정 없이 결과만 출력

환경변수: SUPABASE_URL, SUPABASE_KEY
"""
import argparse
import os
import sys
import time

import pandas as pd


def get_client():
    from supabase import create_client

    url, key = os.environ.get("SUPABASE_URL"), os.environ.get("SUPABASE_KEY")
    if not url or not key:
        sys.exit("SUPABASE_URL / SUPABASE_KEY 환경변수가 필요합니다.")
    return create_client(url, key)


def load_targets(client, market, force):
    rows, start = [], 0
    while True:
        res = client.table("stocks").select("ticker, name, sector, market").eq("market", market).range(start, start + 999).execute()
        data = res.data or []
        rows.extend(data)
        if len(data) < 1000:
            break
        start += 1000
    df = pd.DataFrame(rows)
    if df.empty:
        return df
    df["ticker"] = df["ticker"].astype(str).str.strip().str.upper()
    if not force:
        df = df[df["sector"].isna() | (df["sector"].astype(str).str.strip() == "")]
    return df.reset_index(drop=True)


def kr_sector_map():
    """{종목코드: 업종} — FinanceDataReader KRX-DESC(Sector/Industry) 우선, 실패 시 KRX(Sector/Dept)."""
    import FinanceDataReader as fdr

    for listing in ("KRX-DESC", "KRX"):
        try:
            d = fdr.StockListing(listing)
        except Exception as e:
            print(f"⚠️ fdr.StockListing('{listing}') 실패: {e}")
            continue
        code_col = next((c for c in ("Code", "Symbol") if c in d.columns), None)
        sec_cols = [c for c in ("Sector", "Industry", "Dept") if c in d.columns]
        if not code_col or not sec_cols:
            print(f"⚠️ '{listing}' 목록에 업종 컬럼이 없습니다: {list(d.columns)}")
            continue
        out = {}
        for _, r in d.iterrows():
            code = str(r[code_col]).strip().zfill(6)
            for c in sec_cols:
                v = r.get(c)
                if isinstance(v, str) and v.strip() and v.strip().lower() not in ("nan", "none"):
                    out[code] = v.strip()
                    break
        if out:
            print(f"✅ KR 업종 {len(out)}건 로드 (source={listing}, columns={sec_cols})")
            return out
    return {}


def us_sector(ticker, retries=3):
    import yfinance as yf

    sym = ticker.replace(".", "-")
    for attempt in range(retries):
        try:
            info = yf.Ticker(sym).info or {}
            sec = info.get("sector")
            if sec:
                return str(sec).strip()
            if str(info.get("quoteType", "")).upper() == "ETF":
                return "ETF"
            return None
        except Exception:
            time.sleep(1.5 * (attempt + 1))
    return None


def update_sector(client, ticker, sector, dry_run):
    if dry_run:
        return True
    try:
        client.table("stocks").update({"sector": sector}).eq("ticker", ticker).execute()
        return True
    except Exception as e:
        print(f"  ⚠️ {ticker} 저장 실패: {e}")
        return False


def run(market, force, dry_run):
    client = get_client()
    df = load_targets(client, market, force)
    print(f"\n=== {market}: 대상 {len(df)}종목 (force={force}, dry_run={dry_run}) ===")
    if df.empty:
        return
    ok, missing = 0, []
    if market == "KR":
        smap = kr_sector_map()
        for _, r in df.iterrows():
            sec = smap.get(r["ticker"].zfill(6))
            if sec and update_sector(client, r["ticker"], sec, dry_run):
                ok += 1
            else:
                missing.append(f"{r['ticker']}({r['name']})")
    else:
        for i, (_, r) in enumerate(df.iterrows(), 1):
            sec = us_sector(r["ticker"])
            if sec and update_sector(client, r["ticker"], sec, dry_run):
                ok += 1
            else:
                missing.append(r["ticker"])
            if i % 50 == 0:
                print(f"  … {i}/{len(df)}")
            time.sleep(0.25)
    print(f"✅ {market}: {ok}/{len(df)}종목 섹터 {'확인(미저장)' if dry_run else '저장'}")
    if missing:
        print(f"⚠️ 섹터를 찾지 못한 {len(missing)}종목: {', '.join(missing[:60])}{' …' if len(missing) > 60 else ''}")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--market", default="ALL", choices=["KR", "US", "ALL"])
    ap.add_argument("--force", action="store_true", help="이미 섹터가 있는 종목도 다시 채움")
    ap.add_argument("--dry_run", action="store_true")
    a = ap.parse_args()
    for m in (["KR", "US"] if a.market == "ALL" else [a.market]):
        run(m, a.force, a.dry_run)


if __name__ == "__main__":
    main()
