"""Asosiy botda foydalanuvchining o'z (klon) botini yaratishi va boshqarishi."""
import html
import logging

from aiogram import Bot, F, Router
from aiogram.filters import Command, Filter
from aiogram.types import (
    CallbackQuery, InlineKeyboardMarkup, KeyboardButtonRequestManagedBot,
    ManagedBotUpdated, Message, ReplyKeyboardMarkup,
)

from keyboards import InlineKeyboardButton, KeyboardButton
from utils import is_super_admin
from utils.clones import (
    MAX_CLONES_PER_USER, get_clone, is_clone_running, list_clones, register_clone,
    set_clone_status,
)
from utils.tenant import MAIN_BOT_ID
from utils.token_vault import vault_ready

logger = logging.getLogger(__name__)

CREATE_BOT_TEXT = "🤖 Bot yaratish"


class MainBotOnly(Filter):
    """Klon botlarda bu bo'lim ishlamaydi — faqat asosiy botda."""

    async def __call__(self, event, bot: Bot) -> bool:
        return bot.id == MAIN_BOT_ID


router = Router()
router.message.filter(MainBotOnly())
router.callback_query.filter(MainBotOnly())
router.managed_bot.filter(MainBotOnly())


def _create_kb() -> ReplyKeyboardMarkup:
    return ReplyKeyboardMarkup(
        keyboard=[
            [KeyboardButton(
                text="➕ Yangi bot yaratish",
                request_managed_bot=KeyboardButtonRequestManagedBot(
                    request_id=1, suggested_name="Anime bot"
                ),
            )],
            [KeyboardButton(text="◀️ Orqaga")],
        ],
        resize_keyboard=True,
    )


def _clone_line(row) -> str:
    bot_id, _owner, username, name, status = row
    state = "🟢 ishlayapti" if status == "active" and is_clone_running(bot_id) else "🔴 to'xtatilgan"
    return f"• <b>{html.escape(name or '')}</b> — @{html.escape(username or '')} ({state})"


def _clone_buttons(rows) -> InlineKeyboardMarkup | None:
    buttons = []
    for bot_id, _owner, username, _name, status in rows:
        if status == "active":
            buttons.append([InlineKeyboardButton(text=f"⏸ @{username} ni to'xtatish", callback_data=f"cloneStop={bot_id}")])
        else:
            buttons.append([InlineKeyboardButton(text=f"▶️ @{username} ni yoqish", callback_data=f"cloneStart={bot_id}")])
    return InlineKeyboardMarkup(inline_keyboard=buttons) if buttons else None


@router.message(F.text == CREATE_BOT_TEXT)
async def create_bot_menu(message: Message):
    if not vault_ready():
        await message.answer("⚠️ Bot yaratish vaqtincha o'chirilgan. Keyinroq urinib ko'ring.")
        return

    rows = await list_clones(owner_id=message.from_user.id)
    text = (
        "<b>🤖 O'z anime botingizni yarating</b>\n\n"
        "Bot sizning Telegram hisobingizda yaratiladi va bizning tizimimizda ishlaydi: "
        "anime qidirish, qismlar, VIP, to'lovlar, admin panel — hammasi bor.\n"
        "Botda faqat <b>sizning</b> kanalingiz, saytingiz va matnlaringiz chiqadi.\n\n"
        "1️⃣ Pastdagi «➕ Yangi bot yaratish» tugmasini bosing\n"
        "2️⃣ Bot nomi va username'ini tanlang\n"
        "3️⃣ Tayyor! Botingizga kirib /start bosing — siz uning adminisiz\n\n"
        f"<i>Bitta foydalanuvchi {MAX_CLONES_PER_USER} tagacha bot yarata oladi.</i>"
    )
    if rows:
        text += "\n\n<b>Sizning botlaringiz:</b>\n" + "\n".join(_clone_line(r) for r in rows)
    await message.answer(text, reply_markup=_create_kb(), parse_mode="HTML")
    markup = _clone_buttons(rows)
    if markup:
        await message.answer("⚙️ Botlarni boshqarish:", reply_markup=markup)


@router.managed_bot()
async def managed_bot_updated(event: ManagedBotUpdated, bot: Bot):
    """Foydalanuvchi bot yaratdi (yoki tokenini yangiladi) — tokenni olib ishga tushiramiz."""
    owner_id = event.user.id
    new_bot = event.bot_user
    existing = await get_clone(new_bot.id)
    if existing and existing[1] != owner_id:
        logger.warning("[clones] %s boshqa egaga tegishli, e'tiborsiz", new_bot.id)
        return

    if not existing:
        owned = await list_clones(owner_id=owner_id)
        if len(owned) >= MAX_CLONES_PER_USER and not await is_super_admin(owner_id):
            await bot.send_message(
                owner_id,
                f"❌ Bot ulanmadi: bitta foydalanuvchi {MAX_CLONES_PER_USER} tagacha bot yarata oladi.",
            )
            return

    try:
        token = await bot.get_managed_bot_token(user_id=new_bot.id)
        await register_clone(
            owner_id, new_bot.id, new_bot.username or "", new_bot.first_name or "", token
        )
    except Exception as e:
        logger.exception("[clones] @%s ulanmadi: %s", new_bot.username, e)
        await bot.send_message(owner_id, "⚠️ Botni ulashda xatolik yuz berdi. Birozdan keyin qayta urinib ko'ring.")
        return

    await bot.send_message(
        owner_id,
        f"✅ <b>@{html.escape(new_bot.username or '')}</b> tayyor!\n\n"
        "Botingizga kiring va /start bosing — siz uning adminisiz. "
        "«🗄 Boshqarish» orqali kanal, start matni, VIP narxi va boshqa sozlamalarni "
        "o'zingizga moslang.",
        parse_mode="HTML",
    )


@router.message(F.managed_bot_created)
async def managed_bot_created_message(message: Message):
    """Xizmat xabari — asosiy ish managed_bot update'ida bajariladi."""
    return


async def _toggle(callback: CallbackQuery, active: bool):
    bot_id = int(callback.data.split("=", 1)[1])
    row = await get_clone(bot_id)
    if not row or (row[1] != callback.from_user.id and not await is_super_admin(callback.from_user.id)):
        await callback.answer("❌ Bu bot sizga tegishli emas", show_alert=True)
        return
    try:
        await set_clone_status(bot_id, active)
    except Exception as e:
        logger.warning("[clones] %s holati o'zgarmadi: %s", bot_id, e)
        await callback.answer("⚠️ Xatolik yuz berdi", show_alert=True)
        return
    rows = await list_clones(owner_id=row[1])
    await callback.message.edit_reply_markup(reply_markup=_clone_buttons(rows))
    await callback.answer("▶️ Yoqildi" if active else "⏸ To'xtatildi")


@router.callback_query(F.data.startswith("cloneStop="))
async def clone_stop(callback: CallbackQuery):
    await _toggle(callback, active=False)


@router.callback_query(F.data.startswith("cloneStart="))
async def clone_start(callback: CallbackQuery):
    await _toggle(callback, active=True)


@router.message(Command("clones"))
async def all_clones(message: Message):
    if not await is_super_admin(message.from_user.id):
        return
    rows = await list_clones()
    if not rows:
        await message.answer("Hali klon botlar yo'q.")
        return
    lines = [f"{_clone_line(r)} — egasi <code>{r[1]}</code>" for r in rows]
    await message.answer(
        f"<b>🤖 Klon botlar ({len(rows)}):</b>\n\n" + "\n".join(lines),
        reply_markup=_clone_buttons(rows), parse_mode="HTML",
    )
