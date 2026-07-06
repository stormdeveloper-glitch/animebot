// ── THREE.JS BG ──
(function () {
    if (typeof THREE === 'undefined') { console.warn('THREE.js not loaded – skipping 3D background.'); return; }
    const c = document.getElementById('bg3d');
    const r = new THREE.WebGLRenderer({ canvas: c, alpha: true, antialias: true });
    r.setPixelRatio(Math.min(devicePixelRatio, 1.5)); r.setSize(innerWidth, innerHeight);
    const s = new THREE.Scene(), cam = new THREE.PerspectiveCamera(65, innerWidth / innerHeight, .1, 1000);
    cam.position.z = 26;
    const mk = (g, col, o) => new THREE.Mesh(g, new THREE.MeshBasicMaterial({ color: col, wireframe: true, transparent: true, opacity: o }));
    const i1 = mk(new THREE.IcosahedronGeometry(9, 1), 0x00d4ff, .08), i2 = mk(new THREE.IcosahedronGeometry(5.5, 0), 0x8b5cf6, .09);
    s.add(i1, i2);
    const geos = [new THREE.TetrahedronGeometry(.8), new THREE.OctahedronGeometry(.7), new THREE.BoxGeometry(1, 1, 1), new THREE.IcosahedronGeometry(.6, 0)];
    const cols = [0x00d4ff, 0x8b5cf6, 0xf0abfc, 0x10ffa0];
    Array.from({ length: 22 }, (_, i) => {
        const m = mk(geos[i % 4], cols[i % 4], .06 + Math.random() * .09);
        const rr = 14 + Math.random() * 20, t = Math.random() * Math.PI * 2, p = Math.acos(2 * Math.random() - 1);
        m.position.set(rr * Math.sin(p) * Math.cos(t), rr * Math.sin(p) * Math.sin(t), rr * Math.cos(p) - 10);
        m.userData = { sx: (Math.random() - .5) * .009, sy: (Math.random() - .5) * .009 }; s.add(m); return m;
    });
    let mx = 0, my = 0;
    document.addEventListener('mousemove', e => { mx = (e.clientX / innerWidth - .5) * .016; my = (e.clientY / innerHeight - .5) * .016; });
    const smalls = [...s.children].slice(2);
    (function a() {
        requestAnimationFrame(a);
        i1.rotation.x += .0017 + mx * .35; i1.rotation.y += .0026 + my * .35;
        i2.rotation.x -= .0022; i2.rotation.y -= .0016;
        smalls.forEach(m => { m.rotation.x += m.userData.sx; m.rotation.y += m.userData.sy; });
        r.render(s, cam);
    })();
    window.addEventListener('resize', () => { cam.aspect = innerWidth / innerHeight; cam.updateProjectionMatrix(); r.setSize(innerWidth, innerHeight); });
})();

// ── SETTINGS ──
const LS = k => localStorage.getItem('az_' + k);
const LSS = (k, v) => localStorage.setItem('az_' + k, v);
let S = { theme: LS('theme') || 'glass', bg: LS('bg') !== 'off', spin: +LS('spin') || 9, card: +LS('card') || 196, def: LS('def') || 'all', lang: LS('lang') || 'uz' };
document.documentElement.setAttribute('data-theme', S.theme);
updateBrowserThemeColor(S.theme);
document.documentElement.style.setProperty('--sd', S.spin === 0 ? '99999s' : S.spin + 's');
document.documentElement.style.setProperty('--cw', S.card + 'px');
window.addEventListener('DOMContentLoaded', syncUI);
let _mirrorStream = null;

function updateBrowserThemeColor(theme) {
    const color = '#6b3f24';
    document.querySelector('meta[name="theme-color"]')?.setAttribute('content', color);
    document.querySelector('meta[name="msapplication-TileColor"]')?.setAttribute('content', color);
}
function syncUI() {
    ['glass', 'futuristic', 'cyber3d', 'mirror'].forEach(t => document.getElementById('th-' + t)?.classList.toggle('on', S.theme === t));
    const bg = document.getElementById('togBg'); if (bg) bg.checked = S.bg;
    [5, 9, 16, 0].forEach(v => document.getElementById('sp-' + v)?.classList.toggle('on', S.spin === v));
    [150, 196, 260].forEach(v => document.getElementById('cw-' + v)?.classList.toggle('on', S.card === v));
    ['all', 'ongoing', 'top', 'new'].forEach(v => document.getElementById('df-' + v)?.classList.toggle('on', S.def === v));
    ['uz', 'ru', 'en'].forEach(v => document.getElementById('lg-' + v)?.classList.toggle('on', S.lang === v));
    updateMirrorHint();
}
function syncSettingsUI() { syncUI(); }
function setTheme(t, b) {
    S.theme = t; LSS('theme', t); document.documentElement.setAttribute('data-theme', t); hiPill('th-', ['glass', 'futuristic', 'cyber3d', 'mirror'], t);
    updateBrowserThemeColor(t);
    if (t !== 'mirror') stopMirrorCamera(true);
    updateMirrorHint();
}
function setBg(on) { S.bg = on; LSS('bg', on ? 'on' : 'off'); document.getElementById('bg3d').style.opacity = on ? '' : '0'; }
function setSpin(v, b) { S.spin = v; LSS('spin', v); document.documentElement.style.setProperty('--sd', v === 0 ? '99999s' : v + 's'); hiPill('sp-', [5, 9, 16, 0], v); }
function setCard(v, b) { S.card = v; LSS('card', v); document.documentElement.style.setProperty('--cw', v + 'px'); hiPill('cw-', [150, 196, 260], v); }
function setDef(v, b) { S.def = v; LSS('def', v); hiPill('df-', ['all', 'ongoing', 'top', 'new'], v); }
function setLang(v, b) { S.lang = v; LSS('lang', v); hiPill('lg-', ['uz', 'ru', 'en'], v); }
function hiPill(prefix, vals, active) { vals.forEach(v => { const el = document.getElementById(prefix + v); if (el) el.classList.toggle('on', v === active); }); }

function updateMirrorHint() {
    const note = document.getElementById('mirrorNote');
    const ph = document.getElementById('mirrorPlaceholder');
    if (!note || !ph) return;
    if (S.theme === 'mirror') {
        if (_mirrorStream) {
            note.innerHTML = "<b>Mirror faol:</b> xohlagan payt kamerani to'xtatishingiz mumkin.";
            ph.style.display = 'none';
        } else {
            note.innerHTML = "<b>Xotirjam bo'ling:</b> ruxsat bersangiz ham video faqat shu oynada ko'rinadi, saqlanmaydi va serverga yuborilmaydi.";
            ph.style.display = 'flex';
            ph.textContent = "Mirror tema yoqildi. Tayyor bo'lsangiz, pastdagi tugma orqali old kamerani yoqing.";
        }
    } else {
        note.innerHTML = "<b>Mirror rejimi:</b> avval temani Mirror ga o'tkazing, keyin kamerani yoqsangiz bo'ladi.";
        ph.style.display = 'flex';
        ph.textContent = "Old kamerani ishga tushirishdan oldin Mirror temani tanlang.";
    }
}

async function startMirrorCamera() {
    if (S.theme !== 'mirror') {
        alert("Avval temani Mirror ga o'tkazing.");
        return;
    }
    if (!navigator.mediaDevices || !navigator.mediaDevices.getUserMedia) {
        alert("Bu qurilmada kamera API qo'llab-quvvatlanmaydi.");
        return;
    }
    if (location.protocol !== 'https:' && location.hostname !== 'localhost') {
        alert("Kamera uchun HTTPS kerak (yoki localhost).");
        return;
    }
    const cam = document.getElementById('mirrorCam');
    const ph = document.getElementById('mirrorPlaceholder');
    const st = document.getElementById('mirrorStartBtn');
    const sp = document.getElementById('mirrorStopBtn');
    if (!cam || !ph || !st || !sp) return;

    st.disabled = true;
    st.textContent = "⏳ Kamera ulanmoqda...";
    try {
        const stream = await navigator.mediaDevices.getUserMedia({ video: { facingMode: 'user' }, audio: false });
        _mirrorStream = stream;
        // Ruxsat qaytarib olinganda (yoki kamera uzilganda) stream tugaydi
        const track = stream.getVideoTracks && stream.getVideoTracks()[0];
        if (track) {
            track.onended = () => {
                const ph = document.getElementById('mirrorPlaceholder');
                if (ph) {
                    ph.style.display = 'flex';
                    ph.textContent = "Kamera ruxsati bekor qilindi yoki qurilma uzildi.";
                }
                stopMirrorCamera(true);
                updateMirrorHint();
            };
        }
        cam.srcObject = stream;
        cam.style.display = 'block';
        ph.style.display = 'none';
        st.style.display = 'none';
        sp.style.display = 'inline-block';
        updateMirrorHint();
    } catch (e) {
        ph.style.display = 'flex';
        ph.textContent = "Ruxsat berilmadi yoki kamera topilmadi. Xohlasangiz yana urinib ko'ring.";
        st.disabled = false;
        st.textContent = "🔓 Kameraga ruxsat berish";
    }
}

function stopMirrorCamera(silent = false) {
    const cam = document.getElementById('mirrorCam');
    const ph = document.getElementById('mirrorPlaceholder');
    const st = document.getElementById('mirrorStartBtn');
    const sp = document.getElementById('mirrorStopBtn');
    if (_mirrorStream) {
        _mirrorStream.getTracks().forEach(t => t.stop());
        _mirrorStream = null;
    }
    if (cam) {
        cam.pause();
        cam.srcObject = null;
        cam.style.display = 'none';
    }
    if (sp) sp.style.display = 'none';
    if (st) {
        st.style.display = 'inline-block';
        st.disabled = false;
        st.textContent = "🔓 Kameraga ruxsat berish";
    }
    if (ph) {
        ph.style.display = 'flex';
        if (S.theme === 'mirror') {
            ph.textContent = "Kamera to'xtatildi. Qayta yoqish uchun tugmani bosing.";
        } else {
            ph.textContent = "Old kamerani ishga tushirishdan oldin Mirror temani tanlang.";
        }
    }
    if (!silent) updateMirrorHint();
}
window.addEventListener('beforeunload', () => stopMirrorCamera(true));

// ── SIDEBAR ──
let sOpen = LS('sb') !== 'closed';
const sEl = document.getElementById('sidebar');
const arEl = document.getElementById('sideArrow');
if (sOpen) { sEl.classList.add('open'); arEl.textContent = '❮'; }
function toggleSidebar() { sOpen = !sOpen; sEl.classList.toggle('open', sOpen); arEl.textContent = sOpen ? '❮' : '❯'; LSS('sb', sOpen ? 'open' : 'closed'); }

// ── PAGES ──
const PT = { animes: 'Animelar', admins: 'Adminlar', stats: 'Statistika', report: 'Shikoyat / Taklif', settings: 'Sozlamalar', game: '🃏 O\'yinlar', global: '🌐 Global Qidiruv', gallery: '🖼️ Gallery', profile: '👤 Profil' };
const PS = { animes: 'Barcha anime sarlavhalar', admins: 'Bot boshqaruvchilari', stats: 'Faoliyat ko\'rsatkichlari', report: 'Xabaringiz adminga yetkaziladi', settings: 'Interfeys sozlamalari', game: 'Google bilan kiring va o\'ynang', global: 'AniList orqali dunyo bo\'yicha qidiring', gallery: 'Poster ko\'rinishda barcha animelar', profile: 'Profil va saqlangan animelar' };
function showPage(name, btn) {
    document.querySelectorAll('.page').forEach(p => p.classList.remove('active'));
    document.querySelectorAll('.snav,.bnav-item').forEach(b => b.classList.remove('active'));
    document.getElementById('page-' + name).classList.add('active');
    document.querySelectorAll(`[onclick*="'${name}'"]`).forEach(b => b.classList.add('active'));
    const tt = document.getElementById('topTitle'); if (tt) tt.textContent = PT[name] || name;
    const ts = document.getElementById('topSub'); if (ts) ts.textContent = PS[name] || '';
    if (name === 'admins') renderAdmins();
    if (name === 'stats') renderStats();
    if (name === 'game') switchGameTab(_activeGameTab || 'card');
    if (name === 'settings') syncSettingsUI();
    if (name === 'global') _checkAnilistStatus();
    if (name === 'gallery') renderGallery();
    if (name === 'profile') renderProfile();
}

// ── ANIMES ──
const BOT = 'anime_uz_official_bot';
let allAnimes = [], curFilter = S.def, srch = '';

// loadAnimes — see cached version below

function applyFilter() {
    let list = [...allAnimes];
    if (srch) { const q = srch.toLowerCase(); list = list.filter(a => (a.nom || '').toLowerCase().includes(q)); }
    if (curFilter === 'ongoing') list = list.filter(a => (a.aniType || '').toLowerCase().includes('ongoing'));
    else if (curFilter === 'completed') list = list.filter(a => a.aniType && !a.aniType.toLowerCase().includes('ongoing'));
    else if (curFilter === 'top') list = [...list].sort((a, b) => (b.qidiruv || 0) - (a.qidiruv || 0));
    else if (curFilter === 'new') list = [...list].sort((a, b) => b.id - a.id);
    else if (curFilter === 'age0') { const AGES = ['0+']; list = list.filter(a => AGES.includes(a.yosh_toifa)); }
    else if (curFilter === 'age7') { const AGES = ['0+', '7+']; list = list.filter(a => AGES.includes(a.yosh_toifa)); }
    else if (curFilter === 'age13') { const AGES = ['0+', '7+', '13+']; list = list.filter(a => AGES.includes(a.yosh_toifa)); }
    else if (curFilter === 'age16') { const AGES = ['0+', '7+', '13+', '16+']; list = list.filter(a => AGES.includes(a.yosh_toifa)); }
    else if (curFilter === 'age18') list = list.filter(a => a.yosh_toifa === '18+');
    const rc = document.getElementById('resultCount'); if (rc) rc.textContent = list.length;
    renderGrid(list);
}

// HUD card back HTML generator
function _hudCardBack(a, idx) {
    const og = (a.aniType || '').toLowerCase().includes('ongoing');
    const delay = (idx * 0.15) % 2; // stagger per card, max 2s
    // Pips: 8 total — ongoing=8, completed=5, unknown=3
    const pipOn = og ? 8 : (a.aniType ? 5 : 3);
    const pips = Array.from({ length: 8 }, (_, i) => `<div class="hud-pip${i < pipOn ? ' on' : ''}"></div>`).join('');
    // Truncate at 24 chars (was 18 — too aggressive)
    const rawName = a.nom || 'Nomsiz';
    const shortName = rawName.length > 24 ? rawName.slice(0, 22) + '…' : rawName;
    // Dynamic typewriter steps matching actual name length
    const nameSteps = shortName.length;
    const views = a.qidiruv ? `👁 ${a.qidiruv}` : '—';
    const fandub = a.fandub || '\u2014';

    return `<div class="hud-cb" style="--hud-delay:${delay}s">
    <div class="hud-top-line"></div>
    <div class="hud-bot-line"></div>

    <div class="hud-tag">ANIME DATA · ID ${String(a.id).padStart(3, '0')}</div>

    <div style="display:flex;flex-direction:column;gap:1px">
      <div class="hud-name" style="animation-timing-function:steps(${nameSteps},end)">${shortName}</div>
      <div class="hud-div-wrap">
        <div class="hud-div-line"></div>
        <div class="hud-div-cap"></div>
      </div>
    </div>

    <div class="hud-rows">
      <div class="hud-row">
        <div class="hud-dot"></div>
        <div class="hud-key">Holat</div>
        <div class="hud-sep"></div>
        <div class="hud-val">${a.aniType || '—'}</div>
      </div>
      <div class="hud-row">
        <div class="hud-dot"></div>
        <div class="hud-key">Qismlar</div>
        <div class="hud-sep"></div>
        <div class="hud-val">${a.ep_count || 0} ta</div>
      </div>
      <div class="hud-row">
        <div class="hud-dot"></div>
        <div class="hud-key">Janr</div>
        <div class="hud-sep"></div>
        <div class="hud-val">${(a.janri || '—').split(',').slice(0, 2).join(',')}</div>
      </div>
      <div class="hud-row">
        <div class="hud-dot"></div>
        <div class="hud-key">Yil</div>
        <div class="hud-sep"></div>
        <div class="hud-val">${a.yili || '—'}</div>
      </div>
      <div class="hud-row">
        <div class="hud-dot"></div>
        <div class="hud-key">Ovoz</div>
        <div class="hud-sep"></div>
        <div class="hud-val">${fandub}</div>
      </div>
      <div class="hud-row">
        <div class="hud-dot"></div>
        <div class="hud-key">Ko'rish</div>
        <div class="hud-sep"></div>
        <div class="hud-val">${views}</div>
      </div>
    </div>

    <div class="hud-pips">${pips}</div>
    <div class="hud-id">#${String(a.id).padStart(3, '0')}</div>
  </div>`;
}

function renderGrid(list) {
    const g = document.getElementById('animeGrid');
    if (!list.length) { g.innerHTML = `<div class="empty"><div class="empty-ico">😔</div><h3>Topilmadi</h3><p>"${srch}" bo'yicha natija yo'q</p></div>`; return; }
    g.innerHTML = list.map((a, idx) => {
        const likedCls = _isLiked(a.id) ? 'liked' : '';
        const savedCls = _isSaved(a.id) ? 'saved' : '';
        return `<div class="card-wrap" title="${a.nom}">
      <div class="card-flipper" onclick="openModal(${a.id},this)">
        <div class="cf">
          <img class="card-poster" src="${a.rams_url || ''}" loading="lazy" onerror="this.outerHTML='<div class=card-poster-ph>🎬</div>'">
        </div>
        <div class="cb">${_hudCardBack(a, idx)}</div>
      </div>
      <div class="card-action-bar">
        <button class="ca-btn ${likedCls}" onclick="event.stopPropagation();toggleLike(${a.id})" id="like-${a.id}">❤️ Yoqtir</button>
        <button class="ca-btn ${savedCls}" onclick="event.stopPropagation();toggleSave(${a.id})" id="save-${a.id}">💾 Saqlash</button>
      </div>
    </div>`;
    }).join('');
}

document.getElementById('searchInput').addEventListener('input', e => { srch = e.target.value.trim(); applyFilter(); });
document.querySelectorAll('.filter-btn').forEach(b => b.addEventListener('click', () => {
    document.querySelectorAll('.filter-btn').forEach(x => x.classList.remove('active'));
    b.classList.add('active'); curFilter = b.dataset.filter; applyFilter();
}));

// ── MODAL ──
let _portalBusy = false;
let _openingPosterFromRoute = false;
function _posterRouteId() {
    const m = location.pathname.match(/^\/poster\/(\d+)\/?$/);
    return m ? Number(m[1]) : 0;
}
function openModal(id, sourceEl, opts = {}) {
    const a = allAnimes.find(x => x.id === id); if (!a) return;
    if (_portalBusy) return;
    if (!opts.skipHistory && location.pathname !== `/poster/${id}`) {
        history.pushState({ poster: id }, '', `/poster/${id}`);
    }
    const reduced = window.matchMedia && window.matchMedia('(prefers-reduced-motion: reduce)').matches;
    if (typeof THREE === 'undefined' || reduced || opts.skipFx) { renderAnimeModal(a); return; }
    _playPortalFx(sourceEl).then(() => renderAnimeModal(a)).catch(() => { _portalBusy = false; renderAnimeModal(a); });
}
function _playPortalFx(sourceEl) {
    return new Promise(resolve => {
        _portalBusy = true;
        const wrap = document.getElementById('portalFx'), flash = document.getElementById('portalFlash');
        wrap.innerHTML = '';
        wrap.classList.add('on');
        const canvas = document.createElement('canvas');
        wrap.appendChild(canvas);
        const renderer = new THREE.WebGLRenderer({ canvas, alpha: true, antialias: true });
        renderer.setPixelRatio(Math.min(window.devicePixelRatio || 1, 1.6));
        renderer.setSize(innerWidth, innerHeight);
        const scene = new THREE.Scene();
        const camera = new THREE.PerspectiveCamera(68, innerWidth / innerHeight, .1, 120);
        camera.position.z = 22;
        const accent = getComputedStyle(document.documentElement).getPropertyValue('--accent').trim() || '#6c63ff';
        const sphere = new THREE.Mesh(new THREE.SphereGeometry(7.5, 64, 32), new THREE.MeshBasicMaterial({ color: new THREE.Color(accent), wireframe: true, transparent: true, opacity: .42 }));
        const inner = new THREE.Mesh(new THREE.IcosahedronGeometry(4.3, 2), new THREE.MeshBasicMaterial({ color: 0xa78bfa, wireframe: true, transparent: true, opacity: .28 }));
        scene.add(sphere); scene.add(inner);
        const ptsGeo = new THREE.BufferGeometry();
        const count = innerWidth < 640 ? 150 : 280;
        const pos = new Float32Array(count * 3);
        for (let i = 0; i < count; i++) {
            const radius = 9 + Math.random() * 28, theta = Math.random() * Math.PI * 2, phi = Math.acos(2 * Math.random() - 1);
            pos[i * 3] = radius * Math.sin(phi) * Math.cos(theta);
            pos[i * 3 + 1] = radius * Math.sin(phi) * Math.sin(theta);
            pos[i * 3 + 2] = radius * Math.cos(phi);
        }
        ptsGeo.setAttribute('position', new THREE.BufferAttribute(pos, 3));
        const pts = new THREE.Points(ptsGeo, new THREE.PointsMaterial({ color: 0xffffff, size: .075, transparent: true, opacity: .62 }));
        scene.add(pts);
        if (sourceEl) {
            const rect = sourceEl.getBoundingClientRect();
            const x = ((rect.left + rect.width / 2) / innerWidth - .5) * 8;
            const y = -((rect.top + rect.height / 2) / innerHeight - .5) * 5;
            sphere.position.set(x, y, 0); inner.position.copy(sphere.position);
        }
        const start = performance.now(), duration = 850;
        function frame(now) {
            const t = Math.min(1, (now - start) / duration);
            const ease = 1 - Math.pow(1 - t, 3);
            sphere.rotation.x += .012 + ease * .02; sphere.rotation.y += .018 + ease * .03;
            inner.rotation.x -= .021; inner.rotation.y += .028;
            pts.rotation.y += .004 + ease * .01;
            camera.position.z = 22 - 17 * ease;
            sphere.scale.setScalar(1 + ease * 2.6);
            inner.scale.setScalar(1 + ease * 3.3);
            renderer.render(scene, camera);
            if (t < 1) { requestAnimationFrame(frame); return; }
            flash.classList.add('on');
            setTimeout(() => flash.classList.remove('on'), 130);
            setTimeout(() => { wrap.classList.remove('on'); wrap.innerHTML = ''; renderer.dispose(); _portalBusy = false; resolve(); }, 160);
        }
        requestAnimationFrame(frame);
    });
}
function renderAnimeModal(a) {
    if (window.ytTrailerPlayer && typeof window.ytTrailerPlayer.destroy === 'function') {
        try { window.ytTrailerPlayer.destroy(); } catch (e) { }
        window.ytTrailerPlayer = null;
    }
    document.getElementById('modalContent').innerHTML = `
    <div class="m-media">
      <img class="m-img" src="${a.rams_url || ''}" onerror="this.outerHTML='<div class=m-img-ph>🎬</div>'">
      <button class="play-btn" onclick="loadVideo(${a.id})">▶</button>
    </div>
    <div class="m-body">
      <div class="m-title">${a.nom || 'Nomsiz'}</div>
      <div class="irow"><span class="ilbl">Holati</span><span class="ival">${a.aniType || '—'}</span></div>
      <div class="irow"><span class="ilbl">Qismlar</span><span class="ival">${a.ep_count || 0} ta</span></div>
      <div class="irow"><span class="ilbl">Janr</span><span class="ival">${a.janri || '—'}</span></div>
      <div class="irow"><span class="ilbl">Yili</span><span class="ival">${a.yili || '—'}</span></div>
      <div class="irow"><span class="ilbl">Davlat</span><span class="ival">${a.davlat || '—'}</span></div>
      <div class="irow"><span class="ilbl">Ovoz</span><span class="ival">${a.fandub || '—'}</span></div>
      <div class="irow"><span class="ilbl">Yosh toifasi</span><span class="ival">${a.yosh_toifa || 'Barcha yoshlar'}</span></div>
      <div class="irow"><span class="ilbl">Ko'rish</span><span class="ival">👁 ${a.qidiruv || 0}</span></div>
      <a class="m-btn" href="https://t.me/${BOT}?start=${a.id}" target="_blank">▶ Botda tomosha qilish</a>
      ${a.tavsif ? `<div class="irow" style="display:block"><span class="ilbl">Tavsif</span><span class="ival" style="display:block;margin-top:6px;line-height:1.55">${a.tavsif}</span></div>` : ''}
      ${a.filler_info ? `<div class="irow" style="display:block"><span class="ilbl">Filler qismlar</span><span class="ival" style="display:block;margin-top:6px;line-height:1.55">${a.filler_info}<br><small>Asosiy syujetga kuchli ta'sir qilmaydigan qo'shimcha qismlar.</small></span></div>` : ''}
      <a class="m-btn" href="/poster/${a.id}" onclick="event.preventDefault();navigator.clipboard?.writeText(location.origin+'/poster/${a.id}');this.textContent='Link nusxalandi'">Poster linki</a>
    </div>`;
    document.getElementById('modalBg').classList.add('open');
}

async function loadVideo(id) {
    const m = document.querySelector('.m-media'); if (!m) return;
    window._curAnimeId = id;
    m.innerHTML = `<div class="verr"><div class="spinner" style="margin:0 auto 10px"></div>Qismlar yuklanmoqda...</div>`;
    try {
        const res = await fetch(`/api/episodes/${id}`);
        const d = await res.json();
        if (!d.episodes || !d.episodes.length) { m.innerHTML = `<div class="verr">🎬 Hali qism yuklanmagan.<br><a href="https://t.me/${BOT}?start=${id}" target="_blank" style="color:var(--accent)">Botda ko'rish</a></div>`; return; }
        _playEp(m, d.episodes, 0);
    } catch (e) { m.innerHTML = `<div class="verr">⚠️ Xatolik: ${e.message}</div>`; }
}
function _playEp(mediaEl, eps, idx) {
    const ep = eps[idx]; if (!ep) return;
    window._epCache = eps;
    const epBtns = eps.map((e, i) => `<button class="ep-btn ${i === idx ? 'active' : ''}" onclick="_playEp(document.querySelector('.m-media'),window._epCache,${i})">${e.qism || (i + 1)}-qism</button>`).join('');
    const epList = eps.length > 1 ? `<div class="ep-lbl">Qismlar (${eps.length} ta):</div><div class="ep-list">${epBtns}</div>` : '';
    if (!ep.video_url || ep.too_big) {
        mediaEl.innerHTML = `<div class="verr" style="display:flex;flex-direction:column;align-items:center;gap:10px;padding:26px 14px">
      <div style="font-size:1.8rem">📦</div>
      <div>${ep.too_big ? 'Video juda katta (20MB+), botda tomosha qiling.' : 'Video topilmadi.'}</div>
      <a class="m-btn" href="https://t.me/${BOT}?start=${window._curAnimeId || ''}" target="_blank" style="width:auto;padding:10px 20px">▶ Botda ko'rish</a>
    </div>${epList}`; return;
    }
    mediaEl.innerHTML = `
    <video id="epVid" class="modal-video" controls autoplay playsinline preload="auto">
      <source src="${ep.video_url}" type="video/mp4">
    </video>
    <div id="vErr" style="display:none" class="verr">⚠️ Video ochilmadi.
      <a href="https://t.me/${BOT}?start=${window._curAnimeId || ''}" target="_blank" style="color:var(--accent)">Botda ko'rish</a>
    </div>${epList}`;
    const v = document.getElementById('epVid');
    if (v) v.addEventListener('error', () => { const e = document.getElementById('vErr'); if (e) e.style.display = 'block'; v.style.display = 'none'; });
}
function closeModal() {
    const modalBg = document.getElementById('modalBg');
    modalBg.classList.remove('open');
    modalBg.querySelector('.modal').classList.remove('al-detail');

    const v = document.querySelector('.m-media video');
    if (v) { v.pause(); v.src = ''; }

    if (window.ytTrailerPlayer && typeof window.ytTrailerPlayer.destroy === 'function') {
        try {
            window.ytTrailerPlayer.destroy();
        } catch (e) {
            console.error("Error destroying YouTube player:", e);
        }
        window.ytTrailerPlayer = null;
    }

    // Clear innerHTML to stop any playing YouTube iframe trailers
    document.getElementById('modalContent').innerHTML = '';

    window._epCache = [];
    if (!_openingPosterFromRoute && location.pathname.startsWith('/poster/')) {
        history.pushState({}, '', location.origin + '/');
    }
}

function _loadYtApi(callback) {
    if (window.YT && window.YT.Player) {
        callback();
        return;
    }
    if (window._ytCallbacks) {
        window._ytCallbacks.push(callback);
        return;
    }
    window._ytCallbacks = [callback];

    window.onYouTubeIframeAPIReady = function () {
        while (window._ytCallbacks && window._ytCallbacks.length) {
            const cb = window._ytCallbacks.shift();
            if (cb) cb();
        }
        delete window._ytCallbacks;
    };

    if (!document.getElementById('yt-iframe-api-script')) {
        const tag = document.createElement('script');
        tag.id = 'yt-iframe-api-script';
        tag.src = "https://www.youtube.com/iframe_api";
        const firstScriptTag = document.getElementsByTagName('script')[0];
        firstScriptTag.parentNode.insertBefore(tag, firstScriptTag);
    }
}
document.addEventListener('keydown', e => { if (e.key === 'Escape') closeModal(); });
window.addEventListener('popstate', () => {
    const id = _posterRouteId();
    if (id) { _openPosterRoute(id); return; }
    _openingPosterFromRoute = false;
});

async function openAlDetail(alId) {
    if (window.ytTrailerPlayer && typeof window.ytTrailerPlayer.destroy === 'function') {
        try { window.ytTrailerPlayer.destroy(); } catch (e) { }
        window.ytTrailerPlayer = null;
    }
    const modalBg = document.getElementById('modalBg');
    const modalContent = document.getElementById('modalContent');
    const modal = modalBg.querySelector('.modal');

    // Apply the large detailed view class to modal
    modal.classList.add('al-detail');
    modalContent.innerHTML = `
    <div class="al-detail-loader">
      <div class="spinner"></div>
      <div>AniList ma'lumotlari yuklanmoqda...</div>
    </div>
  `;
    modalBg.classList.add('open');

    try {
        const res = await fetch(`/api/anilist/detail?id=${alId}`);
        const d = await res.json();
        if (!d.ok) {
            modalContent.innerHTML = `<div class="verr">⚠️ Ma'lumotlarni yuklab bo'lmadi: ${d.error || 'Noma\'lum xato'}</div>`;
            return;
        }
        const a = d.result;

        // Banner section HTML
        const bannerStyle = a.banner ? `style="background-image: url('${a.banner}')"` : '';
        const bannerHtml = `
      <div class="al-detail-banner-wrap" ${bannerStyle}>
        <div class="al-detail-banner-overlay"></div>
      </div>
    `;

        // Title / cover image / badges row HTML
        const safeTitle = _alEscape(a.title || 'Nomsiz');
        const safeRomaji = _alEscape(a.title_romaji || '');
        const safeNative = _alEscape(a.title_native || '');

        let subTitles = '';
        if (safeRomaji && safeRomaji !== safeTitle) subTitles += `<div><b>Romaji:</b> ${safeRomaji}</div>`;
        if (safeNative && safeNative !== safeTitle) subTitles += `<div><b>Native:</b> ${safeNative}</div>`;

        const imgHtml = a.cover
            ? `<img class="al-detail-cover" src="${_alEscape(a.cover)}" alt="${safeTitle}">`
            : '<div class="al-detail-cover" style="display:flex;align-items:center;justify-content:center;font-size:2rem;background:var(--surface)">🎬</div>';

        const statusLabel = _alStatusLabels[a.status] || a.status || 'UNKNOWN';
        const statusCls = `al-badge status-${a.status || ''}`;

        const badgesHtml = `
      <span class="${statusCls}">${statusLabel}</span>
      ${a.score ? `<span class="al-score">⭐ ${a.score}/100</span>` : ''}
      ${a.episodes ? `<span class="al-badge">${a.episodes} qism</span>` : ''}
      ${a.year ? `<span class="al-badge">${a.year}</span>` : ''}
      ${a.format ? `<span class="al-badge">${a.format}</span>` : ''}
      ${a.season ? `<span class="al-badge" style="text-transform: uppercase;">${a.season}</span>` : ''}
    `;

        // Sidebar widgets HTML
        let sidebarHtml = '';

        // Studios widget
        if (a.studios && a.studios.length > 0) {
            sidebarHtml += `
        <div class="al-sidebar-widget">
          <div class="al-widget-title">Studiyalar</div>
          <div class="al-widget-value">${a.studios.map(s => _alEscape(s)).join(', ')}</div>
        </div>
      `;
        }

        // Genres widget
        if (a.genres && a.genres.length > 0) {
            sidebarHtml += `
        <div class="al-sidebar-widget">
          <div class="al-widget-title">Janrlar</div>
          <div style="margin: -2px;">
            ${a.genres.map(g => `<span class="al-genre-tag">${_alEscape(g)}</span>`).join('')}
          </div>
        </div>
      `;
        }

        // Synonyms / Alternative titles
        if (a.synonyms && a.synonyms.length > 0) {
            sidebarHtml += `
        <div class="al-sidebar-widget">
          <div class="al-widget-title">Muqobil Nomlar</div>
          <div class="al-widget-value" style="font-size:0.72rem; max-height:100px; overflow-y:auto;">
            ${a.synonyms.map(s => `• ${_alEscape(s)}`).join('<br>')}
          </div>
        </div>
      `;
        }

        // Main content details: Description, Trailer, Characters, Relations, Links, Tags
        let mainContentHtml = '';

        // Description
        if (a.description) {
            mainContentHtml += `
        <div class="al-sidebar-widget" style="background: transparent; border-color: var(--border2); padding: 0;">
          <div class="al-widget-title" style="font-size: 0.75rem;">Tavsif (Description)</div>
          <div class="al-widget-value" style="font-size: 0.82rem; line-height: 1.6; text-align: justify;">${a.description}</div>
        </div>
      `;
        }

        // Trailer widget (YouTube iframe embed with referrerpolicy and origin optimization)
        if (a.trailer && a.trailer.site === 'youtube' && a.trailer.id) {
            mainContentHtml += `
        <div>
          <div class="al-widget-title" style="font-size: 0.75rem;">Treyler (Trailer)</div>
          <div class="al-trailer-wrap">
            <iframe id="al-trailer-player"
                    width="100%" height="100%"
                    src="https://www.youtube-nocookie.com/embed/${a.trailer.id}?enablejsapi=1&rel=0&playsinline=1&modestbranding=1&iv_load_policy=3&origin=${encodeURIComponent(location.origin)}"
                    title="YouTube video player"
                    frameborder="0"
                    allow="accelerometer; autoplay; clipboard-write; encrypted-media; gyroscope; picture-in-picture; web-share"
                    referrerpolicy="strict-origin-when-cross-origin"
                    allowfullscreen></iframe>
          </div>
        </div>
      `;
        }

        // Relations widget
        if (a.relations && a.relations.length > 0) {
            const relationCardsHtml = a.relations.map(rel => {
                const relTitle = _alEscape(rel.title || 'Nomsiz');
                const relImg = rel.cover
                    ? `<div class="al-relation-img-wrap"><img class="al-relation-img" src="${_alEscape(rel.cover)}" alt="${relTitle}" loading="lazy"></div>`
                    : `<div class="al-relation-img-wrap" style="display:flex;align-items:center;justify-content:center;background:var(--surface);font-size:1.8rem">🎬</div>`;

                // Translate relationType to user friendly labels
                const relTypeLabels = {
                    'PREQUEL': 'Prequel (Avvalgi)',
                    'SEQUEL': 'Sequel (Keyingi)',
                    'PARENT': 'Asosiy hikoya',
                    'SIDE_STORY': 'Spin-off',
                    'SPIN_OFF': 'Spin-off',
                    'SUMMARY': 'Xulosa',
                    'ALTERNATIVE': 'Muqobil',
                    'CHARACTER': 'Qahramon',
                    'OTHER': 'Boshqa',
                };
                const relTypeLabel = relTypeLabels[rel.relation_type] || rel.relation_type;

                return `
          <div class="al-relation-card" onclick="event.stopPropagation(); openAlDetail(${rel.id})">
            ${relImg}
            <div class="al-relation-body">
              <div class="al-relation-title" title="${relTitle}">${relTitle}</div>
              <div class="al-relation-type">${_alEscape(relTypeLabel)}</div>
            </div>
          </div>
        `;
            }).join('');

            mainContentHtml += `
        <div>
          <div class="al-widget-title" style="font-size: 0.75rem;">Aloqador Animelar (Relations)</div>
          <div class="al-relations-grid">${relationCardsHtml}</div>
        </div>
      `;
        }

        // Characters widget
        if (a.characters && a.characters.length > 0) {
            const charCardsHtml = a.characters.map(char => {
                const charName = _alEscape(char.name);
                const charRole = char.role === 'MAIN' ? 'Bosh qahramon' : 'Yordamchi qahramon';
                const charImg = char.image
                    ? `<img class="al-char-img" src="${_alEscape(char.image)}" alt="${charName}">`
                    : '<div class="al-char-img" style="display:flex;align-items:center;justify-content:center;background:var(--surface);font-size:1.2rem">👤</div>';

                const vaName = _alEscape(char.va_name);
                const vaImg = char.va_image
                    ? `<img class="al-va-img" src="${_alEscape(char.va_image)}" alt="${vaName}">`
                    : '<div class="al-va-img" style="display:flex;align-items:center;justify-content:center;background:var(--surface);font-size:1.2rem">👤</div>';

                return `
          <div class="al-char-card">
            <div class="al-char-entity">
              ${charImg}
              <div class="al-char-info">
                <div class="al-char-name" title="${charName}">${charName}</div>
                <div class="al-char-role">${charRole}</div>
              </div>
            </div>
            ${char.va_name ? `
              <div class="al-va-entity">
                <div class="al-va-info">
                  <div class="al-va-name" title="${vaName}">${vaName}</div>
                  <div class="al-va-lang">Seiyuu (JP)</div>
                </div>
                ${vaImg}
              </div>
            ` : '<div style="width:48%; display:flex; align-items:center; justify-content:center; font-size:0.6rem; color:var(--muted)">Ovoz berilmagan</div>'}
          </div>
        `;
            }).join('');

            mainContentHtml += `
        <div>
          <div class="al-widget-title" style="font-size: 0.75rem;">Qahramonlar va Ovoz Beruvchilar (Characters & Staff)</div>
          <div class="al-chars-grid">${charCardsHtml}</div>
        </div>
      `;
        }

        // External and streaming links widget
        if (a.links && a.links.length > 0) {
            const linksHtml = a.links.map(link => {
                const linkBgColor = link.color || '#3f3f46';
                return `
          <a class="al-link-btn" href="${_alEscape(link.url)}" target="_blank" style="background-color: ${linkBgColor};">
            <span>🔗</span>
            <span>${_alEscape(link.site)}</span>
          </a>
        `;
            }).join('');

            mainContentHtml += `
        <div>
          <div class="al-widget-title" style="font-size: 0.75rem;">Rasmiy havolalar va Translyatsiya (Streaming & Links)</div>
          <div style="margin: -3px;">${linksHtml}</div>
        </div>
      `;
        }

        // Tags widget
        if (a.tags && a.tags.length > 0) {
            const tagsHtml = a.tags.map(tag => `
        <span class="al-genre-tag" style="border-color: var(--border2); padding: 4px 10px;" title="Rank: ${tag.rank}%">
          #${_alEscape(tag.name)} <span style="opacity:0.6; font-size:0.55rem; margin-left:2px;">${tag.rank}%</span>
        </span>
      `).join('');

            mainContentHtml += `
        <div>
          <div class="al-widget-title" style="font-size: 0.75rem;">Teglar (Tags)</div>
          <div style="margin: -2px;">${tagsHtml}</div>
        </div>
      `;
        }

        // Assemble the complete modal markup
        modalContent.innerHTML = `
      ${bannerHtml}
      <div class="al-detail-header-content">
        ${imgHtml}
        <div class="al-detail-title-block">
          <div class="al-detail-main-title">${safeTitle}</div>
          <div class="al-detail-sub-titles">${subTitles}</div>
          <div class="al-detail-badges-row">${badgesHtml}</div>
        </div>
      </div>
      <div class="al-detail-layout">
        <div class="al-detail-sidebar">${sidebarHtml}</div>
        <div class="al-detail-main-content">${mainContentHtml}</div>
      </div>
    `;

        // Initialize YouTube trailer player if trailer exists in DOM
        if (a.trailer && a.trailer.site === 'youtube' && a.trailer.id) {
            _loadYtApi(() => {
                const iframe = document.getElementById('al-trailer-player');
                if (!iframe) return;

                window.ytTrailerPlayer = new YT.Player('al-trailer-player', {
                    events: {
                        'onStateChange': (event) => {
                            if (event.data === YT.PlayerState.PLAYING) {
                                const epVid = document.getElementById('epVid');
                                if (epVid && typeof epVid.pause === 'function') {
                                    epVid.pause();
                                }
                            }
                        }
                    }
                });
            });
        }

    } catch (e) {
        modalContent.innerHTML = `<div class="verr">⚠️ Kutilmagan xatolik yuz berdi: ${e.message}</div>`;
    }
}


// ── ADMINS ──
async function renderAdmins() {
    const g = document.getElementById('adminGrid');
    g.innerHTML = '<div class="loading"><div class="spinner"></div>Yuklanmoqda...</div>';
    let admins = [];
    try { const res = await fetch('/api/admins'); if (res.ok) { const d = await res.json(); admins = d.admins || []; } else throw new Error(); }
    catch { g.innerHTML = '<div class="empty" style="grid-column:1/-1"><div class="empty-ico">⚠️</div><h3>Serverga ulanib bo\'lmadi</h3></div>'; return; }
    if (!admins.length) { g.innerHTML = '<div class="empty" style="grid-column:1/-1"><div class="empty-ico">👥</div><h3>Adminlar topilmadi</h3></div>'; return; }
    g.innerHTML = admins.map(a => {
        const sup = a.is_super;
        const av = a.photo ? `<img class="avt" src="${a.photo}" onerror="this.style.display='none'">` : `<div class="avt-ph">${(a.name[0] || 'A').toUpperCase()}</div>`;
        const rc = sup ? 'var(--accent3)' : 'var(--accent)';
        return `<div class="aw" onclick="window.open('${a.link}','_blank')">
      <div class="af-fl">
        <div class="af${sup ? ' sup' : ''}">
          ${av}
          <div class="aname">${a.name}</div>
          <div class="aun">${a.username}</div>
          <span class="atag ${sup ? 'dev' : 'adm'}">${sup ? '✦ Developer' : '◈ Admin'}</span>
        </div>
        <div class="ab2${sup ? ' sup' : ''}">
          <div class="ab2-r">
            <div class="ab2-init">${(a.name[0] || '?').toUpperCase()}</div>
            <div class="ab2-role" style="color:${rc}">${sup ? '✦ Developer' : '◈ Admin'}</div>
            <div class="ab2-un">${a.username}</div>
            <div class="ab2-div"></div>
            <a class="ab2-btn" href="${a.link}" target="_blank" onclick="event.stopPropagation()">Telegram →</a>
          </div>
        </div>
      </div></div>`;
    }).join('');
}

// ── STATS ──
let _sl = false, _ci = null;
const SDEFS = [
    { key: 'users', icon: '👥', label: 'Foydalanuvchilar', color: 'sc-cyan', desc: 'Botga /start bosgan foydalanuvchilar' },
    { key: 'vip', icon: '👑', label: 'VIP Obunachlar', color: 'sc-purple', desc: "Faol VIP obuna bo'lganlar" },
    { key: 'animes', icon: '🎬', label: 'Animelar', color: 'sc-pink', desc: 'Jami anime sarlavhalar' },
    { key: 'eps', icon: '🎞', label: 'Jami Qismlar', color: 'sc-green', desc: 'Yuklangan qismlar soni' },
];
async function renderStats() {
    if (_sl) return; _sl = true;
    let st = { users: 0, vip: 0, animes: 0, eps: 0 };
    try { const r = await fetch('/api/stats'); if (r.ok) st = await r.json(); } catch { }
    document.getElementById('statGrid').innerHTML = SDEFS.map(d => {
        const v = st[d.key] || 0; const dv = v >= 1000 ? (v / 1000).toFixed(1) + 'K' : v;
        return `<div class="sc-w ${d.color}"><div class="sc-fl">
      <div class="scf"><div class="sc-ico">${d.icon}</div><div class="sc-val">${dv}</div><div class="sc-lbl">${d.label}</div></div>
      <div class="scb"><div class="sc-bi">${d.icon}</div><div class="sc-bt">${d.label}</div><div class="sc-bv">${dv}</div><div class="sc-bd">${d.desc}</div></div>
    </div></div>`;
    }).join('');
    if (_ci) { _ci.destroy(); _ci = null; }
    _ci = new Chart(document.getElementById('actChart'), { type: 'bar', data: { labels: SDEFS.map(d => d.label), datasets: [{ data: SDEFS.map(d => st[d.key] || 0), backgroundColor: ['rgba(0,212,255,.55)', 'rgba(139,92,246,.55)', 'rgba(240,171,252,.55)', 'rgba(16,255,160,.55)'], borderColor: ['rgba(0,212,255,1)', 'rgba(139,92,246,1)', 'rgba(240,171,252,1)', 'rgba(16,255,160,1)'], borderWidth: 1, borderRadius: 4 }] }, options: { responsive: true, plugins: { legend: { display: false }, tooltip: { backgroundColor: 'rgba(4,4,18,.96)', borderColor: 'rgba(0,212,255,.3)', borderWidth: 1, titleColor: '#00d4ff', bodyColor: '#dde8ff', titleFont: { family: 'Orbitron', size: 10 } } }, scales: { x: { ticks: { color: 'rgba(160,185,230,.6)', font: { family: 'Orbitron', size: 9 } }, grid: { color: 'rgba(0,212,255,.06)' } }, y: { ticks: { color: 'rgba(160,185,230,.6)', font: { family: 'Orbitron', size: 9 } }, grid: { color: 'rgba(0,212,255,.06)' } } } } });
}

// ── REPORT ──
let rType = 'bug';
function selectType(btn, type) { document.querySelectorAll('.rf-type-btn').forEach(b => b.classList.remove('sel')); btn.classList.add('sel'); rType = type; }
function updateChar() { const v = document.getElementById('rMsg')?.value || ''; document.getElementById('rCharCount').textContent = v.length; }
async function sendReport() {
    const msg = (document.getElementById('rMsg')?.value || '').trim();
    if (!msg) { document.getElementById('rMsg').focus(); return; }
    const btn = document.getElementById('rSendBtn');
    btn.disabled = true; btn.textContent = '⏳ Yuborilmoqda...';
    const name = (document.getElementById('rName')?.value || '').trim();
    const uname = (document.getElementById('rUsername')?.value || '').trim();
    try {
        const res = await fetch('/api/report', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ type: rType, name, username: uname, message: msg }) });
        const d = await res.json();
        if (!d.ok) throw new Error(d.error || 'Server xatosi');
    } catch (e) { btn.disabled = false; btn.textContent = '🚀 Yuborish'; alert('Xatolik: ' + e.message); return; }
    document.getElementById('rSuccess').classList.add('show');
    btn.disabled = false; btn.textContent = '🚀 Yuborish';
    document.getElementById('rMsg').value = '';
    document.getElementById('rName').value = '';
    document.getElementById('rUsername').value = '';
    updateChar();
    setTimeout(() => document.getElementById('rSuccess').classList.remove('show'), 5000);
}

// ── AI CHAT ──
let _aiAdminPasswordMode = false;
function toggleAi() { window.location.href = './Ai/Ai.html'; }
function _escHtml(s) { return String(s ?? '').replace(/[&<>"']/g, m => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[m])); }
async function sendAi() {
    const inp = document.getElementById('chatInp');
    const msg = inp.value.trim(); if (!msg) return;
    inp.value = '';
    const m = document.getElementById('chatMsgs');
    const pendingId = 'aiT' + Date.now();
    const visibleMsg = _aiAdminPasswordMode ? '••••••' : msg;
    m.innerHTML += `<div class="msg user">${_escHtml(visibleMsg)}</div><div class="msg ai" id="${pendingId}">...</div>`;
    m.scrollTop = m.scrollHeight;
    try {
        const res = await fetch('/api/ai/chat', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ message: msg, admin_password_mode: _aiAdminPasswordMode }) });
        const d = await res.json();
        _aiAdminPasswordMode = !!d.admin_password_required;
        document.getElementById(pendingId).outerHTML = `<div class="msg ai">${_escHtml(d.reply || '❌ Xatolik')}</div>`;
        if (d.admin_ok) {
            if (d.admin_token) localStorage.setItem('az_admin_token', d.admin_token);
            setTimeout(() => { window.location.href = d.admin_url || '/admin'; }, 500);
        }
    } catch { document.getElementById(pendingId).outerHTML = `<div class="msg ai">⚠️ Serverga ulanib bo'lmadi.</div>`; }
    m.scrollTop = m.scrollHeight;
}

loadAnimes();

// ══ GAME ══
let _gToken = localStorage.getItem('az_token') || '';
let _gUser = JSON.parse(localStorage.getItem('az_user') || 'null');
let _gGameId = null, _gState = null, _gWaiting = false;
function _authHeaders() { return { 'Content-Type': 'application/json', 'Authorization': 'Bearer ' + _gToken }; }
function initGame() { _refreshUserBadge(); _refreshTopbarAuth && _refreshTopbarAuth(); if (_gUser && _gToken) { _renderGameReady(); } else { _renderLoginScreen(); } }
function _refreshUserBadge() { const badge = document.getElementById('game-user-badge'); if (!badge) return; if (_gUser) { badge.style.display = 'flex'; const av = document.getElementById('game-avatar'); if (av) { av.src = _gUser.picture || ''; av.style.display = _gUser.picture ? 'block' : 'none'; } const un = document.getElementById('game-uname'); if (un) un.textContent = _gUser.name || ''; } else { badge.style.display = 'none'; } }
function _renderLoginScreen() { const root = document.getElementById('game-root'); if (!root) return; const clientId = document.querySelector('meta[name="google-client-id"]')?.content || ''; const redirectUri = window.location.origin + '/callback'; const scope = 'openid profile email'; const authUrl = `https://accounts.google.com/o/oauth2/v2/auth?response_type=code&client_id=${clientId}&redirect_uri=${encodeURIComponent(redirectUri)}&scope=${encodeURIComponent(scope)}&access_type=offline`; root.innerHTML = `<div class="g-login-wrap"><div class="g-login-ico">🃏</div><div class="g-login-title">Anime Karta Jangi</div><div class="g-login-desc">Anime kartalaringiz bilan CPU ga qarshi jang qiling!</div><button class="g-google-btn" onclick="window.location.href='${authUrl}'"><svg viewBox="0 0 48 48"><path fill="#EA4335" d="M24 9.5c3.54 0 6.71 1.22 9.21 3.6l6.85-6.85C35.9 2.38 30.47 0 24 0 14.62 0 6.51 5.38 2.56 13.22l7.98 6.19C12.43 13.08 17.74 9.5 24 9.5z"/><path fill="#4285F4" d="M46.98 24.55c0-1.57-.15-3.09-.38-4.55H24v9.02h12.94c-.58 2.96-2.26 5.48-4.78 7.18l7.73 6c4.51-4.18 7.09-10.36 7.09-17.65z"/><path fill="#FBBC05" d="M10.53 28.59c-.48-1.45-.76-2.99-.76-4.59s.27-3.14.76-4.59l-7.98-6.19C.92 16.46 0 20.12 0 24c0 3.88.92 7.54 2.56 10.78l7.97-6.19z"/><path fill="#34A853" d="M24 48c6.48 0 11.93-2.13 15.89-5.81l-7.73-6c-2.18 1.48-4.97 2.31-8.16 2.31-6.26 0-11.57-3.59-13.46-8.78l-7.98 6.19C6.51 42.62 14.62 48 24 48z"/></svg>Google bilan kirish</button></div>`; }
function _renderGameReady() { const root = document.getElementById('game-root'); if (!root) return; root.innerHTML = `<div class="g-over" style="padding:40px 20px"><div class="g-over-ico">🃏</div><div class="g-over-title">Tayyor!</div><div class="g-over-score">Salom, <b>${_gUser.name}</b>! O'yinni boshlang.</div><button class="g-play-again" onclick="startGame()">▶ O'yinni Boshlash</button></div>`; }
async function startGame() { const root = document.getElementById('game-root'); root.innerHTML = '<div class="g-loading"><div class="spinner" style="margin:0 auto 12px"></div>Kartalar tayyorlanmoqda...</div>'; const res = await fetch('/api/game/start', { method: 'POST', headers: _authHeaders() }); const d = await res.json(); if (!d.ok) { root.innerHTML = `<div class="g-loading">❌ ${d.error}</div>`; return; } _gGameId = d.game_id; _gState = d.state; _gWaiting = false; _renderBoard(); }
function _renderBoard() { const root = document.getElementById('game-root'); if (!root || !_gState) return; const st = _gState; if (st.finished) { _renderGameOver(); return; } const pc = st.player_card, cc = st.cpu_card, lastRound = st.history.length > 0 ? st.history[st.history.length - 1] : null; root.innerHTML = `<div class="g-board"><div class="g-score-bar"><div class="g-score-side"><div class="g-score-name">👤 Siz</div><div class="g-score-val player">${st.player_score}</div></div><div class="g-score-mid"><div class="g-round-info">Tur ${st.round + 1}/${st.total_rounds}</div><div style="margin-top:3px">VS</div></div><div class="g-score-side"><div class="g-score-name">AnimeUZ AI CPU</div><div class="g-score-val cpu">${st.cpu_score}</div></div></div>${lastRound && _gWaiting ? _roundResultHtml(lastRound) : ''} ${!_gWaiting ? '<div class="g-choose-prompt">⬇ Statistika tanlang</div>' : ''}<div class="g-cards-row">${_cardHtml(pc, 'you', lastRound, true)}<div class="g-vs-badge">VS</div>${_cardHtml(cc, 'cpu', lastRound, false)}</div></div>`; }
function _cardHtml(card, side, lastRound, isPlayer) { if (!card) return '<div></div>'; const poster = card.poster ? `<img class="g-card-poster" src="${card.poster}" onerror="this.outerHTML='<div class=g-card-poster-ph>🎬</div>'">` : '<div class="g-card-poster-ph">🎬</div>'; const ownerLabel = isPlayer ? 'Sizning karta' : 'CPU kartasi'; const ownerClass = isPlayer ? 'you' : 'cpu-label'; let winnerClass = ''; if (lastRound && _gWaiting) { if (lastRound.result === 'player') winnerClass = isPlayer ? 'winner' : 'loser'; else if (lastRound.result === 'cpu') winnerClass = isPlayer ? 'loser' : 'winner'; else winnerClass = 'draw-c'; } const stats = _gState.stats.map(s => { let cls = 'g-stat-row', txtCls = 'g-stat-lbl'; if (_gWaiting && lastRound && lastRound.stat_key === s.key) { cls += ' chosen'; if (lastRound.result === 'draw') cls = 'g-stat-row draw-s'; else if ((lastRound.result === 'player') === isPlayer) { cls = 'g-stat-row win'; txtCls += ' colored'; } else { cls = 'g-stat-row lose'; txtCls += ' colored'; } } const val = card[s.key] ?? '—'; const clickable = !_gWaiting && isPlayer; const onclick = clickable ? `onclick="playMove('${s.key}')"` : ''; return `<div class="${cls}" ${onclick}><span class="${txtCls}">${s.icon} ${s.label}</span><span class="g-stat-val">${val || '—'}</span></div>`; }).join(''); return `<div class="g-card ${winnerClass}"><div class="g-card-owner ${ownerClass}">${ownerLabel}</div>${poster}<div class="g-card-body"><div class="g-card-title">${card.nom}</div><div class="g-card-stats">${stats}</div></div></div>`; }
function _roundResultHtml(r) { let cls, ico, txt, sub; if (r.result === 'player') { cls = 'win'; ico = '🎉'; txt = 'Siz yutdingiz!'; sub = `${r.stat_icon} ${r.stat_label}: Siz <b>${r.player_val}</b> vs CPU <b>${r.cpu_val}</b>`; } else if (r.result === 'cpu') { cls = 'lose'; ico = '😤'; txt = 'CPU yutdi!'; sub = `${r.stat_icon} ${r.stat_label}: Siz <b>${r.player_val}</b> vs CPU <b>${r.cpu_val}</b>`; } else { cls = 'draw-r'; ico = '🤝'; txt = 'Durrang!'; sub = `${r.stat_icon} ${r.stat_label}: Ikkalasi ham <b>${r.player_val}</b>`; } return `<div class="g-round-result ${cls}"><div class="g-rr-ico">${ico}</div><div class="g-rr-text">${txt}</div><div class="g-rr-sub">${sub}</div><button class="g-next-btn" onclick="nextRound()">Keyingi tur ➡</button></div>`; }
function _renderGameOver() { const root = document.getElementById('game-root'); const st = _gState; let ico, title, sub; if (st.winner === 'player') { ico = '🏆'; title = "G'alaba!"; sub = 'Tabriklaymiz!'; } else if (st.winner === 'cpu') { ico = '💀'; title = 'Yutqazdingiz!'; sub = 'CPU sizni yendi.'; } else { ico = '🤝'; title = 'Durrang!'; sub = "Teng natija."; } root.innerHTML = `<div class="g-over"><div class="g-over-ico">${ico}</div><div class="g-over-title">${title}</div><div class="g-over-score">${sub}<br><b>${st.player_score}</b> : <b>${st.cpu_score}</b></div><button class="g-play-again" onclick="startGame()">🔁 Qayta O'ynash</button></div>`; }
async function playMove(statKey) { if (_gWaiting || !_gGameId) return; const res = await fetch(`/api/game/${_gGameId}/move`, { method: 'POST', headers: _authHeaders(), body: JSON.stringify({ stat: statKey }) }); const d = await res.json(); if (!d.ok) { alert(d.error); return; } _gState = d.state; _gWaiting = true; _renderBoard(); }
function nextRound() { _gWaiting = false; _renderBoard(); }

// ── GAME TABS ──
let _activeGameTab = 'card';
function switchGameTab(tab) {
    _activeGameTab = tab;
    const cardRoot = document.getElementById('game-root'), guessRoot = document.getElementById('guess-root');
    const tabCard = document.getElementById('gtab-card'), tabGuess = document.getElementById('gtab-guess');
    if (tab === 'card') {
        cardRoot.style.display = ''; guessRoot.style.display = 'none';
        tabCard.style.background = 'var(--accent)'; tabCard.style.color = '#000'; tabCard.style.borderColor = 'var(--accent)';
        tabGuess.style.background = 'var(--card-bg)'; tabGuess.style.color = 'var(--muted)'; tabGuess.style.borderColor = 'var(--border)';
        initGame();
    } else {
        cardRoot.style.display = 'none'; guessRoot.style.display = '';
        tabGuess.style.background = 'var(--accent)'; tabGuess.style.color = '#000'; tabGuess.style.borderColor = 'var(--accent)';
        tabCard.style.background = 'var(--card-bg)'; tabCard.style.color = 'var(--muted)'; tabCard.style.borderColor = 'var(--border)';
        initGuessGame();
    }
}

// ── GUESS GAME ──
let _guessState = null;
async function initGuessGame() { const root = document.getElementById('guess-root'); if (!root) return; if (!_gUser || !_gToken) { _renderGuessLogin(root); return; } if (_guessState && !_guessState.finished) { _renderGuessBoard(root); } else { _renderGuessMenu(root); } }
function _renderGuessLogin(root) { const url = _getGoogleAuthUrl(); root.innerHTML = `<div class="g-login-wrap"><div class="g-login-ico">🎯</div><div class="g-login-title">Anime Taxminlash</div><div class="g-login-desc">Animening rasmini ko'rib, nomini toping!</div><button class="g-google-btn" onclick="window.location.href='${url}'"><svg viewBox="0 0 48 48"><path fill="#EA4335" d="M24 9.5c3.54 0 6.71 1.22 9.21 3.6l6.85-6.85C35.9 2.38 30.47 0 24 0 14.62 0 6.51 5.38 2.56 13.22l7.98 6.19C12.43 13.08 17.74 9.5 24 9.5z"/><path fill="#4285F4" d="M46.98 24.55c0-1.57-.15-3.09-.38-4.55H24v9.02h12.94c-.58 2.96-2.26 5.48-4.78 7.18l7.73 6c4.51-4.18 7.09-10.36 7.09-17.65z"/><path fill="#FBBC05" d="M10.53 28.59c-.48-1.45-.76-2.99-.76-4.59s.27-3.14.76-4.59l-7.98-6.19C.92 16.46 0 20.12 0 24c0 3.88.92 7.54 2.56 10.78l7.97-6.19z"/><path fill="#34A853" d="M24 48c6.48 0 11.93-2.13 15.89-5.81l-7.73-6c-2.18 1.48-4.97 2.31-8.16 2.31-6.26 0-11.57-3.59-13.46-8.78l-7.98 6.19C6.51 42.62 14.62 48 24 48z"/></svg>Google bilan kirish</button></div>`; }
function _renderGuessMenu(root) { root.innerHTML = `<div class="g-over" style="padding:40px 20px"><div class="g-over-ico">🎯</div><div class="g-over-title">Anime Taxminlash</div><div class="g-over-score">Salom, <b>${_gUser.name}</b>!</div><button class="g-play-again" onclick="startGuessGame()">▶ O'yinni Boshlash</button></div>`; }
async function startGuessGame() { const root = document.getElementById('guess-root'); root.innerHTML = '<div class="g-loading"><div class="spinner" style="margin:0 auto 12px"></div>Savollar tayyorlanmoqda...</div>'; try { const res = await fetch('/api/animes'); const data = await res.json(); let animes = data.animes || []; if (animes.length < 8) { root.innerHTML = '<div class="g-loading">❌ DB da yetarli anime yo\'q</div>'; return; } animes = animes.sort(() => Math.random() - .5); const selected = animes.slice(0, 6); const otherPool = animes.slice(6); const questions = selected.map(correct => { const wrong = otherPool.filter(a => a.id !== correct.id).sort(() => Math.random() - .5).slice(0, 3).map(a => a.nom); const options = [correct.nom, ...wrong].sort(() => Math.random() - .5); return { anime: correct, options, correct: correct.nom }; }); _guessState = { questions, current: 0, score: 0, total: 6, answered: null, chosenOption: null, finished: false }; _renderGuessBoard(root); } catch (e) { root.innerHTML = `<div class="g-loading">❌ Xatolik: ${e.message}</div>`; } }
function _renderGuessBoard(root) { if (!_guessState) return; const st = _guessState; if (st.finished) { _renderGuessOver(root); return; } const q = st.questions[st.current]; const anime = q.anime; const imgUrl = anime.rams_url || ''; const progress = Math.round((st.current / st.total) * 100); let optionsHtml = ''; for (let i = 0; i < q.options.length; i++) { const opt = q.options[i]; let cls = 'guess-opt', icon = ''; if (st.answered !== null) { if (opt === q.correct) { cls += ' correct'; icon = ' ✅'; } else if (opt === st.chosenOption && opt !== q.correct) { cls += ' wrong'; icon = ' ❌'; } else { cls += ' disabled'; } } const clickAttr = st.answered === null ? 'onclick="guessAnswer(' + i + ')"' : ''; optionsHtml += '<button class="' + cls + '" ' + clickAttr + '>' + opt + icon + '</button>'; } let nextBtn = ''; if (st.answered !== null) { const btnLabel = (st.current + 1 >= st.total) ? '🏁 Natijani Ko\'rish' : 'Keyingi Savol ➡'; nextBtn = '<button class="g-next-btn" style="margin-top:14px;width:100%" onclick="guessNext()">' + btnLabel + '</button>'; } root.innerHTML = '<div style="max-width:480px;margin:0 auto"><div style="display:flex;align-items:center;justify-content:space-between;margin-bottom:8px"><span style="font-size:.78rem;color:var(--muted)">Savol ' + (st.current + 1) + ' / ' + st.total + '</span><span style="font-size:.78rem;font-weight:700;color:var(--accent)">🏆 ' + st.score + ' ball</span></div><div style="height:5px;background:var(--border);border-radius:4px;margin-bottom:16px;overflow:hidden"><div style="height:100%;width:' + progress + '%;background:var(--accent);border-radius:4px;transition:width .4s"></div></div><div style="position:relative;width:100%;border-radius:12px;overflow:hidden;border:1px solid var(--border);margin-bottom:16px;background:var(--card-bg)"><img src="' + imgUrl + '" style="width:100%;height:auto;max-height:320px;object-fit:contain;display:block;background:var(--border2)" onerror="this.style.display=\'none\'"><div style="position:absolute;top:10px;left:10px;background:rgba(0,0,0,.7);padding:3px 10px;border-radius:20px;font-size:.72rem;color:#fff;font-weight:600">Bu anime nima? 🤔</div></div><div class="guess-opts-grid">' + optionsHtml + '</div>' + nextBtn + '</div>'; }
function guessAnswer(optIdx) { if (!_guessState || _guessState.answered !== null) return; const q = _guessState.questions[_guessState.current]; const chosen = q.options[optIdx]; _guessState.chosenOption = chosen; if (chosen === q.correct) { _guessState.answered = 'correct'; _guessState.score++; } else { _guessState.answered = 'wrong'; } _renderGuessBoard(document.getElementById('guess-root')); }
function guessNext() { if (!_guessState) return; _guessState.current++; _guessState.answered = null; _guessState.chosenOption = null; if (_guessState.current >= _guessState.total) { _guessState.finished = true; } _renderGuessBoard(document.getElementById('guess-root')); }
function _renderGuessOver(root) { const st = _guessState; const pct = Math.round((st.score / st.total) * 100); let ico, title, sub; if (pct >= 80) { ico = "🏆"; title = "Zo'r natija!"; sub = "Siz haqiqiy anime bilimdonisiz!"; } else if (pct >= 50) { ico = "😊"; title = "Yaxshi urinish!"; sub = "Yana mashq kerak."; } else { ico = "😅"; title = "Qiyin ekan..."; sub = "Ko'proq anime ko'ring!"; } root.innerHTML = `<div class="g-over"><div class="g-over-ico">${ico}</div><div class="g-over-title">${title}</div><div class="g-over-score">${sub}<br><b>${st.score}</b>/<b>${st.total}</b> to'g'ri • <b>${pct}%</b></div><button class="g-play-again" onclick="startGuessGame()">🔁 Qayta O'ynash</button></div>`; }

// ── TOPBAR AUTH ──
function _getGoogleAuthUrl() { const clientId = document.querySelector('meta[name="google-client-id"]')?.content || ''; const redirectUri = window.location.origin + '/callback'; const scope = 'openid profile email'; return `https://accounts.google.com/o/oauth2/v2/auth?response_type=code&client_id=${clientId}&redirect_uri=${encodeURIComponent(redirectUri)}&scope=${encodeURIComponent(scope)}&access_type=offline`; }
function topbarLogin() { const url = _getGoogleAuthUrl(); if (!url.includes('client_id=&')) { window.location.href = url; } else { alert("GOOGLE_CLIENT_ID sozlanmagan."); } }
// ── ANILIST GLOBAL QIDIRUV ──
const _alStatusLabels = {
    RELEASING: '🔴 OnGoing',
    FINISHED: '✅ Tugallangan',
    NOT_YET_RELEASED: '⏳ Tez Kunda',
    CANCELLED: '❌ Bekor',
    HIATUS: '⏸ Pauza',
};

let _alCountdownTimer = null;

function _alEscape(v) {
    return String(v ?? '').replace(/[&<>"']/g, ch => ({
        '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;'
    }[ch]));
}

function _alFormatAiringDate(airingAt) {
    if (!airingAt) return '';
    try {
        return new Intl.DateTimeFormat('uz-UZ', {
            day: '2-digit', month: 'short', year: 'numeric',
            hour: '2-digit', minute: '2-digit'
        }).format(new Date(airingAt * 1000));
    } catch {
        return new Date(airingAt * 1000).toLocaleString();
    }
}

function _alCountdownParts(airingAt) {
    const diff = Math.max(0, (airingAt * 1000) - Date.now());
    const total = Math.floor(diff / 1000);
    const days = Math.floor(total / 86400);
    const hours = Math.floor((total % 86400) / 3600);
    const mins = Math.floor((total % 3600) / 60);
    const secs = total % 60;
    return { diff, days, hours, mins, secs };
}

function _alRenderCountdowns() {
    document.querySelectorAll('[data-airing-at]').forEach(el => {
        const airingAt = Number(el.dataset.airingAt || 0);
        const p = _alCountdownParts(airingAt);
        if (!airingAt) return;
        if (p.diff <= 0) {
            el.innerHTML = '<div class="al-airing-ended">Chiqdi yoki AniList yangilanmoqda</div>';
            return;
        }
        const pad = n => String(n).padStart(2, '0');
        el.innerHTML = `
      <div class="al-count-unit"><span class="al-count-num">${p.days}</span><span class="al-count-lbl">Kun</span></div>
      <div class="al-count-unit"><span class="al-count-num">${pad(p.hours)}</span><span class="al-count-lbl">Soat</span></div>
      <div class="al-count-unit"><span class="al-count-num">${pad(p.mins)}</span><span class="al-count-lbl">Daq</span></div>
      <div class="al-count-unit"><span class="al-count-num">${pad(p.secs)}</span><span class="al-count-lbl">Son</span></div>`;
    });
}

function _alStartCountdowns() {
    if (_alCountdownTimer) clearInterval(_alCountdownTimer);
    _alRenderCountdowns();
    if (document.querySelector('[data-airing-at]')) {
        _alCountdownTimer = setInterval(_alRenderCountdowns, 1000);
    }
}

async function _checkAnilistStatus() {
    const bar = document.getElementById('alConnectBar');
    const btn = document.getElementById('alConnectBtn');
    if (!bar) return;

    if (!_gToken) {
        // Google login qilinmagan — ulash tugmasi Google login ga yo'naltirsin
        if (btn) { btn.textContent = 'Kirish kerak'; btn.onclick = () => topbarLogin(); }
        return;
    }

    try {
        const res = await fetch('/api/auth/anilist/status', { headers: _authHeaders() });
        const d = await res.json();
        if (d.ok && d.connected && d.anilist) {
            // Ulangan
            const av = d.anilist.avatar
                ? `<img src="${d.anilist.avatar}" style="width:22px;height:22px;border-radius:50%;object-fit:cover">`
                : '🟦';
            bar.innerHTML = `
        <div class="al-logo">${av}</div>
        <div class="al-info">
          <div class="al-title">AniList ulangan</div>
          <div class="al-sub">${d.anilist.name || ''}</div>
        </div>
        <div class="al-connected-badge">✅ Ulangan</div>`;
        }
    } catch (_) { }
}

async function anilistConnect() {
    if (!_gToken) { topbarLogin(); return; }
    const btn = document.getElementById('alConnectBtn');
    if (btn) { btn.disabled = true; btn.textContent = 'Yo\'naltirilmoqda...'; }
    try {
        const res = await fetch('/api/auth/anilist', { headers: _authHeaders() });
        const d = await res.json();
        if (d.ok && d.url) {
            const popup = window.open(d.url, 'anilist_oauth',
                'width=520,height=640,menubar=no,toolbar=no,status=no');
            // Popup yopilishini kuzatamiz
            const timer = setInterval(async () => {
                if (popup && popup.closed) {
                    clearInterval(timer);
                    await _checkAnilistStatus();
                }
            }, 800);
        } else {
            alert(d.error || 'AniList ulanishda xatolik');
            if (btn) { btn.disabled = false; btn.textContent = 'Ulash'; }
        }
    } catch (e) {
        alert('Xatolik: ' + e.message);
        if (btn) { btn.disabled = false; btn.textContent = 'Ulash'; }
    }
}

async function glSearch() {
    const q = (document.getElementById('glSearchInput')?.value || '').trim();
    if (!q) return;

    const grid = document.getElementById('glResultGrid');
    const bar = document.getElementById('glResultBar');
    const btn = document.getElementById('glSearchBtn');
    const cntEl = document.getElementById('glResultCount');

    if (!grid) return;
    if (_alCountdownTimer) clearInterval(_alCountdownTimer);
    btn.disabled = true;
    grid.innerHTML = '<div class="gl-msg"><div class="spinner" style="margin:0 auto 14px"></div>Qidirilmoqda...</div>';
    if (bar) bar.style.display = 'none';

    try {
        const res = await fetch(`/api/anilist/search?q=${encodeURIComponent(q)}&per=24`);
        const data = await res.json();

        if (!data.ok) {
            grid.innerHTML = `<div class="gl-msg"><div class="gl-msg-ico">❌</div>${data.error || 'Xatolik'}</div>`;
            return;
        }

        const items = data.results || [];
        if (cntEl) cntEl.textContent = items.length;
        if (bar) bar.style.display = '';

        if (!items.length) {
            grid.innerHTML = `<div class="gl-msg"><div class="gl-msg-ico">🔎</div>"${q}" bo'yicha hech narsa topilmadi.</div>`;
            return;
        }

        grid.innerHTML = items.map(a => {
            const safeTitle = _alEscape(a.title || 'Nomsiz');
            const img = a.cover
                ? `<img class="al-card-img" src="${_alEscape(a.cover)}" alt="${safeTitle}" loading="lazy" onerror="this.outerHTML='<div class=al-card-img-ph>🎬</div>'">`
                : '<div class="al-card-img-ph">🎬</div>';

            const statusLabel = _alStatusLabels[a.status] || a.status || 'UNKNOWN';
            const statusCls = `al-badge status-${a.status || ''}`;
            const scoreBadge = a.score
                ? `<span class="al-score">⭐ ${a.score}/100</span>`
                : '';
            const epBadge = a.episodes
                ? `<span class="al-badge">${a.episodes} qism</span>`
                : '';
            const yearBadge = a.year
                ? `<span class="al-badge">${a.year}</span>`
                : '';
            const fmtBadge = a.format
                ? `<span class="al-badge">${a.format}</span>`
                : '';
            const airing = a.next_airing && a.next_airing.airingAt
                ? `<div class="al-airing">
            <div class="al-airing-top">
              <span>Keyingi qism</span>
              <span>${a.next_airing.episode ? _alEscape(a.next_airing.episode) + '-qism' : ''}</span>
            </div>
            <div class="al-airing-date">Chiqish vaqti: ${_alEscape(_alFormatAiringDate(a.next_airing.airingAt))}</div>
            <div class="al-countdown" data-airing-at="${Number(a.next_airing.airingAt)}"></div>
          </div>`
                : '';

            return `<div class="al-card" onclick="openAlDetail(${a.id})" style="cursor: pointer;">
        ${img}
        <div class="al-card-body">
          <div class="al-card-title" title="${safeTitle}">${safeTitle}</div>
          <div class="al-card-meta">
            <span class="${statusCls}">${statusLabel}</span>
            ${scoreBadge}${epBadge}${yearBadge}${fmtBadge}
          </div>
          ${airing}
        </div>
      </div>`;
        }).join('');
        _alStartCountdowns();

    } catch (e) {
        grid.innerHTML = `<div class="gl-msg"><div class="gl-msg-ico">❌</div>Xatolik: ${e.message}</div>`;
    } finally {
        btn.disabled = false;
    }
}

// Global sahifa ochilganda AniList statusini tekshir (showPage ichida handle qilinadi)

async function topbarLogout() { await fetch('/api/auth/logout', { method: 'POST', headers: _authHeaders() }).catch(() => { }); localStorage.removeItem('az_token'); localStorage.removeItem('az_user'); _gToken = ''; _gUser = null; _gGameId = null; _gState = null; _refreshTopbarAuth(); _refreshUserBadge(); if (document.getElementById('page-game').classList.contains('active')) { _renderLoginScreen(); } }
function _refreshTopbarAuth() { const loginBtn = document.getElementById('topbar-login-btn'), userDiv = document.getElementById('topbar-user'); if (!loginBtn || !userDiv) return; if (_gUser) { loginBtn.style.display = 'none'; userDiv.style.display = 'flex'; const av = document.getElementById('topbar-avatar'); if (av) { av.src = _gUser.picture || ''; av.style.display = _gUser.picture ? 'block' : 'none'; } const un = document.getElementById('topbar-uname'); if (un) un.textContent = _gUser.name || ''; } else { loginBtn.style.display = 'flex'; userDiv.style.display = 'none'; } }
(async function () { if (_gToken && !_gUser) { try { const res = await fetch('/api/auth/me', { headers: { 'Authorization': 'Bearer ' + _gToken } }); const d = await res.json(); if (d.ok) { _gUser = d.user; localStorage.setItem('az_user', JSON.stringify(_gUser)); _refreshUserBadge(); } else { localStorage.removeItem('az_token'); _gToken = ''; } } catch { } } _refreshTopbarAuth(); })();
async function gameLogout() { await fetch('/api/auth/logout', { method: 'POST', headers: _authHeaders() }).catch(() => { }); localStorage.removeItem('az_token'); localStorage.removeItem('az_user'); _gToken = ''; _gUser = null; _gGameId = null; _gState = null; _refreshUserBadge(); _refreshTopbarAuth(); if (document.getElementById('page-game').classList.contains('active')) { _renderLoginScreen(); } }

// ══ DEVICE ID — har qurilmaga unikal ══
function _getDeviceId() { let id = localStorage.getItem('az_device_id'); if (!id) { id = 'dev_' + Math.random().toString(36).slice(2) + Date.now().toString(36); localStorage.setItem('az_device_id', id); } return id; }
const _DEV = _getDeviceId();

// ══ DEVICE CACHE — animelar keshlash ══
const _CACHE_KEY = 'az_animes_cache_v2';
const _CACHE_TTL = 30 * 60 * 1000; // 30 daqiqa
function _saveAnimeCache(data) { try { localStorage.setItem(_CACHE_KEY, JSON.stringify({ ts: Date.now(), data })); } catch { } }
function _loadAnimeCache() { try { const c = JSON.parse(localStorage.getItem(_CACHE_KEY) || 'null'); if (c && Date.now() - c.ts < _CACHE_TTL) return c.data; } catch { } return null; }

// ══ SAVE / LIKE — localStorage per device ══
function _getLiked() { try { return JSON.parse(localStorage.getItem('az_liked_' + _DEV) || '[]'); } catch { return []; } }
function _getSaved() { try { return JSON.parse(localStorage.getItem('az_saved_' + _DEV) || '[]'); } catch { return []; } }
function _saveLiked(arr) { localStorage.setItem('az_liked_' + _DEV, JSON.stringify(arr)); }
function _saveSavedList(arr) { localStorage.setItem('az_saved_' + _DEV, JSON.stringify(arr)); }
function _isLiked(id) { return _getLiked().includes(id); }
function _isSaved(id) { return _getSaved().includes(id); }

function toggleLike(id) {
    let arr = _getLiked();
    if (arr.includes(id)) arr = arr.filter(x => x !== id); else arr.push(id);
    _saveLiked(arr);
    const btn = document.getElementById('like-' + id);
    if (btn) btn.classList.toggle('liked', arr.includes(id));
    // gallerydagi tugmani ham yangilaymiz
    const gbtn = document.getElementById('glike-' + id);
    if (gbtn) gbtn.classList.toggle('liked', arr.includes(id));
}
function toggleSave(id) {
    let arr = _getSaved();
    if (arr.includes(id)) arr = arr.filter(x => x !== id); else arr.push(id);
    _saveSavedList(arr);
    const btn = document.getElementById('save-' + id);
    if (btn) btn.classList.toggle('saved', arr.includes(id));
    const gbtn = document.getElementById('gsave-' + id);
    if (gbtn) gbtn.classList.toggle('saved', arr.includes(id));
    _syncSavedToTelegram(id, arr.includes(id));
}
function removeFromSaved(id) { let arr = _getSaved().filter(x => x !== id); _saveSavedList(arr); _syncSavedToTelegram(id, false); renderProfile(); }
function removeFromLiked(id) { let arr = _getLiked().filter(x => x !== id); _saveLiked(arr); renderProfile(); }

// ══ GALLERY ══
let _galFilter = 'all';
function renderGallery() {
    const g = document.getElementById('galGrid');
    if (!allAnimes.length && !g.querySelector('.gal-card')) {
        // Hali yuklanmagan
        g.innerHTML = '<div class="loading"><div class="spinner"></div>Yuklanmoqda...</div>';
        if (!allAnimes.length) { loadAnimes().then(() => renderGallery()); return; }
    }
    _renderGalGrid();
    // Filter buttonlar
    document.querySelectorAll('[data-gf]').forEach(b => {
        b.onclick = () => {
            document.querySelectorAll('[data-gf]').forEach(x => x.classList.remove('active'));
            b.classList.add('active');
            _galFilter = b.dataset.gf;
            _renderGalGrid();
        };
        b.classList.toggle('active', b.dataset.gf === _galFilter);
    });
}
function _renderGalGrid() {
    const g = document.getElementById('galGrid');
    let list = [...allAnimes];
    if (_galFilter === 'ongoing') list = list.filter(a => (a.aniType || '').toLowerCase().includes('ongoing'));
    else if (_galFilter === 'completed') list = list.filter(a => a.aniType && !a.aniType.toLowerCase().includes('ongoing'));
    else if (_galFilter === 'saved') { const ids = _getSaved(); list = list.filter(a => ids.includes(a.id)); }
    else if (_galFilter === 'liked') { const ids = _getLiked(); list = list.filter(a => ids.includes(a.id)); }
    if (!list.length) { g.innerHTML = '<div class="prof-empty" style="grid-column:1/-1">Hech narsa topilmadi 😔</div>'; return; }
    g.innerHTML = list.map(a => {
        const og = (a.aniType || '').toLowerCase().includes('ongoing');
        const badgeCls = og ? 'on' : 'fin'; const badgeTxt = og ? 'OnGoing' : 'Tugagan';
        const likedCls = _isLiked(a.id) ? 'liked' : '';
        const savedCls = _isSaved(a.id) ? 'saved' : '';
        return `<div class="gal-card" onclick="openModal(${a.id},this)">
      <img class="gal-img" src="${a.rams_url || ''}" loading="lazy" onerror="this.outerHTML='<div class=gal-img-ph>🎬</div>'">
      <span class="gal-badge ${badgeCls}">${badgeTxt}</span>
      <div class="gal-overlay">
        <div class="gal-title">${a.nom || 'Nomsiz'}</div>
        <div class="gal-actions">
          <button class="ga-btn ${likedCls}" id="glike-${a.id}" onclick="event.stopPropagation();toggleLike(${a.id})">❤️ Yoqtir</button>
          <button class="ga-btn ${savedCls}" id="gsave-${a.id}" onclick="event.stopPropagation();toggleSave(${a.id})">💾 Saqlash</button>
        </div>
      </div>
    </div>`;
    }).join('');
}

// ══ PROFILE ══
async function _fetchTelegramProfile() {
    try { const r = await fetch('/api/telegram/profile?device_id=' + encodeURIComponent(_DEV)); return await r.json(); } catch { return { ok: false, linked: false }; }
}
async function _syncSavedToTelegram(animeId, saved) {
    fetch('/api/profile/saved', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ device_id: _DEV, anime_id: animeId, saved }) }).catch(() => { });
}
async function startTelegramLink() {
    const input = document.getElementById('tg-link-id');
    const status = document.getElementById('tg-link-status');
    const telegramId = (input?.value || '').trim();
    if (!telegramId) { if (status) status.textContent = 'Telegram ID kiriting'; return; }
    if (status) status.textContent = 'Botga tasdiqlash xabari yuborilmoqda...';
    try {
        const res = await fetch('/api/telegram/link/start', { method: 'POST', headers: _authHeaders(), body: JSON.stringify({ device_id: _DEV, telegram_id: telegramId, saved_ids: _getSaved() }) });
        const d = await res.json();
        if (!d.ok) { if (status) status.textContent = '❌ ' + (d.error || 'Xatolik'); return; }
        if (status) status.textContent = 'Botdagi xabar ostidan Tasdiqlash tugmasini bosing...';
        pollTelegramLink(d.request_id);
    } catch { if (status) status.textContent = '❌ Serverga ulanib bo\'lmadi'; }
}
async function pollTelegramLink(requestId) {
    const status = document.getElementById('tg-link-status');
    for (let i = 0; i < 40; i++) {
        await new Promise(r => setTimeout(r, 2000));
        try {
            const res = await fetch(`/api/telegram/link/status?request_id=${encodeURIComponent(requestId)}&device_id=${encodeURIComponent(_DEV)}`);
            const d = await res.json();
            if (d.status === 'approved') { if (status) status.textContent = '✅ Telegram profil ulandi'; renderProfile(); return; }
            if (d.status === 'rejected') { if (status) status.textContent = '❌ So\'rov rad etildi'; return; }
        } catch { }
    }
    if (status) status.textContent = '⏳ Tasdiqlash kutilmoqda. Profilni qayta ochib tekshiring.';
}
function _telegramConnectBox() {
    return `<div class="prof-card" style="padding:18px">
    <div class="prof-sec-title">🔗 Telegram profilni ulash</div>
    <div class="prof-login-desc" style="max-width:none;text-align:left;margin-bottom:12px">Telegram ID kiriting. Bot sizga tasdiqlash xabari yuboradi.</div>
    <div style="display:flex;gap:8px;flex-wrap:wrap">
      <input id="tg-link-id" inputmode="numeric" placeholder="Telegram ID" style="flex:1;min-width:180px;padding:11px 13px;border-radius:10px;border:1px solid var(--border);background:var(--card-bg);color:var(--text)">
      <button class="prof-google-btn" onclick="startTelegramLink()" style="min-width:130px">Davom etish</button>
    </div>
    <div id="tg-link-status" style="font-size:.78rem;color:var(--muted);margin-top:10px"></div>
  </div>`;
}
async function _fetchSpotifyStatus() {
    if (!_gToken) return { ok: false, connected: false };
    try { const r = await fetch('/api/auth/spotify/status', { headers: _authHeaders() }); return await r.json(); } catch { return { ok: false, connected: false }; }
}
async function spotifyConnect() {
    if (!_gToken) { alert('Avval Google bilan kiring.'); return; }
    try {
        const res = await fetch('/api/auth/spotify', { headers: _authHeaders() });
        const d = await res.json();
        if (d.ok && d.url) { window.location.href = d.url; return; }
        alert(d.error || 'Spotify ulashda xatolik');
    } catch { alert('Serverga ulanib bo\'lmadi'); }
}
function _spotifyConnectBox(status) {
    const s = status?.spotify || {};
    if (status?.connected) {
        const av = s.image ? `<img class="prof-spotify-avatar" src="${s.image}" onerror="this.style.display='none'">` : '<div class="prof-spotify-avatar" style="background:#1ed760"></div>';
        const link = s.profile_url ? `<a class="prof-spotify-btn" href="${s.profile_url}" target="_blank" rel="noopener">Spotify profil</a>` : '';
        return `<div class="prof-card" style="padding:18px">
      <div class="prof-sec-title">Spotify ulangan</div>
      <div style="display:flex;align-items:center;gap:10px;margin:12px 0">
        ${av}
        <div>
          <div class="prof-name">${s.name || 'Spotify foydalanuvchi'}</div>
          <div class="prof-email">${s.email || s.country || ''}</div>
        </div>
      </div>
      ${link}
    </div>`;
    }
    return `<div class="prof-card" style="padding:18px">
    <div class="prof-sec-title">Spotify hisobini ulash</div>
    <div class="prof-login-desc" style="max-width:none;text-align:left;margin:12px 0">Spotify profilingizni web profilingizga bog'lang.</div>
    <button class="prof-spotify-btn" onclick="spotifyConnect()">Spotify bilan ulash</button>
  </div>`;
}
async function renderProfile() {
    const c = document.getElementById('profileContent');
    if (!c) return;
    c.innerHTML = '<div class="loading"><div class="spinner"></div>Profil yuklanmoqda...</div>';
    const tgProfile = await _fetchTelegramProfile();
    if (!_gUser && !tgProfile.linked) {
        const url = _getGoogleAuthUrl();
        c.innerHTML = `<div class="prof-login-wrap">
      <div class="prof-login-ico">👤</div>
      <div class="prof-login-title">Profilga kirish</div>
      <div class="prof-login-desc">Google hisobingiz bilan kiring. Saqlangan va yoqtirgan animelaringiz bu yerda saqlanadi.</div>
      <button class="prof-google-btn" onclick="window.location.href='${url}'">
        <svg viewBox="0 0 48 48"><path fill="#EA4335" d="M24 9.5c3.54 0 6.71 1.22 9.21 3.6l6.85-6.85C35.9 2.38 30.47 0 24 0 14.62 0 6.51 5.38 2.56 13.22l7.98 6.19C12.43 13.08 17.74 9.5 24 9.5z"/><path fill="#4285F4" d="M46.98 24.55c0-1.57-.15-3.09-.38-4.55H24v9.02h12.94c-.58 2.96-2.26 5.48-4.78 7.18l7.73 6c4.51-4.18 7.09-10.36 7.09-17.65z"/><path fill="#FBBC05" d="M10.53 28.59c-.48-1.45-.76-2.99-.76-4.59s.27-3.14.76-4.59l-7.98-6.19C.92 16.46 0 20.12 0 24c0 3.88.92 7.54 2.56 10.78l7.97-6.19z"/><path fill="#34A853" d="M24 48c6.48 0 11.93-2.13 15.89-5.81l-7.73-6c-2.18 1.48-4.97 2.31-8.16 2.31-6.26 0-11.57-3.59-13.46-8.78l-7.98 6.19C6.51 42.62 14.62 48 24 48z"/></svg>
        Google bilan kirish
      </button>
    </div>`;
        c.innerHTML += _telegramConnectBox();
        return;
    }
    if (tgProfile.linked && Array.isArray(tgProfile.watchlist)) {
        _saveSavedList(tgProfile.watchlist.map(Number));
    }
    const saved = _getSaved(); const liked = _getLiked();
    const savedAnimes = allAnimes.filter(a => saved.includes(a.id));
    const likedAnimes = allAnimes.filter(a => liked.includes(a.id));
    const displayUser = tgProfile.linked ? {
        name: tgProfile.telegram?.name || 'Telegram foydalanuvchi',
        email: (tgProfile.telegram?.username ? '@' + tgProfile.telegram.username : 'ID: ' + tgProfile.telegram?.id),
        picture: tgProfile.telegram?.photo_url || ''
    } : _gUser;
    const avatarEl = displayUser.picture ? `<img class="prof-av" src="${displayUser.picture}" onerror="this.outerHTML='<div class=prof-av-ph>👤</div>'">` : '<div class="prof-av-ph">👤</div>';
    const _animeItem = (a, rmFn) => `<div class="prof-anime-item" onclick="openModal(${a.id},this)">
    <img class="prof-anime-img" src="${a.rams_url || ''}" loading="lazy" onerror="this.style.display='none'">
    <div class="prof-anime-label">${a.nom || 'Nomsiz'}</div>
    <button class="prof-anime-rm" onclick="event.stopPropagation();${rmFn}(${a.id})" title="O'chirish">✕</button>
  </div>`;

    c.innerHTML = `<div class="profile-wrap">
    <div class="prof-card">
      <div class="prof-cover"><div class="prof-cover::after"></div></div>
      <div class="prof-av-wrap">${avatarEl}</div>
      <div class="prof-body">
        <div class="prof-name">${displayUser.name || 'Foydalanuvchi'}</div>
        <div class="prof-email">${displayUser.email || ''}</div>
        <div class="prof-stats-row">
          <div class="prof-stat"><div class="prof-stat-val">${savedAnimes.length}</div><div class="prof-stat-lbl">Saqlangan</div></div>
          <div class="prof-stat"><div class="prof-stat-val">${likedAnimes.length}</div><div class="prof-stat-lbl">Yoqtirilgan</div></div>
          <div class="prof-stat"><div class="prof-stat-val">${tgProfile.linked ? (tgProfile.bot_profile?.status || 'Oddiy') : allAnimes.length}</div><div class="prof-stat-lbl">${tgProfile.linked ? 'Bot holati' : 'Jami Anime'}</div></div>
        </div>
        ${_gUser ? '<button class="prof-logout-btn" onclick="topbarLogout();renderProfile()">🚪 Chiqish</button>' : ''}
      </div>
    </div>

    ${tgProfile.linked ? `<div class="prof-card">
      <div class="prof-sec-title"><img src="./Ai/Ai.png" alt="AI"> Bot profili</div>
      <div class="prof-stats-row">
        <div class="prof-stat"><div class="prof-stat-val">${tgProfile.bot_profile?.balance || 0}</div><div class="prof-stat-lbl">Hisob</div></div>
        <div class="prof-stat"><div class="prof-stat-val">${tgProfile.bot_profile?.cashback || 0}</div><div class="prof-stat-lbl">Cashback</div></div>
        <div class="prof-stat"><div class="prof-stat-val">${tgProfile.bot_profile?.referrals || 0}</div><div class="prof-stat-lbl">Referal</div></div>
      </div>
      <div class="prof-sec-title" style="margin-top:14px">▶️ Davom etish</div>
      <div class="prof-empty" style="text-align:left">${(tgProfile.progress || []).length ? tgProfile.progress.map(p => `${p.name || ('Anime #' + p.anime_id)} — ${p.last_episode}-qism`).join('<br>') : 'Hali ko\'rish tarixi yo\'q.'}</div>
    </div>`: _telegramConnectBox()}

    <div class="prof-card">
      <div class="prof-sec-title">💾 Saqlangan Animelar (${savedAnimes.length})</div>
      <div class="prof-anime-grid">${savedAnimes.length ? savedAnimes.map(a => _animeItem(a, 'removeFromSaved')).join('') : '<div class="prof-empty">Saqlangan anime yo\'q.<br>Kartada 💾 tugmasini bosing.</div>'}</div>
    </div>

    <div class="prof-card">
      <div class="prof-sec-title">❤️ Yoqtirilgan Animelar (${likedAnimes.length})</div>
      <div class="prof-anime-grid">${likedAnimes.length ? likedAnimes.map(a => _animeItem(a, 'removeFromLiked')).join('') : '<div class="prof-empty">Yoqtirilgan anime yo\'q.<br>Kartada ❤️ tugmasini bosing.</div>'}</div>
    </div>
  </div>`;
}

// ══ HERO + SPLASH BOTINFO ══
async function _loadBotInfo() {
    let BOT_UN = '{{BOT_USERNAME}}' || 'anime_uz_official_bot';
    let displayName = BOT_UN.replace(/_/g, ' ').toUpperCase().replace(' BOT', '');
    let botPhoto = '';
    try {
        const res = await fetch('/api/bot-info');
        const d = await res.json();
        if (d.ok) {
            BOT_UN = (d.username || BOT_UN || 'anime_uz_official_bot').replace(/^@/, '');
            displayName = (d.name || BOT_UN).replace(/_/g, ' ').toUpperCase().replace(' BOT', '');
            botPhoto = d.photo_url || '';
        }
    } catch { }
    const setLogo = (id, cls, sizeLetter) => {
        const el = document.getElementById(id); if (!el) return;
        if (botPhoto) { el.innerHTML = `<img src="${botPhoto}" alt="${displayName}" onerror="this.remove();this.parentElement.textContent='${sizeLetter}'">`; }
        else { el.textContent = sizeLetter; }
    };
    const setHeadImage = (selector, url) => {
        const el = document.querySelector(selector); if (el && url) el.setAttribute(selector.startsWith('link') ? 'href' : 'content', url);
    };
    if (botPhoto) {
        setHeadImage('link[rel="icon"]', botPhoto);
        setHeadImage('link[rel="apple-touch-icon"]', botPhoto);
        setHeadImage('meta[property="og:image"]', botPhoto);
        setHeadImage('meta[name="twitter:image"]', botPhoto);
    }
    // Splash update
    const sn = document.getElementById('splashBotName'); if (sn) sn.textContent = displayName;
    const su = document.getElementById('splashBotUser'); if (su) su.textContent = '@' + BOT_UN;
    setLogo('splashLogoEl', 'splash-logo-img', displayName[0] || 'A');
    // Hero update
    const hn = document.getElementById('heroBotName'); if (hn) hn.textContent = displayName;
    const hu = document.getElementById('heroBotUser'); if (hu) hu.textContent = '@' + BOT_UN;
    const tb = document.getElementById('heroTgBtn'); if (tb) tb.href = 'https://t.me/' + BOT_UN;
    setLogo('heroLogoEl', 'hero-logo-img', displayName[0] || 'A');
    // Sidebar
    const sbn = document.getElementById('sideBotName'); if (sbn) sbn.textContent = displayName.split(' ')[0];
    setLogo('sideLogoEl', 'sidebar-logo-img', displayName[0] || 'A');
    // stats
    try {
        const res = await fetch('/api/stats'); const d = await res.json();
        const hu2 = document.getElementById('heroUsers'); if (hu2) hu2.textContent = d.users?.toLocaleString() || '—';
        const ha = document.getElementById('heroAnimes'); if (ha) ha.textContent = d.animes?.toLocaleString() || '—';
        const ho = document.getElementById('heroOnline'); if (ho) { ho.textContent = '● Online'; ho.style.color = 'var(--green)'; }
    } catch { }
}

// ══ ANIME CACHE patching ══
async function loadAnimes() {
    // Cached version check
    const cached = _loadAnimeCache();
    if (cached && cached.length) {
        allAnimes = cached;
        const tcEl = document.getElementById('sideCount'); if (tcEl) tcEl.textContent = allAnimes.length;
        curFilter = S.def;
        document.querySelectorAll('.filter-btn').forEach(b => b.classList.toggle('active', b.dataset.filter === curFilter));
        applyFilter();
        // Background refresh
        _refreshAnimesFromServer();
        return;
    }
    await _refreshAnimesFromServer();
}
async function _refreshAnimesFromServer() {
    const g = document.getElementById('animeGrid');
    if (!allAnimes.length && g) g.innerHTML = '<div class="loading"><div class="spinner"></div>Yuklanmoqda...</div>';
    try {
        const res = await fetch('/api/animes');
        if (!res.ok) throw new Error('Server xatosi');
        const d = await res.json();
        allAnimes = d.animes || [];
        _saveAnimeCache(allAnimes);
    } catch {
        if (!allAnimes.length && g) g.innerHTML = '<div class="empty" style="grid-column:1/-1"><div class="empty-ico">⚠️</div><h3>Serverga ulanib bo\'lmadi</h3></div>';
        return;
    }
    const tcEl = document.getElementById('sideCount'); if (tcEl) tcEl.textContent = allAnimes.length;
    curFilter = S.def;
    document.querySelectorAll('.filter-btn').forEach(b => b.classList.toggle('active', b.dataset.filter === curFilter));
    applyFilter();
}

async function _openPosterRoute(id) {
    if (!id) return;
    let anime = allAnimes.find(a => a.id === id);
    if (!anime) {
        try {
            const res = await fetch(`/api/animes/${id}`);
            const d = await res.json();
            if (d.ok && d.anime) {
                anime = d.anime;
                allAnimes = [anime, ...allAnimes.filter(a => a.id !== id)];
                _saveAnimeCache(allAnimes);
            }
        } catch { }
    }
    if (!anime) return;
    showPage('animes', null);
    _openingPosterFromRoute = true;
    openModal(id, null, { skipHistory: true, skipFx: true });
    _openingPosterFromRoute = false;
}

// ══ SPLASH HIDE ══
function _hideSplash() { const s = document.getElementById('splash'); if (s) s.classList.add('hidden'); }
// 2.5 soniyadan keyin yoki animelar yuklangandan keyin
setTimeout(_hideSplash, 2500);

// ══ INIT ══
_loadBotInfo();
loadAnimes().then(() => { const id = _posterRouteId(); if (id) _openPosterRoute(id); });
if (location.hash === '#profile') {
    setTimeout(() => showPage('profile', null), 0);
}