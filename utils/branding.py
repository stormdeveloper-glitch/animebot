"""Bot nomi/kanali — asosiy botda env dan, klon botda o'z sozlamalaridan.

Klon botlarda AnimeUZ bot havolasi yoki kanali chiqmasligi kerak, shuning uchun
config.BOT_USERNAME / MAIN_CHANNEL_* o'rniga shu funksiya ishlatiladi.
"""
import aiosqlite

from config import BOT_USERNAME, DB_PATH, MAIN_CHANNEL_ID, MAIN_CHANNEL_USERNAME
from utils.tenant import current_tenant


async def brand_config() -> tuple:
    """(MAIN_CHANNEL_ID, BOT_USERNAME, MAIN_CHANNEL_USERNAME) joriy bot uchun."""
    tenant = current_tenant()
    if not tenant:
        return MAIN_CHANNEL_ID, BOT_USERNAME, MAIN_CHANNEL_USERNAME

    from utils.clones import clone_username

    channel = ""
    try:
        async with aiosqlite.connect(DB_PATH) as db:
            async with db.execute("SELECT value FROM bot_settings WHERE key='main_channel'") as c:
                row = await c.fetchone()
        channel = (row[0] if row else "") or ""
    except Exception:
        channel = ""
    channel = channel.strip().replace("https://t.me/", "")
    channel_id = None
    channel_username = ""
    if channel.lstrip("-").isdigit():
        channel_id = int(channel)
    elif channel:
        channel_username = channel.lstrip("@")
        channel_id = f"@{channel_username}"
    return channel_id, clone_username(tenant), channel_username
