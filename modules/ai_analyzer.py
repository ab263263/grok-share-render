"""AI 分析模块：调用 Grok AI 进行 OSINT 情报分析。

利用 Grok 的实时搜索能力（思维链 + 网页爬虫）进行深度情报收集。
"""

import httpx
import json
import re
import asyncio

# Grok API 后端配置
GROK_BASE_URL = "https://grok2api-2-hpc2.onrender.com"
GROK_API_KEY = "c9d05cfdfd6b4dbc8f13f474"
GROK_ENDPOINT = f"{GROK_BASE_URL}/v1/chat/completions"

# 模型常量（grok2api 后端支持的模型）
MODEL_FAST = "grok-4.20-fast"  # 快速响应
MODEL_DEEP = "grok-4.20-0309-non-reasoning"  # 深度分析 + 实时搜索（无推理链，低延迟）
MODEL_IMAGE = "grok-imagine-image-lite"  # 图像生成
# 注意：grok-4.20-0309-reasoning 模型不可用


def call_grok(messages: list[dict], model: str = MODEL_DEEP, temperature: float = 0.7, timeout: float = 120.0) -> str:
    """通用 Grok API 调用函数（同步版本）。

    Args:
        messages: OpenAI 兼容的 messages 列表
        model: 模型名称（默认用 DEEP 模型，支持搜索）
        temperature: 采样温度
        timeout: 超时时间（秒），搜索任务需要更长

    Returns:
        模型生成的文本内容；调用失败时返回空字符串
    """
    headers = {
        "Authorization": f"Bearer {GROK_API_KEY}",
        "Content-Type": "application/json",
    }
    payload = {
        "model": model,
        "messages": messages,
        "temperature": temperature,
        "max_tokens": 4000,
        "stream": False,
    }
    try:
        with httpx.Client(timeout=timeout) as client:
            resp = client.post(GROK_ENDPOINT, headers=headers, json=payload)
            resp.raise_for_status()
            # 尝试 JSON 解析，失败则尝试原始文本
            try:
                data = resp.json()
                return data["choices"][0]["message"]["content"]
            except Exception:
                # 可能是 SSE 流式响应，尝试解析最后一行 data
                raw = resp.text
                for line in reversed(raw.split("\n")):
                    line = line.strip()
                    if line.startswith("data: ") and line != "data: [DONE]":
                        try:
                            d = json.loads(line[6:])
                            content = d.get("choices", [{}])[0].get("delta", {}).get("content", "")
                            if content:
                                return content
                        except Exception:
                            continue
                return ""
    except Exception as e:
        print(f"[call_grok] 调用失败: {e}")
        return ""


async def call_grok_async(messages: list[dict], model: str = MODEL_DEEP, temperature: float = 0.7, timeout: float = 120.0) -> str:
    """通用 Grok API 调用函数（异步版本）。

    Args:
        messages: OpenAI 兼容的 messages 列表
        model: 模型名称（默认用 DEEP 模型，支持搜索）
        temperature: 采样温度
        timeout: 超时时间（秒），搜索任务需要更长

    Returns:
        模型生成的文本内容；调用失败时返回空字符串
    """
    headers = {
        "Authorization": f"Bearer {GROK_API_KEY}",
        "Content-Type": "application/json",
    }
    payload = {
        "model": model,
        "messages": messages,
        "temperature": temperature,
        "max_tokens": 4000,
        "stream": False,
    }
    try:
        async with httpx.AsyncClient(timeout=timeout) as client:
            resp = await client.post(GROK_ENDPOINT, headers=headers, json=payload)
            resp.raise_for_status()
            # 尝试 JSON 解析，失败则尝试原始文本
            try:
                data = resp.json()
                return data["choices"][0]["message"]["content"]
            except Exception:
                # 可能是 SSE 流式响应，尝试解析最后一行 data
                raw = resp.text
                for line in reversed(raw.split("\n")):
                    line = line.strip()
                    if line.startswith("data: ") and line != "data: [DONE]":
                        try:
                            d = json.loads(line[6:])
                            content = d.get("choices", [{}])[0].get("delta", {}).get("content", "")
                            if content:
                                return content
                        except Exception:
                            continue
                return ""
    except Exception as e:
        print(f"[call_grok_async] 调用失败: {e}")
        return ""


def grok_search(target: str, sites: list = None) -> dict:
    """利用 Grok 的实时搜索能力搜索目标用户名。

    Grok 会自动搜索互联网，访问网站，爬取网页内容，
    然后总结提炼信息。这是核心优势：Grok 自带的搜索 AI 爬虫。

    Args:
        target: 目标用户名
        sites: 可选的站点列表，提供给 Grok 让它搜索这些平台

    Returns:
        {
            "summary": "Grok 的搜索总结",
            "platforms": [{"platform": "...", "url": "...", "snippet": "..."}],
            "personal_info": {"name": "...", "location": "...", "email": "...", ...},
            "raw": "原始回复"
        }
    """
    # 构建搜索 prompt
    base_prompt = (
        f"Search the web for the username '{target}'. "
        f"Find ALL platforms where this username has an account. "
    )

    if sites:
        # 提供站点列表给 Grok
        site_list = "\n".join(
            f"- {s.get('name', '?')}: {s.get('url', '').replace('{username}', target)}"
            for s in sites[:50]  # 最多 50 个站点
        )
        base_prompt += (
            f"Please check the following platforms specifically:\n{site_list}\n\n"
            f"For each platform, visit the URL and check if the profile exists. "
        )
    else:
        base_prompt += (
            f"Check GitHub, Reddit, Twitter/X, Instagram, Facebook, TikTok, "
            f"YouTube, Twitch, Discord, Steam, Pinterest, LinkedIn, Tumblr, "
            f"DeviantArt, Flickr, SoundCloud, Spotify, Medium, Patreon, etc. "
        )

    base_prompt += (
        f"\nFor each platform found:\n"
        f"1. Provide the profile URL\n"
        f"2. Extract any personal information (real name, bio, location, email, age)\n"
        f"3. Note the account creation date if visible\n"
        f"4. Note follower/following counts if visible\n\n"
        f"Also search for any leaked data, breach records, or public records "
        f"associated with this username. Search X/Twitter for posts mentioning "
        f"this username.\n\n"
        f"Finally, provide a comprehensive summary of everything you found, "
        f"including a risk assessment and recommended next steps for investigation."
    )

    messages = [{"role": "user", "content": base_prompt}]
    text = call_grok(messages, model=MODEL_DEEP, temperature=0.7, timeout=180.0)

    if not text:
        return {"summary": "", "platforms": [], "personal_info": {}, "raw": ""}

    # 解析引用链接 [[N]](url) 格式
    platforms = []
    seen_urls = set()

    # 提取所有引用链接
    citations = re.findall(r'\[\[(\d+)\]\]\((https?://[^\s)]+)\)', text)
    for num, url in citations:
        if url not in seen_urls:
            seen_urls.add(url)
            platform = _infer_platform(url)
            platforms.append({"platform": platform, "url": url, "snippet": ""})

    # 提取 Markdown 链接 [text](url)
    md_links = re.findall(r'\[([^\]]+)\]\((https?://[^\s)]+)\)', text)
    for link_text, url in md_links:
        if url not in seen_urls and not url.startswith("#"):
            seen_urls.add(url)
            platform = _infer_platform(url)
            platforms.append({"platform": platform or link_text, "url": url, "snippet": link_text})

    # 提取裸 URL
    bare_urls = re.findall(r'(https?://[^\s\]\)]+)', text)
    for url in bare_urls:
        url = url.rstrip(".,;")
        if url not in seen_urls:
            seen_urls.add(url)
            platform = _infer_platform(url)
            if platform:
                platforms.append({"platform": platform, "url": url, "snippet": ""})

    # 提取个人信息
    personal_info = _extract_personal_info(text)

    return {
        "summary": text[:2000],
        "platforms": platforms,
        "personal_info": personal_info,
        "raw": text,
    }


def _extract_personal_info(text: str) -> dict:
    """从 Grok 回复中提取个人信息"""
    info = {}

    # 提取邮箱
    emails = re.findall(r'[\w.+-]+@[\w-]+\.[\w.-]+', text)
    if emails:
        info["emails"] = list(set(emails))[:5]

    # 提取电话号码
    phones = re.findall(r'\b\d{3}[-.]?\d{3}[-.]?\d{4}\b', text)
    if phones:
        info["phones"] = list(set(phones))[:3]

    # 提取位置信息
    loc_match = re.search(r'(?:location|位置|地点|地址|based in|from)\s*[:：]?\s*([^\n,]{3,50})', text, re.I)
    if loc_match:
        info["location"] = loc_match.group(1).strip()

    # 提取真实姓名
    name_match = re.search(r'(?:real name|真实姓名|本名|name)\s*[:：]?\s*([^\n,]{3,50})', text, re.I)
    if name_match:
        info["real_name"] = name_match.group(1).strip()

    # 提取年龄
    age_match = re.search(r'(?:age|年龄|岁)\s*[:：]?\s*(\d{1,3})', text, re.I)
    if age_match:
        info["age"] = age_match.group(1)

    return info


async def grok_batch_probe(target: str, sites: list, batch_size: int = 50, progress_callback=None) -> list:
    """使用 Grok 批量探测站点，替代 Python 的 httpx 探测（异步版本）。

    Grok 可以绕过很多反爬虫机制，直接访问网站并提取内容。

    Args:
        target: 目标用户名
        sites: Maigret 站点列表
        batch_size: 每批处理的站点数（默认 50）
        progress_callback: 异步进度回调函数，签名 async callback(current, total, message)

    Returns:
        发现的站点列表，格式：[{"platform": "...", "url": "...", "snippet": "..."}]
    """
    found_results = []
    total_batches = (len(sites) + batch_size - 1) // batch_size

    for i in range(0, len(sites), batch_size):
        batch = sites[i:i + batch_size]
        batch_num = i // batch_size + 1

        if progress_callback:
            await progress_callback(batch_num, total_batches, f"Grok 探测批次 {batch_num}/{total_batches} ({len(batch)} 个站点)")

        # 构建站点 URL 列表
        site_urls = []
        for s in batch:
            url_template = s.get("url", "")
            if "{username}" in url_template:
                url = url_template.replace("{username}", target)
                site_urls.append(f"- {s.get('name', '?')}: {url}")

        if not site_urls:
            continue

        prompt = (
            f"请检查以下 {len(batch)} 个网站，看用户名 '{target}' 是否注册了账号：\n\n"
            f"{chr(10).join(site_urls)}\n\n"
            f"对于每个网站：\n"
            f"1. 访问 URL，检查页面是否存在\n"
            f"2. 如果存在，提取页面标题和简介\n"
            f"3. 如果不存在或显示 '用户不存在'，跳过\n\n"
            f"请以 JSON 格式返回结果：\n"
            f'```json\n'
            f'[\n'
            f'  {{"platform": "网站名", "url": "完整URL", "snippet": "页面简介"}},\n'
            f'  ...\n'
            f']\n'
            f'```\n\n'
            f"只返回存在的账号，不要返回不存在的。"
        )

        messages = [{"role": "user", "content": prompt}]
        response = await call_grok_async(messages, model=MODEL_DEEP, temperature=0.3, timeout=180.0)

        # 解析 JSON 结果
        if response:
            try:
                # 尝试提取 JSON 代码块
                json_match = re.search(r'```json\s*(\{.*?\}|\[.*?\])\s*```', response, re.DOTALL)
                if json_match:
                    json_str = json_match.group(1)
                    batch_results = json.loads(json_str)
                    if isinstance(batch_results, list):
                        found_results.extend(batch_results)
                else:
                    # 尝试直接解析
                    batch_results = json.loads(response)
                    if isinstance(batch_results, list):
                        found_results.extend(batch_results)
            except Exception as e:
                print(f"[grok_batch_probe] 解析批次 {batch_num} 失败: {e}")

    if progress_callback:
        await progress_callback(total_batches, total_batches, f"Grok 探测完成，发现 {len(found_results)} 个站点")

    return found_results


def grok_deep_analysis(target: str, findings: list[dict]) -> str:
    """使用推理模式进行深度情报分析。

    利用 Grok 的扩展思维链，对收集到的情报进行深度分析。
    """
    findings_text = ""
    for f in findings[:20]:
        findings_text += f"- [{f.get('platform', '?')}] {f.get('url', '')}\n"
        if f.get("snippet"):
            findings_text += f"  → {f['snippet'][:150]}\n"

    messages = [
        {
            "role": "user",
            "content": (
                f"你是 OSINT 情报分析专家。目标用户名: {target}\n\n"
                f"收集到的情报:\n{findings_text}\n\n"
                f"请进行深度分析：\n"
                f"1. 交叉验证：哪些账号可能是同一人？\n"
                f"2. 时间线分析：账号创建时间、活动模式\n"
                f"3. 社交网络图谱：账号之间的关联\n"
                f"4. 风险评估：虚假账号、机器人、钓鱼可能性\n"
                f"5. 推荐下一步：还需要搜索什么？\n\n"
                f"用中文回复，格式清晰。"
            ),
        }
    ]
    return call_grok(messages, model=MODEL_DEEP, temperature=0.7, timeout=180.0)


def _infer_platform(url: str) -> str:
    """从 URL 推断平台名称"""
    url_lower = url.lower()
    platform_map = {
        "github.com": "GitHub",
        "reddit.com": "Reddit",
        "twitter.com": "Twitter",
        "x.com": "X",
        "instagram.com": "Instagram",
        "facebook.com": "Facebook",
        "tiktok.com": "TikTok",
        "youtube.com": "YouTube",
        "twitch.tv": "Twitch",
        "discord.com": "Discord",
        "discord.gg": "Discord",
        "steamcommunity.com": "Steam",
        "pinterest.com": "Pinterest",
        "linkedin.com": "LinkedIn",
        "tumblr.com": "Tumblr",
        "deviantart.com": "DeviantArt",
        "flickr.com": "Flickr",
        "soundcloud.com": "SoundCloud",
        "spotify.com": "Spotify",
        "medium.com": "Medium",
        "patreon.com": "Patreon",
        "gitlab.com": "GitLab",
        "stackoverflow.com": "StackOverflow",
        "hackernews": "HackerNews",
        "producthunt.com": "ProductHunt",
        "behance.net": "Behance",
        "dribbble.com": "Dribbble",
        "mastodon": "Mastodon",
        "telegram.me": "Telegram",
        "t.me": "Telegram",
        "vk.com": "VK",
        "weibo.com": "Weibo",
        "bilibili.com": "Bilibili",
    }
    for domain, name in platform_map.items():
        if domain in url_lower:
            return name
    return ""


def _parse_json(text: str) -> dict | None:
    """从模型输出文本中解析 JSON。

    模型可能返回带 ```json 代码块或额外说明的文本，
    这里尝试多种方式提取 JSON。
    """
    if not text:
        return None
    # 直接尝试解析
    try:
        return json.loads(text)
    except Exception:
        pass
    # 尝试提取 ```json ... ``` 代码块
    try:
        start = text.find("```json")
        if start != -1:
            start = text.find("{", start)
            end = text.rfind("}")
            if start != -1 and end != -1 and end > start:
                return json.loads(text[start:end + 1])
    except Exception:
        pass
    # 尝试提取首个 { ... } 片段
    try:
        start = text.find("{")
        end = text.rfind("}")
        if start != -1 and end != -1 and end > start:
            return json.loads(text[start:end + 1])
    except Exception:
        pass
    return None


def plan_strategy(target: str) -> dict:
    """策略规划：分析目标用户名，生成搜索策略。

    Args:
        target: 目标用户名

    Returns:
        策略 dict，解析失败时返回默认策略
    """
    default_strategy = {
        "primary_query": target,
        "variants": [target],
        "site_tags": ["social", "coding"],
        "platforms_to_focus": ["GitHub", "Reddit"],
        "notes": "默认策略（AI 解析失败）",
    }
    messages = [
        {
            "role": "system",
            "content": "你是一名 OSINT 情报分析师。分析目标用户名，生成搜索策略。",
        },
        {
            "role": "user",
            "content": (
                f"分析用户名 `{target}`，返回 JSON：\n"
                "{\n"
                '  "primary_query": "搜索查询词",\n'
                '  "variants": ["变体1", "变体2"],\n'
                '  "site_tags": ["social", "coding"],\n'
                '  "platforms_to_focus": ["GitHub", "Reddit"],\n'
                '  "notes": "分析备注"\n'
                "}\n"
                "只返回 JSON，不要额外说明。"
            ),
        },
    ]
    text = call_grok(messages, model=MODEL_FAST, temperature=0.7)
    parsed = _parse_json(text)
    if not parsed:
        print("[plan_strategy] JSON 解析失败，使用默认策略")
        return default_strategy
    # 校验必要字段，缺失则补默认值
    parsed.setdefault("primary_query", target)
    parsed.setdefault("variants", [target])
    parsed.setdefault("site_tags", ["social", "coding"])
    parsed.setdefault("platforms_to_focus", ["GitHub", "Reddit"])
    parsed.setdefault("notes", "")
    return parsed


def analyze_findings(target: str, strategy: dict, findings: list[dict]) -> dict:
    """分析命中线索，提取关联身份和新 ID。

    Args:
        target: 目标用户名
        strategy: 搜索策略 dict
        findings: 命中线索列表，每项包含 platform/username/url/snippet

    Returns:
        分析结果 dict，包含 analysis 与 new_ids 字段
    """
    default_result = {
        "analysis": "",
        "new_ids": [],
    }
    # 将 findings 格式化为文本
    if findings:
        lines = []
        for idx, item in enumerate(findings, start=1):
            platform = item.get("platform", "")
            username = item.get("username", "")
            url = item.get("url", "")
            snippet = item.get("snippet", "")
            lines.append(
                f"{idx}. [平台: {platform}] 用户名: {username}\n"
                f"   URL: {url}\n"
                f"   片段: {snippet}"
            )
        findings_text = "\n".join(lines)
    else:
        findings_text = "（无命中线索）"

    messages = [
        {
            "role": "system",
            "content": "你是一名 OSINT 情报分析师。分析探测结果，提取关联身份和新 ID。",
        },
        {
            "role": "user",
            "content": (
                f"分析目标 `{target}` 的命中线索，返回 JSON：\n"
                "{\n"
                '  "analysis": "分析文本（关联性、可信度、推断画像）",\n'
                '  "new_ids": ["新发现的用户名/ID"]\n'
                "}\n"
                f"命中线索如下：\n{findings_text}\n"
                "只返回 JSON，不要额外说明。"
            ),
        },
    ]
    text = call_grok(messages, model=MODEL_DEEP, temperature=0.7)
    parsed = _parse_json(text)
    if not parsed:
        print("[analyze_findings] JSON 解析失败，使用默认结果")
        return default_result
    parsed.setdefault("analysis", "")
    parsed.setdefault("new_ids", [])
    return parsed


def finalize_profile(target: str, strategy: dict, findings: list[dict], analysis: str) -> str:
    """生成最终情报档案（Markdown 格式）。

    Args:
        target: 目标用户名
        strategy: 搜索策略 dict
        findings: 命中线索列表
        analysis: analyze_findings 返回的分析文本

    Returns:
        Markdown 格式的情报档案文本；失败时返回基础模板
    """
    # 将 findings 格式化为文本
    if findings:
        lines = []
        for idx, item in enumerate(findings, start=1):
            platform = item.get("platform", "")
            username = item.get("username", "")
            url = item.get("url", "")
            snippet = item.get("snippet", "")
            lines.append(
                f"{idx}. [平台: {platform}] 用户名: {username}\n"
                f"   URL: {url}\n"
                f"   片段: {snippet}"
            )
        findings_text = "\n".join(lines)
    else:
        findings_text = "（无命中线索）"

    messages = [
        {
            "role": "system",
            "content": "你是一名 OSINT 情报分析师。基于所有线索生成结构化情报档案。",
        },
        {
            "role": "user",
            "content": (
                f"为目标 `{target}` 生成 Markdown 格式情报档案，包含：\n"
                "- 身份判定（可信度百分比）\n"
                "- 基本信息（姓名/ID/别名、职业、地区）\n"
                "- 账号清单（表格）\n"
                "- 关联线索\n"
                "- 推断画像\n"
                "- 风险与不确定性\n"
                "- 来源索引\n\n"
                f"搜索策略：\n{json.dumps(strategy, ensure_ascii=False, indent=2)}\n\n"
                f"命中线索：\n{findings_text}\n\n"
                f"分析结论：\n{analysis}\n\n"
                "只返回 Markdown 文本，不要额外说明。"
            ),
        },
    ]
    text = call_grok(messages, model=MODEL_DEEP, temperature=0.7)
    if not text:
        # 失败时返回基础模板
        print("[finalize_profile] 生成失败，返回基础模板")
        return (
            f"# 情报档案：{target}\n\n"
            "## 身份判定\n- 可信度：未知（生成失败）\n\n"
            "## 基本信息\n- 目标用户名：{target}\n\n"
            "## 账号清单\n| 平台 | 用户名 | URL |\n| --- | --- | --- |\n\n"
            "## 关联线索\n- 无\n\n"
            "## 推断画像\n- 无\n\n"
            "## 风险与不确定性\n- AI 生成失败，需人工复核\n\n"
            "## 来源索引\n- 无\n"
        ).format(target=target)
    return text
