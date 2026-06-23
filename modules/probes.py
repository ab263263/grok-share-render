"""OSINT 用户名探测模块。

负责探测给定用户名在各平台是否存在，支持 GitHub / Reddit / Instagram 专用探测，
以及基于 Maigret 站点配置的通用 HTTP 探测。
"""

import httpx
import asyncio
import re
import json
from datetime import datetime, timezone

# 通用浏览器请求头
DEFAULT_HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
    "Accept-Language": "en-US,en;q=0.9",
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
}

# 通用 not-found 文本模式（不区分大小写匹配）
GENERIC_NOT_FOUND_PATTERNS = [
    "user not found",
    "account not found",
    "doesn't exist",
    "does not exist",
    "page not found",
    "not found",
]


def _to_list(value) -> list:
    """将字符串 / 列表 / None 统一转为列表。"""
    if not value:
        return []
    if isinstance(value, str):
        return [value]
    if isinstance(value, (list, tuple, set)):
        return list(value)
    return [str(value)]


def _lower(text: str) -> str:
    """安全转小写。"""
    return (text or "").lower()


def _extract_meta(html: str, prop: str) -> str:
    """从 HTML 中提取 <meta> 标签内容，支持 property/name 属性及其顺序。

    匹配形如：
      <meta property="og:title" content="...">
      <meta name="description" content="...">
      <meta content="..." property="og:title">
    """
    prop_escaped = re.escape(prop)
    patterns = [
        rf'<meta[^>]*\sproperty=["\']{prop_escaped}["\'][^>]*\scontent=["\']([^"\']*)["\']',
        rf'<meta[^>]*\scontent=["\']([^"\']*)["\'][^>]*\sproperty=["\']{prop_escaped}["\']',
        rf'<meta[^>]*\sname=["\']{prop_escaped}["\'][^>]*\scontent=["\']([^"\']*)["\']',
        rf'<meta[^>]*\scontent=["\']([^"\']*)["\'][^>]*\sname=["\']{prop_escaped}["\']',
    ]
    for pat in patterns:
        m = re.search(pat, html, re.IGNORECASE)
        if m:
            return m.group(1).strip()
    return ""


def _extract_title(html: str) -> str:
    """提取 <title> 标签内容。"""
    m = re.search(r"<title[^>]*>(.*?)</title>", html, re.IGNORECASE | re.DOTALL)
    return m.group(1).strip() if m else ""


def _err(platform: str, username: str, e: Exception) -> dict:
    """构造异常时的 notfound 返回值。"""
    return {
        "status": "notfound",
        "platform": platform,
        "username": username,
        "error": getattr(e, "message", str(e)),
    }


async def probe_github(username: str) -> dict:
    """探测 GitHub 用户名是否存在。

    调用 GitHub REST API，User-Agent 使用 "OSINT-Agent/1.0"，超时 15 秒。
    """
    url = f"https://api.github.com/users/{username}"
    headers = {
        "User-Agent": "OSINT-Agent/1.0",
        "Accept": "application/vnd.github+json",
    }
    try:
        async with httpx.AsyncClient(timeout=15.0) as client:
            resp = await client.get(url, headers=headers)
        if resp.status_code == 200:
            data = resp.json()
            name = data.get("name") or ""
            bio = data.get("bio") or ""
            followers = data.get("followers", 0)
            html_url = data.get("html_url") or f"https://github.com/{username}"
            snippet = f"Name: {name} | Bio: {bio} | Followers: {followers}"
            return {
                "status": "found",
                "platform": "GitHub",
                "username": username,
                "url": html_url,
                "snippet": snippet,
                "extra": data,
            }
        return {
            "status": "notfound",
            "platform": "GitHub",
            "username": username,
        }
    except Exception as e:
        return _err("GitHub", username, e)


async def probe_reddit(username: str) -> dict:
    """探测 Reddit 用户名是否存在。

    调用 Reddit about.json 接口，超时 15 秒。
    若 JSON 解析失败或 data.name 为 null，返回 notfound。
    """
    url = f"https://www.reddit.com/user/{username}/about.json"
    try:
        async with httpx.AsyncClient(timeout=15.0, headers=DEFAULT_HEADERS) as client:
            resp = await client.get(url)
        if resp.status_code != 200:
            return {
                "status": "notfound",
                "platform": "Reddit",
                "username": username,
            }
        # JSON 解析失败则视为未找到
        try:
            payload = resp.json()
        except Exception:
            return {
                "status": "notfound",
                "platform": "Reddit",
                "username": username,
            }
        data = payload.get("data") or {}
        # data.name 为空则视为未找到
        if not data.get("name"):
            return {
                "status": "notfound",
                "platform": "Reddit",
                "username": username,
            }
        name = data.get("name", "")
        # 优先使用 total_karma，否则用 link + comment karma
        if "total_karma" in data:
            karma = data.get("total_karma", 0)
        else:
            karma = (data.get("link_karma", 0) or 0) + (data.get("comment_karma", 0) or 0)
        created_utc = data.get("created_utc")
        # 将时间戳转为可读日期
        if isinstance(created_utc, (int, float)):
            created = datetime.fromtimestamp(created_utc, tz=timezone.utc).strftime(
                "%Y-%m-%d"
            )
        else:
            created = str(created_utc or "")
        profile_url = f"https://www.reddit.com/user/{username}"
        snippet = f"Name: {name} | Karma: {karma} | Created: {created}"
        return {
            "status": "found",
            "platform": "Reddit",
            "username": username,
            "url": profile_url,
            "snippet": snippet,
            "extra": data,
        }
    except Exception as e:
        return _err("Reddit", username, e)


async def probe_instagram(username: str) -> dict:
    """探测 Instagram 用户名是否存在。

    抓取用户主页 HTML，检查 404 模式，提取 og 元数据与 _sharedData。
    超时 20 秒。
    """
    url = f"https://www.instagram.com/{username}/"
    try:
        async with httpx.AsyncClient(timeout=20.0, headers=DEFAULT_HEADERS) as client:
            resp = await client.get(url, follow_redirects=True)
        html = resp.text or ""
        lower_html = _lower(html)
        # 检查 not-found 模式
        not_found_markers = [
            "sorry, this page isn't available",
            "page isn't available",
            "dialog-404",
        ]
        if any(marker in lower_html for marker in not_found_markers):
            return {
                "status": "notfound",
                "platform": "Instagram",
                "username": username,
            }
        # 提取 og 元数据
        og_title = _extract_meta(html, "og:title")
        og_description = _extract_meta(html, "og:description")
        og_image = _extract_meta(html, "og:image")
        # 尝试解析 window._sharedData = {...} JSON
        followers = ""
        bio = ""
        shared_data = {}
        m = re.search(
            r"window\._sharedData\s*=\s*(\{.*?\});\s*</script>",
            html,
            re.DOTALL,
        )
        if not m:
            # 兜底：匹配到行尾分号
            m = re.search(r"window\._sharedData\s*=\s*(\{.*?\})\s*;", html, re.DOTALL)
        if m:
            try:
                shared_data = json.loads(m.group(1))
                # 深层定位 entry_data 中的用户信息
                entry_data = (
                    shared_data.get("entry_data", {})
                    .get("ProfilePage", [{}])[0]
                    .get("graphql", {})
                    .get("user", {})
                )
                if entry_data:
                    followers = entry_data.get(
                        "edge_followed_by", {}
                    ).get("count", "")
                    bio = entry_data.get("biography", "") or ""
            except Exception:
                shared_data = {}
        # 组装 snippet
        parts = []
        if og_title:
            parts.append(f"Title: {og_title}")
        if bio:
            parts.append(f"Bio: {bio}")
        if followers != "":
            parts.append(f"Followers: {followers}")
        if og_description and f"Bio: {og_description}" not in " | ".join(parts):
            parts.append(f"Desc: {og_description}")
        snippet = " | ".join(parts) if parts else og_title or og_description
        extra = {
            "og_title": og_title,
            "og_description": og_description,
            "og_image": og_image,
            "followers": followers,
            "bio": bio,
            "shared_data": shared_data,
        }
        # 没有任何有效信息则视为未找到
        if not snippet and not og_image:
            return {
                "status": "notfound",
                "platform": "Instagram",
                "username": username,
            }
        return {
            "status": "found",
            "platform": "Instagram",
            "username": username,
            "url": url,
            "snippet": snippet,
            "extra": extra,
        }
    except Exception as e:
        return _err("Instagram", username, e)


async def probe_http(site: dict, username: str) -> dict:
    """通用 HTTP 探测，基于 Maigret 站点配置。

    site 字段：name, url(含 {u} 占位), nf(not-found 模式列表), pf(presence 指标列表)。
    超时 20 秒。
    """
    platform = site.get("name", "Unknown")
    try:
        url_template = site.get("url", "")
        url = url_template.replace("{u}", username)
        if not url:
            return {
                "status": "notfound",
                "platform": platform,
                "username": username,
                "error": "empty url",
            }
        async with httpx.AsyncClient(timeout=20.0, headers=DEFAULT_HEADERS) as client:
            resp = await client.get(url, follow_redirects=True)
        status_code = resp.status_code
        html = resp.text or ""
        lower_html = _lower(html)
        # 404 / 410 直接判定为未找到
        if status_code in (404, 410):
            return {
                "status": "notfound",
                "platform": platform,
                "username": username,
            }
        # 检查 not-found 模式：站点配置 nf + 通用模式
        nf_patterns = _to_list(site.get("nf")) + GENERIC_NOT_FOUND_PATTERNS
        for pattern in nf_patterns:
            if pattern and _lower(pattern) in lower_html:
                return {
                    "status": "notfound",
                    "platform": platform,
                    "username": username,
                }
        # 检查 presence 指标
        pf_patterns = _to_list(site.get("pf"))
        verified = False
        if pf_patterns:
            verified = any(
                _lower(p) in lower_html for p in pf_patterns if p
            )
        # 提取 snippet：title / meta description / og:description
        title = _extract_title(html)
        meta_desc = _extract_meta(html, "description")
        og_desc = _extract_meta(html, "og:description")
        snippet_parts = []
        if title:
            snippet_parts.append(f"Title: {title}")
        if meta_desc:
            snippet_parts.append(f"Desc: {meta_desc}")
        elif og_desc:
            snippet_parts.append(f"Desc: {og_desc}")
        snippet = " | ".join(snippet_parts)
        return {
            "status": "found",
            "platform": platform,
            "username": username,
            "url": url,
            "snippet": snippet,
            "verified": verified,
        }
    except Exception as e:
        return _err(platform, username, e)


async def probe_platform(site: dict, username: str) -> dict:
    """路由函数：根据站点名称分发到专用或通用探测函数。"""
    name = site.get("name", "")
    if name == "GitHub":
        return await probe_github(username)
    if name == "Reddit":
        return await probe_reddit(username)
    if name == "Instagram":
        return await probe_instagram(username)
    return await probe_http(site, username)


async def probe_batch(
    sites: list, username: str, concurrency: int = 10
) -> list:
    """批量并发探测多个站点。

    使用 asyncio.Semaphore 控制并发数，返回所有结果列表（顺序与 sites 对应）。
    """
    semaphore = asyncio.Semaphore(max(1, int(concurrency)))

    async def _run(site: dict) -> dict:
        async with semaphore:
            return await probe_platform(site, username)

    tasks = [_run(site) for site in sites]
    results = await asyncio.gather(*tasks, return_exceptions=False)
    return list(results)
