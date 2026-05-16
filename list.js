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

        const info = document.createElement('div');
        info.className = 'grok-panel-info';
        info.textContent = '3504 账号自动轮询 | 点击切换账号';
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
        updatePanel();
    }

    if (document.body) init();
    else window.addEventListener('DOMContentLoaded', init);

    const observer = new MutationObserver(() => {
        if (!document.getElementById('grok-panel')) init();
    });
    if (document.body) observer.observe(document.body, { childList: true, subtree: true });
})();
