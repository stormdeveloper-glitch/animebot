"""AnimeUZ MCP server — Claude Code / boshqa MCP klientlar uchun.

Transport: MCP "Streamable HTTP" (stateless, faqat JSON javoblar), endpoint: POST /mcp
Tokenlar admin panelda yaratiladi (/admin → MCP bo'limi).

Xavfsizlik (OWASP Top 10:2025 bo'yicha qisqa xarita):
  A01 Broken Access Control      — har bir token faqat o'z scope'lari bo'yicha tool ko'radi/chaqiradi,
                                   default: hammasi taqiqlangan; admin endpointlari sessiya + Origin tekshiruvi.
  A02 Security Misconfiguration  — Origin allowlist (DNS rebinding), no-store, MCP_ENABLED kill-switch,
                                   umumiy xato matnlari (ichki tafsilot chiqmaydi).
  A03 Supply Chain Failures      — yangi tashqi kutubxona qo'shilmagan (faqat aiohttp/aiosqlite).
  A04 Cryptographic Failures     — 256-bit tasodifiy token, bazada faqat HMAC-SHA256 (pepper bilan) saqlanadi,
                                   token faqat bir marta ko'rsatiladi.
  A05 Injection                  — faqat parametrlangan SQL, LIKE escape, qat'iy argument validatsiyasi.
  A06 Insecure Design            — faqat o'qish tool'lari, natija hajmi cheklangan, majburiy muddat (max 90 kun),
                                   token va IP bo'yicha rate limit.
  A07 Authentication Failures    — noto'g'ri tokenlar uchun IP blok, muddat, bekor qilish (revoke).
  A08 Data Integrity Failures    — token yaratish faqat tasdiqlangan admin sessiyasidan, kim yaratgani yoziladi.
  A09 Logging & Alerting         — audit jurnali (sirlarsiz), Telegram ogohlantirishlari.
  A10 Exceptional Conditions     — har qanday xatoda "fail closed", umumiy javob, xato ID logga yoziladi.
"""

from __future__ import annotations

import asyncio
import hashlib
import hmac
import json
import logging
import os
import re
import secrets
import time
from collections import deque
from typing import Any, Awaitable, Callable

import aiohttp
import aiosqlite
from aiohttp import web

from config import BOT_TOKEN, DATA_DIR, DB_PATH, SUPER_ADMIN_ID, WEB_PUBLIC_ORIGIN

logger = logging.getLogger("mcp")

# ─── Sozlamalar ──────────────────────────────────────────────────────────────
SERVER_NAME = "animeuz"
SERVER_VERSION = "1.0.0"
SUPPORTED_PROTOCOL_VERSIONS = ("2025-06-18", "2025-03-26")
LATEST_PROTOCOL_VERSION = SUPPORTED_PROTOCOL_VERSIONS[0]
TOKEN_PREFIX = "amcp_"

MCP_ENABLED = os.getenv("MCP_ENABLED", "1").strip().lower() in {"1", "true", "yes", "on"}
MCP_RATE_LIMIT_PER_MIN = max(1, int(os.getenv("MCP_RATE_LIMIT_PER_MIN", "60")))
MCP_MAX_BODY_BYTES = 64 * 1024
MCP_MAX_ACTIVE_TOKENS = 20
MCP_MAX_EXPIRY_DAYS = 90
MCP_AUTH_FAIL_LIMIT = 10           # shuncha noto'g'ri urinish ...
MCP_AUTH_FAIL_WINDOW = 15 * 60     # ... shu oynada bo'lsa IP bloklanadi
MCP_AUTH_BLOCK_SECONDS = 30 * 60
MCP_AUDIT_RETENTION_DAYS = 30
MCP_TRUSTED_PROXY_HOPS = max(1, int(os.getenv("MCP_TRUSTED_PROXY_HOPS", "1")))
MCP_ALLOWED_ORIGINS = {
    o.strip().rstrip("/")
    for o in os.getenv("MCP_ALLOWED_ORIGINS", WEB_PUBLIC_ORIGIN or "").split(",")
    if o.strip()
}

SCOPES: dict[str, str] = {
    "stats:read": "Umumiy statistika (foydalanuvchi/anime/qism soni)",
    "anime:read": "Animelar va qismlar ro'yxatini o'qish",
    "users:read": "Oxirgi foydalanuvchilar (ID, status, ban) — shaxsiy ma'lumot!",
}

# DB yo'li testlarda almashtirilishi uchun modul darajasida
DB_FILE = DB_PATH

# ─── Ichki holat ─────────────────────────────────────────────────────────────
_tables_ready = False
_tables_lock = asyncio.Lock()
_auth_failures: dict[str, deque] = {}
_blocked_ips: dict[str, float] = {}
_token_hits: dict[int, deque] = {}
_admin_create_hits: dict[str, deque] = {}
_audit_counter = 0
_pepper_cache: bytes | None = None


# ═════════════════════════════════════════════════════════════════════════════
#  Kriptografiya (A04)
# ═════════════════════════════════════════════════════════════════════════════

def _load_pepper() -> bytes:
    """HMAC kaliti. Avval MCP_TOKEN_PEPPER env, bo'lmasa volume'dagi faylda saqlanadi."""
    global _pepper_cache
    if _pepper_cache:
        return _pepper_cache
    env = os.getenv("MCP_TOKEN_PEPPER", "").strip()
    if len(env) >= 32:
        _pepper_cache = env.encode()
        return _pepper_cache
    if env:
        logger.warning("MCP_TOKEN_PEPPER 32 belgidan qisqa — e'tiborsiz qoldirildi.")
    path = os.path.join(DATA_DIR, ".mcp_token_pepper")
    try:
        with open(path, "r", encoding="utf-8") as f:
            value = f.read().strip()
        if len(value) >= 32:
            _pepper_cache = value.encode()
            return _pepper_cache
    except FileNotFoundError:
        pass
    value = secrets.token_hex(32)
    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(fd, "w", encoding="utf-8") as f:
        f.write(value)
    logger.warning("MCP_TOKEN_PEPPER o'rnatilmagan — %s faylida yangi kalit yaratildi. "
                   "Railway'da MCP_TOKEN_PEPPER env o'rnatish tavsiya etiladi.", path)
    _pepper_cache = value.encode()
    return _pepper_cache


def _hash_token(token: str) -> str:
    return hmac.new(_load_pepper(), token.encode("utf-8"), hashlib.sha256).hexdigest()


def _generate_token() -> str:
    return TOKEN_PREFIX + secrets.token_urlsafe(32)  # 256 bit entropiya


# ═════════════════════════════════════════════════════════════════════════════
#  Baza
# ═════════════════════════════════════════════════════════════════════════════

async def _ensure_tables() -> None:
    global _tables_ready
    if _tables_ready:
        return
    async with _tables_lock:
        if _tables_ready:
            return
        async with aiosqlite.connect(DB_FILE) as db:
            await db.executescript("""
                CREATE TABLE IF NOT EXISTS mcp_tokens (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    name TEXT NOT NULL,
                    token_hash TEXT NOT NULL UNIQUE,
                    token_hint TEXT NOT NULL,
                    scopes TEXT NOT NULL,
                    created_by INTEGER NOT NULL DEFAULT 0,
                    created_at INTEGER NOT NULL,
                    expires_at INTEGER NOT NULL,
                    revoked_at INTEGER DEFAULT NULL,
                    last_used_at INTEGER DEFAULT NULL,
                    last_used_ip TEXT DEFAULT NULL,
                    use_count INTEGER NOT NULL DEFAULT 0
                );
                CREATE TABLE IF NOT EXISTS mcp_audit_log (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    ts INTEGER NOT NULL,
                    token_id INTEGER DEFAULT NULL,
                    ip TEXT NOT NULL,
                    event TEXT NOT NULL,
                    tool TEXT DEFAULT NULL,
                    status TEXT NOT NULL,
                    detail TEXT DEFAULT NULL
                );
                CREATE INDEX IF NOT EXISTS idx_mcp_audit_ts ON mcp_audit_log(ts);
            """)
            await db.commit()
        _tables_ready = True


async def _audit(ip: str, event: str, status: str, *, token_id: int | None = None,
                 tool: str | None = None, detail: str | None = None) -> None:
    """Audit yozuvi. Hech qachon token, parol yoki argument qiymatlari yozilmaydi (A09)."""
    global _audit_counter
    now = int(time.time())
    try:
        await _ensure_tables()
        async with aiosqlite.connect(DB_FILE) as db:
            await db.execute(
                "INSERT INTO mcp_audit_log (ts, token_id, ip, event, tool, status, detail) VALUES (?,?,?,?,?,?,?)",
                (now, token_id, ip[:64], event[:40], (tool or "")[:64] or None, status[:20],
                 (detail or "")[:200] or None),
            )
            _audit_counter += 1
            if _audit_counter % 500 == 1:
                await db.execute("DELETE FROM mcp_audit_log WHERE ts < ?",
                                 (now - MCP_AUDIT_RETENTION_DAYS * 86400,))
            await db.commit()
    except Exception:
        logger.exception("MCP audit yozilmadi")
    log_fn = logger.warning if status not in {"ok"} else logger.info
    log_fn("MCP %s status=%s token=%s tool=%s ip=%s %s", event, status, token_id, tool, ip, detail or "")


async def _alert(text: str) -> None:
    """Super adminga Telegram orqali ogohlantirish (A09). Xato bo'lsa jim o'tadi."""
    if not BOT_TOKEN or not SUPER_ADMIN_ID:
        return
    try:
        timeout = aiohttp.ClientTimeout(total=8)
        async with aiohttp.ClientSession(timeout=timeout) as s:
            await s.post(f"https://api.telegram.org/bot{BOT_TOKEN}/sendMessage",
                         json={"chat_id": SUPER_ADMIN_ID, "text": f"🛡 MCP: {text}"[:3500]})
    except Exception:
        logger.warning("MCP alert yuborilmadi")


def _alert_bg(text: str) -> None:
    try:
        asyncio.get_running_loop().create_task(_alert(text))
    except RuntimeError:
        pass


# ═════════════════════════════════════════════════════════════════════════════
#  Tarmoq yordamchilari
# ═════════════════════════════════════════════════════════════════════════════

def client_ip(request: web.Request) -> str:
    """Ishonchli proksi qo'shgan IP. X-Forwarded-For'ning chap qismi mijoz tomonidan
    soxtalashtirilishi mumkin, shuning uchun o'ngdan MCP_TRUSTED_PROXY_HOPS-chi element olinadi."""
    xff = [p.strip() for p in request.headers.get("X-Forwarded-For", "").split(",") if p.strip()]
    if xff:
        idx = max(0, len(xff) - MCP_TRUSTED_PROXY_HOPS)
        return xff[idx][:64]
    return (request.remote or "unknown")[:64]


def _sliding_hit(store: dict, key, limit: int, window: int) -> bool:
    """True — ruxsat; False — limitdan oshdi."""
    now = time.time()
    q = store.setdefault(key, deque())
    while q and now - q[0] >= window:
        q.popleft()
    if len(q) >= limit:
        return False
    q.append(now)
    return True


def _is_ip_blocked(ip: str) -> bool:
    until = _blocked_ips.get(ip)
    if until and until > time.time():
        return True
    if until:
        _blocked_ips.pop(ip, None)
    return False


async def _register_auth_failure(ip: str, reason: str) -> None:
    await _audit(ip, "auth", "denied", detail=reason)
    if not _sliding_hit(_auth_failures, ip, MCP_AUTH_FAIL_LIMIT, MCP_AUTH_FAIL_WINDOW):
        if not _is_ip_blocked(ip):
            _blocked_ips[ip] = time.time() + MCP_AUTH_BLOCK_SECONDS
            await _audit(ip, "auth", "blocked", detail=f"{MCP_AUTH_FAIL_LIMIT}+ noto'g'ri token")
            _alert_bg(f"IP {ip} {MCP_AUTH_FAIL_LIMIT} marta noto'g'ri token yubordi — "
                      f"{MCP_AUTH_BLOCK_SECONDS // 60} daqiqaga bloklandi.")
    # Eski yozuvlarni tozalash (xotira o'smasligi uchun)
    if len(_auth_failures) > 5000:
        now = time.time()
        for k in [k for k, q in _auth_failures.items() if not q or now - q[-1] > MCP_AUTH_FAIL_WINDOW]:
            _auth_failures.pop(k, None)


def _origin_allowed(request: web.Request) -> bool:
    """MCP spec talabi: Origin bo'lsa tekshirilsin (DNS rebinding himoyasi).
    CLI klientlar (Claude Code) Origin yubormaydi."""
    origin = request.headers.get("Origin")
    if origin is None:
        return True
    return origin.rstrip("/") in MCP_ALLOWED_ORIGINS


def _no_store(resp: web.StreamResponse) -> web.StreamResponse:
    resp.headers["Cache-Control"] = "no-store"
    resp.headers["Pragma"] = "no-cache"
    return resp


# ═════════════════════════════════════════════════════════════════════════════
#  Token tekshiruvi (A01, A07)
# ═════════════════════════════════════════════════════════════════════════════

_TOKEN_RE = re.compile(r"^amcp_[A-Za-z0-9_-]{43}$")


async def _authenticate(request: web.Request) -> dict | None:
    auth = request.headers.get("Authorization", "")
    if not auth.startswith("Bearer "):
        return None
    token = auth[7:].strip()
    if not _TOKEN_RE.fullmatch(token):
        return None
    token_hash = _hash_token(token)
    await _ensure_tables()
    async with aiosqlite.connect(DB_FILE) as db:
        db.row_factory = aiosqlite.Row
        async with db.execute(
            "SELECT id, name, token_hash, scopes, expires_at, revoked_at FROM mcp_tokens WHERE token_hash=?",
            (token_hash,),
        ) as c:
            row = await c.fetchone()
    if not row or not hmac.compare_digest(row["token_hash"], token_hash):
        return None
    now = int(time.time())
    if row["revoked_at"] is not None or int(row["expires_at"]) <= now:
        return None
    return {
        "id": int(row["id"]),
        "name": row["name"],
        "scopes": {s for s in str(row["scopes"]).split(",") if s in SCOPES},
    }


async def _touch_token(token_id: int, ip: str) -> None:
    try:
        async with aiosqlite.connect(DB_FILE) as db:
            await db.execute(
                "UPDATE mcp_tokens SET last_used_at=?, last_used_ip=?, use_count=use_count+1 WHERE id=?",
                (int(time.time()), ip[:64], token_id),
            )
            await db.commit()
    except Exception:
        logger.exception("MCP token last_used yangilanmadi")


# ═════════════════════════════════════════════════════════════════════════════
#  Argument validatsiyasi (A05)
# ═════════════════════════════════════════════════════════════════════════════

class ToolArgError(ValueError):
    pass


def _validate_args(schema: dict, args: Any) -> dict:
    if args is None:
        args = {}
    if not isinstance(args, dict):
        raise ToolArgError("arguments obyekt bo'lishi kerak")
    props: dict = schema.get("properties", {})
    extra = set(args) - set(props)
    if extra:
        raise ToolArgError(f"Noma'lum argument: {sorted(extra)[0][:40]}")
    out: dict = {}
    for key in schema.get("required", []):
        if key not in args:
            raise ToolArgError(f"'{key}' majburiy")
    for key, spec in props.items():
        if key not in args:
            if "default" in spec:
                out[key] = spec["default"]
            continue
        val = args[key]
        typ = spec.get("type")
        if typ == "integer":
            if isinstance(val, bool) or not isinstance(val, int):
                raise ToolArgError(f"'{key}' butun son bo'lishi kerak")
            if "minimum" in spec and val < spec["minimum"]:
                raise ToolArgError(f"'{key}' kamida {spec['minimum']}")
            if "maximum" in spec and val > spec["maximum"]:
                raise ToolArgError(f"'{key}' ko'pi bilan {spec['maximum']}")
        elif typ == "string":
            if not isinstance(val, str):
                raise ToolArgError(f"'{key}' matn bo'lishi kerak")
            val = val.strip()
            if "\x00" in val:
                raise ToolArgError(f"'{key}' ruxsat etilmagan belgi bor")
            if len(val) < spec.get("minLength", 0):
                raise ToolArgError(f"'{key}' juda qisqa")
            if len(val) > spec.get("maxLength", 200):
                raise ToolArgError(f"'{key}' juda uzun")
        else:
            raise ToolArgError("Sxema xatosi")
        if "enum" in spec and val not in spec["enum"]:
            raise ToolArgError(f"'{key}' qiymati ruxsat etilmagan")
        out[key] = val
    return out


def _like_escape(text: str) -> str:
    return text.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")


# ═════════════════════════════════════════════════════════════════════════════
#  Tool'lar (hammasi faqat o'qish uchun — A06)
# ═════════════════════════════════════════════════════════════════════════════

def _anime_row(r: aiosqlite.Row, full: bool = False) -> dict:
    keys = r.keys()
    data = {
        "id": r["id"],
        "nom": r["nom"],
        "nom_en": r["nom_en"] if "nom_en" in keys else "",
        "janri": r["janri"],
        "yili": r["yili"],
        "turi": r["aniType"] if "aniType" in keys else "",
        "qidiruv": r["qidiruv"],
    }
    if full:
        for k in ("qismi", "davlat", "tili", "fandub", "liklar", "desliklar"):
            if k in keys:
                data[k] = r[k]
        if "tavsif" in keys:
            data["tavsif"] = (r["tavsif"] or "")[:1500]
    return data


async def tool_get_stats(_: dict) -> dict:
    async with aiosqlite.connect(DB_FILE) as db:
        out = {}
        for key, table in (("users", "users"), ("vip", "vip_status"),
                           ("animes", "animelar"), ("episodes", "anime_datas")):
            try:
                async with db.execute(f"SELECT COUNT(*) FROM {table}") as c:  # table nomi — qattiq ro'yxatdan
                    out[key] = (await c.fetchone())[0]
            except aiosqlite.OperationalError:
                out[key] = None
    return out


async def tool_search_anime(a: dict) -> dict:
    pattern = f"%{_like_escape(a['query'])}%"
    async with aiosqlite.connect(DB_FILE) as db:
        db.row_factory = aiosqlite.Row
        async with db.execute(
            "SELECT * FROM animelar WHERE nom LIKE ? ESCAPE '\\' OR nom_en LIKE ? ESCAPE '\\' "
            "ORDER BY qidiruv DESC LIMIT ?",
            (pattern, pattern, a["limit"]),
        ) as c:
            rows = await c.fetchall()
    return {"results": [_anime_row(r) for r in rows], "count": len(rows)}


async def tool_get_anime(a: dict) -> dict:
    async with aiosqlite.connect(DB_FILE) as db:
        db.row_factory = aiosqlite.Row
        async with db.execute("SELECT * FROM animelar WHERE id=?", (a["anime_id"],)) as c:
            row = await c.fetchone()
        if not row:
            return {"found": False}
        async with db.execute("SELECT COUNT(*) FROM anime_datas WHERE id=?", (a["anime_id"],)) as c:
            eps = (await c.fetchone())[0]
    data = _anime_row(row, full=True)
    data["episode_count"] = eps
    return {"found": True, "anime": data}


async def tool_list_episodes(a: dict) -> dict:
    async with aiosqlite.connect(DB_FILE) as db:
        async with db.execute(
            "SELECT qism, sana FROM anime_datas WHERE id=? ORDER BY qism ASC LIMIT ? OFFSET ?",
            (a["anime_id"], a["limit"], a["offset"]),
        ) as c:
            rows = await c.fetchall()
    return {"anime_id": a["anime_id"], "episodes": [{"qism": r[0], "sana": r[1]} for r in rows]}


_TOP_ORDER = {"qidiruv": "qidiruv", "liklar": "liklar", "yangi": "id"}  # foydalanuvchi qiymati SQL'ga to'g'ridan tushmaydi


async def tool_top_anime(a: dict) -> dict:
    col = _TOP_ORDER[a["by"]]
    async with aiosqlite.connect(DB_FILE) as db:
        db.row_factory = aiosqlite.Row
        async with db.execute(f"SELECT * FROM animelar ORDER BY {col} DESC LIMIT ?", (a["limit"],)) as c:
            rows = await c.fetchall()
    return {"by": a["by"], "results": [_anime_row(r) for r in rows]}


async def tool_recent_users(a: dict) -> dict:
    # Ma'lumotni minimallashtirish: balans/referal kabi maydonlar qaytarilmaydi.
    async with aiosqlite.connect(DB_FILE) as db:
        async with db.execute(
            "SELECT user_id, status, ban, joined_at FROM users ORDER BY joined_at DESC LIMIT ?",
            (a["limit"],),
        ) as c:
            rows = await c.fetchall()
    return {"users": [{"user_id": r[0], "status": r[1], "ban": r[2], "joined_at": r[3]} for r in rows]}


TOOLS: dict[str, dict] = {
    "get_stats": {
        "scope": "stats:read",
        "handler": tool_get_stats,
        "description": "Botning umumiy statistikasi: foydalanuvchilar, VIP, animelar va qismlar soni.",
        "inputSchema": {"type": "object", "properties": {}, "additionalProperties": False},
    },
    "search_anime": {
        "scope": "anime:read",
        "handler": tool_search_anime,
        "description": "Anime nomi (o'zbekcha yoki inglizcha) bo'yicha qidirish.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "query": {"type": "string", "minLength": 1, "maxLength": 100, "description": "Qidiruv matni"},
                "limit": {"type": "integer", "minimum": 1, "maximum": 20, "default": 10},
            },
            "required": ["query"],
            "additionalProperties": False,
        },
    },
    "get_anime": {
        "scope": "anime:read",
        "handler": tool_get_anime,
        "description": "Anime haqida to'liq ma'lumot (ID bo'yicha), qismlar soni bilan.",
        "inputSchema": {
            "type": "object",
            "properties": {"anime_id": {"type": "integer", "minimum": 1, "maximum": 2_147_483_647}},
            "required": ["anime_id"],
            "additionalProperties": False,
        },
    },
    "list_episodes": {
        "scope": "anime:read",
        "handler": tool_list_episodes,
        "description": "Anime qismlari ro'yxati (raqam va sana).",
        "inputSchema": {
            "type": "object",
            "properties": {
                "anime_id": {"type": "integer", "minimum": 1, "maximum": 2_147_483_647},
                "limit": {"type": "integer", "minimum": 1, "maximum": 100, "default": 50},
                "offset": {"type": "integer", "minimum": 0, "maximum": 100_000, "default": 0},
            },
            "required": ["anime_id"],
            "additionalProperties": False,
        },
    },
    "top_anime": {
        "scope": "anime:read",
        "handler": tool_top_anime,
        "description": "Eng ko'p qidirilgan, eng ko'p layk olgan yoki eng yangi animelar.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "by": {"type": "string", "enum": list(_TOP_ORDER), "default": "qidiruv"},
                "limit": {"type": "integer", "minimum": 1, "maximum": 20, "default": 10},
            },
            "additionalProperties": False,
        },
    },
    "recent_users": {
        "scope": "users:read",
        "handler": tool_recent_users,
        "description": "Oxirgi qo'shilgan foydalanuvchilar (ID, status, ban holati).",
        "inputSchema": {
            "type": "object",
            "properties": {"limit": {"type": "integer", "minimum": 1, "maximum": 50, "default": 20}},
            "additionalProperties": False,
        },
    },
}


# ═════════════════════════════════════════════════════════════════════════════
#  JSON-RPC / MCP protokol
# ═════════════════════════════════════════════════════════════════════════════

def _rpc_result(req_id, result: dict) -> dict:
    return {"jsonrpc": "2.0", "id": req_id, "result": result}


def _rpc_error(req_id, code: int, message: str) -> dict:
    return {"jsonrpc": "2.0", "id": req_id, "error": {"code": code, "message": message}}


def _json(payload: dict, status: int = 200, headers: dict | None = None) -> web.Response:
    return _no_store(web.json_response(payload, status=status, headers=headers))


def _unauthorized() -> web.Response:
    return _json(
        _rpc_error(None, -32001, "Avtorizatsiya talab qilinadi"),
        status=401,
        headers={"WWW-Authenticate": f'Bearer realm="{SERVER_NAME}-mcp"'},
    )


async def mcp_handler(request: web.Request) -> web.StreamResponse:
    ip = client_ip(request)
    try:
        if not MCP_ENABLED:
            return _no_store(web.Response(status=404, text="Not found"))

        if request.method != "POST":
            # SSE oqimi qo'llab-quvvatlanmaydi (stateless server) — spec bo'yicha 405
            return _no_store(web.Response(status=405, headers={"Allow": "POST"}))

        if not _origin_allowed(request):
            await _audit(ip, "origin", "denied", detail=(request.headers.get("Origin") or "")[:100])
            return _json(_rpc_error(None, -32000, "Origin ruxsat etilmagan"), status=403)

        if _is_ip_blocked(ip):
            return _json(_rpc_error(None, -32000, "Juda ko'p urinish"), status=429,
                         headers={"Retry-After": str(MCP_AUTH_BLOCK_SECONDS)})

        token = await _authenticate(request)
        if not token:
            await _register_auth_failure(ip, "noto'g'ri/yo'q/muddati o'tgan token")
            return _unauthorized()

        if not _sliding_hit(_token_hits, token["id"], MCP_RATE_LIMIT_PER_MIN, 60):
            await _audit(ip, "rate_limit", "denied", token_id=token["id"])
            return _json(_rpc_error(None, -32000, "Juda ko'p so'rov"), status=429, headers={"Retry-After": "60"})

        ctype = request.headers.get("Content-Type", "").split(";", 1)[0].strip().lower()
        if ctype != "application/json":
            return _json(_rpc_error(None, -32700, "Content-Type application/json bo'lishi kerak"), status=415)

        if request.content_length is not None and request.content_length > MCP_MAX_BODY_BYTES:
            return _json(_rpc_error(None, -32600, "So'rov juda katta"), status=413)
        raw = await request.content.read(MCP_MAX_BODY_BYTES + 1)
        if len(raw) > MCP_MAX_BODY_BYTES:
            return _json(_rpc_error(None, -32600, "So'rov juda katta"), status=413)

        try:
            msg = json.loads(raw.decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError):
            return _json(_rpc_error(None, -32700, "JSON xato"), status=400)

        if isinstance(msg, list):
            return _json(_rpc_error(None, -32600, "Batch so'rovlar qo'llab-quvvatlanmaydi"), status=400)
        if not isinstance(msg, dict) or msg.get("jsonrpc") != "2.0":
            return _json(_rpc_error(None, -32600, "Noto'g'ri JSON-RPC"), status=400)

        method = msg.get("method")
        has_id = "id" in msg
        req_id = msg.get("id")

        # Klientdan kelgan javob yoki notification — body'siz 202
        if method is None and ("result" in msg or "error" in msg):
            return _no_store(web.Response(status=202))
        if not isinstance(method, str) or len(method) > 100:
            return _json(_rpc_error(None, -32600, "Noto'g'ri method"), status=400)
        if not has_id:
            return _no_store(web.Response(status=202))
        if isinstance(req_id, bool) or not isinstance(req_id, (str, int)) or (isinstance(req_id, str) and len(req_id) > 100):
            return _json(_rpc_error(None, -32600, "Noto'g'ri id"), status=400)

        proto_hdr = request.headers.get("MCP-Protocol-Version")
        if method != "initialize" and proto_hdr and proto_hdr not in SUPPORTED_PROTOCOL_VERSIONS:
            return _json(_rpc_error(req_id, -32600, "Protokol versiyasi qo'llab-quvvatlanmaydi"), status=400)

        await _touch_token(token["id"], ip)
        params = msg.get("params") or {}
        if not isinstance(params, dict):
            return _json(_rpc_error(req_id, -32602, "params obyekt bo'lishi kerak"))

        if method == "initialize":
            client_ver = params.get("protocolVersion")
            version = client_ver if client_ver in SUPPORTED_PROTOCOL_VERSIONS else LATEST_PROTOCOL_VERSION
            await _audit(ip, "initialize", "ok", token_id=token["id"])
            return _json(_rpc_result(req_id, {
                "protocolVersion": version,
                "capabilities": {"tools": {"listChanged": False}},
                "serverInfo": {"name": SERVER_NAME, "version": SERVER_VERSION},
                "instructions": "AnimeUZ bot ma'lumotlarini faqat o'qish uchun MCP server.",
            }))

        if method == "ping":
            return _json(_rpc_result(req_id, {}))

        if method == "tools/list":
            tools = [
                {"name": name, "description": t["description"], "inputSchema": t["inputSchema"]}
                for name, t in TOOLS.items() if t["scope"] in token["scopes"]
            ]
            return _json(_rpc_result(req_id, {"tools": tools}))

        if method == "tools/call":
            name = params.get("name")
            tool = TOOLS.get(name) if isinstance(name, str) else None
            # Ruxsat yo'q tool'ni "mavjud emas" deb ko'rsatamiz — tool ro'yxatini oshkor qilmaslik uchun
            if not tool or tool["scope"] not in token["scopes"]:
                await _audit(ip, "tools/call", "denied", token_id=token["id"],
                             tool=str(name)[:64], detail="scope yo'q yoki tool mavjud emas")
                return _json(_rpc_error(req_id, -32602, "Tool topilmadi"))
            try:
                args = _validate_args(tool["inputSchema"], params.get("arguments"))
            except ToolArgError as e:
                await _audit(ip, "tools/call", "bad_args", token_id=token["id"], tool=name)
                return _json(_rpc_result(req_id, {
                    "content": [{"type": "text", "text": f"Argument xatosi: {e}"}], "isError": True}))
            try:
                data = await asyncio.wait_for(tool["handler"](args), timeout=10)
            except Exception:
                err_id = secrets.token_hex(4)
                logger.exception("MCP tool xatosi [%s] tool=%s", err_id, name)
                await _audit(ip, "tools/call", "error", token_id=token["id"], tool=name, detail=f"err={err_id}")
                return _json(_rpc_result(req_id, {
                    "content": [{"type": "text", "text": f"Ichki xato (ID: {err_id})"}], "isError": True}))
            await _audit(ip, "tools/call", "ok", token_id=token["id"], tool=name)
            text = json.dumps(data, ensure_ascii=False, default=str)
            return _json(_rpc_result(req_id, {
                "content": [{"type": "text", "text": text}],
                "structuredContent": data,
                "isError": False,
            }))

        return _json(_rpc_error(req_id, -32601, "Method topilmadi"))

    except Exception:
        # A10: kutilmagan holatda ham ichki tafsilot chiqmaydi, so'rov rad etiladi
        err_id = secrets.token_hex(4)
        logger.exception("MCP kutilmagan xato [%s]", err_id)
        return _json(_rpc_error(None, -32603, f"Ichki xato (ID: {err_id})"), status=500)


# ═════════════════════════════════════════════════════════════════════════════
#  Admin panel API (token boshqaruvi)
# ═════════════════════════════════════════════════════════════════════════════

_NAME_RE = re.compile(r"^[\w .\-]{1,64}$", re.UNICODE)


def _same_origin(request: web.Request) -> bool:
    """CSRF himoyasi (A01): o'zgartiruvchi admin so'rovlari faqat shu sayt sahifasidan."""
    origin = request.headers.get("Origin") or ""
    if not origin:
        referer = request.headers.get("Referer") or ""
        m = re.match(r"^(https?://[^/]+)", referer)
        origin = m.group(1) if m else ""
    if not origin:
        return False
    origin = origin.rstrip("/")
    allowed = set(MCP_ALLOWED_ORIGINS)
    if WEB_PUBLIC_ORIGIN:
        allowed.add(WEB_PUBLIC_ORIGIN)
    host = request.headers.get("X-Forwarded-Host") or request.host or ""
    host = host.split(",", 1)[0].strip()
    if host:
        allowed.update({f"https://{host}", f"http://{host}"})
    return origin in allowed


def register_mcp_routes(
    app: web.Application,
    *,
    is_admin: Callable[[web.Request], bool],
    admin_id: Callable[[web.Request], int],
) -> None:
    def _denied() -> web.Response:
        return _json({"ok": False, "error": "Admin sessiyasi kerak"}, status=401)

    def _csrf_denied() -> web.Response:
        return _json({"ok": False, "error": "So'rov manbasi tasdiqlanmadi"}, status=403)

    async def list_tokens(request: web.Request) -> web.Response:
        if not is_admin(request):
            return _denied()
        await _ensure_tables()
        now = int(time.time())
        async with aiosqlite.connect(DB_FILE) as db:
            db.row_factory = aiosqlite.Row
            async with db.execute(
                "SELECT id, name, token_hint, scopes, created_by, created_at, expires_at, revoked_at, "
                "last_used_at, last_used_ip, use_count FROM mcp_tokens ORDER BY id DESC LIMIT 100"
            ) as c:
                rows = await c.fetchall()
        tokens = []
        for r in rows:
            status = "revoked" if r["revoked_at"] else ("expired" if r["expires_at"] <= now else "active")
            tokens.append({k: r[k] for k in r.keys()} | {"scopes": r["scopes"].split(","), "status": status})
        return _json({"ok": True, "tokens": tokens, "scopes": SCOPES, "enabled": MCP_ENABLED,
                      "max_expiry_days": MCP_MAX_EXPIRY_DAYS})

    async def create_token(request: web.Request) -> web.Response:
        if not is_admin(request):
            return _denied()
        if not _same_origin(request):
            return _csrf_denied()
        ip = client_ip(request)
        if not _sliding_hit(_admin_create_hits, ip, 10, 3600):
            return _json({"ok": False, "error": "Soatiga 10 tadan ko'p token yaratib bo'lmaydi"}, status=429)
        try:
            body = await request.json()
        except Exception:
            return _json({"ok": False, "error": "JSON xato"}, status=400)
        if not isinstance(body, dict):
            return _json({"ok": False, "error": "JSON xato"}, status=400)

        name = str(body.get("name") or "").strip()
        if not _NAME_RE.fullmatch(name):
            return _json({"ok": False, "error": "Nom 1–64 belgi: harf, raqam, probel, . _ -"}, status=400)
        scopes = body.get("scopes")
        if not isinstance(scopes, list) or not scopes or not all(isinstance(s, str) and s in SCOPES for s in scopes):
            return _json({"ok": False, "error": "Kamida bitta to'g'ri ruxsat (scope) tanlang"}, status=400)
        scopes = sorted(set(scopes))
        days = body.get("expires_days")
        if isinstance(days, bool) or not isinstance(days, int) or not 1 <= days <= MCP_MAX_EXPIRY_DAYS:
            return _json({"ok": False, "error": f"Muddat 1–{MCP_MAX_EXPIRY_DAYS} kun bo'lishi kerak"}, status=400)

        await _ensure_tables()
        now = int(time.time())
        async with aiosqlite.connect(DB_FILE) as db:
            async with db.execute(
                "SELECT COUNT(*) FROM mcp_tokens WHERE revoked_at IS NULL AND expires_at > ?", (now,)
            ) as c:
                active = (await c.fetchone())[0]
            if active >= MCP_MAX_ACTIVE_TOKENS:
                return _json({"ok": False, "error": f"Faol tokenlar soni {MCP_MAX_ACTIVE_TOKENS} dan oshmasin. "
                                                    "Keraksizlarini bekor qiling."}, status=400)
            token = _generate_token()
            hint = token[: len(TOKEN_PREFIX) + 4] + "…" + token[-4:]
            creator = int(admin_id(request) or 0)
            cur = await db.execute(
                "INSERT INTO mcp_tokens (name, token_hash, token_hint, scopes, created_by, created_at, expires_at) "
                "VALUES (?,?,?,?,?,?,?)",
                (name, _hash_token(token), hint, ",".join(scopes), creator, now, now + days * 86400),
            )
            token_id = cur.lastrowid
            await db.commit()
        await _audit(ip, "token_create", "ok", token_id=token_id,
                     detail=f"admin={creator} scopes={','.join(scopes)} days={days}")
        _alert_bg(f"Yangi token yaratildi: #{token_id} «{name}», ruxsatlar: {', '.join(scopes)}, "
                  f"muddat: {days} kun, admin: {creator}, IP: {ip}. Agar bu siz bo'lmasangiz — darhol bekor qiling!")
        return _json({"ok": True, "id": token_id, "token": token, "hint": hint,
                      "note": "Token faqat hozir ko'rsatiladi. Uni xavfsiz joyga saqlang."})

    async def revoke_token(request: web.Request) -> web.Response:
        if not is_admin(request):
            return _denied()
        if not _same_origin(request):
            return _csrf_denied()
        try:
            token_id = int(request.match_info["token_id"])
        except (KeyError, ValueError):
            return _json({"ok": False, "error": "Noto'g'ri ID"}, status=400)
        await _ensure_tables()
        async with aiosqlite.connect(DB_FILE) as db:
            cur = await db.execute(
                "UPDATE mcp_tokens SET revoked_at=? WHERE id=? AND revoked_at IS NULL",
                (int(time.time()), token_id),
            )
            await db.commit()
        if cur.rowcount == 0:
            return _json({"ok": False, "error": "Token topilmadi yoki allaqachon bekor qilingan"}, status=404)
        ip = client_ip(request)
        await _audit(ip, "token_revoke", "ok", token_id=token_id, detail=f"admin={admin_id(request)}")
        _alert_bg(f"Token #{token_id} bekor qilindi (admin: {admin_id(request)}, IP: {ip}).")
        return _json({"ok": True})

    async def audit_log(request: web.Request) -> web.Response:
        if not is_admin(request):
            return _denied()
        await _ensure_tables()
        async with aiosqlite.connect(DB_FILE) as db:
            db.row_factory = aiosqlite.Row
            async with db.execute(
                "SELECT ts, token_id, ip, event, tool, status, detail FROM mcp_audit_log ORDER BY id DESC LIMIT 100"
            ) as c:
                rows = await c.fetchall()
        return _json({"ok": True, "entries": [{k: r[k] for k in r.keys()} for r in rows]})

    app.router.add_route("*", "/mcp", mcp_handler)
    app.router.add_get("/api/admin/mcp/tokens", list_tokens)
    app.router.add_post("/api/admin/mcp/tokens", create_token)
    app.router.add_post("/api/admin/mcp/tokens/{token_id}/revoke", revoke_token)
    app.router.add_get("/api/admin/mcp/audit", audit_log)
