"""B&B-inspired recommendation wrapper for NewSight.

This file adds an optional Branch-and-Bound-inspired recommendation mode
without modifying the original recommender.py.
"""

from __future__ import annotations

import os
from dataclasses import dataclass

from recommender import (
    _compact,
    _dataset_notice,
    _issue_match_score,
    _load_dataset,
    _query_context,
    _split_tags,
    _specific_tag_overlap_count,
    _status_score,
    _sub_issue_difference_score,
    _voice_difference_score,
)


@dataclass
class BnbCandidate:
    score_tuple: tuple
    numeric_score: float
    upper_bound: float
    article: dict


@dataclass
class BnbBranch:
    branch_key: str
    upper_bound: float
    candidates: list


def _bnb_gap_threshold():
    try:
        return float(os.getenv("BNB_GAP_THRESHOLD", "0.10"))
    except ValueError:
        return 0.10


def _bnb_max_evaluations(dataset_name):
    default_value = "24" if dataset_name == "curated" else "36"
    try:
        return max(3, int(os.getenv("BNB_MAX_EVALUATIONS", default_value)))
    except ValueError:
        return int(default_value)


def _score_tuple_to_number(score):
    issue_match_flag = score[0]
    specific_overlap_count = score[1]
    issue_score = score[2]
    voice_diff = score[3]
    sub_issue_diff = score[4]
    status_score = score[5]
    excerpt_len = score[6]
    excerpt_bonus = min(5.0, excerpt_len / 200.0)
    return (
        100.0 * issue_match_flag
        + 20.0 * specific_overlap_count
        + 15.0 * issue_score
        + 8.0 * voice_diff
        + 5.0 * sub_issue_diff
        + 4.0 * status_score
        + excerpt_bonus
    )


def _estimate_upper_bound(issue_match_flag, specific_overlap_count, issue_score, voice_diff):
    return (
        100.0 * issue_match_flag
        + 20.0 * specific_overlap_count
        + 15.0 * issue_score
        + 8.0 * voice_diff
        + 5.0
        + 16.0
        + 5.0
    )


def _candidate_payload(row, candidate_url, candidate_tags, dataset_name, numeric_score, upper_bound):
    return {
        "issue": row.get("issue", ""),
        "title": row.get("title", ""),
        "source": row.get("source", ""),
        "date": row.get("date", ""),
        "url": candidate_url,
        "frame": row.get("frame", ""),
        "issue_tags": candidate_tags,
        "sub_issue": row.get("sub_issue", ""),
        "memo": row.get("memo", ""),
        "tone": row.get("tone", ""),
        "primary_voice": row.get("primary_voice", ""),
        "body_excerpt": row.get("body_excerpt", ""),
        "tagging_status": row.get("tagging_status", ""),
        "source_dataset": row.get("source_dataset", dataset_name),
        "bnb_score": round(numeric_score, 4),
        "bnb_upper_bound": round(upper_bound, 4),
    }


def _make_candidate(row, dataset_name, normalized_query_tags, query_frame, query_voice, query_text, input_url, input_title):
    candidate_url = (row.get("url") or "").strip()
    candidate_title = _compact(row.get("title", ""))
    candidate_frame = _compact(row.get("frame", ""))
    candidate_tags = _split_tags(row.get("issue_tags", ""))
    normalized_candidate_tags = set()
    for tag in candidate_tags:
        compact_tag = _compact(tag)
        if compact_tag:
            normalized_candidate_tags.add(compact_tag)
    if input_url and candidate_url == input_url:
        return None
    if input_title and candidate_title == input_title:
        return None
    if query_frame and candidate_frame == query_frame:
        return None
    specific_overlap_count = _specific_tag_overlap_count(normalized_query_tags, normalized_candidate_tags)
    issue_score = _issue_match_score(row.get("issue", ""), query_text)
    min_specific_overlap = 2 if dataset_name == "curated" else 3
    if issue_score <= 0 and specific_overlap_count < min_specific_overlap:
        return None
    issue_match_flag = 1 if issue_score > 0 else 0
    voice_diff = _voice_difference_score(query_voice, row.get("primary_voice", ""))
    sub_issue_diff = _sub_issue_difference_score(query_text, row.get("sub_issue", ""))
    status_score = _status_score(row)
    excerpt_len = len((row.get("body_excerpt") or "").strip())
    score_tuple = (
        issue_match_flag,
        specific_overlap_count,
        issue_score,
        voice_diff,
        sub_issue_diff,
        status_score,
        excerpt_len,
    )
    numeric_score = _score_tuple_to_number(score_tuple)
    upper_bound = _estimate_upper_bound(issue_match_flag, specific_overlap_count, issue_score, voice_diff)
    payload = _candidate_payload(row, candidate_url, candidate_tags, dataset_name, numeric_score, upper_bound)
    return BnbCandidate(score_tuple=score_tuple, numeric_score=numeric_score, upper_bound=upper_bound, article=payload)


def _collect_candidates(article, analysis, dataset_name):
    rows = _load_dataset(dataset_name)
    if not rows:
        return []
    query_tags = _split_tags(analysis.get("issue_tags", []))
    query_frame = _compact(analysis.get("frame", ""))
    query_voice = str(analysis.get("primary_voice", "")).strip()
    query_text_tags, query_text = _query_context(article, analysis)
    normalized_query_tags = set()
    for tag in query_tags + query_text_tags:
        compact_tag = _compact(tag)
        if compact_tag:
            normalized_query_tags.add(compact_tag)
    if not normalized_query_tags and not query_text.strip():
        return []
    input_url = ""
    input_title = ""
    if isinstance(article, dict):
        input_url = (article.get("url", "") or "").strip()
        input_title = _compact(article.get("title", ""))
    candidates = []
    for row in rows:
        candidate = _make_candidate(row, dataset_name, normalized_query_tags, query_frame, query_voice, query_text, input_url, input_title)
        if candidate is not None:
            candidates.append(candidate)
    return candidates


def _branch_key(candidate):
    article = candidate.article
    parts = [
        str(article.get("issue", "")).strip(),
        str(article.get("frame", "")).strip(),
        str(article.get("primary_voice", "")).strip(),
    ]
    clean_parts = [part for part in parts if part]
    return " | ".join(clean_parts) if clean_parts else "unknown"


def _build_branches(candidates):
    grouped = {}
    for candidate in candidates:
        key = _branch_key(candidate)
        grouped.setdefault(key, []).append(candidate)
    branches = []
    for branch_key, branch_candidates in grouped.items():
        branch_candidates.sort(key=lambda item: (item.upper_bound, item.numeric_score, item.score_tuple), reverse=True)
        branches.append(BnbBranch(branch_key=branch_key, upper_bound=max(item.upper_bound for item in branch_candidates), candidates=branch_candidates))
    branches.sort(key=lambda branch: branch.upper_bound, reverse=True)
    return branches


def _top_k_threshold(top_candidates, limit):
    if len(top_candidates) < limit:
        return -1.0
    ordered = sorted(top_candidates, key=lambda item: (item.numeric_score, item.score_tuple), reverse=True)
    return ordered[limit - 1].numeric_score


def _push_top_candidate(top_candidates, candidate, limit):
    top_candidates.append(candidate)
    top_candidates.sort(key=lambda item: (item.numeric_score, item.score_tuple), reverse=True)
    return top_candidates[:limit]


def _select_bnb(candidates, dataset_name, limit):
    total_candidates = len(candidates)
    if not candidates:
        return {"articles": [], "bnb_meta": {"mode": "bnb", "enabled": True, "dataset": dataset_name, "total_candidates": 0, "branch_count": 0, "evaluated_count": 0, "skipped_count": 0, "stop_reason": "no_candidate_after_filter", "optimality_gap": None}}
    branches = _build_branches(candidates)
    branch_count = len(branches)
    max_evaluations = _bnb_max_evaluations(dataset_name)
    gap_threshold = _bnb_gap_threshold()
    top_candidates = []
    evaluated_count = 0
    stop_reason = "exhausted"
    optimality_gap = None
    while branches and evaluated_count < max_evaluations:
        branches.sort(key=lambda branch: branch.upper_bound, reverse=True)
        global_upper_bound = branches[0].upper_bound
        kth_score = _top_k_threshold(top_candidates, limit)
        if kth_score >= 0:
            optimality_gap = max(0.0, (global_upper_bound - kth_score) / max(global_upper_bound, 1.0))
            if optimality_gap <= gap_threshold:
                stop_reason = "optimality_gap"
                break
        branch = branches.pop(0)
        if not branch.candidates:
            continue
        candidate = branch.candidates.pop(0)
        evaluated_count += 1
        top_candidates = _push_top_candidate(top_candidates, candidate, limit)
        if branch.candidates:
            branch.upper_bound = max(item.upper_bound for item in branch.candidates)
            branches.append(branch)
    if evaluated_count >= max_evaluations and branches:
        stop_reason = "max_evaluations"
    elif not branches and stop_reason != "optimality_gap":
        stop_reason = "exhausted"
    top_candidates.sort(key=lambda item: (item.numeric_score, item.score_tuple), reverse=True)
    skipped_count = max(0, total_candidates - evaluated_count)
    return {"articles": [candidate.article for candidate in top_candidates[:limit]], "bnb_meta": {"mode": "bnb", "enabled": True, "dataset": dataset_name, "total_candidates": total_candidates, "branch_count": branch_count, "evaluated_count": evaluated_count, "skipped_count": skipped_count, "max_evaluations": max_evaluations, "gap_threshold": gap_threshold, "stop_reason": stop_reason, "optimality_gap": None if optimality_gap is None else round(optimality_gap, 4)}}


def recommend_articles_bnb(article, analysis, limit=3):
    curated_candidates = _collect_candidates(article=article, analysis=analysis, dataset_name="curated")
    curated_result = _select_bnb(candidates=curated_candidates, dataset_name="curated", limit=limit)
    if curated_result["articles"]:
        return {"tier": "curated", "heading": "다른 관점 기사", "caption": "같은 이슈를 다른 강조점이나 다른 중심 주체로 읽게 하는 기사를 B&B 탐색으로 먼저 골랐습니다.", "notice": _dataset_notice("curated"), "articles": curated_result["articles"], "recommendation_mode": "bnb", "bnb_meta": curated_result["bnb_meta"]}
    expanded_candidates = _collect_candidates(article=article, analysis=analysis, dataset_name="expanded")
    expanded_result = _select_bnb(candidates=expanded_candidates, dataset_name="expanded", limit=limit)
    if expanded_result["articles"]:
        return {"tier": "expanded", "heading": "관련 관점 기사", "caption": "입력 기사와 비슷한 쟁점을 다른 강조점이나 다른 인용 중심으로 다루는 기사를 B&B 탐색으로 골랐습니다.", "notice": _dataset_notice("expanded") or _dataset_notice("curated"), "articles": expanded_result["articles"], "recommendation_mode": "bnb", "bnb_meta": expanded_result["bnb_meta"]}
    curated_meta = curated_result.get("bnb_meta", {})
    expanded_meta = expanded_result.get("bnb_meta", {})
    return {"tier": "none", "heading": "", "caption": "", "notice": _dataset_notice("curated") or _dataset_notice("expanded"), "articles": [], "recommendation_mode": "bnb", "bnb_meta": {"mode": "bnb", "enabled": True, "dataset": "curated+expanded", "total_candidates": int(curated_meta.get("total_candidates", 0)) + int(expanded_meta.get("total_candidates", 0)), "branch_count": int(curated_meta.get("branch_count", 0)) + int(expanded_meta.get("branch_count", 0)), "evaluated_count": int(curated_meta.get("evaluated_count", 0)) + int(expanded_meta.get("evaluated_count", 0)), "skipped_count": int(curated_meta.get("skipped_count", 0)) + int(expanded_meta.get("skipped_count", 0)), "stop_reason": "no_local_recommendation", "optimality_gap": None}}
