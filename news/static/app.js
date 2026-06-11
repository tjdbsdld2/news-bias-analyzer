const analyzeForm = document.getElementById("analyzeForm");
const newsUrlInput = document.getElementById("newsUrl");
const analyzeBtn = document.getElementById("analyzeBtn");
const loadingSection = document.getElementById("loading");
const resultsSection = document.getElementById("results");
const articlePanel = document.getElementById("articlePanel");
const overviewGrid = document.getElementById("overviewGrid");
const analysisGrid = document.getElementById("analysisGrid");
const recommendationSection = document.getElementById("recommendationSection");
const statusBanner = document.getElementById("statusBanner");

const idleLabel = analyzeBtn.querySelector(".btn-idle");
const loadingLabel = analyzeBtn.querySelector(".btn-loading");

let sentencePopover = null;
let activeSentence = null;

function setActiveSentence(nextSentence) {
    if (activeSentence && activeSentence !== nextSentence) {
        activeSentence.classList.remove("is-active");
    }

    activeSentence = nextSentence || null;

    if (activeSentence) {
        activeSentence.classList.add("is-active");
    }
}

function ensureSentencePopover() {
    if (sentencePopover) {
        return sentencePopover;
    }

    sentencePopover = document.createElement("div");
    sentencePopover.className = "ns-sentence-popover hidden";
    sentencePopover.innerHTML = `
        <div class="ns-sentence-popover-label"></div>
        <div class="ns-sentence-popover-body"></div>
    `;
    document.body.appendChild(sentencePopover);

    document.addEventListener("click", (event) => {
        if (!sentencePopover || sentencePopover.classList.contains("hidden")) {
            return;
        }
        if (sentencePopover.contains(event.target) || event.target.closest(".ns-annotated-sentence")) {
            return;
        }
        hideSentencePopover();
    });

    return sentencePopover;
}

function escapeHtml(value) {
    return String(value ?? "")
        .replaceAll("&", "&amp;")
        .replaceAll("<", "&lt;")
        .replaceAll(">", "&gt;")
        .replaceAll('"', "&quot;")
        .replaceAll("'", "&#39;");
}

function renderTagRow(tags = [], tone = "accent") {
    if (!Array.isArray(tags) || tags.length === 0) {
        return "";
    }

    return `
        <div class="ns-chip-row">
            ${tags
                .filter(Boolean)
                .map((tag) => `<span class="ns-chip ${tone}">#${escapeHtml(tag)}</span>`)
                .join("")}
        </div>
    `;
}

function getAnalysisModeMeta(analysis = {}) {
    const notice = String(analysis.analysis_notice || "").trim();
    if (notice) {
        return {
            label: "개발용 대체 분석",
            toneClass: "fallback",
            description: notice,
        };
    }

    return {
        label: "실시간 분석",
        toneClass: "live",
        description: "현재 LLM 응답을 바탕으로 생성된 분석 결과입니다.",
    };
}

function setLoading(isLoading) {
    analyzeBtn.disabled = isLoading;
    idleLabel.classList.toggle("hidden-inline", isLoading);
    loadingLabel.classList.toggle("hidden-inline", !isLoading);
    loadingSection.classList.toggle("hidden", !isLoading);
}

function setStatus(message, tone = "note") {
    if (!message) {
        statusBanner.className = "ns-status hidden";
        statusBanner.innerHTML = "";
        return;
    }

    statusBanner.className = `ns-status ${tone === "caution" ? "caution" : ""}`;
    statusBanner.innerHTML = `<p>${escapeHtml(message)}</p>`;
}

function getUrlValidationMessage(value) {
    const trimmed = String(value || "").trim();
    const genericMessage = "올바른 뉴스 기사 URL을 입력해 주세요. 예: https://...";

    if (!trimmed || trimmed.length < 12) {
        return genericMessage;
    }
    if (/^(javascript:|data:|file:)/i.test(trimmed)) {
        return genericMessage;
    }

    try {
        const parsed = new URL(trimmed);
        if (!["http:", "https:"].includes(parsed.protocol)) {
            return genericMessage;
        }
        if (!parsed.hostname || !parsed.hostname.includes(".")) {
            return genericMessage;
        }
    } catch (_) {
        return genericMessage;
    }

    return "";
}

async function parseApiResponse(response) {
    const rawText = await response.text();
    if (!rawText) {
        return {};
    }

    try {
        return JSON.parse(rawText);
    } catch (_) {
        return { message: response.ok ? "" : "서버 응답을 해석하지 못했습니다. 잠시 후 다시 시도해 주세요." };
    }
}

function hideSentencePopover() {
    if (!sentencePopover) {
        return;
    }
    sentencePopover.classList.add("hidden");
    sentencePopover.classList.remove("is-clickable");
    setActiveSentence(null);
}

function positionSentencePopover(target, event = null) {
    if (!sentencePopover || !target) {
        return;
    }

    const rect = target.getBoundingClientRect();
    const popoverRect = sentencePopover.getBoundingClientRect();
    const scrollX = window.scrollX;
    const scrollY = window.scrollY;
    const viewportWidth = window.innerWidth;
    const viewportHeight = window.innerHeight;
    const gutter = 16;

    let left = (event?.clientX ?? rect.left) + scrollX + 14;
    let top = rect.bottom + scrollY + 12;

    if (left + popoverRect.width > scrollX + viewportWidth - gutter) {
        left = scrollX + viewportWidth - popoverRect.width - gutter;
    }
    if (left < scrollX + gutter) {
        left = scrollX + gutter;
    }

    if (top + popoverRect.height > scrollY + viewportHeight - gutter) {
        top = rect.top + scrollY - popoverRect.height - 12;
    }
    if (top < scrollY + gutter) {
        top = rect.bottom + scrollY + 12;
    }

    sentencePopover.style.left = `${left}px`;
    sentencePopover.style.top = `${top}px`;
}

function showSentencePopover(target, event = null, clickable = false) {
    const popover = ensureSentencePopover();
    const labelNode = popover.querySelector(".ns-sentence-popover-label");
    const bodyNode = popover.querySelector(".ns-sentence-popover-body");

    labelNode.textContent = target.dataset.tipLabel || "읽기 메모";
    bodyNode.textContent = target.dataset.tip || "";

    popover.classList.remove("hidden");
    popover.classList.toggle("is-clickable", clickable);
    setActiveSentence(target);
    positionSentencePopover(target, event);
}

function initSentencePopover() {
    ensureSentencePopover();
    const prefersHover = window.matchMedia("(hover: hover) and (pointer: fine)").matches;
    const sentences = articlePanel.querySelectorAll(".ns-annotated-sentence");

    sentences.forEach((sentence) => {
        if (prefersHover) {
            sentence.addEventListener("mouseenter", (event) => {
                showSentencePopover(sentence, event, false);
            });
            sentence.addEventListener("mousemove", (event) => {
                if (activeSentence === sentence) {
                    positionSentencePopover(sentence, event);
                }
            });
            sentence.addEventListener("mouseleave", () => {
                hideSentencePopover();
            });
        }

        sentence.addEventListener("click", (event) => {
            event.preventDefault();
            event.stopPropagation();
            const willClose = activeSentence === sentence && sentencePopover && !sentencePopover.classList.contains("hidden");
            if (willClose) {
                hideSentencePopover();
                return;
            }
            showSentencePopover(sentence, event, true);
        });
    });
}

function renderArticle(article, analysis) {
    const analysisMode = getAnalysisModeMeta(analysis);

    articlePanel.innerHTML = `
        <div class="ns-panel-kicker">입력 기사 요약</div>
        <h2 class="ns-article-title">${escapeHtml(article.title)}</h2>
        <div class="ns-meta">
            <strong>언론사</strong> ${escapeHtml(article.source)}
            &nbsp;·&nbsp;
            <strong>날짜</strong> ${escapeHtml(article.date)}
            &nbsp;·&nbsp;
            <strong>입력 URL</strong> ${escapeHtml(article.url)}
        </div>

        <div class="ns-summary-box">
            <div class="ns-mini-label">핵심 요약</div>
            <p>${escapeHtml(analysis.summary)}</p>
        </div>

        <div class="ns-analysis-mode ${escapeHtml(analysisMode.toneClass)}">
            <div class="ns-analysis-mode-label">${escapeHtml(analysisMode.label)}</div>
            <p>${escapeHtml(analysisMode.description)}</p>
        </div>

        <div class="ns-kpi-grid">
            <div class="ns-kpi-card">
                <div class="ns-mini-label">대표 프레임</div>
                <div class="ns-kpi-value">${escapeHtml(analysis.frame)}</div>
            </div>
            <div class="ns-kpi-card">
                <div class="ns-mini-label">주요 목소리</div>
                <div class="ns-kpi-value">${escapeHtml(analysis.primary_voice)}</div>
            </div>
        </div>

        <div class="ns-mini-label">이슈 태그</div>
        ${renderTagRow(analysis.issue_tags, "accent")}

        <div class="ns-position-strip">
            <strong>한눈에 읽는 포지션</strong>
            <p>${escapeHtml(article.position_summary || analysis.position_summary || "")}</p>
        </div>

        <details class="ns-body-details">
            <summary>본문 읽기 보조 펼치기</summary>
            <div class="ns-body-inner">
                ${article.body_preview_html || '<div class="ns-body-empty">본문 정보가 없습니다.</div>'}
            </div>
        </details>
    `;
    initSentencePopover();
}

function renderOverview(analysis) {
    const cards = [
        {
            title: "이 기사에서 가장 먼저 커지는 쟁점",
            body: analysis.framing_analysis,
        },
        {
            title: "누구의 말이 중심 근거로 들리나",
            body: analysis.citation_analysis,
        },
        {
            title: "이 기사만으로는 아직 무엇이 부족한가",
            body: analysis.missing_perspective,
        },
    ];

    overviewGrid.innerHTML = cards
        .map(
            (card) => `
                <article class="ns-overview-card">
                    <div class="ns-card-title">${escapeHtml(card.title)}</div>
                    <p class="ns-card-copy">${escapeHtml(card.body || "분석 결과가 없습니다.")}</p>
                </article>
            `
        )
        .join("");
}

function renderAnalysisCards(analysis) {
    const cards = [
        {
            title: "표현과 어조",
            body: analysis.language_analysis,
            tone: analysis.tone,
        },
        {
            title: "제목이 먼저 밀어 올리는 쟁점",
            body: analysis.title_body_gap,
        },
        {
            title: "다음 기사에서 비교할 포인트",
            body: analysis.comparison_hint,
        },
    ];

    analysisGrid.innerHTML = cards
        .map(
            (card) => `
                <article class="ns-analysis-card">
                    <div class="ns-card-title">${escapeHtml(card.title)}</div>
                    ${card.tone ? `<div class="ns-tone-pill">어조 · ${escapeHtml(card.tone)}</div>` : ""}
                    <p class="ns-card-copy">${escapeHtml(card.body || "분석 결과가 없습니다.")}</p>
                </article>
            `
        )
        .join("");
}

function renderRecommendationCards(recommendations) {
    return recommendations
        .map((rec) => {
            const subline = [rec.sub_issue, rec.tone, rec.primary_voice].filter(Boolean).join(" · ");
            return `
                <article class="ns-rec-card">
                    <div class="ns-rec-topline">
                        <span class="ns-frame-pill">${escapeHtml(rec.frame || "프레임 정보 없음")}</span>
                        <span class="ns-rec-meta">${escapeHtml(rec.source || "출처 정보 없음")} · ${escapeHtml(rec.date || "날짜 정보 없음")}</span>
                    </div>
                    <h3 class="ns-rec-title">${escapeHtml(rec.title || "제목 없음")}</h3>
                    ${subline ? `<div class="ns-rec-subline">${escapeHtml(subline)}</div>` : ""}
                    ${renderTagRow(rec.issue_tags || [], "secondary")}
                    ${
                        rec.memo
                            ? `<div class="ns-rec-guide"><strong>왜 같이 보면 좋은가</strong><p>${escapeHtml(rec.memo)}</p></div>`
                            : ""
                    }
                    <a class="ns-link-btn" href="${escapeHtml(rec.url || "#")}" target="_blank" rel="noopener noreferrer">기사 보러 가기</a>
                </article>
            `;
        })
        .join("");
}

function renderExternalCards(candidates = [], guidance = {}) {
    const guidanceCandidates = Array.isArray(guidance.candidates) ? guidance.candidates : [];

    return candidates
        .map((candidate, index) => {
            const guide = guidanceCandidates[index] || {};
            return `
                <article class="ns-external-card">
                    <div class="ns-rec-topline">
                        <span class="ns-frame-pill">비교 후보</span>
                        <span class="ns-rec-meta">${escapeHtml(candidate.source || "출처 정보 없음")} · ${escapeHtml(candidate.date || "날짜 정보 없음")}</span>
                    </div>
                    <h3 class="ns-rec-title">${escapeHtml(candidate.title || "제목 없음")}</h3>
                    <div class="ns-rec-guide">
                        <strong>왜 같이 보면 좋은가</strong>
                        <p>${escapeHtml(guide.why_relevant || "입력 기사와 연관된 주제를 다룰 가능성이 있어 비교 후보로 제시되었습니다.")}</p>
                    </div>
                    <div class="ns-rec-guide">
                        <strong>비교 포인트</strong>
                        <p>${escapeHtml(guide.what_to_compare || "입력 기사에서 덜 다뤄진 이해관계자, 근거, 강조점을 함께 비교해보세요.")}</p>
                    </div>
                    ${
                        candidate.snippet
                            ? `<div class="ns-inline-note"><strong>검색 요약</strong> ${escapeHtml(candidate.snippet)}</div>`
                            : ""
                    }
                    <a class="ns-link-btn" href="${escapeHtml(candidate.url || "#")}" target="_blank" rel="noopener noreferrer">후보 기사 보러 가기</a>
                </article>
            `;
        })
        .join("");
}

function renderRecommendationSection(result, external) {
    const articles = result?.articles || [];
    const tier = result?.tier || "none";
    const recommendationNotice = result?.notice || "";
    const externalMessage = external?.message || "";

    if (articles.length > 0) {
        const heading = result.heading || "다른 관점 추천 기사";
        const caption = result.caption || "";
        const tierLabel = tier === "curated" ? "검수 기반 추천" : "";
        const supplementalNote =
            tier === "expanded"
                ? "자동 수집 기사와 자동 태깅 결과를 바탕으로 고른 보조 추천입니다."
                : "";

        recommendationSection.innerHTML = `
            <div class="ns-reco-shell">
                ${tierLabel ? `<div class="ns-reco-tier-pill">${escapeHtml(tierLabel)}</div>` : ""}
                <h2 class="ns-reco-headline">${escapeHtml(heading)}</h2>
                <p class="ns-reco-caption">${escapeHtml(caption)}</p>
            </div>
            <div class="ns-reco-list">
                ${renderRecommendationCards(articles)}
            </div>
            ${
                supplementalNote
                    ? `<div class="ns-inline-note">${escapeHtml(supplementalNote)}</div>`
                    : ""
            }
            ${
                recommendationNotice
                    ? `<div class="ns-inline-note">${escapeHtml(recommendationNotice)}</div>`
                    : ""
            }
        `;
        return;
    }

    const candidates = external?.candidates || [];
    const guidance = external?.guidance || {};

    recommendationSection.innerHTML = `
        <div class="ns-reco-shell">
            <div class="ns-reco-tier-pill">외부 탐색</div>
            <h2 class="ns-reco-headline">함께 볼 기사</h2>
            <p class="ns-reco-caption">로컬 추천 DB에서 바로 연결되는 기사를 찾지 못해, 같은 주제를 넓게 살펴볼 수 있는 외부 기사를 모았습니다.</p>
        </div>
        ${
            guidance?.overall_note
                ? `<div class="ns-external-note">${escapeHtml(guidance.overall_note)}</div>`
                : ""
        }
        ${
            candidates.length === 0
                ? `<div class="ns-empty-shell"><p>${escapeHtml(externalMessage || "지금은 함께 볼 외부 기사를 찾지 못했습니다.")}</p></div>`
                : `<div class="ns-reco-list">${renderExternalCards(candidates, guidance)}</div>`
        }
        ${
            guidance?.explanation_notice
                ? `<div class="ns-inline-note">${escapeHtml(guidance.explanation_notice)}</div>`
                : ""
        }
        ${
            recommendationNotice && candidates.length > 0
                ? `<div class="ns-inline-note">${escapeHtml(recommendationNotice)}</div>`
                : ""
        }
        ${
            externalMessage && candidates.length > 0
                ? `<div class="ns-inline-note">${escapeHtml(externalMessage)}</div>`
                : ""
        }
    `;
}

async function analyzeArticle(url) {
    setLoading(true);
    setStatus("");
    resultsSection.classList.add("hidden");

    try {
        const response = await fetch("/api/analyze", {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify({ url }),
        });

        const data = await parseApiResponse(response);
        if (!response.ok) {
            throw new Error(data.message || data.error || "분석에 실패했습니다.");
        }

        const { article, analysis, recommendations, external } = data;

        renderArticle(article, analysis);
        renderOverview(analysis);
        renderAnalysisCards(analysis);
        renderRecommendationSection(recommendations, external);

        const baseStatus = analysis.analysis_notice
            ? "분석은 완료되었지만 현재는 개발용 대체 분석을 표시하고 있습니다."
            : "실시간 분석이 완료되었습니다. 아래에서 기사 요약, 관점 분석, 비교 추천을 순서대로 확인할 수 있습니다.";
        setStatus(analysis.analysis_notice ? `${baseStatus} ${analysis.analysis_notice}` : baseStatus);

        resultsSection.classList.remove("hidden");
        resultsSection.scrollIntoView({ behavior: "smooth", block: "start" });
    } catch (error) {
        const rawMessage = error?.message || "";
        const friendlyMessage =
            /Failed to fetch|NetworkError|Load failed/i.test(rawMessage)
                ? "분석 서버에 연결하지 못했습니다. 앱을 localhost 주소로 열었는지 확인한 뒤 다시 시도해 주세요."
                : rawMessage || "오류가 발생했습니다.";
        setStatus(friendlyMessage, "caution");
    } finally {
        setLoading(false);
    }
}

analyzeForm.addEventListener("submit", async (event) => {
    event.preventDefault();
    const url = newsUrlInput.value.trim();
    const validationMessage = getUrlValidationMessage(url);
    if (validationMessage) {
        setStatus(validationMessage, "caution");
        return;
    }
    await analyzeArticle(url);
});
