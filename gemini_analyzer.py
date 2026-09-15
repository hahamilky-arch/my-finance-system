import streamlit as st
import google.generativeai as genai

# Streamlit Secrets에서 API Key 가져오기
GEMINI_KEY = st.secrets.get("GEMINI_API_KEY", "")
if GEMINI_KEY:
    genai.configure(api_key=GEMINI_KEY)

MAX_DAILY_QUOTA = 250

if 'gemini_api_count' not in st.session_state:
    st.session_state['gemini_api_count'] = 0

def get_remaining_quota():
    """Gemini API 일일 잔여 사용량 계산"""
    used = st.session_state['gemini_api_count']
    remaining = max(0, MAX_DAILY_QUOTA - used)
    return used, remaining

def analyze_stock_with_gemini(ticker, stock_name, row_data, analysis_type):
    """선택한 종목 및 분석 옵션에 따른 Gemini 3.5 AI 분석 수행"""
    if not GEMINI_KEY:
        return "❌ `.streamlit/secrets.toml` 또는 Streamlit Cloud Secrets에 `GEMINI_API_KEY`가 설정되지 않았습니다."
    
    used, remaining = get_remaining_quota()
    if remaining <= 0:
        return "⚠️ 오늘 사용할 수 있는 Gemini API 호출 한도를 모두 소진했습니다."

    # Gemini 3.5 Flash 모델 지정 및 자동 폴백 처리
    model_names = ['gemini-3.5-flash', 'gemini-1.5-flash', 'gemini-1.5-pro']
    model = None
    for m_name in model_names:
        try:
            model = genai.GenerativeModel(m_name)
            break
        except Exception:
            continue
            
    if not model:
        model = genai.GenerativeModel('gemini-3.5-flash')

    base_info = f"""
    [종목 정보]
    - 종목명: {stock_name} ({ticker})
    - 현재 종가: {row_data.get('종가', '-')}
    - 모멘텀 점수(MOT): {row_data.get('MOT', '-')}
    - 상대강도 RS(90): {row_data.get('RS(90)', '-')}
    - 20일 이격도: {row_data.get('이격도', '-')}
    - ATR: {row_data.get('atr', '-')}
    """

    if analysis_type == "🏢 사업 구조 및 수익 모델":
        prompt = f"""
        당신은 주식 펀더멘털 분석 전문가입니다. {stock_name}({ticker})의 사업 구조를 분석해주세요.
        {base_info}
        [요청 사항]
        1. 핵심 제품/서비스 및 매출 발생 구조
        2. 해당 산업 내 독점력 또는 경쟁 우위 요소(경제적 해자)
        3. 향후 1~2년 내 실적을 견인할 주요 성장 동력
        """
    elif analysis_type == "📊 퀀트 지표 기반 밸류에이션":
        prompt = f"""
        당신은 퀀트 투자 전문가입니다. 아래 지표를 바탕으로 기술적/수량적 가치를 평가해주세요.
        {base_info}
        [요청 사항]
        1. 현재 이격도 및 모멘텀(MOT) 기준 가격 과열 여부 판단
        2. 변동성 지표(ATR) 대비 가격 위치의 안정성 평가
        3. 퀀트 지표 관점에서의 적정 가격대 판단 및 주의 구간
        """
    elif analysis_type == "⚠️ 주요 리스크 및 억제 요인":
        prompt = f"""
        당신은 리스크 관리 전문가입니다. {stock_name}({ticker}) 투자 시 발생 가능한 위험 요소를 분석해주세요.
        {base_info}
        [요청 사항]
        1. 기업 내부 또는 실적 관련 잠재적 펀더멘털 리스크 2가지
        2. 거시경제(매크로: 금리, 환율, 원자재 등)에 따른 부정적 영향
        3. 주가 하방 압력으로 작용할 수 있는 수급/기술적 위협 요인
        """
    elif analysis_type == "🎯 단기/중기 매매 시나리오":
        prompt = f"""
        당신은 트레이딩 전략가입니다. 아래 데이터를 바탕으로 실제 매매에 활용 가능한 전략을 제시해주세요.
        {base_info}
        [요청 사항]
        1. 현재 위치에서의 추세 대응(신규 진입 vs 보유 유지를 위한 구체적 가이드)
        2. 지표(ATR, 이격도) 연계 손절선 및 1차/2차 목표가 설정 기준
        3. 매매 시 반드시 지켜야 할 자금 관리 핵심 주의사항
        """
    else:
        prompt = f"""
        당신은 퀀트 및 주식 펀더멘털 분석 전문가입니다. {stock_name}({ticker})의 종합 분석을 작성해주세요.
        {base_info}
        [요청 사항]
        1. 주요 사업 영역 및 최근 기업 이슈 요약
        2. 퀀트 지표(MOT, RS)와 연계된 펀더멘털 강점 및 리스크
        3. 투자 판단에 필요한 핵심 관전 포인트 3가지
        """

    try:
        response = model.generate_content(prompt)
        st.session_state['gemini_api_count'] += 1
        return response.text
    except Exception as e:
        return f"❌ Gemini API 분석 요청 중 오류 발생: {e}"
