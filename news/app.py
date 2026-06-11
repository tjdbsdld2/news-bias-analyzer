"""NewSight Flask application."""

from __future__ import annotations

import difflib
import html
import logging
import os
import re
from urllib.parse import urlparse

from dotenv import load_dotenv
from flask import Flask, jsonify, render_template, request
from flask_cors import CORS

from analyzer import analyze_article, explain_external_candidates
from crawler import fetch_article
from recommender import recommend_articles
from searcher import search_related_articles


load_dotenv()

app = Flask(__name__, template_folder="templates", static_folder="static")
CORS(app)
logger = logging.getLogger(__name__)


DATE_TIME_PATTERN = re.compile(
    r"""
    (?:
        (?:오전|오후)\s*\d{1,2}시(?:\s*\d{1,2}분)? |
        \d{1,2}시(?:\s*\d{1,2}분)? |
        \d{1,2}분 |
        (?:지난|오는|전날|당일)?\s*\d{1,2}일 |
        \d{1,2}월\s*\d{1,2}일 |
        \d{4}년(?:\s*\d{1,2}월(?:\s*\d{1,2}일)?)? |
        \d+\s*(?:번|차|번째|회차)
    )
    """,
    re.VERBOSE,
)

SIGNIFICANT_METRIC_PATTERN = re.compile(
    r"""
    (?:
        (?:전년|전월|전분기|작년)\s*대비\s*\d[\d,]*(?:\.\d+)?\s*%\s*(?:증가|감소|상승|하락)? |
        (?:매출|영업이익|점유율|비중|온라인\s*비중|고용|손실)\s*\d[\d,]*(?:\.\d+)?\s*% |
        \d[\d,]*(?:\.\d+)?\s*%\s*(?:증가|감소|상승|하락|비중|점유율)? |
        \d[\d,]*(?:\.\d+)?\s*(?:명|곳|건|개)\s*(?:매장|점포|업체|물류\s*거점|폐점|고용\s*불안|인력|노동자|사업장)? |
        \d[\d,]*(?:\.\d+)?\s*(?:조|억|만)?\s*원\s*(?:매출|손실|감소|증가|영업이익|적자|흑자)? |
        (?:매출|영업이익|점유율|비중|손실)\s*\d[\d,]*(?:\.\d+)?\s*(?:조|억|만)?\s*원
    )
    """,
    re.VERBOSE,
)

CAUTION_PATTERN = re.compile(
    r"논란|의혹|반발|우려|비판|공방|봉쇄|감금|책임(?!자)|사과|실패|부족|피해|강행|부담|혼란|참담함|충돌|무효|사퇴|진상규명"
)

HIGHLIGHT_RULES = [
    ("quote", re.compile(r"[\"“][^\"”]{2,120}[\"”]")),
    ("metric", SIGNIFICANT_METRIC_PATTERN),
    ("caution", CAUTION_PATTERN),
    (
        "attribution",
        re.compile(
            r"밝혔(?:다|습니다)?|설명했(?:다|습니다)?|말했(?:다|습니다)?|주장했(?:다|습니다)?|전했다|강조했(?:다|습니다)?|사과했(?:다|습니다)?|촉구했(?:다|습니다)?"
        ),
    ),
]

CAUTION_GROUPS = {
    "갈등 쟁점": {"논란", "반발", "비판", "공방", "봉쇄", "충돌", "강행"},
    "책임 쟁점": {"책임", "사과", "실패", "무효", "사퇴", "진상규명"},
    "피해 관점": {"피해", "부족", "부담", "혼란", "우려", "참담함"},
}

KEY_ACTION_PATTERN = re.compile(
    r"상정(?:됐|되었|된다)|통과(?:됐|되었|된다)|추진(?:한|한다|하겠)|허용(?:한|한다|하겠)|"
    r"개정(?:한|된다|하겠)|발표(?:했|한다)|도입(?:한|한다)|확대(?:한|한다)|축소(?:한|한다)|"
    r"제시(?:했|한다)|예고(?:했|한다)|요구(?:했|한다)|촉구(?:했|한다)|나섰(?:다|습니다)"
)

ANNOTATED_SENTENCE_LIMIT = 20
BODY_REST_CHAR_LIMIT = 900
HIGHLIGHT_MATCH_THRESHOLD = 0.84
VALID_URL_MESSAGE = "올바른 뉴스 기사 URL을 입력해 주세요. 예: https://..."
ARTICLE_EXTRACTION_FAILURE_MESSAGE = (
    "기사 본문을 충분히 추출하지 못했습니다. 언론사 원문 링크를 입력하거나 다른 기사 URL로 다시 시도해 주세요."
)
NO_RECOMMENDATION_MESSAGE = (
    "현재 로컬 DB와 외부 검색에서 비교할 만한 기사 후보를 찾지 못했습니다. 다른 기사 URL로 다시 시도해 주세요."
)
EXTERNAL_SEARCH_FAILURE_MESSAGE = "외부 관련 기사 후보를 찾지 못했습니다."
EVIDENCE_CUE_PATTERN = re.compile(
    r"자료|통계|조사|집계|보고서|설문|발표|공시|백서|브리핑|기자회견|질의응답|전망|예상|전했다|밝혔다|설명했다|따르면"
)
LIST_LIKE_MARKER_PATTERN = re.compile(
    r"등이\s*(?:참가|참석|배석|만난다|만날\s*예정)|비롯해|잇달아\s*찾아|주요\s*경영진|참가한다|참석한다"
)
DIRECT_QUOTE_PATTERN = re.compile(r"[\"“][^\"”]{2,120}[\"”]")


def _validate_input_url(url: str) -> str | None:
    """Reject obviously invalid or dangerous URL inputs before crawling."""
    if not url or len(url.strip()) < 12:
        return VALID_URL_MESSAGE

    lowered = url.strip().lower()
    if lowered.startswith(("javascript:", "data:", "file:")):
        return VALID_URL_MESSAGE

    try:
        parsed = urlparse(url)
    except ValueError:
        return VALID_URL_MESSAGE

    if parsed.scheme not in {"http", "https"}:
        return VALID_URL_MESSAGE
    if not parsed.netloc or "." not in parsed.netloc:
        return VALID_URL_MESSAGE
    if len(url) > 2048:
        return VALID_URL_MESSAGE

    return None


def _article_payload_is_usable(article: dict | None) -> bool:
    """Double-check crawler output before sending it to the analyzer."""
    if not isinstance(article, dict):
        return False

    title = str(article.get("title", "")).strip()
    body = str(article.get("body", "")).strip()
    if not title or not body:
        return False
    if len(body) < 200:
        return False
    return True


def _split_sentences(text: str) -> list[str]:
    """Split article body into readable sentence-like chunks."""
    normalized = re.sub(r"\s+", " ", (text or "").strip())
    if not normalized:
        return []

    parts = re.split(
        r"(?<=[.!?])\s+|(?<=다\.)\s+|(?<=요\.)\s+|(?<=죠\.)\s+|(?<=다)\s+(?=[\"'“‘A-Z가-힣])",
        normalized,
    )
    sentences = [part.strip() for part in parts if part.strip()]
    return sentences or [normalized]


def _mask_date_time_tokens(text: str) -> str:
    """Mask date/time/order tokens while preserving string length."""
    return DATE_TIME_PATTERN.sub(lambda match: " " * len(match.group(0)), text)


def _find_significant_metric(sentence: str) -> re.Match[str] | None:
    """Find only meaningful statistical or scale-related numbers."""
    masked = _mask_date_time_tokens(sentence)
    return SIGNIFICANT_METRIC_PATTERN.search(masked)


def _iter_significant_metric_matches(sentence: str):
    """Yield meaningful metric matches with original string offsets preserved."""
    masked = _mask_date_time_tokens(sentence)
    return SIGNIFICANT_METRIC_PATTERN.finditer(masked)


def _find_caution_term(sentence: str) -> str | None:
    """Return the first caution term worth surfacing, avoiding false positives like 책임자."""
    match = CAUTION_PATTERN.search(sentence)
    return match.group(0) if match else None


def _build_body_focus_note(labels: list[str], custom_focus: str = "") -> str:
    """Summarize what kinds of highlighted sentences the reader should pay attention to."""
    if custom_focus:
        return custom_focus

    if not labels:
        return "표시된 문장은 기사 방향을 크게 정하는 부분입니다. 초반 핵심 서술, 근거 제시, 관점 전환 문장을 중심으로 비교해 보세요."

    ordered: list[str] = []
    for label in labels:
        if label not in ordered:
            ordered.append(label)

    mapping = {
        "핵심 주장": "기사의 결론이나 조치가 드러나는 문장",
        "핵심 서술": "기사 초반의 문제 설정 문장",
        "직접 발화": "누가 어떤 표현을 직접 말했는지 보여주는 문장",
        "주장 전달": "특정 주체의 설명이 실리는 문장",
        "관점 전환": "반면, 한편처럼 흐름이 바뀌는 문장",
        "근거 제시": "수치나 사례로 주장을 받치는 문장",
        "갈등 쟁점": "대립이나 충돌을 크게 보이게 하는 문장",
        "책임 쟁점": "책임 소재를 읽게 하는 문장",
        "피해 관점": "손실이나 피해를 앞세우는 문장",
        "출처 흐림": "판단 주체가 흐려지는 문장",
    }
    fragments = [mapping[label] for label in ordered[:3] if label in mapping]
    if not fragments:
        return "표시된 문장은 기사 방향을 크게 정하는 부분입니다. 초반 핵심 서술, 근거 제시, 관점 전환 문장을 중심으로 비교해 보세요."

    return f"표시된 문장은 기사 방향을 크게 정하는 부분입니다. 특히 {' / '.join(fragments)}을 중심으로 읽어보면 도움이 됩니다."


def _compact_sentence(text: str) -> str:
    """Compact a sentence for tolerant matching between LLM output and article text."""
    normalized = html.unescape(text or "")
    normalized = normalized.replace("“", '"').replace("”", '"').replace("’", "'").replace("‘", "'")
    normalized = re.sub(r"\s+", "", normalized)
    normalized = re.sub(r"[\"'`·….,!?;:()\[\]{}<>]", "", normalized)
    return normalized


def _match_llm_highlights(
    sentences: list[str], reading_highlights: list[dict]
) -> dict[int, tuple[str, str]]:
    """Match LLM-selected highlight sentences back to preview sentences."""
    if not sentences or not isinstance(reading_highlights, list):
        return {}

    compact_sentences = [_compact_sentence(sentence) for sentence in sentences]
    used_indices: set[int] = set()
    matched: dict[int, tuple[str, str]] = {}

    for item in reading_highlights:
        if not isinstance(item, dict):
            continue

        target_sentence = str(item.get("sentence", "")).strip()
        role = str(item.get("role", "")).strip()
        note = str(item.get("note", "")).strip()
        compact_target = _compact_sentence(target_sentence)

        if not compact_target or not role or not note:
            continue

        best_index: int | None = None
        best_score = 0.0
        for index, compact_sentence in enumerate(compact_sentences):
            if index in used_indices or not compact_sentence:
                continue

            if compact_sentence == compact_target:
                best_index = index
                best_score = 1.0
                break

            if compact_target in compact_sentence or compact_sentence in compact_target:
                score = min(len(compact_target), len(compact_sentence)) / max(
                    len(compact_target), len(compact_sentence)
                )
            else:
                score = difflib.SequenceMatcher(None, compact_target, compact_sentence).ratio()

            if score > best_score:
                best_score = score
                best_index = index

        if best_index is None or best_score < HIGHLIGHT_MATCH_THRESHOLD:
            continue

        matched_sentence = sentences[best_index]
        if not _is_actionable_llm_highlight(matched_sentence, role, note):
            continue

        matched[best_index] = (role, note)
        used_indices.add(best_index)

    return matched


def _looks_like_entity_list(sentence: str) -> bool:
    """Detect list-heavy sentences that rarely deserve standalone hover notes."""
    separator_count = sentence.count(",") + sentence.count("·") + sentence.count("ㆍ")
    if separator_count < 2:
        return False

    if LIST_LIKE_MARKER_PATTERN.search(sentence):
        return True

    role_word_hits = len(re.findall(r"(회장|사장|대표|의장|부회장|CTO|CEO|경영진)", sentence))
    return role_word_hits >= 3


def _is_actionable_llm_highlight(sentence: str, role: str, note: str) -> bool:
    """Keep only LLM highlights that feel like real reading aids, not stray lists."""
    compact = sentence.strip()
    if len(compact) < 18:
        return False

    has_quote = bool(DIRECT_QUOTE_PATTERN.search(compact))
    has_metric = bool(_find_significant_metric(compact))
    has_caution = bool(_find_caution_term(compact))
    has_contrast = bool(re.search(r"반면|하지만|그러나|다만|한편", compact))
    has_key_action = bool(KEY_ACTION_PATTERN.search(compact))
    has_evidence_cue = bool(EVIDENCE_CUE_PATTERN.search(compact))
    looks_like_list = _looks_like_entity_list(compact)

    if role == "직접 발화":
        return has_quote

    if role == "관점 전환":
        return has_contrast

    if role == "근거 제시":
        if looks_like_list and not (has_metric or has_quote):
            return False
        return has_metric or has_quote or has_evidence_cue

    if role in {"핵심 주장", "핵심 서술"}:
        if looks_like_list and not (has_key_action or has_caution or has_quote):
            return False
        return has_key_action or has_caution or has_quote or has_metric or len(note.strip()) >= 24

    if role in {"갈등 쟁점", "책임 쟁점", "피해 관점", "주의 표현"}:
        return has_caution

    if role == "주장 전달":
        return bool(re.search(r"밝혔(?:다|습니다)?|설명했(?:다|습니다)?|말했(?:다|습니다)?|주장했(?:다|습니다)?|전했다|강조했(?:다|습니다)?", compact))

    return not looks_like_list


def _sentence_tooltip(sentence: str, sentence_index: int = 0) -> tuple[str, str] | None:
    """Generate a label and a short hover explanation for one sentence."""
    quote_match = re.search(r"[\"“][^\"”]{2,120}[\"”]", sentence)
    attribution_match = re.search(
        r"밝혔(?:다|습니다)?|설명했(?:다|습니다)?|말했(?:다|습니다)?|주장했(?:다|습니다)?|전했다|강조했(?:다|습니다)?|사과했(?:다|습니다)?|촉구했(?:다|습니다)?",
        sentence,
    )
    vague_match = re.search(r"지적된다|우려된다", sentence)
    contrast_match = re.search(r"반면|하지만|그러나|다만|한편", sentence)
    key_action_match = KEY_ACTION_PATTERN.search(sentence)
    caution_term = _find_caution_term(sentence)

    if quote_match and attribution_match:
        quote = quote_match.group(0)
        clipped = quote if len(quote) <= 20 else f"{quote[:18]}…"
        return (
            "직접 발화",
            f"{clipped}처럼 발화가 그대로 실려 있습니다. 누가 오래 말하고, 반대 주체의 발언도 같은 밀도로 실리는지 비교해 보세요.",
        )

    if caution_term:
        pivot = caution_term
        label = "주의 표현"
        message = f"'{pivot}' 같은 표현이 사건을 특정 문제로 읽게 만듭니다. 이 단어가 사실 설명인지 평가인지 구분해서 보세요."
        for group_label, terms in CAUTION_GROUPS.items():
            if pivot in terms:
                label = group_label
                break
        if label == "갈등 쟁점":
            message = f"'{pivot}'처럼 대립을 크게 보이게 하는 단어가 들어 있습니다. 실제 쟁점 설명보다 충돌 장면이 앞서는지 함께 보세요."
        elif label == "책임 쟁점":
            message = f"'{pivot}'처럼 책임 소재를 읽게 하는 표현입니다. 누구의 책임이 구체적으로 설명되는지, 빠진 주체는 없는지 확인해 보세요."
        elif label == "피해 관점":
            message = f"'{pivot}'처럼 손실이나 피해를 떠올리게 하는 단어가 쓰였습니다. 피해 주체가 누구인지, 반대 효과는 다뤄지는지 같이 보세요."
        return (label, message)

    if attribution_match:
        verb = attribution_match.group(0)
        return (
            "주장 전달",
            f"'{verb}'처럼 누군가의 설명을 전달하는 문장입니다. 같은 사안에서 다른 주체의 설명도 비슷한 비중으로 실리는지 비교해 보세요.",
        )

    if contrast_match:
        marker = contrast_match.group(0)
        return (
            "관점 전환",
            f"'{marker}' 이후에 논점이 바뀌는 문장입니다. 앞문장과 무엇이 달라지는지 보면 기사 안의 우선순위 이동이 잘 보입니다.",
        )

    if key_action_match:
        pivot = key_action_match.group(0)
        return (
            "핵심 주장",
            f"'{pivot}'처럼 기사 핵심 조치나 입장 변화가 드러나는 문장입니다. 독자가 이 사안을 어떤 문제로 읽게 만드는지 기준점이 되는 문장으로 보세요.",
        )

    metric_match = _find_significant_metric(sentence)
    if metric_match:
        metric = sentence[metric_match.start() : metric_match.end()].strip()
        return (
            "근거 제시",
            f"'{metric}'처럼 통계나 규모가 주장을 떠받치는 근거로 놓였습니다. 이 수치의 출처와 비교 기준이 함께 설명되는지 확인해 보세요.",
        )

    if vague_match:
        return (
            "출처 흐림",
            "판단의 출처가 직접 드러나지 않는 배경 설명 문장입니다. 누가 그렇게 보거나 우려하는지 다른 문장에서 확인해 보세요.",
        )

    if sentence_index < 2 and len(sentence) >= 28:
        return (
            "핵심 서술",
            "기사 초반에 배치된 문장입니다. 이 문장이 독자가 사건을 처음 어떤 구도로 받아들이는지 결정하는 경우가 많습니다.",
        )

    return None


def _highlight_sentence(sentence: str) -> str:
    """Wrap notable expressions inside a sentence with styled spans."""
    matches: list[tuple[int, int, str]] = []
    priority = {"quote": 0, "caution": 1, "metric": 2, "attribution": 3}

    for tone, pattern in HIGHLIGHT_RULES:
        iterator = _iter_significant_metric_matches(sentence) if tone == "metric" else pattern.finditer(sentence)
        for match in iterator:
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


def _sentence_note_class(label: str) -> str:
    """Map tooltip labels to stable CSS classes for annotated sentences."""
    mapping = {
        "핵심 주장": "note-core",
        "핵심 서술": "note-core",
        "근거 제시": "note-evidence",
        "관점 전환": "note-shift",
        "직접 발화": "note-quote",
        "주장 전달": "note-claim",
        "갈등 쟁점": "note-conflict",
        "책임 쟁점": "note-responsibility",
        "피해 관점": "note-harm",
        "주의 표현": "note-caution",
        "출처 흐림": "note-blur",
    }
    return mapping.get(label, "note-generic")


def _render_body_preview_html(body: str, analysis: dict | None = None) -> str:
    """Build annotated body preview HTML with hover explanations."""
    sentences = _split_sentences(body)
    if not sentences:
        return "<div class='ns-body-empty'>본문 정보가 없습니다.</div>"

    annotated_sentences = sentences[:ANNOTATED_SENTENCE_LIMIT]
    remaining_sentences = sentences[ANNOTATED_SENTENCE_LIMIT:]
    reading_highlights = []
    reading_focus = ""
    if isinstance(analysis, dict):
        raw_highlights = analysis.get("reading_highlights", [])
        if isinstance(raw_highlights, list):
            reading_highlights = raw_highlights
        reading_focus = str(analysis.get("reading_focus", "")).strip()

    llm_highlight_map = _match_llm_highlights(annotated_sentences, reading_highlights)
    use_llm_highlights = bool(llm_highlight_map)

    assigned_tips: list[tuple[str, str] | None] = []
    for index, sentence in enumerate(annotated_sentences):
        llm_tip = llm_highlight_map.get(index)
        rule_tip = _sentence_tooltip(sentence, sentence_index=index)
        assigned_tips.append(llm_tip or rule_tip)

    if annotated_sentences and not any(assigned_tips):
        fallback_index = 0
        for index, sentence in enumerate(annotated_sentences):
            if len(sentence.strip()) >= 18:
                fallback_index = index
                break
        assigned_tips[fallback_index] = (
            "핵심 서술",
            "이 문장을 기준점으로 두고 기사가 사건을 처음 어떤 방향으로 읽게 만드는지 확인해 보세요.",
        )

    sentence_html = []
    active_labels: list[str] = []
    for sentence, tip in zip(annotated_sentences, assigned_tips):
        if tip is None:
            sentence_html.append(html.escape(sentence))
            continue

        tip_label, tooltip = tip
        active_labels.append(tip_label)
        label_class = _sentence_note_class(tip_label)
        sentence_html.append(
            f"<span class='ns-annotated-sentence {label_class}' "
            f"data-tip-label='{html.escape(tip_label, quote=True)}' "
            f"data-tip='{html.escape(tooltip, quote=True)}'>"
            f"{_highlight_sentence(sentence)}</span>"
        )

    body_html = " ".join(sentence_html)
    focus_note = _build_body_focus_note(active_labels, custom_focus=reading_focus if use_llm_highlights else "")
    rest_html = ""
    if remaining_sentences:
        rest_text = " ".join(remaining_sentences).strip()
        if len(rest_text) > BODY_REST_CHAR_LIMIT:
            rest_text = f"{rest_text[:BODY_REST_CHAR_LIMIT].rstrip()}..."
        rest_html = f"""
          <div class="ns-body-rest">
            <div class="ns-mini-label">이후 본문 미리보기</div>
            <p class="ns-body-rest-copy">{html.escape(rest_text)}</p>
          </div>
        """

    return f"""
        <div class="ns-body-panel">
          <div class="ns-body-topline">
            <div class="ns-panel-kicker">문장별 읽기 보조</div>
            <div class="ns-panel-note">표시된 문장에 커서를 올리면 이 문장이 기사 안에서 어떤 역할을 하는지 짧은 메모가 나타납니다.</div>
          </div>
          <div class="ns-inline-note">본문 미리보기는 추출된 원문을 바탕으로 표시하고, 강조 메모만 AI가 덧붙입니다.</div>
          <div class="ns-body-focus-note">{html.escape(focus_note)}</div>
          <div class="ns-body-legend">
            <span class="ns-legend-item"><span class="ns-mark ns-mark-caution">핵심 주장</span> 기사의 주요 결론이나 입장을 드러내는 문장</span>
            <span class="ns-legend-item"><span class="ns-mark ns-mark-metric">근거 제시</span> 수치, 사례, 인용으로 주장을 뒷받침하는 문장</span>
            <span class="ns-legend-item"><span class="ns-mark ns-mark-quote">관점 전환</span> 앞뒤 문장과 다른 시각이나 반론을 제시하는 문장</span>
          </div>
          <div class="ns-body-copy">{body_html}</div>
          {rest_html}
        </div>
    """


def _build_position_summary(analysis: dict) -> str:
    """Create a short one-line reading orientation sentence."""
    frame = str(analysis.get("frame", "")).strip() or "정보 없음"
    voice = str(analysis.get("primary_voice", "")).strip() or "정보 없음"
    tone = str(analysis.get("tone", "")).strip() or "정보 없음"
    return (
        f"이 기사는 '{frame}' 프레임으로 사건을 정리하고 '{voice}'의 설명과 발화를 중심 근거로 배치하며, "
        f"전체 어조는 '{tone}'에 가깝습니다."
    )


def _build_comparison_hint(analysis: dict) -> str:
    """Turn the analysis into a concrete next-step comparison hint."""
    voice = str(analysis.get("primary_voice", "")).strip() or "현재 기사에서 가장 크게 들리는 주체"
    frame = str(analysis.get("frame", "")).strip() or "현재 기사 프레임"
    return (
        f"다음 기사에서는 '{voice}' 대신 누구의 설명과 인용이 중심 근거가 되는지, "
        f"같은 사안을 '{frame}'보다 어떤 쟁점으로 먼저 읽게 만드는지 함께 확인해 보세요. "
        "특히 빠져 있던 이해관계자나 배경 근거가 실제로 보완되는지 비교하면 도움이 됩니다."
    )


def _serialize_article(article: dict, analysis: dict) -> dict:
    """Prepare article metadata for the frontend."""
    return {
        "title": article.get("title", "제목 없음"),
        "source": article.get("source", "출처 정보 없음"),
        "date": article.get("date", "날짜 정보 없음"),
        "url": article.get("url", ""),
        "body_preview_html": _render_body_preview_html(article.get("body", ""), analysis),
        "position_summary": _build_position_summary(analysis),
    }


def _serialize_analysis(analysis: dict) -> dict:
    """Add UI-friendly derived fields to the analysis payload."""
    payload = dict(analysis)
    payload["position_summary"] = _build_position_summary(analysis)
    payload["comparison_hint"] = _build_comparison_hint(analysis)
    return payload


@app.route("/")
def index() -> str:
    """Render the NewSight landing page."""
    return render_template("index.html")


@app.post("/api/analyze")
def analyze() -> tuple[dict, int] | tuple[object, int]:
    """Analyze one input URL and return article, analysis, and recommendations."""
    try:
        payload = request.get_json(silent=True) or {}
        url = str(payload.get("url", "")).strip()
        validation_error = _validate_input_url(url)
        if validation_error:
            return jsonify({"message": validation_error, "tone": "caution"}), 400

        article = fetch_article(url)
        if not _article_payload_is_usable(article):
            return jsonify({"message": ARTICLE_EXTRACTION_FAILURE_MESSAGE, "tone": "caution"}), 422

        analysis = analyze_article(article)
        recommendation_result = recommend_articles(article, analysis, limit=3)

        external_candidates: list[dict] = []
        external_guidance: dict = {}
        external_message = ""
        if not recommendation_result.get("articles"):
            if recommendation_result.get("notice"):
                external_message = str(recommendation_result.get("notice", "")).strip()
            external_candidates = search_related_articles(article, analysis, limit=3)
            if external_candidates:
                external_guidance = explain_external_candidates(article, analysis, external_candidates)
            else:
                external_message = external_message or EXTERNAL_SEARCH_FAILURE_MESSAGE

        if not recommendation_result.get("articles") and not external_candidates:
            external_message = NO_RECOMMENDATION_MESSAGE

        return (
            jsonify(
                {
                    "article": _serialize_article(article, analysis),
                    "analysis": _serialize_analysis(analysis),
                    "recommendations": recommendation_result,
                    "external": {
                        "candidates": external_candidates,
                        "guidance": external_guidance,
                        "message": external_message,
                    },
                }
            ),
            200,
        )
    except Exception as exc:
        logger.exception("Unexpected /api/analyze failure: %s", exc)
        return (
            jsonify(
                {
                    "message": "분석 중 예기치 않은 오류가 발생했습니다. 잠시 후 다시 시도해 주세요.",
                    "tone": "caution",
                }
            ),
            500,
        )


@app.get("/api/health")
def health() -> tuple[object, int]:
    """Health check endpoint."""
    return jsonify({"status": "ok", "message": "NewSight is running"}), 200


if __name__ == "__main__":
    port = int(os.getenv("PORT", 5000))
    debug = os.getenv("FLASK_ENV", "development") == "development"
    app.run(host="0.0.0.0", port=port, debug=debug)
