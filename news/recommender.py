"""CSV-based recommendation logic for curated and expanded article pools."""

from __future__ import annotations

import csv
import logging
import re
from functools import lru_cache
from pathlib import Path
from typing import Any
from difflib import SequenceMatcher


BASE_DIR = Path(__file__).resolve().parent
DATA_DIR = BASE_DIR / "data"
CURATED_PATH = DATA_DIR / "articles_curated.csv"
EXPANDED_PATH = DATA_DIR / "articles_expanded.csv"
LEGACY_CURATED_PATH = DATA_DIR / "articles_final.csv"
LEGACY_EXPANDED_PATH = DATA_DIR / "articles_clean.csv"

STATUS_PRIORITY = {"ok": 4, "partial": 3, "legacy": 2, "mock": 1}
GENERIC_TAGS = {
    "ai",
    "정책",
    "사회",
    "정부",
    "경제",
    "산업",
    "기업",
    "시장",
    "기술",
    "뉴스",
    "기사",
    "반도체",
    "반도체호황",
    "시장경제",
    "경제회복",
    "경기회복",
    "증시",
    "코스피",
    "성장률",
    "투자",
    "수출",
    "매출",
    "산업성장",
    "기업성과",
    "호황",
}
REQUIRED_COLUMNS = {"url", "title", "frame", "issue_tags"}

logger = logging.getLogger(__name__)


def _compact(text: str) -> str:
    """Normalize text for lightweight fuzzy comparisons."""
    return re.sub(r"[\s_]+", "", (text or "").strip().lower())


def _split_tags(value: Any) -> list[str]:
    """Normalize issue_tags from either a list or a delimiter-separated string."""
    if isinstance(value, list):
        return [str(item).strip() for item in value if str(item).strip()]
    if isinstance(value, str):
        return [part.strip() for part in re.split(r"[;,/]", value) if part.strip()]
    return []


def _dataset_path(dataset_name: str) -> Path:
    """Resolve the preferred CSV path with a backward-compatible fallback."""
    if dataset_name == "curated":
        return CURATED_PATH if CURATED_PATH.exists() else LEGACY_CURATED_PATH
    if dataset_name == "expanded":
        return EXPANDED_PATH if EXPANDED_PATH.exists() else LEGACY_EXPANDED_PATH
    raise ValueError(f"Unknown dataset name: {dataset_name}")


@lru_cache(maxsize=4)
def _load_dataset_bundle(dataset_name: str) -> tuple[list[dict[str, str]], list[str]]:
    """Load a recommendation CSV into memory."""
    csv_path = _dataset_path(dataset_name)
    if not csv_path.exists():
        warning = f"{dataset_name} 추천 DB 파일이 없어 해당 추천 단계를 건너뜁니다."
        logger.warning(warning)
        return [], [warning]

    warnings: list[str] = []
    rows: list[dict[str, str]] = []
    last_error: Exception | None = None

    for encoding in ("utf-8-sig", "utf-8", "cp949"):
        try:
            with csv_path.open("r", encoding=encoding, newline="") as handle:
                reader = csv.DictReader(handle)
                fieldnames = set(reader.fieldnames or [])
                missing_columns = sorted(REQUIRED_COLUMNS - fieldnames)
                if missing_columns:
                    warning = f"{dataset_name} 추천 DB에 필요한 컬럼이 부족해 일부 추천을 건너뜁니다."
                    logger.warning("%s Missing columns: %s", warning, ", ".join(missing_columns))
                    warnings.append(warning)
                    return [], warnings

                seen_urls: set[str] = set()
                for row in reader:
                    normalized_row = {str(key): (value or "").strip() for key, value in row.items()}
                    url = normalized_row.get("url", "")
                    title = normalized_row.get("title", "")
                    if not url or not title:
                        continue
                    if url in seen_urls:
                        continue
                    seen_urls.add(url)
                    rows.append(normalized_row)
            break
        except (UnicodeDecodeError, csv.Error) as exc:
            last_error = exc
            rows = []
            continue
        except OSError as exc:
            last_error = exc
            rows = []
            break

    if last_error and not rows:
        warning = f"{dataset_name} 추천 DB를 읽지 못해 외부 관련 기사 후보를 먼저 찾습니다."
        logger.warning("%s (%s)", warning, last_error)
        warnings.append(warning)
        return [], warnings

    if not rows:
        warning = f"{dataset_name} 추천 DB가 비어 있어 해당 추천 단계를 건너뜁니다."
        logger.warning(warning)
        warnings.append(warning)

    return rows, warnings


def _load_dataset(dataset_name: str) -> list[dict[str, str]]:
    """Return only dataset rows for callers that do not need warnings."""
    rows, _ = _load_dataset_bundle(dataset_name)
    return rows


def _dataset_notice(dataset_name: str) -> str:
    """Return a user-facing notice when dataset loading had issues."""
    _, warnings = _load_dataset_bundle(dataset_name)
    return warnings[0] if warnings else ""


def _status_score(row: dict[str, str]) -> int:
    """Prefer fully tagged rows over partial or legacy rows."""
    return STATUS_PRIORITY.get((row.get("tagging_status") or "").strip(), 0)


def _issue_terms(issue: str) -> list[str]:
    """Extract high-signal matching terms from a structured issue label."""
    issue = (issue or "").strip()
    if not issue:
        return []

    candidates: list[str] = []
    for chunk in re.split(r"/", issue):
        cleaned_chunk = chunk.strip()
        if not cleaned_chunk:
            continue
        candidates.append(cleaned_chunk)

    unique_terms: list[str] = []
    seen: set[str] = set()
    for term in candidates:
        compact_term = _compact(term)
        if compact_term and compact_term not in seen:
            seen.add(compact_term)
            unique_terms.append(term)
    return unique_terms


def _issue_match_score(issue: str, query_text: str) -> int:
    """Score how strongly a dataset issue label matches the input article context."""
    score = 0
    compact_query = _compact(query_text)
    for term in _issue_terms(issue):
        compact_term = _compact(term)
        if compact_term and compact_term in compact_query:
            score += 2 if len(term.split()) > 1 or "/" in issue else 1
    return score


def _query_context(article: dict | None, analysis: dict) -> tuple[list[str], str]:
    """Build normalized query tags plus a text blob for fuzzy issue matching."""
    query_tags = _split_tags(analysis.get("issue_tags", []))
    query_text_parts = [
        analysis.get("issue", "") if isinstance(analysis, dict) else "",
        analysis.get("sub_issue", "") if isinstance(analysis, dict) else "",
        article.get("title", "") if isinstance(article, dict) else "",
        analysis.get("summary", "") if isinstance(analysis, dict) else "",
        " ".join(query_tags),
    ]
    return query_tags, " ".join(part for part in query_text_parts if part)


def _specific_tag_overlap_count(query_tags: set[str], candidate_tags: set[str]) -> int:
    """Count only non-generic overlapping tags for local recommendation decisions."""
    return len(
        {
            tag
            for tag in query_tags.intersection(candidate_tags)
            if tag and tag not in GENERIC_TAGS and len(tag) >= 2
        }
    )


def _voice_difference_score(query_voice: str, candidate_voice: str) -> int:
    """Prefer candidates foregrounding a different main actor or stakeholder."""
    normalized_query_voice = _compact(query_voice)
    normalized_candidate_voice = _compact(candidate_voice)
    if not normalized_query_voice or not normalized_candidate_voice:
        return 0
    return 1 if normalized_query_voice != normalized_candidate_voice else 0


def _sub_issue_difference_score(query_text: str, candidate_sub_issue: str) -> int:
    """Prefer candidates that seem to foreground a different sub-angle of the same issue."""
    normalized_sub_issue = _compact(candidate_sub_issue)
    if not normalized_sub_issue:
        return 0
    return 1 if normalized_sub_issue not in _compact(query_text) else 0


def _title_similarity(left: str, right: str) -> float:
    """Measure normalized title similarity for filtering near-duplicates."""
    if not left or not right:
        return 0.0
    return SequenceMatcher(None, left, right).ratio()


def _build_candidates(
    article: dict | None,
    analysis: dict,
    dataset_name: str,
    limit: int,
) -> list[dict[str, str]]:
    """Score and select different-frame candidates from one dataset tier."""
    rows = _load_dataset(dataset_name)
    if not rows:
        return []

    query_tags = _split_tags(analysis.get("issue_tags", []))
    query_frame = _compact(analysis.get("frame", ""))
    query_voice = str(analysis.get("primary_voice", "")).strip()
    query_issue = str(analysis.get("issue", "")).strip()
    query_sub_issue = str(analysis.get("sub_issue", "")).strip()
    query_text_tags, query_text = _query_context(article, analysis)
    normalized_query_tags = {_compact(tag) for tag in query_tags + query_text_tags if _compact(tag)}

    if not normalized_query_tags and not query_text.strip():
        return []

    input_url = (article.get("url", "") if isinstance(article, dict) else "").strip()
    input_title = _compact(article.get("title", "")) if isinstance(article, dict) else ""

    scored: list[tuple[tuple[int, int, int, int, int], dict[str, str]]] = []
    for row in rows:
        candidate_url = (row.get("url") or "").strip()
        candidate_title = _compact(row.get("title", ""))
        candidate_frame = _compact(row.get("frame", ""))
        candidate_tags = _split_tags(row.get("issue_tags", ""))
        normalized_candidate_tags = {_compact(tag) for tag in candidate_tags if _compact(tag)}
        candidate_issue = str(row.get("issue", "")).strip()
        candidate_sub_issue = str(row.get("sub_issue", "")).strip()

        if input_url and candidate_url == input_url:
            continue
        if input_title and candidate_title == input_title:
            continue

        overlap = sorted(normalized_query_tags.intersection(normalized_candidate_tags))
        overlap_count = len(overlap)
        specific_overlap_count = _specific_tag_overlap_count(normalized_query_tags, normalized_candidate_tags)
        issue_score = _issue_match_score(candidate_issue, query_text)
        issue_exact_match = 1 if query_issue and _compact(query_issue) == _compact(candidate_issue) else 0
        voice_difference = _voice_difference_score(query_voice, row.get("primary_voice", ""))
        sub_issue_difference = _sub_issue_difference_score(query_text, candidate_sub_issue)
        title_similarity = _title_similarity(input_title, candidate_title)

        compare_signal = voice_difference + sub_issue_difference + (1 if query_frame and candidate_frame and candidate_frame != query_frame else 0)
        if query_frame and candidate_frame == query_frame and compare_signal <= 0:
            continue

        min_specific_overlap = 2 if dataset_name == "curated" else 3
        if issue_exact_match == 0 and issue_score <= 0 and specific_overlap_count < min_specific_overlap:
            continue
        if overlap_count == 0 and issue_score < 2 and issue_exact_match == 0:
            continue
        if title_similarity >= 0.82 and issue_exact_match == 0 and issue_score <= 0 and specific_overlap_count < (min_specific_overlap + 1):
            continue

        score = (
            issue_exact_match,
            1 if issue_score > 0 else 0,
            specific_overlap_count,
            issue_score,
            1 if query_frame and candidate_frame and candidate_frame != query_frame else 0,
            voice_difference,
            sub_issue_difference,
            _status_score(row),
            len((row.get("memo") or "").strip()),
        )
        scored.append(
            (
                score,
                {
                    "issue": row.get("issue", ""),
                    "title": row.get("title", ""),
                    "source": row.get("source", ""),
                    "date": row.get("date", ""),
                    "url": candidate_url,
                    "frame": row.get("frame", ""),
                    "issue_tags": candidate_tags,
                    "sub_issue": row.get("sub_issue", ""),
                    "memo": row.get("memo", ""),
                    "tone": row.get("tone", ""),
                    "primary_voice": row.get("primary_voice", ""),
                    "body_excerpt": row.get("body_excerpt", ""),
                    "tagging_status": row.get("tagging_status", ""),
                    "source_dataset": row.get("source_dataset", dataset_name),
                },
            )
        )

    scored.sort(key=lambda item: item[0], reverse=True)
    return [candidate for _, candidate in scored[:limit]]


def recommend_articles(article: dict | None, analysis: dict, limit: int = 3) -> dict[str, Any]:
    """Recommend from curated first, then expanded, returning tier metadata."""
    curated_candidates = _build_candidates(article, analysis, dataset_name="curated", limit=limit)
    if curated_candidates:
        return {
            "tier": "curated",
            "heading": "함께 비교해볼 기사",
            "caption": "같은 이슈를 다루지만 다른 쟁점, 다른 목소리, 다른 관점이 드러나는 기사를 함께 살펴볼 수 있습니다.",
            "notice": "",
            "articles": curated_candidates,
        }

    expanded_candidates = _build_candidates(article, analysis, dataset_name="expanded", limit=limit)
    if expanded_candidates:
        return {
            "tier": "expanded",
            "heading": "함께 비교해볼 기사",
            "caption": "같은 이슈를 다루지만 다른 쟁점, 다른 목소리, 다른 관점이 드러나는 기사를 함께 살펴볼 수 있습니다.",
            "notice": "",
            "articles": expanded_candidates,
        }

    return {
        "tier": "none",
        "heading": "",
        "caption": "",
        "notice": "",
        "articles": [],
    }


def recommend_opposite(analysis: dict, limit: int = 3) -> list[dict]:
    """Compatibility wrapper that returns only the article list."""
    result = recommend_articles(article=None, analysis=analysis, limit=limit)
    return result["articles"]


def get_recommendations(analysis: dict, limit: int = 3) -> list[dict]:
    """Compatibility wrapper for the naming used in older app drafts."""
    return recommend_opposite(analysis, limit=limit)
