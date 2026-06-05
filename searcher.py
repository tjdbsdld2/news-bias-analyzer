"""Fallback external article search for issues missing from the local DB."""

from __future__ import annotations

import html
import re
import urllib.error
import urllib.parse
import urllib.request
import xml.etree.ElementTree as ET


GOOGLE_NEWS_RSS_URL = "https://news.google.com/rss/search"


def _dedupe_preserve_order(values: list[str]) -> list[str]:
    """Remove duplicates while preserving the original order."""
    seen: set[str] = set()
    unique_values: list[str] = []
    for value in values:
        normalized = value.strip()
        if not normalized or normalized in seen:
            continue
        seen.add(normalized)
        unique_values.append(normalized)
    return unique_values


def _clean_snippet(text: str) -> str:
    """Strip HTML tags and normalize whitespace for RSS snippets."""
    text = html.unescape(text or "")
    text = re.sub(r"<[^>]+>", " ", text)
    text = " ".join(text.split()).strip()
    return text


def _normalize_title(text: str) -> str:
    """Normalize titles for duplicate filtering."""
    return " ".join((text or "").split()).strip().lower()


def search_google_news_rss(query: str, limit: int = 3) -> list[dict]:
    """Search Google News RSS directly with a text query."""
    if not query.strip():
        return []

    params = urllib.parse.urlencode({"q": query, "hl": "ko", "gl": "KR", "ceid": "KR:ko"})
    search_url = f"{GOOGLE_NEWS_RSS_URL}?{params}"

    try:
        with urllib.request.urlopen(search_url, timeout=10) as response:
            payload = response.read()
    except (urllib.error.URLError, TimeoutError, ValueError):
        return []

    try:
        root = ET.fromstring(payload)
    except ET.ParseError:
        return []

    seen_links: set[str] = set()
    candidates: list[dict] = []

    channel = root.find("channel")
    if channel is None:
        return []

    for item in channel.findall("item"):
        title = (item.findtext("title") or "").strip()
        link = (item.findtext("link") or "").strip()
        published = (item.findtext("pubDate") or "").strip()
        snippet = _clean_snippet(item.findtext("description") or "")

        source_elem = item.find("source")
        source = (source_elem.text or "").strip() if source_elem is not None and source_elem.text else "출처 정보 없음"

        if not title or not link or link in seen_links:
            continue

        seen_links.add(link)
        candidates.append(
            {
                "title": title,
                "url": link,
                "source": source,
                "date": published or "날짜 정보 없음",
                "snippet": snippet,
                "search_query": query,
            }
        )

        if len(candidates) >= limit:
            break

    return candidates


def build_search_query(article: dict, analysis: dict) -> str:
    """
    Create a search query from analysis metadata.

    Preference order:
    1. issue / sub_issue when present
    2. issue_tags
    3. original article title as fallback
    """
    terms: list[str] = []

    for key in ("issue", "sub_issue"):
        value = str(analysis.get(key, "")).strip()
        if value:
            terms.append(value)

    issue_tags = analysis.get("issue_tags", [])
    if isinstance(issue_tags, list):
        terms.extend(str(tag).strip() for tag in issue_tags if str(tag).strip())
    elif isinstance(issue_tags, str):
        terms.extend(part.strip() for part in re.split(r"[,;/]", issue_tags) if part.strip())

    if not terms:
        title = str(article.get("title", "")).strip()
        if title:
            terms.append(title)

    # Keep the query concise so RSS search results stay on-topic.
    return " ".join(_dedupe_preserve_order(terms)[:4])


def search_related_articles(article: dict, analysis: dict, limit: int = 3) -> list[dict]:
    """
    Search for external related articles when the local DB has no recommendations.

    This fallback only returns candidate articles. They are not re-analyzed here,
    so the UI should present them as external suggestions rather than confirmed
    opposite-frame recommendations.
    """
    query = build_search_query(article, analysis)
    if not query:
        return []

    original_title = _normalize_title(article.get("title", ""))
    candidates = search_google_news_rss(query, limit=limit * 2)
    filtered = []
    for candidate in candidates:
        if original_title and _normalize_title(candidate.get("title", "")) == original_title:
            continue
        filtered.append(candidate)
        if len(filtered) >= limit:
            break
    return filtered
