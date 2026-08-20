import pandas as pd
import numpy as np
import warnings
warnings.filterwarnings('ignore')

# 1. 데이터 불러오기 (선생님의 실제 파일명으로 지정)
file_path = "20260102-0807_dailyAnalysis_KR_6.csv"
df = pd.read_csv(file_path, encoding='utf-8', on_bad_lines='skip')

# 컬럼명 정리 및 날짜, 숫자형 변환
df.columns = [c.replace('\\_', '_').strip() for c in df.columns]
df['price_date'] = pd.to_datetime(df['price_date'], errors='coerce')
df = df.dropna(subset=['price_date'])

num_cols = ['close_price', 'ma10', 'ma20', 'rs_score', 'rs_score_10', 'momentum_rank', 'high_price', 'low_price']
for c in num_cols:
    if c in df.columns:
        df[c] = pd.to_numeric(df[c], errors='coerce')

df = df.sort_values(['price_date', 'ticker'])

# 💡 이격도 계산 (가장 핵심적인 타이밍 지표)
df['disp_20'] = (df['close_price'] / df['ma20']) - 1

# ==========================================
# ⚙️ 2. 백테스트 환경 설정 (알파 시스템)
# ==========================================
SLIPPAGE = 0.003       # 매수/매도 시 각각 0.3% 불리하게 체결 (왕복 0.6%)
TOP_N = 3              # 포트폴리오 최대 편입 종목 수 (국장 기준)
SL = -0.06             # 고정 손절선 (-6%)
TRIG = 0.12            # 트레일링 스탑 트리거 (+12% 이상 상승 시)
STOP = -0.05           # 트레일링 스탑 익절선 (고점 대비 -5% 하락 시)
START_CASH = 100000000 # 초기 투자금 (1억 원)

dates = sorted(df['price_date'].unique())
portfolio = {} 
cash = START_CASH
trade_log = []
equity_curve = []
sold_history = {} # 쿨다운 체크용 (매도 후 3일)

# ==========================================
# 🔄 3. 일별 시뮬레이션 엔진 가동
# ==========================================
for dt in dates:
    daily_data = df[df['price_date'] == dt].drop_duplicates('ticker').set_index('ticker')
    
    # [현재 총 자산 계산]
    current_equity = cash
    for tk, pos in portfolio.items():
        if tk in daily_data.index:
            current_equity += pos['qty'] * daily_data.loc[tk, 'close_price']
        else:
            current_equity += pos['qty'] * pos['buy_price']
            
    # [매도 로직 평가]
    for tk, pos in list(portfolio.items()):
        if tk not in daily_data.index:
            continue
        row = daily_data.loc[tk]
        curr_price = row['close_price']
        curr_high = row['high_price'] if pd.notna(row['high_price']) else curr_price
        curr_low = row['low_price'] if pd.notna(row['low_price']) else curr_price
        
        # 고점 갱신
        if curr_high > pos['peak']:
            pos['peak'] = curr_high
            
        sell_price = None
        reason = ""
        
        # 1) 손절가 도달 (-6%)
        sl_price = pos['buy_price'] * (1 + SL)
        if curr_low <= sl_price:
            sell_price = sl_price * (1 - SLIPPAGE)
            reason = "Stop Loss"
        # 2) 트레일링 스탑 도달
        elif pos['peak'] >= pos['buy_price'] * (1 + TRIG):
            ts_price = pos['peak'] * (1 - abs(STOP))
            if curr_low <= ts_price:
                sell_price = ts_price * (1 - SLIPPAGE)
                reason = "Trailing Stop"
        # 3) 추세 이탈 (30위 밖 밀림 or MA20 하향 이탈)
        elif row['momentum_rank'] > 30 or curr_price < row['ma20']:
            sell_price = curr_price * (1 - SLIPPAGE)
            reason = "Trend Exit"
            
        if sell_price:
            cash += pos['qty'] * sell_price
            ret = (sell_price / pos['buy_price']) - 1
            trade_log.append({
                'ticker': tk, 'buy_date': pos['buy_date'], 'sell_date': dt,
                'buy_price': pos['buy_price'], 'sell_price': sell_price,
                'return': ret, 'reason': reason
            })
            sold_history[tk] = {'sell_date': dt, 'sell_price': sell_price}
            del portfolio[tk]
    
    # [매수 로직 평가]
    slots_available = TOP_N - len(portfolio)
    if slots_available > 0:
        # 필터링: 순위<=20 & RS(90, 10)>0 & MA20 위 (밴드 제한 없음)
        cond = (daily_data['momentum_rank'] <= 20) & \
               (daily_data['rs_score'] > 0) & \
               (daily_data['rs_score_10'] > 0) & \
               (daily_data['close_price'] > daily_data['ma20'])
        
        candidates = daily_data[cond].copy()
        
        # 💡 핵심 로직: 이격도 오름차순(가장 MA에 잘 붙은 종목) 최우선 정렬!
        candidates = candidates.sort_values(by=['disp_20', 'momentum_rank'], ascending=[True, True])
        
        for tk, row in candidates.iterrows():
            if len(portfolio) >= TOP_N:
                break
            if tk in portfolio:
                continue
                
            # 쿨다운 필터 (직전 매도가 재돌파 시에는 허용)
            if tk in sold_history:
                days_since_sell = (pd.to_datetime(dt) - pd.to_datetime(sold_history[tk]['sell_date'])).days
                if days_since_sell <= 3:
                    if row['close_price'] <= sold_history[tk]['sell_price']:
                        continue
                        
            # 슬리피지를 더하여 비싸게 매수
            buy_price = row['close_price'] * (1 + SLIPPAGE)
            
            # 자산 3등분 분산 매수
            buy_val = current_equity / TOP_N 
            buy_val = min(cash, buy_val)
            if buy_val < (current_equity * 0.1): 
                continue # 현금이 너무 적으면 패스
                
            qty = buy_val / buy_price
            cash -= buy_val
            portfolio[tk] = {'buy_price': buy_price, 'qty': qty, 'peak': buy_price, 'buy_date': dt}
            
    # [일마감 자산 기록]
    eod_equity = cash
    for tk, pos in portfolio.items():
        if tk in daily_data.index:
            eod_equity += pos['qty'] * daily_data.loc[tk, 'close_price']
        else:
            eod_equity += pos['qty'] * pos['buy_price']
    equity_curve.append({'date': dt, 'equity': eod_equity})

# ==========================================
# 📊 4. 결과 출력
# ==========================================
eq_df = pd.DataFrame(equity_curve)
eq_df['cum_max'] = eq_df['equity'].cummax()
eq_df['drawdown'] = eq_df['equity'] / eq_df['cum_max'] - 1
mdd = eq_df['drawdown'].min()
total_ret = (eq_df['equity'].iloc[-1] / eq_df['equity'].iloc[0]) - 1

trades_df = pd.DataFrame(trade_log)
if not trades_df.empty:
    win_rate = (trades_df['return'] > 0).mean()
    win_trades = trades_df[trades_df['return'] > 0]
    loss_trades = trades_df[trades_df['return'] <= 0]
    avg_win = win_trades['return'].mean() if not win_trades.empty else 0
    avg_loss = abs(loss_trades['return'].mean()) if not loss_trades.empty else 0
    pf = avg_win / avg_loss if avg_loss != 0 else np.inf
    
    print("=" * 40)
    print("🏆 [알파 시스템 최종 백테스트 결과] 🏆")
    print(f"기간: {eq_df['date'].min().date()} ~ {eq_df['date'].max().date()}")
    print(f"💰 누적 수익률 : {total_ret*100:.2f} %")
    print(f"📉 최악의 낙폭(MDD) : {mdd*100:.2f} %")
    print(f"⚖️ 손익비(PF) : {pf:.2f}")
    print(f"🎯 총 매매 횟수 : {len(trades_df)}회 (승률 {win_rate*100:.1f}%)")
    print("=" * 40)
    print("\n[매도(청산) 사유별 횟수]")
    print(trades_df['reason'].value_counts())
    
    eq_df['month'] = pd.to_datetime(eq_df['date']).dt.strftime('%Y-%m')
    monthly = eq_df.groupby('month').apply(lambda x: (x['equity'].iloc[-1] / x['equity'].iloc[0]) - 1)
    print("\n[📅 월별 수익률]")
    print((monthly * 100).apply(lambda x: f"{x:+.2f}%"))
else:
    print("해당 기간 동안 거래 내역이 발생하지 않았습니다.")
