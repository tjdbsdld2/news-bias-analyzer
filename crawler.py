import argparse
import re
import time
from datetime import datetime
from urllib.parse import urlparse

import requests
from bs4 import BeautifulSoup


HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/125.0 Safari/537.36"
    ),
    "Accept-Language": "ko-KR,ko;q=0.9,en-US;q=0.8,en;q=0.7",
}


NAVER_SELECTORS = [
    "#dic_area",
    "#articeBody",
    "#articleBodyContents",
    "div.newsct_article",
]


GENERIC_SELECTORS = [
    "article",
    "main",
    "[class*=article]",
    "[class*=content]",
    "[class*=news]",
    "[id*=article]",
    "[id*=content]",
    "[id*=news]",
]


REMOVE_SELECTORS = [
    "script",
    "style",
    "iframe",
    "noscript",
    "nav",
    "header",
    "footer",
    "aside",
    "button",
    "form",
    "figure",
    "svg",
    "canvas",
]


DROP_LINE_PATTERNS = [
    r"^광고$",
    r"^AD$",
    r"^본문\s*바로가기$",
    r"^언론사별\s*바로가기$",
    r"^말하기\s*속도$",
    r"^글자\s*크기\s*변경하기$",
    r"^인쇄하기$",
    r"^공유하기$",
    r"^구독$",
    r"^좋아요$",
    r"^댓글$",
    r"무단\s*전재",
    r"재배포\s*금지",
    r"저작권자",
    r"Copyright",
    r"AI\s*학습\s*및\s*활용\s*금지",
    r"이 기사에 대해 어떻게 생각하시나요",
    r"기자\s*[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+",
    r"[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+",
]


def now_iso():
    return datetime.now().isoformat(timespec="seconds")


def validate_url(url):
    if not isinstance(url, str) or not url.strip():
        raise ValueError("뉴스 링크가 비어 있습니다.")

    url = url.strip()
    parsed = urlparse(url)

    if parsed.scheme not in ["http", "https"]:
        raise ValueError("뉴스 링크는 http 또는 https로 시작해야 합니다.")

    if not parsed.netloc:
        raise ValueError("올바른 뉴스 링크 형식이 아닙니다.")

    return url


def fetch_html(url, timeout=12):
    response = requests.get(
        url,
        headers=HEADERS,
        timeout=timeout,
    )

    response.raise_for_status()

    if not response.encoding or response.encoding.lower() == "iso-8859-1":
        response.encoding = response.apparent_encoding

    return response.text


def remove_noise_nodes(node):
    for selector in REMOVE_SELECTORS:
        for tag in node.select(selector):
            tag.decompose()


def normalize_text(text):
    if not isinstance(text, str):
        return ""

    text = text.replace("\u200b", " ")
    text = text.replace("\xa0", " ")
    text = text.replace("\ufeff", " ")

    text = re.sub(r"[\t\r\f\v]+", " ", text)
    text = re.sub(r"\n{2,}", "\n", text)
    text = re.sub(r" {2,}", " ", text)

    return text.strip()


def get_node_text(node):
    remove_noise_nodes(node)

    for br in node.find_all("br"):
        br.replace_with("\n")

    text = node.get_text("\n", strip=True)

    return normalize_text(text)


def extract_naver_content(soup):
    for selector in NAVER_SELECTORS:
        node = soup.select_one(selector)

        if node:
            text = get_node_text(node)

            if len(text) >= 100:
                return text

    return ""


def extract_generic_content(soup):
    remove_noise_nodes(soup)

    candidates = []

    for selector in GENERIC_SELECTORS:
        for node in soup.select(selector):
            text = get_node_text(node)

            if len(text) >= 200:
                candidates.append(text)

    paragraphs = []

    for p in soup.find_all("p"):
        text = normalize_text(p.get_text(" ", strip=True))

        if len(text) >= 30:
            paragraphs.append(text)

    if paragraphs:
        candidates.append("\n".join(paragraphs))

    if not candidates and soup.body:
        candidates.append(get_node_text(soup.body))

    candidates = sorted(
        set(candidates),
        key=len,
        reverse=True,
    )

    return candidates[0] if candidates else ""


def extract_content(url, html):
    soup = BeautifulSoup(html, "html.parser")
    domain = urlparse(url).netloc.lower()

    if "news.naver.com" in domain or "n.news.naver.com" in domain:
        content = extract_naver_content(soup)

        if content:
            return content

    return extract_generic_content(soup)


def drop_noise_lines(text):
    lines = []

    for line in text.splitlines():
        line = normalize_text(line)

        if not line:
            continue

        should_drop = False

        for pattern in DROP_LINE_PATTERNS:
            if re.search(pattern, line, flags=re.IGNORECASE):
                should_drop = True
                break

        if should_drop:
            continue

        lines.append(line)

    return "\n".join(lines)


def remove_inline_noise(text):
    text = re.sub(
        r"[가-힣]{2,4}\s*(기자|특파원|인턴기자)\s*[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+",
        " ",
        text,
    )

    text = re.sub(
        r"[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+",
        " ",
        text,
    )

    text = re.sub(
        r"\[[^\]]{0,40}(기자|특파원|인턴기자)[^\]]{0,40}\]",
        " ",
        text,
    )

    return text


def dedupe_lines(text):
    result = []
    seen = set()

    for line in text.splitlines():
        line = normalize_text(line)
        key = re.sub(r"\s+", "", line)

        if not key:
            continue

        if key in seen:
            continue

        seen.add(key)
        result.append(line)

    return "\n".join(result)


def preprocess_content(text, max_chars=12000):
    text = normalize_text(text)
    text = remove_inline_noise(text)
    text = drop_noise_lines(text)
    text = dedupe_lines(text)

    text = re.sub(r"\n{3,}", "\n\n", text)
    text = re.sub(r" {2,}", " ", text)
    text = text.strip()

    if max_chars and len(text) > max_chars:
        text = text[:max_chars].rsplit(" ", 1)[0].strip()

    return text


def crawl_news(news_url, delay=1.0, timeout=12, max_chars=12000):
    news_url = validate_url(news_url)

    try:
        html = fetch_html(
            url=news_url,
            timeout=timeout,
        )

        raw_content = extract_content(
            url=news_url,
            html=html,
        )

        content = preprocess_content(
            text=raw_content,
            max_chars=max_chars,
        )

        time.sleep(delay)

        if not content:
            return {
                "url": news_url,
                "raw_content": raw_content,
                "content": "",
                "crawl_status": "no_content",
                "crawled_at": now_iso(),
            }

        return {
            "url": news_url,
            "raw_content": raw_content,
            "content": content,
            "crawl_status": "success",
            "crawled_at": now_iso(),
        }

    except requests.exceptions.Timeout:
        time.sleep(delay)

        return {
            "url": news_url,
            "raw_content": "",
            "content": "",
            "crawl_status": "timeout",
            "crawled_at": now_iso(),
        }

    except requests.exceptions.HTTPError as error:
        time.sleep(delay)

        status_code = (
            error.response.status_code
            if error.response is not None
            else "unknown"
        )

        return {
            "url": news_url,
            "raw_content": "",
            "content": "",
            "crawl_status": f"http_error_{status_code}",
            "crawled_at": now_iso(),
        }

    except requests.exceptions.RequestException:
        time.sleep(delay)

        return {
            "url": news_url,
            "raw_content": "",
            "content": "",
            "crawl_status": "request_error",
            "crawled_at": now_iso(),
        }

    except Exception:
        time.sleep(delay)

        return {
            "url": news_url,
            "raw_content": "",
            "content": "",
            "crawl_status": "parse_error",
            "crawled_at": now_iso(),
        }


def save_to_txt(result, output_path="crarling_data.txt"):
    with open(output_path, "w", encoding="utf-8") as file:
        file.write("=" * 80 + "\n")
        file.write("CRAWLING RESULT\n")
        file.write("=" * 80 + "\n")
        file.write(f"url: {result.get('url', '')}\n")
        file.write(f"crawl_status: {result.get('crawl_status', '')}\n")
        file.write(f"crawled_at: {result.get('crawled_at', '')}\n")
        file.write("-" * 80 + "\n")
        file.write(result.get("content", ""))
        file.write("\n")


def main():
    parser = argparse.ArgumentParser()

    parser.add_argument(
        "news_url",
        help="크롤링할 뉴스 기사 링크",
    )

    parser.add_argument(
        "--output",
        default="crarling_data.txt",
    )

    parser.add_argument(
        "--delay",
        type=float,
        default=1.0,
    )

    parser.add_argument(
        "--timeout",
        type=int,
        default=12,
    )

    parser.add_argument(
        "--max-chars",
        type=int,
        default=12000,
    )

    args = parser.parse_args()

    news_url = args.news_url

    result = crawl_news(
        news_url=news_url,
        delay=args.delay,
        timeout=args.timeout,
        max_chars=args.max_chars,
    )

    save_to_txt(
        result=result,
        output_path=args.output,
    )

    print(f"crawl_status: {result['crawl_status']}")
    print(f"saved: {args.output}")


if __name__ == "__main__":
   main()

# def test_crawler_inside_file():
#     news_url = "https://n.news.naver.com/mnews/article/001/0016110438?sid=100"

#     result = crawl_news(
#         news_url=news_url,
#         delay=1.0,
#         timeout=12,
#         max_chars=12000,
#     )

#     save_to_txt(
#         result=result,
#         output_path="crarling_data.txt",
#     )

#     print("크롤링 테스트 완료")
#     print(f"URL: {result.get('url')}")
#     print(f"상태: {result.get('crawl_status')}")
#     print(f"본문 길이: {len(result.get('content', ''))}")
#     print("저장 파일: crarling_data.txt")

#     preview = result.get("content", "")

#     print()
#     print("=" * 80)
#     print("본문 미리보기")
#     print("=" * 80)
#     print(preview)


# if __name__ == "__main__":
#     test_crawler_inside_file()