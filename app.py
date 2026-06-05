"""Streamlit UI for the NewSight app."""

from __future__ import annotations

import html
import re

import streamlit as st

from analyzer import analyze_article, explain_external_candidates
from crawler import fetch_article
from recommender import recommend_articles
from searcher import search_related_articles


HIGHLIGHT_RULES = [
    (
        "quote",
        re.compile(r"[\"“][^\"”]{2,120}[\"”]"),
    ),
    (
        "metric",
        re.compile(r"\d[\d,]*(?:\.\d+)?\s*(?:%|명|곳|건|개|차례|년|월|일|배)?"),
    ),
    (
        "caution",
        re.compile(
            r"논란|의혹|반발|우려|비판|공방|봉쇄|감금|책임|사과|실패|부족|피해|강행|부담|혼란|참담함|충돌|무효|사퇴|진상규명"
        ),
    ),
    (
        "attribution",
        re.compile(
            r"밝혔(?:다|습니다)?|설명했(?:다|습니다)?|말했(?:다|습니다)?|주장했(?:다|습니다)?|전했다|강조했(?:다|습니다)?|사과했(?:다|습니다)?|촉구했(?:다|습니다)?"
        ),
    ),
]


def _escape(text: str) -> str:
    """Escape text for safe inline HTML rendering."""
    return html.escape(text or "").replace("\n", "<br>")


def _render_tag_row(tags: list[str], tone: str = "default") -> str:
    """Render a compact set of keyword chips."""
    if not tags:
        return ""

    chips = "".join(
        f"<span class='ns-chip ns-chip-{tone}'>#{_escape(tag)}</span>"
        for tag in tags
        if str(tag).strip()
    )
    return f"<div class='ns-chip-row'>{chips}</div>"


def _build_position_summary(analysis: dict) -> str:
    """Create a short one-line reading orientation sentence."""
    frame = str(analysis.get("frame", "")).strip() or "정보 없음"
    voice = str(analysis.get("primary_voice", "")).strip() or "정보 없음"
    tone = str(analysis.get("tone", "")).strip() or "정보 없음"
    return (
        f"이 기사는 '{frame}' 프레임을 중심에 두고 '{voice}'의 목소리를 가장 크게 들려주며, "
        f"전체 어조는 '{tone}'에 가깝습니다."
    )


def _build_comparison_hint(analysis: dict) -> str:
    """Turn the analysis into a concrete next-step comparison hint."""
    voice = str(analysis.get("primary_voice", "")).strip() or "현재 기사에서 가장 크게 들리는 주체"
    frame = str(analysis.get("frame", "")).strip() or "현재 기사 프레임"
    missing = str(analysis.get("missing_perspective", "")).strip()
    if missing:
        return (
            f"다음 기사에서는 '{voice}' 외에 어떤 주체가 더 길게 인용되는지, "
            f"같은 사안을 '{frame}' 대신 다른 문제로 읽게 만드는 근거가 있는지 함께 확인해 보세요. "
            f"{missing}"
        )
    return (
        f"다음 기사에서는 '{voice}' 외에 어떤 주체가 더 길게 인용되는지, "
        f"같은 사안을 '{frame}' 대신 다른 문제로 읽게 만드는 근거가 있는지 함께 확인해 보세요."
    )


def _split_sentences(text: str) -> list[str]:
    """Split article body into readable sentence-like chunks."""
    normalized = re.sub(r"\s+", " ", (text or "").strip())
    if not normalized:
        return []

    parts = re.split(r"(?<=[.!?]|[다요죠]\.)\s+|(?<=다)\s+(?=[\"'“‘A-Z가-힣])", normalized)
    sentences = [part.strip() for part in parts if part.strip()]
    if sentences:
        return sentences
    return [normalized]


def _sentence_tooltip(sentence: str) -> str:
    """Generate a short hover explanation for one sentence."""
    notes: list[str] = []

    if re.search(r"[\"“][^\"”]{2,120}[\"”]", sentence):
        notes.append("직접 인용이 들어 있습니다. 누가 어떤 표현을 그대로 말했는지 보세요.")
    if re.search(r"\d[\d,]*(?:\.\d+)?\s*(?:%|명|곳|건|개|차례|년|월|일|배)?", sentence):
        notes.append("수치나 규모가 제시됩니다. 비교 기준이 함께 제시되는지도 확인해 보세요.")
    if re.search(r"논란|의혹|반발|우려|비판|공방|봉쇄|감금|책임|사과|실패|부족|피해|강행|부담|혼란|참담함|충돌|무효|사퇴|진상규명", sentence):
        notes.append("갈등·책임·평가 성격의 표현이 있습니다. 사건을 어떤 문제로 읽게 만드는지 보세요.")
    if re.search(r"밝혔(?:다|습니다)?|설명했(?:다|습니다)?|말했(?:다|습니다)?|주장했(?:다|습니다)?|전했다|강조했(?:다|습니다)?|사과했(?:다|습니다)?|촉구했(?:다|습니다)?", sentence):
        notes.append("발화 주체의 설명이나 주장이 실린 문장입니다. 이 목소리가 얼마나 길게 다뤄지는지 확인해 보세요.")
    if re.search(r"알려졌다|전해졌다|거론된다|지적된다|우려된다", sentence):
        notes.append("행위 주체가 흐려질 수 있는 수동적 표현입니다. 누가 그렇게 말하는지 따져보면 도움이 됩니다.")

    if not notes:
        notes.append("맥락을 이어주는 설명 문장입니다. 앞뒤 문장과 함께 보면 강조 방향이 더 잘 보입니다.")

    return " ".join(notes[:3])


def _highlight_sentence(sentence: str) -> str:
    """Wrap notable expressions inside a sentence with styled spans."""
    matches: list[tuple[int, int, str]] = []
    priority = {"quote": 0, "caution": 1, "metric": 2, "attribution": 3}

    for tone, pattern in HIGHLIGHT_RULES:
        for match in pattern.finditer(sentence):
            matches.append((match.start(), match.end(), tone))

    matches.sort(key=lambda item: (item[0], priority[item[2]], -(item[1] - item[0])))

    filtered: list[tuple[int, int, str]] = []
    cursor = 0
    for start, end, tone in matches:
        if start < cursor:
            continue
        filtered.append((start, end, tone))
        cursor = end

    chunks: list[str] = []
    last = 0
    for start, end, tone in filtered:
        chunks.append(html.escape(sentence[last:start]))
        chunk = html.escape(sentence[start:end])
        chunks.append(f"<span class='ns-mark ns-mark-{tone}'>{chunk}</span>")
        last = end
    chunks.append(html.escape(sentence[last:]))
    return "".join(chunks)


def _render_body_preview_html(body: str) -> str:
    """Build annotated body preview HTML with hover explanations."""
    sentences = _split_sentences(body)
    if not sentences:
        return "<div class='ns-body-empty'>본문 정보가 없습니다.</div>"

    sentence_html = []
    for sentence in sentences:
        tooltip = html.escape(_sentence_tooltip(sentence), quote=True)
        sentence_html.append(
            f"<span class='ns-annotated-sentence' data-tip='{tooltip}' title='{tooltip}'>{_highlight_sentence(sentence)}</span>"
        )

    body_html = " ".join(sentence_html)
    return f"""
        <div class="ns-body-panel">
          <div class="ns-body-topline">
            <div class="ns-section-title" style="margin-bottom:0.35rem;">본문 읽기 보조</div>
            <div class="ns-muted-copy">문장 위에 커서를 올리면 읽기 힌트가 나타납니다.</div>
          </div>
          <div class="ns-body-legend">
            <span class="ns-legend-item"><span class="ns-mark ns-mark-caution">주의 표현</span> 갈등, 책임, 평가가 실린 단어</span>
            <span class="ns-legend-item"><span class="ns-mark ns-mark-metric">수치 근거</span> 규모나 비율이 제시된 부분</span>
            <span class="ns-legend-item"><span class="ns-mark ns-mark-quote">직접 인용</span> 발화가 그대로 드러나는 부분</span>
          </div>
          <div class="ns-body-copy">{body_html}</div>
        </div>
    """


def inject_styles() -> None:
    """Inject a more editorial visual system for the Streamlit app."""
    st.markdown(
        """
        <style>
        :root {
            --ns-bg: #f4efe6;
            --ns-ink: #1d2430;
            --ns-muted: #5d6573;
            --ns-border: rgba(29, 36, 48, 0.10);
            --ns-card: rgba(255, 252, 247, 0.88);
            --ns-card-strong: rgba(255, 250, 242, 0.96);
            --ns-accent: #8b2e22;
            --ns-accent-soft: rgba(139, 46, 34, 0.10);
            --ns-secondary: #20455e;
            --ns-secondary-soft: rgba(32, 69, 94, 0.10);
            --ns-shadow: 0 18px 48px rgba(34, 32, 28, 0.08);
            --ns-radius-lg: 24px;
            --ns-radius-md: 18px;
            --ns-radius-sm: 999px;
        }

        .stApp {
            background:
                radial-gradient(circle at top left, rgba(139, 46, 34, 0.10), transparent 24%),
                radial-gradient(circle at top right, rgba(32, 69, 94, 0.08), transparent 22%),
                linear-gradient(180deg, #f8f2e8 0%, var(--ns-bg) 55%, #efe8dd 100%);
            color: var(--ns-ink);
        }

        .block-container {
            max-width: 1180px;
            padding-top: 2.2rem;
            padding-bottom: 3.2rem;
        }

        h1, h2, h3, h4 {
            color: var(--ns-ink);
            letter-spacing: -0.02em;
            font-family: "Iowan Old Style", "Palatino Linotype", "Book Antiqua", Georgia, serif;
        }

        p, li, label, span, div {
            font-family: "Avenir Next", "Segoe UI", "Apple SD Gothic Neo", "Noto Sans KR", sans-serif;
        }

        [data-testid="stHeader"] {
            background: transparent;
        }

        [data-testid="stSidebar"] {
            background: rgba(255, 252, 247, 0.55);
        }

        .stTextInput label p,
        .stTextInput label,
        .stButton button,
        .stLinkButton a {
            font-family: "Avenir Next", "Segoe UI", "Apple SD Gothic Neo", "Noto Sans KR", sans-serif;
        }

        div[data-testid="stTextInput"] label p {
            color: var(--ns-muted);
            font-size: 0.92rem;
            font-weight: 600;
        }

        div[data-testid="stTextInput"] input {
            background: rgba(255, 252, 247, 0.9);
            border: 1px solid var(--ns-border);
            border-radius: 16px;
            color: var(--ns-ink);
            min-height: 3.2rem;
            padding-left: 0.9rem;
            box-shadow: inset 0 1px 0 rgba(255, 255, 255, 0.4);
        }

        div[data-testid="stTextInput"] input:focus {
            border-color: rgba(32, 69, 94, 0.35);
            box-shadow: 0 0 0 1px rgba(32, 69, 94, 0.20);
        }

        .stButton > button,
        .stLinkButton > a {
            border-radius: 999px;
            border: 1px solid rgba(21, 34, 49, 0.08);
            min-height: 3rem;
            font-weight: 700;
            transition: all 0.2s ease;
        }

        .stButton > button[kind="primary"] {
            background: linear-gradient(135deg, #1d3b53 0%, #315d7c 100%);
            color: #fdf9f3;
            box-shadow: 0 12px 24px rgba(29, 59, 83, 0.18);
        }

        .stButton > button[kind="primary"]:hover,
        .stLinkButton > a:hover {
            transform: translateY(-1px);
        }

        .stLinkButton > a {
            background: rgba(32, 69, 94, 0.08);
            color: var(--ns-secondary);
            border-color: rgba(32, 69, 94, 0.12);
        }

        .ns-hero {
            background:
                linear-gradient(135deg, rgba(255, 252, 247, 0.95) 0%, rgba(245, 235, 221, 0.90) 100%);
            border: 1px solid rgba(29, 36, 48, 0.08);
            border-radius: var(--ns-radius-lg);
            box-shadow: var(--ns-shadow);
            overflow: hidden;
            margin-bottom: 1.5rem;
        }

        .ns-hero-top {
            display: grid;
            grid-template-columns: minmax(0, 1.2fr) minmax(250px, 0.8fr);
            gap: 1.4rem;
            padding: 1.6rem 1.7rem 1.2rem;
        }

        .ns-eyebrow {
            display: inline-flex;
            align-items: center;
            gap: 0.4rem;
            font-size: 0.76rem;
            font-weight: 800;
            letter-spacing: 0.12em;
            text-transform: uppercase;
            color: var(--ns-accent);
            margin-bottom: 0.9rem;
        }

        .ns-title {
            font-size: clamp(2.2rem, 5vw, 3.8rem);
            line-height: 0.95;
            margin: 0;
            color: #172230;
        }

        .ns-lead {
            margin: 1rem 0 0;
            font-size: 1.02rem;
            line-height: 1.7;
            color: var(--ns-muted);
            max-width: 54ch;
        }

        .ns-hero-note {
            background: rgba(32, 69, 94, 0.07);
            border: 1px solid rgba(32, 69, 94, 0.10);
            border-radius: 20px;
            padding: 1.1rem 1.15rem;
            align-self: end;
        }

        .ns-hero-note strong {
            display: block;
            color: var(--ns-secondary);
            font-size: 0.82rem;
            letter-spacing: 0.08em;
            text-transform: uppercase;
            margin-bottom: 0.5rem;
        }

        .ns-hero-note p {
            margin: 0;
            color: var(--ns-ink);
            font-size: 0.94rem;
            line-height: 1.65;
        }

        .ns-hero-note ul {
            margin: 0;
            padding-left: 1rem;
            color: var(--ns-ink);
            font-size: 0.94rem;
            line-height: 1.7;
        }

        .ns-panel,
        .ns-analysis-card,
        .ns-rec-card,
        .ns-callout {
            background: var(--ns-card);
            border: 1px solid var(--ns-border);
            border-radius: var(--ns-radius-md);
            box-shadow: var(--ns-shadow);
        }

        .ns-panel {
            padding: 1.35rem 1.35rem 1.15rem;
        }

        .ns-panel + .ns-panel {
            margin-top: 1rem;
        }

        .ns-section-title {
            margin: 0 0 0.9rem;
            font-size: 0.88rem;
            letter-spacing: 0.08em;
            text-transform: uppercase;
            color: var(--ns-muted);
            font-weight: 800;
        }

        .ns-article-title {
            margin: 0 0 0.55rem;
            font-size: 1.62rem;
            line-height: 1.18;
            color: #182230;
        }

        .ns-meta-line {
            font-size: 0.92rem;
            line-height: 1.6;
            color: var(--ns-muted);
            margin-bottom: 1rem;
        }

        .ns-summary-box {
            background: linear-gradient(135deg, rgba(139, 46, 34, 0.06) 0%, rgba(32, 69, 94, 0.04) 100%);
            border: 1px solid rgba(139, 46, 34, 0.08);
            border-radius: 18px;
            padding: 1rem 1.05rem;
            margin-bottom: 1rem;
        }

        .ns-summary-label,
        .ns-kicker {
            font-size: 0.78rem;
            font-weight: 800;
            letter-spacing: 0.08em;
            text-transform: uppercase;
            color: var(--ns-accent);
            margin-bottom: 0.45rem;
        }

        .ns-summary-text,
        .ns-card-body {
            color: var(--ns-ink);
            font-size: 0.98rem;
            line-height: 1.72;
        }

        .ns-kpi-grid {
            display: grid;
            grid-template-columns: repeat(2, minmax(0, 1fr));
            gap: 0.8rem;
            margin-bottom: 1rem;
        }

        .ns-kpi-card {
            background: rgba(255, 255, 255, 0.58);
            border: 1px solid rgba(29, 36, 48, 0.08);
            border-radius: 18px;
            padding: 0.95rem 1rem;
        }

        .ns-kpi-label {
            font-size: 0.78rem;
            font-weight: 700;
            letter-spacing: 0.06em;
            text-transform: uppercase;
            color: var(--ns-muted);
            margin-bottom: 0.35rem;
        }

        .ns-kpi-value {
            color: #162332;
            font-size: 1.05rem;
            font-weight: 800;
            line-height: 1.35;
        }

        .ns-chip-row {
            display: flex;
            flex-wrap: wrap;
            gap: 0.45rem;
            margin-top: 0.25rem;
        }

        .ns-chip {
            display: inline-flex;
            align-items: center;
            border-radius: var(--ns-radius-sm);
            padding: 0.34rem 0.72rem;
            font-size: 0.84rem;
            font-weight: 700;
            letter-spacing: -0.01em;
            border: 1px solid rgba(29, 36, 48, 0.08);
            background: rgba(255, 255, 255, 0.62);
            color: #223245;
        }

        .ns-chip-accent {
            background: rgba(139, 46, 34, 0.09);
            color: var(--ns-accent);
        }

        .ns-chip-secondary {
            background: rgba(32, 69, 94, 0.09);
            color: var(--ns-secondary);
        }

        .ns-chip-subtle {
            background: rgba(29, 36, 48, 0.05);
            color: var(--ns-muted);
        }

        .ns-position-strip {
            margin-top: 0.9rem;
            padding: 0.95rem 1rem;
            border-radius: 18px;
            background: rgba(32, 69, 94, 0.07);
            border: 1px solid rgba(32, 69, 94, 0.10);
            color: var(--ns-ink);
            line-height: 1.72;
            font-size: 0.95rem;
        }

        .ns-position-strip strong {
            color: var(--ns-secondary);
        }

        .ns-analysis-card {
            padding: 1.1rem 1.1rem 1rem;
            min-height: 100%;
        }

        .ns-insight-grid {
            display: grid;
            grid-template-columns: repeat(3, minmax(0, 1fr));
            gap: 0.9rem;
            margin-bottom: 1rem;
        }

        .ns-overview-card {
            background: var(--ns-card-strong);
            border: 1px solid var(--ns-border);
            border-radius: 18px;
            box-shadow: var(--ns-shadow);
            padding: 1rem 1rem 0.95rem;
        }

        .ns-overview-header {
            margin: 1.05rem 0 0.85rem;
        }

        .ns-overview-label {
            color: var(--ns-accent);
            font-size: 0.78rem;
            font-weight: 800;
            letter-spacing: 0.08em;
            text-transform: uppercase;
            margin-bottom: 0.45rem;
        }

        .ns-overview-body {
            color: var(--ns-ink);
            font-size: 0.94rem;
            line-height: 1.7;
        }

        .ns-card-title {
            margin: 0 0 0.65rem;
            color: #182230;
            font-size: 1.08rem;
            line-height: 1.35;
        }

        .ns-tone-inline {
            display: inline-flex;
            align-items: center;
            gap: 0.4rem;
            padding: 0.34rem 0.7rem;
            margin-bottom: 0.7rem;
            border-radius: var(--ns-radius-sm);
            background: rgba(139, 46, 34, 0.08);
            color: var(--ns-accent);
            font-size: 0.82rem;
            font-weight: 700;
        }

        .ns-reco-header {
            margin-top: 0.5rem;
            margin-bottom: 0.8rem;
        }

        .ns-reco-title {
            margin: 0;
            font-size: 1.8rem;
            color: #182230;
        }

        .ns-reco-caption,
        .ns-muted-copy {
            color: var(--ns-muted);
            line-height: 1.65;
            font-size: 0.95rem;
        }

        .ns-rec-card {
            padding: 1.15rem 1.15rem 1rem;
            margin-bottom: 0.9rem;
        }

        .ns-rec-topline {
            display: flex;
            justify-content: space-between;
            gap: 1rem;
            align-items: center;
            margin-bottom: 0.65rem;
            flex-wrap: wrap;
        }

        .ns-frame-pill {
            display: inline-flex;
            align-items: center;
            gap: 0.35rem;
            border-radius: var(--ns-radius-sm);
            padding: 0.36rem 0.74rem;
            background: rgba(32, 69, 94, 0.08);
            color: var(--ns-secondary);
            font-size: 0.82rem;
            font-weight: 800;
        }

        .ns-rec-meta {
            color: var(--ns-muted);
            font-size: 0.84rem;
            font-weight: 600;
        }

        .ns-rec-headline {
            margin: 0 0 0.7rem;
            color: #182230;
            font-size: 1.22rem;
            line-height: 1.35;
        }

        .ns-rec-subline {
            color: var(--ns-muted);
            font-size: 0.9rem;
            line-height: 1.6;
            margin-bottom: 0.75rem;
        }

        .ns-rec-guide {
            margin-top: 0.85rem;
            padding: 0.9rem 0.95rem;
            border-radius: 16px;
            background: rgba(32, 69, 94, 0.06);
            border: 1px solid rgba(32, 69, 94, 0.08);
            color: var(--ns-ink);
            line-height: 1.68;
            font-size: 0.94rem;
        }

        .ns-rec-guide strong {
            display: inline-block;
            margin-bottom: 0.28rem;
            color: var(--ns-secondary);
            font-size: 0.78rem;
            letter-spacing: 0.06em;
            text-transform: uppercase;
        }

        .ns-callout {
            padding: 0.95rem 1rem;
            margin-bottom: 1rem;
        }

        .ns-body-panel {
            padding: 0.25rem 0.1rem 0.35rem;
        }

        .ns-body-topline {
            margin-bottom: 0.85rem;
        }

        .ns-body-legend {
            display: flex;
            flex-wrap: wrap;
            gap: 0.5rem;
            margin-bottom: 0.9rem;
        }

        .ns-legend-item {
            display: inline-flex;
            align-items: center;
            gap: 0.42rem;
            padding: 0.38rem 0.68rem;
            border-radius: 999px;
            background: rgba(255, 252, 247, 0.88);
            border: 1px solid rgba(29, 36, 48, 0.08);
            color: var(--ns-muted);
            font-size: 0.82rem;
            line-height: 1.4;
        }

        .ns-body-copy {
            color: var(--ns-ink);
            font-size: 0.98rem;
            line-height: 2.05;
        }

        .ns-annotated-sentence {
            position: relative;
            display: inline;
            cursor: help;
            border-radius: 8px;
            transition: background 0.18s ease;
        }

        .ns-annotated-sentence:hover {
            background: rgba(32, 69, 94, 0.06);
        }

        .ns-annotated-sentence::after {
            content: attr(data-tip);
            position: absolute;
            left: 0;
            bottom: calc(100% + 10px);
            width: min(320px, 75vw);
            opacity: 0;
            pointer-events: none;
            transform: translateY(6px);
            transition: opacity 0.18s ease, transform 0.18s ease;
            background: rgba(24, 34, 48, 0.96);
            color: #f8f2e8;
            padding: 0.72rem 0.8rem;
            border-radius: 14px;
            box-shadow: 0 16px 34px rgba(17, 21, 27, 0.22);
            font-size: 0.82rem;
            line-height: 1.58;
            z-index: 5;
            white-space: normal;
        }

        .ns-annotated-sentence:hover::after {
            opacity: 1;
            transform: translateY(0);
        }

        .ns-mark {
            display: inline;
            padding: 0.02rem 0.18rem;
            border-radius: 6px;
            box-decoration-break: clone;
            -webkit-box-decoration-break: clone;
        }

        .ns-mark-caution {
            background: rgba(139, 46, 34, 0.14);
            color: var(--ns-accent);
            font-weight: 700;
        }

        .ns-mark-metric {
            background: rgba(32, 69, 94, 0.11);
            color: var(--ns-secondary);
            font-weight: 700;
        }

        .ns-mark-quote {
            background: rgba(95, 101, 115, 0.10);
            color: #263243;
            font-weight: 700;
            border-bottom: 1px dashed rgba(29, 36, 48, 0.28);
        }

        .ns-mark-attribution {
            background: rgba(29, 36, 48, 0.06);
            color: #263243;
            font-weight: 700;
        }

        .ns-body-empty {
            color: var(--ns-muted);
            font-size: 0.94rem;
            line-height: 1.7;
        }

        .ns-callout-note {
            background: rgba(32, 69, 94, 0.06);
        }

        .ns-callout-caution {
            background: rgba(139, 46, 34, 0.06);
        }

        .ns-footer-note {
            margin-top: 1rem;
            padding: 1rem 1.1rem;
            background: rgba(29, 36, 48, 0.05);
            border: 1px solid rgba(29, 36, 48, 0.08);
            border-radius: 18px;
            color: var(--ns-muted);
            line-height: 1.7;
            font-size: 0.92rem;
        }

        @media (max-width: 960px) {
            .ns-hero-top {
                grid-template-columns: 1fr;
            }

            .ns-kpi-grid {
                grid-template-columns: 1fr;
            }

            .ns-insight-grid {
                grid-template-columns: 1fr;
            }
        }
        </style>
        """,
        unsafe_allow_html=True,
    )


def render_header() -> None:
    """Render the hero header."""
    st.markdown(
        """
        <section class="ns-hero">
          <div class="ns-hero-top">
            <div>
              <div class="ns-eyebrow">NewSight 리딩 콘솔</div>
              <h1 class="ns-title">같은 사건을<br>다른 시선으로 읽기</h1>
              <p class="ns-lead">
                기사 URL 하나만 넣으면, 텍스트가 어떤 목소리를 앞세우는지 정리하고
                같은 이슈를 다른 프레임으로 다루는 기사를 함께 제안합니다.
              </p>
            </div>
            <aside class="ns-hero-note">
              <strong>이 도구를 보는 법</strong>
              <ul>
                <li>기사의 결론보다 어떤 장면과 목소리를 먼저 보여주는지 봅니다.</li>
                <li>제목, 인용, 누락된 맥락을 함께 보며 읽기 방향을 점검합니다.</li>
                <li>추천 기사에서는 같은 사건을 다른 프레임으로 다루는 지점을 비교합니다.</li>
              </ul>
            </aside>
          </div>
        </section>
        """,
        unsafe_allow_html=True,
    )


def render_status_banner(message: str, tone: str = "note") -> None:
    """Show a styled status banner instead of the default Streamlit alerts."""
    st.markdown(
        f"<div class='ns-callout ns-callout-{tone}'>{_escape(message)}</div>",
        unsafe_allow_html=True,
    )


def render_article_panel(article: dict, analysis: dict) -> None:
    """Show the crawled article metadata and concise summary."""
    issue_tags = analysis.get("issue_tags", [])
    meta_html = (
        f"<div class='ns-meta-line'><strong>언론사</strong> { _escape(article.get('source', '정보 없음')) }"
        f" &nbsp;·&nbsp; <strong>날짜</strong> { _escape(article.get('date', '정보 없음')) }"
        f" &nbsp;·&nbsp; <strong>입력 URL</strong> { _escape(article.get('url', '')) }</div>"
    )
    st.markdown(
        f"""
        <section class="ns-panel">
          <div class="ns-section-title">입력 기사 요약</div>
          <h2 class="ns-article-title">{_escape(article.get('title', '제목 없음'))}</h2>
          {meta_html}
          <div class="ns-summary-box">
            <div class="ns-summary-label">핵심 요약</div>
            <div class="ns-summary-text">{_escape(analysis.get('summary', '요약 정보가 없습니다.'))}</div>
          </div>
          <div class="ns-kpi-grid">
            <div class="ns-kpi-card">
              <div class="ns-kpi-label">대표 프레임</div>
              <div class="ns-kpi-value">{_escape(analysis.get('frame', '정보 없음'))}</div>
            </div>
            <div class="ns-kpi-card">
              <div class="ns-kpi-label">주요 목소리</div>
              <div class="ns-kpi-value">{_escape(analysis.get('primary_voice', '정보 없음'))}</div>
            </div>
          </div>
          <div class="ns-kicker">이슈 태그</div>
          {_render_tag_row(issue_tags, tone='accent')}
          <div class="ns-position-strip"><strong>한눈에 읽는 포지션</strong><br>{_escape(_build_position_summary(analysis))}</div>
        </section>
        """,
        unsafe_allow_html=True,
    )

    with st.expander("본문 미리보기", expanded=False):
        st.markdown(
            _render_body_preview_html(article.get("body", "")),
            unsafe_allow_html=True,
        )


def render_analysis_overview(analysis: dict) -> None:
    """Show the three most useful reading aids first."""
    st.markdown(
        """
        <div class="ns-overview-header">
          <div class="ns-section-title">읽기 체크포인트</div>
        </div>
        """,
        unsafe_allow_html=True,
    )
    cards = [
        ("이 기사만 읽으면 무엇이 가장 중요해 보이나", analysis.get("framing_analysis", "분석 결과가 없습니다.")),
        ("앞으로 들리는 목소리와 뒤로 밀리는 목소리", analysis.get("citation_analysis", "분석 결과가 없습니다.")),
        ("추천 기사에서 꼭 확인할 비교 질문", analysis.get("missing_perspective", "분석 결과가 없습니다.")),
    ]
    columns = st.columns(3, gap="medium")
    for index, (label, body) in enumerate(cards):
        with columns[index]:
            st.markdown(
                f"""
                <section class="ns-overview-card">
                  <div class="ns-overview-label">{_escape(label)}</div>
                  <div class="ns-overview-body">{_escape(body)}</div>
                </section>
                """,
                unsafe_allow_html=True,
            )


def _analysis_card(title: str, body: str, tone: str | None = None) -> str:
    """Render one stylized analysis card."""
    tone_html = ""
    if tone:
        tone_html = f"<div class='ns-tone-inline'>어조 · {_escape(tone)}</div>"

    return f"""
        <section class="ns-analysis-card">
          <h3 class="ns-card-title">{_escape(title)}</h3>
          {tone_html}
          <div class="ns-card-body">{_escape(body)}</div>
        </section>
    """


def render_analysis_panel(analysis: dict) -> None:
    """Display the media-literacy analysis in a readable editorial layout."""
    st.markdown("<div class='ns-section-title'>AI 미디어 리터러시 분석</div>", unsafe_allow_html=True)
    render_analysis_overview(analysis)
    col_a, col_b = st.columns(2, gap="medium")

    cards = [
        (
            "표현과 어조",
            analysis.get("language_analysis", "분석 결과가 없습니다."),
            analysis.get("tone", "정보 없음"),
        ),
        (
            "제목과 본문 관계",
            analysis.get("title_body_gap", "분석 결과가 없습니다."),
            None,
        ),
        (
            "추천 기사에서 확인할 차이",
            _build_comparison_hint(analysis),
            None,
        ),
    ]

    for index, card in enumerate(cards):
        column = col_a if index % 2 == 0 else col_b
        with column:
            st.markdown(_analysis_card(*card), unsafe_allow_html=True)


def render_recommendations(recommendation_result: dict) -> None:
    """Render recommended articles that present another angle."""
    recommendations = recommendation_result.get("articles", [])
    heading = recommendation_result.get("heading", "다른 관점 추천 기사")
    caption = recommendation_result.get("caption", "")

    st.divider()
    st.markdown(
        f"""
        <div class="ns-reco-header">
          <div class="ns-section-title">비교 읽기</div>
          <h2 class="ns-reco-title">{_escape(heading)}</h2>
          <div class="ns-reco-caption">{_escape(caption)}</div>
        </div>
        """,
        unsafe_allow_html=True,
    )

    if not recommendations:
        render_status_banner(
            "현재 로컬 추천 DB 기준으로는 겹치는 이슈 태그를 가진 다른 프레임의 기사를 찾지 못했습니다.",
            tone="note",
        )
        return

    for rec in recommendations:
        issue_tags = rec.get("issue_tags", [])
        sub_issue = str(rec.get("sub_issue", "")).strip()
        memo = str(rec.get("memo", "")).strip()
        tone = str(rec.get("tone", "")).strip()
        primary_voice = str(rec.get("primary_voice", "")).strip()
        subline_parts = [part for part in [sub_issue, tone, primary_voice] if part]
        subline = " · ".join(subline_parts)
        st.markdown(
            f"""
            <section class="ns-rec-card">
              <div class="ns-rec-topline">
                <span class="ns-frame-pill">{_escape(rec.get('frame', '프레임 정보 없음'))}</span>
                <span class="ns-rec-meta">{_escape(rec.get('source', '출처 정보 없음'))} · {_escape(rec.get('date', '날짜 정보 없음'))}</span>
              </div>
              <h3 class="ns-rec-headline">{_escape(rec.get('title', '제목 없음'))}</h3>
              {"<div class='ns-rec-subline'>" + _escape(subline) + "</div>" if subline else ""}
              {_render_tag_row(issue_tags, tone='secondary')}
              {"<div class='ns-rec-guide'><strong>왜 같이 보면 좋은가</strong><br>" + _escape(memo) + "</div>" if memo else ""}
            </section>
            """,
            unsafe_allow_html=True,
        )
        st.link_button("기사 보러 가기", rec.get("url", ""), use_container_width=True)


def render_external_candidates(candidates: list[dict], guidance: dict | None = None) -> None:
    """Render externally searched related articles when the local DB has no match."""
    st.divider()
    st.markdown(
        """
        <div class="ns-reco-header">
          <div class="ns-section-title">외부 탐색</div>
          <h2 class="ns-reco-title">외부 관련 기사 후보</h2>
          <div class="ns-reco-caption">아직 반대 프레임으로 검증된 기사는 아니지만, 같은 이슈를 더 넓게 비교해볼 수 있는 후보를 보여드립니다.</div>
        </div>
        """,
        unsafe_allow_html=True,
    )

    if not candidates:
        render_status_banner("외부 관련 기사 후보도 찾지 못했습니다.", tone="caution")
        return

    guidance = guidance or {}
    query = candidates[0].get("search_query", "")
    if query:
        st.markdown(
            f"<div class='ns-muted-copy' style='margin-bottom: 0.9rem;'><strong>검색어</strong> {_escape(query)}</div>",
            unsafe_allow_html=True,
        )

    overall_note = guidance.get("overall_note", "")
    if overall_note:
        render_status_banner(overall_note, tone="note")

    if guidance.get("explanation_notice"):
        st.markdown(
            f"<div class='ns-muted-copy' style='margin-bottom: 0.9rem;'>{_escape(guidance['explanation_notice'])}</div>",
            unsafe_allow_html=True,
        )

    guidance_candidates = guidance.get("candidates", [])

    for index, candidate in enumerate(candidates):
        guide = guidance_candidates[index] if index < len(guidance_candidates) else {}
        st.markdown(
            f"""
            <section class="ns-rec-card">
              <div class="ns-rec-topline">
                <span class="ns-frame-pill">비교 후보</span>
                <span class="ns-rec-meta">{_escape(candidate.get('source', '출처 정보 없음'))} · {_escape(candidate.get('date', '날짜 정보 없음'))}</span>
              </div>
              <h3 class="ns-rec-headline">{_escape(candidate.get('title', '제목 없음'))}</h3>
              <div class="ns-card-body">
                <strong>왜 같이 보면 좋은가</strong><br>{_escape(guide.get('why_relevant', '입력 기사와 연관된 주제를 다룰 가능성이 있어 비교 후보로 제시되었습니다.'))}
              </div>
              <div class="ns-card-body" style="margin-top: 0.8rem;">
                <strong>비교 포인트</strong><br>{_escape(guide.get('what_to_compare', '입력 기사에서 덜 다뤄진 이해관계자, 근거, 강조점을 함께 비교해보세요.'))}
              </div>
            </section>
            """,
            unsafe_allow_html=True,
        )
        snippet = candidate.get("snippet", "")
        if snippet:
            with st.expander("검색 요약 보기", expanded=False):
                st.write(snippet)
        st.link_button("후보 기사 보러 가기", candidate.get("url", ""), use_container_width=True)


def main() -> None:
    """Entry point for the Streamlit app."""
    st.set_page_config(page_title="NewSight | AI 뉴스 관점 분석", page_icon="🔎", layout="wide")
    inject_styles()
    render_header()

    with st.form("newsight_url_form", clear_on_submit=False):
        st.markdown("<div class='ns-section-title'>입력 기사</div>", unsafe_allow_html=True)
        news_url = st.text_input(
            "뉴스 기사 링크를 붙여넣어 주세요.",
            placeholder="https://news.naver.com/main/read.nhn?...",
        )
        submit_col_left, submit_col_right = st.columns([7, 2])
        with submit_col_right:
            start_button = st.form_submit_button("분석 시작", use_container_width=True, type="primary")

    st.divider()

    if start_button:
        if not news_url.strip():
            render_status_banner("분석할 뉴스 URL을 입력해 주세요.", tone="caution")
        else:
            with st.spinner("기사 본문을 추출하고, 비교 읽기에 필요한 단서를 정리하고 있습니다..."):
                article = fetch_article(news_url.strip())

                if article is None:
                    st.error("기사 제목 또는 본문을 추출하지 못했습니다. 다른 기사 URL로 다시 시도해 주세요.")
                    st.stop()

                analysis = analyze_article(article)
                recommendation_result = recommend_articles(article, analysis, limit=3)
                recommendations = recommendation_result.get("articles", [])
                external_candidates = []
                external_guidance = {}

                if not recommendations:
                    external_candidates = search_related_articles(article, analysis, limit=3)
                    if external_candidates:
                        external_guidance = explain_external_candidates(article, analysis, external_candidates)

            render_status_banner("분석이 완료되었습니다. 아래에서 기사 요약, 관점 분석, 비교 추천을 순서대로 확인할 수 있습니다.", tone="note")

            if analysis.get("analysis_notice"):
                st.markdown(
                    f"<div class='ns-muted-copy' style='margin: 0.8rem 0 1rem;'>{_escape(analysis['analysis_notice'])}</div>",
                    unsafe_allow_html=True,
                )

            render_article_panel(article, analysis)
            st.write("")
            render_analysis_panel(analysis)

            if recommendations:
                render_recommendations(recommendation_result)
            else:
                render_status_banner(
                    "검수본과 자동 태깅 확장 DB에서 적절한 다른 프레임 기사를 찾지 못해, 외부 기사 후보를 함께 보여드립니다.",
                    tone="note",
                )
                render_external_candidates(external_candidates, external_guidance)

    st.markdown(
        """
        <div class="ns-footer-note">
          <strong>안내</strong><br>
          NewSight의 분석은 절대적인 정치적 판단이 아니라, 독자의 비판적 뉴스 읽기를 돕는 참고 자료입니다.
          실제 맥락을 이해하기 위해서는 입력 기사와 함께 추천 기사 원문도 직접 비교해 읽는 것을 권장합니다.
        </div>
        """,
        unsafe_allow_html=True,
    )


if __name__ == "__main__":
    main()
