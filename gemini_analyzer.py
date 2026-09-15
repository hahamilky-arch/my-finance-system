import streamlit as st
import google.generativeai as genai

# 1. Gemini API 초기화 (Secrets에서 안전하게 로드)
GEMINI_KEY = st.secrets.get("GEMINI_API_KEY", "")
if GEMINI_KEY:
    genai.configure(api_key=GEMINI_KEY)

# Free Tier 기준 일일 한도 (예: 250회)
MAX_DAILY_QUOTA = 250

def get_remaining_quota():
    """세션 기반 잔여 호출 수 반환"""
    if 'gemini_api_count' not in st.session_state:
        st.session_state['gemini_api_count'] = 0
    used = st.session_state['gemini_api_count']
    remaining = max(0, MAX_DAILY_QUOTA - used)
    return used, remaining

def analyze_stock_fundamentals(ticker, stock_name, row_data):
    """선택한 종목의 기본적/정량 펀더멘털 분석 요청"""
    if not GEMINI_KEY:
        return "❌ `.streamlit/secrets.toml` 또는 Streamlit Cloud Secrets에 `GEMINI_API_KEY`가 설정되지 않았습니다."
    
    used, remaining = get_remaining_quota()
    if remaining <= 0:
        return "⚠️ 오늘 사용할 수 있는 Gemini API 호출 한도를 모두 소진했습니다."

    model = genai.GenerativeModel('gemini-3.5-flash')
    
    prompt = f"""
    당신은 퀀트 및 주식 펀더멘털 분석 전문가입니다.
    아래 제공된 종목 정보와 수치를 바탕으로 {stock_name}({ticker})의 기본적 분석(Fundamental Analysis) 요약을 친근한 말투 없이 쉽고 자세하게 작성해주세요.

    [종목 정보]
    - 종목명: {stock_name} ({ticker})
    - 현재 종가: {row_data.get('종가', '-')}
    - 모멘텀 점수(MOT): {row_data.get('MOT', '-')}
    - 상대강도 RS(90): {row_data.get('RS(90)', '-')}
    - 20일 이격도: {row_data.get('이격도', '-')}
    - ATR: {row_data.get('atr', '-')}

    [요청 사항]
    1. 해당 기업의 주요 사업 영역 및 최근 사업 모멘텀
    2. 기술적/퀀트 지표(MOT, RS)와 연계된 재무적 강점 및 리스크 요소
    3. 투자 시 유의해야 할 주요 관전 포인트 3가지 요약
    """

    try:
        response = model.generate_content(prompt)
        st.session_state['gemini_api_count'] += 1
        return response.text
    except Exception as e:
        return f"❌ Gemini API 분석 요청 중 오류 발생: {e}"
