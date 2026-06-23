"""AI 分析模块：调用 Grok AI 进行 OSINT 情报分析。"""

import httpx
import json

# Grok API 后端配置
GROK_BASE_URL = "https://grok2api-2-hpc2.onrender.com"
GROK_API_KEY = "c9d05cfdfd6b4dbc8f13f474"
GROK_ENDPOINT = f"{GROK_BASE_URL}/v1/chat/completions"

# 模型常量
MODEL_FAST = "grok-4.20-fast"  # 快速规划
MODEL_DEEP = "grok-4.20-0309-non-reasoning"  # 深度分析


def call_grok(messages: list[dict], model: str = "grok-4.20-fast", temperature: float = 0.7) -> str:
    """通用 Grok API 调用函数。

    Args:
        messages: OpenAI 兼容的 messages 列表
        model: 模型名称
        temperature: 采样温度

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
    }
    try:
        with httpx.Client(timeout=60.0) as client:
            resp = client.post(GROK_ENDPOINT, headers=headers, json=payload)
            resp.raise_for_status()
            data = resp.json()
            return data["choices"][0]["message"]["content"]
    except Exception as e:
        # 捕获所有异常，失败返回空字符串
        print(f"[call_grok] 调用失败: {e}")
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
