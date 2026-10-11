import os
import streamlit as st
import google.generativeai as genai

# Gemini API 키 설정
GEMINI_API_KEY = st.secrets.get("GEMINI_API_KEY", "")
if GEMINI_API_KEY:
    genai.configure(api_key=GEMINI_API_KEY)

# 일일 쿼터 관리
MAX_DAILY_QUOTA = 50

def get_remaining_quota():
    if "gemini_used_count" not in st.session_state:
        st.session_state["gemini_used_count"] = 0
    used = st.session_state["gemini_used_count"]
    return used, max(0, MAX_DAILY_QUOTA - used)

# ==========================================
# 📌 분석 항목별 프롬프트 템플릿 관리 (분리)
# ==========================================
PROMPT_TEMPLATES = {
    "종합 기본적 분석": """
당신은 퀀트 및 기업 분석 전문가입니다.
아래 제공된 [종목 기본 정보]를 바탕으로 종합 분석 리포트를 작성하세요.

[분석 가이드라인]
1. 제시된 주가 및 기술적 지표가 정상적인 실제 수치임을 전제로 분석하세요. 절대 가격 오기나 오타를 지적하는 것에 분량을 소비하지 마세요.
2. 기술적 지표(이격도, 모멘텀, RS)와 수급 상태를 종합 평가하세요.
3. 해당 기업이 속한 산업군({stock_name})의 최신 모멘텀 및 온디바이스 AI / 반도체 등 핵심 재료를 기반으로 향후 관전 포인트를 제시하세요.
""",

    "ROE 듀퐁 분석": """
당신은 재무제표 및 퀀트 분석 전문가입니다.
제시된 종목 [{stock_name}] ({ticker})에 대해 듀퐁 분석(DuPont Analysis) 관점의 분석을 수행하세요.

[분석 가이드라인]
1. 듀퐁 3단계 요소인 (1) 순이익률 (Profit Margin), (2) 총자산회전율 (Asset Turnover), (3) 재무레버리지 (Financial Leverage)의 개념을 바탕으로, 해당 종목이 속한 업종 특성상 어디에서 수익성이 창출되는지 구조를 설명하세요.
2. 현재 기술적 지표: 종가 {close_price}, MOT {mot}, RS(90) {rs90}, 이격도 {disparities}%
3. 현재 주가 위치에서의 모멘텀 증폭 가능성을 평가하세요.
""",

    "사업 구조": """
당신은 기업 리서치 애널리스트입니다.
종목명: [{stock_name}] ({ticker})

[분석 가이드라인]
1. 이 기업의 주요 제품/서비스 라인업 및 핵심 매출처를 설명하세요.
2. 해당 기업의 핵심 경쟁력(MOAT) 및 전방 산업 환경을 분석하세요.
3. 현재 시장에서의 주목 이유와 리스크 요인을 정리하세요.
""",

    "퀀트 밸류에이션": """
당신은 퀀트 자산운용가입니다.
종목명: [{stock_name}] ({ticker}) | 현재 종가: {close_price}
기술적 모멘텀 지표: MOT({mot}), RS(90)({rs90}), RS(10)({rs10}), 이격도({disparities}%)

[분석 가이드라인]
1. 현재 이격도와 모멘텀 지표를 볼 때, 주가의 과열/저평가 여부를 퀀트적 시각에서 평가하세요.
2. 손절가 및 1차/2차 목표 타점 산출 시 유의해야 할 기술적 마디가를 제시하세요.
""",

    "단/중기 시나리오": """
당신은 트레이딩 전략가입니다.
종목명: [{stock_name}] ({ticker}) | 현재 종가: {close_price}

[분석 가이드라인]
1. 상승 시나리오 (Bull Case): 전고점 돌파 및 모멘텀 지속 시 대응 전략
2. 하락 시나리오 (Bear Case): 지지선 이탈 및 손절 대응 기준
3. 보유 기간별(1~2주 단기 vs 1~3개월 중기) 리스크 관리 팁을 제시하세요.
"""
}

def analyze_stock_with_gemini(ticker, stock_name, stock_row, analysis_option):
    used, remaining = get_remaining_quota()
    if remaining <= 0:
        return "⚠️ 금일 Gemini AI 분석 쿼터(50회)를 모두 소진하였습니다."

    if not GEMINI_API_KEY:
        return "⚠️ GEMINI_API_KEY가 설정되지 않았습니다. .streamlit/secrets.toml을 확인해 주세요."

    try:
        # 📌 1. 데이터 전달 오기 방지를 위한 안전한 데이터 추출 및 포맷팅
        close_price = float(stock_row.get("종가", 0))
        mot_val = float(stock_row.get("MOT", 0))
        rs90_val = float(stock_row.get("RS(90)", 0))
        rs10_val = float(stock_row.get("RS(10)", 0))
        disp_val = float(stock_row.get("이격도", 0)) if "이격도" in stock_row else float(stock_row.get("이격(%)", 0))
        rank_val = stock_row.get("순위", "-")

        # 📌 2. 분석 옵션에 맞는 프롬프트 가져오기
        template = PROMPT_TEMPLATES.get(analysis_option, PROMPT_TEMPLATES["종합 기본적 분석"])
        
        prompt_text = template.format(
            stock_name=stock_name,
            ticker=ticker,
            close_price=f"{close_price:,.0f}원",
            mot=f"{mot_val:.2f}",
            rs90=f"{rs90_val:.2f}",
            rs10=f"{rs10_val:.2f}",
            disparities=f"{disp_val:+.2f}",
            rank=rank_val
        )

        # 📌 3. Gemini 모델 호출 (gemini-1.5-flash 또는 gemini-pro 사용)
        model = genai.GenerativeModel("gemini-1.5-flash")
        
        full_system_instruction = (
            "너는 주식 분석 전문 AI이다. 사용자가 제공한 가격은 수집된 최신 실제 종가 데이터이므로 절대 오타나 오기라고 의심하거나 경고문을 출력하지 마라. "
            "주어진 데이터 안에서 질문에 충실하게 명확하고 읽기 쉬운 Markdown 형식으로 답하라."
        )

        response = model.generate_content(
            f"{full_system_instruction}\n\n[사용자 요청]\n{prompt_text}"
        )

        # 사용량 증가
        st.session_state["gemini_used_count"] = used + 1

        return response.text

    except Exception as e:
        return f"❌ AI 분석 중 오류가 발생했습니다: {str(e)}"
