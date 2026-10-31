import asyncio
import time
import aiosqlite
from config import ADMIN_IDS, SUPER_ADMIN_ID, DB_PATH
from aiogram import Bot
from utils.tenant import current_owner, current_tenant

# ─── Cache ────────────────────────────────────────────────────────────────────
# Kichik TTL cache — DB va API chaqiruvlarini keskin kamaytiradi

# Klon botlar (tenant) ma'lumoti aralashmasligi uchun keshlar tenant bo'yicha
_admin_cache: dict[tuple, tuple[bool, float]] = {}     # (tenant, user_id) → (is_admin, expire_time)
_maintenance_cache: dict = {}                          # tenant → (value, expire_time)
_bot_username_cache: dict[int, str] = {}               # bot_id → username
_channel_names_cache: dict = {}                        # tenant → (channels, expire_time)
_restriction_cache: dict = {}                          # tenant → (value, expire_time)

ADMIN_CACHE_TTL    = 60.0   # 1 daqiqa
MAINT_CACHE_TTL    = 5.0    # 5 soniya
CHANNEL_CACHE_TTL  = 120.0  # 2 daqiqa


async def is_admin(user_id: int) -> bool:
    tenant = current_tenant()
    if tenant:
        # Klon botda env adminlar emas, bot egasi va uning adminlari
        if user_id == current_owner():
            return True
    elif user_id in ADMIN_IDS or user_id == SUPER_ADMIN_ID:
        # Env adminlar — hech qanday DB siz
        return True

    now = time.monotonic()
    cached = _admin_cache.get((tenant, user_id))
    if cached and now < cached[1]:
        return cached[0]

    # Baza xatosi oddiy foydalanuvchining har bir xabarini yiqitmasligi kerak —
    # aks holda userlar menyuni umuman ko'rmaydi (env adminlar esa ko'radi).
    try:
        async with aiosqlite.connect(DB_PATH) as db:
            async with db.execute(
                "SELECT 1 FROM admins WHERE user_id=?", (user_id,)
            ) as cursor:
                result = await cursor.fetchone()
    except Exception as e:
        print(f"[is_admin] DB xatosi: {e}")
        return False

    value = result is not None
    _admin_cache[(tenant, user_id)] = (value, now + ADMIN_CACHE_TTL)
    return value


def invalidate_admin_cache(user_id: int = None):
    """Admin qo'shilganda/o'chirilganda chaqiring."""
    if user_id:
        _admin_cache.pop((current_tenant(), user_id), None)
    else:
        _admin_cache.clear()


async def is_super_admin(user_id: int) -> bool:
    if current_tenant():
        return user_id == current_owner()
    return user_id == SUPER_ADMIN_ID or user_id in ADMIN_IDS


def payment_admin_ids() -> list[int]:
    """To'lov cheklari yuboriladigan adminlar (klon botda — egasi)."""
    if current_tenant():
        owner = current_owner()
        return [owner] if owner else []
    return [i for i in dict.fromkeys([SUPER_ADMIN_ID, *ADMIN_IDS]) if i]


async def is_maintenance() -> bool:
    tenant = current_tenant()
    now = time.monotonic()
    cached = _maintenance_cache.get(tenant)
    if cached and now < cached[1]:
        return cached[0]

    try:
        async with aiosqlite.connect(DB_PATH) as db:
            async with db.execute(
                "SELECT value FROM bot_settings WHERE key='bot_maintenance'"
            ) as cursor:
                row = await cursor.fetchone()
                value = row[0] == "1" if row else False
    except Exception:
        value = False

    _maintenance_cache[tenant] = (value, now + MAINT_CACHE_TTL)
    return value


async def is_content_restricted() -> bool:
    tenant = current_tenant()
    now = time.monotonic()
    cached = _restriction_cache.get(tenant)
    if cached and now < cached[1]:
        return cached[0]

    try:
        async with aiosqlite.connect(DB_PATH) as db:
            async with db.execute(
                "SELECT value FROM bot_settings WHERE key='content_restriction'"
            ) as cursor:
                row = await cursor.fetchone()
                value = row[0] == "1" if row else False
    except Exception:
        value = False

    _restriction_cache[tenant] = (value, now + MAINT_CACHE_TTL)
    return value


def invalidate_restriction_cache():
    _restriction_cache.pop(current_tenant(), None)


def _parse_chat_id(channel_id: str):
    try:
        return int(channel_id)
    except (ValueError, TypeError):
        return channel_id


async def get_bot_username(bot: Bot) -> str:
    username = _bot_username_cache.get(bot.id)
    if not username:
        me = await bot.get_me()
        username = _bot_username_cache[bot.id] = me.username
    return username


async def _get_channels_cached(db_filter: str) -> list:
    """Kanallarni DB dan olib, cache da saqlaydi."""
    tenant = current_tenant()
    now = time.monotonic()
    cached = _channel_names_cache.get((tenant, db_filter))
    if cached and now < cached[1]:
        return cached[0]

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

    _channel_names_cache[(tenant, db_filter)] = (rows, now + CHANNEL_CACHE_TTL)
    return rows


def invalidate_channel_cache():
    _channel_names_cache.clear()


async def check_subscription(user_id: int, bot: Bot) -> bool:
    """
    Barcha majburiy Telegram kanallarni parallel tekshiradi.
    Social kanallar tekshirilmaydi.
    Bot kanalda admin bo'lmasa — o'tkazib yuboradi.
    """
    try:
        rows = await _get_channels_cached("'public', 'request', 'social', 'ongoing'")
    except Exception as e:
        print(f"[Sub check] kanallarni o'qib bo'lmadi: {e}")
        return True
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
