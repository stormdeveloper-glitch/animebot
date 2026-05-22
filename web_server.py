from collections import deque
from datetime import datetime
import asyncio
import hashlib
import html
import os
import json
import secrets
import random
import time
import aiosqlite
import aiohttp
from aiohttp import web
from urllib.parse import urlencode, urlparse

from config import (
    DB_PATH, BOT_TOKEN, BOT_USERNAME,
    GOOGLE_CLIENT_ID, GOOGLE_CLIENT_SECRET, GOOGLE_REDIRECT_URI,
    SPOTIFY_CLIENT_ID, SPOTIFY_CLIENT_SECRET, SPOTIFY_REDIRECT_URI,
    ANILIST_CLIENT_ID, ANILIST_CLIENT_SECRET, ANILIST_REDIRECT_URI,
    AI_API_KEY, AI_BASE_URL, AI_MODEL,
    WEB_PUBLIC_ORIGIN, WEB_SESSION_TTL_HOURS,
    WEB_RATE_LIMIT_PER_MIN, WEB_API_RATE_LIMIT_PER_MIN,
    WEB_MEDIA_RATE_LIMIT_PER_MIN, WEB_MAX_CONCURRENT_REQUESTS,
    WEB_REQUEST_TIMEOUT_SECONDS,
)
from utils.ai_assistant import generate_anime_tavsif

WEBAPP_DIR = os.path.dirname(os.path.abspath(__file__))
WEB_ADMIN_MEDIA_CHAT_ID = os.getenv("WEB_ADMIN_MEDIA_CHAT_ID", os.getenv("SUPER_ADMIN_ID", "")).strip()
ADMIN_LOGIN = os.getenv("ADMIN_LOGIN", "").strip()
ADMIN_PASSWORD = os.getenv("ADMIN_PASSWORD", "").strip()
ADMIN_SESSION_COOKIE = "animeuz_admin_session"
ANILIST_GRAPHQL_URL = "https://graphql.anilist.co"
ANILIST_POSTER_QUERY = """
query ($search: String) {
  Media(search: $search, type: ANIME, sort: SEARCH_MATCH) {
    title { english romaji native }
    coverImage { extraLarge large medium }
  }
}
"""
ANILIST_POSTER_SEARCH_QUERY = """
query ($search: String) {
  Page(page: 1, perPage: 12) {
    media(search: $search, type: ANIME, sort: SEARCH_MATCH) {
      id
      title { english romaji native }
      coverImage { extraLarge large medium }
      startDate { year }
    }
  }
}
"""

# ─── Auth sessions: token -> {id, name, email, picture, created} ──
_sessions: dict = {}

# ─── Game sessions: game_id -> GameState ─────────────────────────
_games: dict = {}
_rate_limits: dict = {}
SESSION_TTL_SECONDS = max(1, WEB_SESSION_TTL_HOURS) * 3600
_global_request_semaphore = asyncio.Semaphore(max(1, WEB_MAX_CONCURRENT_REQUESTS))

_BLOCKED_PATH_PREFIXES = (
    "/.env", "/.git", "/wp-", "/wordpress", "/xmlrpc.php", "/phpmyadmin",
    "/adminer", "/vendor/phpunit", "/cgi-bin", "/server-status",
)
_BLOCKED_PATH_PARTS = ("../", "%2e%2e", "<script", "union%20select")


def _new_token() -> str:
    return secrets.token_urlsafe(32)


def _poster_url(anime_id, rams: str = "") -> str:
    version = hashlib.sha1((rams or "").encode("utf-8", "ignore")).hexdigest()[:10] if rams else "0"
    return f"/poster/{anime_id}?v={version}"


def _is_html_request(request: web.Request) -> bool:
    accept = request.headers.get("Accept", "").lower()
    return "text/html" in accept and "v" not in request.rel_url.query


def _client_ip(request: web.Request) -> str:
    forwarded = request.headers.get("X-Forwarded-For", "")
    if forwarded:
        return forwarded.split(",", 1)[0].strip()[:64]
    return (request.remote or "unknown")[:64]


def _check_rate_limit(request: web.Request, name: str, limit: int, window_seconds: int) -> bool:
    key = (name, _client_ip(request))
    now = time.time()
    hits = [ts for ts in _rate_limits.get(key, []) if now - ts < window_seconds]
    if len(hits) >= limit:
        _rate_limits[key] = hits
        return False
    hits.append(now)
    _rate_limits[key] = hits
    return True


def _rate_limit_response(window_seconds: int = 60) -> web.Response:
    return web.json_response(
        {"ok": False, "error": "Juda ko'p so'rov. Birozdan keyin qayta urinib ko'ring."},
        status=429,
        headers={"Retry-After": str(window_seconds)},
    )


def _is_suspicious_request(request: web.Request) -> bool:
    path = request.path.lower()
    raw_path = request.raw_path.lower()
    return (
        any(path.startswith(prefix) for prefix in _BLOCKED_PATH_PREFIXES)
        or any(part in raw_path for part in _BLOCKED_PATH_PARTS)
    )


def _cleanup_sessions() -> None:
    now = time.time()
    expired = []
    for token, user in _sessions.items():
        created_ts = float(user.get("created_ts") or 0)
        if not created_ts or now - created_ts > SESSION_TTL_SECONDS:
            expired.append(token)
    for token in expired:
        _sessions.pop(token, None)
        _anilist_tokens.pop(token, None)
        _spotify_tokens.pop(token, None)


def _bearer_token(request: web.Request) -> str:
    auth = request.headers.get("Authorization", "")
    if not auth.startswith("Bearer "):
        return ""
    return auth[7:].strip()


def _is_allowed_redirect_uri(redirect_uri: str) -> bool:
    if not redirect_uri:
        return False
    parsed = urlparse(redirect_uri)
    if parsed.scheme != "https" and parsed.hostname not in {"localhost", "127.0.0.1"}:
        return False
    allowed = {GOOGLE_REDIRECT_URI, f"{WEB_PUBLIC_ORIGIN}/callback" if WEB_PUBLIC_ORIGIN else ""}
    allowed = {u for u in allowed if u}
    return not allowed or redirect_uri in allowed


@web.middleware
async def traffic_guard_middleware(request: web.Request, handler):
    if _is_suspicious_request(request):
        return web.Response(status=404, text="Not found")

    path = request.path
    if path.startswith("/media/"):
        limit_name = "global_media"
        limit = max(1, WEB_MEDIA_RATE_LIMIT_PER_MIN)
    elif path.startswith("/api/"):
        limit_name = "global_api"
        limit = max(1, WEB_API_RATE_LIMIT_PER_MIN)
    else:
        limit_name = "global_web"
        limit = max(1, WEB_RATE_LIMIT_PER_MIN)

    if not _check_rate_limit(request, limit_name, limit, 60):
        return _rate_limit_response(60)

    if _global_request_semaphore.locked():
        return web.json_response(
            {"ok": False, "error": "Server band. Birozdan keyin urinib ko'ring."},
            status=503,
            headers={"Retry-After": "5"},
        )

    async with _global_request_semaphore:
        if path.startswith(("/media/", "/events")):
            return await handler(request)
        try:
            return await asyncio.wait_for(
                handler(request),
                timeout=max(1, WEB_REQUEST_TIMEOUT_SECONDS),
            )
        except asyncio.TimeoutError:
            return web.json_response({"ok": False, "error": "So'rov vaqti tugadi"}, status=504)


@web.middleware
async def security_headers_middleware(request: web.Request, handler):
    try:
        response = await handler(request)
    except web.HTTPException as ex:
        response = ex
    response.headers.setdefault("X-Content-Type-Options", "nosniff")
    response.headers.setdefault("X-Frame-Options", "DENY")
    response.headers.setdefault("Referrer-Policy", "no-referrer")
    response.headers.setdefault("Permissions-Policy", "camera=(), microphone=(), geolocation=()")
    if request.path in {"/", "/callback", "/callbackspotify", "/qollanma", "/privacy", "/terms"}:
        response.headers.setdefault("Cache-Control", "public, max-age=120")
    elif request.path == "/bot-icon" or request.path.startswith(("/poster/", "/api/media/")):
        response.headers.setdefault("Cache-Control", "public, max-age=1800")
    elif request.path.startswith("/api/"):
        response.headers.setdefault("Cache-Control", "no-store")
    if request.scheme == "https":
        response.headers.setdefault("Strict-Transport-Security", "max-age=31536000; includeSubDomains")
    return response


class GameState:
    """Anime Karta Jangi — Player vs CPU."""

    STATS = [
        {"key": "ep_count", "label": "Qismlar soni",   "icon": "🎬"},
        {"key": "qidiruv",  "label": "Ko'rilgan marta", "icon": "👁"},
        {"key": "yili",     "label": "Yili",             "icon": "📅"},
    ]

    def __init__(self, player_cards: list, cpu_cards: list, user: dict):
        self.player_cards  = player_cards   # list of anime dicts
        self.cpu_cards     = cpu_cards
        self.player_score  = 0
        self.cpu_score     = 0
        self.round         = 0
        self.total_rounds  = min(len(player_cards), len(cpu_cards))
        self.user          = user
        self.history       = []             # round results
        self.finished      = False
        self.winner        = None

    def current_cards(self):
        if self.round >= self.total_rounds:
            return None, None
        return self.player_cards[self.round], self.cpu_cards[self.round]

    def play_round(self, stat_key: str):
        if self.finished:
            return None
        pc, cc = self.current_cards()
        if pc is None:
            self.finished = True
            return None

        pv = int(pc.get(stat_key) or 0)
        cv = int(cc.get(stat_key) or 0)

        if pv > cv:
            result = "player"
            self.player_score += 1
        elif cv > pv:
            result = "cpu"
            self.cpu_score += 1
        else:
            result = "draw"

        stat_info = next((s for s in self.STATS if s["key"] == stat_key), {})
        self.history.append({
            "round":       self.round + 1,
            "stat_key":    stat_key,
            "stat_label":  stat_info.get("label", stat_key),
            "stat_icon":   stat_info.get("icon", ""),
            "player_val":  pv,
            "cpu_val":     cv,
            "player_card": pc,
            "cpu_card":    cc,
            "result":      result,
        })
        self.round += 1

        # Check finish
        need = (self.total_rounds // 2) + 1
        if self.player_score >= need:
            self.finished = True
            self.winner = "player"
        elif self.cpu_score >= need:
            self.finished = True
            self.winner = "cpu"
        elif self.round >= self.total_rounds:
            self.finished = True
            self.winner = "player" if self.player_score > self.cpu_score else (
                "cpu" if self.cpu_score > self.player_score else "draw"
            )
        return self.history[-1]

    def to_dict(self):
        pc, cc = self.current_cards()
        return {
            "round":        self.round,
            "total_rounds": self.total_rounds,
            "player_score": self.player_score,
            "cpu_score":    self.cpu_score,
            "player_card":  pc,
            "cpu_card":     cc,
            "stats":        self.STATS,
            "history":      self.history,
            "finished":     self.finished,
            "winner":       self.winner,
            "user":         self.user,
        }
WEB_PORT = int(os.getenv("PORT", os.getenv("WEB_PORT", 8080)))

# Cache: file_id -> {"url": ..., "type": "photo"|"video"}
_media_cache = {}
_bot_info_cache = {"ts": 0, "data": None}
WEB_ADMIN_TOKEN = os.getenv("WEB_ADMIN_TOKEN", "").strip()


async def resolve_file_id(file_id: str) -> dict:
    """file_id dan URL va turini aniqlaydi."""
    if file_id in _media_cache:
        return _media_cache[file_id]

    try:
        tg_url = f"https://api.telegram.org/bot{BOT_TOKEN}/getFile?file_id={file_id}"
        async with aiohttp.ClientSession() as session:
            async with session.get(tg_url) as resp:
                data = await resp.json()
                if data.get("ok"):
                    file_path = data["result"]["file_path"]
                    url = f"https://api.telegram.org/file/bot{BOT_TOKEN}/{file_path}"
                    fp_lower = file_path.lower()
                    if any(fp_lower.endswith(ext) for ext in [".mp4", ".mov", ".avi", ".mkv", ".webm"]):
                        media_type = "video"
                    elif any(fp_lower.endswith(ext) for ext in [".jpg", ".jpeg", ".png", ".webp", ".gif"]):
                        media_type = "photo"
                    elif "video" in file_path.lower() or "animations" in file_path.lower():
                        media_type = "video"
                    else:
                        media_type = "photo"
                    result = {"url": url, "type": media_type}
                    _media_cache[file_id] = result
                    return result
                else:
                    err_desc = data.get("description", "unknown")
                    too_big = "too big" in err_desc.lower()
                    print(f"[getFile] XATO — {err_desc} | file_id={file_id[:30]}...")
                    return {"url": None, "type": "video", "too_big": too_big}
    except Exception as e:
        print(f"[getFile] Exception: {e}")
    return {"url": None, "type": "photo"}


async def media_proxy(request):
    """Stream qilish — rasm yoki video. Range request qo'llab-quvvatlaydi."""
    file_id = request.match_info["file_id"]
    if file_id.startswith("http"):
        raise web.HTTPFound(file_id)

    info = await resolve_file_id(file_id)
    if not info["url"]:
        raise web.HTTPNotFound()

    try:
        # Range headerini Telegram CDN ga uzatamiz (video seek uchun muhim)
        req_headers = {}
        range_header = request.headers.get("Range")
        if range_header:
            req_headers["Range"] = range_header

        async with aiohttp.ClientSession() as session:
            async with session.get(info["url"], headers=req_headers) as tg_resp:
                content_type = tg_resp.headers.get("Content-Type", "application/octet-stream")
                content_length = tg_resp.headers.get("Content-Length")
                content_range = tg_resp.headers.get("Content-Range")

                # 206 Partial Content yoki 200 OK — Telegram javobiga qarab
                status = tg_resp.status

                headers = {
                    "Content-Type": content_type,
                    "Accept-Ranges": "bytes",
                    "Cache-Control": "public, max-age=3600",
                }
                if content_length:
                    headers["Content-Length"] = content_length
                if content_range:
                    headers["Content-Range"] = content_range

                response = web.StreamResponse(status=status, headers=headers)
                await response.prepare(request)
                async for chunk in tg_resp.content.iter_chunked(65536):
                    await response.write(chunk)
                await response.write_eof()
                return response
    except Exception as e:
        raise web.HTTPInternalServerError(reason=str(e))


async def anime_media_info(request):
    """
    /api/media/{anime_id} — animening rams turini qaytaradi:
    { "type": "photo"|"video", "url": "/media/{file_id}" }
    """
    anime_id = request.match_info["anime_id"]
    async with aiosqlite.connect(DB_PATH) as db:
        async with db.execute("SELECT rams FROM animelar WHERE id=?", (anime_id,)) as c:
            row = await c.fetchone()

    if not row or not row[0]:
        return web.json_response({"type": "none", "url": None})

    rams = row[0]

    # URL bo'lsa — turini extension dan aniqlaymiz
    if rams.startswith("http"):
        low = rams.lower()
        if any(low.endswith(e) for e in [".mp4", ".mov", ".avi", ".mkv", ".webm"]):
            return web.json_response({"type": "video", "url": rams})
        return web.json_response({"type": "photo", "url": rams})

    # file_id — Telegram dan aniqlaymiz
    info = await resolve_file_id(rams)
    return web.json_response({
        "type": info["type"],
        "url": f"/media/{rams}" if info["url"] else None
    })


async def api_animes(request):
    try:
        search = request.rel_url.query.get("q", "").strip()
        async with aiosqlite.connect(DB_PATH) as db:
            if search:
                words = search.split()
                conditions = " AND ".join(["LOWER(a.nom) LIKE ?" for _ in words])
                params = [f"%{w.lower()}%" for w in words]
                query = f"""
                    SELECT a.id, a.nom, a.janri, a.rams, a.aniType, a.qismi,
                           a.fandub, a.yili, a.davlat, a.qidiruv,
                           COALESCE(a.liklar,0), COALESCE(a.desliklar,0),
                           COUNT(d.data_id) as ep_count, a.yosh_toifa,
                           COALESCE(a.tavsif,'') as tavsif
                    FROM animelar a
                    LEFT JOIN anime_datas d ON d.id = a.id
                    WHERE {conditions}
                    GROUP BY a.id ORDER BY a.qidiruv DESC LIMIT 200
                """
            else:
                params = []
                query = """
                    SELECT a.id, a.nom, a.janri, a.rams, a.aniType, a.qismi,
                           a.fandub, a.yili, a.davlat, a.qidiruv,
                           COALESCE(a.liklar,0), COALESCE(a.desliklar,0),
                           COUNT(d.data_id) as ep_count, a.yosh_toifa,
                           COALESCE(a.tavsif,'') as tavsif
                    FROM animelar a
                    LEFT JOIN anime_datas d ON d.id = a.id
                    GROUP BY a.id ORDER BY a.id DESC LIMIT 500
                """
            async with db.execute(query, params) as cursor:
                rows = await cursor.fetchall()

        animes = []
        for row in rows:
            rams = row[3] or ""
            animes.append({
                "id":        row[0],
                "nom":       row[1],
                "janri":     row[2],
                "rams_url":  _poster_url(row[0], rams),
                "rams_type": "unknown",
                "rams_id":   rams if not rams.startswith("http") else None,
                "aniType":   row[4] or "OnGoing",
                "fandub":    row[6],
                "yili":      row[7],
                "davlat":    row[8],
                "qidiruv":   row[9] or 0,
                "liklar":    row[10] or 0,
                "ep_count":  row[12] or 0,
                "yosh_toifa": row[13] or "Barcha yoshlar",
                "tavsif":    row[14] or "",
                "poster_page_url": f"/poster/{row[0]}",
            })
        return web.json_response({"animes": animes, "total": len(animes)})
    except Exception:
        return web.json_response({"animes": [], "total": 0, "error": "Server xatosi"}, status=200)


async def api_anime_detail(request):
    anime_id = request.match_info["anime_id"]
    async with aiosqlite.connect(DB_PATH) as db:
        async with db.execute("""
            SELECT a.id, a.nom, a.janri, a.rams, a.aniType, a.qismi,
                   a.fandub, a.yili, a.davlat, a.qidiruv,
                   COALESCE(a.liklar,0), COALESCE(a.desliklar,0),
                   COUNT(d.data_id) as ep_count, a.yosh_toifa,
                   COALESCE(a.tavsif,'') as tavsif
            FROM animelar a
            LEFT JOIN anime_datas d ON d.id = a.id
            WHERE a.id = ?
            GROUP BY a.id
        """, (anime_id,)) as c:
            row = await c.fetchone()
    if not row:
        return web.json_response({"ok": False, "error": "Anime topilmadi"}, status=404)

    rams = row[3] or ""
    return web.json_response({
        "ok": True,
        "anime": {
            "id": row[0],
            "nom": row[1],
            "janri": row[2],
            "rams_url": _poster_url(row[0], rams),
            "rams_type": "unknown",
            "rams_id": rams if not rams.startswith("http") else None,
            "aniType": row[4] or "OnGoing",
            "qismi": row[5],
            "fandub": row[6],
            "yili": row[7],
            "davlat": row[8],
            "qidiruv": row[9] or 0,
            "liklar": row[10] or 0,
            "desliklar": row[11] or 0,
            "ep_count": row[12] or 0,
            "yosh_toifa": row[13] or "Barcha yoshlar",
            "tavsif": row[14] or "",
            "poster_page_url": f"/poster/{row[0]}",
        },
    })


async def api_episode_preview(request):
    anime_id = request.match_info["anime_id"]
    async with aiosqlite.connect(DB_PATH) as db:
        async with db.execute(
            "SELECT file_id FROM anime_datas WHERE id=? ORDER BY qism ASC LIMIT 1",
            (anime_id,)
        ) as c:
            row = await c.fetchone()
    if not row:
        return web.json_response({"error": "topilmadi"}, status=404)
    return web.json_response({"video_url": f"/media/{row[0]}"})


async def api_episodes(request):
    """Anime barcha qismlari ro'yxatini qaytaradi."""
    anime_id = request.match_info["anime_id"]
    async with aiosqlite.connect(DB_PATH) as db:
        async with db.execute(
            "SELECT data_id, qism, file_id FROM anime_datas WHERE id=? ORDER BY qism ASC",
            (anime_id,)
        ) as c:
            rows = await c.fetchall()
    if not rows:
        return web.json_response({"episodes": [], "total": 0})

    episodes = []
    for r in rows:
        info = await resolve_file_id(r[2])
        episodes.append({
            "data_id": r[0],
            "qism": r[1],
            "video_url": f"/media/{r[2]}" if info.get("url") else None,
            "too_big": info.get("too_big", False),
        })
    return web.json_response({"episodes": episodes, "total": len(episodes)})


async def _poster_page(request: web.Request, anime_id: str) -> web.Response:
    async with aiosqlite.connect(DB_PATH) as db:
        async with db.execute("""
            SELECT a.id, a.nom, a.janri, a.rams, a.aniType, a.yili,
                   COUNT(d.data_id) as ep_count, COALESCE(a.tavsif,'') as tavsif
            FROM animelar a
            LEFT JOIN anime_datas d ON d.id = a.id
            WHERE a.id=?
            GROUP BY a.id
        """, (anime_id,)) as c:
            row = await c.fetchone()
    if not row:
        raise web.HTTPNotFound()

    origin = WEB_PUBLIC_ORIGIN or f"{request.scheme}://{request.host}"
    description_parts = [
        row[2] or "",
        f"{row[6] or 0} qism",
        str(row[5] or ""),
        row[4] or "",
    ]
    description = " | ".join([p for p in description_parts if p])
    if row[7]:
        description = row[7][:160]
    return await index(request, {
        "title": f"{row[1]} | AnimeUZ",
        "description": description,
        "image": f"{origin}{_poster_url(row[0], row[3] or '')}",
        "url": f"{origin}/poster/{row[0]}",
    })


async def anime_poster(request):
    """Browser uchun poster sahifasi, image request uchun poster rasmi."""
    anime_id = request.match_info["anime_id"]
    if _is_html_request(request):
        return await _poster_page(request, anime_id)

    async with aiosqlite.connect(DB_PATH) as db:
        async with db.execute("SELECT rams FROM animelar WHERE id=?", (anime_id,)) as c:
            row = await c.fetchone()
    if not row or not row[0]:
        raise web.HTTPNotFound()
    rams = row[0]
    if rams.startswith("http"):
        raise web.HTTPFound(rams)
    info = await resolve_file_id(rams)
    if info["url"]:
        raise web.HTTPFound(f"/media/{rams}")
    raise web.HTTPNotFound()


async def api_bot_info(request):
    """Bot nomi, username va Telegram profil rasmini qaytaradi."""
    return web.json_response(await get_bot_info())


async def get_bot_info() -> dict:
    """Bot nomi, username va Telegram profil rasmini cache bilan oladi."""
    now = time.time()
    cached = _bot_info_cache.get("data")
    if cached and now - float(_bot_info_cache.get("ts") or 0) < 1800:
        return dict(cached)

    fallback_username = (BOT_USERNAME or "").lstrip("@")
    result = {
        "ok": True,
        "id": None,
        "name": fallback_username.replace("_", " ").title() or "AnimeUZ",
        "username": fallback_username,
        "photo_url": "",
        "photo_file_id": "",
    }
    if not BOT_TOKEN:
        _bot_info_cache.update({"ts": now, "data": dict(result)})
        return result

    async with aiohttp.ClientSession() as session:
        try:
            async with session.get(f"https://api.telegram.org/bot{BOT_TOKEN}/getMe") as resp:
                data = await resp.json()
            if data.get("ok"):
                me = data.get("result", {})
                result["id"] = me.get("id")
                result["name"] = me.get("first_name") or result["name"]
                result["username"] = me.get("username") or result["username"]
        except Exception:
            pass

        bot_id = result.get("id")
        if bot_id:
            try:
                async with session.get(
                    f"https://api.telegram.org/bot{BOT_TOKEN}/getUserProfilePhotos",
                    params={"user_id": bot_id, "limit": 1},
                ) as resp:
                    photo_data = await resp.json()
                photos = photo_data.get("result", {}).get("photos", []) if photo_data.get("ok") else []
                if photos and photos[0]:
                    file_id = photos[0][-1].get("file_id", "")
                    if file_id:
                        result["photo_file_id"] = file_id
                        result["photo_url"] = f"/media/{file_id}"
            except Exception:
                pass

    _bot_info_cache.update({"ts": now, "data": dict(result)})
    return result


async def bot_icon(request):
    """Sayt favicon/preview rasmi uchun bot profil rasmini qaytaradi."""
    info = await get_bot_info()
    if info.get("photo_file_id"):
        raise web.HTTPFound(f"/media/{info['photo_file_id']}")
    svg = """<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 128 128">
<rect width="128" height="128" rx="28" fill="#6c63ff"/>
<text x="64" y="78" text-anchor="middle" font-family="Arial, sans-serif" font-size="54" font-weight="700" fill="#fff">A</text>
</svg>"""
    return web.Response(
        text=svg,
        content_type="image/svg+xml",
        headers={"Cache-Control": "public, max-age=1800"},
    )


async def index(request, meta: dict | None = None):
    html_path = os.path.join(WEBAPP_DIR, "index.html")
    with open(html_path, "r", encoding="utf-8") as f:
        html = f.read()
    # Dinamik qiymatlarni inject qilamiz
    html = html.replace("{{BOT_USERNAME}}", BOT_USERNAME or "")
    html = html.replace("{{GOOGLE_CLIENT_ID}}", GOOGLE_CLIENT_ID or "")
    if meta:
        import html as html_module

        title = html_module.escape(meta.get("title") or "AnimeUZ Official", quote=True)
        description = html_module.escape(meta.get("description") or "Anime poster va ma'lumotlari", quote=True)
        image = html_module.escape(meta.get("image") or "/bot-icon", quote=True)
        url = html_module.escape(meta.get("url") or request.url.human_repr(), quote=True)
        html = html.replace("<title>AnimeUZ Official</title>", f"<title>{title}</title>")
        html = html.replace(
            '<meta property="og:image" content="/bot-icon">',
            (
                f'<meta property="og:title" content="{title}">\n'
                f'<meta property="og:description" content="{description}">\n'
                f'<meta property="og:url" content="{url}">\n'
                f'<meta property="og:image" content="{image}">'
            ),
        )
        html = html.replace(
            '<meta name="twitter:image" content="/bot-icon">',
            (
                '<meta name="twitter:card" content="summary_large_image">\n'
                f'<meta name="twitter:title" content="{title}">\n'
                f'<meta name="twitter:description" content="{description}">\n'
                f'<meta name="twitter:image" content="{image}">'
            ),
        )
    return web.Response(text=html, content_type="text/html", charset="utf-8")


async def api_admins(request):
    """Adminlar ro'yxatini Telegram API dan oladi — config + DB admins jadvali."""
    from config import ADMIN_IDS, SUPER_ADMIN_ID

    # Config dan
    config_ids = set([SUPER_ADMIN_ID] + ADMIN_IDS)

    # DB dagi qo'shilgan adminlar
    async with aiosqlite.connect(DB_PATH) as db:
        async with db.execute("SELECT user_id FROM admins") as c:
            rows = await c.fetchall()
    db_ids = {r[0] for r in rows}

    # Hammasini birlashtirish
    all_ids = list(config_ids | db_ids)
    all_ids = [uid for uid in all_ids if uid]

    admins = []
    async with aiohttp.ClientSession() as session:
        for uid in all_ids:
            if not uid: continue
            try:
                url = f"https://api.telegram.org/bot{BOT_TOKEN}/getChat?chat_id={uid}"
                async with session.get(url) as r:
                    data = await r.json()
                if not data.get("ok"): continue
                user = data["result"]

                photo_url = None
                ph_url = f"https://api.telegram.org/bot{BOT_TOKEN}/getUserProfilePhotos?user_id={uid}&limit=1"
                async with session.get(ph_url) as r2:
                    ph_data = await r2.json()
                if ph_data.get("ok") and ph_data["result"]["total_count"] > 0:
                    file_id = ph_data["result"]["photos"][0][-1]["file_id"]
                    photo_url = f"/media/{file_id}"

                username = user.get("username", "")
                link = f"https://t.me/{username}" if username else f"tg://user?id={uid}"
                fname = user.get("first_name", "")
                lname = user.get("last_name", "")
                full_name = (fname + " " + lname).strip()

                admins.append({
                    "id": uid,
                    "name": full_name or f"User {uid}",
                    "username": f"@{username}" if username else f"ID: {uid}",
                    "link": link,
                    "photo": photo_url,
                    "is_super": uid == SUPER_ADMIN_ID,
                })
            except Exception:
                continue

    admins.sort(key=lambda x: (0 if x["is_super"] else 1))
    return web.json_response({"admins": admins})


import asyncio
import json
from collections import deque
from datetime import datetime

# ─── SSE Event Bus ────────────────────────────────────────────────────────────
# Oxirgi 50 ta hodisani saqlaymiz
_event_history = deque(maxlen=50)
# Barcha ulanib turgan SSE clientlar
_sse_clients: list = []


def _ts():
    return datetime.now().strftime("%H:%M")


async def push_event(event_type: str, text: str, color: str = "c"):
    """
    Barcha SSE clientlarga hodisa yuboradi.
    color: c=cyan, p=pink, g=gold, gr=green
    """
    data = {"type": event_type, "text": text, "color": color, "time": _ts()}
    _event_history.append(data)
    dead = []
    for q in _sse_clients:
        try:
            await q.put(data)
        except Exception:
            dead.append(q)
    for q in dead:
        try:
            _sse_clients.remove(q)
        except ValueError:
            pass


async def sse_stream(request):
    """SSE endpoint — browser shu yerga ulanadi."""
    resp = web.StreamResponse(headers={
        "Content-Type": "text/event-stream",
        "Cache-Control": "no-cache",
        "X-Accel-Buffering": "no",
        "Access-Control-Allow-Origin": "*",
    })
    await resp.prepare(request)

    q: asyncio.Queue = asyncio.Queue()
    _sse_clients.append(q)

    # Oxirgi 10 ta tarixiy hodisani darhol yuboramiz
    for ev in list(_event_history)[-10:]:
        msg = f"data: {json.dumps(ev)}\n\n"
        try:
            await resp.write(msg.encode())
        except Exception:
            break

    try:
        while True:
            try:
                ev = await asyncio.wait_for(q.get(), timeout=25)
                msg = f"data: {json.dumps(ev)}\n\n"
                await resp.write(msg.encode())
            except asyncio.TimeoutError:
                # Keep-alive ping
                await resp.write(b": ping\n\n")
    except (ConnectionResetError, Exception):
        pass
    finally:
        try:
            _sse_clients.remove(q)
        except ValueError:
            pass
    return resp


async def api_stats(request):
    """Dashboard uchun umumiy statistika."""
    async with aiosqlite.connect(DB_PATH) as db:
        async with db.execute("SELECT COUNT(*) FROM users") as c:
            users = (await c.fetchone())[0]
        async with db.execute("SELECT COUNT(*) FROM vip_status") as c:
            vip = (await c.fetchone())[0]
        async with db.execute("SELECT COUNT(*) FROM animelar") as c:
            animes = (await c.fetchone())[0]
        async with db.execute("SELECT COUNT(*) FROM anime_datas") as c:
            eps = (await c.fetchone())[0]
    return web.json_response({"users": users, "vip": vip, "animes": animes, "eps": eps})


def _admin_authorized(request: web.Request) -> bool:
    session_secret = WEB_ADMIN_TOKEN or ADMIN_PASSWORD
    session_token = request.cookies.get(ADMIN_SESSION_COOKIE, "").strip()
    if session_secret and secrets.compare_digest(session_token, session_secret):
        return True
    if WEB_ADMIN_TOKEN:
        token = (
            request.headers.get("X-Admin-Token", "")
            or request.cookies.get("admin_token", "")
        ).strip()
        return secrets.compare_digest(token, WEB_ADMIN_TOKEN)
    return False


def _admin_denied() -> web.Response:
    return web.json_response({"ok": False, "error": "Admin token noto'g'ri yoki kiritilmagan"}, status=401)


def _clean_text(value, default: str = "") -> str:
    return str(value if value is not None else default).strip()


async def _fetch_anilist_poster(search_title: str) -> dict:
    search_title = _clean_text(search_title)
    if not search_title:
        return {}
    try:
        async with aiohttp.ClientSession() as session:
            async with session.post(
                ANILIST_GRAPHQL_URL,
                json={"query": ANILIST_POSTER_QUERY, "variables": {"search": search_title}},
                headers={"Content-Type": "application/json", "Accept": "application/json"},
                timeout=aiohttp.ClientTimeout(total=12),
            ) as resp:
                data = await resp.json()
        media = data.get("data", {}).get("Media") or {}
        cover = media.get("coverImage") or {}
        title = media.get("title") or {}
        poster_url = cover.get("extraLarge") or cover.get("large") or cover.get("medium") or ""
        matched_title = title.get("english") or title.get("romaji") or title.get("native") or search_title
        return {"poster_url": poster_url, "matched_title": matched_title} if poster_url else {}
    except Exception:
        return {}


async def _search_anilist_posters(search_title: str) -> list[dict]:
    search_title = _clean_text(search_title)
    if not search_title:
        return []
    try:
        async with aiohttp.ClientSession() as session:
            async with session.post(
                ANILIST_GRAPHQL_URL,
                json={"query": ANILIST_POSTER_SEARCH_QUERY, "variables": {"search": search_title}},
                headers={"Content-Type": "application/json", "Accept": "application/json"},
                timeout=aiohttp.ClientTimeout(total=12),
            ) as resp:
                data = await resp.json()
        rows = data.get("data", {}).get("Page", {}).get("media", []) or []
        results = []
        for item in rows:
            title = item.get("title") or {}
            cover = item.get("coverImage") or {}
            poster_url = cover.get("extraLarge") or cover.get("large") or cover.get("medium") or ""
            name = title.get("english") or title.get("romaji") or title.get("native") or ""
            if poster_url and name:
                results.append({
                    "id": item.get("id"),
                    "title": name,
                    "english": title.get("english") or "",
                    "romaji": title.get("romaji") or "",
                    "native": title.get("native") or "",
                    "year": (item.get("startDate") or {}).get("year") or "",
                    "poster_url": poster_url,
                })
        return results
    except Exception:
        return []


async def _telegram_photo_file_id(photo_url: str, anime_name: str = "") -> str:
    if not BOT_TOKEN or not WEB_ADMIN_MEDIA_CHAT_ID or not photo_url:
        return ""
    message_id = None
    try:
        async with aiohttp.ClientSession() as session:
            async with session.post(
                f"https://api.telegram.org/bot{BOT_TOKEN}/sendPhoto",
                json={
                    "chat_id": WEB_ADMIN_MEDIA_CHAT_ID,
                    "photo": photo_url,
                    "disable_notification": True,
                },
                timeout=aiohttp.ClientTimeout(total=20),
            ) as resp:
                data = await resp.json()
        message_id = data.get("result", {}).get("message_id") if data.get("ok") else None
        photos = data.get("result", {}).get("photo", []) if data.get("ok") else []
        if photos:
            return photos[-1].get("file_id", "")
    except Exception:
        return ""
    finally:
        if message_id:
            try:
                async with aiohttp.ClientSession() as session:
                    await session.post(
                        f"https://api.telegram.org/bot{BOT_TOKEN}/deleteMessage",
                        json={"chat_id": WEB_ADMIN_MEDIA_CHAT_ID, "message_id": message_id},
                        timeout=aiohttp.ClientTimeout(total=8),
                    )
            except Exception:
                pass
    return ""


async def _prepare_admin_anime_payload(body: dict, *, existing_rams: str = "") -> tuple[dict, dict]:
    selected_poster_url = _clean_text(body.get("poster_url"))
    values = {
        "nom": _clean_text(body.get("nom")),
        "nom_en": _clean_text(body.get("nom_en")),
        "rams": _clean_text(body.get("rams"), existing_rams),
        "qismi": _clean_text(body.get("qismi"), "0") or "0",
        "davlat": _clean_text(body.get("davlat"), "Yaponiya") or "Yaponiya",
        "tili": _clean_text(body.get("tili"), "O'zbek") or "O'zbek",
        "yili": _clean_text(body.get("yili")),
        "janri": _clean_text(body.get("janri")),
        "aniType": _clean_text(body.get("aniType"), "OnGoing") or "OnGoing",
        "fandub": _clean_text(body.get("fandub")),
        "kanal": _clean_text(body.get("kanal")),
        "yosh_toifa": _clean_text(body.get("yosh_toifa"), "Barcha yoshlar") or "Barcha yoshlar",
        "tavsif": _clean_text(body.get("tavsif")),
    }
    meta = {"poster_source": "manual" if values["rams"] else "", "poster_url": "", "poster_file_id": ""}
    if not values["nom"]:
        raise ValueError("Anime nomi majburiy")

    if selected_poster_url:
        file_id = await _telegram_photo_file_id(selected_poster_url, values["nom"])
        values["rams"] = file_id or selected_poster_url
        meta.update({
            "poster_source": "selected_telegram" if file_id else "selected_url",
            "poster_url": selected_poster_url,
            "poster_file_id": file_id,
        })

    if not values["rams"]:
        poster = await _fetch_anilist_poster(values["nom_en"] or values["nom"])
        poster_url = poster.get("poster_url", "")
        if poster.get("matched_title") and not values["nom_en"]:
            values["nom_en"] = poster["matched_title"]
        if poster_url:
            file_id = await _telegram_photo_file_id(poster_url, values["nom"])
            values["rams"] = file_id or poster_url
            meta.update({
                "poster_source": "anilist_telegram" if file_id else "anilist_url",
                "poster_url": poster_url,
                "poster_file_id": file_id,
            })

    if not values["rams"]:
        raise ValueError("Poster topilmadi. Inglizcha nomini aniqroq kiriting yoki rams/file_id qo'lda kiriting.")

    if not values["tavsif"]:
        values["tavsif"] = await generate_anime_tavsif(
            values["nom"],
            janr=values["janri"],
            holat=values["aniType"],
            qism=values["qismi"],
            yil=values["yili"],
            til=values["tili"],
            davlat=values["davlat"],
        )
        meta["tavsif_source"] = "ai" if values["tavsif"] else "empty"
    else:
        meta["tavsif_source"] = "manual"

    return values, meta


def _bot_start_link(payload: str) -> str:
    bot_username = (BOT_USERNAME or "").lstrip("@")
    return f"https://t.me/{bot_username}?start={payload}" if bot_username else ""


async def serve_admin(request):
    path = os.path.join(WEBAPP_DIR, "admin.html")
    with open(path, "r", encoding="utf-8") as f:
        page = f.read()
    page = page.replace("{{ADMIN_ACCESS}}", "1" if _admin_authorized(request) else "0")
    return web.Response(text=page, content_type="text/html", charset="utf-8")


async def api_admin_stats(request):
    if not _admin_authorized(request):
        return _admin_denied()
    async with aiosqlite.connect(DB_PATH) as db:
        async with db.execute("SELECT COUNT(*) FROM users") as c:
            users = (await c.fetchone())[0]
        async with db.execute("SELECT COUNT(*) FROM vip_status") as c:
            vip = (await c.fetchone())[0]
        async with db.execute("SELECT COUNT(*) FROM animelar") as c:
            animes = (await c.fetchone())[0]
        async with db.execute("SELECT COUNT(*) FROM anime_datas") as c:
            eps = (await c.fetchone())[0]
    return web.json_response({"ok": True, "users": users, "vip": vip, "animes": animes, "eps": eps, "auth_configured": bool(WEB_ADMIN_TOKEN)})


async def api_admin_animes(request):
    if not _admin_authorized(request):
        return _admin_denied()
    search = request.rel_url.query.get("q", "").strip()
    params = []
    where = ""
    if search:
        where = "WHERE LOWER(a.nom) LIKE ? OR LOWER(COALESCE(a.nom_en,'')) LIKE ?"
        params = [f"%{search.lower()}%", f"%{search.lower()}%"]
    query = f"""
        SELECT a.id, a.nom, a.rams, a.qismi, a.davlat, a.tili, a.yili, a.janri,
               COALESCE(a.qidiruv,0), a.sana, a.aniType, a.fandub, a.kanal,
               COALESCE(a.liklar,0), COALESCE(a.desliklar,0), a.tavsif, a.nom_en,
               COALESCE(a.yosh_toifa,'Barcha yoshlar'), COALESCE(a.season_group_id,a.id),
               COALESCE(a.season_number,1), COUNT(d.data_id) as ep_count
        FROM animelar a
        LEFT JOIN anime_datas d ON d.id=a.id
        {where}
        GROUP BY a.id
        ORDER BY a.id DESC
        LIMIT 300
    """
    async with aiosqlite.connect(DB_PATH) as db:
        async with db.execute(query, params) as c:
            rows = await c.fetchall()
    keys = [
        "id", "nom", "rams", "qismi", "davlat", "tili", "yili", "janri",
        "qidiruv", "sana", "aniType", "fandub", "kanal", "liklar", "desliklar",
        "tavsif", "nom_en", "yosh_toifa", "season_group_id", "season_number", "ep_count"
    ]
    animes = []
    for row in rows:
        item = dict(zip(keys, row))
        item["rams_url"] = _poster_url(item["id"], item.get("rams") or "") if item.get("rams") else ""
        item["add_episode_url"] = _bot_start_link(f"add_ep_{item['id']}")
        animes.append(item)
    return web.json_response({"ok": True, "animes": animes})


async def api_admin_anilist_posters(request):
    if not _admin_authorized(request):
        return _admin_denied()
    q = request.rel_url.query.get("q", "").strip()
    if not q:
        return web.json_response({"ok": False, "error": "Qidirish nomi kerak"}, status=400)
    posters = await _search_anilist_posters(q)
    return web.json_response({"ok": True, "posters": posters})


async def api_admin_create_anime(request):
    if not _admin_authorized(request):
        return _admin_denied()
    body = await request.json()
    try:
        values, meta = await _prepare_admin_anime_payload(body)
    except ValueError as exc:
        return web.json_response({"ok": False, "error": str(exc)}, status=400)
    sana = datetime.now().strftime("%H:%M %d.%m.%Y")
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute("""
            INSERT INTO animelar (
                nom, rams, qismi, davlat, tili, yili, janri, qidiruv, sana,
                aniType, fandub, kanal, yosh_toifa, tavsif, nom_en
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, 0, ?, ?, ?, ?, ?, ?, ?)
        """, (
            values["nom"], values["rams"], values["qismi"], values["davlat"], values["tili"],
            values["yili"], values["janri"], sana, values["aniType"], values["fandub"],
            values["kanal"], values["yosh_toifa"], values["tavsif"], values["nom_en"],
        ))
        await db.commit()
        async with db.execute("SELECT last_insert_rowid()") as c:
            anime_id = (await c.fetchone())[0]
        await db.execute("UPDATE animelar SET season_group_id=?, season_number=1 WHERE id=?", (anime_id, anime_id))
        await db.commit()
    return web.json_response({"ok": True, "id": anime_id, "meta": meta, "add_episode_url": _bot_start_link(f"add_ep_{anime_id}")})


async def api_admin_update_anime(request):
    if not _admin_authorized(request):
        return _admin_denied()
    anime_id = int(request.match_info["anime_id"])
    body = await request.json()
    async with aiosqlite.connect(DB_PATH) as db:
        async with db.execute("SELECT rams FROM animelar WHERE id=?", (anime_id,)) as c:
            row = await c.fetchone()
    if not row:
        return web.json_response({"ok": False, "error": "Anime topilmadi"}, status=404)
    try:
        values, meta = await _prepare_admin_anime_payload(body, existing_rams=row[0] or "")
    except ValueError as exc:
        return web.json_response({"ok": False, "error": str(exc)}, status=400)
    set_sql = ", ".join([f"{key}=?" for key in values])
    params = list(values.values()) + [anime_id]
    async with aiosqlite.connect(DB_PATH) as db:
        cur = await db.execute(f"UPDATE animelar SET {set_sql} WHERE id=?", params)
        await db.commit()
    if cur.rowcount == 0:
        return web.json_response({"ok": False, "error": "Anime topilmadi"}, status=404)
    return web.json_response({"ok": True, "id": anime_id, "meta": meta, "add_episode_url": _bot_start_link(f"add_ep_{anime_id}")})


async def api_admin_delete_anime(request):
    if not _admin_authorized(request):
        return _admin_denied()
    anime_id = int(request.match_info["anime_id"])
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute("DELETE FROM anime_datas WHERE id=?", (anime_id,))
        cur = await db.execute("DELETE FROM animelar WHERE id=?", (anime_id,))
        await db.commit()
    if cur.rowcount == 0:
        return web.json_response({"ok": False, "error": "Anime topilmadi"}, status=404)
    return web.json_response({"ok": True})


async def api_admin_users(request):
    if not _admin_authorized(request):
        return _admin_denied()
    async with aiosqlite.connect(DB_PATH) as db:
        async with db.execute("""
            SELECT user_id, status, pul, pul2, odam, ban
            FROM users
            ORDER BY joined_at DESC
            LIMIT 200
        """) as c:
            rows = await c.fetchall()
    users = [
        {"user_id": r[0], "status": r[1], "pul": r[2], "pul2": r[3], "odam": r[4], "ban": r[5]}
        for r in rows
    ]
    return web.json_response({"ok": True, "users": users})


async def get_ai_reply(user_msg: str):
    """AI mantiqi — ham web, ham bot uchun umumiy."""
    if not AI_API_KEY:
        return "Hozircha AI kaliti o'rnatilmagan."

    try:
        async with aiosqlite.connect(DB_PATH) as db:
            async with db.execute("SELECT COUNT(*) FROM users") as c:
                users = (await c.fetchone())[0]
            
            from config import ADMIN_IDS, SUPER_ADMIN_ID
            admins_info = f"Asosiy admin: {SUPER_ADMIN_ID}. Jami {len(ADMIN_IDS)+1} ta."

            async with db.execute("SELECT key, value FROM bot_settings") as c:
                settings = {r[0]: r[1] for r in await c.fetchall()}
            async with db.execute("SELECT key, value FROM bot_texts") as c:
                texts = {r[0]: r[1] for r in await c.fetchall()}
            
            bot_info = f"VIP narxi: {settings.get('vip_price')} {settings.get('vip_currency')}. Qo'llanma: {texts.get('guide', '')[:100]}..."

            keywords = [w for w in user_msg.split() if len(w) >= 3]
            matched_animes = []
            if keywords:
                for kw in keywords[:5]:
                    async with db.execute("SELECT id, nom, rams FROM animelar WHERE nom LIKE ? LIMIT 3", (f'%{kw}%',)) as c:
                        rows = await c.fetchall()
                        for r in rows:
                            if r not in matched_animes: matched_animes.append(r)

            async with db.execute("SELECT nom FROM animelar ORDER BY qidiruv DESC LIMIT 5") as c:
                top_animes = [r[0] for r in await c.fetchall()]

        matched_str = ", ".join([f"{r[1]} (ID:{r[0]}, Img:/poster/{r[0]})" for r in matched_animes[:8]])
        system_prompt = (
            f"Siz 'ANIME UZ' yordamchisisiz. Stats: {users}. "
            f"Bot: {bot_info}. Adminlar: {admins_info}. "
            f"Topilganlar: {matched_str or 'yoq'}. "
            f"QOIDALAR: 1. Anime uchun FAQAT [ANIME_CARD:ID|Nom|RasmURL] formatini ishlating. "
            f"2. Faqat o'zbek tilida qisqa javob bering."
        )

        payload = {
            "model": AI_MODEL or "gpt-4o-mini",
            "messages": [
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_msg}
            ],
            "max_tokens": 150, 
            "temperature": 0.4
        }

        async with aiohttp.ClientSession() as session:
            async with session.post(
                f"{AI_BASE_URL}/chat/completions",
                headers={"Authorization": f"Bearer {AI_API_KEY}"},
                json=payload,
                timeout=20
            ) as r:
                res_data = await r.json()

        if "choices" in res_data:
            return res_data["choices"][0]["message"]["content"]
        return "AI xatosi (API)."
    except Exception:
        return "AI vaqtincha ishlamayapti."


async def api_ai_chat(request):
    """Web UI uchun AI chat endpointi."""
    try:
        if not _check_rate_limit(request, "ai_chat", 10, 86400):
            return web.json_response({"ok": False, "error": "Kunlik limit (10 ta) tugadi!"}, status=429)
        body = await request.json()
        user_msg = (body.get("message") or "").strip()
        admin_password_mode = bool(body.get("admin_password_mode"))
        if not user_msg:
            return web.json_response({"ok": False, "error": "Xabar bo'sh"}, status=400)
        if len(user_msg) > 800:
            return web.json_response({"ok": False, "error": "Xabar juda uzun"}, status=400)

        if admin_password_mode:
            if not ADMIN_LOGIN or not ADMIN_PASSWORD:
                return web.json_response({"ok": True, "reply": "Admin login/parol serverda sozlanmagan."})
            if secrets.compare_digest(user_msg, ADMIN_PASSWORD):
                session_secret = WEB_ADMIN_TOKEN or ADMIN_PASSWORD
                response = web.json_response({
                    "ok": True,
                    "reply": "Parol to'g'ri. Admin panel ochilmoqda...",
                    "admin_ok": True,
                    "admin_url": "/admin",
                    "admin_token": WEB_ADMIN_TOKEN,
                })
                if WEB_ADMIN_TOKEN:
                    response.set_cookie(
                        "admin_token",
                        WEB_ADMIN_TOKEN,
                        max_age=60 * 60 * 12,
                        httponly=True,
                        secure=request.scheme == "https",
                        samesite="Strict",
                    )
                if session_secret:
                    response.set_cookie(
                        ADMIN_SESSION_COOKIE,
                        session_secret,
                        max_age=60 * 60 * 12,
                        httponly=True,
                        secure=request.scheme == "https",
                        samesite="Strict",
                    )
                return response
            return web.json_response({"ok": True, "reply": "Parol noto'g'ri. Qayta urinib ko'ring.", "admin_password_required": True})

        if ADMIN_LOGIN and secrets.compare_digest(user_msg, ADMIN_LOGIN):
            return web.json_response({"ok": True, "reply": "Maxfiy kod qabul qilindi. Admin parolini kiriting.", "admin_password_required": True})

        reply = await get_ai_reply(user_msg)
        return web.json_response({"ok": True, "reply": reply})

    except Exception:
        return web.json_response({"ok": False, "error": "Server xatosi"}, status=500)


async def api_payments(request):
    """So'nggi 10 ta to'lov."""
    async with aiosqlite.connect(DB_PATH) as db:
        async with db.execute(
            "SELECT user_id, amount, status FROM payments ORDER BY id DESC LIMIT 10"
        ) as c:
            rows = await c.fetchall()
    payments = [{"user_id": r[0], "amount": r[1], "status": r[2]} for r in rows]
    return web.json_response({"payments": payments})


async def api_report(request):
    """Saytdan shikoyat / taklif — super adminga Telegram xabar yuboradi."""
    try:
        if not _check_rate_limit(request, "report", 5, 3600):
            return web.json_response({"ok": False, "error": "Juda ko'p murojaat yuborildi"}, status=429)
        body = await request.json()
        msg_type  = body.get("type", "other")
        name      = html.escape((body.get("name") or "").strip()[:80])
        username  = html.escape((body.get("username") or "").strip()[:80])
        message   = html.escape((body.get("message") or "").strip()[:1500])

        if not message:
            return web.json_response({"ok": False, "error": "Xabar bo'sh"}, status=400)

        type_labels = {
            "bug":        "🐛 Xatolik",
            "suggestion": "💡 Taklif",
            "complaint":  "😤 Shikoyat",
            "other":      "📌 Boshqa",
        }
        type_label = type_labels.get(msg_type, "📌 Boshqa")

        text = (
            f"📩 <b>Yangi murojaat — Sayt</b>\n"
            f"{'─' * 28}\n"
            f"<b>Tur:</b> {type_label}\n"
        )
        if name:
            text += f"<b>Ism:</b> {name}\n"
        if username:
            text += f"<b>Username:</b> {username}\n"
        text += f"\n<b>Xabar:</b>\n{message}"

        from config import SUPER_ADMIN_ID
        tg_url = f"https://api.telegram.org/bot{BOT_TOKEN}/sendMessage"
        async with aiohttp.ClientSession() as session:
            await session.post(tg_url, json={
                "chat_id":    SUPER_ADMIN_ID,
                "text":       text,
                "parse_mode": "HTML",
            })

        return web.json_response({"ok": True})
    except Exception:
        return web.json_response({"ok": False, "error": "Server xatosi"}, status=500)


# ═══════════════════════════════════════════════
#  ANILIST INTEGRATION
# ═══════════════════════════════════════════════

# AniList OAuth state → session_token mapping
_anilist_states: dict = {}   # state -> session_token
# AniList access tokens per session
_anilist_tokens: dict = {}   # session_token -> anilist_access_token

ANILIST_GRAPHQL = "https://graphql.anilist.co"


def _missing_anilist_settings() -> list[str]:
    missing = []
    if not ANILIST_CLIENT_ID:
        missing.append("ANILIST_CLIENT_ID")
    if not ANILIST_CLIENT_SECRET:
        missing.append("ANILIST_CLIENT_SECRET")
    if not ANILIST_REDIRECT_URI:
        missing.append("ANILIST_REDIRECT_URI")
    return missing


# Spotify OAuth state/token mapping
_spotify_states: dict = {}   # state -> session_token
_spotify_tokens: dict = {}   # session_token -> spotify token payload

SEARCH_QUERY = """
query ($search: String, $page: Int, $perPage: Int) {
  Page(page: $page, perPage: $perPage) {
    media(search: $search, type: ANIME, sort: SEARCH_MATCH) {
      id
      title { romaji english native }
      coverImage { large medium }
      status
      averageScore
      episodes
      nextAiringEpisode {
        airingAt
        timeUntilAiring
        episode
      }
      season
      seasonYear
      genres
      format
    }
  }
}
"""


async def api_anilist_search(request: web.Request) -> web.Response:
    """
    GET /api/anilist/search?q=naruto&page=1&per=20
    AniList GraphQL API orqali global anime qidirish.
    """
    q = request.rel_url.query.get("q", "").strip()
    if not q:
        return web.json_response({"ok": False, "error": "q parametri kerak"}, status=400)

    page = int(request.rel_url.query.get("page", 1))
    per_page = min(int(request.rel_url.query.get("per", 20)), 50)

    try:
        async with aiohttp.ClientSession() as session:
            async with session.post(
                ANILIST_GRAPHQL,
                json={
                    "query": SEARCH_QUERY,
                    "variables": {"search": q, "page": page, "perPage": per_page},
                },
                headers={"Content-Type": "application/json", "Accept": "application/json"},
                timeout=aiohttp.ClientTimeout(total=15),
            ) as resp:
                data = await resp.json()

        if "errors" in data:
            errs = "; ".join(e.get("message", "?") for e in data["errors"])
            return web.json_response({"ok": False, "error": errs}, status=502)

        media_list = data.get("data", {}).get("Page", {}).get("media", [])

        results = []
        for m in media_list:
            title = (
                m["title"].get("english")
                or m["title"].get("romaji")
                or m["title"].get("native")
                or "Nomsiz"
            )
            results.append({
                "id":           m["id"],
                "title":        title,
                "title_romaji": m["title"].get("romaji") or "",
                "title_native": m["title"].get("native") or "",
                "cover":        m["coverImage"].get("large") or m["coverImage"].get("medium") or "",
                "status":       m.get("status") or "UNKNOWN",
                "score":        m.get("averageScore"),   # 0-100 or null
                "episodes":     m.get("episodes"),
                "next_airing":  m.get("nextAiringEpisode") or None,
                "season":       m.get("season") or "",
                "year":         m.get("seasonYear"),
                "genres":       m.get("genres") or [],
                "format":       m.get("format") or "",
            })

        return web.json_response({"ok": True, "results": results, "total": len(results)})

    except asyncio.TimeoutError:
        return web.json_response({"ok": False, "error": "AniList timeout"}, status=504)
    except Exception:
        return web.json_response({"ok": False, "error": "Server xatosi"}, status=500)


async def api_auth_anilist(request: web.Request) -> web.Response:
    """
    GET /api/auth/anilist  (Authorization: Bearer <session_token>)
    Foydalanuvchini AniList OAuth sahifasiga yo'naltiradi.
    """
    token = _bearer_token(request)
    if not token or token not in _sessions:
        return web.json_response({"ok": False, "error": "Avval Google bilan kiring"}, status=401)

    missing = _missing_anilist_settings()
    if missing:
        return web.json_response(
            {"ok": False, "error": "AniList sozlamalari to'liq emas: " + ", ".join(missing)},
            status=500,
        )

    state = secrets.token_urlsafe(16)
    _anilist_states[state] = token   # state → session_token

    auth_url = (
        "https://anilist.co/api/v2/oauth/authorize?"
        + urlencode({
            "client_id": ANILIST_CLIENT_ID,
            "redirect_uri": ANILIST_REDIRECT_URI,
            "response_type": "code",
            "state": state,
        })
    )
    return web.json_response({"ok": True, "url": auth_url})


async def callback_anilist(request: web.Request) -> web.Response:
    """
    GET /callback/anilist?code=...&state=...
    AniList OAuth callback — kodni token bilan almashtirib, sessiyaga yozadi.
    """
    code = request.rel_url.query.get("code", "").strip()
    state = request.rel_url.query.get("state", "").strip()

    if not code or not state:
        return web.Response(
            text="<h2>❌ Xatolik: code yoki state yo'q</h2>",
            content_type="text/html",
            status=400,
        )

    session_token = _anilist_states.pop(state, None)
    if not session_token:
        return web.Response(
            text="<h2>❌ Xatolik: noto'g'ri state. Qayta urinib ko'ring.</h2>",
            content_type="text/html",
            status=400,
        )

    missing = _missing_anilist_settings()
    if missing:
        return web.Response(
            text=f"<h2>❌ AniList sozlamalari to'liq emas</h2><p>Yetishmayapti: {html.escape(', '.join(missing))}</p>",
            content_type="text/html",
            status=500,
        )

    try:
        async with aiohttp.ClientSession() as session:
            async with session.post(
                "https://anilist.co/api/v2/oauth/token",
                json={
                    "grant_type":    "authorization_code",
                    "client_id":     ANILIST_CLIENT_ID,
                    "client_secret": ANILIST_CLIENT_SECRET,
                    "redirect_uri":  ANILIST_REDIRECT_URI,
                    "code":          code,
                },
                headers={"Content-Type": "application/json", "Accept": "application/json"},
                timeout=aiohttp.ClientTimeout(total=15),
            ) as resp:
                token_data = await resp.json()

        if "error" in token_data:
            err = token_data.get("error_description") or token_data.get("error", "Token xatosi")
            return web.Response(
                text=f"<h2>❌ AniList token xatosi: {err}</h2>",
                content_type="text/html",
                status=400,
            )

        access_token = token_data.get("access_token", "")
        _anilist_tokens[session_token] = access_token

        # Foydalanuvchi ma'lumotini AniList dan olamiz
        viewer_query = "query { Viewer { id name avatar { large } siteUrl } }"
        async with aiohttp.ClientSession() as session:
            async with session.post(
                ANILIST_GRAPHQL,
                json={"query": viewer_query},
                headers={
                    "Authorization":  f"Bearer {access_token}",
                    "Content-Type":   "application/json",
                    "Accept":         "application/json",
                },
                timeout=aiohttp.ClientTimeout(total=10),
            ) as resp:
                viewer_data = await resp.json()

        viewer = viewer_data.get("data", {}).get("Viewer", {})
        if viewer and session_token in _sessions:
            _sessions[session_token]["anilist"] = {
                "id":       viewer.get("id"),
                "name":     viewer.get("name"),
                "avatar":   (viewer.get("avatar") or {}).get("large") or "",
                "site_url": viewer.get("siteUrl") or "",
            }

        # Muvaffaqiyatli — sahifani yopamiz
        html = """<!DOCTYPE html>
<html><head><meta charset="UTF-8"><title>AniList ulandi</title>
<style>
  body{margin:0;display:flex;align-items:center;justify-content:center;min-height:100vh;
       background:#0a0a18;font-family:sans-serif;color:#cce4ff}
  .box{background:rgba(0,212,255,.08);border:1px solid rgba(0,212,255,.25);border-radius:16px;
       padding:40px 48px;text-align:center;max-width:380px}
  .ico{font-size:3rem;margin-bottom:16px}
  h2{color:#00d4ff;font-size:1.2rem;margin:0 0 10px}
  p{font-size:.85rem;color:#7aadcc;margin:0 0 22px}
  button{background:linear-gradient(90deg,#00d4ff,#8b5cf6);border:none;color:#fff;
         padding:10px 28px;border-radius:20px;cursor:pointer;font-weight:700;font-size:.85rem}
</style></head>
<body>
  <div class="box">
    <div class="ico">✅</div>
    <h2>AniList ulandi!</h2>
    <p>Hisobingiz muvaffaqiyatli bog'landi. Bu oynani yopishingiz mumkin.</p>
    <button onclick="window.close()">Oynani yopish</button>
  </div>
  <script>setTimeout(()=>window.close(),3000)</script>
</body></html>"""
        return web.Response(text=html, content_type="text/html")

    except asyncio.TimeoutError:
        return web.Response(
            text="<h2>❌ AniList serveri javob bermadi (timeout)</h2>",
            content_type="text/html",
            status=504,
        )
    except Exception as e:
        return web.Response(
            text=f"<h2>❌ Xatolik: {e}</h2>",
            content_type="text/html",
            status=500,
        )


async def api_anilist_status(request: web.Request) -> web.Response:
    """
    GET /api/auth/anilist/status  (Authorization: Bearer <session_token>)
    AniList ulanish holatini qaytaradi.
    """
    token = _bearer_token(request)
    user = _sessions.get(token)
    if not user:
        return web.json_response({"ok": False, "error": "Autentifikatsiya talab etiladi"}, status=401)

    anilist_info = user.get("anilist")
    connected = bool(_anilist_tokens.get(token)) and bool(anilist_info)
    return web.json_response({
        "ok":        True,
        "connected": connected,
        "anilist":   anilist_info if connected else None,
    })


# ═══════════════════════════════════════════════
#  GOOGLE OAUTH
# ═══════════════════════════════════════════════

async def serve_callback(request):
    """callback.html ni qaytaradi."""
    if request.rel_url.query.get("code") and request.rel_url.query.get("state"):
        return await callback_anilist(request)
    path = os.path.join(WEBAPP_DIR, "callback.html")
    with open(path, "r", encoding="utf-8") as f:
        return web.Response(text=f.read(), content_type="text/html", charset="utf-8")


async def serve_callback_spotify(request):
    """callbackspotify.html ni qaytaradi."""
    path = os.path.join(WEBAPP_DIR, "callbackspotify.html")
    with open(path, "r", encoding="utf-8") as f:
        return web.Response(text=f.read(), content_type="text/html", charset="utf-8")


async def serve_qollanma(request):
    """qollanma.html ni qaytaradi."""
    path = os.path.join(WEBAPP_DIR, "qollanma.html")
    with open(path, "r", encoding="utf-8") as f:
        return web.Response(text=f.read(), content_type="text/html", charset="utf-8")


async def api_auth_google(request):
    """
    POST /api/auth/google  { code: "..." }
    Google authorization code ni token bilan almashtirib,
    user ma'lumotlarini qaytaradi va session yaratadi.
    """
    try:
        if not _check_rate_limit(request, "google_auth", 20, 3600):
            return web.json_response({"ok": False, "error": "Juda ko'p urinish"}, status=429)
        body = await request.json()
        code = body.get("code", "").strip()
        if not code:
            return web.json_response({"ok": False, "error": "code yo'q"}, status=400)

        redirect_uri = GOOGLE_REDIRECT_URI or body.get("redirect_uri", "")
        if not redirect_uri:
            return web.json_response({"ok": False, "error": "GOOGLE_REDIRECT_URI sozlanmagan"}, status=500)
        if not _is_allowed_redirect_uri(redirect_uri):
            return web.json_response({"ok": False, "error": "redirect_uri ruxsat etilmagan"}, status=400)

        async with aiohttp.ClientSession() as session:
            # 1. Code → access token
            async with session.post("https://oauth2.googleapis.com/token", data={
                "code":          code,
                "client_id":     GOOGLE_CLIENT_ID,
                "client_secret": GOOGLE_CLIENT_SECRET,
                "redirect_uri":  redirect_uri,
                "grant_type":    "authorization_code",
            }) as resp:
                token_data = await resp.json()

            if "error" in token_data:
                return web.json_response({"ok": False, "error": token_data.get("error_description", token_data["error"])}, status=400)

            access_token = token_data.get("access_token")

            # 2. Access token → user info
            async with session.get(
                "https://www.googleapis.com/oauth2/v2/userinfo",
                headers={"Authorization": f"Bearer {access_token}"}
            ) as resp:
                user_info = await resp.json()

        # 3. Session yaratish
        session_token = _new_token()
        _sessions[session_token] = {
            "id":      user_info.get("id", ""),
            "name":    user_info.get("name", "Foydalanuvchi"),
            "email":   user_info.get("email", ""),
            "picture": user_info.get("picture", ""),
            "created": datetime.now().isoformat(),
            "created_ts": time.time(),
        }

        return web.json_response({
            "ok":    True,
            "token": session_token,
            "user":  _sessions[session_token],
        })

    except Exception:
        return web.json_response({"ok": False, "error": "Server xatosi"}, status=500)


async def api_auth_me(request):
    """GET /api/auth/me — token orqali user ma'lumotlarini olish."""
    _cleanup_sessions()
    token = _bearer_token(request)
    user = _sessions.get(token)
    if not user:
        return web.json_response({"ok": False, "error": "Autentifikatsiya talab etiladi"}, status=401)
    return web.json_response({"ok": True, "user": user})


async def api_auth_logout(request):
    """POST /api/auth/logout — session o'chirish."""
    token = _bearer_token(request)
    _sessions.pop(token, None)
    _anilist_tokens.pop(token, None)
    _spotify_tokens.pop(token, None)
    return web.json_response({"ok": True})


# ═══════════════════════════════════════════════
def _spotify_redirect_uri() -> str:
    return SPOTIFY_REDIRECT_URI or (f"{WEB_PUBLIC_ORIGIN}/callbackspotify" if WEB_PUBLIC_ORIGIN else "")


async def api_auth_spotify(request: web.Request) -> web.Response:
    token = _bearer_token(request)
    if not token or token not in _sessions:
        return web.json_response({"ok": False, "error": "Avval Google bilan kiring"}, status=401)

    redirect_uri = _spotify_redirect_uri()
    if not SPOTIFY_CLIENT_ID or not redirect_uri:
        return web.json_response(
            {"ok": False, "error": "SPOTIFY_CLIENT_ID yoki SPOTIFY_REDIRECT_URI sozlanmagan"},
            status=500,
        )

    state = secrets.token_urlsafe(16)
    _spotify_states[state] = token
    params = {
        "response_type": "code",
        "client_id": SPOTIFY_CLIENT_ID,
        "scope": "user-read-email user-read-private",
        "redirect_uri": redirect_uri,
        "state": state,
        "show_dialog": "true",
    }
    return web.json_response({"ok": True, "url": f"https://accounts.spotify.com/authorize?{urlencode(params)}"})


async def api_auth_spotify_callback(request: web.Request) -> web.Response:
    try:
        if not _check_rate_limit(request, "spotify_auth", 20, 3600):
            return web.json_response({"ok": False, "error": "Juda ko'p urinish"}, status=429)
        body = await request.json()
        code = (body.get("code") or "").strip()
        state = (body.get("state") or "").strip()
        if not code or not state:
            return web.json_response({"ok": False, "error": "code yoki state yo'q"}, status=400)

        session_token = _spotify_states.pop(state, None)
        if not session_token or session_token not in _sessions:
            return web.json_response({"ok": False, "error": "Noto'g'ri state. Qayta urinib ko'ring."}, status=400)

        redirect_uri = _spotify_redirect_uri()
        if not SPOTIFY_CLIENT_ID or not SPOTIFY_CLIENT_SECRET or not redirect_uri:
            return web.json_response({"ok": False, "error": "Spotify sozlamalari to'liq emas"}, status=500)

        async with aiohttp.ClientSession() as session:
            async with session.post(
                "https://accounts.spotify.com/api/token",
                data={
                    "grant_type": "authorization_code",
                    "code": code,
                    "redirect_uri": redirect_uri,
                    "client_id": SPOTIFY_CLIENT_ID,
                    "client_secret": SPOTIFY_CLIENT_SECRET,
                },
                headers={"Content-Type": "application/x-www-form-urlencoded"},
                timeout=aiohttp.ClientTimeout(total=15),
            ) as resp:
                token_data = await resp.json()

            if token_data.get("error"):
                return web.json_response(
                    {"ok": False, "error": token_data.get("error_description") or token_data.get("error")},
                    status=400,
                )

            access_token = token_data.get("access_token", "")
            async with session.get(
                "https://api.spotify.com/v1/me",
                headers={"Authorization": f"Bearer {access_token}"},
                timeout=aiohttp.ClientTimeout(total=10),
            ) as resp:
                user_info = await resp.json()

        images = user_info.get("images") or []
        spotify_info = {
            "id": user_info.get("id", ""),
            "name": user_info.get("display_name") or user_info.get("id") or "Spotify foydalanuvchi",
            "email": user_info.get("email", ""),
            "country": user_info.get("country", ""),
            "profile_url": (user_info.get("external_urls") or {}).get("spotify", ""),
            "image": images[0].get("url") if images else "",
        }
        _spotify_tokens[session_token] = token_data
        _sessions[session_token]["spotify"] = spotify_info

        return web.json_response({"ok": True, "spotify": spotify_info})

    except asyncio.TimeoutError:
        return web.json_response({"ok": False, "error": "Spotify serveri javob bermadi"}, status=504)
    except Exception:
        return web.json_response({"ok": False, "error": "Server xatosi"}, status=500)


async def api_spotify_status(request: web.Request) -> web.Response:
    token = _bearer_token(request)
    user = _sessions.get(token)
    if not user:
        return web.json_response({"ok": False, "error": "Autentifikatsiya talab etiladi"}, status=401)

    spotify_info = user.get("spotify")
    connected = bool(_spotify_tokens.get(token)) and bool(spotify_info)
    return web.json_response({
        "ok": True,
        "connected": connected,
        "spotify": spotify_info if connected else None,
    })


def _get_session_user(request: web.Request) -> dict | None:
    _cleanup_sessions()
    token = _bearer_token(request)
    return _sessions.get(token)


async def _get_telegram_profile(user_id: int) -> dict:
    profile = {"id": user_id, "name": f"Telegram {user_id}", "username": "", "photo_url": "", "photo_file_id": ""}
    async with aiohttp.ClientSession() as session:
        try:
            async with session.get(f"https://api.telegram.org/bot{BOT_TOKEN}/getChat", params={"chat_id": user_id}) as resp:
                data = await resp.json()
            if data.get("ok"):
                chat = data.get("result", {})
                first = chat.get("first_name") or ""
                last = chat.get("last_name") or ""
                profile["name"] = (f"{first} {last}".strip() or chat.get("title") or profile["name"])
                profile["username"] = chat.get("username") or ""
        except Exception:
            pass
        try:
            async with session.get(
                f"https://api.telegram.org/bot{BOT_TOKEN}/getUserProfilePhotos",
                params={"user_id": user_id, "limit": 1},
            ) as resp:
                data = await resp.json()
            photos = data.get("result", {}).get("photos", []) if data.get("ok") else []
            if photos and photos[0]:
                file_id = photos[0][-1].get("file_id", "")
                profile["photo_file_id"] = file_id
                profile["photo_url"] = f"/media/{file_id}"
        except Exception:
            pass
    return profile


async def api_telegram_link_start(request: web.Request) -> web.Response:
    try:
        if not _check_rate_limit(request, "telegram_link", 5, 3600):
            return web.json_response({"ok": False, "error": "Juda ko'p urinish"}, status=429)
        body = await request.json()
        device_id = (body.get("device_id") or "").strip()
        telegram_id = int(str(body.get("telegram_id") or "").strip())
        saved_ids = body.get("saved_ids") or []
        if not device_id:
            return web.json_response({"ok": False, "error": "device_id kerak"}, status=400)
        if len(device_id) > 128:
            return web.json_response({"ok": False, "error": "device_id juda uzun"}, status=400)
        if not isinstance(saved_ids, list):
            saved_ids = []
        saved_ids = saved_ids[:100]

        request_id = secrets.token_urlsafe(12)
        user = _get_session_user(request) or {}
        who = user.get("name") or "Web foydalanuvchi"
        async with aiosqlite.connect(DB_PATH) as db:
            await db.execute(
                "INSERT OR REPLACE INTO web_link_requests (request_id, device_id, telegram_id, status) VALUES (?, ?, ?, 'pending')",
                (request_id, device_id, telegram_id),
            )
            for anime_id in saved_ids:
                try:
                    await db.execute(
                        "INSERT OR IGNORE INTO web_saved_animes (device_id, anime_id) VALUES (?, ?)",
                        (device_id, int(anime_id)),
                    )
                except Exception:
                    pass
            await db.commit()

        text = (
            "🔐 <b>Web profil ulash so'rovi</b>\n\n"
            f"<b>Web profil:</b> {who}\n"
            f"<b>Telegram ID:</b> <code>{telegram_id}</code>\n\n"
            "Tasdiqlasangiz webdagi saqlangan animelar bot profilingiz/watchlistingiz bilan ulanadi."
        )
        keyboard = {"inline_keyboard": [[
            {"text": "✅ Tasdiqlash", "callback_data": f"web_link_ok={request_id}", "style": "success"},
            {"text": "❌ Rad etish", "callback_data": f"web_link_no={request_id}", "style": "danger"},
        ]]}
        async with aiohttp.ClientSession() as session:
            async with session.post(
                f"https://api.telegram.org/bot{BOT_TOKEN}/sendMessage",
                json={"chat_id": telegram_id, "text": text, "parse_mode": "HTML", "reply_markup": keyboard},
            ) as resp:
                sent = await resp.json()
        if not sent.get("ok"):
            return web.json_response({"ok": False, "error": sent.get("description") or "Bot xabar yubora olmadi. Avval /start qiling."}, status=400)
        return web.json_response({"ok": True, "request_id": request_id})
    except ValueError:
        return web.json_response({"ok": False, "error": "Telegram ID raqam bo'lishi kerak"}, status=400)
    except Exception:
        return web.json_response({"ok": False, "error": "Server xatosi"}, status=500)


async def api_telegram_link_status(request: web.Request) -> web.Response:
    request_id = request.rel_url.query.get("request_id", "").strip()
    device_id = request.rel_url.query.get("device_id", "").strip()
    if not request_id or not device_id:
        return web.json_response({"ok": False, "error": "request_id va device_id kerak"}, status=400)
    async with aiosqlite.connect(DB_PATH) as db:
        async with db.execute("SELECT status FROM web_link_requests WHERE request_id=? AND device_id=?", (request_id, device_id)) as c:
            row = await c.fetchone()
    return web.json_response({"ok": True, "status": row[0] if row else "missing"})


async def api_telegram_profile(request: web.Request) -> web.Response:
    device_id = request.rel_url.query.get("device_id", "").strip()
    if not device_id:
        return web.json_response({"ok": False, "error": "device_id kerak"}, status=400)
    async with aiosqlite.connect(DB_PATH) as db:
        async with db.execute("SELECT telegram_id FROM web_profile_links WHERE device_id=?", (device_id,)) as c:
            link = await c.fetchone()
        if not link:
            return web.json_response({"ok": True, "linked": False})
        telegram_id = int(link[0])
        async with db.execute("SELECT status, pul, pul2, odam, ban FROM users WHERE user_id=?", (telegram_id,)) as c:
            user_row = await c.fetchone()
        async with db.execute("SELECT anime_id FROM watchlist WHERE user_id=? ORDER BY created_at DESC", (telegram_id,)) as c:
            watch_rows = await c.fetchall()
        async with db.execute("""
            SELECT p.anime_id, p.last_episode, a.nom
            FROM watch_progress p
            LEFT JOIN animelar a ON a.id=p.anime_id
            WHERE p.user_id=?
            ORDER BY p.updated_at DESC
            LIMIT 10
        """, (telegram_id,)) as c:
            progress_rows = await c.fetchall()

    profile = await _get_telegram_profile(telegram_id)
    bot_profile = {
        "status": user_row[0] if user_row else "Oddiy",
        "balance": user_row[1] if user_row else 0,
        "cashback": user_row[2] if user_row else 0,
        "referrals": user_row[3] if user_row else 0,
        "ban": user_row[4] if user_row else "unban",
    }
    return web.json_response({
        "ok": True,
        "linked": True,
        "telegram": profile,
        "bot_profile": bot_profile,
        "watchlist": [r[0] for r in watch_rows],
        "progress": [{"anime_id": r[0], "last_episode": r[1], "name": r[2] or ""} for r in progress_rows],
    })


async def api_profile_saved(request: web.Request) -> web.Response:
    try:
        if not _check_rate_limit(request, "profile_saved", 60, 3600):
            return web.json_response({"ok": False, "error": "Juda ko'p so'rov"}, status=429)
        body = await request.json()
        device_id = (body.get("device_id") or "").strip()
        anime_id = int(body.get("anime_id"))
        saved = bool(body.get("saved"))
        if not device_id:
            return web.json_response({"ok": False, "error": "device_id kerak"}, status=400)
        if len(device_id) > 128:
            return web.json_response({"ok": False, "error": "device_id juda uzun"}, status=400)
        if anime_id <= 0:
            return web.json_response({"ok": False, "error": "anime_id noto'g'ri"}, status=400)
        async with aiosqlite.connect(DB_PATH) as db:
            if saved:
                await db.execute("INSERT OR IGNORE INTO web_saved_animes (device_id, anime_id) VALUES (?, ?)", (device_id, anime_id))
            else:
                await db.execute("DELETE FROM web_saved_animes WHERE device_id=? AND anime_id=?", (device_id, anime_id))
            async with db.execute("SELECT telegram_id FROM web_profile_links WHERE device_id=?", (device_id,)) as c:
                link = await c.fetchone()
            if link:
                if saved:
                    await db.execute("INSERT OR IGNORE INTO watchlist (user_id, anime_id) VALUES (?, ?)", (int(link[0]), anime_id))
                else:
                    await db.execute("DELETE FROM watchlist WHERE user_id=? AND anime_id=?", (int(link[0]), anime_id))
            await db.commit()
        return web.json_response({"ok": True})
    except Exception:
        return web.json_response({"ok": False, "error": "Server xatosi"}, status=500)


#  ANIME KARTA JANGI
# ═══════════════════════════════════════════════

async def _random_anime_cards(n: int = 5) -> list:
    """DB dan tasodifiy n ta anime kartani oladi."""
    async with aiosqlite.connect(DB_PATH) as db:
        async with db.execute("""
            SELECT a.id, a.nom, a.rams, a.janri, a.yili, a.aniType, a.fandub,
                   COALESCE(a.qidiruv,0) as qidiruv,
                   COUNT(d.data_id) as ep_count
            FROM animelar a
            LEFT JOIN anime_datas d ON d.id = a.id
            GROUP BY a.id
            ORDER BY RANDOM() LIMIT ?
        """, (n,)) as c:
            rows = await c.fetchall()

    cards = []
    for r in rows:
        rams = r[2] or ""
        poster = _poster_url(r[0], rams) if rams else ""
        cards.append({
            "id":       r[0],
            "nom":      r[1] or "Nomsiz",
            "poster":   poster,
            "janri":    r[3] or "—",
            "yili":     int(r[4]) if r[4] and str(r[4]).isdigit() else 0,
            "aniType":  r[5] or "—",
            "fandub":   r[6] or "—",
            "qidiruv":  int(r[7]) if r[7] else 0,
            "ep_count": int(r[8]) if r[8] else 0,
        })
    return cards


async def api_game_start(request):
    """POST /api/game/start — yangi o'yin boshlash."""
    _cleanup_sessions()
    token = _bearer_token(request)
    user = _sessions.get(token)
    if not user:
        return web.json_response({"ok": False, "error": "Login talab etiladi"}, status=401)

    try:
        cards = await _random_anime_cards(10)
        if len(cards) < 6:
            return web.json_response({"ok": False, "error": "DB da yetarli anime yo'q"}, status=400)

        random.shuffle(cards)
        n = len(cards) // 2
        player_cards = cards[:n]
        cpu_cards    = cards[n:n*2]

        game_id = _new_token()[:16]
        _games[game_id] = GameState(player_cards, cpu_cards, user)

        return web.json_response({
            "ok":      True,
            "game_id": game_id,
            "state":   _games[game_id].to_dict(),
        })
    except Exception:
        return web.json_response({"ok": False, "error": "Server xatosi"}, status=500)


async def api_game_state(request):
    """GET /api/game/{game_id} — o'yin holatini olish."""
    user = _get_session_user(request)
    if not user:
        return web.json_response({"ok": False, "error": "Login talab etiladi"}, status=401)
    game_id = request.match_info["game_id"]
    game = _games.get(game_id)
    if not game:
        return web.json_response({"ok": False, "error": "O'yin topilmadi"}, status=404)
    if game.user.get("id") != user.get("id"):
        return web.json_response({"ok": False, "error": "Ruxsat yo'q"}, status=403)
    return web.json_response({"ok": True, "state": game.to_dict()})


async def api_game_move(request):
    """POST /api/game/{game_id}/move  { stat: "ep_count"|"qidiruv"|"yili" }"""
    user = _get_session_user(request)
    if not user:
        return web.json_response({"ok": False, "error": "Login talab etiladi"}, status=401)
    game_id = request.match_info["game_id"]
    game = _games.get(game_id)
    if not game:
        return web.json_response({"ok": False, "error": "O'yin topilmadi"}, status=404)
    if game.user.get("id") != user.get("id"):
        return web.json_response({"ok": False, "error": "Ruxsat yo'q"}, status=403)
    if game.finished:
        return web.json_response({"ok": False, "error": "O'yin tugagan"}, status=400)

    body = await request.json()
    stat = body.get("stat", "")
    valid = [s["key"] for s in GameState.STATS]
    if stat not in valid:
        return web.json_response({"ok": False, "error": f"Noto'g'ri stat. Mumkin: {valid}"}, status=400)

    result = game.play_round(stat)
    return web.json_response({"ok": True, "round_result": result, "state": game.to_dict()})


async def serve_privacy(request):
    """privacy.html ni qaytaradi."""
    path = os.path.join(WEBAPP_DIR, "privacy.html")
    with open(path, "r", encoding="utf-8") as f:
        return web.Response(text=f.read(), content_type="text/html", charset="utf-8")


async def serve_terms(request):
    """terms.html ni qaytaradi."""
    path = os.path.join(WEBAPP_DIR, "terms.html")
    with open(path, "r", encoding="utf-8") as f:
        return web.Response(text=f.read(), content_type="text/html", charset="utf-8")


def create_app():
    app = web.Application(
        client_max_size=2 * 1024 * 1024,
        middlewares=[security_headers_middleware, traffic_guard_middleware],
    )
    app.router.add_get("/", index)
    app.router.add_get("/admin", serve_admin)
    app.router.add_get("/api/animes", api_animes)
    app.router.add_get("/api/animes/{anime_id}", api_anime_detail)
    app.router.add_get("/api/bot-info", api_bot_info)
    app.router.add_get("/bot-icon", bot_icon)
    app.router.add_get("/poster/{anime_id}", anime_poster)
    app.router.add_get("/api/admins", api_admins)
    app.router.add_get("/api/stats", api_stats)
    app.router.add_get("/api/admin/stats", api_admin_stats)
    app.router.add_get("/api/admin/animes", api_admin_animes)
    app.router.add_get("/api/admin/anilist/posters", api_admin_anilist_posters)
    app.router.add_post("/api/admin/animes", api_admin_create_anime)
    app.router.add_put("/api/admin/animes/{anime_id}", api_admin_update_anime)
    app.router.add_delete("/api/admin/animes/{anime_id}", api_admin_delete_anime)
    app.router.add_get("/api/admin/users", api_admin_users)
    app.router.add_get("/events", sse_stream)
    app.router.add_get("/api/payments", api_payments)
    app.router.add_get("/api/media/{anime_id}", anime_media_info)
    app.router.add_get("/api/preview/{anime_id}", api_episode_preview)
    app.router.add_get("/api/episodes/{anime_id}", api_episodes)
    app.router.add_get("/media/{file_id}", media_proxy)
    app.router.add_post("/api/ai/chat", api_ai_chat)
    app.router.add_post("/api/report",  api_report)
    # OAuth — Google
    app.router.add_get( "/callback",         serve_callback)
    app.router.add_get( "/callbackspotify",  serve_callback_spotify)
    app.router.add_get( "/qollanma",         serve_qollanma)
    app.router.add_get( "/privacy",          serve_privacy)
    app.router.add_get( "/terms",            serve_terms)
    app.router.add_post("/api/auth/google",  api_auth_google)
    app.router.add_get( "/api/auth/me",      api_auth_me)
    app.router.add_post("/api/auth/logout",  api_auth_logout)
    app.router.add_get( "/api/auth/spotify", api_auth_spotify)
    app.router.add_post("/api/auth/spotify/callback", api_auth_spotify_callback)
    app.router.add_get( "/api/auth/spotify/status", api_spotify_status)
    app.router.add_post("/api/telegram/link/start", api_telegram_link_start)
    app.router.add_get( "/api/telegram/link/status", api_telegram_link_status)
    app.router.add_get( "/api/telegram/profile", api_telegram_profile)
    app.router.add_post("/api/profile/saved", api_profile_saved)
    # OAuth — AniList
    app.router.add_get( "/api/auth/anilist",         api_auth_anilist)
    app.router.add_get( "/api/auth/anilist/status",  api_anilist_status)
    app.router.add_get( "/callback/anilist",         callback_anilist)
    # AniList search
    app.router.add_get( "/api/anilist/search",       api_anilist_search)
    # Game
    app.router.add_post("/api/game/start",          api_game_start)
    app.router.add_get( "/api/game/{game_id}",       api_game_state)
    app.router.add_post("/api/game/{game_id}/move",  api_game_move)
    return app


async def start_web_server():
    app = create_app()
    runner = web.AppRunner(app)
    await runner.setup()
    site = web.TCPSite(runner, "0.0.0.0", WEB_PORT)
    await site.start()
    print(f"🌐 Web server: http://0.0.0.0:{WEB_PORT}")
    return runner
