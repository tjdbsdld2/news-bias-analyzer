# NewSight MVP

뉴스 기사 URL을 입력하면 기사 본문을 추출하고, LLM 또는 mock 데이터로 관점 분석을 수행한 뒤, SQLite 샘플 DB에서 다른 프레임의 기사를 추천하는 Streamlit 앱입니다.

## 주요 기능

- `Streamlit` 화면에서 뉴스 URL 입력
- `trafilatura`로 기사 제목/본문/언론사/날짜 추출
- `OpenAI` 또는 `Anthropic` API로 기사 관점 분석
- API 키가 없을 때도 `mock 분석 결과`로 앱 실행 가능
- `SQLite` 샘플 기사 DB에서 다른 관점 기사 추천

## 파일 구조

```text
news-bias-analyzer/
├── app.py
├── analyzer.py
├── crawler.py
├── db.py
├── prompt.py
├── prompts.py
├── recommender.py
├── requirements.txt
└── data/
    └── articles.db   # 첫 실행 시 자동 생성
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
OPENAI_API_KEY=your_openai_api_key
OPENAI_MODEL=gpt-4o-mini

# 또는
ANTHROPIC_API_KEY=your_anthropic_api_key
ANTHROPIC_MODEL=claude-3-5-sonnet-latest
```

둘 중 하나만 설정해도 됩니다.

## 3. 실행 방법

```bash
streamlit run app.py
```

브라우저가 열리면 뉴스 기사 URL을 입력하고 `뉴스 관점 분석 시작` 버튼을 누르면 됩니다.

## 4. 동작 흐름

1. `app.py`에서 URL을 입력받습니다.
2. `crawler.py`의 `fetch_article(url)`이 기사 본문을 추출합니다.
3. `analyzer.py`의 `analyze_article(article)`이 분석 결과 JSON을 반환합니다.
4. `recommender.py`의 `recommend_opposite(analysis)`가 추천 기사를 찾습니다.
5. `db.py`가 SQLite DB를 초기화하고 샘플 기사를 자동으로 넣습니다.

## 5. 주의사항

- 일부 뉴스 사이트는 크롤링 방지 정책 때문에 본문 추출이 실패할 수 있습니다.
- 현재 추천 기능은 `샘플 SQLite DB`를 기반으로 동작합니다.
- 실제 서비스 수준의 추천 품질을 위해서는 더 많은 기사 데이터와 정교한 태그 설계가 필요합니다.
- 이 프로젝트의 분석 결과는 절대적 판정이 아니라 비판적 읽기를 돕는 참고 자료입니다.

## 6. 아직 구현되지 않은 부분

- 대규모 기사 수집 자동화
- 실제 뉴스 데이터셋 기반 추천 고도화
- 사용자 피드백 저장
- 배포 및 로그인 기능

## 7. 빠른 체크

API 키가 없더라도 아래 명령으로 바로 시연할 수 있습니다.

```bash
pip install -r requirements.txt
streamlit run app.py
```
