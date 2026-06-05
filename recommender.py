import argparse
import json
import math
import re
from dataclasses import dataclass, field
from datetime import datetime
from typing import Dict, List, Optional, Tuple

import pandas as pd
import requests

try:
    from crawler import crawl_news
except Exception:
    crawl_news = None

try:
    from analyzer import analyze_article as analyzer_analyze_article
except Exception:
    try:
        from analyzer import analyze_row as analyzer_analyze_row

        def analyzer_analyze_article(article: dict) -> dict:
            return analyzer_analyze_row(pd.Series(article))

    except Exception:
        analyzer_analyze_article = None


MAX_LLM_CALLS = 5
GAP_THRESHOLD = 0.10
DEFAULT_TOP_K_SEARCH = 10
NAVER_NEWS_API_URL = "https://openapi.naver.com/v1/search/news.json"


class AnalyzerCallBudgetExceeded(RuntimeError):
    pass


@dataclass
class AnalyzerCallBudget:
    """
    analyzer.py 호출 횟수를 관리하는 예산 객체.
    추천 과정에서 LLM 호출 수를 제한하기 위해 사용한다.
    """
    max_calls: int
    calls: int = 0

    def remaining(self) -> int:
        return max(0, self.max_calls - self.calls)

    def consume(self) -> None:
        if self.calls >= self.max_calls:
            raise AnalyzerCallBudgetExceeded(
                f"analyzer.py 호출 한도 {self.max_calls}회에 도달했습니다."
            )
        self.calls += 1


@dataclass(order=True)
class Branch:
    """
    B&B(Branch and Bound, 분기한정법)에서 사용하는 탐색 단위.

    - branch: issue / frame 기준으로 묶인 후보군(부분 문제)
    - upper_bound: 이 branch 내부 후보들이 가질 수 있는 최고 잠재 점수의 상한값

    분기한정법은 각 branch의 upper_bound를 먼저 계산해
    유망한 branch부터 먼저 탐색하고,
    상한이 낮은 branch는 뒤로 미루거나 탐색을 조기에 중단하는 방식이다.
    """
    upper_bound: float
    branch_key: str = field(compare=False)
    candidate_indices: List[int] = field(compare=False, default_factory=list)


def now_iso() -> str:
    return datetime.now().isoformat(timespec="seconds")


def safe_str(value) -> str:
    if value is None:
        return ""

    try:
        if pd.isna(value):
            return ""
    except Exception:
        pass

    return str(value)


def safe_float(value, default: float = 0.0) -> float:
    try:
        if pd.isna(value):
            return default
        return float(value)
    except Exception:
        return default


def clean_html(text: str) -> str:
    text = str(text or "")
    text = re.sub(r"<[^>]+>", " ", text)
    text = re.sub(r"\s+", " ", text)
    return text.strip()


def parse_json_safely(value):
    if isinstance(value, dict):
        return value

    if not isinstance(value, str):
        return None

    value = value.strip()
    if not value:
        return None

    try:
        return json.loads(value)
    except Exception:
        return None


def article_from_row(row: pd.Series) -> dict:
    """
    DB row를 analyzer.py가 이해할 수 있는 article dict로 변환한다.
    """
    content = safe_str(row.get("content"))

    if not content:
        content = safe_str(row.get("preprocessed_content"))

    return {
        "issue": safe_str(row.get("issue")),
        "issue_tags": safe_str(row.get("issue_tags")),
        "url": safe_str(row.get("url")),
        "title": safe_str(row.get("title")),
        "source": safe_str(row.get("source")),
        "frame": safe_str(row.get("frame")),
        "memo": safe_str(row.get("memo")),
        "content": content,
    }


def normalize_analysis(analysis: Dict) -> Dict:
    """
    analyzer.py 출력 또는 DB의 analysis_json을
    recommender 내부 표준 형식으로 정규화한다.
    """
    if not isinstance(analysis, dict):
        analysis = {}

    vector = analysis.get("perspective_vector", {})
    if isinstance(vector, str):
        parsed = parse_json_safely(vector)
        vector = parsed if isinstance(parsed, dict) else {}

    return {
        "topic": safe_str(analysis.get("topic")),
        "summary": safe_str(analysis.get("summary")),
        "main_frame": safe_str(analysis.get("main_frame")),
        "stance": safe_str(analysis.get("stance")),
        "bias_axis": safe_float(analysis.get("bias_axis"), 0.0),
        "bias_strength": safe_float(analysis.get("bias_strength"), 0.0),
        "emotionality": safe_float(analysis.get("emotionality"), 0.0),
        "source_balance": safe_float(analysis.get("source_balance"), 50.0),
        "evidence_quality": safe_float(analysis.get("evidence_quality"), 50.0),
        "perspective_vector": vector,
        "loaded_terms": analysis.get("loaded_terms", []),
        "missing_perspectives": analysis.get("missing_perspectives", []),
        "reasoning": safe_str(analysis.get("reasoning")),
        "content_bias": analysis.get("content_bias", {}),
        "background_bias": analysis.get("background_bias", {}),
    }


def load_analysis_from_row(row: pd.Series) -> Optional[Dict]:
    """
    row에 이미 저장된 분석 결과가 있으면 먼저 재사용한다.
    analysis_json / analyzer_result / bias_* 컬럼 등을 지원한다.
    """
    possible_json_columns = [
        "analysis_json",
        "bias_analysis_json",
        "analyzer_result",
        "analysis",
    ]

    for col in possible_json_columns:
        if col in row.index:
            parsed = parse_json_safely(row.get(col))
            if isinstance(parsed, dict):
                return normalize_analysis(parsed)

    if "bias_axis" in row.index:
        return normalize_analysis(
            {
                "topic": row.get("topic", ""),
                "summary": row.get("summary", ""),
                "main_frame": row.get("main_frame", row.get("frame", "")),
                "stance": row.get("stance", ""),
                "bias_axis": row.get("bias_axis", 0),
                "bias_strength": row.get("bias_strength", 0),
                "emotionality": row.get("emotionality", 0),
                "source_balance": row.get("source_balance", 50),
                "evidence_quality": row.get("evidence_quality", 50),
                "perspective_vector": row.get("perspective_vector", {}),
                "reasoning": row.get("reasoning", ""),
            }
        )

    prefixed_columns = [
        "bias_bias_axis",
        "bias_bias_strength",
        "bias_emotionality",
        "bias_source_balance",
        "bias_evidence_quality",
    ]

    if any(col in row.index for col in prefixed_columns):
        return normalize_analysis(
            {
                "topic": row.get("bias_topic", ""),
                "summary": row.get("bias_summary", ""),
                "main_frame": row.get("bias_main_frame", row.get("frame", "")),
                "stance": row.get("bias_stance", ""),
                "bias_axis": row.get("bias_bias_axis", 0),
                "bias_strength": row.get("bias_bias_strength", 0),
                "emotionality": row.get("bias_emotionality", 0),
                "source_balance": row.get("bias_source_balance", 50),
                "evidence_quality": row.get("bias_evidence_quality", 50),
                "perspective_vector": row.get("bias_perspective_vector", {}),
                "reasoning": row.get("bias_reasoning", ""),
            }
        )

    return None


def analysis_cache_key(row: pd.Series) -> str:
    url = safe_str(row.get("url"))
    title = safe_str(row.get("title"))
    return f"url::{url}" if url else f"title::{title}"


def analyze_with_analyzer(article: dict, budget: AnalyzerCallBudget) -> Dict:
    """
    analyzer.py를 실제로 호출하는 래퍼.
    호출 전 예산을 차감한다.
    """
    if analyzer_analyze_article is None:
        raise RuntimeError(
            "analyzer.py에서 analyze_article 또는 analyze_row 함수를 import하지 못했습니다."
        )

    budget.consume()
    analysis = analyzer_analyze_article(article)
    return normalize_analysis(analysis)


def get_or_create_analysis(
    row: pd.Series,
    budget: AnalyzerCallBudget,
    cache: Dict[str, Dict],
) -> Dict:
    """
    캐시 → row 내 저장된 분석값 → analyzer 호출 순서로 분석을 확보한다.
    """
    key = analysis_cache_key(row)
    if key in cache:
        return cache[key]

    cached = load_analysis_from_row(row)
    if cached is not None:
        cache[key] = cached
        return cached

    article = article_from_row(row)
    analysis = analyze_with_analyzer(article, budget)
    cache[key] = analysis
    return analysis


def enrich_row_with_analysis_hints(row: pd.Series, analysis: Dict) -> pd.Series:
    """
    analyzer가 뽑은 topic / main_frame / stance를 row metadata에 반영한다.

    입력 URL 기사는 처음엔 issue=input_url, frame=input_article처럼 들어오는데,
    이 상태 그대로면 relevance 계산이 약해진다.
    그래서 analyzer 결과를 row 메타데이터에 덮어써서
    입력 URL도 실제 주제와 프레임 기준으로 비교되게 만든다.
    """
    row = row.copy()
    topic = safe_str(analysis.get("topic"))
    main_frame = safe_str(analysis.get("main_frame"))
    stance = safe_str(analysis.get("stance"))

    current_issue = safe_str(row.get("issue"))
    current_frame = safe_str(row.get("frame"))
    current_tags = safe_str(row.get("issue_tags"))

    if topic and current_issue in ["", "input_url", "naver_search"]:
        row["issue"] = topic

    if main_frame and current_frame in ["", "input_article", "search_candidate"]:
        row["frame"] = main_frame

    if topic:
        inferred_tags = [topic]
        if main_frame:
            inferred_tags.append(main_frame)
        if stance:
            inferred_tags.append(stance)
        inferred = ";".join([part for part in inferred_tags if part])
        if current_tags in ["", "input_url", "naver_search"]:
            row["issue_tags"] = inferred

    return row


def crawl_url_to_row(news_url: str) -> pd.Series:
    """
    사용자가 입력한 URL을 크롤링해서 target row로 만든다.
    초기 issue/frame은 placeholder로 넣고,
    이후 analyzer 결과로 실제 topic/frame으로 보정한다.
    """
    if crawl_news is None:
        raise RuntimeError("crawler.py에서 crawl_news를 import하지 못했습니다.")

    result = crawl_news(news_url=news_url, delay=1.0)
    if result.get("crawl_status") != "success":
        raise RuntimeError(f"입력 URL 크롤링 실패: {result.get('crawl_status')}")

    return pd.Series(
        {
            "issue": "input_url",
            "issue_tags": "input_url",
            "url": result.get("url", news_url),
            "title": result.get("title", news_url),
            "source": result.get("source", "input_url"),
            "frame": "input_article",
            "memo": "사용자가 입력한 URL 기사",
            "content": result.get("content", ""),
            "crawl_status": result.get("crawl_status", ""),
        }
    )


def append_or_find_target_url(
    df: pd.DataFrame,
    news_url: str,
) -> Tuple[pd.DataFrame, int]:
    """
    입력 URL이 DB 안에 이미 있으면 기존 행을 사용하고,
    없으면 새 target row를 append한다.
    """
    news_url = news_url.strip()

    if "url" in df.columns:
        matched = df.index[
            df["url"].astype(str).str.strip() == news_url
        ].tolist()
        if matched:
            return df, matched[0]

    target_row = crawl_url_to_row(news_url)
    df = pd.concat([df, pd.DataFrame([target_row])], ignore_index=True)
    return df, len(df) - 1


def crawl_candidate_if_needed(row: pd.Series, delay: float = 1.0) -> pd.Series:
    """
    후보 기사에 content가 없으면 crawler.py로 본문을 보충한다.
    """
    content = safe_str(row.get("content")) or safe_str(row.get("preprocessed_content"))
    if content:
        return row
    if crawl_news is None:
        return row

    url = safe_str(row.get("url"))
    if not url:
        return row

    result = crawl_news(news_url=url, delay=delay)
    if result.get("crawl_status") == "success":
        row = row.copy()
        row["content"] = result.get("content", "")
        row["title"] = safe_str(row.get("title")) or result.get("title", "")
        row["source"] = safe_str(row.get("source")) or result.get("source", "")
        row["crawl_status"] = result.get("crawl_status", "")

    return row


def lexical_tokens(text: str) -> set:
    return set(re.findall(r"[가-힣A-Za-z0-9]{2,}", safe_str(text).lower()))


def lexical_similarity(a: str, b: str) -> float:
    tokens_a = lexical_tokens(a)
    tokens_b = lexical_tokens(b)
    if not tokens_a or not tokens_b:
        return 0.0
    return len(tokens_a & tokens_b) / len(tokens_a | tokens_b)


def metadata_text(row: pd.Series) -> str:
    return " ".join([
        safe_str(row.get("issue")),
        safe_str(row.get("issue_tags")),
        safe_str(row.get("title")),
        safe_str(row.get("frame")),
        safe_str(row.get("memo")),
    ])


def vector_distance(vector_a: Dict, vector_b: Dict) -> float:
    keys = sorted(set((vector_a or {}).keys()) | set((vector_b or {}).keys()))
    if not keys:
        return 0.0

    total = 0.0
    for key in keys:
        a = safe_float((vector_a or {}).get(key), 0.0)
        b = safe_float((vector_b or {}).get(key), 0.0)
        total += (a - b) ** 2

    return min(100.0, math.sqrt(total / len(keys)))


def bias_distance_score(target_analysis: Dict, candidate_analysis: Dict) -> float:
    """
    입력 기사와 후보 기사 사이의 편향 거리.
    - bias_axis 거리
    - perspective_vector 거리
    - 방향이 반대면 opposite bonus
    """
    target_axis = safe_float(target_analysis.get("bias_axis"), 0.0)
    candidate_axis = safe_float(candidate_analysis.get("bias_axis"), 0.0)

    axis_distance = abs(target_axis - candidate_axis) / 2.0
    vector_dist = vector_distance(
        target_analysis.get("perspective_vector", {}),
        candidate_analysis.get("perspective_vector", {}),
    )
    opposite_bonus = 15.0 if target_axis * candidate_axis < 0 else 0.0

    return min(
        100.0,
        0.60 * axis_distance + 0.40 * vector_dist + opposite_bonus,
    )


def relevance_score(target_row: pd.Series, candidate_row: pd.Series) -> float:
    """
    issue / issue_tags / metadata lexical overlap 기반 관련도 계산.
    """
    target_issue = safe_str(target_row.get("issue"))
    candidate_issue = safe_str(candidate_row.get("issue"))

    target_tags = safe_str(target_row.get("issue_tags"))
    candidate_tags = safe_str(candidate_row.get("issue_tags"))

    target_meta = metadata_text(target_row)
    candidate_meta = metadata_text(candidate_row)
    lexical = lexical_similarity(target_meta, candidate_meta)

    if target_issue and candidate_issue and target_issue == candidate_issue:
        return min(100.0, 85.0 + lexical * 15.0)

    target_tag_set = set(tag.strip() for tag in target_tags.split(";") if tag.strip())
    candidate_tag_set = set(tag.strip() for tag in candidate_tags.split(";") if tag.strip())

    tag_overlap = 0.0
    if target_tag_set and candidate_tag_set:
        tag_overlap = len(target_tag_set & candidate_tag_set) / len(target_tag_set | candidate_tag_set)

    if tag_overlap > 0:
        return min(100.0, 65.0 + tag_overlap * 25.0 + lexical * 10.0)

    return min(100.0, 30.0 + lexical * 70.0)


def quality_score(candidate_analysis: Dict) -> float:
    source_balance = safe_float(candidate_analysis.get("source_balance"), 50.0)
    evidence_quality = safe_float(candidate_analysis.get("evidence_quality"), 50.0)
    return min(100.0, 0.45 * source_balance + 0.55 * evidence_quality)


def recommendation_score(
    target_row: pd.Series,
    candidate_row: pd.Series,
    target_analysis: Dict,
    candidate_analysis: Dict,
) -> Dict:
    """
    최종 추천 점수 계산.
    - 관련도(relevance)
    - 편향 거리(bias distance)
    - 품질(quality)
    - 프레임 다양성(frame difference)
    를 조합한다.
    """
    rel = relevance_score(target_row, candidate_row)
    dist = bias_distance_score(target_analysis, candidate_analysis)
    qual = quality_score(candidate_analysis)

    target_frame = safe_str(target_row.get("frame"))
    candidate_frame = safe_str(candidate_row.get("frame"))
    frame_diff_bonus = 10.0 if target_frame and candidate_frame and target_frame != candidate_frame else 0.0
    relevance_penalty = -15.0 if rel < 60 else 0.0

    score = 0.50 * rel + 0.30 * dist + 0.15 * qual + 0.05 * frame_diff_bonus + relevance_penalty
    score = min(100.0, max(0.0, score))

    return {
        "relevance_score": round(rel, 4),
        "bias_distance_score": round(dist, 4),
        "quality_score": round(qual, 4),
        "frame_diff_bonus": round(frame_diff_bonus, 4),
        "relevance_penalty": round(relevance_penalty, 4),
        "recommendation_score": round(score, 4),
    }


def estimate_upper_bound(target_row: pd.Series, candidate_row: pd.Series) -> float:
    """
    B&B에서 사용하는 upper bound(상한값) 추정 함수.
    실제 추천 점수와 동일하지는 않지만,
    이 후보/분기가 최대 어느 정도 점수를 낼 수 있을지 보수적으로 추정한다.
    """
    target_meta = metadata_text(target_row)
    candidate_meta = metadata_text(candidate_row)

    similarity = lexical_similarity(target_meta, candidate_meta)
    same_issue = safe_str(target_row.get("issue")) and safe_str(target_row.get("issue")) == safe_str(candidate_row.get("issue"))
    different_frame = safe_str(target_row.get("frame")) != safe_str(candidate_row.get("frame"))
    different_source = safe_str(target_row.get("source")) != safe_str(candidate_row.get("source"))
    has_content = bool(safe_str(candidate_row.get("content")) or safe_str(candidate_row.get("preprocessed_content")))

    relevance_est = 100.0 if same_issue else min(80.0, 45.0 + similarity * 120.0)
    diversity_est = 85.0 if different_frame else 50.0
    source_est = 70.0 if different_source else 50.0
    content_est = 75.0 if has_content else 55.0

    upper_bound = 0.35 * relevance_est + 0.35 * diversity_est + 0.15 * source_est + 0.15 * content_est
    return min(100.0, max(0.0, upper_bound))


def build_branches(df: pd.DataFrame, candidate_indices: List[int], target_row: pd.Series) -> List[Branch]:
    # B&B(분기한정법) 설명:
    # 전체 후보를 한 번에 다 평가하지 않고, issue/frame 기준으로 후보를 "분기(branch)"로 묶는다.
    # 각 branch에 대해 최고 잠재 점수 upper_bound(상한값)를 먼저 계산한 뒤,
    # 상한이 높은 branch부터 탐색한다.
    # 이렇게 하면 유망하지 않은 branch를 늦게 보거나 사실상 생략할 수 있어,
    # 적은 LLM 호출로도 좋은 추천을 찾기 쉽다.
    grouped = {}
    for idx in candidate_indices:
        row = df.loc[idx]
        key_parts = [safe_str(row.get("issue")), safe_str(row.get("frame"))]
        branch_key = " | ".join([part for part in key_parts if part]) or "unknown"
        grouped.setdefault(branch_key, []).append(idx)

    branches = []
    for branch_key, indices in grouped.items():
        upper_bound = max(estimate_upper_bound(target_row, df.loc[idx]) for idx in indices)
        branches.append(Branch(upper_bound=upper_bound, branch_key=branch_key, candidate_indices=indices))

    branches.sort(key=lambda branch: branch.upper_bound, reverse=True)
    return branches


def is_recommendation_suitable(best: Optional[Dict], min_score: float, min_relevance: float) -> bool:
    if not best:
        return False
    final_score = safe_float(best.get("final_score"), 0.0)
    detail = best.get("score_detail", {}) or {}
    rel = safe_float(detail.get("relevance_score"), 0.0)
    return final_score >= min_score and rel >= min_relevance


def naver_search_news(query: str, display: int = DEFAULT_TOP_K_SEARCH) -> List[Dict]:
    import os

    client_id = os.getenv("NAVER_CLIENT_ID")
    client_secret = os.getenv("NAVER_CLIENT_SECRET")
    if not client_id or not client_secret:
        return []

    headers = {
        "X-Naver-Client-Id": client_id,
        "X-Naver-Client-Secret": client_secret,
    }
    params = {
        "query": query,
        "display": min(display, 100),
        "start": 1,
        "sort": "date",
    }

    response = requests.get(NAVER_NEWS_API_URL, headers=headers, params=params, timeout=15)
    response.raise_for_status()

    rows = []
    for item in response.json().get("items", []):
        url = item.get("originallink") or item.get("link") or ""
        rows.append(
            {
                "issue": query,
                "issue_tags": "naver_search",
                "url": url,
                "title": clean_html(item.get("title", "")),
                "source": "naver_search",
                "frame": "search_candidate",
                "memo": clean_html(item.get("description", "")),
                "content": "",
            }
        )

    return rows


def build_naver_query(target_row: pd.Series, target_analysis: Dict) -> str:
    topic = safe_str(target_analysis.get("topic"))
    title = safe_str(target_row.get("title"))
    issue = safe_str(target_row.get("issue"))
    query_parts = [topic, issue, title]
    query = " ".join(part for part in query_parts if part)
    return query[:120]


def run_bnb_on_candidates(
    df: pd.DataFrame,
    target_idx: int,
    target_analysis: Dict,
    candidate_indices: List[int],
    budget: AnalyzerCallBudget,
    gap_threshold: float,
    reserve_calls: int = 0,
) -> Dict:
    target_row = df.loc[target_idx]
    target_row = enrich_row_with_analysis_hints(target_row, target_analysis)

    # B&B(분기한정법) 핵심 흐름:
    # 1) 후보를 여러 branch로 나눈다.
    # 2) 각 branch의 최고 가능 점수 upper_bound를 계산한다.
    # 3) upper_bound가 가장 높은 branch부터 실제 평가한다.
    # 4) 현재 최고 해(incumbent)가 충분히 좋으면,
    #    남은 branch들의 upper_bound와 비교해 더 볼 필요 없는 경우 탐색을 중단한다.
    branches = build_branches(df=df, candidate_indices=candidate_indices, target_row=target_row)
    incumbent = None
    incumbent_score = -1.0
    evaluated = []
    visited = set()
    stop_reason = "exhausted"

    while branches and budget.remaining() > reserve_calls:
        branches.sort(key=lambda branch: branch.upper_bound, reverse=True)
        global_upper_bound = branches[0].upper_bound

        if incumbent is not None:
            optimality_gap = max(0.0, (global_upper_bound - incumbent_score) / max(global_upper_bound, 1.0))

            # B&B의 "한정(bound)" 부분:
            # 남아 있는 branch들의 최고 가능 점수(global_upper_bound)가
            # 현재 최고 점수(incumbent_score)를 거의 이기지 못한다면,
            # 더 탐색해도 개선 여지가 작다고 보고 중단한다.
            if optimality_gap <= gap_threshold:
                stop_reason = "optimality_gap"
                break

        # B&B의 "분기(branch) 선택" 부분:
        # upper_bound가 가장 높은, 즉 가장 유망한 branch를 먼저 꺼낸다.
        branch = branches.pop(0)
        branch.candidate_indices = sorted(
            branch.candidate_indices,
            key=lambda idx: estimate_upper_bound(target_row, df.loc[idx]),
            reverse=True,
        )

        candidate_idx = None
        while branch.candidate_indices:
            idx = branch.candidate_indices.pop(0)
            if idx not in visited:
                candidate_idx = idx
                break

        if candidate_idx is None:
            continue

        visited.add(candidate_idx)
        candidate_row = df.loc[candidate_idx]
        candidate_row = crawl_candidate_if_needed(candidate_row)

        try:
            candidate_analysis = get_or_create_analysis(candidate_row, budget, analysis_cache)
        except AnalyzerCallBudgetExceeded:
            stop_reason = "llm_call_limit"
            break

        candidate_row = enrich_row_with_analysis_hints(candidate_row, candidate_analysis)

        score_detail = recommendation_score(
            target_row=target_row,
            candidate_row=candidate_row,
            target_analysis=target_analysis,
            candidate_analysis=candidate_analysis,
        )
        final_score = safe_float(score_detail.get("recommendation_score"), 0.0)

        record = {
            "candidate_idx": int(candidate_idx),
            "branch": branch.branch_key,
            "url": safe_str(candidate_row.get("url")),
            "title": safe_str(candidate_row.get("title")),
            "source": safe_str(candidate_row.get("source")),
            "frame": safe_str(candidate_row.get("frame")),
            "upper_bound": round(branch.upper_bound, 4),
            "final_score": round(final_score, 4),
            "score_detail": score_detail,
            "candidate_analysis": candidate_analysis,
        }
        evaluated.append(record)

        # 현재까지 가장 좋은 해(incumbent) 갱신
        if final_score > incumbent_score:
            incumbent_score = final_score
            incumbent = record

        # 같은 branch 안에 아직 평가하지 않은 후보가 남아 있으면,
        # branch의 upper_bound를 다시 계산해 탐색 큐에 넣는다.
        if branch.candidate_indices:
            branch.upper_bound = max(
                estimate_upper_bound(target_row, df.loc[idx])
                for idx in branch.candidate_indices
            )
            branches.append(branch)

    remaining_upper_bound = max(
        [branch.upper_bound for branch in branches],
        default=incumbent_score if incumbent is not None else 0.0,
    )
    if incumbent is None:
        final_gap = None
    else:
        final_gap = max(
            0.0,
            (remaining_upper_bound - incumbent_score) / max(remaining_upper_bound, 1.0),
        )

    return {
        "best": incumbent,
        "evaluated": evaluated,
        "stop_reason": stop_reason,
        "optimality_gap": None if final_gap is None else round(final_gap, 4),
    }


analysis_cache = {}


def branch_and_bound_recommend(
    df: pd.DataFrame,
    target_idx: int,
    max_llm_calls: int = MAX_LLM_CALLS,
    gap_threshold: float = GAP_THRESHOLD,
    use_naver: bool = True,
    naver_display: int = DEFAULT_TOP_K_SEARCH,
    min_score: float = 70.0,
    min_relevance: float = 60.0,
) -> Dict:
    """
    추천 파이프라인 메인 함수.
    1) target 분석
    2) DB 후보에 대해 B&B 탐색
    3) DB 추천이 부족하면 네이버 검색 후보 확장
    4) 최종 추천 반환
    """
    global analysis_cache
    analysis_cache = {}

    df = df.copy()
    budget = AnalyzerCallBudget(max_calls=max_llm_calls)

    target_row = df.loc[target_idx]
    target_analysis = get_or_create_analysis(target_row, budget, analysis_cache)
    target_row = enrich_row_with_analysis_hints(target_row, target_analysis)
    for col in ["issue", "issue_tags", "frame"]:
        df.at[target_idx, col] = target_row.get(col)

    candidate_indices = [idx for idx in df.index.tolist() if idx != target_idx]

    if "url" in df.columns:
        target_url = safe_str(target_row.get("url")).strip()
        candidate_indices = [
            idx for idx in candidate_indices
            if safe_str(df.loc[idx].get("url")).strip() != target_url
        ]

    reserve_calls = 2 if use_naver else 0
    db_result = run_bnb_on_candidates(
        df=df,
        target_idx=target_idx,
        target_analysis=target_analysis,
        candidate_indices=candidate_indices,
        budget=budget,
        gap_threshold=gap_threshold,
        reserve_calls=reserve_calls,
    )

    best = db_result.get("best")
    search_used = False
    search_result = None

    if use_naver and not is_recommendation_suitable(best, min_score=min_score, min_relevance=min_relevance):
        query = build_naver_query(target_row, target_analysis)
        search_rows = naver_search_news(query=query, display=naver_display)

        if search_rows and budget.remaining() > 0:
            search_used = True
            start_idx = len(df)
            df = pd.concat([df, pd.DataFrame(search_rows)], ignore_index=True)

            # 중복 URL 제거 + target URL 제거
            target_url = safe_str(target_row.get("url")).strip()
            seen_urls = set()
            search_indices = []
            for idx in range(start_idx, len(df)):
                candidate_url = safe_str(df.loc[idx].get("url")).strip()
                if not candidate_url or candidate_url == target_url or candidate_url in seen_urls:
                    continue
                seen_urls.add(candidate_url)
                search_indices.append(idx)

            if search_indices:
                search_result = run_bnb_on_candidates(
                    df=df,
                    target_idx=target_idx,
                    target_analysis=target_analysis,
                    candidate_indices=search_indices,
                    budget=budget,
                    gap_threshold=gap_threshold,
                    reserve_calls=0,
                )
                search_best = search_result.get("best")
                if search_best and (
                    best is None or safe_float(search_best.get("final_score"), 0.0) > safe_float(best.get("final_score"), 0.0)
                ):
                    best = search_best
            else:
                search_result = {
                    "best": None,
                    "evaluated": [],
                    "stop_reason": "no_search_candidates_after_filter",
                    "optimality_gap": None,
                }

    all_evaluated = []
    all_evaluated.extend(db_result.get("evaluated", []))
    if search_result:
        all_evaluated.extend(search_result.get("evaluated", []))

    if search_result and search_result.get("stop_reason") == "optimality_gap":
        stop_reason = "optimality_gap"
        final_gap = search_result.get("optimality_gap")
    elif db_result.get("stop_reason") == "optimality_gap":
        stop_reason = "optimality_gap"
        final_gap = db_result.get("optimality_gap")
    elif budget.calls >= max_llm_calls:
        stop_reason = "llm_call_limit"
        final_gap = search_result.get("optimality_gap") if search_result else db_result.get("optimality_gap")
    else:
        stop_reason = "exhausted"
        final_gap = search_result.get("optimality_gap") if search_result else db_result.get("optimality_gap")

    return {
        "target_idx": int(target_idx),
        "target_url": safe_str(target_row.get("url")),
        "target_title": safe_str(target_row.get("title")),
        "target_analysis": target_analysis,
        "best_recommendation": best,
        "db_best": db_result.get("best"),
        "search_best": search_result.get("best") if search_result else None,
        "search_used": search_used,
        "evaluated_count": len(all_evaluated),
        "llm_calls": budget.calls,
        "optimality_gap": final_gap,
        "gap_threshold": gap_threshold,
        "max_llm_calls": max_llm_calls,
        "stop_reason": stop_reason,
        "evaluated_candidates": all_evaluated,
        "created_at": now_iso(),
    }


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--input", default="issue_news_db_with_content.csv")
    parser.add_argument("--output", default="recommendation_result.json")
    parser.add_argument("--url", default="")
    parser.add_argument("--target-idx", type=int, default=None)
    parser.add_argument("--max-llm-calls", type=int, default=MAX_LLM_CALLS)
    parser.add_argument("--gap", type=float, default=GAP_THRESHOLD)
    parser.add_argument("--no-naver", action="store_true")
    parser.add_argument("--naver-display", type=int, default=DEFAULT_TOP_K_SEARCH)
    parser.add_argument("--min-score", type=float, default=70.0)
    parser.add_argument("--min-relevance", type=float, default=60.0)
    parser.add_argument("--encoding", default="utf-8-sig")
    args = parser.parse_args()

    df = pd.read_csv(args.input, encoding=args.encoding)

    if args.url:
        df, target_idx = append_or_find_target_url(df=df, news_url=args.url)
    elif args.target_idx is not None:
        target_idx = args.target_idx
    else:
        raise ValueError(
            "추천 기준 기사가 필요합니다. --url 뉴스기사URL 또는 --target-idx 행번호 중 하나를 입력하세요."
        )

    result = branch_and_bound_recommend(
        df=df,
        target_idx=target_idx,
        max_llm_calls=args.max_llm_calls,
        gap_threshold=args.gap,
        use_naver=not args.no_naver,
        naver_display=args.naver_display,
        min_score=args.min_score,
        min_relevance=args.min_relevance,
    )

    with open(args.output, "w", encoding="utf-8") as file:
        json.dump(result, file, ensure_ascii=False, indent=2)

    print_result_summary(result, args.output)


def print_result_summary(result: Dict, output_path: str) -> None:
    print(
        json.dumps(
            {
                "saved": output_path,
                "stop_reason": result.get("stop_reason"),
                "llm_calls": result.get("llm_calls"),
                "optimality_gap": result.get("optimality_gap"),
                "search_used": result.get("search_used"),
                "target_title": result.get("target_title"),
                "best_title": (result.get("best_recommendation") or {}).get("title"),
                "best_url": (result.get("best_recommendation") or {}).get("url"),
                "best_score": (result.get("best_recommendation") or {}).get("final_score"),
            },
            ensure_ascii=False,
            indent=2,
        )
    )


if __name__ == "__main__":
    main()



# def example_analysis_from_frame(frame: str) -> dict:
#     """
#     analyzer.py에서 넘어오는 편향 수치 예시.
#     실제로는 analyzer.py가 기사별로 이 dict를 만들어서 analysis_json에 저장하거나,
#     recommender.py에 전달하면 된다.
#     """

#     frame = safe_str(frame)

#     profiles = {
#         "노동자_생활": {
#             "topic": "최저임금",
#             "main_frame": "노동자_생활",
#             "stance": "supportive",
#             "bias_axis": 70,
#             "bias_strength": 78,
#             "emotionality": 28,
#             "source_balance": 58,
#             "evidence_quality": 74,
#             "perspective_vector": {
#                 "pro_government": 35,
#                 "anti_government": 10,
#                 "pro_business": 10,
#                 "pro_labor": 95,
#                 "pro_market": 20,
#                 "pro_welfare": 90,
#                 "pro_regulation": 75,
#                 "anti_regulation": 10,
#                 "risk_emphasis": 25,
#                 "benefit_emphasis": 85,
#             },
#             "reasoning": "노동자 생계 보장 관점을 강하게 반영한 편향 수치 예시",
#         },
#         "경영계_부담": {
#             "topic": "최저임금",
#             "main_frame": "경영계_부담",
#             "stance": "critical",
#             "bias_axis": -75,
#             "bias_strength": 80,
#             "emotionality": 35,
#             "source_balance": 55,
#             "evidence_quality": 70,
#             "perspective_vector": {
#                 "pro_government": 10,
#                 "anti_government": 30,
#                 "pro_business": 90,
#                 "pro_labor": 10,
#                 "pro_market": 80,
#                 "pro_welfare": 15,
#                 "pro_regulation": 10,
#                 "anti_regulation": 75,
#                 "risk_emphasis": 85,
#                 "benefit_emphasis": 20,
#             },
#             "reasoning": "소상공인·기업 부담 관점을 강하게 반영한 편향 수치 예시",
#         },
#         "산업_성장": {
#             "topic": "AI 반도체",
#             "main_frame": "산업_성장",
#             "stance": "supportive",
#             "bias_axis": 60,
#             "bias_strength": 65,
#             "emotionality": 20,
#             "source_balance": 60,
#             "evidence_quality": 72,
#             "perspective_vector": {
#                 "pro_government": 35,
#                 "anti_government": 10,
#                 "pro_business": 85,
#                 "pro_labor": 20,
#                 "pro_market": 80,
#                 "pro_welfare": 20,
#                 "pro_regulation": 20,
#                 "anti_regulation": 65,
#                 "risk_emphasis": 30,
#                 "benefit_emphasis": 85,
#             },
#             "reasoning": "산업 성장과 기업 경쟁력을 강조한 편향 수치 예시",
#         },
#         "성과_쏠림": {
#             "topic": "AI 반도체",
#             "main_frame": "성과_쏠림",
#             "stance": "critical",
#             "bias_axis": -45,
#             "bias_strength": 65,
#             "emotionality": 30,
#             "source_balance": 62,
#             "evidence_quality": 70,
#             "perspective_vector": {
#                 "pro_government": 20,
#                 "anti_government": 35,
#                 "pro_business": 35,
#                 "pro_labor": 65,
#                 "pro_market": 35,
#                 "pro_welfare": 70,
#                 "pro_regulation": 55,
#                 "anti_regulation": 20,
#                 "risk_emphasis": 75,
#                 "benefit_emphasis": 30,
#             },
#             "reasoning": "성과 쏠림과 분배 불균형을 강조한 편향 수치 예시",
#         },
#         "시장_회복": {
#             "topic": "부동산 금리",
#             "main_frame": "시장_회복",
#             "stance": "supportive",
#             "bias_axis": 50,
#             "bias_strength": 55,
#             "emotionality": 20,
#             "source_balance": 65,
#             "evidence_quality": 72,
#             "perspective_vector": {
#                 "pro_government": 35,
#                 "anti_government": 20,
#                 "pro_business": 70,
#                 "pro_labor": 25,
#                 "pro_market": 85,
#                 "pro_welfare": 25,
#                 "pro_regulation": 20,
#                 "anti_regulation": 65,
#                 "risk_emphasis": 35,
#                 "benefit_emphasis": 75,
#             },
#             "reasoning": "시장 회복과 정상화를 강조한 편향 수치 예시",
#         },
#         "주거_불안": {
#             "topic": "부동산 금리",
#             "main_frame": "주거_불안",
#             "stance": "critical",
#             "bias_axis": -55,
#             "bias_strength": 70,
#             "emotionality": 35,
#             "source_balance": 60,
#             "evidence_quality": 68,
#             "perspective_vector": {
#                 "pro_government": 20,
#                 "anti_government": 35,
#                 "pro_business": 25,
#                 "pro_labor": 40,
#                 "pro_market": 25,
#                 "pro_welfare": 80,
#                 "pro_regulation": 70,
#                 "anti_regulation": 15,
#                 "risk_emphasis": 85,
#                 "benefit_emphasis": 20,
#             },
#             "reasoning": "주거비 부담과 가계부채 위험을 강조한 편향 수치 예시",
#         },
#     }

#     default_profile = {
#         "topic": "",
#         "main_frame": frame,
#         "stance": "neutral",
#         "bias_axis": 0,
#         "bias_strength": 20,
#         "emotionality": 10,
#         "source_balance": 60,
#         "evidence_quality": 60,
#         "perspective_vector": {
#             "pro_government": 30,
#             "anti_government": 30,
#             "pro_business": 40,
#             "pro_labor": 40,
#             "pro_market": 40,
#             "pro_welfare": 40,
#             "pro_regulation": 40,
#             "anti_regulation": 40,
#             "risk_emphasis": 40,
#             "benefit_emphasis": 40,
#         },
#         "reasoning": "중립 또는 미분류 프레임의 기본 편향 수치 예시",
#     }

#     return profiles.get(frame, default_profile)


# def attach_example_analysis_json(df: pd.DataFrame) -> pd.DataFrame:
#     """
#     실제 CSV의 기사 title/url은 그대로 쓰고,
#     analyzer.py에서 넘어온 편향 수치라고 가정한 analysis_json만 붙인다.
#     """

#     df = df.copy()

#     for idx, row in df.iterrows():
#         analysis = example_analysis_from_frame(row.get("frame"))

#         if not analysis.get("topic"):
#             analysis["topic"] = safe_str(row.get("issue"))

#         analysis["summary"] = safe_str(row.get("memo"))
#         analysis["main_frame"] = safe_str(row.get("frame"))

#         df.at[idx, "analysis_json"] = json.dumps(
#             analysis,
#             ensure_ascii=False,
#         )

#     return df


# def find_existing_csv_for_example() -> str:
#     """
#     현재 폴더에서 실제 DB CSV 파일을 찾는다.
#     """

#     candidate_files = [
#         "issue_news_db_merged.csv",
#         "issue_news_db_with_content.csv",
#         "issue_news_db_merged_all_rows.csv",
#     ]

#     import os

#     for file_name in candidate_files:
#         if os.path.exists(file_name):
#             return file_name

#     raise FileNotFoundError(
#         "CSV 파일을 찾지 못했습니다. "
#         "issue_news_db_merged.csv 또는 issue_news_db_with_content.csv를 "
#         "recommender.py와 같은 폴더에 두세요."
#     )


# def choose_example_target_idx(df: pd.DataFrame) -> int:
#     """
#     예시 실행용 추천 기준 기사 선택.
#     가능하면 최저임금 + 노동자_생활 프레임을 기준 기사로 잡는다.
#     없으면 0번 행 사용.
#     """

#     if "issue" in df.columns and "frame" in df.columns:
#         matched = df.index[
#             (df["issue"].astype(str) == "최저임금")
#             & (df["frame"].astype(str) == "노동자_생활")
#         ].tolist()

#         if matched:
#             return matched[0]

#     return 0


# def make_naver_search_with_example_analysis(original_naver_search_func):
#     """
#     기존 naver_search_news를 감싸서,
#     네이버 검색 결과에도 analyzer.py 출력 예시인 analysis_json을 붙인다.

#     실제 구현에서는 여기서 crawler.py + analyzer.py를 호출해
#     검색 결과 URL의 편향 수치를 만들어야 한다.
#     """

#     def wrapped_naver_search_news(query: str, display: int = DEFAULT_TOP_K_SEARCH) -> List[Dict]:
#         rows = original_naver_search_func(
#             query=query,
#             display=display,
#         )

#         enriched_rows = []

#         for row in rows:
#             title = safe_str(row.get("title"))
#             memo = safe_str(row.get("memo"))
#             text = f"{title} {memo}"

#             if "부담" in text or "소상공인" in text or "자영업" in text or "기업" in text:
#                 frame = "경영계_부담"
#             elif "노동자" in text or "생계" in text or "임금" in text:
#                 frame = "노동자_생활"
#             else:
#                 frame = safe_str(row.get("frame")) or "search_candidate"

#             analysis = example_analysis_from_frame(frame)

#             if not analysis.get("topic"):
#                 analysis["topic"] = safe_str(row.get("issue"))

#             analysis["summary"] = safe_str(row.get("memo"))
#             analysis["main_frame"] = frame

#             row = dict(row)
#             row["frame"] = frame
#             row["analysis_json"] = json.dumps(
#                 analysis,
#                 ensure_ascii=False,
#             )

#             enriched_rows.append(row)

#         return enriched_rows

#     return wrapped_naver_search_news


# def run_example_using_real_csv_and_optional_naver():
#     """
#     최종 예시 실행 코드.

#     동작:
#     1. 실제 CSV 파일을 읽는다.
#     2. CSV의 실제 기사 title/url을 사용한다.
#     3. analyzer.py에서 넘어온 편향 수치 예시를 analysis_json으로 붙인다.
#     4. 먼저 CSV DB 안에서 B&B 추천을 수행한다.
#     5. DB 추천이 부적절하면 네이버 검색 API를 사용한다.
#     6. 네이버 검색 결과에도 analyzer.py 출력 예시 수치를 붙여 B&B 추천을 수행한다.
#     """

#     global naver_search_news

#     input_csv = find_existing_csv_for_example()
#     output_path = "recommendation_real_csv_example_result.json"

#     df = pd.read_csv(
#         input_csv,
#         encoding="utf-8-sig",
#     )

#     df = attach_example_analysis_json(df)

#     target_idx = choose_example_target_idx(df)

#     original_naver_search_func = naver_search_news
#     naver_search_news = make_naver_search_with_example_analysis(
#         original_naver_search_func
#     )

#     result = branch_and_bound_recommend(
#         df=df,
#         target_idx=target_idx,
#         max_llm_calls=5,
#         gap_threshold=0.10,
#         use_naver=True,
#         naver_display=10,
#         min_score=70.0,
#         min_relevance=60.0,
#     )

#     with open(
#         output_path,
#         "w",
#         encoding="utf-8",
#     ) as file:
#         json.dump(
#             result,
#             file,
#             ensure_ascii=False,
#             indent=2,
#         )

#     print("=" * 80)
#     print("REAL CSV DB → RECOMMENDER EXAMPLE")
#     print("=" * 80)

#     print(f"input_csv: {input_csv}")
#     print_result_summary(result, output_path)

#     print()
#     print("추천 기준 기사")
#     print("-" * 80)
#     print(f"title: {result.get('target_title')}")
#     print(f"url: {result.get('target_url')}")

#     print()
#     print("DB 추천 결과")
#     print("-" * 80)

#     db_best = result.get("db_best")

#     if db_best:
#         print(f"title: {db_best.get('title')}")
#         print(f"url: {db_best.get('url')}")
#         print(f"source: {db_best.get('source')}")
#         print(f"frame: {db_best.get('frame')}")
#         print(f"score: {db_best.get('final_score')}")
#         print("score_detail:")
#         print(
#             json.dumps(
#                 db_best.get("score_detail", {}),
#                 ensure_ascii=False,
#                 indent=2,
#             )
#         )
#     else:
#         print("CSV DB에서 추천 후보를 찾지 못했습니다.")

#     print()
#     print("네이버 검색 사용 여부")
#     print("-" * 80)
#     print(f"search_used: {result.get('search_used')}")

#     search_best = result.get("search_best")

#     if search_best:
#         print()
#         print("네이버 검색 추천 결과")
#         print("-" * 80)
#         print(f"title: {search_best.get('title')}")
#         print(f"url: {search_best.get('url')}")
#         print(f"source: {search_best.get('source')}")
#         print(f"frame: {search_best.get('frame')}")
#         print(f"score: {search_best.get('final_score')}")
#         print("score_detail:")
#         print(
#             json.dumps(
#                 search_best.get("score_detail", {}),
#                 ensure_ascii=False,
#                 indent=2,
#             )
#         )

#     print()
#     print("최종 추천 결과")
#     print("-" * 80)

#     best = result.get("best_recommendation")

#     if best:
#         print(f"title: {best.get('title')}")
#         print(f"url: {best.get('url')}")
#         print(f"source: {best.get('source')}")
#         print(f"frame: {best.get('frame')}")
#         print(f"score: {best.get('final_score')}")
#     else:
#         print("최종 추천 결과가 없습니다.")

#     print("-" * 80)
#     print(f"saved: {output_path}")


# if __name__ == "__main__":
#     run_example_using_real_csv_and_optional_naver()

# ====================

# def example_analysis_from_frame_for_missing_topic_demo(frame: str) -> dict:
#     """
#     analyzer.py에서 넘어오는 편향 수치 예시.
#     실제 구현에서는 analyzer.py가 기사 본문을 보고 이 수치를 만든다.
#     여기서는 CSV/네이버 후보에 예시 수치를 붙이기 위한 테스트용 함수다.
#     """

#     frame = safe_str(frame)

#     profiles = {
#         "노동자_생활": {
#             "topic": "최저임금",
#             "main_frame": "노동자_생활",
#             "stance": "supportive",
#             "bias_axis": 70,
#             "bias_strength": 78,
#             "emotionality": 28,
#             "source_balance": 58,
#             "evidence_quality": 74,
#             "perspective_vector": {
#                 "pro_government": 35,
#                 "anti_government": 10,
#                 "pro_business": 10,
#                 "pro_labor": 95,
#                 "pro_market": 20,
#                 "pro_welfare": 90,
#                 "pro_regulation": 75,
#                 "anti_regulation": 10,
#                 "risk_emphasis": 25,
#                 "benefit_emphasis": 85,
#             },
#             "reasoning": "노동자 생계 보장 관점을 강조한 편향 수치 예시",
#         },
#         "경영계_부담": {
#             "topic": "최저임금",
#             "main_frame": "경영계_부담",
#             "stance": "critical",
#             "bias_axis": -75,
#             "bias_strength": 80,
#             "emotionality": 35,
#             "source_balance": 55,
#             "evidence_quality": 70,
#             "perspective_vector": {
#                 "pro_government": 10,
#                 "anti_government": 30,
#                 "pro_business": 90,
#                 "pro_labor": 10,
#                 "pro_market": 80,
#                 "pro_welfare": 15,
#                 "pro_regulation": 10,
#                 "anti_regulation": 75,
#                 "risk_emphasis": 85,
#                 "benefit_emphasis": 20,
#             },
#             "reasoning": "소상공인·기업 부담 관점을 강조한 편향 수치 예시",
#         },
#         "의료_공공성": {
#             "topic": "의료대란",
#             "main_frame": "의료_공공성",
#             "stance": "supportive",
#             "bias_axis": 65,
#             "bias_strength": 72,
#             "emotionality": 35,
#             "source_balance": 62,
#             "evidence_quality": 70,
#             "perspective_vector": {
#                 "pro_government": 55,
#                 "anti_government": 15,
#                 "pro_business": 20,
#                 "pro_labor": 55,
#                 "pro_market": 15,
#                 "pro_welfare": 90,
#                 "pro_regulation": 75,
#                 "anti_regulation": 10,
#                 "risk_emphasis": 65,
#                 "benefit_emphasis": 75,
#             },
#             "reasoning": "의료 공공성, 환자 안전, 지역 필수의료 강화를 강조한 편향 수치 예시",
#         },
#         "의료_현장부담": {
#             "topic": "의료대란",
#             "main_frame": "의료_현장부담",
#             "stance": "critical",
#             "bias_axis": -65,
#             "bias_strength": 75,
#             "emotionality": 40,
#             "source_balance": 58,
#             "evidence_quality": 68,
#             "perspective_vector": {
#                 "pro_government": 10,
#                 "anti_government": 65,
#                 "pro_business": 30,
#                 "pro_labor": 80,
#                 "pro_market": 35,
#                 "pro_welfare": 65,
#                 "pro_regulation": 25,
#                 "anti_regulation": 65,
#                 "risk_emphasis": 90,
#                 "benefit_emphasis": 25,
#             },
#             "reasoning": "의료 현장 부담, 전공의·의료진 반발, 정책 부작용을 강조한 편향 수치 예시",
#         },
#         "search_candidate": {
#             "topic": "",
#             "main_frame": "search_candidate",
#             "stance": "neutral",
#             "bias_axis": 0,
#             "bias_strength": 25,
#             "emotionality": 15,
#             "source_balance": 60,
#             "evidence_quality": 60,
#             "perspective_vector": {
#                 "pro_government": 30,
#                 "anti_government": 30,
#                 "pro_business": 40,
#                 "pro_labor": 40,
#                 "pro_market": 40,
#                 "pro_welfare": 40,
#                 "pro_regulation": 40,
#                 "anti_regulation": 40,
#                 "risk_emphasis": 40,
#                 "benefit_emphasis": 40,
#             },
#             "reasoning": "검색 후보 기본 편향 수치 예시",
#         },
#     }

#     default_profile = profiles["search_candidate"]

#     # 원본 dict가 오염되지 않도록 깊은 복사
#     return json.loads(
#         json.dumps(
#             profiles.get(frame, default_profile),
#             ensure_ascii=False,
#         )
#     )


# def attach_example_analysis_json_for_missing_topic_demo(df: pd.DataFrame) -> pd.DataFrame:
#     """
#     실제 CSV의 title/url은 그대로 사용하고,
#     analyzer.py 출력 예시 analysis_json을 붙인다.
#     """

#     df = df.copy()

#     for idx, row in df.iterrows():
#         frame = safe_str(row.get("frame"))
#         analysis = example_analysis_from_frame_for_missing_topic_demo(frame)

#         if not analysis.get("topic"):
#             analysis["topic"] = safe_str(row.get("issue"))

#         analysis["summary"] = safe_str(row.get("memo"))
#         analysis["main_frame"] = frame

#         df.at[idx, "analysis_json"] = json.dumps(
#             analysis,
#             ensure_ascii=False,
#         )

#     return df


# def find_existing_csv_for_missing_topic_demo() -> str:
#     """
#     현재 폴더에서 실제 DB CSV 파일을 찾는다.
#     """

#     import os

#     candidate_files = [
#         "issue_news_db_merged.csv",
#         "issue_news_db_with_content.csv",
#         "issue_news_db_merged_all_rows.csv",
#     ]

#     for file_name in candidate_files:
#         if os.path.exists(file_name):
#             return file_name

#     raise FileNotFoundError(
#         "CSV 파일을 찾지 못했습니다. "
#         "issue_news_db_merged.csv 또는 issue_news_db_with_content.csv를 "
#         "recommender.py와 같은 폴더에 두세요."
#     )


# def make_missing_topic_target_row() -> pd.Series:
#     """
#     CSV에 없는 주제를 가진 추천 기준 기사 예시.
#     analyzer.py에서 이미 편향 수치가 넘어왔다고 가정해서 analysis_json을 포함한다.

#     주제: 의료대란 / 전공의 복귀 / 의대 증원
#     """

#     target_analysis = {
#         "topic": "의료대란",
#         "summary": "전공의 복귀 지연과 응급실 진료 공백으로 환자 안전 우려가 커지는 상황을 다룬 기사다.",
#         "main_frame": "의료_공공성",
#         "stance": "supportive",
#         "bias_axis": 65,
#         "bias_strength": 72,
#         "emotionality": 35,
#         "source_balance": 62,
#         "evidence_quality": 70,
#         "perspective_vector": {
#             "pro_government": 55,
#             "anti_government": 15,
#             "pro_business": 20,
#             "pro_labor": 55,
#             "pro_market": 15,
#             "pro_welfare": 90,
#             "pro_regulation": 75,
#             "anti_regulation": 10,
#             "risk_emphasis": 65,
#             "benefit_emphasis": 75,
#         },
#         "reasoning": "환자 안전, 필수의료, 지역의료 공백 해소를 강조한 편향 수치 예시",
#     }

#     return pd.Series(
#         {
#             "issue": "의료대란",
#             "issue_tags": "의료대란;전공의;의대증원;응급실;필수의료",
#             "url": "https://example.com/medical-target",
#             "title": "전공의 복귀 지연에 응급실 공백 우려, 필수의료 대책 시급",
#             "source": "입력기사",
#             "frame": "의료_공공성",
#             "memo": "환자 안전과 필수의료 공백 해소를 강조하는 입력 기사",
#             "content": "",
#             "analysis_json": json.dumps(
#                 target_analysis,
#                 ensure_ascii=False,
#             ),
#         }
#     )


# def guess_frame_for_naver_medical_result(title: str, memo: str) -> str:
#     """
#     네이버 검색 결과 제목/요약을 보고 예시 frame을 추정한다.
#     실제 구현에서는 이 부분 대신 crawler.py + analyzer.py를 사용해야 한다.
#     """

#     text = f"{safe_str(title)} {safe_str(memo)}"

#     if (
#         "의사" in text
#         or "전공의" in text
#         or "의료진" in text
#         or "복귀" in text
#         or "반발" in text
#         or "현장" in text
#     ):
#         return "의료_현장부담"

#     if (
#         "환자" in text
#         or "응급실" in text
#         or "필수의료" in text
#         or "공공" in text
#         or "지역의료" in text
#         or "공백" in text
#     ):
#         return "의료_공공성"

#     return "search_candidate"


# def make_naver_search_with_medical_analysis_json(original_naver_search_func):
#     """
#     기존 naver_search_news를 감싸서,
#     네이버 검색 결과에 analyzer.py 출력 예시 analysis_json을 붙인다.

#     실제 구현:
#     네이버 검색 URL
#     → crawler.py 본문 수집
#     → analyzer.py 편향 수치 생성
#     → analysis_json 저장
#     → B&B 추천
#     """

#     def wrapped_naver_search_news(
#         query: str,
#         display: int = DEFAULT_TOP_K_SEARCH,
#     ) -> List[Dict]:
#         rows = original_naver_search_func(
#             query=query,
#             display=display,
#         )

#         enriched_rows = []

#         for row in rows:
#             title = safe_str(row.get("title"))
#             memo = safe_str(row.get("memo"))

#             guessed_frame = guess_frame_for_naver_medical_result(
#                 title=title,
#                 memo=memo,
#             )

#             analysis = example_analysis_from_frame_for_missing_topic_demo(
#                 guessed_frame,
#             )

#             if not analysis.get("topic"):
#                 analysis["topic"] = "의료대란"

#             analysis["summary"] = memo
#             analysis["main_frame"] = guessed_frame

#             row = dict(row)
#             row["issue"] = "의료대란"
#             row["issue_tags"] = "의료대란;전공의;의대증원;응급실;필수의료"
#             row["frame"] = guessed_frame
#             row["analysis_json"] = json.dumps(
#                 analysis,
#                 ensure_ascii=False,
#             )

#             enriched_rows.append(row)

#         return enriched_rows

#     return wrapped_naver_search_news


# def run_example_missing_topic_triggers_naver_search():
#     """
#     CSV에 없는 주제인 '의료대란'을 기준 기사로 넣어,
#     DB 추천이 자연스럽게 부적절해지고 네이버 검색으로 넘어가는 예시.

#     강제 min_score=101 같은 방식이 아니라,
#     주제 불일치 때문에 DB 추천이 낮아지는 구조다.
#     """

#     global naver_search_news

#     input_csv = find_existing_csv_for_missing_topic_demo()
#     output_path = "recommendation_missing_topic_naver_example_result.json"

#     df = pd.read_csv(
#         input_csv,
#         encoding="utf-8-sig",
#     )

#     df = attach_example_analysis_json_for_missing_topic_demo(df)

#     target_row = make_missing_topic_target_row()

#     df = pd.concat(
#         [
#             df,
#             pd.DataFrame([target_row]),
#         ],
#         ignore_index=True,
#     )

#     target_idx = len(df) - 1

#     original_naver_search_func = naver_search_news
#     naver_search_news = make_naver_search_with_medical_analysis_json(
#         original_naver_search_func
#     )

#     result = branch_and_bound_recommend(
#         df=df,
#         target_idx=target_idx,
#         max_llm_calls=5,
#         gap_threshold=0.10,
#         use_naver=True,
#         naver_display=10,
#         min_score=70.0,
#         min_relevance=60.0,
#     )

#     with open(
#         output_path,
#         "w",
#         encoding="utf-8",
#     ) as file:
#         json.dump(
#             result,
#             file,
#             ensure_ascii=False,
#             indent=2,
#         )

#     print("=" * 80)
#     print("MISSING TOPIC → DB INSUFFICIENT → NAVER SEARCH EXAMPLE")
#     print("=" * 80)

#     print(f"input_csv: {input_csv}")
#     print_result_summary(result, output_path)

#     print()
#     print("추천 기준 기사")
#     print("-" * 80)
#     print(f"title: {result.get('target_title')}")
#     print(f"url: {result.get('target_url')}")
#     print("issue: 의료대란")
#     print("frame: 의료_공공성")

#     print()
#     print("DB 추천 결과")
#     print("-" * 80)

#     db_best = result.get("db_best")

#     if db_best:
#         print(f"title: {db_best.get('title')}")
#         print(f"url: {db_best.get('url')}")
#         print(f"source: {db_best.get('source')}")
#         print(f"frame: {db_best.get('frame')}")
#         print(f"score: {db_best.get('final_score')}")
#         print("score_detail:")
#         print(
#             json.dumps(
#                 db_best.get("score_detail", {}),
#                 ensure_ascii=False,
#                 indent=2,
#             )
#         )
#     else:
#         print("CSV DB에서 추천 후보를 찾지 못했습니다.")

#     print()
#     print("네이버 검색 사용 여부")
#     print("-" * 80)
#     print(f"search_used: {result.get('search_used')}")

#     search_best = result.get("search_best")

#     print()
#     print("네이버 검색 추천 결과")
#     print("-" * 80)

#     if search_best:
#         print(f"title: {search_best.get('title')}")
#         print(f"url: {search_best.get('url')}")
#         print(f"source: {search_best.get('source')}")
#         print(f"frame: {search_best.get('frame')}")
#         print(f"score: {search_best.get('final_score')}")
#         print("score_detail:")
#         print(
#             json.dumps(
#                 search_best.get("score_detail", {}),
#                 ensure_ascii=False,
#                 indent=2,
#             )
#         )
#     else:
#         print("검색 결과 기반 추천이 없습니다.")
#         print("NAVER_CLIENT_ID / NAVER_CLIENT_SECRET 환경변수를 확인하세요.")

#     print()
#     print("최종 추천 결과")
#     print("-" * 80)

#     best = result.get("best_recommendation")

#     if best:
#         print(f"title: {best.get('title')}")
#         print(f"url: {best.get('url')}")
#         print(f"source: {best.get('source')}")
#         print(f"frame: {best.get('frame')}")
#         print(f"score: {best.get('final_score')}")
#     else:
#         print("최종 추천 결과가 없습니다.")

#     print("-" * 80)
#     print(f"saved: {output_path}")


# if __name__ == "__main__":
#     run_example_missing_topic_triggers_naver_search()