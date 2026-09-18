# gemini_analyzer.py

import os
import google.generativeai as genai
import streamlit as st

# Gemini API 설정 (secrets에서 키 로드)
API_KEY = st.secrets.get("GEMINI_API_KEY", "")
if API_KEY:
    genai.configure(api_key=API_KEY)

MAX_DAILY_QUOTA = 50

def get_remaining_quota():
    # 사용량 세션 상태 관리 (필요 시 세션 초기화)
    if 'gemini_used_count' not in st.session_state:
        st.session_state['gemini_used_count'] = 0
    used = st.session_state['gemini_used_count']
    return used, max(0, MAX_DAILY_QUOTA - used)

def analyze_stock_with_gemini(ticker, stock_name, stock_data, analysis_option):
    used, remain = get_remaining_quota()
    if remain <= 0:
        return "⚠️ 오늘 일일 Gemini AI 분석 호출 한도(50회)를 모두 소모하였습니다."

    # 모델 설정 (최신 gemini-1.5-flash 또는 gemini-pro)
    model = genai.GenerativeModel('gemini-3.5-flash')

    # 기본 수치 정보 요약
    mot = stock_data.get('MOT', 0)
    rs90 = stock_data.get('RS(90)', 0)
    rs10 = stock_data.get('RS(10)', 0)
    close_price = stock_data.get('종가', 0)
    disparity = stock_data.get('이격도', stock_data.get('이격(%)', 0))

    # 💡 듀퐁 분석용 프롬프트 템플릿 추가
    if analysis_option == "📈 ROE 듀퐁 분석 (DuPont Analysis)":
        prompt = f"""
당신은 최고의 스몰캡/대형주 주식 분석가이자 퀀트 투자 전문가입니다.
종목명: {stock_name} (종목코드: {ticker})
현재가: {close_price} / 모멘텀(MOT): {mot:.2f} / RS(90): {rs90:.2f} / 이격도: {disparity:.2f}%

위 종목에 대해 ROE(자기자본이익률)를 분해하는 **듀퐁 분석(DuPont Analysis)** 기법을 적용하여 깊이 있고 전문적인 보고서를 작성해 주세요.

다음 항목 및 형식에 맞춰 작성해야 합니다:

1. **듀퐁 분석 3대 요소별 적용 분석**
   * **순이익률 (Profit Margin) -> [방향성: 상승세/유지/하락세]**
     * 분석: 최근 제품 믹스 개선, 마진 구조, 원자재 가격 변화 및 박리다매 여부 분석
     * 변화 요인: 고마진 제품 비중 확대나 실적 턴어라운드 등 ROE에 미치는 수익성 측면 핵심 동인 상세 작성
   * **자산회전율 (Asset Turnover) -> [방향성: 높은 수준 유지/개선/저하]**
     * 분석: 총자산 대비 매출 발생 효율성, 공장 가동률 및 재고 회전 특성
     * 변화 요인: 업황 전방 산업 수요 및 설비 가동 효율성 분석
   * **재무레버리지 (Financial Leverage) -> [방향성: 유지/증가/관리 필요]**
     * 분석: 총자산/자기자본 비율, 부채 활용도 및 차입 구조
     * 변화 요인: CAPEX 투자, 원자재 매입 자금 등 타인자본 활용이 ROE를 지지하는 효과 분석

2. **{stock_name} ROE 개선의 '질적 평가'**
    아래 마크다운 표 양식을 그대로 사용하여 요약하세요:
   | 요인 | 상태 | 평가 |
   |---|---|---|
   | 마진율 (수익성) | 개선/유지/악화 | 상세 평가 |
   | 자산회전율 (효율성) | 양호/유지/저하 | 상세 평가 |
   | 재무레버리지 (안정성) | 유지/증가/축소 | 상세 평가 |

   * **종합 평가**: 부채 증가로 만든 착시인지, 수익성(순이익률)과 가동률(자산회전율) 상승이 이끈 질적으로 우수한 ROE 상승 단계인지 종합 결론 제시.

답변은 한국어로 명확하고 간결하며 가독성 좋게 작성해 주세요. 불필요한 서론/인사말은 생략하세요.
"""
    elif analysis_option == "📋 종합 기본적 분석":
        prompt = f"{stock_name}({ticker})의 밸류에이션, 최근 실적 추이, 업황 모멘텀을 종합 분석해 주세요."
    elif analysis_option == "🏢 사업 구조 및 수익 모델":
        prompt = f"{stock_name}({ticker})의 주요 제품군, 매출 비중, 핵심 수익 구조 및 전방 산업 환경을 분석해 주세요."
    elif analysis_option == "📊 퀀트 지표 기반 밸류에이션":
        prompt = f"{stock_name}({ticker})의 현재 모멘텀({mot:.2f}), RS(90)={rs90:.2f}, 이격도({disparity:.2f}%) 지표를 바탕으로 한 수급/차트 기술적 평가를 해주세요."
    elif analysis_option == "⚠️ 주요 리스크 및 억제 요인":
        prompt = f"{stock_name}({ticker}) 투자 시 유의해야 할 악재, 재무 리스크, 업황 불확실 요인을 분석해 주세요."
    else:  # 🎯 단기/중기 매매 시나리오
        prompt = f"{stock_name}({ticker})의 현재 주가 위치({close_price}) 기반 단기/중기 매매 전략 및 지지/저항선을 제안해 주세요."

    try:
        response = model.generate_content(prompt)
        st.session_state['gemini_used_count'] = used + 1
        return response.text
    except Exception as e:
        return f"❌ AI 분석 중 오류가 발생했습니다: {str(e)}"
