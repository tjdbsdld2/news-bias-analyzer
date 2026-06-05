"""Clean and rebalance article rows into a presentation-ready recommendation CSV."""

from __future__ import annotations

import argparse
import csv
import re
import shutil
from collections import Counter, defaultdict
from pathlib import Path


ROOT_DIR = Path(__file__).resolve().parents[1]
DATA_DIR = ROOT_DIR / "data"
DEFAULT_INPUT_PATH = DATA_DIR / "articles_combined_backfilled.csv"
DEFAULT_CLEAN_OUTPUT_PATH = DATA_DIR / "articles_expanded.csv"
DEFAULT_OUTPUT_PATH = DATA_DIR / "articles_curated.csv"
DEFAULT_RAW_OUTPUT_PATH = DATA_DIR / "raw_merged.csv"

STATUS_PRIORITY = {"ok": 5, "partial": 4, "legacy": 3, "mock": 2, "failed": 1, "skipped": 0}
SOURCE_DATASET_PRIORITY = {"articles.csv": 2, "articles_flash_lite.csv": 2, "db_final.csv": 2, "": 0}

DEMO_ISSUES = [
    "대형마트 새벽배송 / 유통산업발전법 개정",
    "배달앱 수수료 / 플랫폼 상생",
    "민생지원금 / 소비쿠폰 / 추경",
    "의료개혁 / 의대 증원",
    "노란봉투법 / 노동조합법 개정",
    "AI 반도체 초과이익 재분배 / 사회연대임금",
    "호황의 이면 / 청년 체감경기 괴리",
    "전세사기 특별법 / 피해자 구제",
    "6·3 지방선거 투표용지 부족 / 선거관리 논란",
]

CANONICAL_FRAME_ALIASES = {
    "규제완화": "규제완화",
    "골목상권_보호": "골목상권_보호",
    "소상공인_부담": "소상공인_부담",
    "소비자_편의": "소비자_편의",
    "노동권_보호": "노동권_보호",
    "플랫폼_입장": "플랫폼_입장",
    "규제_필요": "규제_필요",
    "상생_강조": "상생_강조",
    "사회적대화_필요": "사회적대화_필요",
    "민생경제_회복": "민생경제_회복",
    "소상공인_지원": "소상공인_지원",
    "재정건전성_우려": "재정건전성_우려",
    "포퓰리즘_비판": "포퓰리즘_비판",
    "선별지원_필요": "선별지원_필요",
    "정책_정당성": "정책_정당성",
    "의료계_반발": "의료계_반발",
    "환자_피해": "환자_피해",
    "지역의료_확충": "지역의료_확충",
    "갈등_구도": "갈등_구도",
    "기업부담_우려": "기업부담_우려",
    "노사갈등_구도": "노사갈등_구도",
    "제도개선": "제도개선",
    "경영환경_불확실성": "경영환경_불확실성",
    "재분배_필요": "재분배_필요",
    "노동격차_해소": "노동격차_해소",
    "시장경제_원칙": "시장경제_원칙",
    "경제회복_기대": "경제회복_기대",
    "기업성과_강조": "기업성과_강조",
    "청년고용_불안": "청년고용_불안",
    "체감경기_괴리": "체감경기_괴리",
    "산업편중_우려": "산업편중_우려",
    "피해자_보호": "피해자_보호",
    "국가책임": "국가책임",
    "주거안정": "주거안정",
    "중립": "중립",
    # legacy / spacing variants
    "제도_개선": "제도개선",
    "재정건전성 우려": "재정건전성_우려",
    "골목상권보호": "골목상권_보호",
    "소상공인 부담": "소상공인_부담",
    "정책 정당성": "정책_정당성",
    "의료계 반발": "의료계_반발",
    "지역의료 확충": "지역의료_확충",
    "환자 피해": "환자_피해",
    "기업부담 우려": "기업부담_우려",
    "노사갈등 구도": "노사갈등_구도",
    "체감경기 괴리": "체감경기_괴리",
    "청년고용 불안": "청년고용_불안",
    "산업편중 우려": "산업편중_우려",
    "피해자 보호": "피해자_보호",
}

FRAME_TAG_TO_KEYWORD = {
    "규제완화": "규제",
    "골목상권_보호": "골목상권",
    "소상공인_부담": "소상공인",
    "소비자_편의": "소비자",
    "노동권_보호": "노동권",
    "플랫폼_입장": "플랫폼",
    "규제_필요": "규제",
    "상생_강조": "상생",
    "사회적대화_필요": "사회적대화",
    "민생경제_회복": "민생경제",
    "소상공인_지원": "소상공인",
    "재정건전성_우려": "재정건전성",
    "포퓰리즘_비판": "포퓰리즘",
    "선별지원_필요": "선별지원",
    "정책_정당성": "정책",
    "의료계_반발": "의료계",
    "환자_피해": "환자",
    "지역의료_확충": "지역의료",
    "갈등_구도": "갈등",
    "기업부담_우려": "기업부담",
    "노사갈등_구도": "노사갈등",
    "제도개선": "제도개선",
    "경영환경_불확실성": "경영환경",
    "재분배_필요": "재분배",
    "노동격차_해소": "노동격차",
    "시장경제_원칙": "시장경제",
    "경제회복_기대": "경제회복",
    "기업성과_강조": "기업성과",
    "청년고용_불안": "청년고용",
    "체감경기_괴리": "체감경기",
    "산업편중_우려": "산업편중",
    "피해자_보호": "피해자",
    "국가책임": "국가책임",
    "주거안정": "주거안정",
    "중립": "",
}

ISSUE_DEFAULT_TAGS = {
    "대형마트 새벽배송 / 유통산업발전법 개정": ["대형마트", "새벽배송", "유통산업발전법", "골목상권", "노동권"],
    "배달앱 수수료 / 플랫폼 상생": ["배달앱", "수수료", "플랫폼", "소상공인", "상생협의체"],
    "민생지원금 / 소비쿠폰 / 추경": ["민생지원금", "소비쿠폰", "추경", "재정", "소상공인"],
    "의료개혁 / 의대 증원": ["의대증원", "의료개혁", "의료계", "환자", "지역의료"],
    "노란봉투법 / 노동조합법 개정": ["노란봉투법", "노동조합법", "손해배상", "하청노동자", "경영계"],
    "AI 반도체 초과이익 재분배 / 사회연대임금": ["반도체", "초과이익", "사회연대임금", "원하청", "재분배"],
    "호황의 이면 / 청년 체감경기 괴리": ["청년고용", "체감경기", "반도체호황", "쉬었음청년", "양극화"],
    "전세사기 특별법 / 피해자 구제": ["전세사기", "특별법", "피해자구제", "주거안정", "국가책임"],
    "6·3 지방선거 투표용지 부족 / 선거관리 논란": ["지방선거", "투표용지", "선관위", "참정권", "선거관리"],
}

ISSUE_MATCH_TERMS = {
    "대형마트 새벽배송 / 유통산업발전법 개정": ["대형마트", "새벽배송", "유통산업발전법", "의무휴업", "골목상권"],
    "배달앱 수수료 / 플랫폼 상생": ["배달앱", "수수료", "배달의민족", "쿠팡이츠", "플랫폼", "상생협의체", "공공배달앱"],
    "민생지원금 / 소비쿠폰 / 추경": ["민생지원금", "소비쿠폰", "추경", "민생회복", "지역화폐", "지원금"],
    "의료개혁 / 의대 증원": ["의대증원", "의대 증원", "의료개혁", "전공의", "의료공백", "환자", "지역의료", "필수의료"],
    "노란봉투법 / 노동조합법 개정": ["노란봉투법", "노동조합법", "단체교섭", "손해배상", "하청", "원청", "중앙노동위원회", "중노위"],
    "AI 반도체 초과이익 재분배 / 사회연대임금": ["초과이익", "사회연대임금", "국민배당", "원하청", "재분배", "성과급", "반도체"],
    "호황의 이면 / 청년 체감경기 괴리": ["청년", "쉬었음", "체감경기", "고용", "호황", "코스피", "실업", "양극화"],
    "전세사기 특별법 / 피해자 구제": ["전세사기", "특별법", "피해자", "주거", "선구제", "주택", "보증금"],
    "6·3 지방선거 투표용지 부족 / 선거관리 논란": [
        "지방선거",
        "투표용지 부족",
        "선관위",
        "참정권",
        "재선거",
        "선거무효",
        "송파구",
        "잠실7동",
        "개표 중단",
        "부정선거 의혹",
    ],
}

TOPIC_BLOCKLIST = {
    "배달앱 수수료 / 플랫폼 상생": ["중국 배달앱", "유령식당"],
    "AI 가짜뉴스 / 딥페이크 규제": ["셀트리온 노조"],
    "6·3 지방선거 투표용지 부족 / 선거관리 논란": ["홍어 연상 CG"],
}

LEGACY_REMAP_RULES = {
    "민생지원금 / 소비쿠폰 / 추경": {
        "source_issues": {"에너지 전환", "국민연금", "기후재난", "지역소멸", "플랫폼 노동", "부동산 금리"},
        "anchors": ["민생지원금", "민생회복", "소비쿠폰", "추경", "고유가 피해지원금"],
    },
    "의료개혁 / 의대 증원": {
        "source_issues": {"국민연금", "지역소멸"},
        "anchors": ["의대 증원", "의대증원", "의료개혁"],
    },
    "노란봉투법 / 노동조합법 개정": {
        "source_issues": {"플랫폼 노동", "국민연금", "지역소멸", "최저임금"},
        "anchors": ["노란봉투법", "노동조합법"],
    },
    "호황의 이면 / 청년 체감경기 괴리": {
        "source_issues": {"AI 반도체", "최저임금", "플랫폼 노동", "부동산 금리", "국민연금", "지역소멸"},
        "anchors": [
            "체감경기",
            "쉬었음",
            "청년 실업",
            "청년고용",
            "취업난",
            "코스피는 웃는데",
            "가계는 냉기",
            "자영업자는 운다",
            "반도체 환호 뒤",
        ],
    },
}


def _canonical_key(text: str) -> str:
    """Normalize separators/spaces so similar labels can be matched reliably."""
    return re.sub(r"[\s_]+", "", (text or "").strip())


FRAME_NORMALIZATION_MAP = {
    _canonical_key(key): value for key, value in CANONICAL_FRAME_ALIASES.items()
}

TAG_NORMALIZATION_MAP = {
    _canonical_key(key): value
    for key, value in {
        **FRAME_TAG_TO_KEYWORD,
        "골목상권보호": "골목상권",
        "골목상권 보호": "골목상권",
        "규제 완화": "규제",
        "의료계 반발": "의료계",
        "지역의료 확충": "지역의료",
        "피해자 보호": "피해자",
        "재정건전성 우려": "재정건전성",
        "정책 정당성": "정책",
        "사회적 대화": "사회적대화",
        "사회적 대화기구": "사회적대화",
        "정책 성과": "정책",
        "대형마트 새벽배송": "대형마트",
        "피해자구제": "피해자구제",
        "플랫폼_책임": "플랫폼",
        "지역경제_활성화": "지역경제",
        "쉬었음_인구": "쉬었음",
        "피해자_연대": "피해자",
        "세입자_목소리": "세입자",
    }.items()
}


def _read_rows(csv_path: Path) -> tuple[list[dict[str, str]], list[str]]:
    """Read CSV rows and preserve field order."""
    with csv_path.open("r", encoding="utf-8-sig", newline="") as handle:
        reader = csv.DictReader(handle)
        rows = [dict(row) for row in reader]
        return rows, list(reader.fieldnames or [])


def _row_quality_key(row: dict[str, str]) -> tuple[int, int, int, int, int]:
    """Score rows so selection prefers richer, newer metadata."""
    status_score = STATUS_PRIORITY.get((row.get("tagging_status") or "").strip(), -1)
    source_score = SOURCE_DATASET_PRIORITY.get((row.get("source_dataset") or "").strip(), 0)
    title_score = 1 if (row.get("title") or "").strip() else 0
    memo_score = 1 if (row.get("memo") or "").strip() else 0
    excerpt_length = len((row.get("body_excerpt") or "").strip())
    return status_score, source_score, title_score, memo_score, excerpt_length


def _dedupe_by_url(rows: list[dict[str, str]]) -> list[dict[str, str]]:
    """Keep the best row for each URL."""
    best_by_url: dict[str, dict[str, str]] = {}
    for row in rows:
        url = (row.get("url") or "").strip()
        if not url:
            continue
        existing = best_by_url.get(url)
        if existing is None or _row_quality_key(row) > _row_quality_key(existing):
            best_by_url[url] = row
    return list(best_by_url.values())


def _normalize_frame(frame: str, issue: str = "", title: str = "", source_dataset: str = "") -> str:
    """Normalize frame labels to a single canonical naming style."""
    cleaned = (frame or "").strip()
    if not cleaned:
        return "중립"

    normalized = FRAME_NORMALIZATION_MAP.get(_canonical_key(cleaned))
    if normalized:
        return normalized

    compact_title = (title or "").replace(" ", "")
    if source_dataset == "db_final.csv":
        if issue == "민생지원금 / 소비쿠폰 / 추경":
            if cleaned == "세대_부담":
                return "재정건전성_우려"
            if cleaned == "탈탄소_전환":
                return "민생경제_회복"
        if issue == "의료개혁 / 의대 증원" and cleaned == "노후_보장":
            return "지역의료_확충"
        if issue == "노란봉투법 / 노동조합법 개정":
            if cleaned == "산업_부담":
                return "기업부담_우려"
            if cleaned == "노후_보장":
                return "제도개선"
        if issue == "호황의 이면 / 청년 체감경기 괴리":
            if cleaned in {"산업_성장", "성과_쏠림"}:
                if any(keyword in compact_title for keyword in ["가계는냉기", "자영업자는운다", "신불자", "체감경기"]):
                    return "체감경기_괴리"
                if "쏠림" in compact_title:
                    return "산업편중_우려"
                return "기업성과_강조"
            if cleaned == "경영계_부담":
                return "청년고용_불안" if "청년실업" in compact_title else "체감경기_괴리"

    return cleaned.replace(" ", "")


def _split_tags(raw_tags: str) -> list[str]:
    """Split a raw tag string into individual tags."""
    return [part.strip() for part in re.split(r"[;,/]", raw_tags or "") if part.strip()]


def _normalize_tag(tag: str) -> str:
    """Normalize one keyword-like tag and strip frame-shaped aliases into topic keywords."""
    cleaned = (tag or "").strip()
    if not cleaned:
        return ""
    mapped = TAG_NORMALIZATION_MAP.get(_canonical_key(cleaned), cleaned)
    mapped = mapped.replace(" ", "").replace("_", "")
    return mapped


def _normalize_issue_tags(issue: str, raw_tags: str) -> str:
    """Normalize issue tags into 3-5 short keyword-style terms."""
    normalized: list[str] = []
    seen: set[str] = set()

    for tag in _split_tags(raw_tags):
        keyword = _normalize_tag(tag)
        if not keyword or keyword in seen:
            continue
        seen.add(keyword)
        normalized.append(keyword)

    for fallback in ISSUE_DEFAULT_TAGS.get(issue, []):
        if len(normalized) >= 5:
            break
        if fallback not in seen:
            seen.add(fallback)
            normalized.append(fallback)

    if len(normalized) < 3:
        normalized.extend(tag for tag in ISSUE_DEFAULT_TAGS.get(issue, []) if tag not in seen)
        normalized = normalized[:5]

    return ";".join(normalized[:5])


def _normalize_issue(issue: str) -> str:
    """Trim issue labels while keeping the chosen display text intact."""
    return " ".join((issue or "").split()).strip()


def _compose_legacy_match_text(row: dict[str, str]) -> str:
    """Build a compact text blob for strict legacy-topic remapping checks."""
    parts = [
        row.get("title", ""),
        row.get("issue_tags", ""),
        row.get("memo", ""),
    ]
    return " ".join(parts).replace(" ", "")


def _remap_legacy_issue(row: dict[str, str]) -> str:
    """Map a legacy teammate article to one of the current demo issues when anchors are explicit."""
    original_issue = _normalize_issue(row.get("issue", ""))
    if original_issue in DEMO_ISSUES:
        return original_issue

    source_dataset = (row.get("source_dataset") or "").strip()
    if source_dataset != "db_final.csv":
        return original_issue

    compact_text = _compose_legacy_match_text(row)
    for demo_issue, rule in LEGACY_REMAP_RULES.items():
        if original_issue not in rule["source_issues"]:
            continue
        if any(anchor.replace(" ", "") in compact_text for anchor in rule["anchors"]):
            return demo_issue

    return original_issue


def _matches_issue(row: dict[str, str]) -> bool:
    """Heuristic guard to drop rows whose topic clearly does not fit the selected issue."""
    issue = _normalize_issue(row.get("issue", ""))
    if issue not in ISSUE_MATCH_TERMS:
        return False

    text = " ".join(
        [
            row.get("title", ""),
            row.get("sub_issue", ""),
            row.get("issue_tags", ""),
            row.get("memo", ""),
            row.get("body_excerpt", ""),
        ]
    )
    compact = text.replace(" ", "")

    terms = ISSUE_MATCH_TERMS[issue]
    if not any(term.replace(" ", "") in compact for term in terms):
        return False

    for blocked_term in TOPIC_BLOCKLIST.get(issue, []):
        if blocked_term.replace(" ", "") in compact:
            return False
    return True


def _normalize_row(row: dict[str, str]) -> dict[str, str]:
    """Apply issue/frame/tag normalization without losing non-core metadata."""
    updated = row.copy()
    issue = _remap_legacy_issue(updated)
    updated["issue"] = issue
    updated["frame"] = _normalize_frame(
        updated.get("frame", ""),
        issue=issue,
        title=updated.get("title", ""),
        source_dataset=updated.get("source_dataset", ""),
    )
    updated["issue_tags"] = _normalize_issue_tags(issue, updated.get("issue_tags", ""))
    updated["title"] = " ".join((updated.get("title") or "").split()).strip()
    updated["source"] = " ".join((updated.get("source") or "").split()).strip()
    updated["sub_issue"] = " ".join((updated.get("sub_issue") or "").split()).strip()
    updated["tone"] = " ".join((updated.get("tone") or "").split()).strip()
    updated["primary_voice"] = " ".join((updated.get("primary_voice") or "").split()).strip()
    return updated


def _filter_rows(rows: list[dict[str, str]], allowed_issues: list[str]) -> list[dict[str, str]]:
    """Remove rows that are not suitable for the final demo dataset."""
    allowed = set(allowed_issues)
    filtered: list[dict[str, str]] = []
    for row in rows:
        if not (row.get("title") or "").strip():
            continue
        if (row.get("tagging_status") or "").strip() in {"failed", "skipped"}:
            continue
        if _normalize_issue(row.get("issue", "")) not in allowed:
            continue
        if not _matches_issue(row):
            continue
        filtered.append(row)
    return filtered


def _print_issue_summary(rows: list[dict[str, str]], title: str) -> None:
    """Print issue counts and frame distributions for quick review."""
    print(title)
    issue_groups: defaultdict[str, list[dict[str, str]]] = defaultdict(list)
    for row in rows:
        issue_groups[(row.get("issue") or "").strip()].append(row)

    for issue in DEMO_ISSUES:
        issue_rows = issue_groups.get(issue, [])
        if not issue_rows:
            continue
        frame_counts = Counter((row.get("frame") or "미분류").strip() for row in issue_rows)
        source_counts = Counter((row.get("source_dataset") or "unknown").strip() for row in issue_rows)
        frame_summary = ", ".join(f"{frame}:{count}" for frame, count in frame_counts.items())
        source_summary = ", ".join(f"{source}:{count}" for source, count in source_counts.items())
        print(f"- {issue}: {len(issue_rows)}건 | {frame_summary} | 출처 {source_summary}")
    print("")


def _select_diverse_rows(issue_rows: list[dict[str, str]], max_per_issue: int) -> list[dict[str, str]]:
    """Select up to max_per_issue rows while keeping frame diversity first."""
    ranked_rows = sorted(issue_rows, key=_row_quality_key, reverse=True)
    if len(ranked_rows) <= max_per_issue:
        return ranked_rows

    frame_buckets: defaultdict[str, list[dict[str, str]]] = defaultdict(list)
    frame_order: list[str] = []
    for row in ranked_rows:
        frame = (row.get("frame") or "미분류").strip()
        if frame not in frame_buckets:
            frame_order.append(frame)
        frame_buckets[frame].append(row)

    selected: list[dict[str, str]] = []
    while len(selected) < max_per_issue and any(frame_buckets.values()):
        for frame in frame_order:
            bucket = frame_buckets[frame]
            if bucket and len(selected) < max_per_issue:
                selected.append(bucket.pop(0))

    legacy_rows = [row for row in ranked_rows if (row.get("source_dataset") or "").strip() == "db_final.csv"]
    if legacy_rows and not any((row.get("source_dataset") or "").strip() == "db_final.csv" for row in selected):
        selected_urls = {(row.get("url") or "").strip() for row in selected}
        for legacy_row in legacy_rows:
            legacy_url = (legacy_row.get("url") or "").strip()
            if legacy_url and legacy_url not in selected_urls:
                selected.append(legacy_row)
                break

    return selected


def build_article_db(
    input_path: Path,
    clean_output_path: Path,
    output_path: Path,
    max_per_issue: int | None = None,
    raw_output_path: Path | None = None,
) -> tuple[list[dict[str, str]], list[dict[str, str]]]:
    """Create clean and final article CSVs for the demo recommendation DB."""
    if raw_output_path is not None:
        raw_output_path.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(input_path, raw_output_path)

    rows, fieldnames = _read_rows(input_path)
    normalized_rows = [_normalize_row(row) for row in rows]
    deduped_rows = _dedupe_by_url(normalized_rows)
    clean_rows = _filter_rows(deduped_rows, DEMO_ISSUES)

    _print_issue_summary(clean_rows, "정제 후 issue/frame 분포")

    clean_output_path.parent.mkdir(parents=True, exist_ok=True)
    with clean_output_path.open("w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(clean_rows)

    final_rows = clean_rows
    if max_per_issue is not None:
        grouped: defaultdict[str, list[dict[str, str]]] = defaultdict(list)
        for row in clean_rows:
            grouped[(row.get("issue") or "").strip()].append(row)

        final_rows = []
        for issue in DEMO_ISSUES:
            issue_rows = grouped.get(issue, [])
            if not issue_rows:
                continue
            final_rows.extend(_select_diverse_rows(issue_rows, max_per_issue))

        _print_issue_summary(final_rows, "최대 기사 수 제한 적용 후 issue/frame 분포")

    output_path.parent.mkdir(parents=True, exist_ok=True)
    with output_path.open("w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(final_rows)

    return clean_rows, final_rows


def build_parser() -> argparse.ArgumentParser:
    """Build CLI arguments for final DB cleanup."""
    parser = argparse.ArgumentParser(description="통합 기사 CSV를 정제해 발표용 추천 DB를 만듭니다.")
    parser.add_argument("--input", default=str(DEFAULT_INPUT_PATH), help="입력 CSV 경로")
    parser.add_argument("--clean-output", default=str(DEFAULT_CLEAN_OUTPUT_PATH), help="정제 중간본 CSV 경로")
    parser.add_argument("--output", default=str(DEFAULT_OUTPUT_PATH), help="articles_final.csv 출력 경로")
    parser.add_argument("--raw-output", default=str(DEFAULT_RAW_OUTPUT_PATH), help="정제 전 원본 보관 CSV 경로")
    parser.add_argument("--max-per-issue", type=int, default=8, help="curated에서 이슈당 최대 기사 수")
    return parser


def main() -> None:
    """CLI entry point."""
    parser = build_parser()
    args = parser.parse_args()

    clean_rows, final_rows = build_article_db(
        input_path=Path(args.input).expanduser(),
        clean_output_path=Path(args.clean_output).expanduser(),
        output_path=Path(args.output).expanduser(),
        max_per_issue=args.max_per_issue,
        raw_output_path=Path(args.raw_output).expanduser(),
    )
    print(f"정제 중간본 저장 완료: {len(clean_rows)}건")
    print(f"최종 저장 완료: {len(final_rows)}건")
    print(f"중간본: {Path(args.clean_output).expanduser()}")
    print(f"최종본: {Path(args.output).expanduser()}")


if __name__ == "__main__":
    main()
