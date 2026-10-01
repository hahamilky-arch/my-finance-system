import streamlit as st
import streamlit.components.v1 as components

# 페이지 설정
st.set_page_config(layout="wide")

# 📌 새로고침 / 페이지 이탈 방지 컨펌 팝업 스크립트
components.html(
    """
    <script>
    const preventReload = function (e) {
        e.preventDefault();
        e.returnValue = ''; // 브라우저 표준 경고창 출력을 위한 설정
    };
    
    // 부모 창(Streamlit 메인 브라우저 window)에 이벤트 등록
    window.parent.addEventListener('beforeunload', preventReload);
    </script>
    """,
    height=0,
)
