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
        model = genai.GenerativeModel("gemini-1.5-flash")

        # 📌 1. 시장 전체 스마트머니 수급 & 주도 섹터/주도주 분석 프롬프트
        if analysis_type == "스마트머니 수급 분석":
            market_info = stock_data if isinstance(stock_data, dict) else {}
            
            prompt = f"""
너는 대한민국 증시의 스마트머니(외국인, 기관, 메이저 세력) 자금 흐름과 주도주를 정밀 분석하는 최고 수준의 퀀트 헤지펀드 매니저이다.
아래 제공된 국내 증시 전체의 수급 지표와 최근 스마트머니 상위 집결 종목 데이터를 바탕으로 시장 전체의 자금 이동 및 주도 섹터/주도주를 분석하라.

[수집된 시장 전체 수급 데이터]
- 조회일자: {market_info.get('조회일자', '-')}
- 비차익 Z-Score (20일 기준): {market_info.get('비차익_ZScore_20일', '-')}
- 최근 5일 비차익 순매수 누적: {market_info.get('비차익_5일누적', '-')}
- KOSPI 외국인 5일 누적: {market_info.get('KOSPI_외인_5일누적', '-')}
- KOSPI 기관 5일 누적: {market_info.get('KOSPI_기관_5일누적', '-')}
- KOSDAQ 외국인 5일 누적: {market_info.get('KOSDAQ_외인_5일누적', '-')}
- KOSDAQ 기관 5일 누적: {market_info.get('KOSDAQ_기관_5일누적', '-')}
- 최근 20일 스마트머니 집중 상위 종목: {market_info.get('시장_스마트머니_집중_상위종목', '-')}
- 수급 다이버전스/특이사항: {market_info.get('다이버전스_신호', '-')}

[분석 요구사항 및 지침]
1. **시장 전체 스마트머니 자금 흐름 평가**:
   - 외국인, 기관, 비차익 프로그램 매수세의 연속성을 바탕으로 현재 시장 전체 수급이 '강한 유입', '중립', '이탈/경계' 중 어느 상태인지 진단하라.

2. **주도 섹터/분야 및 해당 분야의 핵심 주도주 도출 (★매우 중요★)**:
   - 스마트머니 자금이 유입되는 핵심 산업 분야/섹터(예: 반도체, AI/IT, 제약/바이오, 2차전지, 자동차, 조선 등)를 명확히 제시하라.
   - **각 분야/섹터별로 시장 자금을 이끌고 있는 대표 주도주 종목(대장주 및 수급 집중 종목)을 구체적으로 명시하라.**

3. **투자 전략 및 포트폴리오 비중 가이드**:
   - 현재 시장 수급 상태에 맞는 포트폴리오 대응 전략(공격적 진입 / 차별화된 주도주 매수 / 관망 및 위험 관리)을 직관적인 Bullet Point로 요약하라.

답변은 가독성이 높고 명확한 Markdown 양식으로 작성해라.
"""

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

        response = model.generate_content(prompt)
        return response.text

    except Exception as e:
        return f"❌ Gemini AI 분석 중 오류가 발생했습니다: {str(e)}"
