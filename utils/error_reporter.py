"""Bot xatolarini Telegram orqali super adminga yuborish.

Bir xil xato (turi + kod joyi) ERROR_REPORT_COOLDOWN_SECONDS ichida faqat bir
marta yuboriladi; shu oraliqda takrorlanganlar sanab boriladi va keyingi
hisobotda "yana N marta" deb ko'rsatiladi — admin spam bilan to'lib ketmaydi.
"""
import html
import logging
import os
import time
import traceback
from datetime import datetime

from aiogram import Bot
from aiogram.types import Update

from config import ADMIN_IDS, SUPER_ADMIN_ID

logger = logging.getLogger(__name__)

ERROR_REPORT_COOLDOWN_SECONDS = int(os.getenv("ERROR_REPORT_COOLDOWN_SECONDS", "600"))
_PROJECT_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

# signature → (oxirgi yuborilgan vaqt, shu orada yutilgan takrorlar soni)
_last_sent: dict[str, tuple[float, int]] = {}


def _report_chat_id() -> int | None:
    value = os.getenv("ERROR_REPORT_CHAT_ID", "").strip()
    if value.lstrip("-").isdigit():
        return int(value)
    if SUPER_ADMIN_ID:
        return SUPER_ADMIN_ID
    return ADMIN_IDS[0] if ADMIN_IDS else None


def _project_frame(exc: BaseException) -> str:
    """Xato yuz bergan eng ichki loyiha fayli va qatori (kutubxonalar emas)."""
    frames = traceback.extract_tb(exc.__traceback__)
    for frame in reversed(frames):
        path = os.path.abspath(frame.filename)
        if path.startswith(_PROJECT_DIR) and "site-packages" not in path:
            rel = os.path.relpath(path, _PROJECT_DIR).replace("\\", "/")
            return f"{rel}:{frame.lineno} ({frame.name})"
    if frames:
        last = frames[-1]
        return f"{os.path.basename(last.filename)}:{last.lineno} ({last.name})"
    return "noma'lum"


def _describe_update(update: Update) -> tuple[str, str]:
    """(foydalanuvchi, nima yuborgan) juftligi."""
    user, action = None, "—"
    if update.message:
        user = update.message.from_user
        msg = update.message
        action = msg.text or msg.caption or (msg.content_type and f"[{msg.content_type}]") or "—"
    elif update.callback_query:
        user = update.callback_query.from_user
        action = f"tugma: {update.callback_query.data}"
    elif update.inline_query:
        user = update.inline_query.from_user
        action = f"inline: {update.inline_query.query}"
    if user is None:
        return "—", action
    name = user.full_name + (f" @{user.username}" if user.username else "")
    return f"{name} (<code>{user.id}</code>)", action


async def report_error(bot: Bot, update: Update, exc: BaseException) -> None:
    chat_id = _report_chat_id()
    if not chat_id:
        return

    location = _project_frame(exc)
    signature = f"{type(exc).__name__}|{location}"
    now = time.monotonic()
    last, suppressed = _last_sent.get(signature, (0.0, 0))
    if last and now - last < ERROR_REPORT_COOLDOWN_SECONDS:
        _last_sent[signature] = (last, suppressed + 1)
        return
    _last_sent[signature] = (now, 0)

    user, action = _describe_update(update)
    error_text = f"{type(exc).__name__}: {exc}"
    lines = [
        "🚨 <b>Botda xatolik</b>",
        "",
        f"<b>Xato:</b> <code>{html.escape(error_text[:700])}</code>",
        f"<b>Joyi:</b> <code>{html.escape(location)}</code>",
        f"<b>Foydalanuvchi:</b> {user}",
        f"<b>Yuborgan:</b> <code>{html.escape(str(action)[:300])}</code>",
        f"<b>Vaqt:</b> {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}",
    ]
    if suppressed:
        minutes = ERROR_REPORT_COOLDOWN_SECONDS // 60
        lines.append(f"\n🔁 Oldingi hisobotdan beri yana <b>{suppressed}</b> marta takrorlandi "
                     f"(bir xil xato {minutes} daqiqada bir marta yuboriladi).")

    try:
        await bot.send_message(chat_id, "\n".join(lines), parse_mode="HTML")
    except Exception as e:
        logger.warning("Xato hisoboti adminga yuborilmadi: %s", e)
