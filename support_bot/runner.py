"""
support_bot/runner.py
Support botni ishga tushirish moduli.
main.py tomonidan asyncio.gather() orqali chaqiriladi.
"""
import logging
from aiogram import Bot, Dispatcher
from aiogram.fsm.storage.memory import MemoryStorage

from config import SUPPORT_BOT_TOKEN, SUPPORT_GROUP_ID
from support_bot.handlers import user_handlers, admin_handlers

logger = logging.getLogger("support_bot")


async def run_support_bot():
    """Support botni polling rejimida ishga tushiradi."""
    if not SUPPORT_BOT_TOKEN:
        logger.warning(
            "[SupportBot] SUPPORT_BOT_TOKEN o'rnatilmagan — support bot ishlamaydi."
        )
        return

    bot = Bot(token=SUPPORT_BOT_TOKEN)
    dp = Dispatcher(storage=MemoryStorage())

    # Routerlar: admin_handlers OLDIN (guruh callbacklari uchun)
    dp.include_router(admin_handlers.router)
    dp.include_router(user_handlers.router)

    try:
        me = await bot.get_me()
    except Exception as e:
        logger.error(f"[SupportBot] Token yoki tarmoq xatosi: {e}")
        print(f"❌ Support bot ishga tushmadi: {e}")
        await bot.session.close()
        return

    if not SUPPORT_GROUP_ID:
        logger.warning("[SupportBot] SUPPORT_GROUP_ID berilmagan (0). Ticketlar guruhga yuborilmaydi.")
    elif str(SUPPORT_GROUP_ID).startswith("-100") is False:
        logger.warning("[SupportBot] SUPPORT_GROUP_ID noto'g'ri formatda bo'lishi mumkin. Odatda -100... bo'ladi.")

    logger.info(f"[SupportBot] @{me.username} ishga tushdi.")
    print(f"✅ Support bot @{me.username} ishga tushdi.")

    try:
        await dp.start_polling(bot, allowed_updates=dp.resolve_used_update_types())
    finally:
        await bot.session.close()
        logger.info("[SupportBot] To'xtatildi.")
