import os
import time
import pandas as pd
import streamlit as st
import google.generativeai as genai

# Gemini API 키 설정
GEMINI_API_KEY = st.secrets.get("GEMINI_API_KEY", "")
if GEMINI_API_KEY:
    genai.configure(api_key=GEMINI_API_KEY)

# 일일 AI 분석 제한 횟수 설정
MAX_DAILY_QUOTA = 50

def get_remaining_quota():
    """Gemini API 일일 사용량 및 잔여 횟수 계산 함수"""
    today_str = time.strftime("%Y-%m-%d")
    if "gemini_usage_date" not in st.session_state or st.session_state["gemini_usage_date"] != today_str:
        st.session_state["gemini_usage_date"] = today_str
        st.session_state["gemini_usage_count"] = 0
    
    used_count = st.session_state.get("gemini_usage_count", 0)
    remaining = max(0, MAX_DAILY_QUOTA - used_count)
    return used_count, remaining


_COMMON_RULES = """
[작성 원칙]
- 위에 제공된 데이터만 근거로 판단하고, 제공되지 않은 수치·뉴스·실적은 만들어내지 마라. 모르면 '데이터 없음'이라고 써라.
- 종목/섹터 분류처럼 데이터에 없는 배경지식은 '추정'이라고 표시하라.
- 투자 권유가 아니라 이 시스템(모멘텀 Top7 전략)의 신호를 해석하는 관점으로 쓴다.
- 가독성 높은 Markdown, 항목별 3~5줄 이내로 간결하게 작성하라.
"""


def _build_kr_market_prompt(m):
    return f"""
너는 대한민국 증시의 수급(외국인·기관·프로그램)과 주도주를 분석하는 퀀트 헤지펀드 매니저이다.
아래 데이터는 시스템이 계산한 KOSPI/KOSDAQ 시장 상태이다. 이를 바탕으로 시장 전체 흐름과 현재 전략 대응을 분석하라.

[시장 상태 · {m.get('조회일자', '-')}]
- 시스템 레짐: {m.get('시장상태', '-')} ({m.get('레짐', '-')})
- 코스피 지수: {m.get('지수현황', '-')}
- 시장 폭(전체 종목 중 이동평균선 위 비율): {m.get('시장폭', '-')}
- 보유 슬롯: {m.get('잔여슬롯', '-')} / 오늘 매수 추천: {m.get('추천종목수', '-')}

[수급 데이터]
- 비차익 Z-Score(20일): {m.get('비차익_ZScore_20일', '-')} / 비차익 5일 누적: {m.get('비차익_5일누적', '-')}
- KOSPI 외국인 5일 누적: {m.get('KOSPI_외인_5일누적', '-')} / 기관 5일 누적: {m.get('KOSPI_기관_5일누적', '-')}
- KOSDAQ 외국인 5일 누적: {m.get('KOSDAQ_외인_5일누적', '-')} / 기관 5일 누적: {m.get('KOSDAQ_기관_5일누적', '-')}
- 수급 괴리 신호: {m.get('다이버전스_신호', '-')}
- 최근 스마트머니(외국인+기관) 순매수 상위 종목: {m.get('수급상위주요종목', '-')}

[전략 신호 · 모멘텀 상위 종목]
{m.get('모멘텀상위', '-')}
- 오늘 매수 추천 종목: {m.get('추천종목명', '-')}

[분석 요구사항]
1. **시장 수급 진단**: 외국인·기관·비차익의 연속성을 근거로 '강한 유입 / 중립 / 이탈·경계' 중 하나로 판정하고, 코스피와 코스닥의 차이를 짚어라.
2. **지수·시장 폭과 수급의 일치 여부**: 지수 추세, 시장 폭, 수급이 같은 방향인지 괴리인지 평가하라.
3. **주도 섹터와 대표 종목**: 모멘텀 상위 종목과 수급 상위 종목에서 겹치는 산업 분야를 묶어 제시하라(섹터 분류는 추정 표기).
4. **전략 관점 대응**: 현재 레짐과 추천 종목을 고려해 '신규 진입 가능 / 선별 진입 / 관망' 중 무엇이 타당한지, 주의할 쏠림 위험과 함께 요약하라.
{_COMMON_RULES}"""


def _build_us_market_prompt(m):
    return f"""
너는 미국 주식 시장의 추세와 시장 내부 강도(breadth), 모멘텀 주도주를 분석하는 퀀트 헤지펀드 매니저이다.
미국 시장에는 한국식 수급(외국인·기관·비차익) 데이터가 없으므로, S&P 500 지수 추세·시장 폭·모멘텀 지표를 중심으로 분석하라.

[시장 상태 · {m.get('조회일자', '-')}]
- 시스템 레짐: {m.get('시장상태', '-')} ({m.get('레짐', '-')})
- S&P 500: {m.get('지수현황', '-')}
- 시장 폭(S&P 종목군 중 이동평균선 위 비율): {m.get('시장폭', '-')}
- 보유 슬롯: {m.get('잔여슬롯', '-')} / 오늘 매수 추천: {m.get('추천종목수', '-')}

[전략 신호 · 모멘텀 상위 종목 (순위, RS(90), MA20 이격)]
{m.get('모멘텀상위', '-')}
- 오늘 매수 추천 종목: {m.get('추천종목명', '-')}

[분석 요구사항]
1. **지수 추세 진단**: S&P 500의 20/50/200일선 대비 위치로 '상승 추세 / 조정 / 하락' 중 판정하고, 추세 전환 확인에 필요한 조건을 제시하라.
2. **시장 내부 강도 점검**: 지수와 시장 폭이 같은 방향인지(예: 지수는 약한데 폭은 양호, 또는 반대) 평가하고, 소수 대형주가 지수를 좌우하는지 가늠하라.
3. **모멘텀 상위 종목의 섹터 쏠림**: 상위 종목을 GICS 섹터로 분류(추정 표기)해 어느 섹터에 몰려 있는지 정리하고, 한 섹터 쏠림이 클 때의 위험(동반 급락, 갭하락)을 짚어라.
4. **전략 관점 대응**: 현재 레짐과 추천 종목을 고려해 '신규 진입 가능 / 선별 진입 / 관망'을 판단하고, 갭하락·실적 시즌 같은 미국장 특유의 위험을 체크리스트로 요약하라.
{_COMMON_RULES}"""



def analyze_stock_with_gemini(ticker, stock_name, stock_data, analysis_type="종합 기본적 분석"):
    """
    Gemini AI 모델을 사용하여 시장 수급 및 개별 종목 분석을 수행하는 함수
    """
    used_cnt, remain_cnt = get_remaining_quota()
    if remain_cnt <= 0:
        return "⚠️ 금일 Gemini AI 분석 허용 횟수(50회)를 모두 소모하였습니다. 내일 다시 시도해주세요."

    # 사용 횟수 증가
    st.session_state["gemini_usage_count"] = used_cnt + 1

    try:
        # 📌 1. 시장 전체 분석 프롬프트 (시장별: KR=수급 중심 / US=지수·시장 폭·모멘텀 중심)
        if analysis_type == "스마트머니 수급 분석":
            market_info = stock_data if isinstance(stock_data, dict) else {}
            if str(market_info.get("시장타입", "KR")).upper() == "US":
                prompt = _build_us_market_prompt(market_info)
            else:
                prompt = _build_kr_market_prompt(market_info)

        # 📌 2. 개별 종목 스마트머니 & 섹터 주도주 분석 프롬프트
        elif analysis_type == "스마트머니 & 섹터 주도주 분석":
            prompt = f"""
너는 주식 시장의 메이저 세력 수급과 산업 주도주를 정밀 분석하는 전문가이다.
대상 종목: [{stock_name} ({ticker})]

[종목 기술/수급 데이터]
- 종가: {stock_data.get('종가', '-')}
- 모멘텀 순위: {stock_data.get('순위', '-')}위
- Relative Strength (RS 90): {stock_data.get('RS(90)', '-')}
- 이격도: {stock_data.get('이격도', '-')}
- 제외/참고 사유: {stock_data.get('제외사유', '-')}

[분석 지침]
1. **해당 종목이 속한 산업 섹터 및 분야 정의**:
   - [{stock_name}]이 속한 핵심 산업 섹터와 현재 시장에서의 위치를 설명하라.
2. **섹터 내 주도주 여부 판정**:
   - 모멘텀 및 수급 데이터를 바탕으로 이 종목이 해당 분야의 '대장주/주도주'인지, 아니면 '후발 추종주'인지 평가하라.
3. **해당 분야 타 주도주와의 비교 및 수급 매력도**:
   - 동일 섹터 내 함께 주목해야 할 핵심 주도주 종목들을 언급하고, 본 종목의 투자 매력도를 결론으로 제시하라.
"""

        # 📌 3. ROE 듀퐁 분석 프롬프트
        elif analysis_type == "ROE 듀퐁 분석":
            prompt = f"""
[{stock_name} ({ticker})] 종목에 대해 ROE 듀퐁 분석(Dupont Analysis)을 수행하라.
- 순이익률 (Profit Margin)
- 자산회전율 (Asset Turnover)
- 재무레버리지 (Financial Leverage)
위 3가지 요소를 기반으로 이 종목의 수익성 구조와 자본 효율성을 상세히 평가하라.
"""

        # 📌 4. 사업 구조 분석 프롬프트
        elif analysis_type == "사업 구조":
            prompt = f"""
[{stock_name} ({ticker})] 종목의 핵심 사업 구조 및 매출 체계를 분석하라.
- 주력 제품/서비스 및 매출 비중
- 전방 산업의 성장성 및 주요 고객사
- 시장 점유율 및 경쟁 우위 요소(진입장벽)
"""

        # 📌 5. 퀀트 밸류에이션 프롬프트
        elif analysis_type == "퀀트 밸류에이션":
            prompt = f"""
[{stock_name} ({ticker})] 종목의 퀀트 밸류에이션 상태를 정밀 평가하라.
- 모멘텀 지표(RS 90, MOT)와 가격 이격도 분석
- 현재 주가 위치가 밸류에이션 상 부담스러운 구간인지, 기술적/수급적 저평가 구간인지 평가
- 적정 매수 타점 및 위험 관리 가격대 제안
"""

        # 📌 6. 단/중기 시나리오 프롬프트
        elif analysis_type == "단/중기 시나리오":
            prompt = f"""
[{stock_name} ({ticker})] 종목의 단기 및 중기 주가 대응 시나리오를 작성하라.
- 강세 시나리오 (상승 모멘텀 지속 시 목표가 및 관전 포인트)
- 약세 시나리오 (수급 이탈 또는 시장 조정 시 리스크 관리 손절선)
- 주요 매매 가이드라인
"""

        # 📌 7. 기본 종합 분석 프롬프트 (Default)
        else:
            prompt = f"""
[{stock_name} ({ticker})] 종목에 대한 종합 기본적/기술적 분석 리포트를 작성하라.
- 종가: {stock_data.get('종가', '-')}
- 모멘텀 순위: {stock_data.get('순위', '-')}위
- RS(90): {stock_data.get('RS(90)', '-')}

위 데이터를 바탕으로 종목의 현재 모멘텀, 기업 가치, 투자 유의점 및 최종 매매 제언을 간결하게 작성해라.
"""

        # 📌 gemini-3.6-flash 모델 단일 고정 호출
        model = genai.GenerativeModel("gemini-3.6-flash")
        response = model.generate_content(prompt)
        return response.text

    except Exception as e:
        return f"❌ Gemini AI 분석 중 오류가 발생했습니다: {str(e)}"
