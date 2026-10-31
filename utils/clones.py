"""Klon (managed) botlar reyestri: yaratish, saqlash, ishga tushirish.

Foydalanuvchi asosiy botda "Bot yaratish" tugmasi orqali Telegram'da o'z botini
yaratadi (Managed Bots). Token getManagedBotToken bilan olinadi, shifrlanib
asosiy bazadagi `clones` jadvaliga yoziladi. Klonlar asosiy bot bilan bir xil
Dispatcher va handlerlarda ishlaydi, update'lar webhook orqali keladi; har bir
klonning ma'lumoti o'z bazasida (utils.tenant).
"""
import asyncio
import hmac
import logging
import os

from aiogram import Bot, Dispatcher
from aiogram.types import Update

from config import WEB_PUBLIC_ORIGIN
from utils.tenant import main_db_connect, reset_tenant, set_tenant
from utils.token_vault import decrypt_token, encrypt_token, vault_ready, webhook_secret

logger = logging.getLogger(__name__)

MAX_CLONES_PER_USER = int(os.getenv("MAX_CLONES_PER_USER", "3"))

_dp: Dispatcher | None = None
_bots: dict[int, Bot] = {}
_owners: dict[int, int] = {}


def set_dispatcher(dp: Dispatcher) -> None:
    global _dp
    _dp = dp


def clone_owner(bot_id: int) -> int | None:
    return _owners.get(bot_id)


def is_clone_running(bot_id: int) -> bool:
    return bot_id in _bots


def _public_origin() -> str:
    if WEB_PUBLIC_ORIGIN:
        return WEB_PUBLIC_ORIGIN
    domain = os.getenv("RAILWAY_PUBLIC_DOMAIN", "").strip()
    return f"https://{domain}" if domain else ""


def webhook_url(bot_id: int) -> str:
    origin = _public_origin()
    return f"{origin}/tg/clone/{bot_id}" if origin else ""


async def ensure_clones_table() -> None:
    async with main_db_connect() as db:
        await db.execute("""
            CREATE TABLE IF NOT EXISTS clones (
                bot_id INTEGER PRIMARY KEY,
                owner_id INTEGER NOT NULL,
                username TEXT,
                name TEXT,
                token_enc TEXT NOT NULL,
                status TEXT NOT NULL DEFAULT 'active',
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        """)
        await db.execute("CREATE INDEX IF NOT EXISTS idx_clones_owner ON clones(owner_id)")
        await db.commit()


async def list_clones(owner_id: int | None = None) -> list[tuple]:
    """(bot_id, owner_id, username, name, status) ro'yxati."""
    query = "SELECT bot_id, owner_id, username, name, status FROM clones"
    params: tuple = ()
    if owner_id is not None:
        query += " WHERE owner_id=?"
        params = (owner_id,)
    async with main_db_connect() as db:
        async with db.execute(query + " ORDER BY created_at", params) as c:
            return await c.fetchall()


async def get_clone(bot_id: int) -> tuple | None:
    async with main_db_connect() as db:
        async with db.execute(
            "SELECT bot_id, owner_id, username, name, status FROM clones WHERE bot_id=?", (bot_id,)
        ) as c:
            return await c.fetchone()


async def init_clone_db(bot_id: int, owner_id: int) -> None:
    """Klon bazasini yaratadi va egasini admin qiladi."""
    from database import init_sqlite_db
    import aiosqlite

    from config import DB_PATH

    tokens = set_tenant(bot_id, owner_id)
    try:
        await init_sqlite_db()
        async with aiosqlite.connect(DB_PATH) as db:
            await db.execute(
                "INSERT OR IGNORE INTO admins (user_id, added_by) VALUES (?, ?)", (owner_id, owner_id)
            )
            await db.commit()
    finally:
        reset_tenant(tokens)


async def _start_bot(bot_id: int, token: str, owner_id: int) -> None:
    url = webhook_url(bot_id)
    if not url:
        raise RuntimeError("Public domen topilmadi (WEB_PUBLIC_ORIGIN / RAILWAY_PUBLIC_DOMAIN)")
    bot = Bot(token=token)
    try:
        await bot.set_webhook(
            url,
            secret_token=webhook_secret(bot_id),
            allowed_updates=_dp.resolve_used_update_types() if _dp else None,
            drop_pending_updates=False,
        )
    except Exception:
        await bot.session.close()
        raise
    old = _bots.pop(bot_id, None)
    if old is not None:
        await old.session.close()
    _bots[bot_id] = bot
    _owners[bot_id] = owner_id


async def register_clone(owner_id: int, bot_id: int, username: str, name: str, token: str) -> None:
    """Yangi (yoki tokeni yangilangan) klonni saqlaydi va ishga tushiradi."""
    token_enc = encrypt_token(token)
    async with main_db_connect() as db:
        await db.execute(
            """
            INSERT INTO clones (bot_id, owner_id, username, name, token_enc, status)
            VALUES (?, ?, ?, ?, ?, 'active')
            ON CONFLICT(bot_id) DO UPDATE SET
                username=excluded.username, name=excluded.name,
                token_enc=excluded.token_enc, status='active'
            """,
            (bot_id, owner_id, username, name, token_enc),
        )
        await db.commit()
    await init_clone_db(bot_id, owner_id)
    await _start_bot(bot_id, token, owner_id)
    logger.info("[clones] klon ishga tushdi: @%s (%s) owner=%s", username, bot_id, owner_id)


async def set_clone_status(bot_id: int, active: bool) -> None:
    """Klonni to'xtatadi yoki qayta ishga tushiradi."""
    async with main_db_connect() as db:
        await db.execute(
            "UPDATE clones SET status=? WHERE bot_id=?", ("active" if active else "stopped", bot_id)
        )
        await db.commit()
        async with db.execute("SELECT owner_id, token_enc FROM clones WHERE bot_id=?", (bot_id,)) as c:
            row = await c.fetchone()
    if not row:
        return
    if active:
        await _start_bot(bot_id, decrypt_token(row[1]), row[0])
        return
    bot = _bots.pop(bot_id, None)
    _owners.pop(bot_id, None)
    if bot is not None:
        try:
            await bot.delete_webhook()
        except Exception as e:
            logger.warning("[clones] %s webhook o'chirilmadi: %s", bot_id, e)
        await bot.session.close()


async def load_clones() -> None:
    """Bot ishga tushganda faol klonlarni qayta ulaydi."""
    await ensure_clones_table()
    if not vault_ready():
        logger.warning("[clones] BOT_TOKEN_ENC_KEY yo'q — klonlar o'chirilgan")
        return
    async with main_db_connect() as db:
        async with db.execute(
            "SELECT bot_id, owner_id, username, token_enc FROM clones WHERE status='active'"
        ) as c:
            rows = await c.fetchall()
    started = 0
    for bot_id, owner_id, username, token_enc in rows:
        try:
            await init_clone_db(bot_id, owner_id)
            await _start_bot(bot_id, decrypt_token(token_enc), owner_id)
            started += 1
        except Exception as e:
            logger.warning("[clones] @%s (%s) ishga tushmadi: %s", username, bot_id, e)
    logger.info("[clones] faol klonlar: %d/%d", started, len(rows))


async def feed_webhook(bot_id: int, secret: str, payload: dict) -> bool:
    """Webhook update'ini Dispatcher'ga uzatadi. Sir noto'g'ri bo'lsa False."""
    bot = _bots.get(bot_id)
    if bot is None or _dp is None or not vault_ready():
        return False
    if not secret or not hmac.compare_digest(secret, webhook_secret(bot_id)):
        return False
    update = Update.model_validate(payload, context={"bot": bot})
    task = asyncio.create_task(_dp.feed_update(bot, update))
    task.add_done_callback(_log_task_error)
    return True


def _log_task_error(task: asyncio.Task) -> None:
    if not task.cancelled() and task.exception():
        logger.error("[clones] update ishlovida xato: %s", task.exception())
