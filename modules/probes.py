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
    # 游戏平台专用探测器
    game_probes = {
        "Steam": probe_steam,
        "SteamGroup": probe_steam_group,
        "EpicGames": probe_epic_games,
        "RiotGames": probe_riot_games,
        "LeagueOfLegends": probe_lol,
        "Valorant": probe_valorant,
        "WarGaming": probe_wargaming,
        "WorldOfTanks": probe_wargaming,
        "WorldOfWarships": probe_wargaming,
        "WorldOfWarplanes": probe_wargaming,
        "XboxLive": probe_xbox,
        "PlayStationNetwork": probe_psn,
        "BattleNet": probe_battle_net,
        "Twitch": probe_twitch,
        "Discord": probe_discord,
        "Roblox": probe_roblox,
        "Minecraft": probe_minecraft,
        "Fortnite": probe_fortnite,
        "CSGO": probe_csgo,
        "Faceit": probe_faceit,
    }
    if name in game_probes:
        return await game_probes[name](username)
    return await probe_http(site, username)


# ==================== 游戏平台探测器 ====================

async def probe_steam(username: str) -> dict:
    """Steam 个人资料探测"""
    url = f"https://steamcommunity.com/id/{username}"
    try:
        async with httpx.AsyncClient(timeout=15, follow_redirects=True) as client:
            resp = await client.get(url, headers=DEFAULT_HEADERS)
            html = resp.text
            if resp.status_code == 200 and "profile_header" in html:
                # 提取 Steam 信息
                name_match = re.search(r'<span class="actual_persona_name"[^>]*>([^<]+)</span>', html)
                level_match = re.search(r'<span class="friendPlayerLevelNum"[^>]*>(\d+)</span>', html)
                snippet = ""
                if name_match:
                    snippet += f"名称: {name_match.group(1)} "
                if level_match:
                    snippet += f"等级: {level_match.group(1)}"
                return {"status": "found", "platform": "Steam", "username": username, "url": url, "snippet": snippet}
            return {"status": "not_found", "platform": "Steam", "username": username, "url": url}
    except Exception as e:
        return {"status": "error", "platform": "Steam", "username": username, "url": url, "error": str(e)[:100]}


async def probe_steam_group(username: str) -> dict:
    """Steam 群组探测"""
    url = f"https://steamcommunity.com/groups/{username}"
    try:
        async with httpx.AsyncClient(timeout=15, follow_redirects=True) as client:
            resp = await client.get(url, headers=DEFAULT_HEADERS)
            if resp.status_code == 200 and "groupContent" in resp.text:
                return {"status": "found", "platform": "SteamGroup", "username": username, "url": url}
            return {"status": "not_found", "platform": "SteamGroup", "username": username, "url": url}
    except Exception as e:
        return {"status": "error", "platform": "SteamGroup", "username": username, "url": url, "error": str(e)[:100]}


async def probe_epic_games(username: str) -> dict:
    """Epic Games Store 探测"""
    url = f"https://store.epicgames.com/u/{username}"
    try:
        async with httpx.AsyncClient(timeout=15, follow_redirects=True) as client:
            resp = await client.get(url, headers=DEFAULT_HEADERS)
            if resp.status_code == 200 and "user-card" in resp.text.lower():
                return {"status": "found", "platform": "EpicGames", "username": username, "url": url}
            return {"status": "not_found", "platform": "EpicGames", "username": username, "url": url}
    except Exception as e:
        return {"status": "error", "platform": "EpicGames", "username": username, "url": url, "error": str(e)[:100]}


async def probe_riot_games(username: str) -> dict:
    """Riot Games（LoL + Valorant）探测 - 通过 op.gg"""
    # LoL 多个服务器
    regions = ["na", "euw", "kr", "eune", "jp", "oce", "br", "las", "lan", "ru", "tr"]
    found_regions = []
    for region in regions[:5]:  # 限制前 5 个服务器避免太慢
        url = f"https://lol.op.gg/summoners/{region}/{username}"
        try:
            async with httpx.AsyncClient(timeout=10, follow_redirects=True) as client:
                resp = await client.get(url, headers=DEFAULT_HEADERS)
                if resp.status_code == 200 and "summoner" in resp.text.lower():
                    found_regions.append({"region": region, "url": url})
        except Exception:
            pass
    if found_regions:
        return {
            "status": "found",
            "platform": "RiotGames",
            "username": username,
            "url": found_regions[0]["url"],
            "snippet": f"在 {len(found_regions)} 个服务器找到: {', '.join(r['region'].upper() for r in found_regions)}",
        }
    return {"status": "not_found", "platform": "RiotGames", "username": username, "url": f"https://lol.op.gg/summoners/na/{username}"}


async def probe_lol(username: str) -> dict:
    """League of Legends 探测 - 通过 op.gg"""
    return await probe_riot_games(username)


async def probe_valorant(username: str) -> dict:
    """Valorant 探测 - 通过 tracker.gg"""
    url = f"https://tracker.gg/valorant/profile/riot/{username}"
    try:
        async with httpx.AsyncClient(timeout=15, follow_redirects=True) as client:
            resp = await client.get(url, headers=DEFAULT_HEADERS)
            if resp.status_code == 200 and "profile" in resp.text.lower():
                return {"status": "found", "platform": "Valorant", "username": username, "url": url}
            return {"status": "not_found", "platform": "Valorant", "username": username, "url": url}
    except Exception as e:
        return {"status": "error", "platform": "Valorant", "username": username, "url": url, "error": str(e)[:100]}


async def probe_wargaming(username: str) -> dict:
    """War Gaming（World of Tanks/Warships/Warplanes）探测"""
    # WoT 多个服务器
    regions = ["na", "eu", "ru", "asia"]
    found_regions = []
    for region in regions:
        url = f"https://worldoftanks.{region}/community/accounts/search/?query={username}"
        try:
            async with httpx.AsyncClient(timeout=10, follow_redirects=True) as client:
                resp = await client.get(url, headers=DEFAULT_HEADERS)
                if resp.status_code == 200:
                    data = resp.json()
                    if data.get("data") and len(data["data"]) > 0:
                        account = data["data"][0]
                        found_regions.append({
                            "region": region,
                            "url": f"https://worldoftanks.{region}/community/accounts/{account.get('account_id', '')}",
                            "name": account.get("nickname", ""),
                        })
        except Exception:
            pass
    if found_regions:
        return {
            "status": "found",
            "platform": "WarGaming",
            "username": username,
            "url": found_regions[0]["url"],
            "snippet": f"在 {len(found_regions)} 个服务器找到: {', '.join(r['region'].upper() for r in found_regions)}",
        }
    return {"status": "not_found", "platform": "WarGaming", "username": username, "url": f"https://worldoftanks.com/community/accounts/search/?query={username}"}


async def probe_xbox(username: str) -> dict:
    """Xbox Live Gamertag 探测"""
    url = f"https://www.xboxgamertag.com/search/{username}"
    try:
        async with httpx.AsyncClient(timeout=15, follow_redirects=True) as client:
            resp = await client.get(url, headers=DEFAULT_HEADERS)
            if resp.status_code == 200 and "gamertag" in resp.text.lower():
                return {"status": "found", "platform": "XboxLive", "username": username, "url": url}
            return {"status": "not_found", "platform": "XboxLive", "username": username, "url": url}
    except Exception as e:
        return {"status": "error", "platform": "XboxLive", "username": username, "url": url, "error": str(e)[:100]}


async def probe_psn(username: str) -> dict:
    """PlayStation Network 探测 - 通过 PSNProfiles"""
    url = f"https://psnprofiles.com/{username}"
    try:
        async with httpx.AsyncClient(timeout=15, follow_redirects=True) as client:
            resp = await client.get(url, headers=DEFAULT_HEADERS)
            if resp.status_code == 200 and "profile" in resp.text.lower():
                return {"status": "found", "platform": "PlayStationNetwork", "username": username, "url": url}
            return {"status": "not_found", "platform": "PlayStationNetwork", "username": username, "url": url}
    except Exception as e:
        return {"status": "error", "platform": "PlayStationNetwork", "username": username, "url": url, "error": str(e)[:100]}


async def probe_battle_net(username: str) -> dict:
    """Battle.net 探测"""
    url = f"https://starcraft2.com/legacy/profile/1/1/{username}"
    try:
        async with httpx.AsyncClient(timeout=15, follow_redirects=True) as client:
            resp = await client.get(url, headers=DEFAULT_HEADERS)
            if resp.status_code == 200:
                return {"status": "found", "platform": "BattleNet", "username": username, "url": url}
            return {"status": "not_found", "platform": "BattleNet", "username": username, "url": url}
    except Exception as e:
        return {"status": "error", "platform": "BattleNet", "username": username, "url": url, "error": str(e)[:100]}


async def probe_twitch(username: str) -> dict:
    """Twitch 探测"""
    url = f"https://www.twitch.tv/{username}"
    try:
        async with httpx.AsyncClient(timeout=15, follow_redirects=True) as client:
            resp = await client.get(url, headers=DEFAULT_HEADERS)
            if resp.status_code == 200 and "channel" in resp.text.lower():
                return {"status": "found", "platform": "Twitch", "username": username, "url": url}
            return {"status": "not_found", "platform": "Twitch", "username": username, "url": url}
    except Exception as e:
        return {"status": "error", "platform": "Twitch", "username": username, "url": url, "error": str(e)[:100]}


async def probe_discord(username: str) -> dict:
    """Discord 探测（用户名无法直接探测，需要用户 ID）"""
    # Discord 用户名无法通过 HTTP 直接探测
    # 但可以检查 Discord 服务器邀请链接
    return {"status": "unknown", "platform": "Discord", "username": username, "url": "", "snippet": "Discord 需要用户 ID，无法通过用户名直接探测"}


async def probe_roblox(username: str) -> dict:
    """Roblox 探测 - 通过 Roblox API"""
    url = f"https://www.roblox.com/user.aspx?username={username}"
    try:
        async with httpx.AsyncClient(timeout=15, follow_redirects=True) as client:
            resp = await client.get(url, headers=DEFAULT_HEADERS)
            if resp.status_code == 200 and "Profile" in resp.text:
                return {"status": "found", "platform": "Roblox", "username": username, "url": resp.url}
            return {"status": "not_found", "platform": "Roblox", "username": username, "url": url}
    except Exception as e:
        return {"status": "error", "platform": "Roblox", "username": username, "url": url, "error": str(e)[:100]}


async def probe_minecraft(username: str) -> dict:
    """Minecraft 探测 - 通过 NameMC"""
    url = f"https://namemc.com/profile/{username}"
    try:
        async with httpx.AsyncClient(timeout=15, follow_redirects=True) as client:
            resp = await client.get(url, headers=DEFAULT_HEADERS)
            if resp.status_code == 200 and "profile" in resp.text.lower():
                return {"status": "found", "platform": "Minecraft", "username": username, "url": url}
            return {"status": "not_found", "platform": "Minecraft", "username": username, "url": url}
    except Exception as e:
        return {"status": "error", "platform": "Minecraft", "username": username, "url": url, "error": str(e)[:100]}


async def probe_fortnite(username: str) -> dict:
    """Fortnite 探测 - 通过 tracker.gg"""
    url = f"https://fortnitetracker.com/profile/all/{username}"
    try:
        async with httpx.AsyncClient(timeout=15, follow_redirects=True) as client:
            resp = await client.get(url, headers=DEFAULT_HEADERS)
            if resp.status_code == 200 and "profile" in resp.text.lower():
                return {"status": "found", "platform": "Fortnite", "username": username, "url": url}
            return {"status": "not_found", "platform": "Fortnite", "username": username, "url": url}
    except Exception as e:
        return {"status": "error", "platform": "Fortnite", "username": username, "url": url, "error": str(e)[:100]}


async def probe_csgo(username: str) -> dict:
    """CS:GO/CS2 探测 - 通过 tracker.gg"""
    url = f"https://tracker.gg/csgo/profile/steam/{username}"
    try:
        async with httpx.AsyncClient(timeout=15, follow_redirects=True) as client:
            resp = await client.get(url, headers=DEFAULT_HEADERS)
            if resp.status_code == 200 and "profile" in resp.text.lower():
                return {"status": "found", "platform": "CSGO", "username": username, "url": url}
            return {"status": "not_found", "platform": "CSGO", "username": username, "url": url}
    except Exception as e:
        return {"status": "error", "platform": "CSGO", "username": username, "url": url, "error": str(e)[:100]}


async def probe_faceit(username: str) -> dict:
    """FACEIT 探测 - 通过 FACEIT API"""
    url = f"https://www.faceit.com/en/players/{username}"
    try:
        async with httpx.AsyncClient(timeout=15, follow_redirects=True) as client:
            resp = await client.get(url, headers=DEFAULT_HEADERS)
            if resp.status_code == 200 and "player" in resp.text.lower():
                return {"status": "found", "platform": "Faceit", "username": username, "url": url}
            return {"status": "not_found", "platform": "Faceit", "username": username, "url": url}
    except Exception as e:
        return {"status": "error", "platform": "Faceit", "username": username, "url": url, "error": str(e)[:100]}


# 游戏平台列表（用于聊天端点快速探测）
GAME_PLATFORMS = [
    {"name": "Steam", "url": "https://steamcommunity.com/id/{username}"},
    {"name": "SteamGroup", "url": "https://steamcommunity.com/groups/{username}"},
    {"name": "EpicGames", "url": "https://store.epicgames.com/u/{username}"},
    {"name": "RiotGames", "url": "https://lol.op.gg/summoners/na/{username}"},
    {"name": "Valorant", "url": "https://tracker.gg/valorant/profile/riot/{username}"},
    {"name": "WarGaming", "url": "https://worldoftanks.com/community/accounts/search/?query={username}"},
    {"name": "XboxLive", "url": "https://www.xboxgamertag.com/search/{username}"},
    {"name": "PlayStationNetwork", "url": "https://psnprofiles.com/{username}"},
    {"name": "BattleNet", "url": "https://starcraft2.com/legacy/profile/1/1/{username}"},
    {"name": "Twitch", "url": "https://www.twitch.tv/{username}"},
    {"name": "Roblox", "url": "https://www.roblox.com/user.aspx?username={username}"},
    {"name": "Minecraft", "url": "https://namemc.com/profile/{username}"},
    {"name": "Fortnite", "url": "https://fortnitetracker.com/profile/all/{username}"},
    {"name": "CSGO", "url": "https://tracker.gg/csgo/profile/steam/{username}"},
    {"name": "Faceit", "url": "https://www.faceit.com/en/players/{username}"},
]


async def probe_game_platforms(username: str) -> list:
    """探测所有游戏平台"""
    tasks = []
    for platform in GAME_PLATFORMS:
        site = {"name": platform["name"], "url": platform["url"]}
        tasks.append(probe_platform(site, username))
    results = await asyncio.gather(*tasks, return_exceptions=False)
    return list(results)


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


# ==================== 从 Maigret 学习：递归身份挖掘 ====================

def extract_related_usernames(html: str, current_username: str) -> list:
    """从页面 HTML 中提取关联用户名/ID（Maigret 递归搜索核心）。

    提取策略：
    1. og:url / canonical 链接中的用户名
    2. 页面中的 @username 提及
    3. 社交媒体链接（twitter.com/xxx, instagram.com/xxx 等）
    4. data-username 属性
    """
    related = set()
    current_lower = (current_username or "").lower()

    # 1. 提取社交媒体链接中的用户名
    social_patterns = [
        r'(?:twitter\.com|x\.com)/([A-Za-z0-9_]{3,20})(?:/|\?|$)',
        r'instagram\.com/([A-Za-z0-9_.]{3,30})(?:/|\?|$)',
        r'github\.com/([A-Za-z0-9_-]{2,39})(?:/|\?|$)',
        r'reddit\.com/u(?:ser)?/([A-Za-z0-9_-]{3,20})(?:/|\?|$)',
        r'twitch\.tv/([A-Za-z0-9_]{3,25})(?:/|\?|$)',
        r'youtube\.com/(?:c|hannel|user)/([A-Za-z0-9_-]{3,40})(?:/|\?|$)',
        r'tiktok\.com/@([A-Za-z0-9_.]{3,24})(?:/|\?|$)',
        r'facebook\.com/([A-Za-z0-9.]{5,50})(?:/|\?|$)',
        r'linkedin\.com/in/([A-Za-z0-9_-]{3,100})(?:/|\?|$)',
        r't.me/([A-Za-z0-9_]{3,32})(?:/|\?|$)',
        r'discord\.gg/([A-Za-z0-9]{3,100})',
    ]
    for pat in social_patterns:
        for m in re.finditer(pat, html or "", re.IGNORECASE):
            uname = m.group(1)
            if uname.lower() not in ("p", "home", "search", "login", "signup", "register", "watch", "videos", "photos", "posts", current_lower):
                related.add(uname)

    # 2. 提取 @username 提及
    for m in re.finditer(r'(?:^|\s)@([A-Za-z0-9_]{3,20})', html or ""):
        uname = m.group(1)
        if uname.lower() != current_lower:
            related.add(uname)

    # 3. 限制数量，避免过多噪音
    return list(related)[:10]


def extract_metadata(result: dict) -> dict:
    """从探测结果中提取用户元数据（Blackbird 风格）。

    提取：头像、bio、位置、关注数、粉丝数、账号创建时间等。
    """
    metadata = {}
    extra = result.get("extra") or {}
    snippet = result.get("snippet") or ""

    # 头像
    avatar = extra.get("og_image") or extra.get("avatar_url") or extra.get("profile_image_url")
    if avatar:
        metadata["avatar"] = avatar

    # bio
    bio = extra.get("bio") or extra.get("biography")
    if not bio:
        m = re.search(r'(?:Bio|biography|Description)[:\s]+(.+?)(?:\||$)', snippet, re.I)
        bio = m.group(1).strip() if m else ""
    if bio:
        metadata["bio"] = bio[:200]

    # 位置
    location = extra.get("location") or extra.get("city") or extra.get("country")
    if not location:
        m = re.search(r'(?:Location|位置|地点|Based in)[:\s]+(.+?)(?:\||$)', snippet, re.I)
        location = m.group(1).strip() if m else ""
    if location:
        metadata["location"] = location[:100]

    # 关注数/粉丝数
    followers = extra.get("followers") or extra.get("follower_count")
    if not followers:
        m = re.search(r'(?:Followers|粉丝|followers)[:\s]+([\d,]+)', snippet, re.I)
        followers = m.group(1) if m else ""
    if followers:
        metadata["followers"] = str(followers)

    following = extra.get("following") or extra.get("following_count")
    if not following:
        m = re.search(r'(?:Following|关注|following)[:\s]+([\d,]+)', snippet, re.I)
        following = m.group(1) if m else ""
    if following:
        metadata["following"] = str(following)

    # 账号创建时间
    created = extra.get("created_at") or extra.get("created") or extra.get("join_date")
    if not created:
        m = re.search(r'(?:Created|创建|Joined|注册)[:\s]+(\d{4}[-/]\d{2}[-/]\d{2})', snippet, re.I)
        created = m.group(1) if m else ""
    if created:
        metadata["created"] = created

    # 真实姓名
    name = extra.get("name") or extra.get("real_name") or extra.get("display_name")
    if not name:
        m = re.search(r'(?:Name|名称|姓名)[:\s]+(.+?)(?:\||$)', snippet, re.I)
        name = m.group(1).strip() if m else ""
    if name:
        metadata["name"] = name[:100]

    # 邮箱（从 bio 或 snippet 中提取）
    emails = re.findall(r'[\w.+-]+@[\w-]+\.[\w.-]+', snippet + " " + (bio or ""))
    if emails:
        metadata["emails"] = list(set(emails))[:3]

    return metadata


def calculate_confidence(result: dict) -> int:
    """计算探测结果的置信度评分（Social Analyzer 风格，0-100）。

    评分依据：
    - 状态码 200 且有 presence 指标验证: +40
    - 有 og:image / 头像: +20
    - 有 bio / snippet: +15
    - 有 followers 数据: +10
    - URL 可访问（非 404/410）: +15
    """
    if result.get("status") != "found":
        return 0

    score = 0

    # presence 指标验证
    if result.get("verified"):
        score += 40

    # 有 snippet
    snippet = result.get("snippet") or ""
    if snippet:
        score += 15

    # extra 中有元数据
    extra = result.get("extra") or {}
    if extra.get("og_image") or extra.get("avatar_url"):
        score += 20
    if extra.get("followers") or extra.get("follower_count"):
        score += 10

    # URL 存在
    if result.get("url"):
        score += 15

    return min(score, 100)


async def recursive_probe(
    username: str,
    sites: list,
    max_depth: int = 2,
    concurrency: int = 10,
    progress_callback=None,
) -> dict:
    """递归身份挖掘（Maigret 核心功能）。

    探测到账号后，从页面中提取关联用户名，自动二次搜索。

    Args:
        username: 初始目标用户名
        sites: 站点列表
        max_depth: 递归深度（默认 2 层）
        concurrency: 并发数
        progress_callback: async callback(current, total, message)

    Returns:
        {
            "original": [原始探测结果],
            "related": [{"username": "xxx", "source": "GitHub", "results": [...]}],
            "graph": {"nodes": [...], "links": [...]},  # 关系图谱数据
        }
    """
    visited = {username.lower()}
    all_results = []
    related_findings = []
    graph_nodes = [{"id": username, "type": "root", "platform": "target"}]
    graph_links = []

    # 第一轮探测
    if progress_callback:
        await progress_callback(0, max_depth, f"🔍 递归探测第 1 轮: {username}")

    results = await probe_batch(sites, username, concurrency)
    found = [r for r in results if r.get("status") == "found"]
    all_results.extend(found)

    # 提取关联用户名
    for r in found:
        platform = r.get("platform", "?")
        graph_nodes.append({"id": f"{username}@{platform}", "type": "account", "platform": platform, "url": r.get("url", "")})
        graph_links.append({"source": username, "target": f"{username}@{platform}"})

        # 从 extra 中获取 HTML（如果有）
        extra = r.get("extra") or {}
        html = extra.get("html") or extra.get("raw_html") or ""
        if not html:
            # 从 snippet 中提取
            html = r.get("snippet") or ""

        related = extract_related_usernames(html, username)
        for rel_user in related:
            if rel_user.lower() not in visited:
                visited.add(rel_user.lower())
                graph_nodes.append({"id": rel_user, "type": "related", "source": platform})
                graph_links.append({"source": f"{username}@{platform}", "target": rel_user, "type": "mentions"})

    # 递归探测关联用户名
    for depth in range(2, max_depth + 1):
        new_users = [n["id"] for n in graph_nodes if n.get("type") == "related" and n["id"] not in visited]
        if not new_users:
            break

        for rel_user in new_users[:5]:  # 每轮最多探测 5 个关联用户
            visited.add(rel_user.lower())
            if progress_callback:
                await progress_callback(depth - 1, max_depth, f"🔍 递归探测第 {depth} 轮: {rel_user}")

            rel_results = await probe_batch(sites[:20], rel_user, concurrency)  # 关联用户只探测 top 20
            rel_found = [r for r in rel_results if r.get("status") == "found"]

            if rel_found:
                related_findings.append({
                    "username": rel_user,
                    "source": "recursive",
                    "results": rel_found,
                })
                for r in rel_found:
                    platform = r.get("platform", "?")
                    graph_nodes.append({"id": f"{rel_user}@{platform}", "type": "account", "platform": platform})
                    graph_links.append({"source": rel_user, "target": f"{rel_user}@{platform}"})

    if progress_callback:
        await progress_callback(max_depth, max_depth, f"✅ 递归探测完成: {len(all_results)} 个直接命中, {len(related_findings)} 个关联用户")

    return {
        "original": all_results,
        "related": related_findings,
        "graph": {"nodes": graph_nodes, "links": graph_links},
    }
