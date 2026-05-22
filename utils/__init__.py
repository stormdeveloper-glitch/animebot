import asyncio
import time
import aiosqlite
from config import ADMIN_IDS, SUPER_ADMIN_ID, DB_PATH
from aiogram import Bot

# ─── Cache ────────────────────────────────────────────────────────────────────
# Kichik TTL cache — DB va API chaqiruvlarini keskin kamaytiradi

_admin_cache: dict[int, tuple[bool, float]] = {}       # user_id → (is_admin, expire_time)
_maintenance_cache: tuple[bool, float] = (False, 0.0)  # (value, expire_time)
_bot_username_cache: str = ""
_channel_names_cache: tuple[list, float] = ([], 0.0)   # (channels, expire_time)
_restriction_cache: tuple[bool, float] = (False, 0.0)      # (value, expire_time)

ADMIN_CACHE_TTL    = 60.0   # 1 daqiqa
MAINT_CACHE_TTL    = 5.0    # 5 soniya
CHANNEL_CACHE_TTL  = 120.0  # 2 daqiqa


async def is_admin(user_id: int) -> bool:
    # Env adminlar — hech qanday DB siz
    if user_id in ADMIN_IDS or user_id == SUPER_ADMIN_ID:
        return True

    now = time.monotonic()
    cached = _admin_cache.get(user_id)
    if cached and now < cached[1]:
        return cached[0]

    async with aiosqlite.connect(DB_PATH) as db:
        async with db.execute(
            "SELECT 1 FROM admins WHERE user_id=?", (user_id,)
        ) as cursor:
            result = await cursor.fetchone()

    value = result is not None
    _admin_cache[user_id] = (value, now + ADMIN_CACHE_TTL)
    return value


def invalidate_admin_cache(user_id: int = None):
    """Admin qo'shilganda/o'chirilganda chaqiring."""
    if user_id:
        _admin_cache.pop(user_id, None)
    else:
        _admin_cache.clear()


async def is_super_admin(user_id: int) -> bool:
    return user_id == SUPER_ADMIN_ID or user_id in ADMIN_IDS


async def is_maintenance() -> bool:
    global _maintenance_cache
    now = time.monotonic()
    if now < _maintenance_cache[1]:
        return _maintenance_cache[0]

    try:
        async with aiosqlite.connect(DB_PATH) as db:
            async with db.execute(
                "SELECT value FROM bot_settings WHERE key='bot_maintenance'"
            ) as cursor:
                row = await cursor.fetchone()
                value = row[0] == "1" if row else False
    except Exception:
        value = False

    _maintenance_cache = (value, now + MAINT_CACHE_TTL)
    return value


async def is_content_restricted() -> bool:
    global _restriction_cache
    now = time.monotonic()
    if now < _restriction_cache[1]:
        return _restriction_cache[0]

    try:
        async with aiosqlite.connect(DB_PATH) as db:
            async with db.execute(
                "SELECT value FROM bot_settings WHERE key='content_restriction'"
            ) as cursor:
                row = await cursor.fetchone()
                value = row[0] == "1" if row else False
    except Exception:
        value = False

    _restriction_cache = (value, now + MAINT_CACHE_TTL)
    return value


def invalidate_restriction_cache():
    global _restriction_cache
    _restriction_cache = (False, 0.0)


def _parse_chat_id(channel_id: str):
    try:
        return int(channel_id)
    except (ValueError, TypeError):
        return channel_id


async def get_bot_username(bot: Bot) -> str:
    global _bot_username_cache
    if not _bot_username_cache:
        me = await bot.get_me()
        _bot_username_cache = me.username
    return _bot_username_cache


async def _get_channels_cached(db_filter: str) -> list:
    """Kanallarni DB dan olib, cache da saqlaydi."""
    global _channel_names_cache
    now = time.monotonic()
    if now < _channel_names_cache[1]:
        return _channel_names_cache[0]

    async with aiosqlite.connect(DB_PATH) as db:
        try:
            async with db.execute(
                f"SELECT channelId, channelType, channelLink, channelName FROM channels WHERE channelType IN ({db_filter})"
            ) as cursor:
                rows = await cursor.fetchall()
        except Exception:
            async with db.execute(
                f"SELECT channelId, channelType, channelLink FROM channels WHERE channelType IN ({db_filter})"
            ) as cursor:
                rows_raw = await cursor.fetchall()
                rows = [(r[0], r[1], r[2], None) for r in rows_raw]

    _channel_names_cache = (rows, now + CHANNEL_CACHE_TTL)
    return rows


def invalidate_channel_cache():
    global _channel_names_cache
    _channel_names_cache = ([], 0.0)


async def check_subscription(user_id: int, bot: Bot) -> bool:
    """
    Barcha majburiy Telegram kanallarni parallel tekshiradi.
    Social kanallar tekshirilmaydi.
    Bot kanalda admin bo'lmasa — o'tkazib yuboradi.
    """
    rows = await _get_channels_cached("'public', 'request', 'social', 'ongoing'")
    tg_channels = [
        _parse_chat_id(r[0]) for r in rows
        if r[1] in ('public', 'request')
    ]

    if not tg_channels:
        return True

    # Barcha kanallarni PARALLEL tekshiramiz
    async def check_one(chat_id) -> bool:
        try:
            member = await bot.get_chat_member(chat_id=chat_id, user_id=user_id)
            return member.status in ("member", "administrator", "creator")
        except Exception as e:
            print(f"[Sub check] {chat_id}: {e}")
            return True  # Tekshira olmasa — o'tkazib yuboramiz

    results = await asyncio.gather(*[check_one(ch) for ch in tg_channels])
    return all(results)


async def get_subscription_keyboard(user_id: int, bot: Bot):
    from aiogram.types import InlineKeyboardMarkup
    from keyboards import InlineKeyboardButton

    rows = await _get_channels_cached("'public', 'request', 'social'")

    # Kanal nomlarini parallel olamiz
    async def get_btn(row) -> list | None:
        channel_id, channel_type, channel_link = row[0], row[1], row[2]
        channel_name = row[3] if len(row) > 3 else None

        if channel_type == 'social':
            title = channel_name or channel_id or "Ijtimoiy tarmoq"
            return [InlineKeyboardButton(text=f"🌐 {title}", url=channel_link)]
        else:
            chat_id = _parse_chat_id(channel_id)
            try:
                chat = await bot.get_chat(chat_id)
                title = chat.title or "Kanal"
            except Exception:
                title = channel_name or "Kanalga o'tish"
            return [InlineKeyboardButton(text=f"📢 {title}", url=channel_link)]

    buttons = await asyncio.gather(*[get_btn(r) for r in rows])
    buttons = [b for b in buttons if b]
    buttons.append([InlineKeyboardButton(text="✅ Tekshirish", callback_data="check_subscription")])
    return InlineKeyboardMarkup(inline_keyboard=buttons)
