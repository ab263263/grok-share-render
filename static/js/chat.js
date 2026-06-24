// 聊天功能模块

const API_BASE = window.location.origin;
const STORAGE_KEY = 'osint_history';

let history = [];
let welcomeRemoved = false;

// HTML 转义
function escapeHtml(s) {
  return (s || '').replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;').replace(/"/g, '&quot;');
}

// 加载历史记录
function loadHistory() {
  const saved = localStorage.getItem(STORAGE_KEY);
  if (saved) {
    try {
      history = JSON.parse(saved);
      if (history.length > 0) {
        const welcome = document.getElementById('welcome');
        if (welcome && !welcomeRemoved) {
          welcome.remove();
          welcomeRemoved = true;
        }
        history.forEach(msg => {
          if (msg.role === 'user') {
            addMessage(msg.content, 'user');
          } else if (msg.role === 'assistant') {
            addMessage(msg.content, 'ai');
          }
        });
      }
    } catch (e) {
      console.error('加载历史失败:', e);
    }
  }
}

// 保存历史记录
function saveHistory() {
  localStorage.setItem(STORAGE_KEY, JSON.stringify(history.slice(-50)));
}

// 添加消息
function addMessage(content, type) {
  const welcome = document.getElementById('welcome');
  if (welcome && !welcomeRemoved) {
    welcome.remove();
    welcomeRemoved = true;
  }

  const chat = document.getElementById('chat-mode');
  const div = document.createElement('div');
  div.className = 'message ' + type;

  if (type === 'ai') {
    div.innerHTML = formatMarkdown(content);
  } else {
    div.textContent = content;
  }

  chat.appendChild(div);
  chat.scrollTop = chat.scrollHeight;
  return div;
}

// 格式化 Markdown
function formatMarkdown(text) {
  if (!text) return '<em style="color:var(--text-muted)">（无回复）</em>';

  text = text.replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;');
  text = text.replace(/```(\w*)\n([\s\S]*?)```/g, '<pre>$2</pre>');
  text = text.replace(/`([^`]+)`/g, '<code>$1</code>');
  text = text.replace(/\[([^\]]+)\]\((https?:\/\/[^\s)]+)\)/g, '<a href="$2" target="_blank">$1</a>');
  text = text.replace(/\[\[(\d+)\]\]\((https?:\/\/[^\s)]+)\)/g, '<a href="$2" target="_blank">[$1]</a>');
  text = text.replace(/(https?:\/\/[^\s<]+)/g, '<a href="$1" target="_blank">$1</a>');
  text = text.replace(/\*\*([^*]+)\*\*/g, '<strong>$1</strong>');
  text = text.replace(/\n/g, '<br>');

  return text;
}

// 添加情报发现
function addFindings(findings) {
  if (!findings || findings.length === 0) return;

  const chat = document.getElementById('chat-mode');
  const div = document.createElement('div');
  div.className = 'findings';

  const grokCount = findings.filter(f => f.platform && f.platform.startsWith('Grok')).length;
  const gameCount = findings.filter(f => f.platform && f.platform.includes('🎮')).length;
  const maigretCount = findings.length - grokCount - gameCount;

  let header = `<div class="findings-header">📊 情报发现 <span class="badge">${findings.length} 个</span>`;
  if (grokCount) header += ` <span class="badge" style="background:rgba(74,222,128,0.15);color:var(--success)">Grok ${grokCount}</span>`;
  if (maigretCount) header += ` <span class="badge">Maigret ${maigretCount}</span>`;
  if (gameCount) header += ` <span class="badge" style="background:rgba(240,147,251,0.15);color:var(--accent-3)">游戏 ${gameCount}</span>`;
  header += `</div>`;

  div.innerHTML = header;

  findings.slice(0, 20).forEach(f => {
    const item = document.createElement('div');
    item.className = 'finding-item';
    const platform = f.platform || '?';
    const tagClass = platform.startsWith('Grok') ? 'grok' : (platform.includes('🎮') ? 'game' : '');
    const tagText = platform.replace('🎮 ', '').replace('Grok: ', '');
    const url = f.url || '';
    const snippet = f.snippet ? `<div class="snippet">${f.snippet.substring(0, 100)}</div>` : '';
    item.innerHTML = `<span class="platform-tag ${tagClass}">${tagText}</span><div><a href="${url}" target="_blank">${url}</a>${snippet}</div>`;
    div.appendChild(item);
  });

  chat.appendChild(div);
  chat.scrollTop = chat.scrollHeight;
}

// 添加个人信息
function addPersonalInfo(info) {
  if (!info || Object.keys(info).length === 0) return;

  const chat = document.getElementById('chat-mode');
  const div = document.createElement('div');
  div.className = 'personal-info';

  let html = '<div class="personal-info-header">👤 提取的个人信息</div>';
  const labels = {
    emails: '邮箱', phones: '电话', location: '位置', real_name: '真实姓名', age: '年龄'
  };

  for (const [key, value] of Object.entries(info)) {
    const label = labels[key] || key;
    const val = Array.isArray(value) ? value.join(', ') : value;
    html += `<div class="personal-info-item"><strong>${label}:</strong> ${val}</div>`;
  }

  div.innerHTML = html;
  chat.appendChild(div);
  chat.scrollTop = chat.scrollHeight;
}

// === 从 Maigret/OpenOSINT 学习：报告导出 + 关系图谱 ===

// 添加报告导出按钮
function addReportButtons(target, results, osintData) {
  const chat = document.getElementById('chat-mode');
  const div = document.createElement('div');
  div.className = 'report-buttons';

  const foundCount = (results || []).filter(r => r.status === 'found').length;
  if (foundCount === 0) return;

  div.innerHTML = `
    <div class="report-header">📄 报告导出 (${foundCount} 个命中)</div>
    <div class="report-actions">
      <button class="report-btn" onclick="exportReport('html', '${target}')">🌐 HTML 报告</button>
      <button class="report-btn" onclick="exportReport('csv', '${target}')">📊 CSV 报告</button>
      <button class="report-btn" onclick="exportReport('json', '${target}')">📋 JSON 报告</button>
    </div>
  `;
  chat.appendChild(div);
  chat.scrollTop = chat.scrollHeight;

  // 保存当前结果供导出使用
  window._lastReportData = { target, results: results || [], osintData: osintData || {} };
}

// 导出报告
async function exportReport(format, target) {
  const data = window._lastReportData;
  if (!data) {
    addMessage('⚠️ 没有可导出的数据', 'system');
    return;
  }

  const statusText = document.getElementById('status-text');
  statusText.textContent = `生成 ${format.toUpperCase()} 报告...`;

  try {
    const resp = await fetch(`${API_BASE}/api/report/${format}`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        target: data.target,
        results: data.results,
        osint_data: data.osintData
      })
    });

    if (!resp.ok) throw new Error(`HTTP ${resp.status}`);

    const blob = await resp.blob();
    const url = URL.createObjectURL(blob);
    const a = document.createElement('a');
    a.href = url;
    a.download = `osint-report-${target}.${format}`;
    document.body.appendChild(a);
    a.click();
    document.body.removeChild(a);
    URL.revokeObjectURL(url);

    statusText.textContent = `${format.toUpperCase()} 报告已下载`;
  } catch (e) {
    addMessage(`❌ 导出失败: ${e.message}`, 'system');
    statusText.textContent = '导出失败';
  }
}

// 显示 D3.js 关系图谱
function showGraph(graphData) {
  if (!graphData || !graphData.nodes || graphData.nodes.length === 0) return;

  const chat = document.getElementById('chat-mode');
  const container = document.createElement('div');
  container.className = 'graph-container';
  container.innerHTML = '<div class="graph-header">🕸️ 关系图谱</div><div class="graph-svg" id="graph-' + Date.now() + '"></div>';
  chat.appendChild(container);

  const graphId = container.querySelector('.graph-svg').id;
  const el = document.getElementById(graphId);

  const width = el.clientWidth || 600;
  const height = 350;

  const svg = d3.select('#' + graphId).append('svg')
    .attr('width', width).attr('height', height)
    .style('background', '#0d1117').style('border-radius', '8px');

  const sim = d3.forceSimulation(graphData.nodes)
    .force('link', d3.forceLink(graphData.links).id(d => d.id).distance(80))
    .force('charge', d3.forceManyBody().strength(-200))
    .force('center', d3.forceCenter(width / 2, height / 2));

  const colors = { root: '#f093fb', account: '#4facfe', related: '#fbbf24' };

  const link = svg.selectAll('line').data(graphData.links).join('line')
    .attr('stroke', '#333').attr('stroke-width', 1.5);

  const node = svg.selectAll('circle').data(graphData.nodes).join('circle')
    .attr('r', d => d.type === 'root' ? 14 : 8)
    .attr('fill', d => colors[d.type] || '#666')
    .style('cursor', 'pointer')
    .call(d3.drag()
      .on('start', (e, d) => { if (!e.active) sim.alphaTarget(0.3).restart(); d.fx = d.x; d.fy = d.y; })
      .on('drag', (e, d) => { d.fx = e.x; d.fy = e.y; })
      .on('end', (e, d) => { d.fx = null; d.fy = null; })
    );

  node.append('title').text(d => d.id);

  const label = svg.selectAll('text').data(graphData.nodes).join('text')
    .text(d => d.id.split('@')[0].substring(0, 15))
    .attr('font-size', 10).attr('fill', '#aaa').attr('dx', 12).attr('dy', 4);

  sim.on('tick', () => {
    link.attr('x1', d => d.source.x).attr('y1', d => d.source.y)
        .attr('x2', d => d.target.x).attr('y2', d => d.target.y);
    node.attr('cx', d => d.x).attr('cy', d => d.y);
    label.attr('x', d => d.x).attr('y', d => d.y);
  });

  chat.scrollTop = chat.scrollHeight;
}

// 发送建议
function sendSuggestion(text) {
  const input = document.getElementById('input');
  input.value = text;
  sendMessage();
}

// 当前选择的模式
let currentMode = 'default';

// 设置模式
function setMode(btn) {
  document.querySelectorAll('.mode-btn').forEach(b => b.classList.remove('active'));
  btn.classList.add('active');
  currentMode = btn.dataset.mode;
  console.log('切换到模式:', currentMode);
}

// 发送消息
async function sendMessage() {
  const input = document.getElementById('input');
  const targetInput = document.getElementById('target-input');
  const sendBtn = document.getElementById('send-btn');
  const statusText = document.getElementById('status-text');
  const chat = document.getElementById('chat-mode');

  // 优先使用 target-input，否则从 input 解析
  let target = targetInput ? targetInput.value.trim() : '';
  let rawMessage = input.value.trim();

  // 如果没填 target-input，尝试从 input 中提取 @xxx 或 xxx
  if (!target && rawMessage) {
    const atMatch = rawMessage.match(/@(\w{3,30})/);
    if (atMatch) {
      target = atMatch[1];
    } else {
      // 提取第一个连续单词作为目标
      const cmdMatch = rawMessage.match(/(?:搜索|查找|调查|查一下|search|find|lookup)\s+[@]?(\w+)/i);
      if (cmdMatch) {
        target = cmdMatch[1];
      }
    }
  }

  if (!target) {
    addMessage('⚠️ 请先在上方输入用户名', 'system');
    if (targetInput) targetInput.focus();
    return;
  }

  // 根据当前模式构造消息（覆盖或附加模式关键词）
  let modeHint = '';
  if (currentMode === 'full') modeHint = '全站搜索';
  else if (currentMode === 'game') modeHint = '搜索游戏平台';
  else if (currentMode === 'deep') modeHint = '深度分析';

  const message = rawMessage
    ? (modeHint ? `${modeHint} ${target}，${rawMessage}` : `搜索 ${target}，${rawMessage}`)
    : `${modeHint || '搜索'} ${target}`;

  addMessage(`🎯 目标: ${target} | 模式: ${currentMode}`, 'system');
  addMessage(message, 'user');
  input.value = '';
  sendBtn.disabled = true;
  statusText.textContent = '思考中...';

  // 创建思考过程容器（使用唯一 ID 避免冲突）
  const thinkingId = 'thinking-' + Date.now();
  const stepsId = 'steps-' + Date.now();
  const thinkingDiv = document.createElement('div');
  thinkingDiv.className = 'message ai thinking-process';
  thinkingDiv.id = thinkingId;
  thinkingDiv.innerHTML = `<div class="thinking-header">🧠 思考过程</div><div class="thinking-steps" id="${stepsId}"></div>`;
  chat.appendChild(thinkingDiv);

  const stepsDiv = document.getElementById(stepsId);

  // SSE 实时进度
  const taskId = 'task-' + Date.now() + '-' + Math.random().toString(36).substr(2, 9);
  let sseDone = false;

  const eventSource = new EventSource(`${API_BASE}/api/progress?task_id=${taskId}`);
  eventSource.onmessage = (event) => {
    try {
      const data = JSON.parse(event.data);
      const step = document.createElement('div');
      step.className = 'thinking-step';
      step.innerHTML = `<span class="check">✓</span> ${data.message}`;
      stepsDiv.appendChild(step);
      chat.scrollTop = chat.scrollHeight;
      if (data.done) {
        sseDone = true;
        eventSource.close();
        // 标记思考过程为完成
        const header = thinkingDiv.querySelector('.thinking-header');
        if (header) header.innerHTML = '🧠 思考过程 <span style="color:var(--success);font-size:12px;">✓ 完成</span>';
      }
    } catch (e) {
      console.error('SSE parse error:', e);
    }
  };

  eventSource.onerror = () => {
    eventSource.close();
    if (!sseDone) {
      const header = thinkingDiv.querySelector('.thinking-header');
      if (header) header.innerHTML = '🧠 思考过程 <span style="color:var(--text-muted);font-size:12px;">（连接中断）</span>';
    }
  };

  try {
    // 创建 AI 回复占位（流式填充）
    const aiDiv = document.createElement('div');
    aiDiv.className = 'message ai streaming';
    aiDiv.innerHTML = '<span class="stream-cursor"></span>';
    chat.appendChild(aiDiv);

    let accText = '';
    let accReasoning = '';
    let osintData = null;

    // 用 fetch + ReadableStream 消费 SSE（支持 POST）
    const response = await fetch(`${API_BASE}/api/chat/stream`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ message: message, target: target, history: history.slice(-5), task_id: taskId })
    });

    const reader = response.body.getReader();
    const dec = new TextDecoder();
    let sseBuf = '';
    let lastFlush = 0;

    while (true) {
      const { done, value } = await reader.read();
      if (done) break;
      sseBuf += dec.decode(value, { stream: true });

      // 解析 SSE 事件
      const blocks = sseBuf.split('\n\n');
      sseBuf = blocks.pop(); // 保留最后不完整的块

      for (const block of blocks) {
        const lines = block.split('\n');
        let eventType = 'message';
        let eventData = '';
        for (const line of lines) {
          if (line.startsWith('event: ')) eventType = line.slice(7).trim();
          else if (line.startsWith('data: ')) eventData = line.slice(6);
        }
        if (!eventData) continue;

        try {
          const data = JSON.parse(eventData);

          if (eventType === 'token') {
            accText += data.text;
          } else if (eventType === 'reasoning') {
            accReasoning += data.text;
          } else if (eventType === 'osint') {
            osintData = data;
          } else if (eventType === 'error') {
            accText += `\n\n⚠️ 错误: ${data.text}`;
          } else if (eventType === 'done') {
            // 流结束
          }
        } catch (e) {}

        // 节流刷新 UI（每 50ms）
        const now = Date.now();
        if (now - lastFlush > 50 || eventType === 'done') {
          let html = '';
          if (accReasoning) {
            html += `<details style="margin-bottom:8px;font-size:12px;color:var(--text-secondary)"><summary>💭 思考过程 (${accReasoning.length} 字)</summary><div style="margin-top:6px;white-space:pre-wrap;max-height:200px;overflow-y:auto;color:var(--text-muted)">${escapeHtml(accReasoning)}</div></details>`;
          }
          if (accText) {
            html += formatMarkdown(accText);
          }
          if (!accText && !accReasoning) {
            html = '<span class="stream-cursor"></span>';
          } else {
            html += '<span class="stream-cursor"></span>';
          }
          aiDiv.innerHTML = html;
          chat.scrollTop = chat.scrollHeight;
          lastFlush = now;
        }
      }
    }

    // 最终渲染（去掉光标）
    let finalHtml = '';
    if (accReasoning) {
      finalHtml += `<details style="margin-bottom:8px;font-size:12px;color:var(--text-secondary)"><summary>💭 思考过程 (${accReasoning.length} 字)</summary><div style="margin-top:6px;white-space:pre-wrap;max-height:200px;overflow-y:auto;color:var(--text-muted)">${escapeHtml(accReasoning)}</div></details>`;
    }
    finalHtml += formatMarkdown(accText);
    aiDiv.innerHTML = finalHtml;
    aiDiv.classList.remove('streaming');
    chat.scrollTop = chat.scrollHeight;

    // 保存到历史
    if (accText) {
      history.push({ role: 'user', content: message });
      history.push({ role: 'assistant', content: accText });
      saveHistory();
    }

    // 处理 OSINT 结果
    if (osintData && !osintData.error) {
      const grokPlatforms = osintData.grok_search?.platforms || [];
      const maigretFound = osintData.maigret_found || [];
      const gameFound = osintData.game_found || [];

      const allFindings = [
        ...grokPlatforms.map(p => ({ platform: 'Grok: ' + (p.platform || '?'), url: p.url, snippet: p.snippet })),
        ...maigretFound.map(f => ({ platform: f.platform, url: f.url, snippet: f.snippet })),
        ...gameFound.map(f => ({ platform: '🎮 ' + f.platform, url: f.url, snippet: f.snippet }))
      ];

      if (allFindings.length > 0) addFindings(allFindings);

      const personalInfo = osintData.grok_search?.personal_info || {};
      if (Object.keys(personalInfo).length > 0) addPersonalInfo(personalInfo);

      const deepAnalysis = osintData.deep_analysis || '';
      if (deepAnalysis) addMessage(deepAnalysis, 'ai');

      // 添加报告导出按钮（从 Maigret 学习）
      addReportButtons(target, allFindings, osintData);

      // 显示 D3.js 关系图谱（从 Maigret 学习）
      if (osintData.graph) showGraph(osintData.graph);
    }

    statusText.textContent = '就绪';
  } catch (error) {
    addMessage(`❌ 错误: ${error.message}`, 'system');
    statusText.textContent = '错误';
  } finally {
    sendBtn.disabled = false;
    input.focus();
  }
}

// 健康检查
function checkHealth() {
  const statusText = document.getElementById('status-text');
  fetch(`${API_BASE}/api/health`)
    .then(r => r.json())
    .then(d => {
      if (d.status === 'ok') {
        statusText.textContent = `就绪 · ${d.sites_loaded} 站点`;
      }
    })
    .catch(() => {
      statusText.textContent = '后端未连接';
    });
}

// 初始化
function initChat() {
  const input = document.getElementById('input');
  input.focus();
  checkHealth();
}
