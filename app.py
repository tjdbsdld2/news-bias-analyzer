"""Streamlit UI for the NewSight MVP."""

from __future__ import annotations

import streamlit as st

from analyzer import analyze_article
from crawler import fetch_article
from db import init_db
from recommender import recommend_opposite


def render_header() -> None:
    """Render the page title and short project description."""
    st.markdown(
        """
        <style>
        .main-title { font-size: 2.5rem; font-weight: 700; color: #1E3A8A; margin-bottom: 5px; }
        .sub-title { font-size: 1.1rem; color: #4B5563; margin-bottom: 25px; }
        </style>
        """,
        unsafe_allow_html=True,
    )

    st.markdown('<div class="main-title">🔮 NewSight</div>', unsafe_allow_html=True)
    st.markdown(
        '<div class="sub-title">기사 URL 하나로, 내가 읽은 뉴스의 관점을 분석하고 다른 시선을 발견합니다.</div>',
        unsafe_allow_html=True,
    )


def render_article_panel(article: dict, analysis: dict) -> None:
    """Show the crawled article metadata and concise summary."""
    st.markdown("### 📰 읽은 기사 정보")
    with st.container(border=True):
        st.markdown(f"#### **{article.get('title', '제목 없음')}**")
        st.caption(
            f"**언론사:** {article.get('source', '정보 없음')} | "
            f"**날짜:** {article.get('date', '정보 없음')} | "
            f"**입력 URL:** {article.get('url', '')}"
        )

        st.write("")
        st.markdown("**📝 기사 한눈에 요약**")
        st.info(analysis.get("summary", "요약 정보가 없습니다."))

        st.write("")
        st.markdown("**📌 주요 메타 태그**")
        st.metric(label="대표 프레임 (Frame)", value=analysis.get("frame", "정보 없음"))
        st.metric(label="주요 목소리 (Voice)", value=analysis.get("primary_voice", "정보 없음"))

        issue_tags = analysis.get("issue_tags", [])
        if issue_tags:
            st.markdown("**🏷️ 이슈 태그**")
            st.markdown(" ".join(f"`#{tag}`" for tag in issue_tags))

        with st.expander("본문 미리보기"):
            st.write(article.get("body", "본문 정보가 없습니다."))


def render_analysis_panel(analysis: dict) -> None:
    """Display the media-literacy analysis in a readable layout."""
    st.markdown("### 📊 AI 미디어 리터러시 분석")
    with st.container(border=True):
        with st.expander("🔍 1. 프레이밍 (Framing Analysis)", expanded=True):
            st.write(analysis.get("framing_analysis", "분석 결과가 없습니다."))

        with st.expander("⚖️ 2. 표현 중립성 (Tone & Language)"):
            st.write(f"**어조:** {analysis.get('tone', '정보 없음')}")
            st.write(analysis.get("language_analysis", "분석 결과가 없습니다."))

        with st.expander("🗣️ 3. 인용 출처 분포 (Citations)"):
            st.write(analysis.get("citation_analysis", "분석 결과가 없습니다."))

        with st.expander("✏️ 4. 제목-본문 일치성 (Title-Body Gap)"):
            st.write(analysis.get("title_body_gap", "분석 결과가 없습니다."))

        with st.expander("💡 5. 누락된 관점 (Missing Perspective)"):
            st.warning(analysis.get("missing_perspective", "분석 결과가 없습니다."))


def render_recommendations(recommendations: list[dict]) -> None:
    """Render recommended articles that present another angle."""
    st.divider()
    st.markdown("### 🔮 다른 시선 발견하기 (반대 관점 추천 기사)")
    st.caption("같은 이슈를 다루지만 다른 프레임으로 접근한 기사들입니다. 비교해서 읽어보세요.")

    if not recommendations:
        st.info("현재 샘플 DB 기준으로는 겹치는 이슈 태그를 가진 다른 프레임의 기사를 찾지 못했습니다.")
        return

    rec_cols = st.columns(len(recommendations))
    for idx, rec in enumerate(recommendations):
        with rec_cols[idx]:
            with st.container(border=True):
                st.markdown(f"`🏷️ {rec.get('frame', '프레임 정보 없음')}`")
                st.markdown(f"##### **[{rec.get('source', '출처 정보 없음')}]**")
                st.markdown(f"**{rec.get('title', '제목 없음')}**")
                st.caption(f"{rec.get('date', '날짜 정보 없음')}")

                issue_tags = rec.get("issue_tags", [])
                if issue_tags:
                    st.markdown(" ".join(f"`#{tag}`" for tag in issue_tags))

                st.write("")
                st.link_button("🔗 기사 보러 가기", rec.get("url", ""), use_container_width=True)


def main() -> None:
    """Entry point for the Streamlit MVP app."""
    init_db()

    st.set_page_config(page_title="NewSight | AI 뉴스 관점 분석", page_icon="🔮", layout="wide")
    render_header()

    with st.container(border=True):
        st.subheader("🔗 분석할 뉴스 기사 URL 입력")
        news_url = st.text_input(
            "뉴스 기사 링크를 붙여넣어 주세요.",
            placeholder="https://news.naver.com/main/read.nhn?...",
        )

        _, _, col_btn = st.columns([4, 4, 2])
        with col_btn:
            start_button = st.button("🔮 뉴스 관점 분석 시작", use_container_width=True, type="primary")

    st.divider()

    if start_button:
        if not news_url.strip():
            st.warning("경고: 분석할 뉴스 URL을 입력해 주세요!")
        else:
            with st.spinner("🕵️ 뉴스를 추출하고 AI가 관점을 분석하는 중입니다..."):
                article = fetch_article(news_url.strip())

                if article is None:
                    st.error("기사 제목 또는 본문을 추출하지 못했습니다. 다른 기사 URL로 다시 시도해 주세요.")
                    st.stop()

                analysis = analyze_article(article)
                recommendations = recommend_opposite(analysis)

            st.success("분석이 완료되었습니다!")

            if analysis.get("analysis_notice"):
                st.info(analysis["analysis_notice"])

            col_left, col_right = st.columns([4, 6])
            with col_left:
                render_article_panel(article, analysis)
            with col_right:
                render_analysis_panel(analysis)

            render_recommendations(recommendations)

    st.write("")
    st.divider()
    st.caption(
        "⚠️ **안내:** NewSight AI의 분석은 절대적인 정치적 판단이 아니라, "
        "독자의 비판적 뉴스 읽기를 돕는 미디어 리터러시 보조 도구입니다."
    )


if __name__ == "__main__":
    main()
