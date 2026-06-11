"""LLM-based article analysis with a safe mock fallback."""

from __future__ import annotations

import json
import os
import re
from typing import Any

from dotenv import load_dotenv

from prompts import (
    DATASET_TAGGING_SYSTEM_PROMPT,
    EXTERNAL_GUIDANCE_SYSTEM_PROMPT,
    PERSPECTIVE_VECTOR_KEYS,
    READING_ROLE_CANDIDATES,
    SYSTEM_PROMPT,
    get_analysis_prompt,
    get_dataset_tagging_prompt,
    get_external_candidate_prompt,
)


DEFAULT_ANALYSIS = {
    "summary": "기사 핵심 내용을 요약한 문장입니다.",
    "frame": "갈등_구도",
    "tone": "중립적",
    "primary_voice": "정부",
    "issue_tags": ["정책", "사회"],
    "framing_analysis": "이 기사는 사건을 어떤 갈등 구도로 제시하는지 살펴볼 수 있습니다.",
    "language_analysis": "평가적 표현이나 감정적 단어가 사용되었는지 점검할 수 있습니다.",
    "citation_analysis": "어떤 출처가 상대적으로 더 많이 인용되었는지 확인합니다.",
    "title_body_gap": "제목과 본문의 강조점이 얼마나 비슷한지 비교합니다.",
    "missing_perspective": "이 기사만 읽으면 놓칠 수 있는 이해관계자나 맥락을 설명합니다.",
    "reading_focus": "기사 초반에 무엇이 핵심 문제로 제시되는지, 그리고 어떤 주체의 말이 가장 길게 실리는지 먼저 살펴보세요.",
    "reading_highlights": [],
    "analysis_notice": "",
    "bias_axis": 0.0,
    "bias_strength": 0.0,
    "emotionality": 0.0,
    "source_balance": 50.0,
    "evidence_quality": 50.0,
    "content_bias": {
        "favored_side": "",
        "disfavored_side": "",
        "axis": 0.0,
        "strength": 0.0,
        "reasoning": "",
    },
    "background_bias": {
        "favored_side": "",
        "disfavored_side": "",
        "axis": 0.0,
        "strength": 0.0,
        "reasoning": "",
    },
    "perspective_vector": {key: 0.0 for key in PERSPECTIVE_VECTOR_KEYS},
}

DEFAULT_EXTERNAL_GUIDANCE_NOTE = (
    "현재 DB에는 직접 대응되는 비교 기사가 없어, 같은 이슈를 다룰 가능성이 있는 외부 기사 후보를 함께 제시합니다. "
    "아래 기사들은 확정된 반대 프레임 추천이 아니라 추가로 비교해볼 만한 읽기 후보입니다."
)
SUPPORTED_LLM_KEY_TEXT = (
    "GOOGLE_API_KEY 또는 GEMINI_API_KEY, OPENAI_API_KEY, OPENROUTER_API_KEY 또는 ANTHROPIC_API_KEY"
)
DEFAULT_DATASET_TAG = {
    "sub_issue": "세부 쟁점 미분류",
    "issue_tags": ["정책", "사회", "이슈"],
    "frame": "갈등_구도",
    "tone": "중립적",
    "primary_voice": "정부",
    "memo": "기사에서 관찰 가능한 강조점과 인용 주체를 바탕으로 분류한 mock 태깅 결과입니다.",
}
OPENROUTER_BASE_URL = "https://openrouter.ai/api/v1"
LLM_TIMEOUT_SECONDS = int(os.getenv("LLM_TIMEOUT_SECONDS", "45"))
TITLE_TAG_STOPWORDS = {
    "기사",
    "뉴스",
    "오늘",
    "내일",
    "이번",
    "관련",
    "예정",
    "발표",
    "발표한다",
    "회의",
    "논의",
    "방문",
    "추진",
    "예고",
    "정부",
}


class NoConfiguredProviderError(RuntimeError):
    """Raised when no supported LLM provider key is configured."""


class LLMProviderFailure(RuntimeError):
    """Raised when all configured LLM providers fail in sequence."""


def _strip_code_fences(text: str) -> str:
    """Remove common markdown wrappers before JSON parsing."""
    cleaned = text.strip()
    fenced_match = re.search(r"```(?:json)?\s*(\{.*\})\s*```", cleaned, re.DOTALL)
    if fenced_match:
        return fenced_match.group(1).strip()

    start = cleaned.find("{")
    end = cleaned.rfind("}")
    if start != -1 and end != -1 and end > start:
        return cleaned[start : end + 1]
    return cleaned


def _normalize_tag_list(value: Any, limit: int) -> list[str]:
    """Normalize a tag-like field into a short list."""
    if isinstance(value, str):
        candidates = [item.strip() for item in re.split(r"[,/;]", value) if item.strip()]
        return candidates[:limit]

    if isinstance(value, list):
        tags = [str(item).strip() for item in value if str(item).strip()]
        return tags[:limit]

    return []


def _normalize_issue_tags(value: Any) -> list[str]:
    """Keep issue tags in a small, predictable list form."""
    normalized = _normalize_tag_list(value, 3)
    if normalized:
        return normalized

    return DEFAULT_ANALYSIS["issue_tags"][:]


def _clamp_float(value: Any, minimum: float, maximum: float, default: float) -> float:
    """Safely normalize numeric diagnostics into a bounded float."""
    try:
        number = float(value)
    except (TypeError, ValueError):
        return default
    return max(minimum, min(maximum, number))


def _normalize_reading_highlights(value: Any) -> list[dict[str, str]]:
    """Normalize LLM-provided reading highlights into a short list of sentence notes."""
    if not isinstance(value, list):
        return []

    normalized: list[dict[str, str]] = []
    for item in value[:5]:
        if not isinstance(item, dict):
            continue

        sentence = str(item.get("sentence", "")).strip()
        role = str(item.get("role", "")).strip()
        note = str(item.get("note", "")).strip()
        if not sentence or not note:
            continue
        if role not in READING_ROLE_CANDIDATES:
            role = "핵심 서술"

        normalized.append(
            {
                "sentence": sentence,
                "role": role,
                "note": note,
            }
        )

    return normalized


def _normalize_bias_block(value: Any) -> dict[str, Any]:
    """Normalize content/background bias blocks into a stable shape."""
    if not isinstance(value, dict):
        value = {}

    default_block = DEFAULT_ANALYSIS["content_bias"]
    return {
        "favored_side": str(value.get("favored_side", "")).strip(),
        "disfavored_side": str(value.get("disfavored_side", "")).strip(),
        "axis": _clamp_float(value.get("axis"), -100.0, 100.0, float(default_block["axis"])),
        "strength": _clamp_float(value.get("strength"), 0.0, 100.0, float(default_block["strength"])),
        "reasoning": str(value.get("reasoning", "")).strip(),
    }


def _normalize_perspective_vector(value: Any) -> dict[str, float]:
    """Normalize multi-axis perspective scores."""
    raw_vector = value if isinstance(value, dict) else {}
    return {
        key: _clamp_float(raw_vector.get(key), 0.0, 100.0, 0.0)
        for key in PERSPECTIVE_VECTOR_KEYS
    }


def _normalize_analysis(payload: dict[str, Any]) -> dict[str, Any]:
    """Merge partial or slightly malformed LLM output into the expected schema."""
    normalized = DEFAULT_ANALYSIS.copy()
    for key in DEFAULT_ANALYSIS:
        if key not in payload:
            continue

        if key == "issue_tags":
            normalized[key] = _normalize_issue_tags(payload[key])
        elif key == "reading_highlights":
            normalized[key] = _normalize_reading_highlights(payload[key])
        elif key in {"bias_axis"}:
            normalized[key] = _clamp_float(payload[key], -100.0, 100.0, float(DEFAULT_ANALYSIS[key]))
        elif key in {"bias_strength", "emotionality", "source_balance", "evidence_quality"}:
            normalized[key] = _clamp_float(payload[key], 0.0, 100.0, float(DEFAULT_ANALYSIS[key]))
        elif key in {"content_bias", "background_bias"}:
            normalized[key] = _normalize_bias_block(payload[key])
        elif key == "perspective_vector":
            normalized[key] = _normalize_perspective_vector(payload[key])
        else:
            value = payload[key]
            normalized[key] = str(value).strip() if value not in (None, "") else DEFAULT_ANALYSIS[key]

    return normalized


def _calibrate_supplemental_diagnostics(analysis: dict[str, Any], article: dict) -> dict[str, Any]:
    """Lightly strengthen supplementary diagnostics when the raw model output is too thin."""
    title = str(article.get("title", "")).strip()
    body = str(article.get("body", "")).strip()
    text = f"{title} {body}"
    if not text.strip():
        return analysis

    labor_hits = sum(1 for keyword in ("노조", "노동자", "근로자", "파업", "임금", "단체교섭", "노동권") if keyword in text)
    business_hits = sum(1 for keyword in ("기업", "경영", "사측", "경영계", "비용", "부담", "생산 차질") if keyword in text)
    government_hits = sum(1 for keyword in ("정부", "대통령", "장관", "부처", "정책", "제도", "규제") if keyword in text)
    welfare_hits = sum(1 for keyword in ("지원", "복지", "보호", "공공성", "구제", "안전망") if keyword in text)
    market_hits = sum(1 for keyword in ("시장", "투자", "성장", "수익", "경쟁력", "수출") if keyword in text)
    risk_hits = sum(1 for keyword in ("우려", "논란", "갈등", "피해", "충돌", "위기", "부담") if keyword in text)
    benefit_hits = sum(1 for keyword in ("개선", "확대", "회복", "보호", "강화", "성과") if keyword in text)

    vector = dict(analysis.get("perspective_vector", {}) or {})
    vector["pro_labor"] = max(vector.get("pro_labor", 0.0), min(100.0, labor_hits * 18.0))
    vector["pro_business"] = max(vector.get("pro_business", 0.0), min(100.0, business_hits * 18.0))
    vector["pro_government"] = max(vector.get("pro_government", 0.0), min(100.0, government_hits * 15.0))
    vector["pro_welfare"] = max(vector.get("pro_welfare", 0.0), min(100.0, welfare_hits * 18.0))
    vector["pro_market"] = max(vector.get("pro_market", 0.0), min(100.0, market_hits * 16.0))
    vector["pro_regulation"] = max(vector.get("pro_regulation", 0.0), min(100.0, (government_hits + welfare_hits) * 10.0))
    vector["anti_regulation"] = max(vector.get("anti_regulation", 0.0), min(100.0, market_hits * 10.0))
    vector["risk_emphasis"] = max(vector.get("risk_emphasis", 0.0), min(100.0, risk_hits * 14.0))
    vector["benefit_emphasis"] = max(vector.get("benefit_emphasis", 0.0), min(100.0, benefit_hits * 14.0))
    analysis["perspective_vector"] = _normalize_perspective_vector(vector)

    if analysis.get("emotionality", 0.0) < 15.0 and risk_hits:
        analysis["emotionality"] = min(100.0, 20.0 + risk_hits * 8.0)
    if analysis.get("evidence_quality", 50.0) < 50.0 and any(word in text for word in ("통계", "자료", "조사", "발표", "%", "명", "건", "개")):
        analysis["evidence_quality"] = 58.0

    if not analysis.get("content_bias", {}).get("favored_side"):
        if labor_hits > business_hits + 1:
            analysis["content_bias"] = {
                "favored_side": "노동·권리 보호 논리",
                "disfavored_side": "기업·비용 부담 논리",
                "axis": 32.0,
                "strength": max(analysis.get("bias_strength", 0.0), 36.0),
                "reasoning": "기사 내용에서 노동·권리 보호 쪽 어휘와 이해관계자 비중이 상대적으로 더 크게 드러납니다.",
            }
        elif business_hits > labor_hits + 1:
            analysis["content_bias"] = {
                "favored_side": "기업·비용 부담 논리",
                "disfavored_side": "노동·권리 보호 논리",
                "axis": -32.0,
                "strength": max(analysis.get("bias_strength", 0.0), 36.0),
                "reasoning": "기사 내용에서 비용 부담, 경영, 생산 차질 같은 논리가 상대적으로 더 앞에 놓입니다.",
            }

    if not analysis.get("background_bias", {}).get("favored_side"):
        if government_hits and any(word in text for word in ("개정", "발표", "도입", "추진")):
            analysis["background_bias"] = {
                "favored_side": "정책 추진 주체",
                "disfavored_side": "정책 외 이해관계자",
                "axis": 14.0 if welfare_hits >= market_hits else -8.0,
                "strength": 24.0,
                "reasoning": "이 기사는 정책 발표나 제도 변화 자체를 중심 사건으로 삼아 정책 주체의 문제 설정을 먼저 읽게 만듭니다.",
            }

    return _normalize_analysis(analysis)


def _normalize_dataset_tag(payload: dict[str, Any]) -> dict[str, Any]:
    """Normalize LLM dataset-tagging output into the expected schema."""
    normalized = DEFAULT_DATASET_TAG.copy()
    for key in DEFAULT_DATASET_TAG:
        if key not in payload:
            continue

        if key == "issue_tags":
            tags = _normalize_tag_list(payload[key], 5)
            normalized[key] = tags if tags else DEFAULT_DATASET_TAG["issue_tags"][:]
        elif key == "tone":
            tone = str(payload[key]).strip()
            normalized[key] = tone if tone in {"긍정적", "부정적", "중립적", "혼합"} else DEFAULT_DATASET_TAG["tone"]
        else:
            value = payload[key]
            normalized[key] = str(value).strip() if value not in (None, "") else DEFAULT_DATASET_TAG[key]

    return normalized


def _contains_any(text: str, keywords: tuple[str, ...]) -> bool:
    """Return whether any of the given keywords appears in the text."""
    return any(keyword in text for keyword in keywords)


def _fallback_title_tags(title: str) -> list[str]:
    """Extract a few search-friendly tags from the article title when LLM output is unavailable."""
    tokens = re.findall(r"[A-Za-z0-9가-힣]+", title or "")
    tags: list[str] = []
    seen: set[str] = set()
    for token in tokens:
        cleaned = token.strip()
        if not cleaned:
            continue
        lowered = cleaned.lower()
        if lowered in TITLE_TAG_STOPWORDS:
            continue
        if len(cleaned) < 2 and cleaned.upper() not in {"AI", "SK", "LG"}:
            continue
        if cleaned.endswith(("한다", "했다", "된다", "예정", "방문")):
            continue
        if lowered in seen:
            continue
        seen.add(lowered)
        tags.append(cleaned)
        if len(tags) >= 3:
            break
    return tags


def _infer_mock_profile(article: dict) -> dict[str, Any]:
    """Infer safer fallback labels so mock analysis still feels article-aware."""
    title = str(article.get("title", "")).strip()
    body = str(article.get("body", "")).strip()
    text = f"{title} {body}"

    labor_hits = sum(1 for keyword in ("노조", "노동자", "근로자", "파업", "임금", "노동권", "한국노총", "민주노총") if keyword in text)
    business_hits = sum(1 for keyword in ("기업", "경영", "회장", "ceo", "대표이사", "투자", "협력", "공급망", "산업", "반도체", "엔비디아", "sk하이닉스", "삼성전자") if keyword.lower() in text.lower())
    platform_hits = sum(1 for keyword in ("배달앱", "플랫폼", "수수료", "상생안", "중개수수료") if keyword in text)
    retail_hits = sum(1 for keyword in ("대형마트", "새벽배송", "유통산업발전법", "골목상권", "의무휴업") if keyword in text)
    election_hits = sum(1 for keyword in ("선관위", "투표용지", "지방선거", "개표", "재선거", "선거무효", "참정권") if keyword in text)
    medical_hits = sum(1 for keyword in ("의료개혁", "의대", "전공의", "의협", "의사", "환자", "지역의료") if keyword in text)
    housing_hits = sum(1 for keyword in ("전세사기", "보증금", "피해자", "특별법", "주거안정") if keyword in text)
    support_hits = sum(1 for keyword in ("민생지원금", "소비쿠폰", "추경", "지원금", "소비진작") if keyword in text)

    title_tags = _fallback_title_tags(title)
    profile = {
        "frame": DEFAULT_ANALYSIS["frame"],
        "tone": "설명적",
        "primary_voice": DEFAULT_ANALYSIS["primary_voice"],
        "issue_tags": title_tags or DEFAULT_ANALYSIS["issue_tags"][:],
        "framing_analysis": DEFAULT_ANALYSIS["framing_analysis"],
        "language_analysis": DEFAULT_ANALYSIS["language_analysis"],
        "citation_analysis": DEFAULT_ANALYSIS["citation_analysis"],
        "title_body_gap": DEFAULT_ANALYSIS["title_body_gap"],
        "missing_perspective": DEFAULT_ANALYSIS["missing_perspective"],
        "reading_focus": DEFAULT_ANALYSIS["reading_focus"],
    }

    if business_hits >= 2 and _contains_any(text.lower(), ("엔비디아", "ai", "반도체", "hbm")):
        profile.update(
            {
                "frame": "기업성과_강조",
                "tone": "설명적",
                "primary_voice": "엔비디아 및 국내 대기업 경영진",
                "issue_tags": ["AI", "반도체", "엔비디아"],
                "framing_analysis": "이 기사는 글로벌 AI 산업 협력과 반도체 공급망 전략을 중심 쟁점으로 앞세웁니다. 기업 간 만남과 협력 일정이 사건의 핵심 의미처럼 배치됩니다.",
                "language_analysis": "회동 일정, 차세대 제품, 협력 청사진 같은 표현이 기술 협력의 기대감과 산업적 중요성을 키웁니다. 갈등보다는 산업 성과와 기업 동선을 정리하는 설명적 어조가 강합니다.",
                "citation_analysis": "기업 경영진과 업계 일정이 사실 판단의 중심 근거로 배치됩니다. 시장 평가나 경쟁 리스크를 설명하는 외부 시각은 상대적으로 약합니다.",
                "title_body_gap": "제목은 SK와의 협력에 집중하지만, 본문은 삼성·LG·현대차·네이버까지 포함한 더 넓은 산업 협력 구도로 확장됩니다.",
                "missing_perspective": "이 협력이 시장 경쟁, 기술 의존도, 중소 생태계에 어떤 영향을 주는지는 충분히 다뤄지지 않습니다. 공급망 리스크나 산업 경쟁 구도를 중심으로 읽는 다른 기사와 비교해 보면 도움이 됩니다.",
                "reading_focus": "누가 협력의 핵심 주체로 반복 등장하는지, 일정 소개를 넘어 실제 기술·시장 근거가 얼마나 구체적으로 제시되는지 확인해 보세요.",
            }
        )
        return profile

    if labor_hits and business_hits:
        if labor_hits > business_hits:
            frame = "노동권_보호"
            voice = "노동계"
            missing = "경영계의 비용 부담 근거나 고용 영향 데이터는 얼마나 구체적으로 제시되는지 비교해 보는 것이 좋습니다."
        elif business_hits > labor_hits:
            frame = "기업부담_우려"
            voice = "기업 및 경영계"
            missing = "노동자 처우와 권리 보장 논리가 얼마나 직접적으로 제시되는지 비교할 필요가 있습니다."
        else:
            frame = "노사갈등_구도"
            voice = "노동계와 경영계"
            missing = "노사 양측 외에 현장 노동자, 소상공인, 소비자 등 제3의 이해관계자 관점이 얼마나 비어 있는지 함께 확인해 보세요."

        profile.update(
            {
                "frame": frame,
                "tone": "갈등적",
                "primary_voice": voice,
                "issue_tags": ["노동", "임금", "노사"] if not title_tags else title_tags,
                "framing_analysis": "이 기사는 같은 사안을 노사 간 이해 충돌의 문제로 읽게 만듭니다. 어느 쪽 논리를 더 길게 싣는지가 독자의 초기 판단에 큰 영향을 줍니다.",
                "language_analysis": "권리, 부담, 위기, 생존 같은 표현이 어느 쪽에 더 강하게 붙는지에 따라 감정 온도가 달라집니다. 제목과 초반 문단에서 갈등 압력이 먼저 세워지는지 보는 것이 중요합니다.",
                "citation_analysis": "노동계와 경영계 중 누구의 발언이 직접 인용으로 더 길게 제시되는지 확인하는 것이 핵심입니다. 한쪽이 존재만 언급되고 구체 근거가 없으면 체감 균형이 달라질 수 있습니다.",
                "missing_perspective": missing,
                "reading_focus": "직접 인용의 길이와 근거 밀도를 비교하면서, 같은 사안을 권리 문제로 읽게 하는지 비용 문제로 읽게 하는지 살펴보세요.",
            }
        )
        return profile

    if platform_hits:
        profile.update(
            {
                "frame": "플랫폼_입장" if "플랫폼" in text and "상생" not in text else "상생_강조",
                "tone": "설명적",
                "primary_voice": "플랫폼 업계 및 소상공인",
                "issue_tags": ["배달앱", "수수료", "플랫폼"] if not title_tags else title_tags,
                "framing_analysis": "이 기사는 플랫폼 수수료와 상생 논의를 중심 문제로 배치합니다. 비용 구조와 규제 필요성이 어떤 순서로 등장하는지에 따라 읽는 방향이 달라집니다.",
                "citation_analysis": "플랫폼 업계와 점주·소상공인 중 누가 더 구체적으로 발언하는지 확인하는 것이 중요합니다.",
                "missing_perspective": "소비자 비용 변화나 규제 이후의 시장 구조 변화가 빠져 있다면, 그 부분을 다루는 비교 기사가 필요합니다.",
                "reading_focus": "플랫폼의 설명이 중심인지, 현장 점주의 부담이 중심인지 먼저 확인해 보세요.",
            }
        )
        return profile

    if retail_hits:
        profile.update(
            {
                "frame": "골목상권_보호" if "골목상권" in text else "소비자_편의",
                "tone": "설명적",
                "primary_voice": "유통업계 및 상권 이해관계자",
                "issue_tags": ["대형마트", "새벽배송", "유통규제"] if not title_tags else title_tags,
                "framing_analysis": "이 기사는 유통 규제의 편익과 부담 중 어느 쪽을 더 앞세우는지에 따라 읽히는 방향이 달라집니다.",
                "citation_analysis": "대형 유통업체, 소비자, 골목상권 중 누구의 목소리가 중심 근거가 되는지 확인해 볼 필요가 있습니다.",
                "missing_perspective": "규제 완화의 소비자 편익과 골목상권 보호 논리가 동시에 충분히 다뤄지는지 비교 기사를 통해 확인해 보세요.",
                "reading_focus": "편의와 보호 중 어느 단어가 더 반복되는지, 누구의 손익이 중심 근거로 놓이는지 살펴보세요.",
            }
        )
        return profile

    if election_hits:
        profile.update(
            {
                "frame": "국가책임" if _contains_any(text, ("사과", "책임", "무효", "재선거")) else "제도개선",
                "tone": "우려 중심",
                "primary_voice": "선관위 및 정치권",
                "issue_tags": ["지방선거", "선관위", "투표용지"] if not title_tags else title_tags,
                "framing_analysis": "이 기사는 선거 관리 실패 또는 제도 보완 필요성을 핵심 쟁점으로 밀어 올립니다. 책임 소재와 재발 방지 중 무엇이 더 크게 다뤄지는지에 따라 프레임이 달라집니다.",
                "citation_analysis": "선관위 설명, 정치권 비판, 유권자 피해 호소 중 어느 목소리가 중심 근거가 되는지 확인해 볼 필요가 있습니다.",
                "missing_perspective": "실제 투표권 침해 경험이나 구체적 제도 개선안이 충분히 다뤄지는지 비교 기사를 통해 보완하면 좋습니다.",
                "reading_focus": "책임 추궁과 제도 개선 논리 중 무엇이 기사 초반에 더 크게 놓이는지 먼저 확인해 보세요.",
            }
        )
        return profile

    if medical_hits:
        primary_voice = "의료계" if _contains_any(text, ("의협", "전공의", "의사")) else "정부"
        frame = "환자_피해" if "환자" in text else ("지역의료_확충" if "지역의료" in text else "의료계_반발")
        profile.update(
            {
                "frame": frame,
                "tone": "갈등적",
                "primary_voice": primary_voice,
                "issue_tags": ["의료개혁", "전공의", "의대정원"] if not title_tags else title_tags,
                "framing_analysis": "이 기사는 의료개혁을 두고 정책 정당성, 의료계 반발, 환자 영향 중 무엇을 더 크게 앞세우는지 보여줍니다.",
                "citation_analysis": "정부 설명과 의료계 발언이 어떤 비중으로 제시되는지, 환자나 지역 의료 현장 관점은 얼마나 살아 있는지 확인해 보세요.",
                "missing_perspective": "환자 영향, 지역 의료 공백, 정책 시행 근거 데이터 중 무엇이 빠져 있는지 비교 기사를 통해 확인할 필요가 있습니다.",
                "reading_focus": "같은 사건을 정책 추진 문제로 읽게 하는지, 환자 피해나 의료계 반발 문제로 읽게 하는지 먼저 구분해 보세요.",
            }
        )
        return profile

    if housing_hits:
        profile.update(
            {
                "frame": "피해자_보호",
                "tone": "우려 중심",
                "primary_voice": "피해자 및 정부",
                "issue_tags": ["전세사기", "피해자", "특별법"] if not title_tags else title_tags,
                "framing_analysis": "이 기사는 피해자 구제와 주거 불안 문제를 앞세워 사건을 읽게 만듭니다.",
                "citation_analysis": "피해자 호소와 정부 대책 중 어느 쪽이 더 길게 설명되는지에 따라 독자의 체감이 달라질 수 있습니다.",
                "missing_perspective": "실제 구제 집행 속도, 사각지대, 금융·법적 후속 과제가 충분히 다뤄지는지 비교 기사를 통해 확인해 보세요.",
                "reading_focus": "피해 사실 묘사와 제도 개선 설명 중 어느 부분에 더 많은 공간이 배정되는지 주목해 보세요.",
            }
        )
        return profile

    if support_hits:
        profile.update(
            {
                "frame": "민생경제_회복",
                "tone": "설명적",
                "primary_voice": "정부 및 재정 정책 주체",
                "issue_tags": ["민생지원금", "추경", "소비쿠폰"] if not title_tags else title_tags,
                "framing_analysis": "이 기사는 지원 정책의 경기 부양 효과를 핵심 문제로 앞세웁니다. 동시에 재정 부담 논리가 얼마나 함께 설명되는지에 따라 해석이 달라집니다.",
                "citation_analysis": "정부의 정책 설명이 중심인지, 재정 우려나 현장 체감 의견이 함께 제시되는지 살펴볼 필요가 있습니다.",
                "missing_perspective": "재정 건전성, 정책 효과의 지속성, 실제 체감 소비 변화가 충분히 설명되는지 비교 기사를 통해 보완하면 좋습니다.",
                "reading_focus": "지원의 효과와 비용 중 어느 쪽이 기사 앞부분에서 먼저 부각되는지 확인해 보세요.",
            }
        )
        return profile

    if title_tags:
        profile["issue_tags"] = title_tags
    return profile


def _build_mock_analysis(article: dict, notice: str) -> dict[str, Any]:
    """Create a readable fallback so the app still runs without API keys."""
    title = article.get("title", "입력 기사")
    source = article.get("source", "해당 기사")
    body = article.get("body", "")
    excerpt = body[:160].strip()
    sentences = [part.strip() for part in re.split(r"(?<=[.!?])\s+|(?<=다\.)\s+|(?<=요\.)\s+", body) if part.strip()]
    profile = _infer_mock_profile(article)

    reading_highlights: list[dict[str, str]] = []
    if sentences:
        reading_highlights.append(
            {
                "sentence": sentences[0],
                "role": "핵심 서술",
                "note": "기사 초반에 놓인 문장이라 독자가 사건을 처음 어떤 구도로 받아들이는지 보여주는 기준점입니다.",
            }
        )
    metric_match = re.search(r"\d[\d,]*(?:\.\d+)?\s*(?:%|명|곳|건|개|억|조|원)", body)
    if metric_match and sentences:
        for sentence in sentences[1:4]:
            if metric_match.group(0) in sentence:
                reading_highlights.append(
                    {
                        "sentence": sentence,
                        "role": "근거 제시",
                        "note": "수치가 들어간 문장이라 기사 주장에 어떤 근거가 붙는지 확인하기 좋은 지점입니다.",
                    }
                )
                break

    mock_result = DEFAULT_ANALYSIS.copy()
    mock_result.update(
        {
            "summary": (
                f"'{title}' 기사에서 다루는 핵심 내용을 바탕으로 요약한 개발용 결과입니다. "
                f"{excerpt}..."
                if excerpt
                else f"'{title}' 기사에 대한 개발용 요약 결과입니다."
            ),
            "frame": profile["frame"],
            "tone": profile["tone"],
            "primary_voice": profile["primary_voice"],
            "issue_tags": profile["issue_tags"],
            "framing_analysis": profile["framing_analysis"],
            "language_analysis": profile["language_analysis"],
            "citation_analysis": profile["citation_analysis"],
            "title_body_gap": profile["title_body_gap"],
            "missing_perspective": profile["missing_perspective"],
            "reading_focus": profile["reading_focus"],
            "reading_highlights": reading_highlights,
            "bias_axis": 0.0,
            "bias_strength": 24.0,
            "emotionality": 18.0,
            "source_balance": 48.0,
            "evidence_quality": 42.0,
            "content_bias": {
                "favored_side": "",
                "disfavored_side": "",
                "axis": 0.0,
                "strength": 24.0,
                "reasoning": "실제 LLM 연결 없이 생성된 예시 결과이므로, 편향 진단 값은 참고용 기본치입니다.",
            },
            "background_bias": {
                "favored_side": "",
                "disfavored_side": "",
                "axis": 0.0,
                "strength": 18.0,
                "reasoning": "실제 LLM 연결 없이 생성된 예시 결과이므로, 배경 편향 진단 값은 참고용 기본치입니다.",
            },
            "perspective_vector": {key: 0.0 for key in PERSPECTIVE_VECTOR_KEYS},
            "analysis_notice": notice,
        }
    )
    return _calibrate_supplemental_diagnostics(mock_result, article)


def _build_mock_dataset_tag(article: dict, issue: str, notice: str) -> dict[str, Any]:
    """Create a mock dataset tag so data-building scripts still run without API keys."""
    title = article.get("title", "입력 기사")
    source = article.get("source", "해당 기사")
    profile = _infer_mock_profile(article)
    issue_terms = [issue] if issue else []
    if article.get("source"):
        issue_terms.append(str(article["source"]).strip())

    mock_tag = DEFAULT_DATASET_TAG.copy()
    mock_tag.update(
        {
            "sub_issue": f"{issue} 관련 세부 쟁점" if issue else DEFAULT_DATASET_TAG["sub_issue"],
            "issue_tags": (issue_terms[:1] + profile["issue_tags"])[:3],
            "frame": profile["frame"],
            "tone": "중립적" if profile["tone"] not in {"긍정적", "부정적", "중립적", "혼합"} else profile["tone"],
            "primary_voice": profile["primary_voice"],
            "memo": f"'{title}' 기사에서 {source}가 '{profile['frame']}' 프레임으로 어떤 주체를 전면에 두는지 기준으로 생성한 mock 태깅 결과입니다.",
            "tagging_notice": notice,
        }
    )
    return mock_tag


def _parse_json_response(raw_text: str) -> dict[str, Any]:
    """Parse a model response into JSON, raising a helpful error if it fails."""
    try:
        cleaned = _strip_code_fences(raw_text)
        start = cleaned.find("{")
        if start == -1:
            raise json.JSONDecodeError("No JSON object found", cleaned, 0)

        decoder = json.JSONDecoder()
        payload, _ = decoder.raw_decode(cleaned[start:])
    except json.JSONDecodeError as exc:
        raise ValueError("LLM 응답을 JSON으로 해석하지 못했습니다.") from exc

    if not isinstance(payload, dict):
        raise ValueError("LLM 응답 JSON이 객체 형태가 아닙니다.")
    return payload


def _get_openai_client_kwargs() -> dict[str, str]:
    """Build client options for either OpenAI or OpenRouter."""
    openrouter_api_key = os.getenv("OPENROUTER_API_KEY")
    if openrouter_api_key:
        return {
            "api_key": openrouter_api_key,
            "base_url": OPENROUTER_BASE_URL,
        }

    return {"api_key": os.getenv("OPENAI_API_KEY", "")}


def _get_openai_model_name() -> str:
    """Choose the model name for OpenAI-compatible providers."""
    if os.getenv("OPENROUTER_API_KEY"):
        return os.getenv("OPENROUTER_MODEL", "openai/gpt-4o-mini")
    return os.getenv("OPENAI_MODEL", "gpt-4o-mini")


def _get_google_api_key() -> str:
    """Return the configured Gemini API key, supporting both common env names."""
    return os.getenv("GOOGLE_API_KEY", "") or os.getenv("GEMINI_API_KEY", "")


def _get_google_model_name() -> str:
    """Choose the Gemini model name for Google AI Studio keys."""
    return (
        os.getenv("GOOGLE_MODEL", "")
        or os.getenv("GEMINI_MODEL", "")
        or "models/gemini-flash-lite-latest"
    )


def _get_openai_extra_headers() -> dict[str, str] | None:
    """Add optional OpenRouter headers when using OpenRouter."""
    if not os.getenv("OPENROUTER_API_KEY"):
        return None

    headers = {"X-Title": "NewSight"}
    referer = os.getenv("OPENROUTER_HTTP_REFERER")
    if referer:
        headers["HTTP-Referer"] = referer
    return headers


def _call_openai_prompt(system_prompt: str, user_prompt: str) -> str:
    """Call the OpenAI Chat Completions API with arbitrary prompts."""
    from openai import OpenAI

    client = OpenAI(**_get_openai_client_kwargs())
    response = client.chat.completions.create(
        model=_get_openai_model_name(),
        temperature=0.2,
        messages=[
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_prompt},
        ],
        extra_headers=_get_openai_extra_headers(),
        timeout=LLM_TIMEOUT_SECONDS,
    )
    return response.choices[0].message.content or ""


def _extract_google_response_text(response: Any) -> str:
    """Extract text content from a Google GenAI response object."""
    text = getattr(response, "text", None)
    if text:
        return text

    parts: list[str] = []
    for candidate in getattr(response, "candidates", []) or []:
        content = getattr(candidate, "content", None)
        if content is None:
            continue
        for part in getattr(content, "parts", []) or []:
            part_text = getattr(part, "text", None)
            if part_text:
                parts.append(part_text)

    if parts:
        return "\n".join(parts)
    raise ValueError("Gemini 응답에서 텍스트를 추출하지 못했습니다.")


def _call_google_prompt(system_prompt: str, user_prompt: str, max_tokens: int = 1200) -> str:
    """Call the Gemini API using a Google AI Studio key."""
    from google import genai
    from google.genai import types

    client = genai.Client(
        api_key=_get_google_api_key(),
        http_options=types.HttpOptions(timeout=LLM_TIMEOUT_SECONDS * 1000),
    )
    response = client.models.generate_content(
        model=_get_google_model_name(),
        contents=user_prompt,
        config=types.GenerateContentConfig(
            system_instruction=system_prompt,
            temperature=0.2,
            max_output_tokens=max_tokens,
            response_mime_type="application/json",
        ),
    )
    return _extract_google_response_text(response)


def _call_anthropic_prompt(system_prompt: str, user_prompt: str, max_tokens: int = 1200) -> str:
    """Call the Anthropic Messages API with arbitrary prompts."""
    from anthropic import Anthropic

    client = Anthropic(api_key=os.getenv("ANTHROPIC_API_KEY"), timeout=LLM_TIMEOUT_SECONDS)
    response = client.messages.create(
        model=os.getenv("ANTHROPIC_MODEL", "claude-3-5-sonnet-latest"),
        temperature=0.2,
        max_tokens=max_tokens,
        system=system_prompt,
        messages=[{"role": "user", "content": user_prompt}],
    )

    text_blocks = [block.text for block in response.content if getattr(block, "type", "") == "text"]
    return "\n".join(text_blocks)


def _summarize_provider_error(exc: Exception) -> str:
    """Compress provider errors into one readable line for fallback notices."""
    message = str(exc).strip() or exc.__class__.__name__
    message = re.sub(r"\s+", " ", message)
    if len(message) > 220:
        message = f"{message[:217]}..."
    return message


def _provider_attempts(system_prompt: str, user_prompt: str, max_tokens: int) -> list[tuple[str, Any]]:
    """Build provider call attempts in fallback order."""
    attempts: list[tuple[str, Any]] = []

    if _get_google_api_key():
        attempts.append(
            (
                "Gemini",
                lambda: _call_google_prompt(system_prompt, user_prompt, max_tokens=max_tokens),
            )
        )

    if os.getenv("OPENROUTER_API_KEY") or os.getenv("OPENAI_API_KEY"):
        provider_name = "OpenRouter" if os.getenv("OPENROUTER_API_KEY") else "OpenAI"
        attempts.append(
            (
                provider_name,
                lambda: _call_openai_prompt(system_prompt, user_prompt),
            )
        )

    if os.getenv("ANTHROPIC_API_KEY"):
        attempts.append(
            (
                "Anthropic",
                lambda: _call_anthropic_prompt(system_prompt, user_prompt, max_tokens=max_tokens),
            )
        )

    return attempts


def _call_llm_text(system_prompt: str, user_prompt: str, max_tokens: int = 1200) -> str:
    """Dispatch a prompt across configured providers with automatic fallback."""
    attempts = _provider_attempts(system_prompt, user_prompt, max_tokens)
    if not attempts:
        raise NoConfiguredProviderError(f"{SUPPORTED_LLM_KEY_TEXT}가 설정되지 않았습니다.")

    errors: list[str] = []
    for provider_name, call in attempts:
        try:
            return call()
        except Exception as exc:  # noqa: BLE001 - provider fallback should be resilient
            errors.append(f"{provider_name}: {_summarize_provider_error(exc)}")
            continue

    joined = " | ".join(errors) if errors else "원인을 확인하지 못했습니다."
    raise LLMProviderFailure(f"모든 LLM provider 호출이 실패했습니다. {joined}")


def _default_compare_point(analysis: dict[str, Any]) -> str:
    """Create a simple fallback comparison point from the input article analysis."""
    missing_perspective = str(analysis.get("missing_perspective", "")).strip()
    if missing_perspective:
        return missing_perspective
    return "입력 기사에서 덜 다뤄진 이해관계자, 근거, 정책 효과를 함께 비교해보세요."


def _build_mock_external_guidance(
    analysis: dict[str, Any], candidates: list[dict], notice: str
) -> dict[str, Any]:
    """Return readable fallback guidance for external candidates."""
    tags = analysis.get("issue_tags", [])
    tag_text = ", ".join(tags[:2]) if isinstance(tags, list) and tags else "같은 이슈"
    compare_point = _default_compare_point(analysis)

    guidance_candidates = []
    for candidate in candidates:
        title = candidate.get("title", "후보 기사")
        source = candidate.get("source", "외부 기사")
        guidance_candidates.append(
            {
                "title": title,
                "why_relevant": f"'{title}' 기사는 {tag_text}와 관련된 외부 기사 후보로 검색되어 {source}의 시선을 추가로 확인하는 데 도움이 될 수 있습니다.",
                "what_to_compare": compare_point,
            }
        )

    return {
        "overall_note": DEFAULT_EXTERNAL_GUIDANCE_NOTE,
        "candidates": guidance_candidates,
        "explanation_notice": notice,
    }


def _normalize_external_guidance(payload: dict[str, Any], candidates: list[dict]) -> dict[str, Any]:
    """Normalize LLM guidance for external candidate cards."""
    overall_note = str(payload.get("overall_note", "")).strip() or DEFAULT_EXTERNAL_GUIDANCE_NOTE
    raw_candidates = payload.get("candidates", [])
    if not isinstance(raw_candidates, list):
        raw_candidates = []

    normalized_candidates = []
    for index, candidate in enumerate(candidates):
        raw_item = raw_candidates[index] if index < len(raw_candidates) and isinstance(raw_candidates[index], dict) else {}
        normalized_candidates.append(
            {
                "title": candidate.get("title", "후보 기사"),
                "why_relevant": str(raw_item.get("why_relevant", "")).strip()
                or f"'{candidate.get('title', '후보 기사')}' 기사는 입력 기사와 연관된 주제를 다룰 가능성이 있어 비교 후보로 제시되었습니다.",
                "what_to_compare": str(raw_item.get("what_to_compare", "")).strip()
                or "입력 기사에서 덜 다뤄진 이해관계자, 근거, 강조점을 함께 비교해보세요.",
            }
        )

    return {"overall_note": overall_note, "candidates": normalized_candidates}


def llm_provider_available() -> bool:
    """Return whether any supported LLM provider key is configured."""
    load_dotenv()
    return any(
        [
            bool(_get_google_api_key()),
            bool(os.getenv("OPENAI_API_KEY")),
            bool(os.getenv("OPENROUTER_API_KEY")),
            bool(os.getenv("ANTHROPIC_API_KEY")),
        ]
    )


def request_llm_json(system_prompt: str, user_prompt: str, max_tokens: int = 1200) -> dict[str, Any]:
    """
    Public helper for scripts that need a JSON-only LLM response.

    Raises NoConfiguredProviderError when no provider key exists, ValueError
    when parsing fails, and LLMProviderFailure when configured providers all
    fail, so callers can decide whether to skip or use mock fallbacks.
    """
    load_dotenv()
    raw_text = _call_llm_text(system_prompt, user_prompt, max_tokens=max_tokens)
    return _parse_json_response(raw_text)


def analyze_article(article: dict) -> dict[str, Any]:
    """
    Analyze a crawled article using an available LLM provider.

    When API keys or optional SDKs are unavailable, the function returns a
    mock result so the rest of the app remains usable during demos.
    """
    load_dotenv()

    if not article or not article.get("body"):
        return _build_mock_analysis(
            article or {},
            "기사 본문이 없어 mock 분석 결과를 표시합니다.",
        )

    try:
        raw_text = _call_llm_text(
            SYSTEM_PROMPT,
            get_analysis_prompt(article),
            max_tokens=2200,
        )
        try:
            normalized = _normalize_analysis(_parse_json_response(raw_text))
        except ValueError:
            # Retry once with a larger budget because Gemini sometimes truncates
            # the long JSON schema used by the main analysis response.
            retry_text = _call_llm_text(
                SYSTEM_PROMPT,
                get_analysis_prompt(article),
                max_tokens=2800,
            )
            normalized = _normalize_analysis(_parse_json_response(retry_text))
        return _calibrate_supplemental_diagnostics(normalized, article)
    except NoConfiguredProviderError:
        return _build_mock_analysis(
            article,
            f"{SUPPORTED_LLM_KEY_TEXT}가 없어 mock 분석 결과를 표시합니다.",
        )
    except ValueError as exc:
        return _build_mock_analysis(
            article,
            f"{exc} mock 분석 결과로 대체했습니다.",
        )
    except LLMProviderFailure as exc:
        return _build_mock_analysis(
            article,
            f"{exc} mock 분석 결과로 대체했습니다.",
        )
    except Exception as exc:
        return _build_mock_analysis(
            article,
            f"LLM 호출 중 오류가 발생했습니다: {exc}. mock 분석 결과로 대체했습니다.",
        )


def explain_external_candidates(article: dict, analysis: dict, candidates: list[dict]) -> dict[str, Any]:
    """
    Provide short LLM guidance for externally searched candidate articles.

    The guidance explains why each article may be worth comparing, but it does
    not claim that the candidates are confirmed opposite-frame recommendations.
    """
    load_dotenv()

    if not candidates:
        return {"overall_note": "", "candidates": []}

    try:
        raw_text = _call_llm_text(
            EXTERNAL_GUIDANCE_SYSTEM_PROMPT,
            get_external_candidate_prompt(article, analysis, candidates),
            max_tokens=1400,
        )
        return _normalize_external_guidance(_parse_json_response(raw_text), candidates)
    except NoConfiguredProviderError:
        return _build_mock_external_guidance(
            analysis,
            candidates,
            f"{SUPPORTED_LLM_KEY_TEXT}가 없어 외부 후보 기사 설명은 mock 안내문으로 표시합니다.",
        )
    except ValueError as exc:
        return _build_mock_external_guidance(
            analysis,
            candidates,
            f"{exc} 외부 후보 기사 설명은 mock 안내문으로 대체했습니다.",
        )
    except LLMProviderFailure as exc:
        return _build_mock_external_guidance(
            analysis,
            candidates,
            f"{exc} 외부 후보 기사 설명은 mock 안내문으로 대체했습니다.",
        )
    except Exception as exc:
        return _build_mock_external_guidance(
            analysis,
            candidates,
            f"외부 후보 기사 설명 생성 중 오류가 발생했습니다: {exc}. mock 안내문으로 대체했습니다.",
        )


def tag_article_metadata(article: dict, issue: str) -> dict[str, Any]:
    """
    Tag a collected article for recommendation-dataset construction.

    Returns a dict with:
    - sub_issue
    - issue_tags
    - frame
    - tone
    - primary_voice
    - memo
    - tagging_status
    """
    load_dotenv()

    try:
        payload = request_llm_json(
            DATASET_TAGGING_SYSTEM_PROMPT,
            get_dataset_tagging_prompt(issue, article),
            max_tokens=1200,
        )
        normalized = _normalize_dataset_tag(payload)
        normalized["tagging_status"] = "ok"
        return normalized
    except NoConfiguredProviderError:
        mock_tag = _build_mock_dataset_tag(
            article,
            issue,
            f"{SUPPORTED_LLM_KEY_TEXT}가 없어 mock 태깅 결과를 표시합니다.",
        )
        mock_tag["tagging_status"] = "mock"
        return mock_tag
    except ValueError as exc:
        mock_tag = _build_mock_dataset_tag(
            article,
            issue,
            f"{exc} mock 태깅 결과로 대체했습니다.",
        )
        mock_tag["tagging_status"] = "mock"
        return mock_tag
    except LLMProviderFailure as exc:
        mock_tag = _build_mock_dataset_tag(
            article,
            issue,
            f"{exc} mock 태깅 결과로 대체했습니다.",
        )
        mock_tag["tagging_status"] = "failed"
        return mock_tag
    except Exception as exc:
        mock_tag = _build_mock_dataset_tag(
            article,
            issue,
            f"LLM 호출 중 오류가 발생했습니다: {exc}. mock 태깅 결과로 대체했습니다.",
        )
        mock_tag["tagging_status"] = "failed"
        return mock_tag


def analyze_news(article_or_body: dict | str) -> dict[str, Any]:
    """Compatibility wrapper for older early-stage app naming."""
    if isinstance(article_or_body, dict):
        article = article_or_body
    else:
        article = {
            "title": "",
            "body": article_or_body,
            "source": "",
            "date": "",
            "url": "",
        }
    return analyze_article(article)
