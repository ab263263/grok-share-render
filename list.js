(function () {
    console.log("list.js loaded - with model selector");

    // The proxied Grok HTML sometimes includes Cloudflare challenge/insights scripts.
    // Inside this mirror they can touch iframe.contentWindow.document and crash the
    // whole React tree with "Something went wrong". Block those scripts before the
    // Next.js app hydrates; this file is injected before the app chunks.
    (function blockCloudflareBrowserChallenge() {
        const blockedPatterns = [
            '/cdn-cgi/challenge-platform/',
            'static.cloudflareinsights.com/beacon.min.js',
            'cloudflareinsights.com/beacon.min.js'
        ];
        const isBlockedScript = (src) => !!src && blockedPatterns.some((pattern) => src.includes(pattern));
        const originalAppendChild = Node.prototype.appendChild;
        Node.prototype.appendChild = function(child) {
            if (child && child.tagName === 'SCRIPT' && isBlockedScript(child.src || '')) {
                console.warn('blocked Cloudflare script in mirror:', child.src);
                return child;
            }
            return originalAppendChild.call(this, child);
        };
        document.addEventListener('beforescriptexecute', function(event) {
            const src = event.target && event.target.src;
            if (isBlockedScript(src || '')) {
                event.preventDefault();
                event.stopPropagation();
            }
        }, true);
    })();

    const MODELS = [
        { id: 'grok-3', name: 'Grok 3', tag: 'Fast', color: '#4a9', quota: '30次/天' },
        { id: 'grok-4', name: 'Grok 4', tag: 'Expert', color: '#f90', quota: '7次/天' },
        { id: 'grok-420', name: 'Grok 420', tag: 'Thinking', color: '#f90', quota: '8次/4h' },
        { id: 'grok-4-heavy', name: 'Grok 4 Heavy', tag: 'Heavy', color: '#f55', quota: '20次/2h' },
        { id: 'grok-3-mini-companion', name: 'Mini', tag: 'Fast', color: '#4a9', quota: '10次/h' }
    ];

    // Inject CSS
    const style = document.createElement('style');
    style.textContent = `
        #grok-panel {
            position: fixed;
            top: 80px;
            right: 24px;
            z-index: 999999;
            font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, sans-serif;
            user-select: none;
            -webkit-user-select: none;
        }
        #grok-panel-toggle {
            display: flex;
            align-items: center;
            gap: 8px;
            padding: 10px 16px;
            background: rgba(255,255,255,0.95);
            backdrop-filter: blur(8px);
            border: 1px solid rgba(0,0,0,0.08);
            border-radius: 9999px;
            box-shadow: 0 4px 12px rgba(0,0,0,0.08);
            cursor: pointer;
            transition: all 0.2s;
            color: #1a1a1a;
            font-size: 13px;
            font-weight: 500;
        }
        #grok-panel-toggle:hover {
            transform: translateY(-2px);
            box-shadow: 0 8px 20px rgba(0,0,0,0.12);
        }
        #grok-panel-menu {
            display: none;
            position: absolute;
            top: 48px;
            right: 0;
            width: 260px;
            background: #1a1a1a;
            border: 1px solid #333;
            border-radius: 12px;
            padding: 8px;
            box-shadow: 0 20px 40px rgba(0,0,0,0.5);
        }
        #grok-panel-menu.show { display: block; }
        .grok-model-item {
            display: flex;
            justify-content: space-between;
            align-items: center;
            padding: 10px 12px;
            border-radius: 8px;
            cursor: pointer;
            transition: background 0.15s;
            color: #eee;
        }
        .grok-model-item:hover { background: #2a2a2a; }
        .grok-model-item.active { background: #1a3a2a; border: 1px solid #4a9; }
        .grok-model-left { display: flex; align-items: center; gap: 8px; }
        .grok-model-name { font-size: 13px; font-weight: 600; }
        .grok-model-tag {
            font-size: 10px;
            padding: 2px 6px;
            border-radius: 4px;
            font-weight: 600;
        }
        .grok-model-quota { font-size: 11px; color: #888; }
        .grok-panel-title {
            font-size: 11px;
            color: #666;
            padding: 8px 12px 4px;
            text-transform: uppercase;
            letter-spacing: 0.5px;
        }
        .grok-panel-info {
            font-size: 11px;
            color: #555;
            padding: 8px 12px;
            border-top: 1px solid #2a2a2a;
            margin-top: 4px;
        }
        .grok-panel-action {
            width: 100%;
            border: 1px solid #333;
            background: #111;
            color: #eee;
            border-radius: 8px;
            padding: 10px 12px;
            margin-top: 6px;
            cursor: pointer;
            text-align: left;
            font-size: 12px;
            transition: border-color 0.15s, background 0.15s;
        }
        .grok-panel-action:hover { border-color: #4a9; background: #151515; }
        #grok-imagine-dialog {
            display: none;
            position: fixed;
            inset: 0;
            z-index: 1000000;
            background: rgba(0,0,0,0.55);
            align-items: center;
            justify-content: center;
            padding: 20px;
            font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, sans-serif;
        }
        #grok-imagine-dialog.show { display: flex; }
        .grok-imagine-card {
            width: min(520px, 100%);
            background: #151515;
            border: 1px solid #333;
            border-radius: 16px;
            box-shadow: 0 24px 80px rgba(0,0,0,0.5);
            color: #eee;
            padding: 18px;
        }
        .grok-imagine-card h3 { font-size: 16px; margin: 0 0 8px; }
        .grok-imagine-card p { font-size: 12px; color: #888; margin: 0 0 12px; line-height: 1.5; }
        .grok-imagine-card textarea {
            width: 100%;
            min-height: 120px;
            resize: vertical;
            border-radius: 10px;
            border: 1px solid #333;
            background: #0a0a0a;
            color: #eee;
            padding: 12px;
            outline: none;
            font-size: 13px;
            line-height: 1.5;
        }
        .grok-imagine-buttons { display: flex; gap: 8px; margin-top: 12px; }
        .grok-imagine-buttons button {
            flex: 1;
            border: 0;
            border-radius: 10px;
            padding: 11px 12px;
            cursor: pointer;
            font-weight: 600;
        }
        .grok-imagine-primary { background: #fff; color: #111; }
        .grok-imagine-secondary { background: #252525; color: #ddd; }
        [data-theme="dark"] #grok-panel-toggle,
        .dark #grok-panel-toggle {
            background: rgba(30,30,30,0.95);
            color: #eee;
            border-color: rgba(255,255,255,0.1);
        }
    `;
    document.head ? document.head.appendChild(style) : document.documentElement.appendChild(style);

    function getSelectedModel() {
        return localStorage.getItem('grok-selected-model') || 'grok-3';
    }

    function setSelectedModel(id) {
        localStorage.setItem('grok-selected-model', id);
        updatePanel();
    }

    function createPanel() {
        const panel = document.createElement('div');
        panel.id = 'grok-panel';

        const toggle = document.createElement('div');
        toggle.id = 'grok-panel-toggle';
        toggle.innerHTML = '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" width="16" height="16"><circle cx="12" cy="12" r="3"/><path d="M19.4 15a1.65 1.65 0 00.33 1.82l.06.06a2 2 0 01-2.83 2.83l-.06-.06a1.65 1.65 0 00-1.82-.33 1.65 1.65 0 00-1 1.51V21a2 2 0 01-4 0v-.09A1.65 1.65 0 009 19.4a1.65 1.65 0 00-1.82.33l-.06.06a2 2 0 01-2.83-2.83l.06-.06A1.65 1.65 0 004.68 15a1.65 1.65 0 00-1.51-1H3a2 2 0 010-4h.09A1.65 1.65 0 004.6 9a1.65 1.65 0 00-.33-1.82l-.06-.06a2 2 0 012.83-2.83l.06.06A1.65 1.65 0 009 4.68a1.65 1.65 0 001-1.51V3a2 2 0 014 0v.09a1.65 1.65 0 001 1.51 1.65 1.65 0 001.82-.33l.06-.06a2 2 0 012.83 2.83l-.06.06A1.65 1.65 0 0019.4 9a1.65 1.65 0 001.51 1H21a2 2 0 010 4h-.09a1.65 1.65 0 00-1.51 1z"/></svg><span id="grok-model-label">Grok 3</span>';

        const menu = document.createElement('div');
        menu.id = 'grok-panel-menu';

        const title = document.createElement('div');
        title.className = 'grok-panel-title';
        title.textContent = '选择模型';
        menu.appendChild(title);

        MODELS.forEach(m => {
            const item = document.createElement('div');
            item.className = 'grok-model-item';
            item.dataset.model = m.id;
            item.innerHTML = `<div class="grok-model-left"><span class="grok-model-name">${m.name}</span><span class="grok-model-tag" style="background:${m.color}22;color:${m.color}">${m.tag}</span></div><span class="grok-model-quota">${m.quota}</span>`;
            item.addEventListener('click', () => {
                setSelectedModel(m.id);
                menu.classList.remove('show');
            });
            menu.appendChild(item);
        });

        const imagine = document.createElement('button');
        imagine.type = 'button';
        imagine.className = 'grok-panel-action';
        imagine.textContent = 'Imagine 图片生成';
        imagine.addEventListener('click', (e) => {
            e.stopPropagation();
            menu.classList.remove('show');
            openImagineDialog();
        });
        menu.appendChild(imagine);

        const info = document.createElement('div');
        info.className = 'grok-panel-info';
        info.textContent = '账号池运行时注入 | 源码不暴露 Token';
        menu.appendChild(info);

        toggle.addEventListener('click', (e) => {
            e.stopPropagation();
            menu.classList.toggle('show');
        });

        document.addEventListener('click', () => menu.classList.remove('show'));

        panel.appendChild(toggle);
        panel.appendChild(menu);
        document.body.appendChild(panel);
        return panel;
    }

    function updatePanel() {
        const selected = getSelectedModel();
        const model = MODELS.find(m => m.id === selected) || MODELS[0];
        const label = document.getElementById('grok-model-label');
        if (label) label.textContent = model.name;

        document.querySelectorAll('.grok-model-item').forEach(el => {
            el.classList.toggle('active', el.dataset.model === selected);
        });
    }

    // Intercept fetch to inject model
    const origFetch = window.fetch;
    window.fetch = function(...args) {
        const url = typeof args[0] === 'string' ? args[0] : args[0]?.url;
        if (url && url.includes('/rest/app-chat')) {
            try {
                const body = args[1]?.body;
                if (body && typeof body === 'string') {
                    const parsed = JSON.parse(body);
                    const selected = getSelectedModel();
                    if (selected && !parsed.model) {
                        parsed.model = selected;
                        args[1] = {...args[1], body: JSON.stringify(parsed)};
                    }
                }
            } catch(e) {}
        }
        return origFetch.apply(this, args);
    };

    function createImagineDialog() {
        const dialog = document.createElement('div');
        dialog.id = 'grok-imagine-dialog';
        dialog.innerHTML = '<div class="grok-imagine-card"><h3>Grok Imagine 图片生成</h3><p>先做图片，不做视频。输入图片提示词后会自动打开一个新聊天，并把提示词整理成 Grok Imagine 请求。若当前账号不支持 Imagine，请换号或换模型后重试。</p><textarea id="grok-imagine-prompt" placeholder="例如：赛博朋克香港雨夜，霓虹灯，电影质感，35mm，超细节"></textarea><div class="grok-imagine-buttons"><button type="button" class="grok-imagine-secondary" id="grok-imagine-close">取消</button><button type="button" class="grok-imagine-primary" id="grok-imagine-send">发送到聊天</button></div></div>';
        document.body.appendChild(dialog);
        dialog.addEventListener('click', (event) => {
            if (event.target === dialog) closeImagineDialog();
        });
        dialog.querySelector('#grok-imagine-close').addEventListener('click', closeImagineDialog);
        dialog.querySelector('#grok-imagine-send').addEventListener('click', sendImaginePrompt);
        return dialog;
    }

    function openImagineDialog() {
        const dialog = document.getElementById('grok-imagine-dialog') || createImagineDialog();
        dialog.classList.add('show');
        const input = document.getElementById('grok-imagine-prompt');
        if (input) setTimeout(() => input.focus(), 0);
    }

    function closeImagineDialog() {
        const dialog = document.getElementById('grok-imagine-dialog');
        if (dialog) dialog.classList.remove('show');
    }

    function sendImaginePrompt() {
        const input = document.getElementById('grok-imagine-prompt');
        const raw = input ? input.value.trim() : '';
        if (!raw) return;
        const prompt = '请使用 Grok Imagine 生成一张图片。要求：' + raw + '\n只生成图片，不要生成视频。';
        closeImagineDialog();
        try {
            navigator.clipboard && navigator.clipboard.writeText(prompt);
        } catch (e) {}
        const encoded = encodeURIComponent(prompt);
        window.location.href = '/?q=' + encoded;
    }

    // Create switch account button (original functionality)
    function createSwitchButton() {
        const btn = document.createElement('div');
        btn.id = 'grok-switch-btn';
        btn.style.cssText = 'position:fixed;top:140px;right:24px;z-index:999999;display:flex;align-items:center;gap:8px;padding:10px 16px;background:rgba(255,255,255,0.95);backdrop-filter:blur(8px);border:1px solid rgba(0,0,0,0.08);border-radius:9999px;box-shadow:0 4px 12px rgba(0,0,0,0.08);cursor:pointer;transition:all 0.2s;font-family:-apple-system,BlinkMacSystemFont,"Segoe UI",Roboto,sans-serif;color:#1a1a1a;font-size:13px;font-weight:500;';
        btn.innerHTML = '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" width="16" height="16"><path d="M4 4v5h.582m15.356 2A8.001 8.001 0 004.582 9m0 0H9m11 11v-5h-.581m0 0a8.003 8.003 0 01-15.357-2m15.357 2H15"/></svg><span>换号</span>';
        btn.addEventListener('click', () => window.location.href = '/');
        document.body.appendChild(btn);
    }

    function init() {
        if (!document.getElementById('grok-panel')) createPanel();
        if (!document.getElementById('grok-switch-btn')) createSwitchButton();
        if (!document.getElementById('grok-imagine-dialog')) createImagineDialog();
        updatePanel();
    }

    if (document.body) init();
    else window.addEventListener('DOMContentLoaded', init);

    const observer = new MutationObserver(() => {
        if (!document.getElementById('grok-panel')) init();
    });
    if (document.body) observer.observe(document.body, { childList: true, subtree: true });
})();
