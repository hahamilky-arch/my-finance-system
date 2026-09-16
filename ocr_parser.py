import easyocr
import pandas as pd
import numpy as np
from PIL import Image
import re
import streamlit as st
from db import supabase

@st.cache_resource
def load_ocr_reader():
    """EasyOCR 엔진 메모리 캐싱 (최초 1회만 로드)"""
    return easyocr.Reader(['ko', 'en'], gpu=False)

def process_and_save_ocr(uploaded_file, target_date_str):
    """
    업로드된 스크린샷 이미지를 분석하여 데이터 추출 후 Supabase DB에 저장
    """
    reader = load_ocr_reader()
    
    # 1. 이미지 읽기
    image = Image.open(uploaded_file)
    img_np = np.array(image)
    
    # 2. EasyOCR 실행
    results = reader.readtext(img_np)
    image.close()
    
    if not results:
        return False, "❌ 이미지에서 텍스트를 읽을 수 없습니다."

    # 3. Y축 좌표 기반으로 같은 행(Row) 묶기 처리
    lines = []
    # OCR 결과: bbox, text, prob
    results_sorted = sorted(results, key=lambda x: x[0][0][1])  # Y좌표 정렬
    
    current_line = []
    last_y = None
    y_threshold = 15  # 동일한 행으로 판단할 Y축 픽셀 오차범위

    for bbox, text, prob in results_sorted:
        y_center = (bbox[0][1] + bbox[2][1]) / 2
        if last_y is None or abs(y_center - last_y) < y_threshold:
            current_line.append((bbox[0][0], text.strip()))  # X좌표와 텍스트 저장
        else:
            current_line.sort(key=lambda x: x[0])  # X좌표 정렬 (왼쪽->오른쪽)
            lines.append([t[1] for t in current_line])
            current_line = [(bbox[0][0], text.strip())]
        last_y = y_center

    if current_line:
        current_line.sort(key=lambda x: x[0])
        lines.append([t[1] for t in current_line])

    # 4. 정형 수급 데이터 굵은 파싱
    parsed_rows = []
    rank_idx = 1
    
    for line in lines:
        # 숫자와 종목명이 섞인 유효한 수급 행 스크리닝
        text_joined = " ".join(line)
        
        # 쉼표 제거 후 수치 추출 예시
        clean_text = text_joined.replace(',', '')
        numbers = re.findall(r'[-+]?\d*\.\d+|\d+', clean_text)
        
        # 종목명(한글 포함 단어) 추출
        words = [w for w in line if re.search(r'[가-힣]', w)]
        
        if words and len(numbers) >= 3:
            stock_name = words[0]
            try:
                # 라인 내 수치 매핑 (현재가, 등락률, 합계, 외인, 기관 등)
                close_price = float(numbers[0]) if len(numbers) > 0 else 0.0
                change_rate = float(numbers[1]) if len(numbers) > 1 else 0.0
                net_total = float(numbers[2]) if len(numbers) > 2 else 0.0
                foreign_net = float(numbers[3]) if len(numbers) > 3 else 0.0
                inst_net = float(numbers[4]) if len(numbers) > 4 else 0.0
                
                parsed_rows.append({
                    "trade_date": target_date_str,
                    "rank": rank_idx,
                    "ticker": f"TEMP_{rank_idx:03d}", # 종목코드 매핑 전 임시 키
                    "name": stock_name,
                    "close_price": close_price,
                    "change_rate": change_rate,
                    "net_total": net_total,
                    "foreign_net": foreign_net,
                    "inst_net": inst_net,
                    "volume_power": 1.0
                })
                rank_idx += 1
            except Exception:
                continue

    if not parsed_rows:
        return False, "⚠️ 이미지에서 수급 표 데이터를 정형화하지 못했습니다."

    # 5. Supabase DB 저장 (UPSERT)
    try:
        supabase.table("daily_top_liquidity").upsert(parsed_rows, on_conflict="trade_date, ticker").execute()
        return True, f"✅ 총 {len(parsed_rows)}개 종목의 수급 데이터가 DB에 성공적으로 저장되었습니다."
    except Exception as e:
        return False, f"❌ Supabase DB 저장 오류: {e}"
