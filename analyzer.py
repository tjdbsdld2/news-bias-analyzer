"""LLM-based article analysis with a safe mock fallback."""

from __future__ import annotations

import json
import os
import re
from typing import Any

from dotenv import load_dotenv

from prompts import SYSTEM_PROMPT, get_analysis_prompt


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
}


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


def _normalize_issue_tags(value: Any) -> list[str]:
    """Keep issue tags in a small, predictable list form."""
    if isinstance(value, str):
        candidates = [item.strip() for item in re.split(r"[,/]", value) if item.strip()]
        return candidates[:3]

    if isinstance(value, list):
        tags = [str(item).strip() for item in value if str(item).strip()]
        return tags[:3]

    return DEFAULT_ANALYSIS["issue_tags"][:]


def _normalize_analysis(payload: dict[str, Any]) -> dict[str, Any]:
    """Merge partial or slightly malformed LLM output into the expected schema."""
    normalized = DEFAULT_ANALYSIS.copy()
    for key in DEFAULT_ANALYSIS:
        if key not in payload:
            continue

        if key == "issue_tags":
            normalized[key] = _normalize_issue_tags(payload[key])
        else:
            value = payload[key]
            normalized[key] = str(value).strip() if value not in (None, "") else DEFAULT_ANALYSIS[key]

    return normalized


def _build_mock_analysis(article: dict, notice: str) -> dict[str, Any]:
    """Create a readable fallback so the app still runs without API keys."""
    title = article.get("title", "입력 기사")
    source = article.get("source", "해당 기사")
    body = article.get("body", "")
    excerpt = body[:160].strip()

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
            "analysis_notice": notice,
        }
    )
    return mock_result


def _parse_json_response(raw_text: str) -> dict[str, Any]:
    """Parse a model response into JSON, raising a helpful error if it fails."""
    try:
        cleaned = _strip_code_fences(raw_text)
        payload = json.loads(cleaned)
    except json.JSONDecodeError as exc:
        raise ValueError("LLM 응답을 JSON으로 해석하지 못했습니다.") from exc

    if not isinstance(payload, dict):
        raise ValueError("LLM 응답 JSON이 객체 형태가 아닙니다.")
    return payload


def _call_openai(article: dict) -> str:
    """Call the OpenAI Chat Completions API."""
    from openai import OpenAI

    client = OpenAI(api_key=os.getenv("OPENAI_API_KEY"))
    response = client.chat.completions.create(
        model=os.getenv("OPENAI_MODEL", "gpt-4o-mini"),
        temperature=0.2,
        messages=[
            {"role": "system", "content": SYSTEM_PROMPT},
            {"role": "user", "content": get_analysis_prompt(article)},
        ],
    )
    return response.choices[0].message.content or ""


def _call_anthropic(article: dict) -> str:
    """Call the Anthropic Messages API."""
    from anthropic import Anthropic

    client = Anthropic(api_key=os.getenv("ANTHROPIC_API_KEY"))
    response = client.messages.create(
        model=os.getenv("ANTHROPIC_MODEL", "claude-3-5-sonnet-latest"),
        temperature=0.2,
        max_tokens=1200,
        system=SYSTEM_PROMPT,
        messages=[{"role": "user", "content": get_analysis_prompt(article)}],
    )

    text_blocks = [block.text for block in response.content if getattr(block, "type", "") == "text"]
    return "\n".join(text_blocks)


def analyze_article(article: dict) -> dict[str, Any]:
    """
    Analyze a crawled article using an available LLM provider.

    When API keys or optional SDKs are unavailable, the function returns a
    mock result so the rest of the Streamlit app remains usable during demos.
    """
    load_dotenv()

    if not article or not article.get("body"):
        return _build_mock_analysis(
            article or {},
            "기사 본문이 없어 mock 분석 결과를 표시합니다.",
        )

    try:
        if os.getenv("OPENAI_API_KEY"):
            raw_text = _call_openai(article)
            return _normalize_analysis(_parse_json_response(raw_text))

        if os.getenv("ANTHROPIC_API_KEY"):
            raw_text = _call_anthropic(article)
            return _normalize_analysis(_parse_json_response(raw_text))

        return _build_mock_analysis(
            article,
            "OPENAI_API_KEY 또는 ANTHROPIC_API_KEY가 없어 mock 분석 결과를 표시합니다.",
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
