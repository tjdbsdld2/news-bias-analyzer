import argparse
import json
import os
import re
from typing import Any, Dict

import requests

try:
    from crawler import crawl_news
except Exception:
    crawl_news = None


LLM_BASE_URL = os.getenv("LLM_BASE_URL", "https://openrouter.ai/api/v1").strip()
LLM_MODEL = os.getenv("LLM_MODEL", "openrouter/free").strip()
LLM_API_KEY = (
    os.getenv("OPENROUTER_API_KEY")
    or os.getenv("LLM_API_KEY")
    or os.getenv("OPENAI_API_KEY")
    or ""
).strip()

USE_RESPONSE_FORMAT = os.getenv("OPENROUTER_USE_RESPONSE_FORMAT", "0").strip() == "1"
LLM_TIMEOUT = int(os.getenv("LLM_TIMEOUT", "60"))

PERSPECTIVE_KEYS = [
    "pro_government",
    "anti_government",
    "pro_business",
    "pro_labor",
    "pro_market",
    "pro_welfare",
    "pro_regulation",
    "anti_regulation",
    "risk_emphasis",
    "benefit_emphasis",
]

ANALYZER_SYSTEM_PROMPT = """
너는 한국어 뉴스 편향성 분석기다.

너의 역할은 기사 표면의 문장만 보는 것이 아니라,
1. 기사 내용이 어느 이해관계자에게 유리하게 구성되었는지,
2. 어떤 프레임을 중심으로 사건을 설명하는지,
3. 기사 자체가 작성되고 보도된 배경이 누구에게 유리한지,
4. 어떤 관점이 누락되었는지,
5. 독자가 기사 이후 어떤 인상을 갖게 되는지
를 강하게 분석하는 것이다.

주의:
- 정치적 선호나 개인 의견을 드러내지 마라.
- 그러나 "중립"이라는 이유로 모든 수치를 0으로 두지 마라.
- 대부분의 기사는 명시적 편향이 약해도 프레임 선택, 제목, 인용 구조, 사건 선택, 배경 설정에서 구조적 편향을 가진다.
- 기사 내용 편향과 기사 배경 편향을 모두 반영해서 최종 bias_axis와 perspective_vector를 산출하라.
- 반드시 JSON 객체만 반환하라.
""".strip()


def safe_str(value: Any) -> str:
    if value is None:
        return ""
    return str(value)


def safe_float(value: Any, default: float = 0.0) -> float:
    try:
        return float(value)
    except Exception:
        return default


def clean_html(text: str) -> str:
    text = safe_str(text)
    text = re.sub(r"<script[\s\S]*?</script>", " ", text, flags=re.IGNORECASE)
    text = re.sub(r"<style[\s\S]*?</style>", " ", text, flags=re.IGNORECASE)
    text = re.sub(r"<[^>]+>", " ", text)
    text = re.sub(r"&nbsp;|&amp;|&lt;|&gt;|&quot;|&#39;", " ", text)
    text = re.sub(r"\s+", " ", text)
    return text.strip()


def clip_text(text: str, max_chars: int = 12000) -> str:
    text = safe_str(text)

    if len(text) <= max_chars:
        return text

    return text[:max_chars]


def load_env_file(path: str = ".env") -> None:
    """
    .env 파일을 선택적으로 읽는다.
    이미 설정된 환경변수는 덮어쓰지 않는다.
    """
    if not os.path.exists(path):
        return

    with open(path, "r", encoding="utf-8") as file:
        for line in file:
            line = line.strip()

            if not line or line.startswith("#") or "=" not in line:
                continue

            key, value = line.split("=", 1)
            key = key.strip()
            value = value.strip().strip('"').strip("'")

            if key and key not in os.environ:
                os.environ[key] = value


def refresh_llm_config_from_env() -> None:
    global LLM_BASE_URL, LLM_MODEL, LLM_API_KEY, USE_RESPONSE_FORMAT

    load_env_file()

    LLM_BASE_URL = os.getenv("LLM_BASE_URL", LLM_BASE_URL).strip()
    LLM_MODEL = os.getenv("LLM_MODEL", LLM_MODEL).strip()
    LLM_API_KEY = (
        os.getenv("OPENROUTER_API_KEY")
        or os.getenv("LLM_API_KEY")
        or os.getenv("OPENAI_API_KEY")
        or LLM_API_KEY
        or ""
    ).strip()

    USE_RESPONSE_FORMAT = (
        os.getenv(
            "OPENROUTER_USE_RESPONSE_FORMAT",
            "1" if USE_RESPONSE_FORMAT else "0",
        ).strip()
        == "1"
    )


def json_loads_safely(text: str) -> Dict:
    if not isinstance(text, str):
        raise ValueError("LLM 응답이 문자열이 아닙니다.")

    text = text.strip()

    if text.startswith("```"):
        text = re.sub(r"^```(?:json)?", "", text).strip()
        text = re.sub(r"```$", "", text).strip()

    match = re.search(r"\{[\s\S]*\}", text)

    if match:
        text = match.group(0)

    return json.loads(text)


def normalize_analysis(analysis: Dict) -> Dict:
    """
    recommender.py가 요구하는 analysis dict 형식으로 정규화한다.
    """
    if not isinstance(analysis, dict):
        analysis = {}

    vector = analysis.get("perspective_vector", {})

    if isinstance(vector, str):
        try:
            vector = json.loads(vector)
        except Exception:
            vector = {}

    if not isinstance(vector, dict):
        vector = {}

    normalized_vector = {}

    for key in PERSPECTIVE_KEYS:
        normalized_vector[key] = max(
            0.0,
            min(
                100.0,
                safe_float(
                    vector.get(key),
                    0.0,
                ),
            ),
        )

    loaded_terms = analysis.get("loaded_terms", [])
    if not isinstance(loaded_terms, list):
        loaded_terms = []

    missing_perspectives = analysis.get("missing_perspectives", [])
    if not isinstance(missing_perspectives, list):
        missing_perspectives = []

    content_bias = analysis.get("content_bias", {})
    if not isinstance(content_bias, dict):
        content_bias = {}

    background_bias = analysis.get("background_bias", {})
    if not isinstance(background_bias, dict):
        background_bias = {}

    return {
        "topic": safe_str(analysis.get("topic")),
        "summary": safe_str(analysis.get("summary")),
        "main_frame": safe_str(analysis.get("main_frame")),
        "stance": safe_str(analysis.get("stance")),
        "bias_axis": max(
            -100.0,
            min(
                100.0,
                safe_float(
                    analysis.get("bias_axis"),
                    0.0,
                ),
            ),
        ),
        "bias_strength": max(
            0.0,
            min(
                100.0,
                safe_float(
                    analysis.get("bias_strength"),
                    0.0,
                ),
            ),
        ),
        "emotionality": max(
            0.0,
            min(
                100.0,
                safe_float(
                    analysis.get("emotionality"),
                    0.0,
                ),
            ),
        ),
        "source_balance": max(
            0.0,
            min(
                100.0,
                safe_float(
                    analysis.get("source_balance"),
                    50.0,
                ),
            ),
        ),
        "evidence_quality": max(
            0.0,
            min(
                100.0,
                safe_float(
                    analysis.get("evidence_quality"),
                    50.0,
                ),
            ),
        ),
        "perspective_vector": normalized_vector,
        "loaded_terms": loaded_terms,
        "missing_perspectives": missing_perspectives,
        "reasoning": safe_str(analysis.get("reasoning")),
        "content_bias": {
            "favored_side": safe_str(content_bias.get("favored_side")),
            "disfavored_side": safe_str(content_bias.get("disfavored_side")),
            "axis": max(
                -100.0,
                min(
                    100.0,
                    safe_float(
                        content_bias.get("axis"),
                        0.0,
                    ),
                ),
            ),
            "strength": max(
                0.0,
                min(
                    100.0,
                    safe_float(
                        content_bias.get("strength"),
                        0.0,
                    ),
                ),
            ),
            "reasoning": safe_str(content_bias.get("reasoning")),
        },
        "background_bias": {
            "favored_side": safe_str(background_bias.get("favored_side")),
            "disfavored_side": safe_str(background_bias.get("disfavored_side")),
            "axis": max(
                -100.0,
                min(
                    100.0,
                    safe_float(
                        background_bias.get("axis"),
                        0.0,
                    ),
                ),
            ),
            "strength": max(
                0.0,
                min(
                    100.0,
                    safe_float(
                        background_bias.get("strength"),
                        0.0,
                    ),
                ),
            ),
            "reasoning": safe_str(background_bias.get("reasoning")),
        },
    }


def calibrate_analysis_with_article(
    analysis: Dict,
    article: Dict,
) -> Dict:
    """
    LLM이 지나치게 중립적으로 0에 가깝게 분석한 경우,
    기사 내용과 배경 맥락을 기반으로 최소 보정을 수행한다.

    이 함수는 추천기가 편향 거리 계산을 할 수 있도록
    bias_strength와 perspective_vector가 완전히 비어 있는 상태를 방지한다.
    """
    title = safe_str(article.get("title"))
    content = safe_str(article.get("content"))
    text = f"{title} {content}"

    topic = safe_str(analysis.get("topic"))
    main_frame = safe_str(analysis.get("main_frame"))
    stance = safe_str(analysis.get("stance"))

    bias_axis = safe_float(analysis.get("bias_axis"), 0.0)
    bias_strength = safe_float(analysis.get("bias_strength"), 0.0)
    emotionality = safe_float(analysis.get("emotionality"), 0.0)
    source_balance = safe_float(analysis.get("source_balance"), 50.0)
    evidence_quality = safe_float(analysis.get("evidence_quality"), 50.0)

    vector = analysis.get("perspective_vector", {}) or {}

    labor_keywords = [
        "노조",
        "노동조합",
        "노동자",
        "근로자",
        "조합원",
        "파업",
        "임금 인상",
        "처우 개선",
        "단체교섭",
        "부당노동행위",
        "노동권",
    ]

    company_keywords = [
        "회사",
        "사측",
        "경영진",
        "기업",
        "사용자",
        "손실",
        "생산 차질",
        "경영 부담",
        "불법 파업",
        "업무 방해",
        "경쟁력",
    ]

    government_keywords = [
        "정부",
        "고용노동부",
        "대통령",
        "장관",
        "정책",
        "제도",
        "규제",
        "개혁",
    ]

    risk_keywords = [
        "우려",
        "논란",
        "갈등",
        "차질",
        "피해",
        "부담",
        "위기",
        "반발",
        "공백",
        "대란",
    ]

    benefit_keywords = [
        "개선",
        "확대",
        "보호",
        "강화",
        "지원",
        "안정",
        "회복",
        "보장",
    ]

    labor_hits = sum(1 for keyword in labor_keywords if keyword in text)
    company_hits = sum(1 for keyword in company_keywords if keyword in text)
    government_hits = sum(1 for keyword in government_keywords if keyword in text)
    risk_hits = sum(1 for keyword in risk_keywords if keyword in text)
    benefit_hits = sum(1 for keyword in benefit_keywords if keyword in text)

    is_labor_company_issue = labor_hits > 0 and company_hits > 0
    is_policy_issue = government_hits > 0 or "정책" in text or "제도" in text

    if is_labor_company_issue:
        if not topic:
            analysis["topic"] = "노사 갈등"

        if labor_hits > company_hits:
            if main_frame in ["", "중립", "노사 갈등"]:
                analysis["main_frame"] = "노조_권리보호"

            if stance in ["", "neutral"]:
                analysis["stance"] = "supportive"

            if bias_axis < 25:
                analysis["bias_axis"] = 45.0

            if bias_strength < 40:
                analysis["bias_strength"] = 55.0

            vector["pro_labor"] = max(
                safe_float(vector.get("pro_labor"), 0.0),
                85.0,
            )
            vector["pro_welfare"] = max(
                safe_float(vector.get("pro_welfare"), 0.0),
                65.0,
            )
            vector["pro_regulation"] = max(
                safe_float(vector.get("pro_regulation"), 0.0),
                60.0,
            )

            analysis["content_bias"] = {
                "favored_side": "노조/노동자",
                "disfavored_side": "회사/사측",
                "axis": 45.0,
                "strength": 55.0,
                "reasoning": "기사 내용에서 노동자 권리, 처우, 노조 입장이 상대적으로 더 강조된다.",
            }

        elif company_hits > labor_hits:
            if main_frame in ["", "중립", "노사 갈등"]:
                analysis["main_frame"] = "회사_경영부담"

            if stance in ["", "neutral"]:
                analysis["stance"] = "critical"

            if bias_axis > -25:
                analysis["bias_axis"] = -45.0

            if bias_strength < 40:
                analysis["bias_strength"] = 55.0

            vector["pro_business"] = max(
                safe_float(vector.get("pro_business"), 0.0),
                85.0,
            )
            vector["pro_market"] = max(
                safe_float(vector.get("pro_market"), 0.0),
                70.0,
            )
            vector["anti_regulation"] = max(
                safe_float(vector.get("anti_regulation"), 0.0),
                60.0,
            )
            vector["risk_emphasis"] = max(
                safe_float(vector.get("risk_emphasis"), 0.0),
                75.0,
            )

            analysis["content_bias"] = {
                "favored_side": "회사/사측",
                "disfavored_side": "노조/노동자",
                "axis": -45.0,
                "strength": 55.0,
                "reasoning": "기사 내용에서 경영 부담, 생산 차질, 회사 피해가 상대적으로 더 강조된다.",
            }

        else:
            if main_frame in ["", "중립"]:
                analysis["main_frame"] = "노사_대립"

            if stance in ["", "neutral"]:
                analysis["stance"] = "mixed"

            if abs(bias_axis) < 5:
                analysis["bias_axis"] = 0.0

            if bias_strength < 30:
                analysis["bias_strength"] = 40.0

            if source_balance < 60:
                analysis["source_balance"] = 70.0

            vector["pro_labor"] = max(
                safe_float(vector.get("pro_labor"), 0.0),
                65.0,
            )
            vector["pro_business"] = max(
                safe_float(vector.get("pro_business"), 0.0),
                65.0,
            )
            vector["risk_emphasis"] = max(
                safe_float(vector.get("risk_emphasis"), 0.0),
                60.0,
            )

            analysis["content_bias"] = {
                "favored_side": "양측 균형",
                "disfavored_side": "",
                "axis": 0.0,
                "strength": 40.0,
                "reasoning": "노조와 회사 양측의 이해가 모두 등장하며 대립 구조를 전달한다.",
            }

        if "background_bias" not in analysis or not isinstance(analysis.get("background_bias"), dict):
            if "파업" in text or "생산 차질" in text or "피해" in text:
                analysis["background_bias"] = {
                    "favored_side": "회사/사측",
                    "disfavored_side": "노조/노동자",
                    "axis": -35.0,
                    "strength": 45.0,
                    "reasoning": "파업이나 차질 자체를 보도하는 배경은 독자에게 회사 피해와 사회적 비용을 먼저 인식시킬 수 있다.",
                }
            elif "부당노동행위" in text or "처우 개선" in text or "노동권" in text:
                analysis["background_bias"] = {
                    "favored_side": "노조/노동자",
                    "disfavored_side": "회사/사측",
                    "axis": 35.0,
                    "strength": 45.0,
                    "reasoning": "노동권 침해나 처우 문제를 보도하는 배경은 노동자 측 문제 제기에 정당성을 부여할 수 있다.",
                }

    if is_policy_issue and bias_strength < 20:
        analysis["bias_strength"] = 25.0

    if risk_hits > 0:
        vector["risk_emphasis"] = max(
            safe_float(vector.get("risk_emphasis"), 0.0),
            min(100.0, 45.0 + risk_hits * 5.0),
        )

    if benefit_hits > 0:
        vector["benefit_emphasis"] = max(
            safe_float(vector.get("benefit_emphasis"), 0.0),
            min(100.0, 45.0 + benefit_hits * 5.0),
        )

    if emotionality < 5 and risk_hits > 0:
        analysis["emotionality"] = 10.0

    if evidence_quality < 50 and (
        "자료" in text
        or "조사" in text
        or "통계"
        in text
        or "발표"
        in text
        or "인용"
        in text
    ):
        analysis["evidence_quality"] = 60.0

    analysis["perspective_vector"] = vector

    return normalize_analysis(analysis)


def fetch_url_article(
    news_url: str,
    delay: float = 1.0,
) -> Dict:
    """
    사용자가 입력한 URL을 기사 dict로 변환한다.

    1순위:
    - crawler.py의 crawl_news 사용

    2순위:
    - requests로 HTML을 가져와 단순 텍스트 추출
    """
    if crawl_news is not None:
        result = crawl_news(
            news_url=news_url,
            delay=delay,
        )

        if result.get("crawl_status") == "success":
            return {
                "url": safe_str(result.get("url")) or news_url,
                "title": safe_str(result.get("title")) or news_url,
                "source": safe_str(result.get("source")) or "input_url",
                "content": safe_str(result.get("content")),
            }

    response = requests.get(
        news_url,
        timeout=20,
        headers={
            "User-Agent": "Mozilla/5.0",
        },
    )
    response.raise_for_status()

    html = response.text

    title_match = re.search(
        r"<title[^>]*>([\s\S]*?)</title>",
        html,
        flags=re.IGNORECASE,
    )

    title = clean_html(
        title_match.group(1)
    ) if title_match else news_url

    return {
        "url": news_url,
        "title": title,
        "source": "input_url",
        "content": clean_html(html),
    }


def build_analysis_prompt(article: Dict) -> str:
    url = safe_str(article.get("url"))
    title = safe_str(article.get("title"))
    source = safe_str(article.get("source"))
    content = clip_text(
        safe_str(article.get("content")),
        12000,
    )

    return f"""
사용자가 입력한 URL의 한국어 뉴스 기사를 분석하라.
분석 결과는 recommender.py가 요구하는 입력 형식으로 JSON 객체만 반환하라.

이번 분석의 핵심은 "강한 편향 분석"이다.
기사가 노골적으로 한쪽 편을 들지 않더라도,
제목, 사건 선택, 인용 순서, 강조된 피해, 누락된 이해관계자, 보도 시점, 기사 작성 배경이
어느 쪽에 유리하게 작동하는지 반드시 판단하라.

분석할 편향은 두 층위다.

1. 기사 자체 내용의 편향(content_bias)
   - 기사 본문과 제목에서 어느 쪽 주장이 더 많이, 더 강하게, 더 설득력 있게 제시되는가?
   - 어떤 이해관계자가 피해자/가해자/문제 해결자로 묘사되는가?
   - 어떤 표현이 더 감정적으로 제시되는가?
   - 예: 노조 관련 기사라면 기사 내용이 노조 편인지, 회사 편인지, 양측 균형인지 판단한다.

2. 기사 작성 배경의 편향(background_bias)
   - 이 기사가 이런 시점에 이런 주제로 쓰였다는 사실 자체가 누구에게 유리한가?
   - 이 사건을 뉴스로 선택한 것이 어느 이해관계자의 문제 제기를 정당화하는가?
   - 예: 파업으로 인한 생산 차질을 보도하는 기사는 내용이 균형적이어도 배경상 회사 피해와 사회적 비용을 부각해 회사 측에 유리할 수 있다.
   - 예: 부당노동행위나 처우 개선 요구를 보도하는 기사는 내용이 균형적이어도 배경상 노조/노동자 측 문제 제기에 유리할 수 있다.

중요 규칙:
- "neutral"이라고 해서 bias_strength를 0으로 두지 마라.
- 사회적 갈등, 노사 대립, 정책 논쟁, 규제 논쟁, 비용 부담 논쟁, 공공성 논쟁이 있으면 bias_strength는 최소 20 이상으로 평가하라.
- 기사 자체 내용 편향과 기사 작성 배경 편향이 서로 다르면 둘을 따로 기록하라.
- 최종 bias_axis는 content_bias와 background_bias를 종합해서 판단하라.
- 단순히 양측 인용이 있다는 이유만으로 완전 중립 처리하지 마라.
- 기사에서 어떤 관점이 독자에게 더 기억될지 기준으로 수치를 부여하라.

URL: {url}
제목: {title}
출처: {source}

본문:
{content}

반드시 아래 JSON 스키마만 반환하라. 설명문, 마크다운, 코드블록은 금지한다.

{{
  "topic": "기사의 핵심 주제",
  "summary": "기사 요약 1~2문장",
  "main_frame": "핵심 프레임",
  "stance": "supportive|critical|neutral|mixed",

  "bias_axis": 0,
  "bias_strength": 0,
  "emotionality": 0,
  "source_balance": 50,
  "evidence_quality": 50,

  "content_bias": {{
    "favored_side": "기사 내용상 유리한 쪽. 예: 노조/노동자, 회사/사측, 정부, 야당, 소비자, 플랫폼기업 등",
    "disfavored_side": "기사 내용상 불리한 쪽",
    "axis": 0,
    "strength": 0,
    "reasoning": "기사 내용 편향 근거"
  }},

  "background_bias": {{
    "favored_side": "기사 작성 배경상 유리한 쪽",
    "disfavored_side": "기사 작성 배경상 불리한 쪽",
    "axis": 0,
    "strength": 0,
    "reasoning": "기사 배경 편향 근거"
  }},

  "perspective_vector": {{
    "pro_government": 0,
    "anti_government": 0,
    "pro_business": 0,
    "pro_labor": 0,
    "pro_market": 0,
    "pro_welfare": 0,
    "pro_regulation": 0,
    "anti_regulation": 0,
    "risk_emphasis": 0,
    "benefit_emphasis": 0
  }},

  "loaded_terms": ["편향적 또는 감정적 표현"],
  "missing_perspectives": ["누락된 이해관계자 관점"],
  "reasoning": "최종 수치화 근거"
}}

점수 기준:
- bias_axis: -100~100.
  - 음수: 회사/사측/기업/시장/규제완화/정부비판/비용부담/위험강조 쪽에 유리한 프레임.
  - 양수: 노조/노동자/복지/공공성/규제필요/권리보호/정책확대 쪽에 유리한 프레임.
  - 단, 기사 주제별로 이해관계자를 명확히 정의하고 reasoning에 설명하라.
- bias_strength: 0~100. 프레임이 한쪽으로 기운 강도. 갈등 사안이면 0 금지.
- emotionality: 0~100. 감정적 표현, 위기감, 책임 추궁, 피해 강조의 강도.
- source_balance: 0~100. 이해관계자 균형성. 여러 입장이 실질적으로 균등하게 제시되면 높게.
- evidence_quality: 0~100. 데이터, 인용, 공식 발언, 통계, 맥락 설명의 품질.
- content_bias.axis와 background_bias.axis도 -100~100.
- content_bias.strength와 background_bias.strength도 0~100.
- perspective_vector 각 값은 0~100.

노조/회사 관련 세부 기준:
- 노조 요구, 노동권, 처우 개선, 부당노동행위, 임금 인상, 노동자 피해가 중심이면:
  - pro_labor, pro_welfare, pro_regulation 높게
  - bias_axis 양수
  - main_frame 예: "노조_권리보호", "노동자_피해", "처우개선_요구"
- 회사 손실, 생산 차질, 경영 부담, 불법 파업, 고객 피해, 경쟁력 저하가 중심이면:
  - pro_business, pro_market, anti_regulation, risk_emphasis 높게
  - bias_axis 음수
  - main_frame 예: "회사_경영부담", "파업_피해", "시장_차질"
- 양측이 모두 등장해도 제목과 기사 배경이 어느 쪽에 더 유리한지 반드시 판단하라.
""".strip()


def call_llm_json(
    system_prompt: str,
    user_prompt: str,
    temperature: float = 0.1,
    timeout: int = LLM_TIMEOUT,
) -> Dict:
    refresh_llm_config_from_env()

    if not LLM_API_KEY:
        raise ValueError(
            "OPENROUTER_API_KEY 또는 LLM_API_KEY 환경변수가 필요합니다. "
            "PowerShell 예: $env:OPENROUTER_API_KEY='sk-or-v1-...'"
        )

    if "openrouter.ai" not in LLM_BASE_URL:
        raise ValueError(
            "LLM_BASE_URL은 https://openrouter.ai/api/v1 이어야 합니다."
        )

    url = LLM_BASE_URL.rstrip("/") + "/chat/completions"

    headers = {
        "Authorization": f"Bearer {LLM_API_KEY}",
        "Content-Type": "application/json",
        "HTTP-Referer": "http://localhost",
        "X-Title": "news-bias-analyzer",
    }

    payload = {
        "model": LLM_MODEL,
        "messages": [
            {
                "role": "system",
                "content": system_prompt,
            },
            {
                "role": "user",
                "content": user_prompt,
            },
        ],
        "temperature": temperature,
    }

    if USE_RESPONSE_FORMAT:
        payload["response_format"] = {
            "type": "json_object",
        }

    response = requests.post(
        url,
        headers=headers,
        json=payload,
        timeout=timeout,
    )

    try:
        data = response.json()
    except Exception:
        print("=" * 80)
        print("LLM NON-JSON RESPONSE")
        print("status:", response.status_code)
        print(response.text)
        print("=" * 80)
        response.raise_for_status()
        raise

    if response.status_code >= 400:
        if USE_RESPONSE_FORMAT and "response_format" in json.dumps(data, ensure_ascii=False):
            retry_payload = dict(payload)
            retry_payload.pop("response_format", None)

            retry_response = requests.post(
                url,
                headers=headers,
                json=retry_payload,
                timeout=timeout,
            )

            retry_data = retry_response.json()

            if retry_response.status_code >= 400:
                print(
                    json.dumps(
                        retry_data,
                        ensure_ascii=False,
                        indent=2,
                    )
                )
                retry_response.raise_for_status()

            content = retry_data["choices"][0]["message"]["content"]

            return json_loads_safely(content)

        print("=" * 80)
        print("LLM API ERROR")
        print("status:", response.status_code)
        print(
            json.dumps(
                data,
                ensure_ascii=False,
                indent=2,
            )
        )
        print("=" * 80)
        response.raise_for_status()

    if "error" in data:
        raise RuntimeError(
            "LLM response has error: "
            + json.dumps(
                data,
                ensure_ascii=False,
            )
        )

    if "choices" not in data or not data.get("choices"):
        raise RuntimeError(
            "LLM response has no choices: "
            + json.dumps(
                data,
                ensure_ascii=False,
            )
        )

    content = data["choices"][0].get("message", {}).get("content", "")

    if not content:
        raise RuntimeError(
            "LLM response has no content: "
            + json.dumps(
                data,
                ensure_ascii=False,
            )
        )

    return json_loads_safely(content)


def analyze_article(article: Dict) -> Dict:
    """
    recommender.py가 import해서 사용하는 표준 함수.

    입력:
    {
      "url": "...",
      "title": "...",
      "source": "...",
      "content": "..."
    }

    출력:
    recommender.py가 요구하는 analysis dict
    """
    raw_analysis = call_llm_json(
        system_prompt=ANALYZER_SYSTEM_PROMPT,
        user_prompt=build_analysis_prompt(article),
        temperature=0.1,
    )

    normalized = normalize_analysis(raw_analysis)

    calibrated = calibrate_analysis_with_article(
        normalized,
        article,
    )

    return calibrated


def analyze_url(
    news_url: str,
    delay: float = 1.0,
) -> Dict:
    article = fetch_url_article(
        news_url,
        delay=delay,
    )

    return analyze_article(article)


def print_analysis_summary(
    result: Dict,
    output_path: str = "",
) -> None:
    print(
        json.dumps(
            {
                "saved": output_path or None,
                "topic": result.get("topic"),
                "summary": result.get("summary"),
                "main_frame": result.get("main_frame"),
                "stance": result.get("stance"),
                "bias_axis": result.get("bias_axis"),
                "bias_strength": result.get("bias_strength"),
                "emotionality": result.get("emotionality"),
                "source_balance": result.get("source_balance"),
                "evidence_quality": result.get("evidence_quality"),
                "content_bias": result.get("content_bias"),
                "background_bias": result.get("background_bias"),
            },
            ensure_ascii=False,
            indent=2,
        )
    )


def main() -> None:
    parser = argparse.ArgumentParser()

    parser.add_argument(
        "--url",
        required=True,
        help="분석할 뉴스 URL",
    )

    parser.add_argument(
        "--output",
        default="analysis_result.json",
        help="출력 JSON 파일",
    )

    parser.add_argument(
        "--crawl-delay",
        type=float,
        default=1.0,
    )

    args = parser.parse_args()

    result = analyze_url(
        args.url,
        delay=args.crawl_delay,
    )

    with open(
        args.output,
        "w",
        encoding="utf-8",
    ) as file:
        json.dump(
            result,
            file,
            ensure_ascii=False,
            indent=2,
        )

    print_analysis_summary(
        result,
        args.output,
    )


if __name__ == "__main__":
    main()