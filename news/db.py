"""SQLite helpers for article recommendation candidates."""

from __future__ import annotations

import json
import sqlite3
from pathlib import Path


BASE_DIR = Path(__file__).resolve().parent
DATA_DIR = BASE_DIR / "data"
DB_PATH = DATA_DIR / "articles.db"


SAMPLE_ARTICLES = [
    {
        "url": "https://example.com/minimum-wage-labor",
        "title": "최저임금 인상 요구 확산, 노동계는 생계비 부담을 강조",
        "body": "노동계는 물가 상승과 실질임금 하락을 이유로 최저임금 인상이 필요하다고 주장했다.",
        "source": "시민뉴스",
        "date": "2026-05-10",
        "issue_tags": ["정책", "사회", "노동"],
        "frame": "노동자_권리",
        "tone": "문제 제기형",
        "primary_voice": "노동계",
    },
    {
        "url": "https://example.com/minimum-wage-business",
        "title": "최저임금 추가 인상에 소상공인들 한숨, 인건비 부담 호소",
        "body": "경영계는 인건비 상승이 고용 축소와 폐업 증가로 이어질 수 있다고 우려했다.",
        "source": "경제포커스",
        "date": "2026-05-12",
        "issue_tags": ["정책", "경제", "노동"],
        "frame": "경영계_부담",
        "tone": "우려 중심",
        "primary_voice": "경영계",
    },
    {
        "url": "https://example.com/minimum-wage-government",
        "title": "정부, 최저임금 조정안 검토하며 취약계층 보호 필요성 설명",
        "body": "정부는 최저임금 조정이 노동시장 안정과 취약계층 보호에 필요하다는 점을 설명했다.",
        "source": "정책브리프",
        "date": "2026-05-13",
        "issue_tags": ["정책", "사회", "정부"],
        "frame": "정책_정당성",
        "tone": "설명적",
        "primary_voice": "정부",
    },
    {
        "url": "https://example.com/minimum-wage-conflict",
        "title": "최저임금 협상 또 평행선, 노사 양측 강대강 대치",
        "body": "최저임금위원회 회의에서 노사 양측이 서로 다른 근거를 내세우며 강하게 맞섰다.",
        "source": "이슈데일리",
        "date": "2026-05-14",
        "issue_tags": ["정책", "사회", "갈등"],
        "frame": "갈등_구도",
        "tone": "대립 부각형",
        "primary_voice": "노사 양측",
    },
    {
        "url": "https://example.com/disaster-victims",
        "title": "집중호우 이재민들 대피소 생활 장기화, 피해 회복 더뎌",
        "body": "재난 피해 주민들은 복구 지연과 생계 불안을 호소하며 실질 지원 확대를 요구했다.",
        "source": "현장리포트",
        "date": "2026-05-15",
        "issue_tags": ["사회", "안전", "피해"],
        "frame": "피해_중심",
        "tone": "호소형",
        "primary_voice": "피해 주민",
    },
    {
        "url": "https://example.com/disaster-policy",
        "title": "정부, 재난 대응 예산 확대 추진... 복구 체계 정비 속도",
        "body": "정부는 재난 대응 체계 정비와 예산 확대가 안전 관리 강화를 위해 필요하다고 밝혔다.",
        "source": "공공뉴스",
        "date": "2026-05-16",
        "issue_tags": ["사회", "안전", "정책"],
        "frame": "정책_정당성",
        "tone": "설명적",
        "primary_voice": "정부",
    },
]


def _get_connection() -> sqlite3.Connection:
    """Open the SQLite database with row access by column name."""
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    connection = sqlite3.connect(DB_PATH)
    connection.row_factory = sqlite3.Row
    return connection


def init_db() -> None:
    """Create the articles table and seed sample data when empty."""
    with _get_connection() as connection:
        connection.execute(
            """
            CREATE TABLE IF NOT EXISTS articles (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                url TEXT UNIQUE,
                title TEXT NOT NULL,
                body TEXT,
                source TEXT,
                date TEXT,
                issue_tags TEXT,
                frame TEXT,
                tone TEXT,
                primary_voice TEXT
            )
            """
        )

    insert_sample_articles_if_empty()


def insert_sample_articles_if_empty() -> None:
    """Populate the database with a few demo articles for MVP testing."""
    with _get_connection() as connection:
        count = connection.execute("SELECT COUNT(*) AS count FROM articles").fetchone()["count"]
        if count > 0:
            return

        connection.executemany(
            """
            INSERT INTO articles (
                url, title, body, source, date, issue_tags, frame, tone, primary_voice
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            [
                (
                    article["url"],
                    article["title"],
                    article["body"],
                    article["source"],
                    article["date"],
                    json.dumps(article["issue_tags"], ensure_ascii=False),
                    article["frame"],
                    article["tone"],
                    article["primary_voice"],
                )
                for article in SAMPLE_ARTICLES
            ],
        )


def _normalize_tags(issue_tags: list[str] | tuple[str, ...]) -> list[str]:
    """Normalize tags for overlap comparison."""
    return [str(tag).strip() for tag in issue_tags if str(tag).strip()]


def _load_tags(raw_value: str | None) -> list[str]:
    """Load tags stored as JSON strings in SQLite."""
    if not raw_value:
        return []

    try:
        payload = json.loads(raw_value)
        if isinstance(payload, list):
            return _normalize_tags(payload)
    except json.JSONDecodeError:
        pass

    return _normalize_tags(raw_value.split(","))


def find_opposite_articles(issue_tags: list[str], frame: str, limit: int = 3) -> list[dict]:
    """
    Return articles that share at least one issue tag but use a different frame.

    Results are sorted by the number of overlapping tags so that closer matches
    appear first.
    """
    init_db()
    normalized_query_tags = set(_normalize_tags(issue_tags))
    if not normalized_query_tags:
        return []

    with _get_connection() as connection:
        rows = connection.execute(
            """
            SELECT id, url, title, source, date, issue_tags, frame, tone, primary_voice
            FROM articles
            WHERE frame != ?
            """,
            (frame,),
        ).fetchall()

    candidates = []
    for row in rows:
        article_tags = _load_tags(row["issue_tags"])
        overlap = sorted(normalized_query_tags.intersection(article_tags))
        if not overlap:
            continue

        candidates.append(
            {
                "title": row["title"],
                "source": row["source"],
                "date": row["date"],
                "url": row["url"],
                "frame": row["frame"],
                "issue_tags": article_tags,
                "overlap_count": len(overlap),
            }
        )

    candidates.sort(key=lambda item: (item["overlap_count"], item["date"]), reverse=True)

    trimmed = []
    for item in candidates[:limit]:
        cleaned = item.copy()
        cleaned.pop("overlap_count", None)
        trimmed.append(cleaned)
    return trimmed
