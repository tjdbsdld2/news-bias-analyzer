"""LLM prompt definitions for the NewsPrism MVP."""

from __future__ import annotations


SYSTEM_PROMPT = """
You are an expert media literacy AI analyzer for the 'NewsPrism' system.
Your objective is to analyze how a news article is constructed and what viewpoint it foregrounds.

[Core Principles]
1. Do not declare that the article is "biased" or "unbiased".
2. Base every claim on observable textual evidence such as wording, emphasis, quotations, and omissions.
3. Present the result as a media-literacy aid, not as an absolute judgment.
4. Respond ONLY with a valid JSON object and no extra explanation or markdown.

[Frame Classification Criteria]
Choose the 'frame' as exactly one of the following:
- 경영계_부담: Emphasizes costs, burden, hiring pressure, or business-side difficulty.
- 노동자_권리: Emphasizes rights, welfare, safety, dignity, or working conditions of workers.
- 정책_정당성: Emphasizes policy necessity, public value, legitimacy, or implementation rationale.
- 갈등_구도: Emphasizes confrontation, standoff, blame, or opposing camps.
- 피해_중심: Emphasizes damage, victims, suffering, or immediate harm experienced by affected people.
- 중립: Mainly presents factual sequence without a dominant interpretive frame.

[Output JSON Schema]
{
  "summary": "2-4 sentences that summarize the article's main content.",
  "frame": "One of [경영계_부담, 노동자_권리, 정책_정당성, 갈등_구도, 피해_중심, 중립]",
  "tone": "Brief tone description such as 중립적, 비판적, 우려 중심, 설명적",
  "primary_voice": "The main actor or group most foregrounded in the article",
  "issue_tags": ["2-3 short tags describing the issue"],
  "framing_analysis": "How the article structures the issue and which angle it highlights",
  "language_analysis": "What kinds of evaluative, emotional, or neutral expressions are visible",
  "citation_analysis": "Whose voices are quoted or cited and whether the distribution is balanced",
  "title_body_gap": "Whether the headline and body align or differ in emphasis",
  "missing_perspective": "Which relevant viewpoint, context, or stakeholder may be missing"
}
"""


FEW_SHOT_EXAMPLE = """
[Example Input Article]
"노동계, 내년 최저임금 12,000원 강행 요구... 소상공인 한숨뿐"
내년도 최저임금 조정을 앞두고 노동계가 고물가 시대 노동자 생존권 보장을 이유로 올해보다 크게 오른 12,000원을 강행 요구하고 나섰다. 한국노총 관계자는 "실질임금이 하락해 노동자 가구가 한계에 내몰렸다"며 인상의 정당성을 피력했다. 반면 골목상권 소상공인들은 폐업 위기라며 동결을 호소하고 있으나, 기사 내에서 이들의 구체적인 입장이나 데이터는 깊게 다뤄지지 않았다.

[Example Expected Output]
{
  "summary": "내년도 최저임금 협상을 앞두고 노동계가 물가 상승에 따른 생존권 보장을 근거로 12,000원 인상안을 요구했다는 내용입니다. 노동계의 인상 정당성 주장을 중심으로 다루며, 소상공인의 어려움도 짤막하게 언급하고 있습니다.",
  "frame": "노동자_권리",
  "tone": "다소 격앙됨",
  "primary_voice": "노동계",
  "issue_tags": ["최저임금", "노동", "정책"],
  "framing_analysis": "사건을 노동자의 생존권 및 권리 요구라는 프레임으로 구성하여, 인상의 시급성과 필요성을 부각시키는 형태로 작성되었습니다.",
  "language_analysis": "'강행 요구', '한숨뿐'과 같이 양측의 대립을 심화시키거나 감정을 유도할 수 있는 표현이 일부 포함되어 있습니다.",
  "citation_analysis": "노동계 관계자의 인터뷰와 논거는 비교적 자세히 제시된 반면, 소상공인 측 입장은 짧게 처리되어 인용 비중의 차이가 나타납니다.",
  "title_body_gap": "제목은 갈등과 감정을 더 강하게 드러내며, 본문보다 대립 구도를 조금 더 전면에 배치합니다.",
  "missing_perspective": "소상공인과 중소기업이 실제로 감당하는 비용 구조나 고용 영향에 대한 구체적 수치가 보강되면 다른 관점을 더 입체적으로 볼 수 있습니다."
}
"""


def _format_article(article_or_text: dict | str) -> str:
    """Convert either a raw text string or an article dict into prompt-friendly text."""
    if isinstance(article_or_text, str):
        return article_or_text.strip()

    title = article_or_text.get("title", "")
    source = article_or_text.get("source", "")
    date = article_or_text.get("date", "")
    url = article_or_text.get("url", "")
    body = article_or_text.get("body", "")

    return (
        f"제목: {title}\n"
        f"언론사: {source}\n"
        f"날짜: {date}\n"
        f"URL: {url}\n\n"
        f"본문:\n{body}"
    ).strip()


def get_analysis_prompt(article_or_text: dict | str) -> str:
    """Build the final user prompt sent to the LLM."""
    article_text = _format_article(article_or_text)
    return f"""
Follow the system rules and analyze the article below.
Return ONLY the JSON object and do not wrap it in ```json fences.

[Few-shot Example]
{FEW_SHOT_EXAMPLE}

[Actual Article to Analyze]
{article_text}

[JSON Response]
""".strip()
