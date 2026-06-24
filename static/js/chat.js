// 聊天功能模块

const API_BASE = window.location.origin;
const STORAGE_KEY = 'osint_history';

let history = [];
let welcomeRemoved = false;

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

// 发送建议
function sendSuggestion(text) {
  const input = document.getElementById('input');
  input.value = text;
  sendMessage();
}

// 发送消息
async function sendMessage() {
  const input = document.getElementById('input');
  const sendBtn = document.getElementById('send-btn');
  const statusText = document.getElementById('status-text');
  const chat = document.getElementById('chat-mode');

  const message = input.value.trim();
  if (!message) return;

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
    const response = await fetch(`${API_BASE}/api/chat`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ message: message, history: history.slice(-5), task_id: taskId })
    });

    const data = await response.json();
    // 不再立即移除 thinkingDiv，保留思考过程显示

    if (data.reply) {
      addMessage(data.reply, 'ai');
      history.push({ role: 'user', content: message });
      history.push({ role: 'assistant', content: data.reply });
      saveHistory();
    }

    if (data.osint_results) {
      const osint = data.osint_results;
      if (osint.error) {
        addMessage(`⚠️ 情报收集出错: ${osint.error}`, 'system');
      } else {
        const grokPlatforms = osint.grok_search?.platforms || [];
        const maigretFound = osint.maigret_found || [];
        const gameFound = osint.game_found || [];

        const allFindings = [
          ...grokPlatforms.map(p => ({ platform: 'Grok: ' + (p.platform || '?'), url: p.url, snippet: p.snippet })),
          ...maigretFound.map(f => ({ platform: f.platform, url: f.url, snippet: f.snippet })),
          ...gameFound.map(f => ({ platform: '🎮 ' + f.platform, url: f.url, snippet: f.snippet }))
        ];

        if (allFindings.length > 0) addFindings(allFindings);

        const personalInfo = osint.grok_search?.personal_info || {};
        if (Object.keys(personalInfo).length > 0) addPersonalInfo(personalInfo);

        const deepAnalysis = osint.deep_analysis || '';
        if (deepAnalysis) addMessage(deepAnalysis, 'ai');
      }
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
