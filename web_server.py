import sys
try:
    sys.stdout.reconfigure(encoding='utf-8')
    sys.stderr.reconfigure(encoding='utf-8')
except AttributeError:
    pass

import re
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
import tempfile
import shutil
import uuid
from pathlib import Path
import aiosqlite
import aiohttp
from aiohttp import web
from urllib.parse import urlencode, urlparse

from config import (
    DB_PATH, BOT_TOKEN, BOT_USERNAME,
    SUPER_ADMIN_ID, ADMIN_IDS,
    GOOGLE_CLIENT_ID, GOOGLE_CLIENT_SECRET, GOOGLE_REDIRECT_URI,
    SPOTIFY_CLIENT_ID, SPOTIFY_CLIENT_SECRET, SPOTIFY_REDIRECT_URI,
    ANILIST_CLIENT_ID, ANILIST_CLIENT_SECRET, ANILIST_REDIRECT_URI,
    AI_API_KEY, AI_BASE_URL, AI_MODEL,
    WEB_PUBLIC_ORIGIN, WEB_SESSION_TTL_HOURS,
    WEB_RATE_LIMIT_PER_MIN, WEB_API_RATE_LIMIT_PER_MIN,
    WEB_MEDIA_RATE_LIMIT_PER_MIN, WEB_MAX_CONCURRENT_REQUESTS,
    WEB_REQUEST_TIMEOUT_SECONDS,
    GROQ_API_KEY, GROQ_MODEL_GENERAL, GROQ_MODEL_CREATIVE, GROQ_MODEL_CODER,
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


def _public_origin(request: web.Request) -> str:
    if WEB_PUBLIC_ORIGIN:
        return WEB_PUBLIC_ORIGIN
    proto = (request.headers.get("X-Forwarded-Proto") or request.scheme or "https").split(",", 1)[0].strip()
    host = (request.headers.get("X-Forwarded-Host") or request.host or "").split(",", 1)[0].strip()
    if proto not in {"http", "https"}:
        proto = "https"
    return f"{proto}://{host}".rstrip("/")


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
_admin_web_sessions: dict[str, dict] = {}
_admin_2fa_sessions: dict[str, dict] = {}
ADMIN_2FA_TTL_SECONDS = 300

# Railway Bucket S3-compatible sozlamalari.
RAILWAY_BUCKET_ENDPOINT = os.getenv("RAILWAY_BUCKET_ENDPOINT", os.getenv("ENDPOINT", "")).strip()
RAILWAY_BUCKET_REGION = os.getenv("RAILWAY_BUCKET_REGION", os.getenv("REGION", "auto")).strip() or "auto"
RAILWAY_BUCKET_NAME = os.getenv("RAILWAY_BUCKET_NAME", os.getenv("BUCKET", "")).strip()
RAILWAY_BUCKET_ACCESS_KEY_ID = os.getenv("RAILWAY_BUCKET_ACCESS_KEY_ID", os.getenv("ACCESS_KEY_ID", "")).strip()
RAILWAY_BUCKET_SECRET_ACCESS_KEY = os.getenv("RAILWAY_BUCKET_SECRET_ACCESS_KEY", os.getenv("SECRET_ACCESS_KEY", "")).strip()
RAILWAY_BUCKET_PUBLIC_URL = os.getenv("RAILWAY_BUCKET_PUBLIC_URL", os.getenv("BUCKET_PUBLIC_URL", "")).strip().rstrip("/")
if not RAILWAY_BUCKET_PUBLIC_URL and RAILWAY_BUCKET_ENDPOINT and RAILWAY_BUCKET_NAME:
    RAILWAY_BUCKET_PUBLIC_URL = f"{RAILWAY_BUCKET_ENDPOINT.rstrip('/')}/{RAILWAY_BUCKET_NAME}"

INSTAGRAM_ACCESS_TOKEN = os.getenv("INSTAGRAM_ACCESS_TOKEN", "").strip()
INSTAGRAM_USER_ID = os.getenv("INSTAGRAM_USER_ID", "").strip()
INSTAGRAM_API_VERSION = os.getenv("INSTAGRAM_API_VERSION", "v24.0").strip() or "v24.0"
INSTAGRAM_API_BASE = f"https://graph.instagram.com/{INSTAGRAM_API_VERSION}"


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
        req_headers = {}
        range_header = request.headers.get("Range")
        if range_header:
            req_headers["Range"] = range_header

        async with aiohttp.ClientSession() as session:
            async with session.get(info["url"], headers=req_headers) as tg_resp:
                content_type = tg_resp.headers.get("Content-Type", "application/octet-stream")
                content_length = tg_resp.headers.get("Content-Length")
                content_range = tg_resp.headers.get("Content-Range")
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
    anime_id = request.match_info["anime_id"]
    async with aiosqlite.connect(DB_PATH) as db:
        async with db.execute("SELECT rams FROM animelar WHERE id=?", (anime_id,)) as c:
            row = await c.fetchone()

    if not row or not row[0]:
        return web.json_response({"type": "none", "url": None})

    rams = row[0]
    if rams.startswith("http"):
        low = rams.lower()
        if any(low.endswith(e) for e in [".mp4", ".mov", ".avi", ".mkv", ".webm"]):
            return web.json_response({"type": "video", "url": rams})
        return web.json_response({"type": "photo", "url": rams})

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
                           COALESCE(a.tavsif,'') as tavsif,
                           COALESCE(a.filler_info,'') as filler_info
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
                           COALESCE(a.tavsif,'') as tavsif,
                           COALESCE(a.filler_info,'') as filler_info
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
                "filler_info": row[15] or "",
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
                   COALESCE(a.tavsif,'') as tavsif,
                   COALESCE(a.filler_info,'') as filler_info
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
            "filler_info": row[15] or "",
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

    origin = _public_origin(request)
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
    anime_id = request.match_info["anime_id"]
    if _is_html_request(request):
        return await _poster_page(request, anime_id)

    async with aiosqlite.connect(DB_PATH) as db:
        async with db.execute("SELECT rams FROM animelar WHERE id=?", (anime_id,)) as c:
            row = await c.fetchone()
    if row and row[0]:
        rams = row[0]
        if rams.startswith("http"):
            raise web.HTTPFound(rams)
        info = await resolve_file_id(rams)
        if info["url"]:
            raise web.HTTPFound(f"/media/{rams}")
    fallback_url = await _fallback_poster_for_anime(anime_id)
    if fallback_url:
        raise web.HTTPFound(fallback_url)
    raise web.HTTPNotFound()


async def api_bot_info(request):
    return web.json_response(await get_bot_info())


async def get_bot_info() -> dict:
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
        html_content = f.read()

    html_content = html_content.replace("{{BOT_USERNAME}}", BOT_USERNAME or "")
    html_content = html_content.replace("{{GOOGLE_CLIENT_ID}}", GOOGLE_CLIENT_ID or "")

    if meta:
        import html as html_module
        title = html_module.escape(meta.get("title") or "AnimeUZ Official", quote=True)
        description = html_module.escape(meta.get("description") or "Anime poster va ma'lumotlari", quote=True)
        image = html_module.escape(meta.get("image") or "/bot-icon", quote=True)
        url = html_module.escape(meta.get("url") or request.url.human_repr(), quote=True)
        html_content = html_content.replace("<title>AnimeUZ Official</title>", f"<title>{title}</title>")
        html_content = html_content.replace(
            '<meta property="og:image" content="/bot-icon">',
            (
                '<meta property="og:type" content="website">\n'
                f'<meta property="og:title" content="{title}">\n'
                f'<meta property="og:description" content="{description}">\n'
                f'<meta property="og:url" content="{url}">\n'
                f'<meta property="og:image" content="{image}">'
            ),
        )
        html_content = html_content.replace(
            '<meta name="twitter:image" content="/bot-icon">',
            (
                '<meta name="twitter:card" content="summary_large_image">\n'
                f'<meta name="twitter:title" content="{title}">\n'
                f'<meta name="twitter:description" content="{description}">\n'
                f'<meta name="twitter:image" content="{image}">'
            ),
        )
    return web.Response(text=html_content, content_type="text/html", charset="utf-8")


async def api_admins(request):
    from config import ADMIN_IDS, SUPER_ADMIN_ID

    config_ids = set([SUPER_ADMIN_ID] + ADMIN_IDS)

    async with aiosqlite.connect(DB_PATH) as db:
        async with db.execute("SELECT user_id FROM admins") as c:
            rows = await c.fetchall()
    db_ids = {r[0] for r in rows}

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


# ─── SSE Event Bus ────────────────────────────────────────────────────────────
_event_history = deque(maxlen=50)
_sse_clients: list = []


def _ts():
    return datetime.now().strftime("%H:%M")


async def push_event(event_type: str, text: str, color: str = "c"):
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
    resp = web.StreamResponse(headers={
        "Content-Type": "text/event-stream",
        "Cache-Control": "no-cache",
        "X-Accel-Buffering": "no",
        "Access-Control-Allow-Origin": "*",
    })
    await resp.prepare(request)

    q: asyncio.Queue = asyncio.Queue()
    _sse_clients.append(q)

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
    session_secret = WEB_ADMIN_TOKEN
    session_token = request.cookies.get(ADMIN_SESSION_COOKIE, "").strip()
    if session_secret and secrets.compare_digest(session_token, session_secret):
        return True
    session = _admin_web_sessions.get(session_token)
    if session and not session.get("revoked") and time.time() - float(session.get("created_ts") or 0) <= SESSION_TTL_SECONDS:
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


def _clean_description(html_text: str) -> str:
    if not html_text:
        return ""
    clean = re.sub(r'<[^>]+>', '', html_text)
    clean = re.sub(r'__|\*|`|#', '', clean)
    clean = re.sub(r'\s+', ' ', clean)
    return clean.strip()


async def _is_web_admin_id(user_id: int) -> bool:
    if user_id == SUPER_ADMIN_ID or user_id in ADMIN_IDS:
        return True
    try:
        async with aiosqlite.connect(DB_PATH) as db:
            async with db.execute("SELECT 1 FROM admins WHERE user_id=? LIMIT 1", (user_id,)) as c:
                return await c.fetchone() is not None
    except Exception:
        return False


def _cleanup_admin_auth() -> None:
    now = time.time()
    for key, item in list(_admin_2fa_sessions.items()):
        if now - float(item.get("created_ts") or 0) > ADMIN_2FA_TTL_SECONDS:
            item["status"] = "expired"
    for token, item in list(_admin_web_sessions.items()):
        if item.get("revoked") or now - float(item.get("created_ts") or 0) > SESSION_TTL_SECONDS:
            _admin_web_sessions.pop(token, None)


async def _send_admin_2fa_request(session_id: str, admin_id: int, request: web.Request) -> bool:
    if not BOT_TOKEN:
        return False
    origin = _public_origin(request)
    ip = _client_ip(request)
    text = (
        "🔐 <b>Admin panelga kirish so'rovi</b>\n\n"
        f"👤 Telegram ID: <code>{admin_id}</code>\n"
        f"🌐 IP: <code>{html.escape(ip)}</code>\n"
        f"🔗 Sayt: {html.escape(origin)}\n\n"
        "Agar bu siz bo'lsangiz, tasdiqlang."
    )
    keyboard = {
        "inline_keyboard": [[
            {"text": "✅ Tasdiqlash", "callback_data": f"web2fa:approve:{session_id}"},
            {"text": "❌ Bekor qilish", "callback_data": f"web2fa:reject:{session_id}"},
        ]]
    }
    try:
        async with aiohttp.ClientSession() as session:
            async with session.post(
                f"https://api.telegram.org/bot{BOT_TOKEN}/sendMessage",
                json={
                    "chat_id": admin_id,
                    "text": text,
                    "parse_mode": "HTML",
                    "reply_markup": keyboard,
                    "disable_web_page_preview": True,
                },
                timeout=aiohttp.ClientTimeout(total=12),
            ) as resp:
                data = await resp.json()
        if data.get("ok"):
            _admin_2fa_sessions[session_id]["message_id"] = data.get("result", {}).get("message_id")
            return True
    except Exception:
        pass
    return False


def approve_admin_2fa(session_id: str, admin_id: int) -> tuple[bool, str]:
    session = _admin_2fa_sessions.get(session_id)
    if not session:
        return False, "So'rov topilmadi yoki eskirgan."
    if int(session.get("admin_id") or 0) != int(admin_id):
        return False, "Bu so'rov sizga tegishli emas."
    if session.get("status") not in {"pending", "approved"}:
        return False, "So'rov allaqachon yopilgan."
    token = session.get("session_token") or _new_token()
    session.update({"status": "approved", "approved_ts": time.time(), "session_token": token})
    _admin_web_sessions[token] = {"admin_id": admin_id, "created_ts": time.time(), "revoked": False}
    return True, "Admin panel kirishi tasdiqlandi."


def reject_admin_2fa(session_id: str, admin_id: int) -> tuple[bool, str]:
    session = _admin_2fa_sessions.get(session_id)
    if not session:
        return False, "So'rov topilmadi yoki eskirgan."
    if int(session.get("admin_id") or 0) != int(admin_id):
        return False, "Bu so'rov sizga tegishli emas."
    session["status"] = "rejected"
    return True, "Admin panel kirishi bekor qilindi."


def disconnect_admin_2fa(session_id: str, admin_id: int) -> tuple[bool, str]:
    session = _admin_2fa_sessions.get(session_id)
    if not session:
        return False, "Session topilmadi."
    if int(session.get("admin_id") or 0) != int(admin_id):
        return False, "Bu session sizga tegishli emas."
    token = session.get("session_token", "")
    if token:
        _admin_web_sessions.pop(token, None)
    session["status"] = "disconnected"
    session["revoked"] = True
    return True, "Admin panel sessioni uzildi."


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


async def _fallback_poster_for_anime(anime_id: str) -> str:
    try:
        async with aiosqlite.connect(DB_PATH) as db:
            async with db.execute("SELECT nom, COALESCE(nom_en,'') FROM animelar WHERE id=?", (anime_id,)) as c:
                row = await c.fetchone()
        if not row:
            return ""
        for title in (row[1], row[0]):
            poster = await _fetch_anilist_poster(title)
            if poster.get("poster_url"):
                return poster["poster_url"]
    except Exception:
        return ""
    return ""


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
        "filler_info": _clean_text(body.get("filler_info")),
        "filler_image": _clean_text(body.get("filler_image")),
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
        if not values["tavsif"]:
            values["tavsif"] = f"{values['nom']} — {values['janri'] or 'turli'} janridagi anime. Syujetida qiziqarli voqealar rivoji mavjud."
        meta["tavsif_source"] = "ai" if values["tavsif"] else "empty"
    else:
        meta["tavsif_source"] = "manual"

    return values, meta


async def _apply_season_link(db: aiosqlite.Connection, anime_id: int, body: dict) -> dict:
    main_raw = _clean_text(body.get("link_season_id"))
    number_raw = _clean_text(body.get("season_number"), "1") or "1"
    try:
        season_number = max(1, int(number_raw))
    except ValueError:
        raise ValueError("Fasl raqami noto'g'ri")

    if not main_raw:
        return {"season_linked": False}
    try:
        main_id = int(main_raw)
    except ValueError:
        raise ValueError("Ulanadigan anime kodi noto'g'ri")

    async with db.execute(
        "SELECT id, nom, COALESCE(season_group_id, id) FROM animelar WHERE id=?",
        (main_id,)
    ) as c:
        main = await c.fetchone()
    async with db.execute("SELECT id, nom FROM animelar WHERE id=?", (anime_id,)) as c:
        season = await c.fetchone()
    if not main or not season:
        raise ValueError("Linkseason uchun tanlangan anime topilmadi")

    group_id = main[2] or main_id
    await db.execute(
        "UPDATE animelar SET season_group_id=?, season_number=1 WHERE id=? AND (season_number IS NULL OR season_number < 1)",
        (group_id, main_id),
    )
    await db.execute(
        "UPDATE animelar SET season_group_id=?, season_number=? WHERE id=?",
        (group_id, season_number, anime_id),
    )
    return {
        "season_linked": True,
        "season_group_id": group_id,
        "season_main_id": main_id,
        "season_number": season_number,
    }


def _bot_start_link(payload: str) -> str:
    bot_username = (BOT_USERNAME or "").lstrip("@")
    return f"https://t.me/{bot_username}?start={payload}" if bot_username else ""


async def serve_admin(request):
    path = os.path.join(WEBAPP_DIR, "admin.html")
    with open(path, "r", encoding="utf-8") as f:
        page = f.read()
    page = page.replace("{{ADMIN_ACCESS}}", "1" if _admin_authorized(request) else "0")
    return web.Response(text=page, content_type="text/html", charset="utf-8")


async def api_admin_login(request):
    _cleanup_admin_auth()
    body = await request.json()
    login = _clean_text(body.get("login"))
    password = _clean_text(body.get("password"))
    admin_id_raw = _clean_text(body.get("telegram_id"))

    if not ADMIN_LOGIN or not ADMIN_PASSWORD:
        return web.json_response({"ok": False, "error": "ADMIN_LOGIN va ADMIN_PASSWORD serverda sozlanmagan"}, status=503)
    if not secrets.compare_digest(login, ADMIN_LOGIN) or not secrets.compare_digest(password, ADMIN_PASSWORD):
        return web.json_response({"ok": False, "error": "Login yoki parol noto'g'ri"}, status=401)
    try:
        admin_id = int(admin_id_raw)
    except (TypeError, ValueError):
        return web.json_response({"ok": False, "error": "Telegram ID raqam bo'lishi kerak"}, status=400)
    if not await _is_web_admin_id(admin_id):
        return web.json_response({"ok": False, "error": "Bu Telegram ID adminlar ro'yxatida yo'q"}, status=403)

    session_id = secrets.token_urlsafe(18)
    _admin_2fa_sessions[session_id] = {
        "admin_id": admin_id,
        "status": "pending",
        "created_ts": time.time(),
        "ip": _client_ip(request),
        "session_token": "",
    }
    sent = await _send_admin_2fa_request(session_id, admin_id, request)
    if not sent:
        _admin_2fa_sessions[session_id]["status"] = "send_failed"
        return web.json_response({"ok": False, "error": "Telegramga tasdiqlash xabari yuborilmadi"}, status=502)
    return web.json_response({"ok": True, "session_id": session_id, "ttl": ADMIN_2FA_TTL_SECONDS})


async def api_admin_login_status(request):
    _cleanup_admin_auth()
    session_id = request.rel_url.query.get("session_id", "").strip()
    session = _admin_2fa_sessions.get(session_id)
    if not session:
        return web.json_response({"ok": False, "error": "2FA so'rovi topilmadi"}, status=404)
    status = session.get("status", "pending")
    resp = web.json_response({"ok": True, "status": status})
    if status == "approved" and session.get("session_token"):
        resp.set_cookie(
            ADMIN_SESSION_COOKIE,
            session["session_token"],
            max_age=SESSION_TTL_SECONDS,
            httponly=True,
            secure=False,
            samesite="Lax",
        )
    return resp


async def api_admin_logout(request):
    token = request.cookies.get(ADMIN_SESSION_COOKIE, "").strip()
    if token:
        _admin_web_sessions.pop(token, None)
    resp = web.json_response({"ok": True})
    resp.del_cookie(ADMIN_SESSION_COOKIE)
    resp.del_cookie("admin_token")
    return resp


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
               COALESCE(a.season_number,1), COALESCE(a.filler_info,''), COALESCE(a.filler_image,''),
               COUNT(d.data_id) as ep_count
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
        "tavsif", "nom_en", "yosh_toifa", "season_group_id", "season_number",
        "filler_info", "filler_image", "ep_count"
    ]
    animes = []
    for row in rows:
        item = dict(zip(keys, row))
        item["rams_url"] = _poster_url(item["id"], item.get("rams") or "")
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
                aniType, fandub, kanal, yosh_toifa, tavsif, nom_en, filler_info, filler_image
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, 0, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """, (
            values["nom"], values["rams"], values["qismi"], values["davlat"], values["tili"],
            values["yili"], values["janri"], sana, values["aniType"], values["fandub"],
            values["kanal"], values["yosh_toifa"], values["tavsif"], values["nom_en"],
            values["filler_info"], values["filler_image"],
        ))
        async with db.execute("SELECT last_insert_rowid()") as c:
            anime_id = (await c.fetchone())[0]
        await db.execute("UPDATE animelar SET season_group_id=?, season_number=1 WHERE id=?", (anime_id, anime_id))
        try:
            season_meta = await _apply_season_link(db, anime_id, body)
        except ValueError as exc:
            await db.rollback()
            return web.json_response({"ok": False, "error": str(exc)}, status=400)
        meta.update(season_meta)
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
        try:
            season_meta = await _apply_season_link(db, anime_id, body)
        except ValueError as exc:
            await db.rollback()
            return web.json_response({"ok": False, "error": str(exc)}, status=400)
        meta.update(season_meta)
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


# ── Anime edits ─────────────────────────────────────────────────────────────
def _normalise_edit_tag(value: str) -> str:
    value = (value or "").strip().lower().lstrip("#")
    value = re.sub(r"[^\w-]", "", value, flags=re.UNICODE)
    return value[:120]


def _extract_edit_tags(*texts: str) -> list[str]:
    found = []
    for text in texts:
        for tag in re.findall(r"(?<!\w)#([\w-]+)", text or "", flags=re.UNICODE):
            clean = _normalise_edit_tag(tag)
            if clean and clean not in found:
                found.append(clean)
    return found[:30]


def _validate_instagram_url(url: str) -> str:
    url = (url or "").strip()
    parsed = urlparse(url)
    host = (parsed.hostname or "").lower()
    if parsed.scheme not in {"http", "https"} or not (host == "instagram.com" or host.endswith(".instagram.com")):
        raise ValueError("Faqat Instagram post/reel havolasi qabul qilinadi")
    if not parsed.path or parsed.path == "/":
        raise ValueError("Instagram post yoki reel havolasini kiriting")
    return url


def _bucket_is_configured() -> bool:
    return bool(RAILWAY_BUCKET_ENDPOINT and RAILWAY_BUCKET_NAME and RAILWAY_BUCKET_ACCESS_KEY_ID and RAILWAY_BUCKET_SECRET_ACCESS_KEY and RAILWAY_BUCKET_PUBLIC_URL)


def _normalise_instagram_permalink(url: str) -> str:
    parsed = urlparse(url)
    return f"https://www.instagram.com{parsed.path.rstrip('/')}".lower()


async def _instagram_graph_media(source_url: str, supplied_media_id: str = "") -> dict:
    if not (INSTAGRAM_ACCESS_TOKEN and INSTAGRAM_USER_ID):
        raise ValueError("Instagram API sozlanmagan")
    fields = "id,caption,media_type,media_product_type,media_url,thumbnail_url,permalink,username,timestamp"
    params = {"fields": fields, "access_token": INSTAGRAM_ACCESS_TOKEN}
    timeout = aiohttp.ClientTimeout(total=30)
    async with aiohttp.ClientSession(timeout=timeout) as session:
        if supplied_media_id:
            async with session.get(f"{INSTAGRAM_API_BASE}/{supplied_media_id}", params=params) as response:
                data = await response.json(content_type=None)
                if response.status >= 400:
                    raise ValueError(data.get("error", {}).get("message", "Instagram media ID topilmadi"))
                return data

        wanted = _normalise_instagram_permalink(source_url)
        next_url = f"{INSTAGRAM_API_BASE}/{INSTAGRAM_USER_ID}/media"
        for _ in range(5):
            async with session.get(next_url, params=params if next_url.endswith("/media") else None) as response:
                data = await response.json(content_type=None)
                if response.status >= 400:
                    raise ValueError(data.get("error", {}).get("message", "Instagram media ro'yxatini olishda xatolik"))
            for media in data.get("data", []):
                if _normalise_instagram_permalink(media.get("permalink", "")) == wanted:
                    return media
            next_url = (data.get("paging") or {}).get("next")
            if not next_url:
                break
    raise ValueError("Bu havola ulangan Instagram Business/Creator akkauntida topilmadi")


async def _download_instagram_api_video(media: dict) -> tuple[dict, Path, Path]:
    media_url = media.get("media_url", "")
    if not media_url or media.get("media_type") not in {"VIDEO", "REELS"}:
        raise ValueError("Tanlangan Instagram media video yoki reel emas")
    temp_dir = Path(tempfile.mkdtemp(prefix="animeuz-ig-api-"))
    file_path = temp_dir / "source.mp4"
    try:
        size = 0
        timeout = aiohttp.ClientTimeout(total=300)
        async with aiohttp.ClientSession(timeout=timeout) as session:
            async with session.get(media_url) as response:
                if response.status >= 400:
                    raise ValueError("Instagram video faylini olish imkonsiz")
                with open(file_path, "wb") as output:
                    async for chunk in response.content.iter_chunked(256 * 1024):
                        size += len(chunk)
                        if size > 250 * 1024 * 1024:
                            raise ValueError("Video 250 MB limitdan katta")
                        output.write(chunk)
        if not size:
            raise ValueError("Instagram video fayli bo'sh")
        return media, file_path, temp_dir
    except Exception:
        shutil.rmtree(temp_dir, ignore_errors=True)
        raise


def _download_instagram_edit(source_url: str) -> tuple[dict, Path, Path]:
    import yt_dlp
    temp_dir = Path(tempfile.mkdtemp(prefix="animeuz-edit-"))
    options = {
        "outtmpl": str(temp_dir / "source.%(ext)s"),
        "format": "best[ext=mp4]/best[ext=webm]",
        "noplaylist": True,
        "quiet": True,
        "no_warnings": True,
        "restrictfilenames": True,
        "max_filesize": 250 * 1024 * 1024,
    }
    try:
        with yt_dlp.YoutubeDL(options) as ydl:
            info = ydl.extract_info(source_url, download=True)
            if info.get("entries"):
                info = next((item for item in info["entries"] if item), info)
        files = [p for p in temp_dir.iterdir() if p.is_file() and p.suffix.lower() in {".mp4", ".webm", ".mkv", ".mov"}]
        if not files:
            raise ValueError("Instagram videosi yuklab olinmadi yoki yopiq")
        return info, max(files, key=lambda item: item.stat().st_size), temp_dir
    except Exception:
        shutil.rmtree(temp_dir, ignore_errors=True)
        raise


def _upload_edit_to_bucket(file_path: Path, key: str) -> str:
    import boto3
    from botocore.config import Config
    client = boto3.client(
        "s3", endpoint_url=RAILWAY_BUCKET_ENDPOINT, region_name=RAILWAY_BUCKET_REGION,
        aws_access_key_id=RAILWAY_BUCKET_ACCESS_KEY_ID,
        aws_secret_access_key=RAILWAY_BUCKET_SECRET_ACCESS_KEY,
        config=Config(signature_version="s3v4"),
    )
    content_type = "video/mp4" if file_path.suffix.lower() == ".mp4" else "video/webm"
    client.upload_file(str(file_path), RAILWAY_BUCKET_NAME, key, ExtraArgs={"ContentType": content_type})
    return f"{RAILWAY_BUCKET_PUBLIC_URL}/{key}"


async def api_anime_edits(request):
    query = _normalise_edit_tag(request.rel_url.query.get("tag", ""))
    search = (request.rel_url.query.get("q", "") or "").strip().lower()[:120]
    try:
        async with aiosqlite.connect(DB_PATH) as db:
            db.row_factory = aiosqlite.Row
            where, params = [], []
            if query:
                where.append("EXISTS (SELECT 1 FROM anime_edit_tags t WHERE t.edit_id=e.id AND t.tag=?)")
                params.append(query)
            if search:
                where.append("(LOWER(e.title) LIKE ? OR LOWER(e.description) LIKE ? OR EXISTS (SELECT 1 FROM anime_edit_tags t WHERE t.edit_id=e.id AND t.tag LIKE ?))")
                params.extend([f"%{search}%", f"%{search}%", f"%{search}%"])
            clause = " WHERE " + " AND ".join(where) if where else ""
            sql = f"SELECT e.* FROM anime_edits e{clause} ORDER BY e.id DESC LIMIT 80"
            rows = await (await db.execute(sql, params)).fetchall()
            items = []
            for row in rows:
                tags = await (await db.execute("SELECT tag FROM anime_edit_tags WHERE edit_id=? ORDER BY tag", (row["id"],))).fetchall()
                item = dict(row)
                item["tags"] = [tag[0] for tag in tags]
                items.append(item)
        return web.json_response({"ok": True, "edits": items, "total": len(items)})
    except Exception:
        return web.json_response({"ok": False, "error": "Edits ro'yxatini olishda xatolik"}, status=500)


async def api_admin_anime_edits(request):
    if not _admin_authorized(request):
        return _admin_denied()
    return await api_anime_edits(request)


async def api_admin_import_anime_edit(request):
    if not _admin_authorized(request):
        return _admin_denied()
    if not _bucket_is_configured():
        return web.json_response({"ok": False, "error": "Railway Bucket sozlanmagan. BUCKET, ENDPOINT, REGION, ACCESS_KEY_ID va SECRET_ACCESS_KEY variables ni tekshiring."}, status=503)
    temp_dir = None
    try:
        body = await request.json()
        source_url = _validate_instagram_url(body.get("instagram_url", ""))
        async with aiosqlite.connect(DB_PATH) as db:
            duplicate = await (await db.execute("SELECT id FROM anime_edits WHERE source_url=?", (source_url,))).fetchone()
        if duplicate:
            return web.json_response({"ok": False, "error": "Bu Instagram havolasi avval qo'shilgan"}, status=409)

        media_id = _clean_text(body.get("instagram_media_id", ""))[:64]
        if INSTAGRAM_ACCESS_TOKEN and INSTAGRAM_USER_ID:
            info = await _instagram_graph_media(source_url, media_id)
            info, file_path, temp_dir = await _download_instagram_api_video(info)
        else:
            info, file_path, temp_dir = await asyncio.to_thread(_download_instagram_edit, source_url)
        ext = file_path.suffix.lower() if file_path.suffix.lower() in {".mp4", ".webm"} else ".mp4"
        key = f"anime-edits/{datetime.utcnow():%Y/%m}/{uuid.uuid4().hex}{ext}"
        video_url = await asyncio.to_thread(_upload_edit_to_bucket, file_path, key)
        title = _clean_text(body.get("title") or info.get("title") or (info.get("caption") or "").split("\n", 1)[0] or "Anime edit")[:512]
        description = _clean_text(body.get("description") or info.get("description") or "")[:5000]
        if not description:
            description = _clean_text(info.get("caption") or "")[:5000]
        author = _clean_text(info.get("uploader") or info.get("channel") or info.get("username") or "")[:255]
        manual_tags = body.get("tags") or ""
        tags = _extract_edit_tags(title, description, manual_tags)
        for tag in re.split(r"[,\s]+", manual_tags):
            tag = _normalise_edit_tag(tag)
            if tag and tag not in tags and len(tags) < 30:
                tags.append(tag)
        async with aiosqlite.connect(DB_PATH) as db:
            cur = await db.execute("INSERT INTO anime_edits (source_url, video_url, title, description, author) VALUES (?, ?, ?, ?, ?)", (source_url, video_url, title, description, author))
            edit_id = cur.lastrowid
            await db.executemany("INSERT OR IGNORE INTO anime_edit_tags (edit_id, tag) VALUES (?, ?)", [(edit_id, tag) for tag in tags])
            await db.commit()
        return web.json_response({"ok": True, "id": edit_id, "video_url": video_url, "tags": tags, "title": title})
    except ValueError as exc:
        return web.json_response({"ok": False, "error": str(exc)}, status=400)
    except Exception as exc:
        print(f"Anime edit import xatosi: {exc}")
        return web.json_response({"ok": False, "error": "Video yuklab olinmadi. Havola ochiq ekanini tekshiring."}, status=502)
    finally:
        if temp_dir:
            shutil.rmtree(temp_dir, ignore_errors=True)


async def api_admin_delete_anime_edit(request):
    if not _admin_authorized(request):
        return _admin_denied()
    try:
        edit_id = int(request.match_info["edit_id"])
        async with aiosqlite.connect(DB_PATH) as db:
            await db.execute("DELETE FROM anime_edit_tags WHERE edit_id=?", (edit_id,))
            cur = await db.execute("DELETE FROM anime_edits WHERE id=?", (edit_id,))
            await db.commit()
        if not cur.rowcount:
            return web.json_response({"ok": False, "error": "Edit topilmadi"}, status=404)
        return web.json_response({"ok": True})
    except ValueError:
        return web.json_response({"ok": False, "error": "Noto'g'ri edit ID"}, status=400)


def _extract_anime_search_query(user_msg: str) -> str:
    text = user_msg.lower()
    if text.startswith("/ai"):
        text = text[3:]
    
    stopwords = {
        "menga", "haqida", "ma'lumot", "malumot", "ber", "ayt", "yoz", 
        "tavsif", "topib", "qidir", "qidirish", "anime", "animeni", 
        "animelar", "haqidaxabar", "haqida,", "tasvirlab", "bormi", "bormi?",
        "kinosi", "multfilm", "multfilmi", "uz", "uzbek", "tarjima", "o'zbekcha",
        "ozbekcha", "skachat", "yuklash", "ko'rish", "korish", "qanaqa", "qanday",
        "nima", "haqida", "haqida.", "haqida!"
    }
    
    verb_bases = {"ber", "ayt", "yoz", "qidir", "ko'rsat", "tavsiya"}
    all_bases = {"ber", "ayt", "yoz", "qidir", "ko'rsat", "tavsiya", "top"}
    valid_suffixes = (
        "ing", "ib", "gan", "asiz", "adi", "ish", "ishi", "ishni", 
        "ishga", "ibdi", "yapti", "adi", "sangiz", "sang", "sa", 
        "ay", "alik", "aylik", "sin"
    )
    
    words = re.findall(r"\b[a-zA-Z0-9'’`‘-]+\b", text)
    filtered_words = []
    for w in words:
        if w in stopwords:
            continue
            
        is_verb = False
        if w in verb_bases:
            is_verb = True
        else:
            for base in all_bases:
                if w.startswith(base):
                    suffix = w[len(base):]
                    if suffix in valid_suffixes:
                        is_verb = True
                        break
        
        if is_verb:
            continue
        if len(w) < 2:
            continue
        filtered_words.append(w)
    
    if not filtered_words:
        words_any = re.findall(r"\b[a-zA-Z0-9'’`‘-]+\b", user_msg)
        filtered_words = [w for w in words_any if len(w) >= 3][:3]
        
    return " ".join(filtered_words)


async def _search_anilist_internal(search_title: str) -> list[dict]:
    search_title = search_title.strip()
    if not search_title:
        return []
    try:
        async with aiohttp.ClientSession() as session:
            async with session.post(
                ANILIST_GRAPHQL_URL,
                json={
                    "query": ANILIST_POSTER_SEARCH_QUERY,
                    "variables": {"search": search_title},
                },
                headers={"Content-Type": "application/json", "Accept": "application/json"},
                timeout=aiohttp.ClientTimeout(total=8),
            ) as resp:
                data = await resp.json()
        
        if "errors" in data or "data" not in data:
            return []
            
        media_list = data.get("data", {}).get("Page", {}).get("media", []) or []
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
                "cover":        m["coverImage"].get("large") or m["coverImage"].get("medium") or "",
                "year":         m.get("startDate", {}).get("year"),
            })
        return results
    except Exception:
        return []


def select_groq_model(user_msg: str) -> str:
    """Prompt mazmuniga qarab to'g'ri Groq modelini tanlaydi (Mixture of Experts)."""
    msg_lower = user_msg.lower()
    
    creative_keywords = ["she'r", "sher", "hikoya", "tavsif yoz", "tasavvur qil", "creative", "poem", "story", "write a story", "ssenariy"]
    if any(kw in msg_lower for kwin creative_keywords):
        return GROQ_MODEL_CREATIVE
        
    code_keywords = ["kod", "code", "python", "javascript", "html", "css", "program", "dastur", "function", "class", "write a", "bug", "err", "exception"]
    if any(kw in msg_lower for kw in code_keywords):
        return GROQ_MODEL_CODER
        
    return GROQ_MODEL_GENERAL


def parse_tool_call(content: str):
    match = re.search(r"CALL:\s*([a-zA-Z0-9_]+)\(([^)]*)\)", content)
    if match:
        return match.group(1), match.group(2).strip()
    return None, None


async def run_tool(name: str, argument: str) -> str:
    print(f"🔧 Running tool {name} with argument: '{argument}'")
    if name == "search_local_anime":
        try:
            async with aiosqlite.connect(DB_PATH) as db:
                async with db.execute("SELECT id, nom, rams FROM animelar WHERE nom LIKE ? LIMIT 5", (f'%{argument}%',)) as c:
                    rows = await c.fetchall()
                    if not rows:
                        return "Mahalliy ma'lumotlar bazasida mos keladigan anime topilmadi."
                    results = []
                    for r in rows:
                        results.append(f"- ID: {r[0]}, Nom: {r[1]}, RasmURL: /poster/{r[0]}")
                    return "Mahalliy bazadan topilgan animelar:\n" + "\n".join(results)
        except Exception as e:
            return f"Mahalliy qidiruvda xatolik yuz berdi: {e}"

    elif name == "search_global_anilist":
        try:
            results = await _search_anilist_internal(argument)
            if not results:
                return "AniList global bazasida mos keladigan anime topilmadi."
            lines = []
            for r in results[:5]:
                lines.append(f"- {r['title']} (ID: {r['id']}, Yil: {r['year']})")
            return "AniList global qidiruv natijalari:\n" + "\n".join(lines)
        except Exception as e:
            return f"AniList global qidiruvda xatolik yuz berdi: {e}"

    elif name == "get_bot_stats":
        try:
            async with aiosqlite.connect(DB_PATH) as db:
                async with db.execute("SELECT COUNT(*) FROM users") as c:
                    users = (await c.fetchone())[0]
            admins_count = len(ADMIN_IDS) + 1
            return f"Bot statistikasi:\n- Jami foydalanuvchilar: {users} ta\n- Adminlar soni: {admins_count} ta"
        except Exception as e:
            return f"Statistikani olishda xatolik: {e}"

    return f"Noma'lum asbob (tool): {name}"


async def query_groq(model: str, messages: list):
    if not GROQ_API_KEY:
        print("⚠️ GROQ_API_KEY sozlanmagan!")
        return None
    payload = {
        "model": model,
        "messages": messages,
        "temperature": 0.5,
        "max_tokens": 1024
    }
    headers = {
        "Authorization": f"Bearer {GROQ_API_KEY}",
        "Content-Type": "application/json"
    }
    try:
        async with aiohttp.ClientSession() as session:
            async with session.post(
                "https://api.groq.com/openai/v1/chat/completions",
                json=payload,
                headers=headers,
                timeout=aiohttp.ClientTimeout(total=30)
            ) as resp:
                if resp.status == 200:
                    data = await resp.json()
                    return data.get("choices", [{}])[0].get("message", {}).get("content", "")
                else:
                    text = await resp.text()
                    print(f"❌ Groq response error (status {resp.status}): {text}")
    except Exception as e:
        print(f"⚠️ Groq API-ga ulanib bo'lmadi: {e}")
    return None


async def get_ai_reply(user_msg: str):
    system_prompt = (
        "Siz 'ANIME UZ' yordamchisi - 'UZGPT 4' modelisiz.\n"
        "Javoblaringizni faqat o'zbek tilida, qisqa va aniq bering.\n"
        "Sizda quyidagi asboblar (tools) bor:\n"
        "1. `search_local_anime(query)`: Mahalliy bazadan anime qidirish. Agar foydalanuvchi anime so'rasa, birinchi navbatda shu asbobdan foydalaning.\n"
        "   Mahalliy anime uchun javobingizda FAQAT [ANIME_CARD:ID|Nom|RasmURL] formatini ishlating.\n"
        "2. `search_global_anilist(query)`: AniList global bazasidan anime qidirish. Mahalliy bazada yo'q yoki qo'shimcha ma'lumot kerak bo'lsa foydalaning.\n"
        "   Bunda [ANIME_CARD] formatini ISHLATMANG, shunchaki tavsif va havola bering.\n"
        "3. `get_bot_stats()`: Bot a'zolari va adminlari soni haqida ma'lumot olish.\n\n"
        "Asbobni ishga tushirish uchun javobingiz ichida aniq quyidagi formatda chaqiruv qiling:\n"
        "CALL: tool_name(argument)\n"
        "Masalan: CALL: search_local_anime(Naruto)\n"
        "Siz ushbu chaqiruvni yozganingizdan so'ng, tizim asbob natijasini sizga taqdim etadi. Natijani olgandan keyingina foydalanuvchiga to'liq javob bering."
    )

    model = select_groq_model(user_msg)
    messages = [
        {"role": "system", "content": system_prompt},
        {"role": "user", "content": user_msg}
    ]
    
    loop_count = 0
    max_loops = 3
    groq_success = False
    final_reply = ""
    
    while loop_count < max_loops:
        loop_count += 1
        reply = await query_groq(model, messages)
        if reply is None:
            break
            
        groq_success = True
        messages.append({"role": "assistant", "content": reply})
        
        tool_name, tool_arg = parse_tool_call(reply)
        if tool_name:
            tool_result = await run_tool(tool_name, tool_arg)
            messages.append({"role": "user", "content": f"SYSTEM/TOOL RESULT ({tool_name}): {tool_result}"})
            continue
        else:
            final_reply = reply
            break
            
    if groq_success and final_reply:
        return final_reply

    print("⚠️ Groq orqali javob olib bo'lmadi. Zaxira OpenAI API-ga o'tilmoqda...")
    if not AI_API_KEY:
        return "AI xizmati vaqtincha ishlamayapti (Groq ham, OpenAI ham sozlanmagan)."

    try:
        async with aiosqlite.connect(DB_PATH) as db:
            async with db.execute("SELECT COUNT(*) FROM users") as c:
                users = (await c.fetchone())[0]
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

            anilist_matches = []
            search_q = _extract_anime_search_query(user_msg)
            if search_q:
                anilist_matches = await _search_anilist_internal(search_q)

        matched_str = ", ".join([f"{r[1]} (ID:{r[0]}, Img:/poster/{r[0]})" for r in matched_animes[:8]])
        anilist_str = ", ".join([f"{m['title']} ({m['year']})" for m in anilist_matches[:5]])

        openai_system = (
            f"Siz 'ANIME UZ' yordamchisisiz. Uzbek tilida javob bering.\n"
            f"Bot statistikasi: Jami a'zolar: {users}.\n"
            f"Adminlar: {admins_info}.\n"
            f"Bot ma'lumotlari: {bot_info}\n"
            f"Bazamizdagi mos kelgan animelar: {matched_str if matched_str else 'Yoq'}.\n"
            f"AniList global topilganlar: {anilist_str if anilist_str else 'Yoq'}.\n"
        )

        headers = {
            "Authorization": f"Bearer {AI_API_KEY}",
            "Content-Type": "application/json",
        }
        payload = {
            "model": AI_MODEL or "gpt-3.5-turbo",
            "messages": [
                {"role": "system", "content": openai_system},
                {"role": "user", "content": user_msg},
            ],
            "max_tokens": 500,
        }
        async with aiohttp.ClientSession() as session:
            async with session.post(
                f"{AI_BASE_URL.rstrip('/')}/chat/completions",
                json=payload,
                headers=headers,
                timeout=aiohttp.ClientTimeout(total=20),
            ) as resp:
                if resp.status == 200:
                    data = await resp.json()
                    return data["choices"][0]["message"]["content"].strip()
                else:
                    return "Xatolik yuz berdi, iltimos keyinroq qayta urinib ko'ring."
    except Exception as exc:
        print(f"OpenAI fallback error: {exc}")
        return "Tizimda vaqtincha texnik xatolik yuz berdi."


async def api_ai_chat(request):
    body = await request.json()
    user_msg = _clean_text(body.get("message"))
    if not user_msg:
        return web.json_response({"ok": False, "error": "Bo'sh xabar"}, status=400)
    reply = await get_ai_reply(user_msg)
    return web.json_response({"ok": True, "reply": reply})
