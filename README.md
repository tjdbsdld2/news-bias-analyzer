# NewSight

뉴스 기사 URL을 입력하면 기사 본문을 추출하고, LLM 또는 mock 데이터로 관점 분석을 수행한 뒤, CSV 기반 추천 DB와 외부 검색 fallback을 이용해 다른 관점의 기사를 제안하는 Streamlit 앱입니다.

## 주요 기능

- `Streamlit` 화면에서 뉴스 URL 입력
- `trafilatura`로 기사 제목/본문/언론사/날짜 추출
- `OpenAI`, `OpenRouter`, 또는 `Anthropic` API로 기사 관점 분석
- API 키가 없을 때도 `mock 분석 결과`로 앱 실행 가능
- `articles_curated.csv`와 `articles_expanded.csv` 기반 다른 관점 기사 추천
- DB에 추천 기사가 없을 때 외부 관련 기사 후보 검색
- 외부 기사 후보에 대해 LLM이 왜 비교해볼 만한지 짧은 가이드 제공

## 파일 구조

```text
news-bias-analyzer/
├── app.py
├── analyzer.py
├── crawler.py
├── db.py
├── ingest_articles.py
├── prompts.py
├── recommender.py
├── searcher.py
├── scripts/
│   ├── collect_urls.py
│   ├── tag_articles.py
│   └── build_article_db.py
├── requirements.txt
└── data/
    ├── issue_keywords.csv
    ├── raw_urls.csv
    ├── articles.csv
    ├── raw_merged.csv
    ├── articles_expanded.csv
    ├── articles_curated.csv
    └── articles.db   # 초기 SQLite 실험용 파일
```

## 1. 설치 방법

Python 3.10 이상을 권장합니다.

```bash
pip install -r requirements.txt
```

## 2. 환경변수 설정

API 키가 없어도 앱은 실행됩니다. 이 경우 mock 분석 결과가 표시됩니다.

`.env` 파일 예시:

```env
GOOGLE_API_KEY=your_google_ai_studio_key
GOOGLE_MODEL=models/gemini-flash-lite-latest

# 또는
OPENAI_API_KEY=your_openai_api_key
OPENAI_MODEL=gpt-4o-mini

# 또는
OPENROUTER_API_KEY=your_openrouter_api_key
OPENROUTER_MODEL=openai/gpt-4o-mini
# 선택: OpenRouter 대시보드용 사이트 주소
OPENROUTER_HTTP_REFERER=https://example.com

# 또는
ANTHROPIC_API_KEY=your_anthropic_api_key
ANTHROPIC_MODEL=claude-3-5-sonnet-latest

# URL 수집 시 네이버 뉴스 검색 API 사용
NAVER_CLIENT_ID=your_naver_client_id
NAVER_CLIENT_SECRET=your_naver_client_secret
```

Google, OpenAI, OpenRouter, Anthropic 중 하나만 설정해도 됩니다.
`GOOGLE_API_KEY`와 `GEMINI_API_KEY`는 둘 다 지원하며, Google 키가 있으면 그 경로를 우선 사용합니다.

`.env` 파일은 절대 GitHub에 올리지 마세요.

## 3. 실행 방법

```bash
streamlit run app.py
```

브라우저가 열리면 뉴스 기사 URL을 입력하고 `뉴스 관점 분석 시작` 버튼을 누르면 됩니다.

## 4. 동작 흐름

1. `app.py`에서 URL을 입력받습니다.
2. `crawler.py`의 `fetch_article(url)`이 기사 본문을 추출합니다.
3. `analyzer.py`의 `analyze_article(article)`이 분석 결과 JSON을 반환합니다.
4. `recommender.py`가 먼저 `data/articles_curated.csv`에서 검수된 추천 기사를 찾습니다.
5. 없으면 `data/articles_expanded.csv`에서 자동 태깅 기반 추천 기사를 찾습니다.
6. 그래도 없으면 `searcher.py`가 외부 관련 기사 후보를 찾습니다.
7. `analyzer.py`가 외부 기사 후보를 어떻게 비교하면 좋을지 짧은 가이드를 생성합니다.

## 5. 기사 URL 일괄 수집

`data/article_urls.csv`에 기사 URL을 적어두고 아래 명령으로 SQLite DB 실험용 데이터를 넣을 수 있습니다.

```bash
python ingest_articles.py
```

처음 몇 개만 시험하고 싶다면:

```bash
python ingest_articles.py --limit 3
```

## 6. 추천 DB 자동 구축

추천용 기사 DB를 CSV 기반 파이프라인으로 자동 구축할 수 있습니다.

### 1. 패키지 설치

```bash
pip install -r requirements.txt
```

### 2. .env 설정

아래 중 가능한 키를 설정합니다.

```env
NAVER_CLIENT_ID=...
NAVER_CLIENT_SECRET=...

GOOGLE_API_KEY=...
# 또는
GEMINI_API_KEY=...
# 또는
OPENAI_API_KEY=...
# 또는
OPENROUTER_API_KEY=...
# 또는
ANTHROPIC_API_KEY=...
```

### 3. 이슈별 검색어 CSV 확인

기본 입력 파일:

```text
data/issue_keywords.csv
```

형식:

```csv
issue,keyword
```

### 4. URL 후보 수집

```bash
python scripts/collect_urls.py
```

특정 이슈만 기존 결과에 덧붙이고 싶다면:

```bash
python scripts/collect_urls.py \
  --issue "6·3 지방선거 투표용지 부족 / 선거관리 논란" \
  --append
```

동작 순서:
- `NAVER_CLIENT_ID`, `NAVER_CLIENT_SECRET`가 있으면 네이버 뉴스 검색 API 사용
- 없거나 실패하면 Google News RSS fallback 사용
- 결과는 `data/raw_urls.csv`에 저장

### 5. 기사 본문 추출 및 LLM 자동 태깅

```bash
python scripts/tag_articles.py
```

특정 이슈만 기존 `articles.csv`에 이어서 태깅하고 싶다면:

```bash
python scripts/tag_articles.py \
  --issue "6·3 지방선거 투표용지 부족 / 선거관리 논란" \
  --append
```

동작:
- `data/raw_urls.csv`를 읽음
- 기사 본문을 추출
- `issue_tags`, `frame`, `tone`, `primary_voice`, `memo` 자동 태깅
- 결과를 `data/articles.csv`에 저장
- `GOOGLE_API_KEY` 또는 `GEMINI_API_KEY`가 있으면 Gemini 경로를 우선 사용

### 6. 추천용 DB 정제

```bash
python scripts/build_article_db.py --input data/articles_combined_backfilled.csv --max-per-issue 8
```

동작:
- `data/raw_merged.csv`: 정제 전 통합 원본 보관
- `data/articles_expanded.csv`: 자동 수집 + 자동 태깅 기반 확장 DB
- `data/articles_curated.csv`: 발표용 검수본 성격의 고품질 DB
- URL 중복 제거, frame/issue_tags 표기 통일, 발표용 이슈만 유지
- 기존 팀원 DB(`db_final.csv`) 기사 중 현재 8개 시연 이슈에 강하게 맞는 기사도 보수적으로 재편입
- curated DB는 issue별 frame 다양성을 우선 유지하면서 기본 8건까지 선별하고, 필요한 경우 검수된 legacy 기사 1건을 보너스로 남길 수 있음

### 7. Streamlit 실행

```bash
streamlit run app.py
```

### 출력 파일

- `data/raw_urls.csv`: 검색 결과 후보 URL 목록
- `data/articles.csv`: 본문 추출 + 자동 태깅 결과
- `data/raw_merged.csv`: 정제 전 통합 원본
- `data/articles_expanded.csv`: 자동 태깅 + 일부 legacy 재정렬이 반영된 확장 추천 DB
- `data/articles_curated.csv`: 발표용 검수 추천 DB

## 7. 주의사항

- 일부 뉴스 사이트는 크롤링 방지 정책 때문에 본문 추출이 실패할 수 있습니다.
- 외부 기사 후보 검색은 네트워크 상태와 RSS 제공 여부에 따라 결과가 없을 수 있습니다.
- 현재 추천 기능은 `articles_curated.csv -> articles_expanded.csv -> 외부 검색 fallback` 순서로 동작합니다.
- 현재 시연용 curated DB는 기사 수를 너무 작게 고정하지 않고, coverage를 위해 expanded DB를 함께 사용합니다.
- 추천 DB 구축 스크립트는 API 키가 없으면 mock 태깅 결과로도 끝까지 실행됩니다.
- 실제 서비스 수준의 추천 품질을 위해서는 더 많은 기사 데이터와 정교한 태그 설계가 필요합니다.
- 이 프로젝트의 분석 결과는 절대적 판정이 아니라 비판적 읽기를 돕는 참고 자료입니다.

## 8. 아직 구현되지 않은 부분

- 대규모 기사 수집 자동화
- 실제 뉴스 데이터셋 기반 추천 고도화
- 사용자 피드백 저장
- 배포 및 로그인 기능

## 9. 빠른 체크

API 키가 없더라도 아래 명령으로 바로 시연할 수 있습니다.

```bash
pip install -r requirements.txt
streamlit run app.py
```
