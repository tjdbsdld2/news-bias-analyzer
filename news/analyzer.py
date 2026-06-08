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
LLM_TIMEOUT_SECONDS = 25


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


def _build_mock_analysis(article: dict, notice: str) -> dict[str, Any]:
    """Create a readable fallback so the app still runs without API keys."""
    title = article.get("title", "입력 기사")
    source = article.get("source", "해당 기사")
    body = article.get("body", "")
    excerpt = body[:160].strip()
    sentences = [part.strip() for part in re.split(r"(?<=[.!?])\s+|(?<=다\.)\s+|(?<=요\.)\s+", body) if part.strip()]

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
            "framing_analysis": (
                f"{source} 기사에서 어떤 행위자와 주장에 더 많은 지면이 배정되는지 살펴보도록 설계된 mock 분석입니다."
            ),
            "language_analysis": "실제 API 없이 실행 중이므로, 감정적 표현이나 평가어 존재 여부를 점검하는 예시 문장입니다.",
            "citation_analysis": "실제 API 없이 실행 중이므로, 어떤 출처가 더 자주 등장하는지 확인하는 예시 문장입니다.",
            "title_body_gap": "제목과 본문의 강조점이 완전히 같은지, 혹은 제목이 더 강한 어조를 쓰는지 비교하는 예시 문장입니다.",
            "missing_perspective": "다른 이해관계자, 반대 입장, 구조적 배경 맥락을 함께 읽어보라는 안내용 예시 문장입니다.",
            "reading_focus": "이 기사를 읽을 때는 초반 문제 설정 문장과, 수치나 직접 발언이 실제로 얼마나 구체적인지 먼저 확인해 보세요.",
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
    body = article.get("body", "")
    source = article.get("source", "해당 기사")
    excerpt = body[:140].strip()
    issue_terms = [issue] if issue else []
    if article.get("source"):
        issue_terms.append(str(article["source"]).strip())

    mock_tag = DEFAULT_DATASET_TAG.copy()
    mock_tag.update(
        {
            "sub_issue": f"{issue} 관련 세부 쟁점" if issue else DEFAULT_DATASET_TAG["sub_issue"],
            "issue_tags": issue_terms[:2] + ["정책", "사회"][: max(0, 3 - len(issue_terms[:2]))],
            "memo": (
                f"'{title}' 기사에서 {source}가 어떤 주체와 강조점을 전면에 두는지 기준으로 생성한 mock 태깅 결과입니다."
                if excerpt
                else DEFAULT_DATASET_TAG["memo"]
            ),
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


def _call_llm_text(system_prompt: str, user_prompt: str, max_tokens: int = 1200) -> str:
    """Dispatch a prompt to whichever LLM provider is configured."""
    if _get_google_api_key():
        return _call_google_prompt(system_prompt, user_prompt, max_tokens=max_tokens)

    if os.getenv("OPENAI_API_KEY") or os.getenv("OPENROUTER_API_KEY"):
        return _call_openai_prompt(system_prompt, user_prompt)

    if os.getenv("ANTHROPIC_API_KEY"):
        return _call_anthropic_prompt(system_prompt, user_prompt, max_tokens=max_tokens)

    raise RuntimeError(f"{SUPPORTED_LLM_KEY_TEXT}가 설정되지 않았습니다.")


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

    Raises RuntimeError when no provider key exists and ValueError when parsing
    fails, so callers can decide whether to skip or use mock fallbacks.
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
        raw_text = _call_llm_text(SYSTEM_PROMPT, get_analysis_prompt(article))
        normalized = _normalize_analysis(_parse_json_response(raw_text))
        return _calibrate_supplemental_diagnostics(normalized, article)
    except RuntimeError:
        return _build_mock_analysis(
            article,
            f"{SUPPORTED_LLM_KEY_TEXT}가 없어 mock 분석 결과를 표시합니다.",
        )
    except ImportError:
        return _build_mock_analysis(
            article,
            "LLM SDK가 설치되지 않아 mock 분석 결과를 표시합니다.",
        )
    except ValueError as exc:
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
    except RuntimeError:
        return _build_mock_external_guidance(
            analysis,
            candidates,
            f"{SUPPORTED_LLM_KEY_TEXT}가 없어 외부 후보 기사 설명은 mock 안내문으로 표시합니다.",
        )
    except ImportError:
        return _build_mock_external_guidance(
            analysis,
            candidates,
            "LLM SDK가 없어 외부 후보 기사 설명은 mock 안내문으로 표시합니다.",
        )
    except ValueError as exc:
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
    except RuntimeError:
        mock_tag = _build_mock_dataset_tag(
            article,
            issue,
            f"{SUPPORTED_LLM_KEY_TEXT}가 없어 mock 태깅 결과를 표시합니다.",
        )
        mock_tag["tagging_status"] = "mock"
        return mock_tag
    except ImportError:
        mock_tag = _build_mock_dataset_tag(
            article,
            issue,
            "LLM SDK가 설치되지 않아 mock 태깅 결과를 표시합니다.",
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
