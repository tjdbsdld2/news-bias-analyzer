import streamlit as st
#python -m streamlit run app.py
import time

# [연동 가이드] 백엔드 담당자분들의 파일이 완성되면 아래 주석을 해제하여 연동하세요.
# from crawler import crawl_news
# from analyzer import analyze_news
# from recommender import get_recommendations

# 1. 페이지 설정 및 디자인 (미디어 리터러시 툴에 맞는 깔끔한 테마)
st.set_page_config(
    page_title="|AI 뉴스 편향 분석", 
    page_icon="🔮", 
    layout="wide"
)

# 커스텀 CSS로 스타일 살짝 다듬기
st.markdown("""
    <style>
    .main-title { font-size: 2.5rem ; font-weight: 700; color: #1E3A8A; margin-bottom: 5px; }
    .sub-title { font-size: 1.1rem; color: #4B5563; margin-bottom: 25px; }
    </style>
""", unsafe_allow_html=True)

# 2. 헤더 섹션
st.markdown('<div class="main-title">🔮 NewsPrism</div>', unsafe_allow_html=True)
st.markdown('<div class="sub-title">기사 URL 하나로, 내가 읽은 뉴스의 관점을 분석하고 다른 시선을 발견합니다.</div>', unsafe_allow_html=True)

# 3. 사용자 입력 섹션
with st.container(border=True):
    st.subheader("🔗 분석할 뉴스 기사 URL 입력")
    news_url = st.text_input(
        "뉴스 기사 링크를 붙여넣어 주세요.", 
        placeholder="https://news.naver.com/main/read.nhn?..."
    )
    
    # 버튼을 우측 정렬하거나 강조하기 위해 컬럼 배치
    _, _, col_btn = st.columns([4, 4, 2])
    with col_btn:
        start_button = st.button("🔮 뉴스 관점 분석 시작", use_container_width=True, type="primary")

st.divider()

# 4. 분석 시작 버튼 클릭 시 동작
if start_button:
    if not news_url:
        st.warning("경고: 분석할 뉴스 URL을 입력해 주세요!")
    else:
        # ─── [백엔드 연동 및 로딩 시뮬레이션] ───
        with st.spinner("🕵️ 뉴스를 크롤링하고 AI(Claude)가 관점을 분석하는 중입니다..."):
            # 1) crawler.py 연동 (예시: title, body, source = crawl_news(news_url))
            # 2) analyzer.py 연동 (예시: analysis_result = analyze_news(body))
            # 3) recommender.py 연동 (예시: rec_articles = get_recommendations(analysis_result['frame']))
            time.sleep(2.5) # 시연 및 캐시 느낌을 위한 대기 시간
        
        st.success("분석이 완료되었습니다!")
        
        # ─── 가상의 AI 분석 응답 데이터 (기획서 명세 기준) ───
        mock_article = {"title": "최저임금 내년도 인상 불가피, 노동계 강력 요구", "source": "OO일보"}
        
        mock_analysis = {
            "summary": "본 기사는 내년도 최저임금 협상을 앞두고 노동계의 인상 요구안과 그 배경을 중심으로 다루고 있습니다. 물가 상승률과 실질 임금 저하를 근거로 제시하며 노동자들의 생존권 보장을 강조하는 흐름을 보입니다.",
            "frame": "노동자_권리",
            "tone": "부정적 (현재 처우에 대한 비판적 어조)",
            "primary_voice": "노동계 (5회 인용)",
            "framing_analysis": "사건을 노동자의 생존권 및 권리 침해라는 '피해 및 권리' 프레임으로 구성하여 독자에게 감정적 공감을 유도함.",
            "language_analysis": "'강행했다', '외면했다' 등 다소 감정이 섞인 평가성 유도 표현이 일부 관찰됨.",
            "citation_analysis": "노동계 시민단체 및 근로자 인터뷰 5회인 반면, 경영계(소상공인) 의견은 1회로 머물러 인용 출처의 불균형이 있음.",
            "title_body_gap": "제목의 '강력 요구'라는 단어 프레임이 본문의 수치적 근거보다 다소 자극적으로 강조됨.",
            "missing_perspective": "최저임금 인상 시 소상공인이 직면할 고용 감소 효과나 경제적 부담(경영계 입장)에 대한 서술이 누락됨."
        }
        
        mock_recommendations = [
            {"title": "소상공인 폐업 위기, 최저임금 동결 호소", "source": "XX경제", "frame": "경영계_부담", "url": "https://example.com/1"},
            {"title": "정부, 최저임금 속도조절론 시사... 중재안 고심", "source": "△△일보", "frame": "정책_정당성", "url": "https://example.com/2"},
            {"title": "올해도 평행선 달리는 최저임금위, 노사 정면 충돌", "source": "□□뉴스", "frame": "갈등_구도", "url": "https://example.com/3"}
        ]
        # ─────────────────────────────────────

        # 5. 결과 화면 레이아웃 구성
        # 왼쪽: 입력 기사 요약 및 메타 정보 / 오른쪽: 5대 편향 분석 핵심 결과
        col_left, col_right = st.columns([4, 6])
        
        with col_left:
            st.markdown("### 📰 읽은 기사 정보")
            with st.container(border=True):
                st.markdown(f"#### **{mock_article['title']}**")
                st.caption(f"**언론사:** {mock_article['source']} | **입력 URL:** {news_url}")
                st.write("")
                st.markdown("**📝 기사 한눈에 요약**")
                st.info(mock_analysis['summary'])
                
                # 핵심 태그 메트릭 표시
                st.write("")
                st.markdown("**📌 주요 메타 태그**")
                st.metric(label="대표 프레임 (Frame)", value=mock_analysis['frame'])
                st.metric(label="주요 목소리 (Voice)", value=mock_analysis['primary_voice'])

        with col_right:
            st.markdown("### 📊 AI 미디어 리터러시 분석")
            
            with st.container(border=True):
                # 5대 분석 항목을 확장형 메뉴(Expander)로 깔끔하게 배치
                with st.expander("🔍 1. 프레이밍 (Framing Analysis)", expanded=True):
                    st.write(mock_analysis['framing_analysis'])
                    
                with st.expander("⚖️ 2. 표현 중립성 (Tone & Language)"):
                    st.write(f"**어조:** {mock_analysis['tone']}")
                    st.write(mock_analysis['language_analysis'])
                    
                with st.expander("🗣️ 3. 인용 출처 분포 (Citations)"):
                    st.write(mock_analysis['citation_analysis'])
                    
                with st.expander("✏️ 4. 제목-본문 일치성 (Title-Body Gap)"):
                    st.write(mock_analysis['title_body_gap'])
                    
                with st.expander("💡 5. 누락된 관점 (Missing Perspective)"):
                    st.warning(mock_analysis['missing_perspective'])

        st.divider()

        # 6. 반대 관점 기사 추천 섹션 (카드 레이아웃 3분할)
        st.markdown("### 🔮 다른 시선 발견하기 (반대 관점 추천 기사)")
        st.caption("내가 읽은 기사와 다른 프레임이나 목소리로 사건을 바라본 기사들입니다. 다각도로 비교해 보세요.")
        st.write("")
        
        rec_cols = st.columns(3)
        for idx, rec in enumerate(mock_recommendations):
            with rec_cols[idx]:
                with st.container(border=True):
                    # 프레임 종류별 다른 색상 뱃지 느낌 내기
                    frame_badge = f"`🏷️ {rec['frame']}`"
                    st.markdown(frame_badge)
                    
                    st.markdown(f"##### **[{rec['source']}]**")
                    st.markdown(f"**{rec['title']}**")
                    st.write("")
                    
                    # 추천 카드 하단 이동 버튼
                    st.link_button("🔗 기사 보러 가기", rec['url'], use_container_width=True)

# 7. 푸터 (시연 시 주의사항 명시)
st.write("")
st.divider()
st.caption("⚠️ **안내:** NewsPrism AI의 분석은 절대적인 정치적 판단이 아닌, 독자의 비판적 뉴스 읽기를 돕는 미디어 리터러시 보조 도구입니다.")