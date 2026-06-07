"""Utilities for extracting article text from a news URL."""

from __future__ import annotations

import json
import logging
import urllib.error
import urllib.request
from urllib.parse import urlparse

import trafilatura


MAX_BODY_LENGTH = 2600
MIN_BODY_LENGTH = 200
DOWNLOAD_TIMEOUT_SECONDS = 10
REQUEST_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
        "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/126.0 Safari/537.36"
    ),
    "Accept-Language": "ko-KR,ko;q=0.9,en-US;q=0.8,en;q=0.7",
}
NOISY_BODY_TERMS = {
    "댓글",
    "로그인",
    "구독",
    "저작권자",
    "무단전재",
    "광고",
    "기사제보",
    "전체메뉴",
    "메뉴 열기",
}

logger = logging.getLogger(__name__)


def _clean_text(text: str) -> str:
    """Normalize whitespace so the analyzer receives cleaner article text."""
    return " ".join(text.split()).strip()


def _truncate_text(text: str, limit: int = MAX_BODY_LENGTH) -> str:
    """Trim very long bodies so prompt size stays manageable."""
    if len(text) <= limit:
        return text
    shortened = text[:limit].rsplit(" ", 1)[0]
    return f"{shortened}..."


def _fallback_source(url: str) -> str:
    """Use the domain name when the crawler cannot identify a media outlet."""
    hostname = urlparse(url).netloc.replace("www.", "").strip()
    return hostname or "출처 미상"


def _download_html(url: str, timeout: int = DOWNLOAD_TIMEOUT_SECONDS) -> str | None:
    """Download raw HTML with an explicit timeout for safer demo behavior."""
    request = urllib.request.Request(url, headers=REQUEST_HEADERS)
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            charset = response.headers.get_content_charset() or "utf-8"
            payload = response.read()
    except (urllib.error.URLError, TimeoutError, ValueError) as exc:
        logger.warning("Article download failed for %s: %s", url, exc)
        return None
    except Exception as exc:
        logger.warning("Unexpected article download error for %s: %s", url, exc)
        return None

    for encoding in (charset, "utf-8", "cp949"):
        try:
            return payload.decode(encoding, errors="ignore")
        except LookupError:
            continue
    return payload.decode("utf-8", errors="ignore")


def _looks_like_article_body(body: str) -> bool:
    """Reject menu-like or extremely thin extractions before analysis."""
    normalized = _clean_text(body)
    if len(normalized) < MIN_BODY_LENGTH:
        return False

    sentence_like_count = len([part for part in normalized.split(".") if len(part.strip()) >= 18])
    if sentence_like_count < 2 and len(normalized) < 320:
        return False

    noisy_hits = sum(1 for term in NOISY_BODY_TERMS if term in normalized)
    if noisy_hits >= 4 and sentence_like_count < 3:
        return False

    return True


def fetch_article(url: str) -> dict | None:
    """
    Download a news page and extract a compact article payload.

    Returns None when extraction fails so the Streamlit app can handle the error
    gracefully instead of crashing.
    """
    if not url:
        return None

    try:
        downloaded = _download_html(url)
    except Exception as exc:
        logger.warning("Failed to fetch article source for %s: %s", url, exc)
        return None

    if not downloaded:
        return None

    try:
        extracted_json = trafilatura.extract(
            downloaded,
            url=url,
            output_format="json",
            with_metadata=True,
            include_comments=False,
            include_tables=False,
            favor_recall=True,
        )

        if extracted_json:
            data = json.loads(extracted_json)
            body = _clean_text(data.get("text", ""))
            title = _clean_text(data.get("title", ""))
            source = _clean_text(data.get("sitename", "")) or _fallback_source(url)
            date = _clean_text(data.get("date", ""))
        else:
            body = _clean_text(
                trafilatura.extract(
                    downloaded,
                    url=url,
                    include_comments=False,
                    include_tables=False,
                    favor_recall=True,
                )
                or ""
            )
            title = ""
            source = _fallback_source(url)
            date = ""
    except Exception as exc:
        logger.warning("Article extraction failed for %s: %s", url, exc)
        return None

    if not body or not _looks_like_article_body(body):
        return None

    return {
        "url": url,
        "title": title or "제목을 추출하지 못했습니다.",
        "body": _truncate_text(body),
        "source": source,
        "date": date or "날짜 정보 없음",
    }


def crawl_news(url: str) -> dict | None:
    """Compatibility wrapper for older function names used in early app drafts."""
    return fetch_article(url)
