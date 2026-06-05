"""Import article URLs from CSV, crawl them, analyze them, and store them in SQLite."""

from __future__ import annotations

import argparse
import csv
from pathlib import Path

from analyzer import analyze_article
from crawler import fetch_article
from db import DATA_DIR, save_article_with_analysis


DEFAULT_CSV_PATH = DATA_DIR / "article_urls.csv"


def load_rows(csv_path: Path) -> list[dict[str, str]]:
    """Read URL rows from the CSV template."""
    if not csv_path.exists():
        raise FileNotFoundError(f"CSV 파일을 찾을 수 없습니다: {csv_path}")

    with csv_path.open("r", encoding="utf-8-sig", newline="") as handle:
        reader = csv.DictReader(handle)
        rows = [dict(row) for row in reader if (row.get("url") or "").strip()]
    return rows


def ingest_from_csv(csv_path: Path, limit: int | None = None) -> dict[str, int]:
    """
    Import articles listed in the CSV file.

    The CSV can include helper columns such as issue, source, expected_frame,
    and memo, but only the URL is required for ingestion.
    """
    rows = load_rows(csv_path)
    if limit is not None:
        rows = rows[:limit]

    stats = {"total": len(rows), "saved": 0, "failed": 0}

    for index, row in enumerate(rows, start=1):
        url = (row.get("url") or "").strip()
        source_hint = (row.get("source") or "").strip()

        print(f"[{index}/{len(rows)}] 수집 중: {url}")
        article = fetch_article(url)
        if article is None:
            print("  - 실패: 기사 추출에 실패했습니다.")
            stats["failed"] += 1
            continue

        if source_hint and not article.get("source"):
            article["source"] = source_hint

        analysis = analyze_article(article)
        save_article_with_analysis(article, analysis)

        print(
            "  - 저장 완료:"
            f" frame={analysis.get('frame', '')},"
            f" tags={analysis.get('issue_tags', [])}"
        )
        stats["saved"] += 1

    return stats


def build_parser() -> argparse.ArgumentParser:
    """Create a small CLI for the ingestion script."""
    parser = argparse.ArgumentParser(
        description="CSV에 적어둔 뉴스 기사 URL을 수집하고 SQLite DB에 저장합니다."
    )
    parser.add_argument(
        "--csv",
        default=str(DEFAULT_CSV_PATH),
        help="기사 URL 목록 CSV 경로 (기본값: data/article_urls.csv)",
    )
    parser.add_argument(
        "--limit",
        type=int,
        default=None,
        help="앞에서부터 몇 개 기사만 수집할지 제한합니다.",
    )
    return parser


def main() -> None:
    """Run CSV-based ingestion from the command line."""
    parser = build_parser()
    args = parser.parse_args()
    csv_path = Path(args.csv).expanduser().resolve()

    stats = ingest_from_csv(csv_path=csv_path, limit=args.limit)
    print("")
    print("수집 완료")
    print(f"- 전체 URL 수: {stats['total']}")
    print(f"- 저장 성공: {stats['saved']}")
    print(f"- 저장 실패: {stats['failed']}")


if __name__ == "__main__":
    main()
