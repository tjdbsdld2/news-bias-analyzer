"""Collect news URL candidates from issue keywords using Naver or Google RSS."""

from __future__ import annotations

import argparse
import csv
import html
import json
import os
import re
import sys
import urllib.error
import urllib.parse
import urllib.request
from collections import defaultdict
from email.utils import parsedate_to_datetime
from pathlib import Path
from urllib.parse import urlparse

from dotenv import load_dotenv


ROOT_DIR = Path(__file__).resolve().parents[1]
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))

from searcher import search_google_news_rss


DATA_DIR = ROOT_DIR / "data"
DEFAULT_INPUT_PATH = DATA_DIR / "issue_keywords.csv"
DEFAULT_OUTPUT_PATH = DATA_DIR / "raw_urls.csv"
NAVER_NEWS_SEARCH_URL = "https://openapi.naver.com/v1/search/news.json"
RAW_URL_FIELDS = [
    "issue",
    "keyword",
    "title",
    "url",
    "source",
    "published_date",
    "snippet",
    "collection_method",
]


def _clean_text(text: str) -> str:
    """Normalize HTML-encoded or tag-heavy text from search APIs."""
    text = html.unescape(text or "")
    text = re.sub(r"<[^>]+>", " ", text)
    return " ".join(text.split()).strip()


def _normalize_date(value: str) -> str:
    """Convert provider-specific dates into YYYY-MM-DD when possible."""
    value = (value or "").strip()
    if not value:
        return ""

    try:
        return parsedate_to_datetime(value).date().isoformat()
    except (TypeError, ValueError, OverflowError):
        pass

    if len(value) >= 10 and re.match(r"\d{4}-\d{2}-\d{2}", value):
        return value[:10]
    return value


def _source_from_url(url: str) -> str:
    """Use domain name as a fallback source label."""
    hostname = urlparse(url).netloc.replace("www.", "").strip()
    return hostname or "출처 정보 없음"


def _read_keywords(csv_path: Path) -> list[dict[str, str]]:
    """Load issue/keyword pairs from CSV."""
    with csv_path.open("r", encoding="utf-8-sig", newline="") as handle:
        reader = csv.DictReader(handle)
        return [
            {"issue": (row.get("issue") or "").strip(), "keyword": (row.get("keyword") or "").strip()}
            for row in reader
            if (row.get("issue") or "").strip() and (row.get("keyword") or "").strip()
        ]


def _read_existing_rows(csv_path: Path) -> list[dict[str, str]]:
    """Load already-collected raw URL rows when append mode is enabled."""
    if not csv_path.exists():
        return []

    with csv_path.open("r", encoding="utf-8-sig", newline="") as handle:
        reader = csv.DictReader(handle)
        return [dict(row) for row in reader if (row.get("url") or "").strip()]


def _search_naver_news(keyword: str, limit: int = 5) -> list[dict[str, str]]:
    """Search Naver News API and normalize results."""
    client_id = os.getenv("NAVER_CLIENT_ID")
    client_secret = os.getenv("NAVER_CLIENT_SECRET")
    if not client_id or not client_secret:
        return []

    params = urllib.parse.urlencode(
        {
            "query": keyword,
            "display": limit,
            "sort": "sim",
        }
    )
    request = urllib.request.Request(
        f"{NAVER_NEWS_SEARCH_URL}?{params}",
        headers={
            "X-Naver-Client-Id": client_id,
            "X-Naver-Client-Secret": client_secret,
        },
    )

    with urllib.request.urlopen(request, timeout=10) as response:
        payload = json.loads(response.read().decode("utf-8"))

    normalized_rows = []
    for item in payload.get("items", []):
        original_url = (item.get("originallink") or "").strip()
        fallback_url = (item.get("link") or "").strip()
        url = original_url or fallback_url
        if not url:
            continue

        normalized_rows.append(
            {
                "title": _clean_text(item.get("title", "")),
                "url": url,
                "source": _source_from_url(url),
                "published_date": _normalize_date(item.get("pubDate", "")),
                "snippet": _clean_text(item.get("description", "")),
                "collection_method": "naver_api",
            }
        )

    return normalized_rows


def _search_google_news(keyword: str, limit: int = 5) -> list[dict[str, str]]:
    """Search Google News RSS and normalize results."""
    results = search_google_news_rss(keyword, limit=limit)
    normalized_rows = []
    for item in results:
        normalized_rows.append(
            {
                "title": _clean_text(item.get("title", "")),
                "url": (item.get("url") or "").strip(),
                "source": _clean_text(item.get("source", "")) or _source_from_url(item.get("url", "")),
                "published_date": _normalize_date(item.get("date", "")),
                "snippet": _clean_text(item.get("snippet", "")),
                "collection_method": "google_news_rss",
            }
        )
    return normalized_rows


def collect_urls(
    input_path: Path,
    output_path: Path,
    limit_per_keyword: int = 5,
    max_per_issue: int = 30,
    issue_filter: str | None = None,
    append: bool = False,
) -> list[dict[str, str]]:
    """Collect deduplicated raw URL candidates across all issue keywords."""
    load_dotenv()
    keyword_rows = _read_keywords(input_path)
    if issue_filter:
        keyword_rows = [row for row in keyword_rows if row["issue"] == issue_filter]

    existing_rows = _read_existing_rows(output_path) if append else []
    seen_urls: set[str] = {(row.get("url") or "").strip() for row in existing_rows if (row.get("url") or "").strip()}
    issue_counts: defaultdict[str, int] = defaultdict(int)
    collected_rows: list[dict[str, str]] = list(existing_rows)

    for existing_row in existing_rows:
        issue = (existing_row.get("issue") or "").strip()
        if issue:
            issue_counts[issue] += 1

    for row in keyword_rows:
        issue = row["issue"]
        keyword = row["keyword"]
        if issue_counts[issue] >= max_per_issue:
            continue

        candidates: list[dict[str, str]] = []

        try:
            candidates = _search_naver_news(keyword, limit=limit_per_keyword)
        except Exception:
            candidates = []

        if not candidates:
            try:
                candidates = _search_google_news(keyword, limit=limit_per_keyword)
            except Exception:
                candidates = []

        for candidate in candidates:
            url = candidate.get("url", "").strip()
            if not url or url in seen_urls or issue_counts[issue] >= max_per_issue:
                continue

            seen_urls.add(url)
            issue_counts[issue] += 1
            collected_rows.append(
                {
                    "issue": issue,
                    "keyword": keyword,
                    "title": candidate.get("title", ""),
                    "url": url,
                    "source": candidate.get("source", ""),
                    "published_date": candidate.get("published_date", ""),
                    "snippet": candidate.get("snippet", ""),
                    "collection_method": candidate.get("collection_method", ""),
                }
            )

    output_path.parent.mkdir(parents=True, exist_ok=True)
    with output_path.open("w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=RAW_URL_FIELDS)
        writer.writeheader()
        writer.writerows(collected_rows)

    return collected_rows


def build_parser() -> argparse.ArgumentParser:
    """Build CLI arguments for URL collection."""
    parser = argparse.ArgumentParser(description="이슈별 키워드로 뉴스 URL 후보를 수집합니다.")
    parser.add_argument("--input", default=str(DEFAULT_INPUT_PATH), help="issue_keywords.csv 경로")
    parser.add_argument("--output", default=str(DEFAULT_OUTPUT_PATH), help="raw_urls.csv 출력 경로")
    parser.add_argument("--limit-per-keyword", type=int, default=5, help="검색어당 최대 수집 기사 수")
    parser.add_argument("--max-per-issue", type=int, default=30, help="이슈당 최대 저장 기사 수")
    parser.add_argument("--issue", default=None, help="특정 issue만 수집할 때 정확한 issue 이름")
    parser.add_argument(
        "--append",
        action="store_true",
        help="기존 raw_urls.csv를 유지한 채 새 결과만 중복 없이 덧붙입니다.",
    )
    return parser


def main() -> None:
    """CLI entry point."""
    parser = build_parser()
    args = parser.parse_args()

    before_rows = _read_existing_rows(Path(args.output).expanduser()) if args.append else []
    rows = collect_urls(
        input_path=Path(args.input).expanduser(),
        output_path=Path(args.output).expanduser(),
        limit_per_keyword=args.limit_per_keyword,
        max_per_issue=args.max_per_issue,
        issue_filter=args.issue,
        append=args.append,
    )
    before_urls = {(row.get("url") or "").strip() for row in before_rows if (row.get("url") or "").strip()}
    added_rows = [row for row in rows if (row.get("url") or "").strip() not in before_urls]

    counts: defaultdict[str, int] = defaultdict(int)
    methods: defaultdict[str, int] = defaultdict(int)
    for row in added_rows:
        counts[row["issue"]] += 1
        methods[row["collection_method"]] += 1

    print(f"추가 수집 완료: {len(added_rows)}건")
    print(f"현재 raw_urls 전체 건수: {len(rows)}건")
    for issue, count in counts.items():
        print(f"- {issue}: {count}건")
    for method, count in methods.items():
        print(f"- {method}: {count}건")


if __name__ == "__main__":
    main()
