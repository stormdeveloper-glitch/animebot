"""Anime ekotizimi: barcha botlar (asosiy + klonlar) animelari bitta katalogda.

Har bir bot o'z bazasida qoladi; katalog ularni o'qiydi. Telegram'da video
file_id faqat uni yuklagan botda ishlaydi, shuning uchun boshqa botning animesi
o'sha botning o'zida (t.me/<bot>?start=<id>) ochiladi.

Bot egasi "access_price" qo'ysa, uning botida qismlarni ko'rish uchun to'lov
cheki yuborib, egasining tasdig'ini olish kerak (eco_access jadvali).
"""
import aiosqlite

from config import DB_PATH
from utils.tenant import MAIN_BOT_ID, _original_connect, tenant_db_path

PAGE_SIZE = 10

_main_info = {"username": "", "name": "AnimeUZ"}


def set_main_info(username: str, name: str) -> None:
    _main_info["username"] = username or ""
    _main_info["name"] = name or "AnimeUZ"


def _db_path(bot_id: int) -> str:
    return DB_PATH if bot_id == MAIN_BOT_ID else tenant_db_path(bot_id)


def connect_bot_db(bot_id: int):
    """Joriy tenantdan qat'i nazar istalgan botning bazasiga ulanish."""
    return _original_connect(_db_path(bot_id))


def ecosystem_bots() -> list[tuple[int, str, str]]:
    """(bot_id, username, name): asosiy bot va ishlayotgan klonlar."""
    from utils.clones import running_clones
    bots = [(MAIN_BOT_ID, _main_info["username"], _main_info["name"])]
    bots += running_clones()
    return bots


def bot_info(bot_id: int) -> tuple[int, str, str] | None:
    return next((b for b in ecosystem_bots() if b[0] == bot_id), None)


async def anime_count(bot_id: int) -> int:
    try:
        async with connect_bot_db(bot_id) as db:
            async with db.execute("SELECT COUNT(*) FROM animelar") as c:
                return (await c.fetchone())[0]
    except Exception:
        return 0


async def anime_page(bot_id: int, page: int) -> list[tuple]:
    """(id, nom) — eng yangilari birinchi."""
    try:
        async with connect_bot_db(bot_id) as db:
            async with db.execute(
                "SELECT id, nom FROM animelar ORDER BY id DESC LIMIT ? OFFSET ?",
                (PAGE_SIZE, page * PAGE_SIZE),
            ) as c:
                return await c.fetchall()
    except Exception:
        return []


async def anime_card(bot_id: int, anime_id: int) -> dict | None:
    try:
        async with connect_bot_db(bot_id) as db:
            async with db.execute(
                "SELECT nom, qismi, davlat, tili, yili, janri, tavsif FROM animelar WHERE id=?",
                (anime_id,),
            ) as c:
                row = await c.fetchone()
            if not row:
                return None
            async with db.execute("SELECT COUNT(*) FROM anime_datas WHERE id=?", (anime_id,)) as c:
                uploaded = (await c.fetchone())[0]
    except Exception:
        return None
    keys = ("nom", "qismi", "davlat", "tili", "yili", "janri", "tavsif")
    card = dict(zip(keys, row))
    card["uploaded"] = uploaded
    card["price"] = await access_price(bot_id)
    return card


async def search_all(query: str, limit: int = 20) -> list[tuple[int, int, str]]:
    """Barcha botlardan nom bo'yicha qidiradi: (bot_id, anime_id, nom)."""
    pattern = f"%{query}%"
    results = []
    for bot_id, _username, _name in ecosystem_bots():
        try:
            async with connect_bot_db(bot_id) as db:
                async with db.execute(
                    "SELECT id, nom FROM animelar WHERE nom LIKE ? OR nom_en LIKE ? ORDER BY id DESC LIMIT ?",
                    (pattern, pattern, limit),
                ) as c:
                    results += [(bot_id, r[0], r[1]) for r in await c.fetchall()]
        except Exception:
            continue
        if len(results) >= limit:
            break
    return results[:limit]


# ─── Pullik kirish (joriy bot bazasida) ──────────────────────────────────────

async def _ensure_access_tables(db) -> None:
    await db.execute("""
        CREATE TABLE IF NOT EXISTS eco_access (
            user_id INTEGER PRIMARY KEY,
            granted_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    """)
    await db.execute("""
        CREATE TABLE IF NOT EXISTS eco_access_requests (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER NOT NULL,
            file_id TEXT,
            status TEXT DEFAULT 'pending',
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    """)


async def access_price(bot_id: int | None = None) -> int:
    """Bot egasi qo'ygan kirish narxi (0 — bepul). bot_id yo'q bo'lsa joriy bot."""
    connect = connect_bot_db(bot_id) if bot_id else aiosqlite.connect(DB_PATH)
    try:
        async with connect as db:
            async with db.execute("SELECT value FROM bot_settings WHERE key='access_price'") as c:
                row = await c.fetchone()
        return max(0, int((row[0] if row else "0") or 0))
    except Exception:
        return 0


async def has_access(user_id: int) -> bool:
    async with aiosqlite.connect(DB_PATH) as db:
        await _ensure_access_tables(db)
        async with db.execute("SELECT 1 FROM eco_access WHERE user_id=?", (user_id,)) as c:
            return await c.fetchone() is not None


async def create_access_request(user_id: int, file_id: str) -> int:
    async with aiosqlite.connect(DB_PATH) as db:
        await _ensure_access_tables(db)
        cursor = await db.execute(
            "INSERT INTO eco_access_requests (user_id, file_id) VALUES (?, ?)", (user_id, file_id)
        )
        await db.commit()
        return cursor.lastrowid


async def resolve_access_request(request_id: int, approve: bool) -> int | None:
    """So'rovni tasdiqlaydi/rad etadi; foydalanuvchi ID sini qaytaradi."""
    async with aiosqlite.connect(DB_PATH) as db:
        await _ensure_access_tables(db)
        async with db.execute(
            "SELECT user_id, status FROM eco_access_requests WHERE id=?", (request_id,)
        ) as c:
            row = await c.fetchone()
        if not row or row[1] != "pending":
            return None
        await db.execute(
            "UPDATE eco_access_requests SET status=? WHERE id=?",
            ("approved" if approve else "rejected", request_id),
        )
        if approve:
            await db.execute("INSERT OR IGNORE INTO eco_access (user_id) VALUES (?)", (row[0],))
        await db.commit()
        return row[0]
