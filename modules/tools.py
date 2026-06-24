"""OSINT 工具注册表 + AI 决策器 + 执行器（Function Calling 风格）。

让 agent 能根据用户意图智能选择并调用工具，而不是硬编码关键词匹配。

工作流程：
1. 用户发送消息
2. AI 决策器（Grok FAST 模型）分析消息，决定调用哪些工具
3. 工具执行器并发执行选中的工具，通过 progress_queue 推送进度
4. 收集所有工具结果，交给主 AI 生成最终回复
"""

import json
import re
import asyncio
import httpx
from typing import Any

from modules import ai_analyzer, maigret_sites, probes, variants, search_engines, reports


# ==================== 工具定义 ====================

TOOLS = [
    {
        "name": "username_probe",
        "description": "探测用户名在多个平台是否存在（Maigret 站点，默认 top 100）",
        "category": "probe",
        "params": {"username": "str", "limit": "int=100", "concurrency": "int=15"},
        "keywords": ["探测", "probe", "查找用户名", "检查账号", "搜索", "查找", "调查", "查一下", "search", "find", "lookup"],
    },
    {
        "name": "recursive_probe",
        "description": "递归身份挖掘：探测账号后提取关联用户名，自动二次搜索（Maigret 核心）",
        "category": "probe",
        "params": {"username": "str", "max_depth": "int=2", "limit": "int=50"},
        "keywords": ["递归", "深度挖掘", "关联", "recursive", "maigret", "挖掘", "关系", "图谱", "graph"],
    },
    {
        "name": "game_probe",
        "description": "探测 15 个游戏平台（Steam/LoL/Xbox/PSN/Fortnite 等）",
        "category": "probe",
        "params": {"username": "str"},
        "keywords": ["游戏", "game", "steam", "lol", "xbox", "psn", "fortnite", "valorant", "minecraft", "twitch"],
    },
    {
        "name": "grok_search",
        "description": "Grok AI 实时搜索：利用 Grok 自带的搜索爬虫查找目标（绕过反爬虫）",
        "category": "search",
        "params": {"target": "str"},
        "keywords": ["grok搜索", "ai搜索", "智能搜索", "grok", "实时搜索"],
    },
    {
        "name": "deep_analysis",
        "description": "深度分析：交叉验证、时间线、社交图谱、风险评估、推荐下一步",
        "category": "analysis",
        "params": {"target": "str", "findings": "list"},
        "keywords": ["深度分析", "分析", "analyze", "deep", "画像", "风险评估"],
    },
    {
        "name": "full_search",
        "description": "全站搜索：探测所有 1836 个 Maigret 站点（耗时较长）",
        "category": "probe",
        "params": {"username": "str", "concurrency": "int=20"},
        "keywords": ["全站", "所有站点", "1836", "全部", "all", " exhaustive"],
    },
    {
        "name": "generate_variants",
        "description": "生成用户名变体（数字、下划线、常见拼写、leet 变换）",
        "category": "util",
        "params": {"username": "str"},
        "keywords": ["变体", "variants", "相似用户名", "别名", "alias"],
    },
    {
        "name": "export_report",
        "description": "导出情报报告（HTML/CSV/JSON/PDF 格式，含关系图谱）",
        "category": "report",
        "params": {"target": "str", "format": "str=html", "results": "list"},
        "keywords": ["报告", "导出", "report", "export", "pdf", "csv", "html", "json", "下载"],
    },
    {
        "name": "email_lookup",
        "description": "邮箱反查：查找邮箱关联的账号、泄露记录（Have I Been Pwned 风格）",
        "category": "osint",
        "params": {"email": "str"},
        "keywords": ["邮箱", "email", "mail", "e-mail", "泄露", "breach", "pwned"],
    },
    {
        "name": "domain_lookup",
        "description": "域名/IP 查询：WHOIS、DNS 记录、地理位置、子域名",
        "category": "osint",
        "params": {"domain": "str"},
        "keywords": ["域名", "domain", "ip", "whois", "dns", "子域名", "服务器"],
    },
    {
        "name": "search_engine",
        "description": "搜索引擎爬取：Google/Bing/DuckDuckGo 搜索 + 内容提取",
        "category": "search",
        "params": {"query": "str", "max_results": "int=5"},
        "keywords": ["google", "bing", "搜索引擎", "搜索网页", "duckduckgo"],
    },
    {
        "name": "phone_lookup",
        "description": "电话号码反查：归属地、运营商、关联账号",
        "category": "osint",
        "params": {"phone": "str"},
        "keywords": ["电话", "phone", "手机", "号码", "归属地"],
    },
]


def get_tool_descriptions() -> list[dict]:
    """获取工具描述列表（供 AI 决策用）"""
    return [{"name": t["name"], "description": t["description"], "category": t["category"]} for t in TOOLS]


def get_tool_by_name(name: str) -> dict | None:
    """按名称获取工具定义"""
    for t in TOOLS:
        if t["name"] == name:
            return t
    return None


# ==================== AI 决策器 ====================

async def decide_tools(message: str, target: str = None) -> list[str]:
    """让 AI 决策调用哪些工具。

    使用 Grok FAST 模型快速决策，返回工具名称列表。
    如果 AI 决策失败，回退到关键词匹配。

    Args:
        message: 用户消息
        target: 当前调查目标（可选）

    Returns:
        工具名称列表，如 ["username_probe", "grok_search", "game_probe"]
    """
    # 先尝试关键词快速匹配（避免每次都调用 AI）
    keyword_tools = _match_keywords(message, target)
    if keyword_tools:
        return keyword_tools

    # 复杂意图交给 AI 决策
    try:
        tools_desc = get_tool_descriptions()
        prompt = (
            f"你是 OSINT 情报分析智能体的工具调度器。根据用户消息，决定需要调用哪些工具。\n\n"
            f"用户消息: {message}\n"
            f"当前目标: {target or '未指定'}\n\n"
            f"可用工具:\n{json.dumps(tools_desc, ensure_ascii=False, indent=2)}\n\n"
            f"请返回要调用的工具名称列表（JSON 数组格式），如:\n"
            f'["username_probe", "grok_search", "game_probe"]\n\n'
            f"规则:\n"
            f"1. 如果用户只是闲聊或提问（无调查意图），返回空数组 []\n"
            f"2. 如果用户要调查某用户名，至少调用 username_probe\n"
            f"3. 如果用户要深度挖掘，调用 recursive_probe\n"
            f"4. 如果用户要分析，调用 deep_analysis\n"
            f"5. 如果用户要导出报告，调用 export_report\n"
            f"6. 如果用户要查邮箱/域名/电话，调用对应工具\n"
            f"7. 只返回 JSON 数组，不要其他文字"
        )
        messages = [{"role": "user", "content": prompt}]
        text = await ai_analyzer.call_grok_async(messages, model=ai_analyzer.MODEL_FAST, temperature=0.3, timeout=30.0)

        if text:
            # 解析 JSON 数组
            parsed = ai_analyzer._parse_json(text)
            if isinstance(parsed, list):
                # 过滤无效工具名
                valid_names = {t["name"] for t in TOOLS}
                return [name for name in parsed if name in valid_names]
            # 尝试直接解析数组
            match = re.search(r'\[([^\]]*)\]', text)
            if match:
                names = [n.strip().strip('"\'') for n in match.group(1).split(",") if n.strip()]
                valid_names = {t["name"] for t in TOOLS}
                return [name for name in names if name in valid_names]
    except Exception as e:
        print(f"[decide_tools] AI 决策失败: {e}")

    # 兜底：返回默认工具
    if target:
        return ["username_probe", "grok_search", "game_probe"]
    return []


def _match_keywords(message: str, target: str = None) -> list[str]:
    """关键词快速匹配（避免每次都调用 AI）。"""
    msg_lower = message.lower()
    tools = []

    # 检测目标（用户名/邮箱/域名/电话）
    has_username = bool(target) or bool(re.search(r'@(\w{3,30})', message)) or bool(re.search(r'(?:搜索|查找|调查|查一下)\s+[@]?(\w+)', message, re.I))
    has_email = bool(re.search(r'[\w.+-]+@[\w-]+\.[\w.-]+', message))
    has_domain = bool(re.search(r'\b(?:[\w-]+\.)+(?:com|net|org|io|cn|ru|de|uk|info|xyz|me)\b', message, re.I))
    has_phone = bool(re.search(r'\b\d{3}[-.]?\d{3}[-.]?\d{4}\b', message))

    if has_email:
        tools.append("email_lookup")
    if has_domain:
        tools.append("domain_lookup")
    if has_phone:
        tools.append("phone_lookup")

    if has_username or target:
        # 模式判断
        if any(kw in msg_lower for kw in ["全站", "所有站点", "1836", "全部", "all"]):
            tools.append("full_search")
        elif any(kw in msg_lower for kw in ["递归", "深度挖掘", "关联", "recursive", "maigret", "挖掘", "关系", "图谱", "graph"]):
            tools.append("recursive_probe")
        elif any(kw in msg_lower for kw in ["游戏", "game", "steam", "lol", "xbox", "psn", "fortnite"]):
            tools.append("game_probe")
        else:
            tools.append("username_probe")

        # Grok 搜索（默认开启，除非用户明确说不要）
        if not any(kw in msg_lower for kw in ["不要grok", "不用grok", "no grok"]):
            tools.append("grok_search")

        # 深度分析
        if any(kw in msg_lower for kw in ["深度分析", "分析", "analyze", "deep", "画像", "风险评估"]):
            tools.append("deep_analysis")

    # 报告导出
    if any(kw in msg_lower for kw in ["报告", "导出", "report", "export", "pdf", "csv", "html", "json", "下载"]):
        tools.append("export_report")

    # 变体生成
    if any(kw in msg_lower for kw in ["变体", "variants", "相似用户名", "别名", "alias"]):
        tools.append("generate_variants")

    # 搜索引擎
    if any(kw in msg_lower for kw in ["google", "bing", "搜索引擎", "搜索网页", "duckduckgo"]):
        tools.append("search_engine")

    return list(set(tools))  # 去重


# ==================== 工具执行器 ====================

async def execute_tool(
    tool_name: str,
    progress_queue: asyncio.Queue,
    **kwargs,
) -> dict:
    """执行单个工具，返回结果。

    Args:
        tool_name: 工具名称
        progress_queue: 进度队列（asyncio.Queue）
        **kwargs: 工具参数

    Returns:
        {"tool": tool_name, "status": "ok"|"error", "data": ..., "message": "..."}
    """
    tool = get_tool_by_name(tool_name)
    if not tool:
        return {"tool": tool_name, "status": "error", "message": f"未知工具: {tool_name}"}

    await progress_queue.put({"message": f"🔧 调用工具: {tool['description']}", "done": False, "tool": tool_name})

    try:
        if tool_name == "username_probe":
            username = kwargs.get("username") or kwargs.get("target", "")
            limit = int(kwargs.get("limit", 100))
            concurrency = int(kwargs.get("concurrency", 15))
            await progress_queue.put({"message": f"📋 探测 top {limit} 站点（并发 {concurrency}）...", "done": False, "tool": tool_name})
            sites = maigret_sites.get_top_sites(limit)
            results = await probes.probe_batch(sites, username, concurrency)
            found = [r for r in results if r.get("status") == "found"]
            # 添加置信度和元数据
            for r in found:
                r["confidence"] = probes.calculate_confidence(r)
                r["metadata"] = probes.extract_metadata(r)
            await progress_queue.put({"message": f"✅ 站点探测完成: {len(found)}/{len(results)} 命中", "done": False, "tool": tool_name})
            return {"tool": tool_name, "status": "ok", "data": {"found": found, "total": len(results), "results": results}, "message": f"探测 {len(results)} 个站点，命中 {len(found)} 个"}

        elif tool_name == "recursive_probe":
            username = kwargs.get("username") or kwargs.get("target", "")
            max_depth = int(kwargs.get("max_depth", 2))
            limit = int(kwargs.get("limit", 50))
            await progress_queue.put({"message": f"🕸️ 递归挖掘（深度 {max_depth}）...", "done": False, "tool": tool_name})
            sites = maigret_sites.get_top_sites(limit)

            async def prog_cb(current, total, msg):
                await progress_queue.put({"message": msg, "done": False, "tool": tool_name})

            result = await probes.recursive_probe(username, sites, max_depth, 10, prog_cb)
            # 添加置信度和元数据
            for r in result.get("original", []):
                r["confidence"] = probes.calculate_confidence(r)
                r["metadata"] = probes.extract_metadata(r)
            await progress_queue.put({"message": f"✅ 递归挖掘完成: {len(result.get('original', []))} 直接命中, {len(result.get('related', []))} 关联用户", "done": False, "tool": tool_name})
            return {"tool": tool_name, "status": "ok", "data": result, "message": f"递归挖掘完成"}

        elif tool_name == "game_probe":
            username = kwargs.get("username") or kwargs.get("target", "")
            await progress_queue.put({"message": "🎮 探测 15 个游戏平台...", "done": False, "tool": tool_name})
            results = await probes.probe_game_platforms(username)
            found = [r for r in results if r.get("status") == "found"]
            await progress_queue.put({"message": f"✅ 游戏平台: {len(found)}/{len(results)} 命中", "done": False, "tool": tool_name})
            return {"tool": tool_name, "status": "ok", "data": {"found": found, "total": len(results), "results": results}, "message": f"游戏平台 {len(found)}/{len(results)} 命中"}

        elif tool_name == "grok_search":
            target = kwargs.get("target") or kwargs.get("username", "")
            await progress_queue.put({"message": "🔍 Grok AI 实时搜索...", "done": False, "tool": tool_name})
            grok_sites = maigret_sites.get_top_sites(50)
            loop = asyncio.get_event_loop()
            result = await loop.run_in_executor(None, ai_analyzer.grok_search, target, grok_sites)
            await progress_queue.put({"message": "✅ Grok 搜索完成", "done": False, "tool": tool_name})
            return {"tool": tool_name, "status": "ok", "data": result, "message": f"Grok 搜索完成，发现 {len(result.get('platforms', []))} 个平台"}

        elif tool_name == "deep_analysis":
            target = kwargs.get("target") or kwargs.get("username", "")
            findings = kwargs.get("findings", [])
            await progress_queue.put({"message": "🧠 深度分析中...", "done": False, "tool": tool_name})
            loop = asyncio.get_event_loop()
            analysis = await loop.run_in_executor(None, ai_analyzer.grok_deep_analysis, target, findings)
            await progress_queue.put({"message": "✅ 深度分析完成", "done": False, "tool": tool_name})
            return {"tool": tool_name, "status": "ok", "data": {"analysis": analysis}, "message": "深度分析完成"}

        elif tool_name == "full_search":
            username = kwargs.get("username") or kwargs.get("target", "")
            concurrency = int(kwargs.get("concurrency", 20))
            await progress_queue.put({"message": "🌐 全站探测 1836 个站点...", "done": False, "tool": tool_name})
            sites = maigret_sites.get_top_sites(0)
            results = await probes.probe_batch(sites, username, concurrency)
            found = [r for r in results if r.get("status") == "found"]
            for r in found:
                r["confidence"] = probes.calculate_confidence(r)
                r["metadata"] = probes.extract_metadata(r)
            await progress_queue.put({"message": f"✅ 全站探测完成: {len(found)}/{len(results)} 命中", "done": False, "tool": tool_name})
            return {"tool": tool_name, "status": "ok", "data": {"found": found, "total": len(results), "results": results}, "message": f"全站 {len(found)}/{len(results)} 命中"}

        elif tool_name == "generate_variants":
            username = kwargs.get("username") or kwargs.get("target", "")
            await progress_queue.put({"message": "🔤 生成用户名变体...", "done": False, "tool": tool_name})
            result = variants.generate_variants(username)
            await progress_queue.put({"message": f"✅ 生成 {len(result)} 个变体", "done": False, "tool": tool_name})
            return {"tool": tool_name, "status": "ok", "data": {"variants": result}, "message": f"生成 {len(result)} 个变体"}

        elif tool_name == "export_report":
            target = kwargs.get("target") or kwargs.get("username", "")
            fmt = kwargs.get("format", "html")
            results = kwargs.get("results", [])
            await progress_queue.put({"message": f"📄 生成 {fmt.upper()} 报告...", "done": False, "tool": tool_name})
            if fmt == "html":
                content = reports.generate_html_report(target, results, kwargs.get("osint_data"))
            elif fmt == "csv":
                content = reports.generate_csv_report(target, results)
            elif fmt == "json":
                content = reports.generate_json_report(target, results, kwargs.get("osint_data"))
            elif fmt == "pdf":
                content = reports.generate_pdf_report(target, results, kwargs.get("osint_data"))
            else:
                content = reports.generate_html_report(target, results, kwargs.get("osint_data"))
            await progress_queue.put({"message": f"✅ {fmt.upper()} 报告已生成", "done": False, "tool": tool_name})
            return {"tool": tool_name, "status": "ok", "data": {"content": content, "format": fmt}, "message": f"{fmt.upper()} 报告已生成"}

        elif tool_name == "email_lookup":
            email = kwargs.get("email", "")
            await progress_queue.put({"message": f"📧 邮箱反查: {email}...", "done": False, "tool": tool_name})
            result = await _email_lookup(email)
            await progress_queue.put({"message": f"✅ 邮箱反查完成", "done": False, "tool": tool_name})
            return {"tool": tool_name, "status": "ok", "data": result, "message": "邮箱反查完成"}

        elif tool_name == "domain_lookup":
            domain = kwargs.get("domain", "")
            await progress_queue.put({"message": f"🌐 域名查询: {domain}...", "done": False, "tool": tool_name})
            result = await _domain_lookup(domain)
            await progress_queue.put({"message": f"✅ 域名查询完成", "done": False, "tool": tool_name})
            return {"tool": tool_name, "status": "ok", "data": result, "message": "域名查询完成"}

        elif tool_name == "phone_lookup":
            phone = kwargs.get("phone", "")
            await progress_queue.put({"message": f"📱 电话反查: {phone}...", "done": False, "tool": tool_name})
            result = await _phone_lookup(phone)
            await progress_queue.put({"message": f"✅ 电话反查完成", "done": False, "tool": tool_name})
            return {"tool": tool_name, "status": "ok", "data": result, "message": "电话反查完成"}

        elif tool_name == "search_engine":
            query = kwargs.get("query", "")
            max_results = int(kwargs.get("max_results", 5))
            await progress_queue.put({"message": f"🔎 搜索引擎: {query}...", "done": False, "tool": tool_name})
            results = await search_engines.search_and_crawl(query, max_results)
            await progress_queue.put({"message": f"✅ 搜索完成: {len(results)} 条结果", "done": False, "tool": tool_name})
            return {"tool": tool_name, "status": "ok", "data": {"results": results, "count": len(results)}, "message": f"搜索 {len(results)} 条结果"}

        else:
            return {"tool": tool_name, "status": "error", "message": f"工具 {tool_name} 未实现"}

    except Exception as e:
        await progress_queue.put({"message": f"❌ 工具 {tool_name} 失败: {e}", "done": False, "tool": tool_name})
        return {"tool": tool_name, "status": "error", "message": str(e)}


async def execute_tools_parallel(
    tool_names: list[str],
    progress_queue: asyncio.Queue,
    target: str = None,
    message: str = "",
) -> dict[str, dict]:
    """并发执行多个工具。

    Args:
        tool_names: 工具名称列表
        progress_queue: 进度队列
        target: 调查目标
        message: 用户消息（用于提取参数）

    Returns:
        {tool_name: result_dict}
    """
    # 为每个工具准备参数
    tool_tasks = []
    for name in tool_names:
        kwargs = _prepare_tool_kwargs(name, target, message)
        tool_tasks.append(execute_tool(name, progress_queue, **kwargs))

    # 并发执行
    results = await asyncio.gather(*tool_tasks, return_exceptions=True)

    # 整理结果
    output = {}
    for name, result in zip(tool_names, results):
        if isinstance(result, Exception):
            output[name] = {"tool": name, "status": "error", "message": str(result)}
        else:
            output[name] = result

    return output


def _prepare_tool_kwargs(tool_name: str, target: str, message: str) -> dict:
    """为工具准备参数（从消息中提取）。"""
    kwargs = {}

    # 提取用户名
    if target:
        kwargs["username"] = target
        kwargs["target"] = target
    else:
        # 从消息中提取
        cmd_match = re.search(r'(?:搜索|查找|调查|查一下|search|find|lookup)\s+[@]?(\w+)', message, re.I)
        if cmd_match:
            kwargs["username"] = cmd_match.group(1)
            kwargs["target"] = cmd_match.group(1)
        else:
            at_match = re.search(r'@(\w{3,30})', message)
            if at_match:
                kwargs["username"] = at_match.group(1)
                kwargs["target"] = at_match.group(1)

    # 提取邮箱
    email_match = re.search(r'[\w.+-]+@[\w-]+\.[\w.-]+', message)
    if email_match:
        kwargs["email"] = email_match.group(0)

    # 提取域名
    domain_match = re.search(r'\b(?:[\w-]+\.)+(?:com|net|org|io|cn|ru|de|uk|info|xyz|me)\b', message, re.I)
    if domain_match:
        kwargs["domain"] = domain_match.group(0)

    # 提取电话
    phone_match = re.search(r'\b\d{3}[-.]?\d{3}[-.]?\d{4}\b', message)
    if phone_match:
        kwargs["phone"] = phone_match.group(0)

    # 提取报告格式
    fmt_match = re.search(r'(?:格式|format)\s*[:：]?\s*(html|csv|json|pdf)', message, re.I)
    if fmt_match:
        kwargs["format"] = fmt_match.group(1).lower()
    elif "pdf" in message.lower():
        kwargs["format"] = "pdf"
    elif "csv" in message.lower():
        kwargs["format"] = "csv"
    elif "json" in message.lower() and "json" not in tool_name:
        kwargs["format"] = "json"

    # 提取搜索查询
    if tool_name == "search_engine":
        # 用整个消息作为查询（去掉命令词）
        query = re.sub(r'(?:搜索|查找|google|bing)\s*', '', message, flags=re.I).strip()
        kwargs["query"] = query or target or message

    return kwargs


# ==================== 邮箱/域名/电话反查工具 ====================

async def _email_lookup(email: str) -> dict:
    """邮箱反查：查找邮箱关联的账号和泄露记录。

    使用公开 API：
    - Gravatar 头像
    - Have I Been Pwned（通过 Grok 搜索）
    """
    result = {"email": email, "gravatar": None, "breaches": [], "associated_accounts": []}

    # 1. Gravatar 头像查询
    try:
        import hashlib
        email_hash = hashlib.md5(email.strip().lower().encode()).hexdigest()
        gravatar_url = f"https://www.gravatar.com/{email_hash}.json"
        async with httpx.AsyncClient(timeout=10.0, verify=False) as client:
            resp = await client.get(gravatar_url)
            if resp.status_code == 200:
                data = resp.json()
                entry = data.get("entry", [{}])[0] if data.get("entry") else {}
                result["gravatar"] = {
                    "username": entry.get("preferredUsername", ""),
                    "display_name": entry.get("displayName", ""),
                    "avatar": f"https://www.gravatar.com/avatar/{email_hash}?s=200",
                    "profile_url": entry.get("profileUrl", ""),
                }
                if entry.get("preferredUsername"):
                    result["associated_accounts"].append({
                        "platform": "Gravatar",
                        "username": entry.get("preferredUsername"),
                        "url": entry.get("profileUrl", ""),
                    })
    except Exception as e:
        result["gravatar_error"] = str(e)

    # 2. 通过 Grok 搜索泄露记录
    try:
        loop = asyncio.get_event_loop()
        grok_result = await loop.run_in_executor(
            None,
            lambda: ai_analyzer.call_grok(
                [{"role": "user", "content": f"Search for the email '{email}' in data breaches and leaked databases. List any breaches this email appears in, and any associated accounts/usernames. Also search for this email on social media platforms. Respond in Chinese."}],
                model=ai_analyzer.MODEL_DEEP,
                temperature=0.5,
                timeout=120.0,
            )
        )
        if grok_result:
            result["breaches"] = grok_result[:2000]
    except Exception as e:
        result["breach_error"] = str(e)

    return result


async def _domain_lookup(domain: str) -> dict:
    """域名/IP 查询：WHOIS、DNS 记录、地理位置。"""
    result = {"domain": domain, "whois": {}, "dns": {}, "ip": "", "location": {}}

    # 清理域名
    domain = domain.strip().lower()
    if domain.startswith("http"):
        domain = re.sub(r'^https?://', '', domain)
    domain = domain.split("/")[0]

    # 1. DNS 解析
    try:
        import socket
        ip = socket.gethostbyname(domain)
        result["ip"] = ip
    except Exception:
        pass

    # 2. 通过 Grok 查询 WHOIS + 地理位置
    try:
        loop = asyncio.get_event_loop()
        grok_result = await loop.run_in_executor(
            None,
            lambda: ai_analyzer.call_grok(
                [{"role": "user", "content": f"Perform a comprehensive OSINT lookup on the domain '{domain}'. Include: 1) WHOIS information (registrar, creation date, expiry date, registrant) 2) DNS records (A, MX, NS, TXT) 3) IP geolocation 4) Subdomains 5) Technologies used by the website. Respond in Chinese with structured format."}],
                model=ai_analyzer.MODEL_DEEP,
                temperature=0.5,
                timeout=120.0,
            )
        )
        if grok_result:
            result["whois"] = grok_result[:3000]
    except Exception as e:
        result["whois_error"] = str(e)

    return result


async def _phone_lookup(phone: str) -> dict:
    """电话号码反查：归属地、运营商、关联账号。"""
    result = {"phone": phone, "info": {}}

    # 清理号码
    phone = re.sub(r'[^\d+]', '', phone)

    # 通过 Grok 查询
    try:
        loop = asyncio.get_event_loop()
        grok_result = await loop.run_in_executor(
            None,
            lambda: ai_analyzer.call_grok(
                [{"role": "user", "content": f"Perform OSINT lookup on the phone number '{phone}'. Include: 1) Country and region 2) Carrier/operator 3) Line type (mobile/landline/voip) 4) Any associated accounts or services linked to this number 5) Any leaked databases containing this number. Respond in Chinese with structured format."}],
                model=ai_analyzer.MODEL_DEEP,
                temperature=0.5,
                timeout=120.0,
            )
        )
        if grok_result:
            result["info"] = grok_result[:2000]
    except Exception as e:
        result["error"] = str(e)

    return result


# ==================== 工具结果整合 ====================

def summarize_tool_results(tool_results: dict[str, dict], target: str) -> str:
    """将所有工具结果整合成文本，供主 AI 生成回复时参考。"""
    if not tool_results:
        return ""

    lines = [f"=== 工具调用结果（目标: {target}）===\n"]

    for tool_name, result in tool_results.items():
        if result.get("status") != "ok":
            lines.append(f"[{tool_name}] ❌ 失败: {result.get('message', '未知错误')}\n")
            continue

        data = result.get("data", {})
        lines.append(f"[{tool_name}] ✅ {result.get('message', '')}")

        if tool_name in ("username_probe", "full_search", "game_probe"):
            found = data.get("found", [])
            total = data.get("total", 0)
            lines.append(f"  探测 {total} 个站点，命中 {len(found)} 个:")
            for f in found[:15]:
                platform = f.get("platform", "?")
                url = f.get("url", "")
                snippet = (f.get("snippet") or "")[:80]
                confidence = f.get("confidence", 0)
                lines.append(f"  - [{platform}] {url} (置信度: {confidence})")
                if snippet:
                    lines.append(f"    → {snippet}")
            if len(found) > 15:
                lines.append(f"  ... 还有 {len(found) - 15} 个命中")

        elif tool_name == "recursive_probe":
            original = data.get("original", [])
            related = data.get("related", [])
            graph = data.get("graph", {})
            lines.append(f"  直接命中: {len(original)} 个")
            lines.append(f"  关联用户: {len(related)} 个")
            lines.append(f"  图谱节点: {len(graph.get('nodes', []))} 个")
            for r in original[:10]:
                lines.append(f"  - [{r.get('platform', '?')}] {r.get('url', '')}")

        elif tool_name == "grok_search":
            summary = data.get("summary", "")
            platforms = data.get("platforms", [])
            personal = data.get("personal_info", {})
            if summary:
                lines.append(f"  搜索总结:\n  {summary[:800]}")
            if platforms:
                lines.append(f"  发现 {len(platforms)} 个平台:")
                for p in platforms[:10]:
                    lines.append(f"  - [{p.get('platform', '?')}] {p.get('url', '')}")
            if personal:
                lines.append(f"  个人信息: {json.dumps(personal, ensure_ascii=False)[:200]}")

        elif tool_name == "deep_analysis":
            analysis = data.get("analysis", "")
            if analysis:
                lines.append(f"  分析结果:\n  {analysis[:1500]}")

        elif tool_name == "generate_variants":
            vlist = data.get("variants", [])
            lines.append(f"  变体: {', '.join(vlist[:20])}")

        elif tool_name == "email_lookup":
            gravatar = data.get("gravatar", {})
            if gravatar:
                lines.append(f"  Gravatar: {gravatar.get('username', '')} ({gravatar.get('display_name', '')})")
            breaches = data.get("breaches", "")
            if breaches:
                lines.append(f"  泄露记录:\n  {breaches[:800]}")

        elif tool_name == "domain_lookup":
            ip = data.get("ip", "")
            whois = data.get("whois", "")
            if ip:
                lines.append(f"  IP: {ip}")
            if whois:
                lines.append(f"  WHOIS:\n  {whois[:800]}")

        elif tool_name == "phone_lookup":
            info = data.get("info", "")
            if info:
                lines.append(f"  信息:\n  {info[:800]}")

        elif tool_name == "search_engine":
            results = data.get("results", [])
            lines.append(f"  搜索结果 {len(results)} 条:")
            for r in results[:5]:
                lines.append(f"  - {r.get('title', '')}: {r.get('url', '')}")

        elif tool_name == "export_report":
            fmt = data.get("format", "")
            lines.append(f"  报告格式: {fmt}")

        lines.append("")

    return "\n".join(lines)
