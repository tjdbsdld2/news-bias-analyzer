"""
NewsPrism - 뉴스 편향 분석 시스템 (Flask 백엔드)

## 실행 방법 (팀원용)

### 1. 가상환경 설정 (처음 한 번만)
   python -m venv .venv
   
### 2. 가상환경 활성화
   Windows PowerShell: .venv\Scripts\Activate.ps1
   Windows CMD: .venv\Scripts\activate.bat
   Mac/Linux: source .venv/bin/activate

### 3. 패키지 설치
   pip install -r requirements.txt

### 4. 환경 설정 파일 생성 (.env)
   news 폴더에 .env 파일 생성 후 다음 내용 추가:
   PORT=5000
   FLASK_ENV=development

### 5. Flask 앱 실행
   python app.py
   또는 디버그 모드:
   python -m flask run --debug

### 6. 브라우저 접속
   http://localhost:5000

## 주의사항
- 반드시 가상환경을 활성화한 후 실행하세요
- .env 파일이 없으면 기본 포트 5000번으로 실행됩니다
- requirements.txt에 모든 필요한 패키지가 포함되어 있습니다
"""

from flask import Flask, request, jsonify
from flask_cors import CORS
import os
from dotenv import load_dotenv


load_dotenv()

app = Flask(__name__)
CORS(app)

# ============================================
# HTML 템플릿 (인라인)
# ============================================
HTML_TEMPLATE = """
<!DOCTYPE html>
<html lang="ko">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>NewsPrism - 뉴스의 다른 시선을 발견하다</title>
    <link rel="preconnect" href="https://fonts.googleapis.com">
    <link href="https://fonts.googleapis.com/css2?family=Noto+Sans+KR:wght@400;500;700;900&display=swap" rel="stylesheet">
    <style>
        /* ========== CSS 스타일 ========== */
        * {
            margin: 0;
            padding: 0;
            box-sizing: border-box;
        }

        :root {
            --primary: #1a1a2e;
            --secondary: #16213e;
            --accent: #0f3460;
            --highlight: #e94560;
            --text: #eee;
            --text-secondary: #aaa;
            --bg: #0f0f1e;
            --card-bg: #1a1a2e;
            --border: #2a2a3e;
        }

        body {
            font-family: 'Noto Sans KR', sans-serif;
            background: var(--bg);
            color: var(--text);
            line-height: 1.6;
        }

        .container {
            max-width: 1200px;
            margin: 0 auto;
            padding: 0 20px;
        }

        .hidden {
            display: none !important;
        }

        /* 헤더 */
        .header {
            background: var(--primary);
            border-bottom: 2px solid var(--highlight);
            padding: 20px 0;
            position: sticky;
            top: 0;
            z-index: 100;
            box-shadow: 0 2px 10px rgba(0,0,0,0.3);
        }

        .header-content {
            display: flex;
            justify-content: space-between;
            align-items: center;
        }

        .logo h1 {
            font-size: 28px;
            font-weight: 900;
            letter-spacing: 2px;
            color: var(--text);
        }

        .logo .prism {
            color: var(--highlight);
        }

        .tagline {
            font-size: 12px;
            color: var(--text-secondary);
            margin-top: 5px;
        }

        .nav {
            display: flex;
            gap: 30px;
        }

        .nav a {
            color: var(--text);
            text-decoration: none;
            font-weight: 500;
            transition: color 0.3s;
        }

        .nav a:hover {
            color: var(--highlight);
        }

        /* 히어로 섹션 */
        .hero {
            padding: 80px 0 100px;
            background: linear-gradient(135deg, var(--secondary) 0%, var(--accent) 100%);
            text-align: center;
        }

        .hero-title {
            font-size: 48px;
            font-weight: 900;
            margin-bottom: 20px;
            line-height: 1.2;
        }

        .hero-subtitle {
            font-size: 18px;
            color: var(--text-secondary);
            margin-bottom: 40px;
        }

        /* 검색 박스 */
        .search-box {
            max-width: 700px;
            margin: 0 auto 15px;
            display: flex;
            gap: 10px;
            background: var(--card-bg);
            padding: 8px;
            border-radius: 50px;
            box-shadow: 0 10px 30px rgba(0,0,0,0.3);
        }

        .url-input {
            flex: 1;
            padding: 15px 25px;
            border: none;
            background: transparent;
            color: var(--text);
            font-size: 16px;
            outline: none;
        }

        .url-input::placeholder {
            color: var(--text-secondary);
        }

        .analyze-btn {
            padding: 15px 35px;
            background: var(--highlight);
            color: white;
            border: none;
            border-radius: 50px;
            font-size: 16px;
            font-weight: 700;
            cursor: pointer;
            transition: all 0.3s;
            display: flex;
            align-items: center;
            gap: 10px;
        }

        .analyze-btn:hover {
            background: #d63651;
            transform: translateY(-2px);
            box-shadow: 0 5px 15px rgba(233, 69, 96, 0.4);
        }

        .example-text {
            font-size: 14px;
            color: var(--text-secondary);
        }

        /* 로딩 */
        .loading {
            text-align: center;
            padding: 60px 20px;
        }

        .spinner {
            width: 50px;
            height: 50px;
            border: 4px solid var(--border);
            border-top-color: var(--highlight);
            border-radius: 50%;
            animation: spin 1s linear infinite;
            margin: 0 auto 20px;
        }

        @keyframes spin {
            to { transform: rotate(360deg); }
        }

        /* 결과 섹션 */
        .results {
            padding: 60px 0;
        }

        /* 기사 카드 */
        .article-card {
            background: var(--card-bg);
            border: 1px solid var(--border);
            border-radius: 12px;
            padding: 30px;
            margin-bottom: 40px;
        }

        .article-card.original {
            border-left: 4px solid var(--highlight);
        }

        .card-header {
            margin-bottom: 15px;
        }

        .badge {
            display: inline-block;
            padding: 5px 12px;
            border-radius: 20px;
            font-size: 12px;
            font-weight: 700;
            text-transform: uppercase;
        }

        .badge-primary {
            background: var(--highlight);
            color: white;
        }

        .article-title {
            font-size: 28px;
            font-weight: 700;
            margin-bottom: 15px;
            line-height: 1.3;
        }

        .article-meta {
            display: flex;
            gap: 10px;
            color: var(--text-secondary);
            font-size: 14px;
            margin-bottom: 20px;
        }

        .divider {
            color: var(--border);
        }

        .article-summary {
            color: var(--text-secondary);
            line-height: 1.8;
            margin-bottom: 20px;
        }

        .read-more {
            color: var(--highlight);
            text-decoration: none;
            font-weight: 600;
            transition: color 0.3s;
        }

        .read-more:hover {
            color: #d63651;
        }

        /* 분석 섹션 */
        .analysis-section {
            margin-bottom: 60px;
        }

        .section-title {
            font-size: 32px;
            font-weight: 700;
            margin-bottom: 10px;
            display: flex;
            align-items: center;
            gap: 10px;
        }

        .section-subtitle {
            color: var(--text-secondary);
            margin-bottom: 30px;
        }

        .icon {
            font-size: 28px;
        }

        .analysis-grid {
            display: grid;
            grid-template-columns: repeat(auto-fit, minmax(280px, 1fr));
            gap: 20px;
        }

        .analysis-card {
            background: var(--card-bg);
            border: 1px solid var(--border);
            border-radius: 12px;
            padding: 25px;
        }

        .analysis-card.highlight {
            border-color: var(--highlight);
            background: linear-gradient(135deg, var(--card-bg) 0%, rgba(233, 69, 96, 0.1) 100%);
        }

        .card-title {
            font-size: 16px;
            font-weight: 700;
            color: var(--text-secondary);
            margin-bottom: 15px;
            text-transform: uppercase;
            letter-spacing: 1px;
        }

        .card-content {
            font-size: 18px;
            font-weight: 600;
        }

        /* 점수 바 */
        .score-container {
            display: flex;
            align-items: center;
            gap: 15px;
        }

        .score-bar {
            flex: 1;
            height: 12px;
            background: var(--border);
            border-radius: 10px;
            overflow: hidden;
        }

        .score-fill {
            height: 100%;
            background: linear-gradient(90deg, var(--highlight) 0%, #4ecca3 100%);
            transition: width 0.5s ease;
        }

        .score-text {
            font-size: 24px;
            font-weight: 700;
            color: var(--highlight);
        }

        /* 인용 리스트 */
        .citations-list {
            display: flex;
            flex-direction: column;
            gap: 10px;
        }

        .citation-item {
            display: flex;
            justify-content: space-between;
            padding: 10px;
            background: var(--bg);
            border-radius: 8px;
        }

        .citation-source {
            font-weight: 600;
        }

        .citation-count {
            color: var(--highlight);
            font-weight: 700;
        }

        /* 관점 리스트 */
        .perspectives-list {
            list-style: none;
            display: flex;
            flex-direction: column;
            gap: 10px;
        }

        .perspectives-list li {
            padding-left: 20px;
            position: relative;
        }

        .perspectives-list li::before {
            content: "▸";
            position: absolute;
            left: 0;
            color: var(--highlight);
            font-weight: 700;
        }

        /* 추천 기사 */
        .recommendations-section {
            margin-bottom: 60px;
        }

        .recommendations-grid {
            display: grid;
            grid-template-columns: repeat(auto-fit, minmax(320px, 1fr));
            gap: 25px;
        }

        .recommendation-card {
            background: var(--card-bg);
            border: 1px solid var(--border);
            border-radius: 12px;
            padding: 25px;
            transition: all 0.3s;
            cursor: pointer;
        }

        .recommendation-card:hover {
            transform: translateY(-5px);
            border-color: var(--highlight);
            box-shadow: 0 10px 30px rgba(233, 69, 96, 0.2);
        }

        .rec-badge {
            display: inline-block;
            padding: 5px 12px;
            background: rgba(233, 69, 96, 0.2);
            color: var(--highlight);
            border-radius: 20px;
            font-size: 11px;
            font-weight: 700;
            margin-bottom: 15px;
        }

        .rec-title {
            font-size: 20px;
            font-weight: 700;
            margin-bottom: 10px;
            line-height: 1.3;
        }

        .rec-meta {
            display: flex;
            gap: 10px;
            color: var(--text-secondary);
            font-size: 13px;
        }

        /* 소개 섹션 */
        .about {
            padding: 80px 0;
            background: var(--secondary);
        }

        .about-grid {
            display: grid;
            grid-template-columns: repeat(auto-fit, minmax(280px, 1fr));
            gap: 30px;
            margin-top: 40px;
        }

        .about-card {
            text-align: center;
            padding: 30px;
        }

        .about-icon {
            font-size: 48px;
            margin-bottom: 20px;
        }

        .about-card h3 {
            font-size: 22px;
            margin-bottom: 15px;
        }

        .about-card p {
            color: var(--text-secondary);
            line-height: 1.8;
        }

        /* 푸터 */
        .footer {
            background: var(--primary);
            padding: 40px 0;
            text-align: center;
            border-top: 2px solid var(--highlight);
        }

        .footer p {
            color: var(--text-secondary);
            margin-bottom: 10px;
        }

        .disclaimer {
            font-size: 14px;
            color: var(--text-secondary);
        }

        /* 반응형 */
        @media (max-width: 768px) {
            .hero-title {
                font-size: 32px;
            }
            
            .search-box {
                flex-direction: column;
                border-radius: 12px;
            }
            
            .analyze-btn {
                border-radius: 8px;
                justify-content: center;
            }
            
            .header-content {
                flex-direction: column;
                gap: 20px;
            }
            
            .nav {
                gap: 15px;
            }
        }
    </style>
</head>
<body>
    <!-- 헤더 -->
    <header class="header">
        <div class="container">
            <div class="header-content">
                <div class="logo">
                    <h1>NEWS<span class="prism">PRISM</span></h1>
                    <p class="tagline">뉴스의 다른 시선을 발견하다</p>
                </div>
                <nav class="nav">
                    <a href="#about">소개</a>
                    <a href="#how-it-works">작동 방식</a>
                    <a href="https://github.com/yourusername/newsprism" target="_blank">GitHub</a>
                </nav>
            </div>
        </div>
    </header>

    <!-- 메인 히어로 섹션 -->
    <section class="hero">
        <div class="container">
            <div class="hero-content">
                <h2 class="hero-title">하나의 기사, 여러 개의 관점</h2>
                <p class="hero-subtitle">
                    AI가 뉴스 기사의 프레이밍을 분석하고,<br>
                    반대 시각의 기사를 자동으로 추천합니다.
                </p>
                
                <!-- URL 입력 폼 -->
                <div class="search-box">
                    <input 
                        type="url" 
                        id="newsUrl" 
                        placeholder="뉴스 기사 URL을 입력하세요 (예: https://news.example.com/article/123)"
                        class="url-input"
                    >
                    <button id="analyzeBtn" class="analyze-btn">
                        <span class="btn-text">분석하기</span>
                        <span class="btn-icon">→</span>
                    </button>
                </div>
                
                <p class="example-text">
                    예시: 네이버뉴스, 다음뉴스, 언론사 직접 링크 등
                </p>
            </div>
        </div>
    </section>

    <!-- 로딩 인디케이터 -->
    <div id="loading" class="loading hidden">
        <div class="spinner"></div>
        <p>기사를 분석하고 있습니다...</p>
    </div>

    <!-- 결과 섹션 -->
    <section id="results" class="results hidden">
        <div class="container">
            <!-- 원본 기사 정보 -->
            <div class="article-card original">
                <div class="card-header">
                    <span class="badge badge-primary">분석한 기사</span>
                </div>
                <h3 id="articleTitle" class="article-title"></h3>
                <div class="article-meta">
                    <span id="articleSource" class="source"></span>
                    <span class="divider">|</span>
                    <span id="articleDate" class="date"></span>
                </div>
                <p id="articleSummary" class="article-summary"></p>
                <a id="articleUrl" href="#" target="_blank" class="read-more">원문 보기 →</a>
            </div>

            <!-- 분석 결과 -->
            <div class="analysis-section">
                <h3 class="section-title">
                    <span class="icon">📊</span>
                    AI 분석 결과
                </h3>
                
                <div class="analysis-grid">
                    <!-- 프레이밍 -->
                    <div class="analysis-card">
                        <h4 class="card-title">프레이밍 방식</h4>
                        <p id="framing" class="card-content"></p>
                    </div>
                    
                    <!-- 중립성 점수 -->
                    <div class="analysis-card">
                        <h4 class="card-title">표현 중립성</h4>
                        <div class="score-container">
                            <div class="score-bar">
                                <div id="neutralityBar" class="score-fill"></div>
                            </div>
                            <span id="neutralityScore" class="score-text"></span>
                        </div>
                    </div>
                    
                    <!-- 인용 분포 -->
                    <div class="analysis-card">
                        <h4 class="card-title">인용 출처 분포</h4>
                        <div id="citations" class="citations-list"></div>
                    </div>
                    
                    <!-- 누락된 관점 -->
                    <div class="analysis-card highlight">
                        <h4 class="card-title">누락된 관점</h4>
                        <ul id="missingPerspectives" class="perspectives-list"></ul>
                    </div>
                </div>
            </div>

            <!-- 추천 기사 -->
            <div class="recommendations-section">
                <h3 class="section-title">
                    <span class="icon">🔍</span>
                    다른 시각의 기사
                </h3>
                <p class="section-subtitle">같은 사건을 다르게 다룬 기사들입니다</p>
                
                <div id="recommendations" class="recommendations-grid"></div>
            </div>
        </div>
    </section>

    <!-- 소개 섹션 -->
    <section id="about" class="about">
        <div class="container">
            <h2 class="section-title">NewsPrism이란?</h2>
            <div class="about-grid">
                <div class="about-card">
                    <div class="about-icon">🎯</div>
                    <h3>문제 인식</h3>
                    <p>독자는 보통 하나의 기사만 읽고 사건을 이해합니다. 하지만 언론사마다 강조하는 정보와 표현이 다릅니다.</p>
                </div>
                <div class="about-card">
                    <div class="about-icon">🤖</div>
                    <h3>AI 분석</h3>
                    <p>Claude AI가 기사의 프레이밍, 표현 방식, 인용 분포를 자동으로 분석합니다.</p>
                </div>
                <div class="about-card">
                    <div class="about-icon">📰</div>
                    <h3>다각도 이해</h3>
                    <p>반대 관점의 기사를 추천하여 사건을 입체적으로 이해할 수 있도록 돕습니다.</p>
                </div>
            </div>
        </div>
    </section>

    <!-- 푸터 -->
    <footer class="footer">
        <div class="container">
            <p>&copy; 2024 NewsPrism. 미디어 리터러시를 위한 AI 도구.</p>
            <p class="disclaimer">
                ⚠️ AI 분석은 보조 도구입니다. 최종 판단은 독자의 몫입니다.
            </p>
        </div>
    </footer>

    <script>
        // ========== JavaScript 로직 ==========
        
        // DOM 요소
        const analyzeBtn = document.getElementById('analyzeBtn');
        const newsUrlInput = document.getElementById('newsUrl');
        const loadingSection = document.getElementById('loading');
        const resultsSection = document.getElementById('results');

        // 분석 버튼 클릭 이벤트
        analyzeBtn.addEventListener('click', async () => {
            const url = newsUrlInput.value.trim();
            
            if (!url) {
                alert('뉴스 기사 URL을 입력해주세요.');
                return;
            }
            
            if (!isValidUrl(url)) {
                alert('올바른 URL 형식이 아닙니다.');
                return;
            }
            
            await analyzeArticle(url);
        });

        // Enter 키 지원
        newsUrlInput.addEventListener('keypress', (e) => {
            if (e.key === 'Enter') {
                analyzeBtn.click();
            }
        });

        // URL 유효성 검사
        function isValidUrl(string) {
            try {
                new URL(string);
                return true;
            } catch (_) {
                return false;
            }
        }

        // 기사 분석 함수
        async function analyzeArticle(url) {
            // UI 상태 변경
            loadingSection.classList.remove('hidden');
            resultsSection.classList.add('hidden');
            
            try {
                const response = await fetch('/api/analyze', {
                    method: 'POST',
                    headers: {
                        'Content-Type': 'application/json',
                    },
                    body: JSON.stringify({ url: url })
                });
                
                if (!response.ok) {
                    throw new Error('분석에 실패했습니다.');
                }
                
                const data = await response.json();
                displayResults(data);
                
            } catch (error) {
                alert('오류가 발생했습니다: ' + error.message);
                loadingSection.classList.add('hidden');
            }
        }

        // 결과 표시 함수
        function displayResults(data) {
            const { article, analysis, recommendations } = data;
            
            // 원본 기사 정보
            document.getElementById('articleTitle').textContent = article.title;
            document.getElementById('articleSource').textContent = article.source;
            document.getElementById('articleDate').textContent = article.date;
            document.getElementById('articleSummary').textContent = article.summary;
            document.getElementById('articleUrl').href = article.url;
            
            // 분석 결과
            document.getElementById('framing').textContent = analysis.framing;
            
            // 중립성 점수
            const neutralityScore = analysis.neutrality;
            document.getElementById('neutralityScore').textContent = `${neutralityScore}/10`;
            document.getElementById('neutralityBar').style.width = `${neutralityScore * 10}%`;
            
            // 인용 분포
            const citationsHtml = Object.entries(analysis.citations)
                .map(([source, count]) => `
                    <div class="citation-item">
                        <span class="citation-source">${source}</span>
                        <span class="citation-count">${count}회</span>
                    </div>
                `)
                .join('');
            document.getElementById('citations').innerHTML = citationsHtml;
            
            // 누락된 관점
            const perspectivesHtml = analysis.missing_perspectives
                .map(perspective => `<li>${perspective}</li>`)
                .join('');
            document.getElementById('missingPerspectives').innerHTML = perspectivesHtml;
            
            // 추천 기사
            const recommendationsHtml = recommendations
                .map(rec => `
                    <div class="recommendation-card" onclick="window.open('${rec.url}', '_blank')">
                        <span class="rec-badge">${rec.framing}</span>
                        <h4 class="rec-title">${rec.title}</h4>
                        <div class="rec-meta">
                            <span>${rec.source}</span>
                            <span class="divider">|</span>
                            <span>${rec.date}</span>
                        </div>
                    </div>
                `)
                .join('');
            document.getElementById('recommendations').innerHTML = recommendationsHtml;
            
            // UI 상태 변경
            loadingSection.classList.add('hidden');
            resultsSection.classList.remove('hidden');
            
            // 결과 섹션으로 스크롤
            resultsSection.scrollIntoView({ behavior: 'smooth', block: 'start' });
        }
    </script>
</body>
</html>
"""

# ============================================
# Flask 라우트
# ============================================

@app.route('/')
def index():
    """메인 홈페이지"""
    return HTML_TEMPLATE

@app.route('/api/analyze', methods=['POST'])
def analyze():
    """
    뉴스 분석 API
    TODO: 팀원이 구현한 모듈과 연동
    """
    try:
        data = request.get_json()
        url = data.get('url')
        
        if not url:
            return jsonify({"error": "URL을 입력해주세요"}), 400
        
        # ========================================
        # TODO: 실제 분석 로직 연동
        # ========================================
        # from backend.crawler import crawl_article
        # from backend.analyzer import analyze_article
        # from backend.recommender import recommend_articles
        # 
        # article_data = crawl_article(url)
        # analysis_result = analyze_article(article_data)
        # recommendations = recommend_articles(analysis_result)
        # ========================================
        
        # 더미 응답 (개발용)
        dummy_response = {
            "article": {
                "title": "정부, 새로운 경제정책 발표",
                "source": "뉴스프리즘",
                "date": "2024-01-15",
                "url": url,
                "summary": "정부가 오늘 새로운 경제정책을 발표했습니다. 주요 내용은 중소기업 지원 확대와 세제 개편입니다."
            },
            "analysis": {
                "framing": "정부 정책 중심",
                "neutrality": 6,
                "citations": {
                    "정부 관계자": 5,
                    "전문가": 2,
                    "시민단체": 1
                },
                "title_match": 8,
                "missing_perspectives": [
                    "야당의 반대 입장",
                    "중소기업 현장 목소리",
                    "경제학자들의 우려"
                ],
                "tags": ["경제", "정부정책", "재정"]
            },
            "recommendations": [
                {
                    "title": "야당, 정부 경제정책 강력 비판",
                    "source": "대안뉴스",
                    "date": "2024-01-15",
                    "url": "https://example.com/article2",
                    "framing": "비판 중심"
                },
                {
                    "title": "중소기업, 새 정책에 '우려' 표명",
                    "source": "경제일보",
                    "date": "2024-01-15",
                    "url": "https://example.com/article3",
                    "framing": "현장 목소리 중심"
                },
                {
                    "title": "전문가 '실효성 의문...재정 부담 커질 것'",
                    "source": "분석저널",
                    "date": "2024-01-15",
                    "url": "https://example.com/article4",
                    "framing": "전문가 분석 중심"
                }
            ]
        }
        
        return jsonify(dummy_response), 200
        
    except Exception as e:
        return jsonify({"error": str(e)}), 500

@app.route('/api/health', methods=['GET'])
def health():
    """서버 상태 확인"""
    return jsonify({"status": "ok", "message": "NewsPrism is running"})

# ============================================
# 서버 실행
# ============================================

if __name__ == '__main__':
    port = int(os.getenv('PORT', 5000))
    debug = os.getenv('FLASK_ENV', 'development') == 'development'
    app.run(host='0.0.0.0', port=port, debug=debug)
