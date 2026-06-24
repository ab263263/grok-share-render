"""OSINT 报告生成模块（从 Maigret/Blackbird 学习）。

支持 HTML / CSV / JSON 三种格式导出。
"""

import json
import csv
import io
from datetime import datetime
from modules.probes import extract_metadata, calculate_confidence


def generate_html_report(target: str, results: list, osint_data: dict = None) -> str:
    """生成完整的 HTML 报告（Maigret 风格）。

    包含：目标信息、探测结果表格、元数据卡片、关系图谱、AI 分析。
    """
    now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

    # 处理探测结果
    found_results = [r for r in results if r.get("status") == "found"]
    total = len(results)
    found_count = len(found_results)

    # 收集所有元数据
    all_metadata = {}
    for r in found_results:
        meta = extract_metadata(r)
        if meta:
            all_metadata[r.get("platform", "?")] = meta

    # AI 分析
    deep_analysis = (osint_data or {}).get("deep_analysis", "")
    grok_summary = (osint_data or {}).get("grok_search", {}).get("summary", "") if osint_data else ""

    # 构建结果表格行
    rows_html = ""
    for r in found_results:
        platform = r.get("platform", "?")
        url = r.get("url", "")
        snippet = r.get("snippet", "")[:150]
        confidence = calculate_confidence(r)
        meta = all_metadata.get(platform, {})
        avatar = meta.get("avatar", "")
        bio = meta.get("bio", "")
        location = meta.get("location", "")
        followers = meta.get("followers", "")

        avatar_html = f'<img src="{avatar}" width="40" height="40" style="border-radius:50%">' if avatar else '<div style="width:40px;height:40px;background:#333;border-radius:50%;display:flex;align-items:center;justify-content:center;color:#666">?</div>'

        rows_html += f"""
        <tr>
          <td>{avatar_html}</td>
          <td><strong>{platform}</strong></td>
          <td><a href="{url}" target="_blank">{url}</a></td>
          <td>{snippet}</td>
          <td>{bio}</td>
          <td>{location}</td>
          <td>{followers}</td>
          <td><span class="confidence-{confidence // 25 * 25}">{confidence}</span></td>
        </tr>"""

    # 关系图谱数据
    graph = (osint_data or {}).get("graph", {}) if osint_data else {}
    graph_json = json.dumps(graph, ensure_ascii=False) if graph else '{"nodes":[],"links":[]}'

    return f"""<!DOCTYPE html>
<html lang="zh-CN">
<head>
<meta charset="UTF-8">
<title>OSINT 情报报告 - {target}</title>
<style>
  :root {{ --bg: #0f0f1a; --card: #1a1a2e; --text: #f0f0f5; --muted: #666680; --accent: #4facfe; --success: #4ade80; --warning: #fbbf24; --error: #f87171; }}
  * {{ margin:0; padding:0; box-sizing:border-box; }}
  body {{ background:var(--bg); color:var(--text); font-family:'Segoe UI',system-ui,sans-serif; padding:20px; }}
  .header {{ text-align:center; padding:30px 0; border-bottom:1px solid #2a2a3e; margin-bottom:30px; }}
  .header h1 {{ font-size:28px; background:linear-gradient(135deg,#4facfe,#00f2fe); -webkit-background-clip:text; -webkit-text-fill-color:transparent; }}
  .header .meta {{ color:var(--muted); margin-top:8px; font-size:14px; }}
  .stats {{ display:flex; gap:16px; margin-bottom:30px; flex-wrap:wrap; }}
  .stat-card {{ background:var(--card); padding:20px; border-radius:12px; flex:1; min-width:150px; text-align:center; border:1px solid #2a2a3e; }}
  .stat-card .num {{ font-size:32px; font-weight:bold; color:var(--accent); }}
  .stat-card .label {{ color:var(--muted); font-size:12px; margin-top:4px; }}
  .section {{ background:var(--card); border-radius:12px; padding:24px; margin-bottom:20px; border:1px solid #2a2a3e; }}
  .section h2 {{ font-size:18px; margin-bottom:16px; color:var(--accent); }}
  table {{ width:100%; border-collapse:collapse; }}
  th {{ text-align:left; padding:10px; border-bottom:2px solid #2a2a3e; color:var(--muted); font-size:12px; text-transform:uppercase; }}
  td {{ padding:10px; border-bottom:1px solid #2a2a3e; font-size:13px; }}
  td a {{ color:var(--accent); text-decoration:none; }}
  td a:hover {{ text-decoration:underline; }}
  .confidence-0 {{ color:var(--error); }} .confidence-25 {{ color:var(--warning); }}
  .confidence-50 {{ color:var(--accent); }} .confidence-75 {{ color:var(--success); font-weight:bold; }}
  .confidence-100 {{ color:var(--success); font-weight:bold; }}
  .analysis {{ white-space:pre-wrap; line-height:1.8; font-size:14px; color:#c0c0d0; }}
  #graph {{ width:100%; height:400px; background:#0d1117; border-radius:8px; }}
  .footer {{ text-align:center; color:var(--muted); font-size:12px; margin-top:30px; padding-top:20px; border-top:1px solid #2a2a3e; }}
</style>
</head>
<body>
<div class="header">
  <h1>OSINT 情报分析报告</h1>
  <div class="meta">目标: <strong>{target}</strong> | 生成时间: {now} | 命中: {found_count}/{total}</div>
</div>

<div class="stats">
  <div class="stat-card"><div class="num">{total}</div><div class="label">探测站点</div></div>
  <div class="stat-card"><div class="num">{found_count}</div><div class="label">命中账号</div></div>
  <div class="stat-card"><div class="num">{len(all_metadata)}</div><div class="label">提取元数据</div></div>
  <div class="stat-card"><div class="num">{len(graph.get('nodes', []))}</div><div class="label">图谱节点</div></div>
</div>

{f'''<div class="section"><h2>🧠 AI 深度分析</h2><div class="analysis">{deep_analysis}</div></div>''' if deep_analysis else ''}

{f'''<div class="section"><h2>🔍 Grok 搜索总结</h2><div class="analysis">{grok_summary[:2000]}</div></div>''' if grok_summary else ''}

<div class="section">
  <h2>📊 探测结果详情</h2>
  <table>
    <thead><tr><th></th><th>平台</th><th>URL</th><th>摘要</th><th>Bio</th><th>位置</th><th>粉丝</th><th>置信度</th></tr></thead>
    <tbody>{rows_html if rows_html else '<tr><td colspan="8" style="text-align:center;color:var(--muted);padding:40px">未找到匹配账号</td></tr>'}</tbody>
  </table>
</div>

<div class="section">
  <h2>🕸️ 关系图谱</h2>
  <div id="graph"></div>
</div>

<div class="footer">OSINT 情报智能体 | 仅供合法授权的安全研究使用</div>

<script src="https://d3js.org/d3.v7.min.js"></script>
<script>
(function() {{
  const data = {graph_json};
  if (!data.nodes || data.nodes.length === 0) {{
    document.getElementById('graph').innerHTML = '<div style="display:flex;align-items:center;justify-content:center;height:100%;color:#666">暂无图谱数据</div>';
    return;
  }}
  const width = document.getElementById('graph').clientWidth;
  const height = 400;
  const svg = d3.select('#graph').append('svg').attr('width', width).attr('height', height);
  const sim = d3.forceSimulation(data.nodes)
    .force('link', d3.forceLink(data.links).id(d => d.id).distance(80))
    .force('charge', d3.forceManyBody().strength(-200))
    .force('center', d3.forceCenter(width/2, height/2));
  const colors = {{ root: '#f093fb', account: '#4facfe', related: '#fbbf24' }};
  const link = svg.selectAll('line').data(data.links).join('line').attr('stroke', '#333').attr('stroke-width', 1);
  const node = svg.selectAll('circle').data(data.nodes).join('circle')
    .attr('r', d => d.type === 'root' ? 12 : 8).attr('fill', d => colors[d.type] || '#666')
    .call(d3.drag().on('start', (e,d) => {{ if(!e.active) sim.alphaTarget(0.3).restart(); d.fx=d.x; d.fy=d.y; }})
      .on('drag', (e,d) => {{ d.fx=e.x; d.fy=e.y; }}).on('end', (e,d) => {{ d.fx=null; d.fy=null; }}));
  const label = svg.selectAll('text').data(data.nodes).join('text').text(d => d.id.split('@')[0]).attr('font-size', 10).attr('fill', '#aaa');
  sim.on('tick', () => {{
    link.attr('x1',d=>d.source.x).attr('y1',d=>d.source.y).attr('x2',d=>d.target.x).attr('y2',d=>d.target.y);
    node.attr('cx',d=>d.x).attr('cy',d=>d.y);
    label.attr('x',d=>d.x+12).attr('y',d=>d.y+4);
  }});
}})();
</script>
</body>
</html>"""


def generate_csv_report(target: str, results: list) -> str:
    """生成 CSV 报告（Blackbird 风格）。"""
    output = io.StringIO()
    writer = csv.writer(output)
    writer.writerow(["Platform", "Username", "URL", "Status", "Snippet", "Bio", "Location", "Followers", "Confidence", "Avatar"])

    for r in results:
        platform = r.get("platform", "?")
        username = r.get("username", target)
        url = r.get("url", "")
        status = r.get("status", "?")
        snippet = (r.get("snippet") or "").replace("\n", " ")[:200]
        confidence = calculate_confidence(r)
        meta = extract_metadata(r)
        writer.writerow([
            platform, username, url, status, snippet,
            meta.get("bio", ""), meta.get("location", ""),
            meta.get("followers", ""), confidence, meta.get("avatar", "")
        ])

    return output.getvalue()


def generate_pdf_report(target: str, results: list, osint_data: dict = None) -> bytes:
    """生成 PDF 报告（使用 reportlab，支持中文）。

    包含：标题、统计、探测结果表格、AI 分析。
    """
    from reportlab.lib.pagesizes import A4
    from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
    from reportlab.lib.units import cm
    from reportlab.lib import colors
    from reportlab.platypus import SimpleDocTemplate, Paragraph, Spacer, Table, TableStyle
    from reportlab.pdfbase import pdfmetrics
    from reportlab.pdfbase.cidfonts import UnicodeCIDFont
    import io as _io

    # 注册中文字体（reportlab 内置 CID 字体，无需外部文件）
    try:
        pdfmetrics.registerFont(UnicodeCIDFont("STSong-Light"))
        font_name = "STSong-Light"
    except Exception:
        font_name = "Helvetica"

    buf = _io.BytesIO()
    doc = SimpleDocTemplate(buf, pagesize=A4, topMargin=2*cm, bottomMargin=2*cm, leftMargin=2*cm, rightMargin=2*cm)

    styles = getSampleStyleSheet()
    title_style = ParagraphStyle("Title", parent=styles["Title"], fontName=font_name, fontSize=22, textColor=colors.HexColor("#4facfe"))
    h2_style = ParagraphStyle("H2", parent=styles["Heading2"], fontName=font_name, fontSize=14, textColor=colors.HexColor("#4facfe"))
    body_style = ParagraphStyle("Body", parent=styles["Normal"], fontName=font_name, fontSize=10, leading=16)
    cell_style = ParagraphStyle("Cell", parent=styles["Normal"], fontName=font_name, fontSize=8, leading=12)

    story = []
    now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    found_results = [r for r in results if r.get("status") == "found"]
    total = len(results)
    found_count = len(found_results)

    # 标题
    story.append(Paragraph(f"OSINT 情报分析报告", title_style))
    story.append(Spacer(1, 8))
    story.append(Paragraph(f"目标: <b>{target}</b> | 生成时间: {now} | 命中: {found_count}/{total}", body_style))
    story.append(Spacer(1, 16))

    # 统计
    story.append(Paragraph("📊 统计概览", h2_style))
    story.append(Spacer(1, 6))
    stat_data = [
        ["探测站点", "命中账号", "提取元数据"],
        [str(total), str(found_count), str(len([r for r in found_results if extract_metadata(r)]))],
    ]
    stat_table = Table(stat_data, colWidths=[5*cm, 5*cm, 5*cm])
    stat_table.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#1a1a2e")),
        ("TEXTCOLOR", (0, 0), (-1, 0), colors.HexColor("#4facfe")),
        ("FONTNAME", (0, 0), (-1, -1), font_name),
        ("FONTSIZE", (0, 0), (-1, 0), 10),
        ("FONTSIZE", (0, 1), (-1, 1), 14),
        ("ALIGN", (0, 0), (-1, -1), "CENTER"),
        ("GRID", (0, 0), (-1, -1), 0.5, colors.HexColor("#2a2a3e")),
    ]))
    story.append(stat_table)
    story.append(Spacer(1, 16))

    # AI 深度分析
    deep_analysis = (osint_data or {}).get("deep_analysis", "")
    if deep_analysis:
        story.append(Paragraph("🧠 AI 深度分析", h2_style))
        story.append(Spacer(1, 6))
        # 截断过长的分析
        analysis_text = deep_analysis[:3000].replace("\n", "<br/>")
        story.append(Paragraph(analysis_text, body_style))
        story.append(Spacer(1, 16))

    # Grok 搜索总结
    grok_summary = (osint_data or {}).get("grok_search", {}).get("summary", "") if osint_data else ""
    if grok_summary:
        story.append(Paragraph("🔍 Grok 搜索总结", h2_style))
        story.append(Spacer(1, 6))
        summary_text = grok_summary[:2000].replace("\n", "<br/>")
        story.append(Paragraph(summary_text, body_style))
        story.append(Spacer(1, 16))

    # 探测结果表格
    story.append(Paragraph("📊 探测结果详情", h2_style))
    story.append(Spacer(1, 6))

    if found_results:
        table_data = [["平台", "URL", "摘要", "置信度"]]
        for r in found_results[:30]:  # 最多 30 行
            platform = r.get("platform", "?")
            url = r.get("url", "")
            snippet = (r.get("snippet") or "")[:60].replace("\n", " ")
            confidence = calculate_confidence(r)
            table_data.append([
                Paragraph(platform, cell_style),
                Paragraph(f'<a href="{url}">{url[:40]}</a>', cell_style),
                Paragraph(snippet, cell_style),
                str(confidence),
            ])

        result_table = Table(table_data, colWidths=[2.5*cm, 4*cm, 7*cm, 1.5*cm])
        result_table.setStyle(TableStyle([
            ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#1a1a2e")),
            ("TEXTCOLOR", (0, 0), (-1, 0), colors.HexColor("#4facfe")),
            ("FONTNAME", (0, 0), (-1, 0), font_name),
            ("FONTSIZE", (0, 0), (-1, 0), 9),
            ("GRID", (0, 0), (-1, -1), 0.3, colors.HexColor("#2a2a3e")),
            ("VALIGN", (0, 0), (-1, -1), "TOP"),
            ("ROWBACKGROUNDS", (0, 1), (-1, -1), [colors.white, colors.HexColor("#f5f5f5")]),
        ]))
        story.append(result_table)
    else:
        story.append(Paragraph("未找到匹配账号", body_style))

    story.append(Spacer(1, 20))
    story.append(Paragraph("OSINT 情报智能体 | 仅供合法授权的安全研究使用", body_style))

    doc.build(story)
    return buf.getvalue()


def generate_json_report(target: str, results: list, osint_data: dict = None) -> str:
    """生成 JSON 报告（完整结构化数据）。"""
    found = [r for r in results if r.get("status") == "found"]
    report = {
        "target": target,
        "generated_at": datetime.now().isoformat(),
        "summary": {
            "total_probed": len(results),
            "total_found": len(found),
            "platforms": [r.get("platform") for r in found],
        },
        "results": [],
        "metadata": {},
        "graph": (osint_data or {}).get("graph", {}),
        "ai_analysis": (osint_data or {}).get("deep_analysis", ""),
        "grok_search": (osint_data or {}).get("grok_search", {}),
    }

    for r in found:
        report["results"].append({
            "platform": r.get("platform"),
            "url": r.get("url"),
            "snippet": r.get("snippet"),
            "confidence": calculate_confidence(r),
            "metadata": extract_metadata(r),
        })
        meta = extract_metadata(r)
        if meta:
            report["metadata"][r.get("platform", "?")] = meta

    return json.dumps(report, ensure_ascii=False, indent=2)
