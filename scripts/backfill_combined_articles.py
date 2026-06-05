"""Backfill missing tagging fields in a combined recommendation CSV."""

from __future__ import annotations

import argparse
import csv
import sys
from pathlib import Path


ROOT_DIR = Path(__file__).resolve().parents[1]
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))

from analyzer import tag_article_metadata
from crawler import fetch_article


DATA_DIR = ROOT_DIR / "data"
DEFAULT_INPUT_PATH = DATA_DIR / "articles_combined.csv"
DEFAULT_OUTPUT_PATH = DATA_DIR / "articles_combined_backfilled.csv"
TARGET_FIELDS = ["sub_issue", "tone", "primary_voice", "body_excerpt"]


def _read_rows(csv_path: Path) -> tuple[list[dict[str, str]], list[str]]:
    """Read CSV rows while preserving field order."""
    with csv_path.open("r", encoding="utf-8-sig", newline="") as handle:
        reader = csv.DictReader(handle)
        rows = [dict(row) for row in reader]
        return rows, list(reader.fieldnames or [])


def _needs_backfill(row: dict[str, str]) -> bool:
    """Return whether a row still has blank fields worth enriching."""
    if (row.get("tagging_status") or "").strip() == "legacy":
        return True
    return any(not (row.get(field) or "").strip() for field in TARGET_FIELDS)


def _build_fallback_article(row: dict[str, str]) -> dict[str, str] | None:
    """Create a lightweight article object when full-body extraction fails."""
    title = (row.get("title") or "").strip()
    source = (row.get("source") or "").strip()
    memo = (row.get("memo") or "").strip()
    body_excerpt = (row.get("body_excerpt") or "").strip()
    url = (row.get("url") or "").strip()

    body = body_excerpt or memo or title
    if not body:
        return None

    return {
        "url": url,
        "title": title,
        "body": body[:2800],
        "source": source,
        "date": "",
    }


def _load_article_for_backfill(row: dict[str, str]) -> tuple[dict[str, str] | None, str]:
    """Fetch the full article when possible, otherwise build a fallback article."""
    url = (row.get("url") or "").strip()
    article = fetch_article(url) if url else None

    if article:
        if not article.get("title"):
            article["title"] = (row.get("title") or "").strip()
        if not article.get("source"):
            article["source"] = (row.get("source") or "").strip()
        article["url"] = url or article.get("url", "")
        return article, "ok"

    fallback = _build_fallback_article(row)
    if fallback is None:
        return None, "skipped"
    return fallback, "partial"


def _merge_tagged_fields(
    row: dict[str, str],
    article: dict[str, str],
    extraction_status: str,
    retag_legacy_labels: bool,
) -> dict[str, str]:
    """Fill only missing fields by default, or fully retag legacy label columns when requested."""
    issue = (row.get("issue") or "").strip()
    tag_result = tag_article_metadata(article, issue=issue)

    updated = row.copy()
    updated["title"] = (updated.get("title") or "").strip() or article.get("title", "").strip()
    updated["source"] = (updated.get("source") or "").strip() or article.get("source", "").strip()

    if retag_legacy_labels or not (updated.get("sub_issue") or "").strip():
        updated["sub_issue"] = tag_result.get("sub_issue", "")
    if retag_legacy_labels or not (updated.get("issue_tags") or "").strip():
        updated["issue_tags"] = ";".join(tag_result.get("issue_tags", []))
    if retag_legacy_labels or not (updated.get("frame") or "").strip():
        updated["frame"] = tag_result.get("frame", "")
    if retag_legacy_labels or not (updated.get("tone") or "").strip():
        updated["tone"] = tag_result.get("tone", "")
    if retag_legacy_labels or not (updated.get("primary_voice") or "").strip():
        updated["primary_voice"] = tag_result.get("primary_voice", "")
    if retag_legacy_labels or not (updated.get("memo") or "").strip():
        updated["memo"] = tag_result.get("memo", "")
    if retag_legacy_labels or not (updated.get("body_excerpt") or "").strip():
        updated["body_excerpt"] = (article.get("body") or "")[:2800]

    tag_status = (tag_result.get("tagging_status") or "").strip()
    if tag_status == "ok":
        updated["tagging_status"] = "ok" if extraction_status == "ok" else "partial"
    elif tag_status:
        updated["tagging_status"] = tag_status
    elif extraction_status in {"ok", "partial"}:
        updated["tagging_status"] = extraction_status

    return updated


def backfill_combined_articles(
    input_path: Path,
    output_path: Path,
    limit: int | None = None,
    print_every: int = 20,
    retag_legacy_labels: bool = False,
) -> list[dict[str, str]]:
    """Backfill missing fields in a combined CSV using crawling plus LLM tagging."""
    rows, fieldnames = _read_rows(input_path)
    output_rows: list[dict[str, str]] = []
    processed = 0
    backfilled = 0

    for index, row in enumerate(rows, start=1):
        if not _needs_backfill(row):
            output_rows.append(row)
            continue

        if limit is not None and backfilled >= limit:
            output_rows.append(row)
            continue

        article, extraction_status = _load_article_for_backfill(row)
        if article is None:
            skipped_row = row.copy()
            if not (skipped_row.get("tagging_status") or "").strip():
                skipped_row["tagging_status"] = "skipped"
            output_rows.append(skipped_row)
        else:
            output_rows.append(
                _merge_tagged_fields(
                    row=row,
                    article=article,
                    extraction_status=extraction_status,
                    retag_legacy_labels=retag_legacy_labels,
                )
            )

        backfilled += 1
        processed += 1
        if print_every > 0 and processed % print_every == 0:
            print(f"진행 중: {processed}건 backfill 완료 (전체 행 {index}/{len(rows)})")

    output_path.parent.mkdir(parents=True, exist_ok=True)
    with output_path.open("w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(output_rows)

    return output_rows


def build_parser() -> argparse.ArgumentParser:
    """Build CLI arguments for combined CSV backfill."""
    parser = argparse.ArgumentParser(description="통합 기사 CSV의 빈 tagging 필드를 LLM으로 보강합니다.")
    parser.add_argument("--input", default=str(DEFAULT_INPUT_PATH), help="입력 CSV 경로")
    parser.add_argument("--output", default=str(DEFAULT_OUTPUT_PATH), help="출력 CSV 경로")
    parser.add_argument("--limit", type=int, default=None, help="backfill할 최대 행 수")
    parser.add_argument("--print-every", type=int, default=20, help="진행 상황 출력 간격")
    parser.add_argument(
        "--retag-legacy-labels",
        action="store_true",
        help="legacy 행의 frame/issue_tags/memo도 LLM 결과로 다시 덮어씁니다.",
    )
    return parser


def main() -> None:
    """CLI entry point."""
    parser = build_parser()
    args = parser.parse_args()

    rows = backfill_combined_articles(
        input_path=Path(args.input).expanduser(),
        output_path=Path(args.output).expanduser(),
        limit=args.limit,
        print_every=args.print_every,
        retag_legacy_labels=args.retag_legacy_labels,
    )
    print(f"보강 완료: {len(rows)}건")
    print(f"출력 파일: {Path(args.output).expanduser()}")


if __name__ == "__main__":
    main()
