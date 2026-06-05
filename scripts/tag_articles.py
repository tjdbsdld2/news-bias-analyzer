"""Extract article text and auto-tag collected URL candidates for recommendation DB use."""

from __future__ import annotations

import argparse
import csv
import sys
import urllib.error
import urllib.request
from pathlib import Path
from urllib.parse import urlparse


ROOT_DIR = Path(__file__).resolve().parents[1]
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))

from analyzer import tag_article_metadata
from crawler import fetch_article


DATA_DIR = ROOT_DIR / "data"
DEFAULT_INPUT_PATH = DATA_DIR / "raw_urls.csv"
DEFAULT_OUTPUT_PATH = DATA_DIR / "articles.csv"
ARTICLE_FIELDS = [
    "issue",
    "sub_issue",
    "issue_tags",
    "url",
    "title",
    "source",
    "frame",
    "tone",
    "primary_voice",
    "memo",
    "body_excerpt",
    "tagging_status",
]


def _read_raw_rows(csv_path: Path) -> list[dict[str, str]]:
    """Load collected raw URL candidates from CSV."""
    with csv_path.open("r", encoding="utf-8-sig", newline="") as handle:
        reader = csv.DictReader(handle)
        return [dict(row) for row in reader if (row.get("url") or "").strip()]


def _read_existing_article_rows(csv_path: Path) -> list[dict[str, str]]:
    """Load already-tagged article rows for append mode."""
    if not csv_path.exists():
        return []

    with csv_path.open("r", encoding="utf-8-sig", newline="") as handle:
        reader = csv.DictReader(handle)
        return [dict(row) for row in reader if (row.get("url") or "").strip()]


def _resolve_candidate_url(url: str) -> str:
    """Resolve Google News RSS redirect URLs to a final article URL when possible."""
    parsed = urlparse(url)
    if "news.google.com" not in parsed.netloc:
        return url

    request = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
    try:
        with urllib.request.urlopen(request, timeout=10) as response:
            return response.geturl() or url
    except (urllib.error.URLError, TimeoutError, ValueError):
        return url


def _normalize_article(raw_row: dict[str, str]) -> tuple[dict[str, str] | None, str]:
    """Extract article text or build a snippet fallback when extraction fails."""
    original_url = (raw_row.get("url") or "").strip()
    resolved_url = _resolve_candidate_url(original_url)
    article = fetch_article(resolved_url)

    if article:
        if not article.get("title") or article.get("title") == "제목을 추출하지 못했습니다.":
            article["title"] = (raw_row.get("title") or "").strip() or article.get("title", "")
        if not article.get("source") or article.get("source") == "출처 미상":
            article["source"] = (raw_row.get("source") or "").strip() or article.get("source", "")
        if not article.get("date") or article.get("date") == "날짜 정보 없음":
            article["date"] = (raw_row.get("published_date") or "").strip() or article.get("date", "")
        article["url"] = resolved_url
        return article, "ok"

    title = (raw_row.get("title") or "").strip()
    snippet = (raw_row.get("snippet") or "").strip()
    if not title and not snippet:
        return None, "skipped"

    fallback_article = {
        "url": resolved_url,
        "title": title or "제목 정보 없음",
        "body": snippet[:2800],
        "source": (raw_row.get("source") or "").strip(),
        "date": (raw_row.get("published_date") or "").strip(),
    }
    return fallback_article, "partial"


def tag_articles(
    input_path: Path,
    output_path: Path,
    issue_filter: str | None = None,
    append: bool = False,
) -> list[dict[str, str]]:
    """Tag raw URLs into structured article rows for recommendation DB construction."""
    raw_rows = _read_raw_rows(input_path)
    if issue_filter:
        raw_rows = [row for row in raw_rows if (row.get("issue") or "").strip() == issue_filter]

    existing_rows = _read_existing_article_rows(output_path) if append else []
    existing_urls = {(row.get("url") or "").strip() for row in existing_rows if (row.get("url") or "").strip()}
    output_rows: list[dict[str, str]] = list(existing_rows)

    for raw_row in raw_rows:
        raw_url = (raw_row.get("url") or "").strip()
        if append and raw_url and raw_url in existing_urls:
            continue

        issue = (raw_row.get("issue") or "").strip()
        article, extraction_status = _normalize_article(raw_row)

        if article is None:
            output_rows.append(
                {
                    "issue": issue,
                    "sub_issue": "",
                    "issue_tags": "",
                    "url": (raw_row.get("url") or "").strip(),
                    "title": (raw_row.get("title") or "").strip(),
                    "source": (raw_row.get("source") or "").strip(),
                    "frame": "",
                    "tone": "",
                    "primary_voice": "",
                    "memo": "본문 추출과 snippet 확보에 모두 실패해 스킵했습니다.",
                    "body_excerpt": "",
                    "tagging_status": "skipped",
                }
            )
            continue

        tag_result = tag_article_metadata(article, issue=issue)
        tagging_status = tag_result.get("tagging_status", "ok")
        if extraction_status == "partial" and tagging_status == "ok":
            tagging_status = "partial"

        output_rows.append(
            {
                "issue": issue,
                "sub_issue": tag_result.get("sub_issue", ""),
                "issue_tags": ";".join(tag_result.get("issue_tags", [])),
                "url": article.get("url", "").strip(),
                "title": article.get("title", "").strip(),
                "source": article.get("source", "").strip(),
                "frame": tag_result.get("frame", ""),
                "tone": tag_result.get("tone", ""),
                "primary_voice": tag_result.get("primary_voice", ""),
                "memo": tag_result.get("memo", ""),
                "body_excerpt": (article.get("body") or "")[:2800],
                "tagging_status": tagging_status,
            }
        )

    output_path.parent.mkdir(parents=True, exist_ok=True)
    with output_path.open("w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=ARTICLE_FIELDS)
        writer.writeheader()
        writer.writerows(output_rows)

    return output_rows


def build_parser() -> argparse.ArgumentParser:
    """Build CLI arguments for article tagging."""
    parser = argparse.ArgumentParser(description="raw_urls.csv를 읽어 기사 본문을 추출하고 LLM 태깅을 수행합니다.")
    parser.add_argument("--input", default=str(DEFAULT_INPUT_PATH), help="raw_urls.csv 입력 경로")
    parser.add_argument("--output", default=str(DEFAULT_OUTPUT_PATH), help="articles.csv 출력 경로")
    parser.add_argument("--issue", default=None, help="특정 issue만 태깅할 때 정확한 issue 이름")
    parser.add_argument(
        "--append",
        action="store_true",
        help="기존 articles.csv를 유지한 채 새 기사만 중복 없이 덧붙입니다.",
    )
    return parser


def main() -> None:
    """CLI entry point."""
    parser = build_parser()
    args = parser.parse_args()

    before_rows = _read_existing_article_rows(Path(args.output).expanduser()) if args.append else []
    rows = tag_articles(
        input_path=Path(args.input).expanduser(),
        output_path=Path(args.output).expanduser(),
        issue_filter=args.issue,
        append=args.append,
    )
    before_urls = {(row.get("url") or "").strip() for row in before_rows if (row.get("url") or "").strip()}
    added_rows = [row for row in rows if (row.get("url") or "").strip() not in before_urls]

    status_counts: dict[str, int] = {}
    for row in added_rows:
        status = row["tagging_status"]
        status_counts[status] = status_counts.get(status, 0) + 1

    print(f"추가 태깅 완료: {len(added_rows)}건")
    print(f"현재 articles 전체 건수: {len(rows)}건")
    for status, count in status_counts.items():
        print(f"- {status}: {count}건")


if __name__ == "__main__":
    main()
