# NewSight Flask App

`news/` 폴더는 `NewSight`의 Flask 기반 웹 앱입니다.  
기존 `songmi` 브랜치의 서비스형 UI 위에, `seoyoon` 브랜치에서 정리한 기사 추출, LLM 분석, 로컬 추천 DB, 외부 기사 fallback 로직을 통합한 버전입니다.

## 핵심 구성

- `app.py`
  Flask 엔트리포인트입니다. 메인 페이지 렌더링과 `/api/analyze` API를 담당합니다.
- `crawler.py`
  기사 URL에서 제목, 본문, 언론사, 날짜를 추출합니다.
- `analyzer.py`
  기사 분석, 외부 후보 기사 설명, mock fallback을 담당합니다.
- `recommender.py`
  `articles_curated.csv` -> `articles_expanded.csv` 순서로 추천합니다.
- `searcher.py`
  로컬 추천 DB에 적절한 후보가 없을 때 Google News RSS 기반 외부 기사 후보를 찾습니다.
- `prompts.py`
  분석 프롬프트와 공통 frame 후보를 정의합니다.
- `data/articles_curated.csv`
  사람이 검수한 고품질 추천 DB입니다.
- `data/articles_expanded.csv`
  자동 수집/자동 태깅 기반의 확장 추천 DB입니다.
- `templates/index.html`
  NewSight 메인 페이지 템플릿입니다.
- `static/app.css`
  에디토리얼 스타일의 UI를 담당합니다.
- `static/app.js`
  URL 입력, API 호출, 결과 렌더링을 담당합니다.

## 추천 흐름

1. 사용자가 기사 URL을 입력합니다.
2. `crawler.py`가 기사 본문을 추출합니다.
3. `analyzer.py`가 기사 요약, frame, tone, primary_voice, issue_tags 등을 생성합니다.
4. `recommender.py`가 먼저 `articles_curated.csv`에서 다른 프레임 기사를 찾습니다.
5. 없으면 `articles_expanded.csv`에서 한 번 더 찾습니다.
6. 그래도 없으면 `searcher.py`가 외부 관련 기사 후보를 제시합니다.

UI에서는 추천 출처를 구분해서 보여줍니다.

- `검수된 다른 관점 추천 기사`
- `자동 태깅 기반 관련 관점 기사`
- `외부 관련 기사 후보`

## 실행 방법

### 1. 가상환경 생성

```bash
python3 -m venv .venv
```

### 2. 가상환경 활성화

```bash
source .venv/bin/activate
```

### 3. 패키지 설치

```bash
pip install -r requirements.txt
```

### 4. `.env` 파일 준비

`news/` 폴더 또는 프로젝트 루트에 `.env` 파일을 두고 아래 값 중 필요한 것을 설정합니다.

```env
PORT=5000
FLASK_ENV=development

GOOGLE_API_KEY=...
GOOGLE_MODEL=models/gemini-flash-lite-latest

OPENROUTER_API_KEY=...
OPENROUTER_MODEL=openai/gpt-4o-mini
OPENROUTER_HTTP_REFERER=https://newsight.local

OPENAI_API_KEY=...
OPENAI_MODEL=gpt-4o-mini

ANTHROPIC_API_KEY=...
ANTHROPIC_MODEL=claude-3-5-sonnet-latest
```

여러 키를 동시에 넣어도 되지만, 현재 코드는 아래 우선순위로 사용합니다.

1. `GOOGLE_API_KEY` 또는 `GEMINI_API_KEY`
2. `OPENROUTER_API_KEY`
3. `OPENAI_API_KEY`
4. `ANTHROPIC_API_KEY`
5. 없으면 mock 결과

## 실행

```bash
cd /Users/choiseoyoon/news-bias-analyzer/news
python3 app.py
```

기본 포트는 `5000`입니다. 이미 사용 중이면 다른 포트로 실행할 수 있습니다.

```bash
PORT=5001 python3 app.py
```

브라우저에서 아래 주소로 접속합니다.

- `http://localhost:5000`
- 또는 지정한 포트

## 현재 반영된 개선점

- `NewsPrism` 브랜딩 제거 후 `NewSight`로 통일
- 서비스형 Flask UI 유지
- Streamlit에서 다듬었던 분석 설명 구조 반영
- 본문 읽기 보조 하이라이트 및 hover 설명 반영
- `curated -> expanded -> external fallback` 추천 계층 반영
- `FRAME_CANDIDATES` 기반 frame 체계 통일

## 주의 사항

- `.env` 파일은 Git에 올리지 마세요.
- 기사 본문 추출은 언론사 구조에 따라 성공률 차이가 있을 수 있습니다.
- 외부 기사 후보는 “반대 프레임으로 검증 완료된 추천”이 아니라 비교 읽기 후보입니다.
- LLM API 키가 없거나 호출이 실패하면 일부 기능은 mock 결과로 대체됩니다.

## 시연 전 예외 케이스 점검

아래 케이스는 시연 전에 한 번씩 넣어보고, 앱이 죽지 않고 안내 메시지를 보여주는지 확인하는 것을 권장합니다.

1. 빈 값 입력
2. `hello` 같은 URL이 아닌 문자열 입력
3. `https://example.com` 입력
4. 존재하지 않는 URL 입력
5. 네이버 메인처럼 기사 아닌 페이지 입력
6. 본문 추출이 어려운 기사 URL 입력
7. DB와 전혀 관련 없는 주제의 기사 입력
8. LLM API 키 없이 실행
9. `articles_curated.csv` 또는 `articles_expanded.csv`를 잠시 치운 상태에서 실행
10. 외부 RSS 검색이 실패하는 환경에서 실행

기대 동작:

- 서버가 500으로 종료되지 않습니다.
- 버튼이 계속 `분석 중...` 상태로 멈추지 않습니다.
- 본문 추출 실패 시 자연스러운 안내 문구가 나옵니다.
- 로컬 추천 DB가 비어 있거나 실패하면 외부 기사 후보 탐색으로 넘어갑니다.
- 외부 후보도 없으면 “왜 결과가 비는지”를 설명하는 문구가 남습니다.
