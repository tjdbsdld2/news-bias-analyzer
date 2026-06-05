"""Utilities for extracting article text from a news URL."""

from __future__ import annotations

import json
from urllib.parse import urlparse

import trafilatura


MAX_BODY_LENGTH = 2600


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


def fetch_article(url: str) -> dict | None:
    """
    Download a news page and extract a compact article payload.

    Returns None when extraction fails so the Streamlit app can handle the error
    gracefully instead of crashing.
    """
    if not url:
        return None

    try:
        downloaded = trafilatura.fetch_url(url)
    except Exception:
        return None

    if not downloaded:
        return None

    try:
        extracted_json = trafilatura.extract(
            downloaded,
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
                    include_comments=False,
                    include_tables=False,
                    favor_recall=True,
                )
                or ""
            )
            title = ""
            source = _fallback_source(url)
            date = ""
    except Exception:
        return None

    if not body:
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
