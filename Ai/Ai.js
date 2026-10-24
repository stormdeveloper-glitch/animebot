/* ══════════════════════════════════════════════════════════
   AnimeUz Ai - ANIME UZ
   Suhbatlar tarixi (localStorage), kunlik 5 urinish, AniList kartalari va kesh.
   ══════════════════════════════════════════════════════════ */

(() => {
    'use strict';

    // ── DOM ──
    const $ = (id) => document.getElementById(id);
    const chatBody = $('chatBody');
    const chatMessages = $('chatMessages');
    const welcome = $('welcome');
    const composer = $('composer');
    const input = $('messageInput');
    const adminInput = $('adminPasswordInput');
    const sendBtn = $('sendBtn');
    const quotaBadge = $('quotaBadge');
    const quotaText = $('quotaText');
    const quotaNote = $('quotaNote');
    const historyPanel = $('historyPanel');
    const historyList = $('historyList');
    const historyBackdrop = $('historyBackdrop');
    const chatMenu = $('chatMenu');

    // ── Konstantalar ──
    const LS_SESSIONS = 'az_ai_chat_sessions';
    const LS_MSG_PREFIX = 'az_ai_chat_msgs_';
    const LS_ACTIVE = 'az_ai_active_session';
    const LS_THEME = 'az_ai_theme';
    const LS_DEVICE = 'az_device_id';
    const LS_CACHE_VERSION = 'az_ai_cache_version';
    const LS_POSTER_CACHE = 'az_ai_poster_cache_v1';
    const LS_DETAIL_CACHE = 'az_ai_detail_cache_v1';
    const MAX_INPUT = 800;
    const MAX_SESSIONS = 60;
    const MAX_CACHED_POSTERS = 80;
    const MAX_CACHED_DETAILS = 40;
    const DETAIL_CACHE_TTL = 6 * 60 * 60 * 1000;
    const CACHE_CHECK_MS = 15 * 60 * 1000;

    const state = {
        sessions: [],
        activeId: null,
        messages: [],
        waiting: false,
        adminPassword: false,
        quota: { limit: 5, used: 0, remaining: 5, reset_at: null },
        options: { reasoning: false, research: false },
        theme: 'dark',
        recognition: null,
        speakingBtn: null,
        cacheVersion: localStorage.getItem(LS_CACHE_VERSION) || '',
        cacheNextCheck: 0,
        modalCard: null,
        lastFocused: null,
    };

    // ── Yordamchilar ──
    function deviceId() {
        let id = localStorage.getItem(LS_DEVICE);
        if (!id) {
            id = 'dev_' + Math.random().toString(36).slice(2) + Date.now().toString(36);
            localStorage.setItem(LS_DEVICE, id);
        }
        return id;
    }

    const DEVICE_ID = deviceId();
    const authHeaders = () => {
        const token = localStorage.getItem('az_token') || '';
        return token ? { Authorization: 'Bearer ' + token } : {};
    };

    function escapeHtml(value) {
        return String(value ?? '').replace(/[&<>"']/g, (ch) => ({
            '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;',
        }[ch]));
    }

    function formatMarkdown(text) {
        let out = escapeHtml(text || '');
        out = out
            .replace(/\*\*([^*]+)\*\*/g, '<strong>$1</strong>')
            .replace(/(^|[\s(])\*([^*\n]+)\*/g, '$1<em>$2</em>')
            .replace(/`([^`]+)`/g, '<code>$1</code>')
            .replace(/\n/g, '<br>');
        return out;
    }

    function plainText(text) {
        return String(text || '')
            .replace(/\[(?:ANIME_CARD|ANILIST_CARD):[^\]]*\]/g, '')
            .replace(/[*_`#>]/g, '')
            .replace(/<[^>]+>/g, '')
            .trim();
    }

    function toast(message, type = '') {
        const stack = $('toastStack');
        const el = document.createElement('div');
        el.className = 'toast' + (type ? ' is-' + type : '');
        el.textContent = message;
        stack.appendChild(el);
        setTimeout(() => {
            el.classList.add('is-out');
            setTimeout(() => el.remove(), 260);
        }, 3200);
    }

    function scrollToBottom(smooth = true) {
        chatBody.scrollTo({ top: chatBody.scrollHeight, behavior: smooth ? 'smooth' : 'auto' });
    }

    function newId() {
        return 'c' + Date.now().toString(36) + Math.random().toString(36).slice(2, 8);
    }

    function loadJSON(key, fallback) {
        try {
            const raw = localStorage.getItem(key);
            return raw ? JSON.parse(raw) : fallback;
        } catch {
            return fallback;
        }
    }

    // ——— Qurilma keshi (posterlar, ma'lumotlar, havolalar) ———
    function readCacheStore(key) {
        const store = loadJSON(key, null);
        if (!store || typeof store.items !== 'object' || !store.items || store.version !== state.cacheVersion) {
            return { version: state.cacheVersion, items: {} };
        }
        return store;
    }

    function writeCacheStore(key, store) {
        try {
            localStorage.setItem(key, JSON.stringify(store));
        } catch {
            // localStorage to'lgan bo'lsa, eng eski yozuvlarni tozalab qayta urinamiz.
            try {
                const items = Object.entries(store.items || {})
                    .sort((a, b) => (a[1].ts || 0) - (b[1].ts || 0))
                    .slice(-Math.floor(Object.keys(store.items || {}).length / 2));
                store.items = Object.fromEntries(items);
                localStorage.setItem(key, JSON.stringify(store));
            } catch { /* kesh mavjud bo'lmasa ham sahifa ishlaydi */ }
        }
    }

    function pruneCache(store, max) {
        const rows = Object.entries(store.items || {});
        if (rows.length <= max) return;
        rows.sort((a, b) => (a[1].ts || 0) - (b[1].ts || 0));
        store.items = Object.fromEntries(rows.slice(rows.length - max));
    }

    function posterCacheKey(card) {
        return card.kind + ':' + String(card.id);
    }

    function getCachedPoster(card) {
        const store = readCacheStore(LS_POSTER_CACHE);
        const hit = store.items[posterCacheKey(card)];
        return hit && hit.src ? hit.src : '';
    }

    function rememberPoster(card, img) {
        if (!img || !img.src || img.dataset.cacheTried === '1') return;
        const key = posterCacheKey(card);
        try {
            const url = new URL(img.src, window.location.origin);
            const ok = url.origin === window.location.origin
                && (/^\/poster\/[0-9]+$/.test(url.pathname) || /^\/api\/ai\/poster\/[0-9]+$/.test(url.pathname));
            if (!ok) return;
        } catch {
            return;
        }
        img.dataset.cacheTried = '1';

        const save = () => {
            try {
                if (!img.naturalWidth || !img.naturalHeight) return;
                const width = 180;
                const height = Math.round(width * 1.5);
                const canvas = document.createElement('canvas');
                canvas.width = width;
                canvas.height = height;
                const ctx = canvas.getContext('2d');
                if (!ctx) return;
                ctx.drawImage(img, 0, 0, width, height);
                const src = canvas.toDataURL('image/jpeg', 0.74);
                if (!src || src.length > 60000) return;
                const store = readCacheStore(LS_POSTER_CACHE);
                store.items[key] = { src, ts: Date.now() };
                pruneCache(store, MAX_CACHED_POSTERS);
                writeCacheStore(LS_POSTER_CACHE, store);
            } catch { /* rasm keshlanmasa ham ko'rinadi */ }
        };

        if (img.complete && img.naturalWidth) save();
        else img.addEventListener('load', save, { once: true });
    }

    async function loadCacheVersion() {
        try {
            const res = await fetch('/api/ai/cache/version', {
                cache: 'no-store',
                headers: authHeaders(),
            });
            const data = await res.json();
            if (!data || !data.ok || !data.version) return;
            const oldVersion = state.cacheVersion;
            state.cacheVersion = String(data.version);
            try { localStorage.setItem(LS_CACHE_VERSION, state.cacheVersion); } catch { /* ignore */ }
            const seconds = Math.max(300, Number(data.check_after_seconds) || 900);
            state.cacheNextCheck = Date.now() + seconds * 1000;
            if (oldVersion && oldVersion !== state.cacheVersion) {
                try {
                    localStorage.removeItem(LS_POSTER_CACHE);
                    localStorage.removeItem(LS_DETAIL_CACHE);
                } catch { /* ignore */ }
                renderAll();
            }
        } catch {
            state.cacheNextCheck = Date.now() + CACHE_CHECK_MS;
        }
    }

    function scheduleCacheCheck() {
        window.setInterval(() => {
            if (document.hidden) return;
            loadCacheVersion();
        }, CACHE_CHECK_MS);
        document.addEventListener('visibilitychange', () => {
            if (!document.hidden && Date.now() >= state.cacheNextCheck) loadCacheVersion();
        });
    }

    function greetingName(user) {
        if (!user) return "do'stim";
        const email = String(user.email || '').trim();
        if (email) {
            const local = email.split('@')[0].replace(/[._+\-]+/g, ' ').replace(/\d+/g, ' ').trim();
            const first = local.split(/\s+/).filter(Boolean)[0];
            if (first) return first.charAt(0).toUpperCase() + first.slice(1);
        }
        if (user.name) {
            const first = String(user.name).trim().split(/\s+/)[0];
            if (first) return first;
        }
        return "do'stim";
    }

    function displayInitial(user) {
        const name = (user && (user.name || user.email)) || '';
        return String(name).trim().charAt(0).toUpperCase() || 'AI';
    }

    // ── Mavzu ──
    function applyTheme(theme) {
        state.theme = theme === 'light' ? 'light' : 'dark';
        document.documentElement.dataset.theme = state.theme;
        localStorage.setItem(LS_THEME, state.theme);
        const meta = document.querySelector('meta[name="theme-color"]');
        if (meta) meta.content = state.theme === 'light' ? '#eef2e7' : '#050704';
        const sun = $('themeSunBtn');
        const moon = $('themeMoonBtn');
        if (sun) sun.setAttribute('aria-pressed', String(state.theme === 'light'));
        if (moon) moon.setAttribute('aria-pressed', String(state.theme === 'dark'));
    }

    function initTheme() {
        const saved = localStorage.getItem(LS_THEME);
        if (saved) {
            applyTheme(saved);
            return;
        }
        const prefersLight = window.matchMedia && window.matchMedia('(prefers-color-scheme: light)').matches;
        applyTheme(prefersLight ? 'light' : 'dark');
    }

    // ── Foydalanuvchi ──
    function applyUser(user) {
        const img = $('userAvatarImg');
        const fallback = document.querySelector('.avatar-fallback');
        const greetName = $('greetName');
        if (greetName) greetName.textContent = greetingName(user);
        if (fallback) fallback.textContent = displayInitial(user);

        if (user && typeof user.picture === 'string' && /^https:\/\//.test(user.picture) && img) {
            img.src = user.picture;
            img.hidden = false;
            img.onerror = () => { img.hidden = true; if (fallback) fallback.hidden = false; };
            if (fallback) fallback.hidden = true;
        }
    }

    function initUser() {
        const user = loadJSON('az_user', null);
        applyUser(user);

        const hour = new Date().getHours();
        const prefix = hour < 6 ? 'Xayrli tun' : hour < 12 ? 'Xayrli tong' : hour < 18 ? 'Xayrli kun' : 'Xayrli kech';
        $('greetingPrefix').textContent = prefix;

        // Google OAuth sessiyasi bo'lsa, email nomini serverdan aniqlashtiramiz.
        const token = localStorage.getItem('az_token') || '';
        if (token && (!user || !user.email)) {
            fetch('/api/auth/me', { headers: authHeaders() })
                .then((res) => res.json())
                .then((data) => {
                    if (!data || !data.ok || !data.user) return;
                    try { localStorage.setItem('az_user', JSON.stringify(data.user)); } catch { /* ignore */ }
                    applyUser(data.user);
                })
                .catch(() => { /* mehmon sifatida davom etadi */ });
        }
    }

    // ── Suhbatlar ──
    function loadSessions() {
        const stored = loadJSON(LS_SESSIONS, []);
        state.sessions = Array.isArray(stored)
            ? stored.filter((s) => s && typeof s.id === 'string')
            : [];
    }

    function saveSessions() {
        localStorage.setItem(LS_SESSIONS, JSON.stringify(state.sessions.slice(0, MAX_SESSIONS)));
    }

    function loadMessages(id) {
        if (!id) return [];
        const stored = loadJSON(LS_MSG_PREFIX + id, []);
        return Array.isArray(stored) ? stored.filter((m) => m && typeof m.text === 'string') : [];
    }

    function saveMessages() {
        if (!state.activeId) return;
        localStorage.setItem(LS_MSG_PREFIX + state.activeId, JSON.stringify(state.messages));
    }

    function sessionById(id) {
        return state.sessions.find((s) => s.id === id) || null;
    }

    function touchSession() {
        if (!state.activeId) return;
        const session = sessionById(state.activeId);
        if (!session) return;
        session.count = state.messages.length;
        session.updated_at = new Date().toISOString();
        if (session.title === 'Yangi suhbat') {
            const firstUser = state.messages.find((m) => m.role === 'user');
            if (firstUser) session.title = firstUser.text.replace(/\s+/g, ' ').slice(0, 46);
        }
        state.sessions = [session, ...state.sessions.filter((s) => s.id !== session.id)];
        saveSessions();
        renderHistory();
        syncSession(session);
    }

    function ensureSession() {
        let session = state.activeId ? sessionById(state.activeId) : null;
        if (session) return session;

        const id = state.activeId || newId();
        session = {
            id,
            title: 'Yangi suhbat',
            created_at: new Date().toISOString(),
            updated_at: new Date().toISOString(),
            count: 0,
        };
        state.activeId = id;
        state.sessions.unshift(session);
        localStorage.setItem(LS_ACTIVE, id);
        saveSessions();
        renderHistory();
        return session;
    }

    function syncSession(session) {
        fetch('/api/ai/sessions', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json', ...authHeaders() },
            body: JSON.stringify({
                device_id: DEVICE_ID,
                session_id: session.id,
                title: session.title,
                message_count: session.count || 0,
            }),
        }).catch(() => { });
    }

    function syncDeleteSession(id) {
        fetch(`/api/ai/sessions/${encodeURIComponent(id)}?device_id=${encodeURIComponent(DEVICE_ID)}`, {
            method: 'DELETE',
            headers: authHeaders(),
        }).catch(() => { });
    }

    function groupSessions() {
        const groups = new Map();
        const now = new Date();
        const startOfToday = new Date(now.getFullYear(), now.getMonth(), now.getDate()).getTime();

        for (const session of state.sessions) {
            const ts = Date.parse(session.updated_at || session.created_at || '') || 0;
            const days = ts ? Math.floor((startOfToday - new Date(ts).setHours(0, 0, 0, 0)) / 86400000) : 99;
            let label;
            if (days <= 0) label = 'Bugun';
            else if (days === 1) label = 'Kecha';
            else if (days <= 5) label = "So'nggi 5 kun";
            else if (days <= 7) label = "So'nggi 7 kun";
            else label = 'Avvalroq';
            if (!groups.has(label)) groups.set(label, []);
            groups.get(label).push(session);
        }
        return groups;
    }

    function renderHistory() {
        historyList.innerHTML = '';
        const groups = groupSessions();

        if (!state.sessions.length) {
            const empty = document.createElement('div');
            empty.className = 'history-empty';
            empty.innerHTML = `
                <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.5" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true">
                    <path d="M21 12a8.5 8.5 0 0 1-12.3 7.6L3 21l1.4-5.7A8.5 8.5 0 1 1 21 12Z"/>
                    <path d="M8 12h8"/>
                </svg>
                <span>Hozircha suhbatlar yo'q.<br>Birinchi savolingizni yozing!</span>`;
            historyList.appendChild(empty);
            return;
        }

        for (const [label, sessions] of groups) {
            const group = document.createElement('div');
            group.className = 'history-group';
            const title = document.createElement('h3');
            title.textContent = label;
            group.appendChild(title);

            for (const session of sessions) {
                const item = document.createElement('div');
                item.className = 'history-item' + (session.id === state.activeId ? ' is-active' : '');
                item.dataset.id = session.id;
                item.setAttribute('role', 'button');
                item.tabIndex = 0;

                const icon = document.createElement('span');
                icon.className = 'history-item-ico';
                icon.innerHTML = `<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.7" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><path d="M21 12a8.5 8.5 0 0 1-12.3 7.6L3 21l1.4-5.7A8.5 8.5 0 1 1 21 12Z"/></svg>`;

                const labelEl = document.createElement('span');
                labelEl.className = 'history-item-title';
                labelEl.textContent = session.title || 'Suhbat';

                const del = document.createElement('button');
                del.type = 'button';
                del.className = 'history-item-del';
                del.setAttribute('aria-label', 'Suhbatni o\'chirish');
                del.innerHTML = `<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" aria-hidden="true"><path d="M6 6l12 12M18 6 6 18"/></svg>`;

                item.append(icon, labelEl, del);
                group.appendChild(item);
            }
            historyList.appendChild(group);
        }
    }

    function switchSession(id) {
        if (state.waiting) {
            toast('Javob kutilmoqda. Iltimos, biroz kuting.');
            return;
        }
        state.activeId = id;
        localStorage.setItem(LS_ACTIVE, id);
        state.messages = loadMessages(id);
        renderAll();
        renderHistory();
        closeHistoryDrawer();
    }

    function newChat() {
        if (state.waiting) {
            toast('Javob kutilmoqda. Iltimos, biroz kuting.');
            return;
        }
        // Bo'sh suhbat tarixga yozilmaydi.
        state.activeId = null;
        state.messages = [];
        setAdminMode(false);
        localStorage.removeItem(LS_ACTIVE);
        renderAll();
        renderHistory();
        closeHistoryDrawer();
        input.focus();
    }

    function deleteSession(id) {
        state.sessions = state.sessions.filter((s) => s.id !== id);
        localStorage.removeItem(LS_MSG_PREFIX + id);
        saveSessions();
        syncDeleteSession(id);

        if (state.activeId === id) {
            state.activeId = null;
            state.messages = [];
            localStorage.removeItem(LS_ACTIVE);
            renderAll();
        }
        renderHistory();
        toast("Suhbat o'chirildi.");
    }

    function deleteAllSessions() {
        if (!state.sessions.length) {
            toast("Tarix allaqachon bo'sh.");
            return;
        }
        if (!window.confirm('Barcha suhbatlar tarixini o\'chirishni tasdiqlaysizmi?')) return;
        const ids = state.sessions.map((s) => s.id);
        for (const id of ids) {
            localStorage.removeItem(LS_MSG_PREFIX + id);
            syncDeleteSession(id);
        }
        state.sessions = [];
        state.activeId = null;
        state.messages = [];
        localStorage.removeItem(LS_ACTIVE);
        saveSessions();
        renderAll();
        renderHistory();
        toast("Barcha suhbatlar o'chirildi.");
    }

    function clearCurrentChat() {
        if (!state.activeId) {
            state.messages = [];
            renderAll();
            return;
        }
        deleteSession(state.activeId);
    }

    // ── Render ──
    function renderAll() {
        chatMessages.innerHTML = '';
        welcome.classList.toggle('is-hidden', state.messages.length > 0);
        state.messages.forEach((msg, index) => {
            chatMessages.appendChild(buildMessageRow(msg, index));
        });
        scrollToBottom(false);
        updateComposerState();
    }

    function buildMessageRow(msg, index) {
        const row = document.createElement('div');
        row.className = 'msg-row ' + (msg.role === 'user' ? 'user' : 'bot');
        row.dataset.index = String(index);

        const avatar = document.createElement('div');
        avatar.className = 'msg-avatar';
        if (msg.role === 'user') {
            avatar.textContent = userInitial();
        } else {
            const img = document.createElement('img');
            img.src = '../Ai/Ai.png';
            img.alt = 'AnimeUz Ai';
            avatar.appendChild(img);
        }

        const content = document.createElement('div');
        content.className = 'msg-content';

        const bubble = document.createElement('div');
        bubble.className = 'msg-bubble';

        let text = msg.text;
        if (msg.role === 'bot') {
            const parsed = parseCards(text);
            text = parsed.text;
            bubble.innerHTML = formatMarkdown(text);
            if (parsed.cards.length) {
                row.classList.add('has-cards');
                bubble.appendChild(buildCards(parsed.cards));
            }
        } else {
            bubble.textContent = text;
        }

        content.appendChild(bubble);
        content.appendChild(buildActions(msg, index));
        row.append(avatar, content);
        return row;
    }

    function userInitial() {
        return displayInitial(loadJSON('az_user', null));
    }

    function icon(name) {
        const icons = {
            copy: '<path d="M9 9h9v11H7V9h2Z"/><path d="M6 15H4V4h9v2"/>',
            like: '<path d="M7 21H4V10h3M7 10l4-7a2 2 0 0 1 2 2v4h4.5a2.5 2.5 0 0 1 2.4 3.2l-1.5 6A2.5 2.5 0 0 1 16 21H7"/>',
            dislike: '<path d="M17 3h3v11h-3M17 14l-4 7a2 2 0 0 1-2-2v-4H6.5a2.5 2.5 0 0 1-2.4-3.2l1.5-6A2.5 2.5 0 0 1 8 3h9"/>',
            speak: '<path d="M4 9v6h4l5 4V5L8 9H4Z"/><path d="M16.5 8.5a5 5 0 0 1 0 7M19 6a8.5 8.5 0 0 1 0 12"/>',
            download: '<path d="M12 3v12"/><path d="m7 10 5 5 5-5"/><path d="M4 21h16"/>',
            regen: '<path d="M20 11a8 8 0 1 0-2.3 6"/><path d="M20 5v6h-6"/>',
        };
        return `<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.7" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true">${icons[name] || ''}</svg>`;
    }

    function buildActions(msg, index) {
        const actions = document.createElement('div');
        actions.className = 'msg-actions';

        const defs = [{ action: 'copy', label: 'Nusxa olish', ico: 'copy' }];
        if (msg.role === 'bot') {
            defs.push(
                { action: 'like', label: 'Yoqdi', ico: 'like' },
                { action: 'dislike', label: 'Yoqmadi', ico: 'dislike' },
                { action: 'speak', label: "Ovozli o'qish", ico: 'speak' },
                { action: 'download', label: 'Yuklab olish', ico: 'download' },
                { action: 'regen', label: 'Qayta yaratish', ico: 'regen' },
            );
        }

        for (const def of defs) {
            const btn = document.createElement('button');
            btn.type = 'button';
            btn.dataset.action = def.action;
            btn.dataset.index = String(index);
            btn.title = def.label;
            btn.setAttribute('aria-label', def.label);
            btn.innerHTML = icon(def.ico);
            if (msg.feedback === def.action) btn.classList.add('is-on');
            actions.appendChild(btn);
        }
        return actions;
    }

    function parseCards(text) {
        const cards = [];
        let clean = String(text || '');

        clean = clean.replace(/\[ANIME_CARD:([^\]]*)\]/g, (_, body) => {
            const [id, title, cover, year, episodes, type] = body.split('|');
            if (/^[0-9]+$/.test(id || '')) {
                cards.push({ kind: 'local', id, title, cover, year, episodes, type });
            }
            return '';
        });

        clean = clean.replace(/\[ANILIST_CARD:([^\]]*)\]/g, (_, body) => {
            const [id, title, cover, url, year, episodes, score, format, status] = body.split('|');
            if (id) cards.push({ kind: 'anilist', id, title, cover, url, year, episodes, score, format, status });
            return '';
        });

        return { text: clean.replace(/\n{3,}/g, '\n\n').trim(), cards };
    }

    function safeImageUrl(raw) {
        if (!raw) return '';
        try {
            const url = new URL(raw, window.location.origin);
            if (url.protocol === 'data:' && /^data:image\/(jpeg|png|webp);base64,/i.test(raw)) return raw;
            if (url.origin === window.location.origin && /^\/(poster|api\/ai\/poster)\/[0-9]+$/.test(url.pathname)) {
                return url.href;
            }
            if (url.protocol === 'https:' && /(^|\.)anilist\.co$/i.test(url.hostname)) return url.href;
        } catch { /* ignore */ }
        return '';
    }

    function safeExternalUrl(raw) {
        if (!raw) return '';
        try {
            const url = new URL(raw);
            if (url.protocol === 'https:') return url.href;
        } catch { /* ignore */ }
        return '';
    }

    function cardPosterUrl(card) {
        if (card.kind === 'anilist') {
            const version = state.cacheVersion ? `?v=${encodeURIComponent(state.cacheVersion)}` : '';
            return `/api/ai/poster/${encodeURIComponent(card.id)}${version}`;
        }
        const safe = safeImageUrl(card.cover);
        return safe || `/poster/${encodeURIComponent(card.id)}`;
    }

    function statusLabel(value) {
        const raw = String(value || '').toUpperCase();
        if (!raw) return '';
        if (raw.includes('RELEASING') || raw.includes('ONGOING') || raw.includes('DAVOM')) return 'Davom etmoqda';
        if (raw.includes('FINISHED') || raw.includes('TUGALLANGAN')) return 'Tugallangan';
        if (raw.includes('NOT_YET') || raw.includes('CHIQMOQDA')) return 'Chiqmoqda';
        if (raw.includes('CANCELLED') || raw.includes('BEKOR')) return 'Bekor qilingan';
        if (raw.includes('HIATUS') || raw.includes("TO'XTATILGAN")) return "To'xtatilgan";
        return raw;
    }

    function formatLabel(value) {
        const raw = String(value || '').toUpperCase();
        const map = {
            TV: 'TV', TV_SHORT: 'TV qisqa', MOVIE: 'Film', SPECIAL: 'Special',
            OVA: 'OVA', ONA: 'ONA', MUSIC: 'Musiqa',
        };
        return map[raw] || (raw ? raw.replace(/_/g, ' ') : '');
    }

    function episodeText(value) {
        const match = String(value || '').match(/[0-9]+/);
        return match ? `${match[0]} qism` : '';
    }

    function scoreText(value) {
        const num = Number(value);
        if (!Number.isFinite(num) || num <= 0) return '';
        return `${Math.round(num)}/100`;
    }

    function makeBadge(text, cls = '') {
        if (!text) return null;
        const span = document.createElement('span');
        span.className = 'ai-badge' + (cls ? ' ' + cls : '');
        if (cls === 'is-score') {
            span.innerHTML = '<svg viewBox="0 0 24 24" aria-hidden="true"><path d="M12 2.5l2.9 6.1 6.6.9-4.8 4.7 1.2 6.6-5.9-3.2-5.9 3.2 1.2-6.6L2.5 9.5l6.6-.9L12 2.5z"/></svg>';
            span.appendChild(document.createTextNode(text));
        } else {
            span.textContent = text;
        }
        return span;
    }

    function buildCards(cards) {
        const wrap = document.createElement('div');
        wrap.className = 'ai-cards';

        for (const card of cards.slice(0, 5)) {
            const el = document.createElement('button');
            el.type = 'button';
            el.className = 'ai-card';
            el.setAttribute('aria-label', `${card.title || 'Anime'} haqida batafsil ma'lumot`);
            el.setAttribute('aria-haspopup', 'dialog');

            const poster = document.createElement('div');
            poster.className = 'ai-card-poster';

            const img = document.createElement('img');
            img.alt = card.title || 'Anime';
            img.loading = 'lazy';
            const cached = getCachedPoster(card);
            if (cached) {
                img.src = cached;
            } else {
                img.src = cardPosterUrl(card);
                img.onerror = () => {
                    const fallback = safeImageUrl(card.cover);
                    if (fallback && fallback !== img.src) img.src = fallback;
                    else img.src = '../Ai/Ai.png';
                };
                rememberPoster(card, img);
            }
            poster.appendChild(img);

            const info = document.createElement('div');
            info.className = 'ai-card-info';

            const title = document.createElement('div');
            title.className = 'ai-card-title';
            title.textContent = card.title || 'Anime';

            const badges = document.createElement('div');
            badges.className = 'ai-card-badges';
            const status = makeBadge(
                statusLabel(card.kind === 'anilist' ? card.status : card.type),
                'is-status',
            );
            const score = makeBadge(scoreText(card.score), 'is-score');
            const episodes = makeBadge(episodeText(card.episodes), 'is-ep');
            const format = makeBadge(formatLabel(card.format), 'is-type');
            [status, score, episodes, format].forEach((badge) => { if (badge) badges.appendChild(badge); });
            if (!badges.childElementCount) {
                const fallback = makeBadge(card.kind === 'local' ? 'ANIME UZ' : 'AniList', 'is-type');
                if (fallback) badges.appendChild(fallback);
            }

            info.append(title, badges);
            el.append(poster, info);
            el.addEventListener('click', () => openAnimeModal(card));
            wrap.appendChild(el);
        }
        return wrap;
    }

    // ——— To'liq ma'lumot oynasi ———
    function element(tag, className, text) {
        const el = document.createElement(tag);
        if (className) el.className = className;
        if (text !== undefined) el.textContent = text;
        return el;
    }

    function detailCacheKey(card) {
        return 'detail:' + card.kind + ':' + String(card.id);
    }

    async function fetchAnimeDetail(card) {
        const store = readCacheStore(LS_DETAIL_CACHE);
        const key = detailCacheKey(card);
        const hit = store.items[key];
        if (hit && hit.ts && Date.now() - hit.ts < DETAIL_CACHE_TTL && hit.data) return hit.data;

        const url = card.kind === 'local'
            ? `/api/animes/${encodeURIComponent(card.id)}`
            : `/api/anilist/detail?id=${encodeURIComponent(card.id)}`;
        const res = await fetch(url, { headers: authHeaders() });
        const data = await res.json();
        if (!data || !data.ok) throw new Error((data && data.error) || 'Ma\'lumot topilmadi');

        const payload = card.kind === 'local'
            ? { kind: 'local', anime: data.anime }
            : { kind: 'anilist', anime: data.result };

        store.items[key] = { ts: Date.now(), data: payload };
        pruneCache(store, MAX_CACHED_DETAILS);
        writeCacheStore(LS_DETAIL_CACHE, store);
        return payload;
    }

    function openAnimeModal(card) {
        const modal = $('animeModal');
        const content = $('animeModalContent');
        if (!modal || !content) return;
        state.modalCard = card;
        state.lastFocused = document.activeElement;

        content.replaceChildren();
        const loading = element('div', 'anime-detail-loading');
        loading.append(element('span', 'spinner'), element('p', '', 'AniList ma\'lumotlari yuklanmoqda...'));
        content.appendChild(loading);

        modal.hidden = false;
        document.body.classList.add('modal-open');
        $('animeModalClose').focus();

        fetchAnimeDetail(card)
            .then((payload) => {
                if (state.modalCard !== card) return;
                renderAnimeDetail(content, payload, card);
            })
            .catch((err) => {
                if (state.modalCard !== card) return;
                content.replaceChildren();
                const box = element('div', 'anime-detail-error');
                box.append(
                    element('p', '', err && err.message ? err.message : 'Ma\'lumotni yuklab bo\'lmadi.'),
                    element('p', '', 'Internet aloqasini tekshirib, kartani qayta bosing.'),
                );
                content.appendChild(box);
            });
    }

    function closeAnimeModal() {
        const modal = $('animeModal');
        if (!modal || modal.hidden) return;
        modal.hidden = true;
        state.modalCard = null;
        document.body.classList.remove('modal-open');
        const content = $('animeModalContent');
        if (content) content.replaceChildren();
        if (state.lastFocused && typeof state.lastFocused.focus === 'function') {
            state.lastFocused.focus();
        }
    }

    function modalPoster(payload, card) {
        const anime = payload.anime || {};
        const wrap = element('div', 'anime-detail-poster');
        const img = document.createElement('img');
        img.alt = anime.nom || anime.title || card.title || 'Anime';
        const cached = getCachedPoster(card);
        if (cached) {
            img.src = cached;
        } else {
            const raw = payload.kind === 'anilist'
                ? (anime.poster_url || `/api/ai/poster/${card.id}`)
                : (anime.rams_url || `/poster/${card.id}`);
            img.src = safeImageUrl(raw) || cardPosterUrl(card);
            rememberPoster({ kind: payload.kind, id: card.id }, img);
        }
        wrap.appendChild(img);
        return wrap;
    }

    function appendBadges(container, specs) {
        const wrap = element('div', 'anime-detail-badges');
        for (const spec of specs) {
            const badge = makeBadge(spec.text, spec.cls || '');
            if (badge) wrap.appendChild(badge);
        }
        if (wrap.childElementCount) container.appendChild(wrap);
    }

    function appendChips(section, title, values) {
        if (!values || !values.length) return;
        const block = element('div', 'anime-detail-section');
        block.appendChild(element('h3', '', title));
        const list = element('div', 'anime-chip-list');
        values.forEach((value) => {
            if (value) list.appendChild(element('span', 'anime-chip', value));
        });
        if (list.childElementCount) block.appendChild(list);
        if (block.childElementCount > 1) section.appendChild(block);
    }

    function renderAnimeDetail(content, payload, card) {
        content.replaceChildren();
        const anime = payload.anime || {};
        const isAniList = payload.kind === 'anilist';

        const hero = element('div', 'anime-detail-hero');
        const bannerUrl = safeImageUrl(anime.banner);
        if (bannerUrl) {
            const banner = document.createElement('img');
            banner.className = 'anime-detail-banner';
            banner.src = bannerUrl;
            banner.alt = '';
            hero.appendChild(banner);
        }

        const head = element('div', 'anime-detail-head');
        head.appendChild(modalPoster(payload, card));

        const headings = element('div', 'anime-detail-headings');
        const title = element('h2', 'anime-detail-title', anime.nom || anime.title || card.title || 'Anime');
        title.id = 'animeModalTitle';
        headings.appendChild(title);
        const mainTitle = String(anime.nom || anime.title || card.title || '').trim().toLowerCase();
        const subTitle = [...new Set(
            (isAniList ? [anime.title_romaji, anime.title_native] : [anime.nom_en, anime.fandub])
                .filter((value) => value && String(value).trim().toLowerCase() !== mainTitle),
        )].join(' • ');
        if (subTitle) headings.appendChild(element('p', 'anime-detail-sub', subTitle));
        head.appendChild(headings);
        hero.appendChild(head);
        content.appendChild(hero);

        const body = element('div', 'anime-detail-body');
        appendBadges(body, [
            { text: statusLabel(anime.status || (isAniList ? '' : anime.aniType)), cls: 'is-status' },
            { text: scoreText(anime.score), cls: 'is-score' },
            { text: episodeText(anime.episodes || anime.qismi || anime.ep_count), cls: 'is-ep' },
            { text: formatLabel(anime.format), cls: 'is-type' },
            { text: anime.year || anime.yili ? `${anime.year || anime.yili}-yil` : '', cls: 'is-type' },
            { text: anime.season ? String(anime.season).toLowerCase() : '', cls: 'is-type' },
        ]);

        const description = anime.description || anime.tavsif || '';
        if (description) body.appendChild(element('p', 'anime-detail-description', description));

        if (isAniList) {
            appendChips(body, 'Janrlar', anime.genres || []);
            appendChips(body, 'Studiyalar', anime.studios || []);
            appendChips(body, 'Teglar', (anime.tags || []).map((tag) => tag.name));

            if (anime.relations && anime.relations.length) {
                const section = element('div', 'anime-detail-section');
                section.appendChild(element('h3', '', 'Bog\'liq animelar'));
                const grid = element('div', 'anime-relations');
                anime.relations.slice(0, 8).forEach((rel) => {
                    const row = element('div', 'anime-relation');
                    const relCover = safeImageUrl(rel.cover);
                    if (relCover) {
                        const img = document.createElement('img');
                        img.src = relCover;
                        img.alt = rel.title || '';
                        img.loading = 'lazy';
                        row.appendChild(img);
                    }
                    const info = element('div');
                    info.appendChild(element('strong', '', rel.title || 'Anime'));
                    info.appendChild(element('span', '', formatLabel(rel.format) || rel.relation_type || ''));
                    row.appendChild(info);
                    grid.appendChild(row);
                });
                section.appendChild(grid);
                body.appendChild(section);
            }

            if (anime.characters && anime.characters.length) {
                const section = element('div', 'anime-detail-section');
                section.appendChild(element('h3', '', 'Qahramonlar'));
                const grid = element('div', 'anime-cast');
                anime.characters.slice(0, 8).forEach((person) => {
                    const row = element('div', 'anime-cast-item');
                    const photo = safeImageUrl(person.image);
                    if (photo) {
                        const img = document.createElement('img');
                        img.src = photo;
                        img.alt = person.name || '';
                        img.loading = 'lazy';
                        row.appendChild(img);
                    }
                    const info = element('div');
                    info.appendChild(element('strong', '', person.name || 'Nomsiz'));
                    info.appendChild(element('span', '', person.role === 'MAIN' ? 'Asosiy' : 'Ikkinchi darajali'));
                    row.appendChild(info);
                    grid.appendChild(row);
                });
                section.appendChild(grid);
                body.appendChild(section);
            }

            const links = (anime.links || [])
                .map((link) => ({ url: safeExternalUrl(link.url), label: link.site || 'Havola' }))
                .filter((link) => link.url);
            const site = safeExternalUrl(anime.site_url);
            if (site) links.unshift({ url: site, label: 'AniList sahifasi' });

            if (links.length) {
                const section = element('div', 'anime-detail-section');
                section.appendChild(element('h3', '', 'Havolalar'));
                const list = element('div', 'anime-detail-links');
                links.slice(0, 8).forEach((link) => {
                    const a = element('a', 'anime-detail-link', link.label);
                    a.href = link.url;
                    a.target = '_blank';
                    a.rel = 'noopener noreferrer';
                    list.appendChild(a);
                });
                section.appendChild(list);
                body.appendChild(section);
            }
        } else {
            appendChips(body, 'Janrlar', String(anime.janri || '').split(/[,/]/).map((s) => s.trim()).filter(Boolean));
            appendChips(body, 'Ma\'lumotlar', [
                anime.davlat ? `Davlat: ${anime.davlat}` : '',
                anime.yosh_toifa ? `Yosh: ${anime.yosh_toifa}` : '',
                anime.qismi ? `Qismlar: ${anime.qismi}` : '',
            ]);
        }

        content.appendChild(body);
    }
    function showTyping() {
        removeTyping();
        const row = document.createElement('div');
        row.className = 'msg-row bot';
        row.id = 'typingIndicator';
        row.innerHTML = `
            <div class="msg-avatar"><img src="../Ai/Ai.png" alt="AnimeUz Ai"></div>
            <div class="msg-content">
                <div class="msg-bubble"><div class="typing-dots"><span></span><span></span><span></span></div></div>
            </div>`;
        chatMessages.appendChild(row);
        welcome.classList.add('is-hidden');
        scrollToBottom();
    }

    function removeTyping() {
        const el = $('typingIndicator');
        if (el) el.remove();
    }

    // ── Xabar amallari ──
    function addMessage(role, text) {
        state.messages.push({ role, text, ts: Date.now() });
        ensureSession();
        saveMessages();
        touchSession();
        renderAll();
        return state.messages.length - 1;
    }

    function updateMessageFeedback(index, value) {
        const msg = state.messages[index];
        if (!msg) return;
        msg.feedback = msg.feedback === value ? null : value;
        saveMessages();
        renderAll();
    }

    function copyText(text) {
        const clean = plainText(text);
        if (navigator.clipboard && window.isSecureContext) {
            navigator.clipboard.writeText(clean).then(
                () => toast('Nusxa olindi.', 'success'),
                () => toast('Nusxa olish imkoni bo\'lmadi.', 'error'),
            );
            return;
        }
        const area = document.createElement('textarea');
        area.value = clean;
        area.style.position = 'fixed';
        area.style.opacity = '0';
        document.body.appendChild(area);
        area.select();
        try {
            document.execCommand('copy');
            toast('Nusxa olindi.', 'success');
        } catch {
            toast('Nusxa olish imkoni bo\'lmadi.', 'error');
        }
        area.remove();
    }

    function downloadMessage(msg, index) {
        const blob = new Blob([plainText(msg.text)], { type: 'text/plain;charset=utf-8' });
        const url = URL.createObjectURL(blob);
        const a = document.createElement('a');
        const session = sessionById(state.activeId);
        a.href = url;
        a.download = `animeuz-ai-${(session && session.title ? session.title : 'suhbat').slice(0, 30)}-${index + 1}.txt`;
        document.body.appendChild(a);
        a.click();
        a.remove();
        URL.revokeObjectURL(url);
        toast('Fayl yuklab olindi.', 'success');
    }

    function speakMessage(text, btn) {
        if (!('speechSynthesis' in window)) {
            toast('Brauzeringiz ovozli o\'qishni qo\'llamaydi.', 'error');
            return;
        }
        window.speechSynthesis.cancel();
        if (state.speakingBtn === btn) {
            btn.classList.remove('is-on');
            state.speakingBtn = null;
            return;
        }
        if (state.speakingBtn) state.speakingBtn.classList.remove('is-on');

        const utterance = new SpeechSynthesisUtterance(plainText(text));
        utterance.lang = 'uz-UZ';
        utterance.rate = 1;
        state.speakingBtn = btn;
        btn.classList.add('is-on');
        utterance.onend = utterance.onerror = () => {
            btn.classList.remove('is-on');
            if (state.speakingBtn === btn) state.speakingBtn = null;
        };
        window.speechSynthesis.speak(utterance);
    }

    function regenerate() {
        if (state.waiting) return;
        const lastUserIndex = findLastUserIndex();
        if (lastUserIndex < 0) {
            toast('Qayta yaratish uchun savol topilmadi.');
            return;
        }
        // Oxirgi bot javobini olib tashlaymiz.
        while (state.messages.length && state.messages[state.messages.length - 1].role === 'bot') {
            state.messages.pop();
        }
        saveMessages();
        renderAll();
        requestReply(state.messages[lastUserIndex].text);
    }

    function findLastUserIndex() {
        for (let i = state.messages.length - 1; i >= 0; i -= 1) {
            if (state.messages[i].role === 'user') return i;
        }
        return -1;
    }

    chatMessages.addEventListener('click', (event) => {
        const btn = event.target.closest('.msg-actions button');
        if (!btn) return;
        const index = Number(btn.dataset.index);
        const msg = state.messages[index];
        if (!msg) return;

        switch (btn.dataset.action) {
            case 'copy':
                copyText(msg.text);
                break;
            case 'like':
            case 'dislike':
                updateMessageFeedback(index, btn.dataset.action);
                break;
            case 'speak':
                speakMessage(msg.text, btn);
                break;
            case 'download':
                downloadMessage(msg, index);
                break;
            case 'regen':
                regenerate();
                break;
            default:
                break;
        }
    });

    // ── Kvota ──
    function formatReset(iso) {
        if (!iso) return '';
        const date = new Date(iso);
        if (Number.isNaN(date.getTime())) return '';
        return date.toLocaleString('uz-UZ', {
            day: '2-digit', month: '2-digit', hour: '2-digit', minute: '2-digit',
        });
    }

    function updateQuotaUI(quota) {
        if (!quota) return;
        if (typeof quota.limit === 'number') state.quota.limit = quota.limit;
        if (typeof quota.used === 'number') state.quota.used = quota.used;
        if (typeof quota.remaining === 'number') state.quota.remaining = quota.remaining;
        if (quota.reset_at) state.quota.reset_at = quota.reset_at;

        const { remaining, limit, reset_at } = state.quota;
        quotaText.textContent = `${remaining}/${limit}`;
        quotaBadge.classList.toggle('is-low', remaining > 0 && remaining <= 2);
        quotaBadge.classList.toggle('is-empty', remaining <= 0);

        if (remaining <= 0) {
            composer.classList.add('is-locked');
            quotaNote.hidden = false;
            quotaNote.textContent = reset_at
                ? `Kunlik limit tugadi. Yangilanish: ${formatReset(reset_at)} (Toshkent).`
                : 'Kunlik limit tugadi. Ertaga yangilanadi.';
        } else {
            composer.classList.remove('is-locked');
            quotaNote.hidden = true;
            quotaNote.textContent = '';
        }
        updateComposerState();
    }

    async function loadQuota() {
        try {
            const res = await fetch(`/api/ai/quota?device_id=${encodeURIComponent(DEVICE_ID)}`, {
                headers: authHeaders(),
            });
            const data = await res.json();
            if (data && data.ok) updateQuotaUI(data);
        } catch { /* quota keyin yangilanadi */ }
    }

    async function loadRemoteSessions() {
        try {
            const res = await fetch(`/api/ai/sessions?device_id=${encodeURIComponent(DEVICE_ID)}`, {
                headers: authHeaders(),
            });
            const data = await res.json();
            if (!data || !data.ok || !Array.isArray(data.sessions)) return;

            let changed = false;
            for (const remote of data.sessions) {
                if (!remote || !/^[A-Za-z0-9_-]{6,64}$/.test(remote.session_id || '')) continue;
                if (sessionById(remote.session_id)) continue;
                if (loadMessages(remote.session_id).length) continue;

                state.sessions.push({
                    id: remote.session_id,
                    title: remote.title || 'Suhbat',
                    created_at: remote.created_at || remote.updated_at || new Date().toISOString(),
                    updated_at: remote.updated_at || new Date().toISOString(),
                    count: Number(remote.message_count) || 0,
                    remote: true,
                });
                changed = true;
            }

            if (changed) {
                state.sessions.sort((a, b) => String(b.updated_at).localeCompare(String(a.updated_at)));
                saveSessions();
                renderHistory();
            }
        } catch { /* server metadata mavjud emas */ }
    }

    function updateComposerState() {
        const disabled = state.waiting || state.quota.remaining <= 0;
        sendBtn.disabled = disabled;
        input.disabled = state.quota.remaining <= 0 && !state.waiting;
        adminInput.disabled = state.waiting;
    }

    function setAdminMode(enabled) {
        state.adminPassword = !!enabled;
        input.hidden = state.adminPassword;
        adminInput.hidden = !state.adminPassword;
        if (state.adminPassword) {
            adminInput.value = '';
            adminInput.focus();
        } else {
            input.focus();
        }
    }

    // ── So'rov yuborish ──
    function buildPrompt(text) {
        const prefixes = [];
        if (state.options.reasoning) prefixes.push('Avval qisqacha fikr yuritib, keyin batafsil javob ber.');
        if (state.options.research) prefixes.push('Mavzuni chuqur tahlil qil, ishonchli ma\'lumotlarga asoslanib batafsil yoz.');
        const prefix = prefixes.length ? prefixes.join(' ') + '\n\n' : '';
        return (prefix + text).slice(0, MAX_INPUT);
    }

    async function submit(text) {
        const source = state.adminPassword ? adminInput.value : input.value;
        const raw = String(text ?? source).trim();
        if (!raw || state.waiting) return;
        if (state.quota.remaining <= 0 && !state.adminPassword) {
            toast(`Kunlik ${state.quota.limit} ta urinish tugadi. Ertaga yangilanadi.`, 'error');
            return;
        }

        const display = state.adminPassword ? '••••••' : raw;
        const apiMessage = state.adminPassword ? raw : buildPrompt(raw);

        addMessage('user', display);
        if (state.adminPassword) {
            adminInput.value = '';
            adminInput.focus();
        } else {
            input.value = '';
            autosize();
            input.focus();
        }

        await requestReply(apiMessage, display);
    }

    async function requestReply(apiMessage, displayMessage = '') {
        if (state.waiting) return;
        state.waiting = true;
        updateComposerState();
        showTyping();

        try {
            const res = await fetch('/api/ai/chat', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json', ...authHeaders() },
                body: JSON.stringify({
                    message: apiMessage,
                    admin_password_mode: state.adminPassword,
                    device_id: DEVICE_ID,
                }),
            });

            let data = {};
            try {
                data = await res.json();
            } catch { /* bo'sh javob */ }

            if (typeof data.remaining === 'number') {
                updateQuotaUI({
                    limit: data.limit,
                    used: data.used,
                    remaining: data.remaining,
                    reset_at: data.reset_at,
                });
            }

            if (!!data.admin_password_required !== state.adminPassword) {
                setAdminMode(!!data.admin_password_required);
            }

            if (res.ok && data.ok) {
                addMessage('bot', data.reply || 'Javob bo\'sh keldi.');
                if (data.admin_ok) {
                    if (data.admin_token) localStorage.setItem('az_admin_token', data.admin_token);
                    setTimeout(() => { window.location.href = data.admin_url || '/admin'; }, 500);
                }
            } else {
                const errorText = data.error || 'Serverga ulanib bo\'lmadi.';
                addMessage('bot', `⚠️ ${errorText}`);
                if (res.status === 429) {
                    toast('Kunlik limit tugadi.', 'error');
                    loadQuota();
                }
            }
        } catch (err) {
            console.error('AI so\'rov xatosi:', err);
            addMessage('bot', '⚠️ Tarmoq xatosi. Iltimos, keyinroq qayta urinib ko\'ring.');
        } finally {
            removeTyping();
            state.waiting = false;
            updateComposerState();
            scrollToBottom();
        }
    }

    // ── Composer ──
    function autosize() {
        input.style.height = 'auto';
        input.style.height = Math.min(input.scrollHeight, 168) + 'px';
    }

    function setOption(name, btn) {
        state.options[name] = !state.options[name];
        btn.setAttribute('aria-pressed', String(state.options[name]));
    }

    function appendToInput(text) {
        input.value = input.value ? input.value.replace(/\s+$/, '') + ' ' + text : text;
        if (input.value.length > MAX_INPUT) input.value = input.value.slice(0, MAX_INPUT);
        autosize();
        input.focus();
    }

    function initSpeech() {
        const SpeechRecognition = window.SpeechRecognition || window.webkitSpeechRecognition;
        const micBtn = $('micBtn');
        if (!SpeechRecognition) {
            micBtn.addEventListener('click', () => toast('Brauzeringiz ovozli kiritishni qo\'llamaydi.', 'error'));
            return;
        }

        const recognition = new SpeechRecognition();
        recognition.lang = 'uz-UZ';
        recognition.interimResults = false;
        recognition.continuous = false;
        recognition.maxAlternatives = 1;

        let listening = false;

        recognition.onresult = (event) => {
            const transcript = event.results?.[0]?.[0]?.transcript || '';
            if (transcript) appendToInput(transcript);
        };
        recognition.onerror = (event) => {
            listening = false;
            micBtn.classList.remove('is-recording');
            micBtn.setAttribute('aria-pressed', 'false');
            if (event.error === 'not-allowed') toast('Mikrofonga ruxsat berilmagan.', 'error');
            else if (event.error !== 'aborted') toast('Ovozni eshitib bo\'lmadi. Qayta urinib ko\'ring.', 'error');
        };
        recognition.onend = () => {
            listening = false;
            micBtn.classList.remove('is-recording');
            micBtn.setAttribute('aria-pressed', 'false');
        };

        micBtn.addEventListener('click', () => {
            if (state.quota.remaining <= 0) {
                toast('Kunlik limit tugadi.', 'error');
                return;
            }
            if (listening) {
                recognition.stop();
                return;
            }
            try {
                recognition.start();
                listening = true;
                micBtn.classList.add('is-recording');
                micBtn.setAttribute('aria-pressed', 'true');
                toast('Gapiring...');
            } catch {
                toast('Mikrofonni ishga tushirib bo\'lmadi.', 'error');
            }
        });
    }

    // ── UI hodisalari ──
    composer.addEventListener('submit', (event) => {
        event.preventDefault();
        submit();
    });

    input.addEventListener('input', autosize);
    input.addEventListener('keydown', (event) => {
        if (event.key === 'Enter' && !event.shiftKey && !event.isComposing) {
            event.preventDefault();
            submit();
        }
    });
    adminInput.addEventListener('keydown', (event) => {
        if (event.key === 'Enter' && !event.isComposing) {
            event.preventDefault();
            submit();
        }
    });

    $('reasoningBtn').addEventListener('click', (event) => setOption('reasoning', event.currentTarget));
    $('researchBtn').addEventListener('click', (event) => setOption('research', event.currentTarget));

    $('attachBtn').addEventListener('click', () => $('fileInput').click());
    $('fileInput').addEventListener('change', (event) => {
        const file = event.target.files?.[0];
        event.target.value = '';
        if (!file) return;
        if (file.size > 200 * 1024) {
            toast('Fayl juda katta (maks. 200 KB).', 'error');
            return;
        }
        const reader = new FileReader();
        reader.onload = () => {
            const content = String(reader.result || '').slice(0, 20000);
            appendToInput(`\n\n[Fayl: ${file.name}]\n${content}\n`);
            toast('Fayl matni qo\'shildi.', 'success');
        };
        reader.onerror = () => toast('Faylni o\'qib bo\'lmadi.', 'error');
        reader.readAsText(file);
    });

    $('linkBtn').addEventListener('click', () => {
        const url = window.prompt('Havolani kiriting (https://...):');
        if (!url) return;
        try {
            const parsed = new URL(url.trim());
            if (!['http:', 'https:'].includes(parsed.protocol)) throw new Error('bad');
            appendToInput(parsed.href);
        } catch {
            toast('Havola noto\'g\'ri.', 'error');
        }
    });

    document.querySelectorAll('#quickPrompts button').forEach((btn) => {
        btn.addEventListener('click', () => {
            const prompt = btn.dataset.prompt || btn.textContent;
            submit(prompt);
        });
    });

    // Theme
    $('themeSunBtn').addEventListener('click', () => applyTheme('light'));
    $('themeMoonBtn').addEventListener('click', () => applyTheme('dark'));
    $('railThemeBtn').addEventListener('click', () => applyTheme(state.theme === 'dark' ? 'light' : 'dark'));

    // History
    const isMobile = () => window.matchMedia('(max-width: 1040px)').matches;
    function openHistoryDrawer() {
        if (!isMobile()) {
            historyList.scrollTop = 0;
            return;
        }
        historyPanel.classList.add('is-open');
        historyBackdrop.hidden = false;
        historyBackdrop.classList.add('is-open');
    }
    function closeHistoryDrawer() {
        historyPanel.classList.remove('is-open');
        historyBackdrop.classList.remove('is-open');
        historyBackdrop.hidden = true;
    }

    $('historyToggleBtn').addEventListener('click', openHistoryDrawer);
    $('railHistoryBtn').addEventListener('click', openHistoryDrawer);
    $('historyClose').addEventListener('click', closeHistoryDrawer);
    historyBackdrop.addEventListener('click', closeHistoryDrawer);

    $('newChatBtn').addEventListener('click', newChat);
    $('railNewChatBtn').addEventListener('click', newChat);

    historyList.addEventListener('click', (event) => {
        const del = event.target.closest('.history-item-del');
        if (del) {
            const item = del.closest('.history-item');
            if (item) deleteSession(item.dataset.id);
            return;
        }
        const item = event.target.closest('.history-item');
        if (item) switchSession(item.dataset.id);
    });

    historyList.addEventListener('keydown', (event) => {
        if (event.target.closest('.history-item-del')) return;
        const item = event.target.closest('.history-item');
        if (!item) return;
        if (event.key === 'Enter' || event.key === ' ') {
            event.preventDefault();
            switchSession(item.dataset.id);
        }
    });

    // Chat menyusi
    $('chatMenuBtn').addEventListener('click', (event) => {
        event.stopPropagation();
        const isHidden = chatMenu.hidden;
        chatMenu.hidden = !isHidden;
        $('chatMenuBtn').setAttribute('aria-expanded', String(isHidden));
    });

    chatMenu.addEventListener('click', (event) => {
        const btn = event.target.closest('button');
        if (!btn) return;
        chatMenu.hidden = true;
        $('chatMenuBtn').setAttribute('aria-expanded', 'false');
        if (btn.dataset.action === 'clear') clearCurrentChat();
        if (btn.dataset.action === 'delete-all') deleteAllSessions();
    });

    document.addEventListener('click', (event) => {
        if (!event.target.closest('.chat-menu-wrap')) {
            chatMenu.hidden = true;
            $('chatMenuBtn').setAttribute('aria-expanded', 'false');
        }
    });

    $('notifyBtn').addEventListener('click', () => toast('Hozircha yangi bildirishnomalar yo\'q.'));

    const animeModal = $('animeModal');
    if (animeModal) {
        animeModal.addEventListener('click', (event) => {
            if (event.target.closest('[data-modal-close]')) closeAnimeModal();
        });
        $('animeModalClose').addEventListener('click', closeAnimeModal);
    }
    document.addEventListener('keydown', (event) => {
        if (event.key === 'Escape' && animeModal && !animeModal.hidden) closeAnimeModal();
    });

    $('userAvatar').addEventListener('click', () => {
        const user = loadJSON('az_user', null);
        if (user) {
            window.location.href = '/admin';
        } else {
            toast('Profil uchun saytga kiring.');
        }
    });

    $('logoutBtn').addEventListener('click', async () => {
        try {
            await fetch('/api/auth/logout', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json', ...authHeaders() },
            });
        } catch { /* ignore */ }
        localStorage.removeItem('az_token');
        localStorage.removeItem('az_user');
        localStorage.removeItem('az_admin_token');
        toast('Hisobdan chiqdingiz.');
        setTimeout(() => window.location.reload(), 500);
    });

    window.addEventListener('resize', () => {
        if (!isMobile()) closeHistoryDrawer();
    });

    // ── Boshlash ──
    function init() {
        initTheme();
        initUser();
        loadSessions();

        const savedActive = localStorage.getItem(LS_ACTIVE);
        if (savedActive && sessionById(savedActive)) {
            state.activeId = savedActive;
            state.messages = loadMessages(savedActive);
        } else if (state.sessions.length) {
            state.activeId = state.sessions[0].id;
            state.messages = loadMessages(state.activeId);
            localStorage.setItem(LS_ACTIVE, state.activeId);
        } else {
            state.activeId = null;
            state.messages = [];
        }

        renderAll();
        renderHistory();
        loadQuota();
        loadRemoteSessions();
        loadCacheVersion();
        scheduleCacheCheck();
        autosize();
        initSpeech();
        input.focus();
    }

    init();
})();
