"""
OSINT 情报收集后端 - FastAPI 主入口
提供用户名探测、搜索引擎爬取、AI 分析等 API
"""
import os, sys, asyncio, traceback
from typing import Optional

# 添加模块路径
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from fastapi.responses import HTMLResponse, FileResponse
from pydantic import BaseModel
from contextlib import asynccontextmanager

from modules import maigret_sites, variants, probes, search_engines, ai_analyzer

# === 配置 ===
PORT = int(os.environ.get("PORT", 8000))
STATIC_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "static")

# === 生命周期 ===
@asynccontextmanager
async def lifespan(app: FastAPI):
    # 启动时预加载站点数据
    sites = maigret_sites.load_sites()
    print(f"[启动] 已加载 {len(sites)} 个 Maigret 站点")
    yield
    print("[关闭] 清理资源")

# === FastAPI 应用 ===
app = FastAPI(
    title="OSINT 情报收集后端",
    description="用户名探测 + 搜索引擎爬取 + AI 分析",
    version="1.0.0",
    lifespan=lifespan,
)

# CORS - 允许所有来源（生产环境应限制）
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# === 请求模型 ===
class ProbeRequest(BaseModel):
    username: str
    site_name: Optional[str] = None  # 单个站点名
    tags: Optional[list[str]] = None  # 按标签筛选
    limit: int = 50  # 站点数量上限
    concurrency: int = 10  # 并发数

class SearchRequest(BaseModel):
    query: str
    max_results: int = 5

class ChatRequest(BaseModel):
    message: str  # 用户消息
    target: Optional[str] = None  # 当前调查目标（可选）
    history: list[dict] = []  # 聊天历史

class AnalyzeRequest(BaseModel):
    target: str
    findings: list[dict] = []
    analysis: Optional[str] = None

class StrategyRequest(BaseModel):
    target: str

class RunRequest(BaseModel):
    target: str
    max_variants: int = 20
    max_sites: int = 50
    search_results: int = 5
    recursion_depth: int = 2

# === API 路由 ===

@app.get("/api/health")
async def health():
    """健康检查"""
    return {"status": "ok", "sites_loaded": len(maigret_sites.load_sites())}

@app.get("/api/sites")
async def get_sites(
    tags: Optional[str] = None,
    limit: int = 50,
    search: Optional[str] = None,
):
    """获取 Maigret 站点列表"""
    if search:
        return maigret_sites.search_sites(search, limit)
    if tags:
        tag_list = [t.strip() for t in tags.split(",") if t.strip()]
        return maigret_sites.get_sites_by_tags(tag_list, limit)
    return maigret_sites.get_top_sites(limit)

@app.get("/api/sites/{name}")
async def get_site(name: str):
    """获取单个站点配置"""
    site = maigret_sites.get_site_by_name(name)
    if not site:
        raise HTTPException(404, f"站点 {name} 未找到")
    return site

@app.get("/api/variants/{username}")
async def get_variants(username: str):
    """生成用户名变体"""
    return variants.generate_variants(username)

@app.post("/api/probe")
async def probe(req: ProbeRequest):
    """探测用户名在多个平台是否存在"""
    # 确定要探测的站点列表
    if req.site_name:
        site = maigret_sites.get_site_by_name(req.site_name)
        if not site:
            raise HTTPException(404, f"站点 {req.site_name} 未找到")
        sites = [site]
    elif req.tags:
        sites = maigret_sites.get_sites_by_tags(req.tags, req.limit)
    else:
        sites = maigret_sites.get_top_sites(req.limit)

    # 批量探测
    results = await probes.probe_batch(sites, req.username, req.concurrency)
    found = [r for r in results if r.get("status") == "found"]
    return {
        "username": req.username,
        "total": len(results),
        "found": len(found),
        "results": results,
    }

@app.post("/api/search")
async def search(req: SearchRequest):
    """搜索引擎搜索 + 爬取内容"""
    results = await search_engines.search_and_crawl(req.query, req.max_results)
    return {"query": req.query, "results": results, "count": len(results)}

@app.post("/api/grok-search")
async def grok_search(target: str):
    """利用 Grok AI 的实时搜索能力搜索目标用户名。
    Grok 会自动搜索互联网，访问网站，返回带引用链接的结果。
    """
    result = ai_analyzer.grok_search(target)
    return result

@app.post("/api/chat")
async def chat(req: ChatRequest):
    """聊天 + 情报收集同步进行。
    
    用户可以像和 ChatGPT 聊天一样输入消息。
    如果消息中包含用户名或搜索请求，AI 会自动触发 OSINT 收集。
    聊天和情报收集同步进行。
    """
    import re, asyncio
    
    message = req.message.strip()
    target = req.target
    
    # 自动检测消息中的用户名（@username 或 "搜索 xxx" 命令）
    detected_target = None
    if not target:
        # 检测 "搜索 xxx" 或 "查找 xxx" 命令
        cmd_match = re.search(r'(?:搜索|查找|调查|查一下|search|find|lookup)\s+[@]?(\w+)', message, re.I)
        if cmd_match:
            detected_target = cmd_match.group(1)
        else:
            # 检测 @username
            at_match = re.search(r'@(\w{3,30})', message)
            if at_match:
                detected_target = at_match.group(1)
    else:
        detected_target = target
    
    # 如果检测到目标，执行情报收集
    osint_results = None
    if detected_target:
        # 同时执行：Grok 搜索 + Maigret 探测
        try:
            # 1. Grok 实时搜索（Grok 自带的搜索爬虫）
            grok_result = ai_analyzer.grok_search(detected_target)
            
            # 2. Maigret 探测（top 30 站点，快速扫描）
            sites = maigret_sites.get_top_sites(30)
            probe_results = await probes.probe_batch(sites, detected_target, 10)
            found_probes = [r for r in probe_results if r.get("status") == "found"]
            
            osint_results = {
                "target": detected_target,
                "grok_search": grok_result,
                "maigret_found": found_probes,
                "maigret_total": len(probe_results),
            }
        except Exception as e:
            osint_results = {"error": str(e)}
    
    # 构建 Grok 聊天消息
    messages = []
    
    # 系统提示
    system_content = (
        "你是一名 OSINT 情报分析智能体。用户和你聊天时，你可以：\n"
        "1. 回答用户的问题\n"
        "2. 如果用户提到用户名或要求搜索，自动进行情报收集\n"
        "3. 分析情报结果，提供见解\n"
        "4. 用中文回复，格式清晰\n"
    )
    if osint_results:
        system_content += (
            f"\n当前调查目标: {detected_target}\n"
            f"情报收集结果:\n"
        )
        grok_data = osint_results.get("grok_search", {})
        if grok_data.get("summary"):
            system_content += f"\nGrok 搜索总结:\n{grok_data['summary'][:1500]}\n"
        if grok_data.get("platforms"):
            system_content += f"\nGrok 发现的平台:\n"
            for p in grok_data["platforms"][:10]:
                system_content += f"- [{p.get('platform', '?')}] {p.get('url', '')}\n"
        maigret_found = osint_results.get("maigret_found", [])
        if maigret_found:
            system_content += f"\nMaigret 探测命中 ({len(maigret_found)} 个):\n"
            for f in maigret_found[:10]:
                system_content += f"- [{f.get('platform', '?')}] {f.get('url', '')}\n"
                if f.get("snippet"):
                    system_content += f"  → {f['snippet'][:100]}\n"
    
    messages.append({"role": "system", "content": system_content})
    
    # 添加聊天历史
    for h in req.history[-5:]:  # 最多保留最近 5 条历史
        messages.append(h)
    
    # 添加当前消息
    messages.append({"role": "user", "content": message})
    
    # 调用 Grok 生成回复
    reply = ai_analyzer.call_grok(messages, model=ai_analyzer.MODEL_DEEP, temperature=0.7, timeout=120.0)
    
    return {
        "reply": reply,
        "target": detected_target,
        "osint_results": osint_results,
    }

@app.post("/api/strategy")
async def plan_strategy(req: StrategyRequest):
    """AI 策略规划"""
    strategy = ai_analyzer.plan_strategy(req.target)
    # 合并变体生成
    generated = variants.generate_variants(req.target)
    if "variants" not in strategy:
        strategy["variants"] = generated[:req.max_variants if hasattr(req, 'max_variants') else 20]
    return strategy

@app.post("/api/analyze")
async def analyze(req: AnalyzeRequest):
    """AI 分析命中线索"""
    result = ai_analyzer.analyze_findings(req.target, {}, req.findings)
    return result

@app.post("/api/finalize")
async def finalize(req: AnalyzeRequest):
    """生成最终情报档案"""
    if req.analysis is None:
        req.analysis = ""
    archive = ai_analyzer.finalize_profile(req.target, {}, req.findings, req.analysis)
    return {"archive": archive}

@app.post("/api/run")
async def run_full_osint(req: RunRequest):
    """
    完整 OSINT 流程：
    1. AI 策略规划
    2. 变体生成
    3. 平台探测（Maigret 站点）
    4. 搜索引擎爬取
    5. AI 分析 + 递归
    6. 生成档案
    """
    target = req.target
    all_findings = []

    try:
        # Step 1: 策略规划
        strategy = ai_analyzer.plan_strategy(target)

        # Step 2: 变体生成（AI 建议 + 自动生成，去重）
        ai_variants = strategy.get("variants", [])
        auto_variants = variants.generate_variants(target)
        seen = set()
        variant_list = []
        for v in ai_variants + auto_variants:
            v_clean = v.strip().lstrip("@")
            if v_clean and v_clean not in seen:
                seen.add(v_clean)
                variant_list.append(v_clean)
        variant_list = variant_list[:req.max_variants]

        # Step 3: 选择站点
        site_tags = strategy.get("site_tags", [])
        if site_tags:
            sites = maigret_sites.get_sites_by_tags(site_tags, req.max_sites)
        else:
            sites = maigret_sites.get_top_sites(req.max_sites)

        # Step 4: 批量探测所有变体
        for v in variant_list:
            results = await probes.probe_batch(sites, v, 10)
            found = [r for r in results if r.get("status") == "found"]
            all_findings.extend(found)

        # Step 5: 搜索引擎爬取
        search_query = strategy.get("primary_query", target)
        search_results = await search_engines.search_and_crawl(search_query, req.search_results)
        for r in search_results:
            all_findings.append({
                "status": "found",
                "platform": r.get("engine", "搜索引擎"),
                "username": target,
                "url": r.get("url", ""),
                "snippet": f"标题: {r.get('title', '')} | 内容: {r.get('snippet', '')}",
            })

        # Step 5.5: Grok AI 实时搜索（核心能力：Grok 自带的搜索爬虫）
        grok_result = ai_analyzer.grok_search(target)
        grok_platforms = grok_result.get("platforms", [])
        for p in grok_platforms:
            all_findings.append({
                "status": "found",
                "platform": p.get("platform", "Grok搜索"),
                "username": target,
                "url": p.get("url", ""),
                "snippet": p.get("snippet", ""),
            })
        grok_summary = grok_result.get("summary", "")

        # Step 6: AI 分析
        analysis_result = ai_analyzer.analyze_findings(target, strategy, all_findings)
        analysis = analysis_result.get("analysis", "")
        new_ids = analysis_result.get("new_ids", [])

        # Step 7: 递归搜索（最多 recursion_depth 层）
        for level in range(req.recursion_depth):
            if not new_ids:
                break
            # 去重
            fresh = [nid for nid in new_ids if nid.strip().lstrip("@") not in seen]
            if not fresh:
                break
            for nid in fresh:
                nid_clean = nid.strip().lstrip("@")
                seen.add(nid_clean)
                results = await probes.probe_batch(sites, nid_clean, 10)
                found = [r for r in results if r.get("status") == "found"]
                all_findings.extend(found)
            # 再分析
            rec_result = ai_analyzer.analyze_findings(target, strategy, all_findings)
            analysis = rec_result.get("analysis", analysis)
            new_ids = rec_result.get("new_ids", [])

        # Step 8: 生成最终档案
        archive = ai_analyzer.finalize_profile(target, strategy, all_findings, analysis)

        return {
            "target": target,
            "variants": variant_list,
            "sites_checked": len(sites),
            "total_findings": len(all_findings),
            "findings": all_findings,
            "analysis": analysis,
            "grok_summary": grok_summary,
            "archive": archive,
        }

    except Exception as e:
        traceback.print_exc()
        raise HTTPException(500, f"OSINT 流程失败: {str(e)}")

# === 静态文件服务（前端）===
if os.path.isdir(STATIC_DIR):
    app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")

@app.get("/{full_path:path}")
async def serve_frontend(full_path: str):
    """提供前端静态文件（默认 index.html）"""
    # 如果请求的是 API 路径，返回 404
    if full_path.startswith("api/"):
        raise HTTPException(404, "API endpoint not found")

    # 尝试提供静态文件
    file_path = os.path.join(STATIC_DIR, full_path)
    if os.path.isfile(file_path):
        return FileResponse(file_path)

    # 默认返回 index.html（SPA 模式）
    index_path = os.path.join(STATIC_DIR, "index.html")
    if os.path.isfile(index_path):
        return FileResponse(index_path, media_type="text/html")

    return HTMLResponse("<h1>OSINT Backend</h1><p>前端文件未找到，请将 index.html 放入 static/ 目录</p>")

# === 启动 ===
if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=PORT)
