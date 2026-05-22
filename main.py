import asyncio
import logging
from aiogram import Bot, Dispatcher
from aiogram.fsm.storage.memory import MemoryStorage

from config import BOT_TOKEN, SUPPORT_BOT_TOKEN, DB_PATH, BOT_USER_RATE_LIMIT_PER_MIN
from database import init_db, init_support_db
from handlers import user_handlers, admin_handlers, inline_handlers
from keyboards import load_button_styles
from utils.text_sanitizer import patch_aiogram_text_sanitizer
from utils.throttle import UserRateLimitMiddleware
from web_server import start_web_server

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(name)s] %(levelname)s: %(message)s"
)
logger = logging.getLogger("main")


async def run_main_bot():
    """Asosiy anime botni ishga tushirish."""
    bot = Bot(token=BOT_TOKEN)
    dp = Dispatcher(storage=MemoryStorage())
    throttle = UserRateLimitMiddleware(limit=BOT_USER_RATE_LIMIT_PER_MIN)
    dp.message.middleware(throttle)
    dp.callback_query.middleware(throttle)

    dp.include_router(admin_handlers.router)
    dp.include_router(user_handlers.router)
    dp.include_router(inline_handlers.router)

    me = await bot.get_me()
    logger.info(f"[MainBot] @{me.username} ishga tushdi.")
    print(f"✅ Asosiy bot @{me.username} ishga tushdi.")

    try:
        await dp.start_polling(bot, allowed_updates=dp.resolve_used_update_types())
    finally:
        await bot.session.close()


async def run_support_bot_safe():
    """
    Support botni xavfsiz ishga tushirish:
    xato bo'lsa asosiy botni yiqitmaydi.
    """
    if not SUPPORT_BOT_TOKEN:
        print("⚠️  SUPPORT_BOT_TOKEN topilmadi — support bot o'chirilgan.")
        return

    from support_bot.runner import run_support_bot
    try:
        await run_support_bot()
    except Exception as e:
        logger.exception(f"[SupportBot] Kutilmagan xato: {e}")
        print(f"⚠️ Support bot xatolik bilan to'xtadi: {e}")


async def main():
    patch_aiogram_text_sanitizer()

    # DB larni ishga tushirish
    await init_db()
    await init_support_db()
    await load_button_styles(DB_PATH)

    # Web server
    web_runner = await start_web_server()
    print("✅ Web server ishga tushdi.")

    tasks = [run_main_bot(), run_support_bot_safe()]

    try:
        await asyncio.gather(*tasks)
    finally:
        await web_runner.cleanup()
        print("Bot(lar) to'xtatildi.")


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        print("\nBot(lar) to'xtatildi.")
