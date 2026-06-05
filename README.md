# crawler.py -> analyzer.py -> recommender.py

# News Bias Analyzer & Recommender

사용자가 입력한 뉴스 기사 URL을 **크롤링(crawler)** 하고, 기사 내용과 기사 작성 배경을 기준으로 **편향성을 수치화(analyzer)** 한 뒤, DB 내부 기사 및 필요 시 네이버 검색 결과 중 **다른 관점의 추천 기사(recommender)** 를 찾는 파이프라인입니다.

---

## 1. 전체 구조

```text
사용자 뉴스 URL
→ crawler.py
→ analyzer.py
→ recommender.py
```

### 처리 단계 요약

1. **crawler.py**
   - URL 검증
   - HTML 요청
   - 기사 제목(title), 출처(source), 본문(content) 추출
   - 본문 전처리

2. **analyzer.py**
   - crawler.py가 제공한 기사 본문 분석
   - 기사 핵심 주제(topic) 요약
   - 기사 자체 내용의 편향(content bias) 분석
   - 기사 작성 배경의 편향(background bias) 분석
   - 편향 수치와 벡터(perspective vector) 생성

3. **recommender.py**
   - analyzer.py가 생성한 편향 수치를 바탕으로 추천 기준 기사(target) 분석
   - DB 기사와 비교하여 B&B(Branch and Bound) 기반 추천
   - DB 추천이 부족하면 네이버 뉴스 검색으로 후보 확장

---

## 2. 각 파일 명세

---

## `crawler.py`

### 역할
사용자가 입력한 뉴스 기사 URL에서 기사 메타데이터와 본문을 추출합니다.

### 입력
- 뉴스 URL

### 출력
`crawl_news()`는 아래 형식의 dict를 반환합니다.

```python
{
    "url": "뉴스 URL",
    "title": "기사 제목",
    "source": "언론사 또는 도메인",
    "raw_content": "원문 추출 텍스트",
    "content": "전처리 완료 본문",
    "crawl_status": "success|no_content|timeout|http_error_xxx|request_error|parse_error",
    "crawled_at": "ISO timestamp"
}
```

### 주요 함수

#### `crawl_news(news_url, delay=1.0, timeout=12, max_chars=12000)`
- URL을 검증합니다.
- 요청을 보내 HTML을 가져옵니다.
- 제목, 출처, 본문을 추출합니다.
- 전처리 후 dict를 반환합니다.

#### `extract_title(soup)`
- `og:title`, `twitter:title`, `<title>` 순서로 제목을 추출합니다.

#### `extract_source(url, soup)`
- `og:site_name` 또는 도메인 이름으로 출처를 추출합니다.

#### `extract_content(url, html)`
- 네이버 뉴스 전용 selector 우선 사용
- 실패 시 generic selector 기반 본문 추출

#### `preprocess_content(text, max_chars=12000)`
- 기자 이메일/광고/저작권 문구 제거
- 중복 라인 제거
- 공백 정리
- 길이 제한 적용

### CLI 실행 예시

```bash
python crawler.py "https://n.news.naver.com/mnews/article/001/0016100464?sid=102" --output crawling_data.txt
```

### 출력 파일
`crawling_data.txt`
- URL
- 제목
- 출처
- 크롤링 상태
- 본문 텍스트

---

## `analyzer.py`

### 역할
crawler.py가 제공한 기사 내용을 바탕으로 **기사의 주제와 편향성을 강하게 분석**하고,
recommender.py가 사용할 수 있는 JSON 형식으로 변환합니다.

### 입력
- URL (`--url`)
- 내부적으로는 `crawl_news()` 결과를 사용

### 출력
최종 분석 결과 JSON:

```python
{
    "topic": "기사의 핵심 주제",
    "summary": "기사 요약 1~2문장",
    "main_frame": "핵심 프레임",
    "stance": "supportive|critical|neutral|mixed",
    "bias_axis": 0,
    "bias_strength": 0,
    "emotionality": 0,
    "source_balance": 50,
    "evidence_quality": 50,
    "perspective_vector": {
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
    },
    "content_bias": {
        "favored_side": "기사 내용상 유리한 쪽",
        "disfavored_side": "기사 내용상 불리한 쪽",
        "axis": 0,
        "strength": 0,
        "reasoning": "..."
    },
    "background_bias": {
        "favored_side": "기사 작성 배경상 유리한 쪽",
        "disfavored_side": "기사 작성 배경상 불리한 쪽",
        "axis": 0,
        "strength": 0,
        "reasoning": "..."
    },
    "loaded_terms": [],
    "missing_perspectives": [],
    "reasoning": "최종 수치화 근거"
}
```

### 주요 함수

#### `fetch_url_article(news_url, delay=1.0)`
- 내부적으로 `crawl_news()` 호출
- 성공하면 `{url, title, source, content}` 구조의 article dict 반환
- 크롤러 사용 불가 시 requests fallback 사용

#### `build_analysis_prompt(article)`
- LLM에 전달할 분석 프롬프트 생성
- 기사 내용 편향(content bias)과 기사 작성 배경 편향(background bias)을 모두 분석하도록 지시

#### `call_llm_json(system_prompt, user_prompt, temperature=0.1)`
- OpenRouter API 호출
- JSON 응답만 허용
- `response_format` 미지원 시 fallback 재시도

#### `normalize_analysis(analysis)`
- LLM 결과를 추천기가 사용할 형식으로 정규화
- 0~100 / -100~100 범위 보정

#### `calibrate_analysis_with_article(analysis, article)`
- LLM이 지나치게 중립적으로 분석한 경우 최소 보정
- 특히 **노사 갈등, 정책 대립, 위험/혜택 프레임**을 강제로 반영

#### `analyze_article(article)`
- recommender.py가 import해 사용하는 표준 분석 함수
- 입력 article dict → 편향 분석 dict 반환

#### `analyze_url(news_url)`
- URL 입력 → 크롤링 → 분석까지 한 번에 수행

### 환경변수

```env
OPENROUTER_API_KEY=sk-or-v1-...
LLM_BASE_URL=https://openrouter.ai/api/v1
LLM_MODEL=openrouter/free
```

### CLI 실행 예시

```bash
python analyzer.py --url "https://n.news.naver.com/mnews/article/001/0016100464?sid=102" --output analysis_result.json
```

---

## `recommender.py`

### 역할
analyzer.py가 생성한 편향 수치를 사용해,
DB 내부 기사 또는 네이버 검색 결과 중에서 **다른 관점의 추천 기사**를 찾습니다.

### 입력
- CSV 파일 (`--input`)
- 사용자 입력 URL (`--url`) 또는 CSV 내부 행 인덱스 (`--target-idx`)

### 출력
추천 결과 JSON:

```python
{
    "target_idx": 0,
    "target_url": "...",
    "target_title": "...",
    "target_analysis": {...},
    "best_recommendation": {...},
    "db_best": {...},
    "search_best": {...},
    "search_used": false,
    "evaluated_count": 0,
    "llm_calls": 0,
    "optimality_gap": 0.0,
    "gap_threshold": 0.1,
    "max_llm_calls": 5,
    "stop_reason": "optimality_gap|llm_call_limit|exhausted",
    "evaluated_candidates": [...],
    "created_at": "..."
}
```

### 주요 함수

#### `append_or_find_target_url(df, news_url)`
- 입력 URL이 DB에 있으면 기존 행을 target으로 사용
- 없으면 `crawler.py`로 크롤링 후 새 행으로 추가

#### `get_or_create_analysis(row, budget, cache)`
- 행에 `analysis_json`이 있으면 그것을 사용
- 없으면 `analyzer.py`를 호출하여 분석 생성

#### `enrich_row_with_analysis_hints(row, analysis)`
- **중요 수정 포인트**
- analyzer가 뽑은 `topic`, `main_frame`, `stance`를 target/candidate row 메타데이터에 반영
- 이 덕분에 입력 URL 기사도 실제 이슈와 프레임 기준으로 DB 기사와 relevance 비교 가능

#### `recommendation_score(...)`
- 추천 점수 계산

구성 요소:
- relevance_score
- bias_distance_score
- quality_score
- frame_diff_bonus
- relevance_penalty

#### `run_bnb_on_candidates(...)`
- Branch and Bound(B&B) 탐색 수행
- branch별 upper bound 계산 후 유망한 후보군부터 평가
- analyzer 호출 예산(max 5회)을 지키며 탐색

#### `naver_search_news(query, display=10)`
- 네이버 뉴스 API로 추가 후보 확보
- DB 추천이 기준 미달일 때만 사용

#### `branch_and_bound_recommend(...)`
- 추천 파이프라인 메인 함수
- target 분석
- DB 후보 탐색
- 필요 시 네이버 검색 후보 탐색
- 최종 추천 결과 반환

### 점수 계산 공식

```text
recommendation_score =
    0.50 * relevance_score
  + 0.30 * bias_distance_score
  + 0.15 * quality_score
  + 0.05 * frame_diff_bonus
  - relevance_penalty
```

### B&B 종료 조건
- optimality gap <= 10%
- analyzer.py 호출 횟수 >= 5회

### CLI 실행 예시

#### 1) DB 행 기준 추천
```bash
python recommender.py --input issue_news_db_merged.csv --target-idx 0 --output recommendation_result.json
```

#### 2) 사용자 URL 기준 추천
```bash
python recommender.py --input issue_news_db_merged.csv --url "https://n.news.naver.com/mnews/article/001/0016100464?sid=102" --output recommendation_result.json
```

#### 3) 네이버 검색 없이 DB만 사용
```bash
python recommender.py --input issue_news_db_merged.csv --target-idx 0 --output recommendation_result.json --no-naver
```

### 네이버 API 환경변수

```env
NAVER_CLIENT_ID=...
NAVER_CLIENT_SECRET=...
```

---

## 3. 파이프라인 동작 흐름

### 1단계: 사용자 URL 입력
사용자가 임의의 뉴스 기사 URL을 입력합니다.

### 2단계: crawler.py 실행
`crawl_news()`가 URL에서:
- title
- source
- content
를 추출합니다.

### 3단계: analyzer.py 실행
추출된 기사 dict를 LLM이 분석해:
- 주제(topic)
- 프레임(main_frame)
- 편향축(bias_axis)
- 편향 강도(bias_strength)
- 내용 편향(content_bias)
- 배경 편향(background_bias)
- 관점 벡터(perspective_vector)
를 생성합니다.

### 4단계: recommender.py 실행
- analyzer 결과를 **추천 기준 기사(target)** 로 사용합니다.
- target의 `topic`, `main_frame`, `stance`를 row metadata에 반영합니다.
- DB 후보와 편향 거리 및 주제 관련성을 비교합니다.
- 적절한 후보가 없으면 네이버 뉴스 검색으로 후보를 확장합니다.
- B&B 탐색으로 최종 추천 기사를 선택합니다.

---

## 4. 실행 순서 예시

### 4-1. 크롤러 단독 점검

```bash
python crawler.py "https://n.news.naver.com/mnews/article/001/0016100464?sid=102" --output crawling_data.txt
```

확인 항목:
- `crawl_status == success`
- `title` 존재
- `source` 존재
- `content_length > 0`

---

### 4-2. 애널라이저 단독 점검

```bash
python analyzer.py --url "https://n.news.naver.com/mnews/article/001/0016100464?sid=102" --output analysis_result.json
```

확인 항목:
- `topic`
- `summary`
- `main_frame`
- `bias_axis`, `bias_strength`
- `perspective_vector`
- `content_bias`, `background_bias`

---

### 4-3. 리커맨더 DB 추천 점검

```bash
python recommender.py --input issue_news_db_merged.csv --target-idx 0 --output recommendation_result.json --no-naver
```

확인 항목:
- `best_title`
- `best_url`
- `best_score`

---

### 4-4. 전체 파이프라인 점검

```bash
python recommender.py --input issue_news_db_merged.csv --url "https://n.news.naver.com/mnews/article/001/0016100464?sid=102" --output recommendation_result.json
```

확인 항목:
- crawler → analyzer → recommender 순서로 정상 연결
- target 분석값이 추천 점수 계산에 반영
- DB 부족 시 `search_used == true`

---

## 5. 수정된 핵심 개선점

### 1) 입력 URL 기사(target)에 analyzer 결과 반영
기존에는 입력 URL target이 다음처럼 고정 메타데이터를 가졌습니다.

```python
issue = "input_url"
frame = "input_article"
```

이렇게 되면 analyzer가 추출한 실제 주제(`topic`)와 프레임(`main_frame`)이
relevance 계산에 반영되지 않았습니다.

수정 후에는 `enrich_row_with_analysis_hints()`가 target row를 보정하여,
입력 URL 기사도 DB 기사와 같은 기준으로 비교됩니다.

### 2) 네이버 검색 후보에도 analyzer 결과 힌트 반영 가능 구조 확보
검색 후보는 초기값으로 `issue=naver_search`, `frame=search_candidate`를 가지지만,
후보 분석 후 `main_frame`와 `topic` 정보를 row metadata에 반영할 수 있도록 구조를 정리했습니다.

### 3) crawler.py가 title/source/content를 모두 반환
analyzer.py가 제목과 출처까지 활용해 프레임 분석할 수 있게 개선했습니다.

---

## 6. 필수 환경변수

```env
OPENROUTER_API_KEY=sk-or-v1-...
LLM_BASE_URL=https://openrouter.ai/api/v1
LLM_MODEL=openrouter/free
NAVER_CLIENT_ID=...
NAVER_CLIENT_SECRET=...
```

---

## 7. 향후 개선 포인트

- `content_bias`와 `background_bias`를 추천 점수에 직접 반영
- 추천 이유를 자연어 설명으로 생성
- topic별 편향축을 더 세분화
- 검색 후보에도 analyzer 결과를 branch 생성 이전에 반영
- article body extraction 정확도 개선