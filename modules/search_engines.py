"""搜索引擎模块

通过搜索引擎查找目标用户名的相关网页并爬取内容。
使用 httpx（异步 HTTP 客户端）+ 正则表达式解析 HTML。
"""

import httpx
import asyncio
import re
import urllib.parse

# 通用请求头
USER_AGENT = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
HEADERS = {"User-Agent": USER_AGENT}

# 搜索引擎 URL 模板
ENGINE_URLS = {
    "duckduckgo": "https://html.duckduckgo.com/html/?q={query}",
    "bing": "https://www.bing.com/search?q={query}",
    "yandex": "https://yandex.com/search/?text={query}",
}


def _strip_tags(text: str) -> str:
    """移除 HTML 标签，保留纯文本"""
    return re.sub(r"<[^>]+>", "", text)


def _compress_whitespace(text: str) -> str:
    """压缩空白字符为单个空格"""
    return re.sub(r"\s+", " ", text).strip()


def parse_duckduckgo(html: str) -> list[dict]:
    """解析 DuckDuckGo 搜索结果页

    解析 <a class="result__a" href="...">title</a>，
    并处理 duckduckgo 重定向 URL（uddg= 参数）。
    """
    results = []
    pattern = r'<a class="result__a" href="([^"]+)"[^>]*>(.*?)</a>'
    for match in re.finditer(pattern, html, re.DOTALL):
        raw_url, title_html = match.group(1), match.group(2)
        # 解析 duckduckgo 重定向 URL，提取 uddg 参数得到真实地址
        url = raw_url
        if "uddg=" in raw_url:
            parsed = urllib.parse.urlparse(raw_url)
            params = urllib.parse.parse_qs(parsed.query)
            if "uddg" in params:
                # parse_qs 已对值做 URL 解码，直接使用
                url = params["uddg"][0]
        title = _compress_whitespace(_strip_tags(title_html))
        if url and title:
            results.append({"url": url, "title": title, "engine": "duckduckgo"})
    return results


def parse_bing(html: str) -> list[dict]:
    """解析 Bing 搜索结果页

    解析 <h2><a href="...">title</a></h2>
    """
    results = []
    pattern = r'<h2>\s*<a href="([^"]+)"[^>]*>(.*?)</a>\s*</h2>'
    for match in re.finditer(pattern, html, re.DOTALL):
        url, title_html = match.group(1), match.group(2)
        title = _compress_whitespace(_strip_tags(title_html))
        if url and title:
            results.append({"url": url, "title": title, "engine": "bing"})
    return results


def parse_yandex(html: str) -> list[dict]:
    """解析 Yandex 搜索结果页

    解析 <a class="organic__url" href="..."> 或 <a href="..." class="Link">
    """
    results = []
    patterns = [
        r'<a class="organic__url"[^>]*href="([^"]+)"[^>]*>(.*?)</a>',
        r'<a href="([^"]+)"[^>]*class="Link"[^>]*>(.*?)</a>',
    ]
    seen = set()
    for pattern in patterns:
        for match in re.finditer(pattern, html, re.DOTALL):
            url, title_html = match.group(1), match.group(2)
            if url in seen:
                continue
            title = _compress_whitespace(_strip_tags(title_html))
            if url and title:
                seen.add(url)
                results.append({"url": url, "title": title, "engine": "yandex"})
    return results


# 引擎与解析函数的映射
PARSERS = {
    "duckduckgo": parse_duckduckgo,
    "bing": parse_bing,
    "yandex": parse_yandex,
}


async def search_engine(query: str, engine: str = "duckduckgo", max_results: int = 5) -> list[dict]:
    """通过指定搜索引擎查询并返回结果列表

    返回结果：[{url, title, engine}, ...]
    任何异常均返回空列表。
    """
    if engine not in ENGINE_URLS:
        return []
    try:
        url = ENGINE_URLS[engine].format(query=urllib.parse.quote(query))
        async with httpx.AsyncClient(headers=HEADERS, timeout=20, follow_redirects=True) as client:
            resp = await client.get(url)
            resp.raise_for_status()
            html = resp.text
        results = PARSERS[engine](html)
        return results[:max_results]
    except Exception:
        return []


async def crawl_page(url: str, max_chars: int = 400) -> dict:
    """爬取单个网页内容

    - 获取 HTML
    - 提取 <title> 标签
    - 移除 <script> 和 <style> 标签内容
    - 移除所有 HTML 标签，保留纯文本
    - 压缩空白字符
    - 返回 {url, title, snippet: text[:max_chars]}
    - 超时 20 秒
    """
    try:
        async with httpx.AsyncClient(headers=HEADERS, timeout=20, follow_redirects=True) as client:
            resp = await client.get(url)
            resp.raise_for_status()
            html = resp.text
        # 提取 <title> 标签内容
        title_match = re.search(r"<title[^>]*>(.*?)</title>", html, re.DOTALL | re.IGNORECASE)
        title = _compress_whitespace(_strip_tags(title_match.group(1))) if title_match else ""
        # 移除 <script> 和 <style> 标签内容
        text = re.sub(r"<script[^>]*>.*?</script>", "", html, flags=re.DOTALL | re.IGNORECASE)
        text = re.sub(r"<style[^>]*>.*?</style>", "", text, flags=re.DOTALL | re.IGNORECASE)
        # 移除所有 HTML 标签，保留纯文本
        text = _strip_tags(text)
        # 压缩空白字符
        text = _compress_whitespace(text)
        return {"url": url, "title": title, "snippet": text[:max_chars]}
    except Exception:
        return {"url": url, "title": "", "snippet": ""}


async def search_and_crawl(query: str, max_results: int = 5) -> list[dict]:
    """完整搜索+爬取流程

    - 依次尝试三个引擎（DuckDuckGo → Bing → Yandex）
    - 第一个返回结果的引擎就用，不用全试
    - 对搜索结果，爬取前 max_results 个页面
    - 返回 [{url, title, snippet, engine}, ...]
    """
    # 依次尝试引擎，命中即停
    search_results = []
    for engine in ("duckduckgo", "bing", "yandex"):
        results = await search_engine(query, engine=engine, max_results=max_results)
        if results:
            search_results = results
            break
    if not search_results:
        return []
    # 爬取前 max_results 个页面
    to_crawl = search_results[:max_results]
    tasks = [crawl_page(item["url"]) for item in to_crawl]
    pages = await asyncio.gather(*tasks)
    # 组装最终结果
    output = []
    for item, page in zip(to_crawl, pages):
        output.append({
            "url": page["url"],
            "title": page["title"],
            "snippet": page["snippet"],
            "engine": item["engine"],
        })
    return output
