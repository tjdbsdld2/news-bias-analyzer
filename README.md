# NewSight

뉴스 기사 URL을 입력하면 기사 속 **프레임, 중심 목소리, 읽기 포인트, 함께 비교해볼 기사**를 보여주는 AI 미디어 리터러시 웹서비스입니다.

NewSight는 기사를 `편향/중립`으로 단정하기보다, 기사 안에서 **무엇이 강조되는지**, **누구의 말이 중심에 놓이는지**, **무엇이 덜 다뤄지는지**를 비교해서 읽도록 돕는 것을 목표로 합니다.

## 주요 기능

* **기사 URL 분석**

  * 뉴스 기사 URL을 입력하면 기사 제목, 본문, 주요 프레임, 중심 목소리, 읽기 포인트를 분석합니다.

* **본문 읽기 보조**

  * 본문 미리보기에서 강조된 문장에 커서를 올리면, 해당 문장이 기사 안에서 어떤 역할을 하는지 확인할 수 있습니다.

* **함께 비교해볼 기사**

  * 같은 이슈를 다루지만 다른 쟁점이나 관점이 드러나는 기사를 함께 보여줍니다.

* **이슈별 관점 보기**

  * 시연용 예시 기사 데이터를 바탕으로, 같은 이슈를 서로 다른 시선으로 읽어보는 화면입니다.

## 화면 구성

NewSight는 상단 탭 기준으로 구성됩니다.

* **홈**

  * 서비스 소개와 주요 기능 요약
* **분석하기**

  * 기사 URL 입력, AI 분석, 본문 읽기 보조, 비교 기사 확인
* **이슈별 관점 보기**

  * 예시 기사 데이터를 이용한 관점 비교 화면
* **분석 기준**

  * 뉴스를 읽을 때 확인할 기준 설명
* **이용 가이드**

  * 분석 결과를 활용하는 방법 안내

---

# 실행 방법

## 1. 저장소 받기

```bash
git clone https://github.com/tjdbsdld2/news-bias-analyzer.git
cd news-bias-analyzer
```

## 2. 가상환경 생성 및 활성화

### macOS / Linux

```bash
python3 -m venv .venv
source .venv/bin/activate
```

### Windows PowerShell

```powershell
python -m venv .venv
Set-ExecutionPolicy -Scope CurrentUser -ExecutionPolicy RemoteSigned -Force
.\.venv\Scripts\Activate.ps1
```

### Windows CMD

```cmd
python -m venv .venv
.\.venv\Scripts\activate.bat
```

### Git Bash / WSL

```bash
python3 -m venv .venv
source .venv/bin/activate
```

## 3. 패키지 설치

```bash
pip install -r requirements.txt
```

## 4. `.env` 파일 생성

프로젝트 루트 폴더에 `.env` 파일을 생성합니다.

### Windows 사용자: VS Code에서 파일 생성

1. VS Code 왼쪽 **Explorer** 패널에서 `news-bias-analyzer` 폴더를 엽니다.
2. **New File** 선택
3. 파일명: `.env` 입력
4. 아래 내용을 복사하여 붙여넣기

```env
PORT=5000
FLASK_ENV=development

GOOGLE_API_KEY=YOUR_API_KEY_HERE
GOOGLE_MODEL=models/gemini-flash-lite-latest
```

`YOUR_API_KEY_HERE` 부분을 실제 API 키로 바꿔주세요.

5. 저장합니다.

> `.env` 파일에는 API 키가 들어가므로 GitHub에 업로드하지 않습니다.

## 5. 실행

아래 명령은 `news-bias-analyzer` 루트 폴더에서 실행합니다.

### macOS / Linux

```bash
python3 app.py
```

### Windows PowerShell / CMD

```powershell
python app.py
```

성공하면 브라우저에서 아래 주소로 접속합니다.

```text
http://localhost:5000/
```

포트를 바꾸고 싶다면 `.env` 파일에서 `PORT=5001`처럼 수정하거나 아래처럼 실행할 수 있습니다.

### macOS / Linux

```bash
PORT=5001 python3 app.py
```

### Windows PowerShell

```powershell
$env:PORT="5001"
python app.py
```

### Windows CMD

```cmd
set PORT=5001
python app.py
```

앱을 종료하려면 터미널에서 `Ctrl + C`를 누릅니다.

---

# API 키 설정

실시간 기사 분석을 사용하려면 LLM API 키가 필요합니다.

현재 앱은 아래 순서로 provider를 시도합니다.

1. Google Gemini
2. OpenRouter / OpenAI
3. Anthropic
4. 모두 실패하면 mock 결과 사용

기본적으로는 Google Gemini 키 하나만 있어도 실행할 수 있습니다.

```env
GOOGLE_API_KEY=YOUR_API_KEY_HERE
GOOGLE_MODEL=models/gemini-flash-lite-latest
```

선택적으로 다른 provider를 사용할 수도 있습니다.

```env
OPENROUTER_API_KEY=YOUR_API_KEY_HERE
OPENROUTER_MODEL=openai/gpt-4o-mini
OPENROUTER_HTTP_REFERER=https://newsight.local
```

```env
OPENAI_API_KEY=YOUR_API_KEY_HERE
OPENAI_MODEL=gpt-4o-mini
```

```env
ANTHROPIC_API_KEY=YOUR_API_KEY_HERE
ANTHROPIC_MODEL=claude-3-5-sonnet-latest
```

---

# 사용 방법

## 기사 분석하기

1. 상단 탭에서 **분석하기**를 선택합니다.
2. 뉴스 기사 URL을 입력합니다.
3. **분석 시작** 버튼을 누릅니다.
4. 분석 결과를 확인합니다.

   * 기사 요약
   * 주요 프레임
   * 중심 목소리
   * 본문 읽기 보조
   * 함께 비교해볼 기사

## 이슈별 관점 보기

1. 상단 탭에서 **이슈별 관점 보기**를 선택합니다.
2. 준비된 이슈 중 하나를 선택합니다.
3. 같은 이슈를 서로 다른 관점으로 다룬 기사 예시를 비교합니다.

이 화면은 실시간 AI 분석이 아니라, 시연용 예시 기사 데이터를 바탕으로 구성됩니다.

---

# 프로젝트 구조

```text
news-bias-analyzer/
├── README.md
├── app.py
├── analyzer.py
├── crawler.py
├── recommender.py
├── searcher.py
├── prompts.py
├── bias_rubric.md
├── requirements.txt
├── templates/
│   └── index.html
├── static/
│   ├── app.css
│   └── app.js
├── data/
│   ├── articles.db
│   ├── articles_curated.csv
│   ├── articles_expanded.csv
│   └── curated_explore.json
└── scripts/
```

## 주요 파일

* `app.py`

  * Flask 서버 실행, API 라우팅, 분석 결과 반환을 담당합니다.

* `analyzer.py`

  * 기사 내용을 LLM으로 분석하고 읽기 포인트를 생성합니다.

* `crawler.py`

  * 기사 URL에서 제목과 본문을 추출합니다.

* `recommender.py`

  * 함께 비교해볼 기사 후보를 찾습니다.

* `searcher.py`

  * 로컬 데이터에서 찾지 못한 경우 관련 기사 후보를 탐색합니다.

* `prompts.py`

  * LLM 분석에 사용하는 프롬프트와 분류 기준을 담고 있습니다.

* `bias_rubric.md`

  * 뉴스 프레임, 인용 구조, 누락 관점 등 분석 기준을 정리한 문서입니다.

* `templates/index.html`

  * 웹페이지 구조를 정의합니다.

* `static/app.css`

  * 화면 디자인과 레이아웃을 담당합니다.

* `static/app.js`

  * 탭 전환, 분석 요청, 결과 렌더링 등 브라우저 동작을 담당합니다.

* `data/curated_explore.json`

  * 이슈별 관점 보기 화면에 사용하는 예시 기사 데이터입니다.

---

# 주의사항

* `.env` 파일은 GitHub에 올리지 않습니다.
* 실시간 기사 분석은 API 키가 있어야 정상적으로 작동합니다.
* 일부 언론사 URL은 본문 추출이 실패할 수 있습니다.
* `이슈별 관점 보기`는 시연용 예시 데이터 기반 화면입니다.
* 분석 결과는 최종 판정이 아니라 뉴스를 비교해서 읽기 위한 보조 정보입니다.
