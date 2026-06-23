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
