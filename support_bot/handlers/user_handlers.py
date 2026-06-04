"""
support_bot/handlers/user_handlers.py
Foydalanuvchi PM handlerlari (support bot bilan bevosita chat)
"""
import aiosqlite
from datetime import datetime
from aiogram import Router, F, Bot
from aiogram.filters import CommandStart, Command
from aiogram.types import Message, CallbackQuery
from aiogram.fsm.context import FSMContext

from config import DB_PATH, SUPPORT_GROUP_ID, ADMIN_IDS, SUPER_ADMIN_ID, MAIN_BOT_USERNAME
from support_bot.states import SupportUserStates
from support_bot.keyboards import (
    user_main_kb, cancel_kb, back_kb,
    faq_list_kb, faq_answer_kb,
    admin_main_kb, admin_panel_kb, ai_escalate_kb
)
from utils.ai_assistant import support_ai_triage

router = Router()
_ai_pending_messages: dict[int, str] = {}

# ─── Yordamchi funksiyalar ────────────────────────────────────────────────────

async def _is_admin(user_id: int) -> bool:
    return user_id == SUPER_ADMIN_ID or user_id in ADMIN_IDS


async def _get_faqs() -> list:
    async with aiosqlite.connect(DB_PATH) as db:
        async with db.execute(
            "SELECT id, question, answer, order_num FROM support_faq ORDER BY order_num ASC"
        ) as c:
            return await c.fetchall()


async def _get_main_kb(user_id: int):
    if await _is_admin(user_id):
        return admin_main_kb()
    return user_main_kb()


async def _create_support_ticket(
    user_id: int,
    username: str,
    full_name: str,
    text: str,
    bot: Bot
) -> int:

    async with aiosqlite.connect(DB_PATH) as db:
        cursor = await db.execute(
            """INSERT INTO support_tickets
               (user_id, username, full_name, message, status)
               VALUES (?, ?, ?, ?, 'open')""",
            (user_id, username, full_name, text)
        )
        ticket_id = cursor.lastrowid

        await db.execute(
            "INSERT INTO support_messages (ticket_id, sender_id, message, is_admin) VALUES (?, ?, ?, 0)",
            (ticket_id, user_id, text)
        )
        await db.commit()

    if SUPPORT_GROUP_ID:
        from support_bot.keyboards import ticket_admin_kb

        uname_str = f"@{username}" if username else f"<a href='tg://user?id={user_id}'>{full_name}</a>"
        group_text = (
            f"🎫 <b>Yangi murojaat #{ticket_id}</b>\n\n"
            f"👤 Foydalanuvchi: {uname_str}\n"
            f"🆔 ID: <code>{user_id}</code>\n"
            f"🕐 Vaqt: {datetime.now().strftime('%d.%m.%Y %H:%M')}\n\n"
            f"💬 <b>Xabar:</b>\n{text}"
        )
        try:
            sent = await bot.send_message(
                SUPPORT_GROUP_ID,
                group_text,
                reply_markup=ticket_admin_kb(ticket_id, user_id),
                parse_mode="HTML"
            )
            async with aiosqlite.connect(DB_PATH) as db:
                await db.execute(
                    "UPDATE support_tickets SET group_msg_id=? WHERE id=?",
                    (sent.message_id, ticket_id)
                )
                await db.commit()
        except Exception as e:
            print(f"[SupportBot] Guruhga yuborishda xato: {e}")

    return ticket_id


# ─── /start ──────────────────────────────────────────────────────────────────

@router.message(CommandStart())
async def cmd_start(message: Message, state: FSMContext, bot: Bot):
    await state.clear()
    user_id = message.from_user.id
    is_adm = await _is_admin(user_id)

    main_bot = f"@{MAIN_BOT_USERNAME}" if MAIN_BOT_USERNAME else "asosiy bot"

    welcome = (
        f"👋 <b>Salom, {message.from_user.first_name}!</b>\n\n"
        f"🎯 Bu — <b>Support Bot</b>.\n\n"
        f"Bu bot orqali siz:\n"
        f"• ❓ Savollaringizni adminga yetkazishingiz\n"
        f"• 📋 Ko'p so'raladigan savollarga javob olishingiz\n"
        f"• 🤖 {main_bot} haqida ma'lumot olishingiz mumkin.\n\n"
        f"Quyidagi menyudan foydalaning 👇"
    )

    if is_adm:
        welcome += "\n\n🗄 <i>Admin sifatida kirildi</i>"

    await message.answer(
        welcome,
        reply_markup=await _get_main_kb(user_id),
        parse_mode="HTML"
    )


# ─── Murojaat yuborish ────────────────────────────────────────────────────────

@router.message(F.text == "💬 Murojaat yuborish")
async def start_support_request(message: Message, state: FSMContext):
    await state.set_state(SupportUserStates.writing_message)
    await message.answer(
        "✍️ <b>Murojaatingizni yozing:</b>\n\n"
        "<i>Savolingizni, muammoingizni yoki taklifingizni batafsil yozing. "
        "Admin imkon qadar tez javob beradi.</i>",
        reply_markup=cancel_kb(),
        parse_mode="HTML"
    )


@router.message(SupportUserStates.writing_message, F.text == "❌ Bekor qilish")
async def cancel_writing(message: Message, state: FSMContext):
    await state.clear()
    await message.answer(
        "❌ Murojaat bekor qilindi.",
        reply_markup=await _get_main_kb(message.from_user.id),
        parse_mode="HTML"
    )


@router.message(SupportUserStates.writing_message, F.text)
async def receive_support_message(message: Message, state: FSMContext, bot: Bot):
    await state.clear()
    text = message.text

    # AI yordamchi javobi
    faqs = await _get_faqs()
    triage = await support_ai_triage(text, faqs, MAIN_BOT_USERNAME)
    if triage and triage.get("reply"):
        await message.answer(
            f"🤖 AI Yordamchi:\n\n{triage['reply']}",
            reply_markup=ai_escalate_kb() if not triage.get("escalate", True) else None
        )

    # Eskalatsiya kerak bo'lmasa ticket yaratmaymiz; user xohlasa tugma orqali yuboradi
    if triage and triage.get("escalate") is False:
        _ai_pending_messages[message.from_user.id] = text
        await message.answer(
            "✅ Savolingizga AI yordamchi javob berdi. Agar baribir admin ko'rishini istasangiz, pastdagi tugmani bosing.",
            reply_markup=await _get_main_kb(message.from_user.id),
            parse_mode="HTML"
        )
        return

    ticket_id = await _create_support_ticket(
        user_id=message.from_user.id,
        username=message.from_user.username or "",
        full_name=message.from_user.full_name or "",
        text=text,
        bot=bot
    )

    # Foydalanuvchiga tasdiqlash
    await message.answer(
        f"✅ <b>Murojaatingiz qabul qilindi!</b>\n\n"
        f"🎫 Murojaat raqami: <b>#{ticket_id}</b>\n\n"
        f"Admin tez orada javob beradi. Kuting...",
        reply_markup=await _get_main_kb(message.from_user.id),
        parse_mode="HTML"
    )


@router.callback_query(F.data == "sup_send_admin")
async def send_to_admin_after_ai(callback: CallbackQuery, bot: Bot):
    user_id = callback.from_user.id
    cached_text = _ai_pending_messages.pop(user_id, None)
    if not cached_text:
        await callback.answer("❌ Yuboriladigan xabar topilmadi. Qayta yozib yuboring.", show_alert=True)
        return

    ticket_id = await _create_support_ticket(
        user_id=callback.from_user.id,
        username=callback.from_user.username or "",
        full_name=callback.from_user.full_name or "",
        text=cached_text,
        bot=bot
    )
    await callback.message.answer(
        f"✅ Adminga yuborildi!\n\n🎫 Ticket: <b>#{ticket_id}</b>",
        parse_mode="HTML"
    )
    await callback.answer("✅ Adminga yuborildi")


# ─── Mening murojaatlarim ─────────────────────────────────────────────────────

@router.message(F.text == "📊 Mening murojaatlarim")
async def my_tickets(message: Message):
    user_id = message.from_user.id

    async with aiosqlite.connect(DB_PATH) as db:
        async with db.execute(
            """SELECT id, message, status, created_at
               FROM support_tickets
               WHERE user_id=?
               ORDER BY created_at DESC LIMIT 10""",
            (user_id,)
        ) as c:
            tickets = await c.fetchall()

    if not tickets:
        await message.answer(
            "📭 <b>Sizda hozircha murojaatlar yo'q.</b>\n\n"
            "Savol yoki muammo bo'lsa, «💬 Murojaat yuborish» tugmasini bosing.",
            reply_markup=await _get_main_kb(user_id),
            parse_mode="HTML"
        )
        return

    STATUS_EMOJI = {"open": "🟡", "closed": "🔒", "answered": "✅"}
    STATUS_TEXT = {"open": "Kutilmoqda", "closed": "Yopildi", "answered": "Javob berildi"}

    lines = ["📊 <b>Murojaatlaringiz (oxirgi 10 ta):</b>\n"]
    for t in tickets:
        tid, msg, status, created = t
        emoji = STATUS_EMOJI.get(status, "⚪")
        label = STATUS_TEXT.get(status, status)
        short_msg = msg[:60] + ("..." if len(msg) > 60 else "")
        dt = created[:16] if created else ""
        lines.append(f"{emoji} <b>#{tid}</b> — {label}\n   <i>{short_msg}</i>\n   🕐 {dt}\n")

    await message.answer(
        "\n".join(lines),
        reply_markup=await _get_main_kb(user_id),
        parse_mode="HTML"
    )


# ─── FAQ ──────────────────────────────────────────────────────────────────────

@router.message(F.text == "📋 FAQ — Ko'p so'raladigan savollar")
async def show_faq(message: Message):
    faqs = await _get_faqs()
    if not faqs:
        await message.answer("📭 FAQ bo'sh. Tez orada to'ldiriladi.")
        return

    await message.answer(
        "📋 <b>Ko'p so'raladigan savollar:</b>\n\n"
        "Quyidagi savollardan birini tanlang:",
        reply_markup=faq_list_kb(faqs),
        parse_mode="HTML"
    )


@router.callback_query(F.data.startswith("faq="))
async def faq_answer(callback: CallbackQuery):
    faq_id = int(callback.data.split("=")[1])
    faqs = await _get_faqs()

    faq = next((f for f in faqs if f[0] == faq_id), None)
    if not faq:
        await callback.answer("FAQ topilmadi!", show_alert=True)
        return

    index = faqs.index(faq)
    text = (
        f"❓ <b>{faq[1]}</b>\n\n"
        f"{faq[2]}"
    )
    await callback.message.edit_text(
        text,
        reply_markup=faq_answer_kb(faq_id, len(faqs), index),
        parse_mode="HTML"
    )
    await callback.answer()


@router.callback_query(F.data.startswith("faq_nav="))
async def faq_navigate(callback: CallbackQuery):
    idx = int(callback.data.split("=")[1])
    faqs = await _get_faqs()

    if idx < 0 or idx >= len(faqs):
        await callback.answer()
        return

    faq = faqs[idx]
    text = f"❓ <b>{faq[1]}</b>\n\n{faq[2]}"
    await callback.message.edit_text(
        text,
        reply_markup=faq_answer_kb(faq[0], len(faqs), idx),
        parse_mode="HTML"
    )
    await callback.answer()


@router.callback_query(F.data == "faq_list")
async def faq_list_back(callback: CallbackQuery):
    faqs = await _get_faqs()
    await callback.message.edit_text(
        "📋 <b>Ko'p so'raladigan savollar:</b>\n\nQuyidagi savollardan birini tanlang:",
        reply_markup=faq_list_kb(faqs),
        parse_mode="HTML"
    )
    await callback.answer()


@router.callback_query(F.data == "faq_back")
async def faq_back(callback: CallbackQuery):
    await callback.message.delete()
    await callback.answer()


# ─── Bot haqida ───────────────────────────────────────────────────────────────

@router.message(F.text == "🤖 Bot haqida")
async def about_bot(message: Message):
    main_bot = f"@{MAIN_BOT_USERNAME}" if MAIN_BOT_USERNAME else "Asosiy bot"
    text = (
        f"🤖 <b>Bot haqida ma'lumot</b>\n\n"
        f"🎬 <b>Asosiy bot:</b> {main_bot}\n"
        f"   Anime va kino qidirish, ko'rish, yuklash\n\n"
        f"🛠 <b>Imkoniyatlar:</b>\n"
        f"   • Anime nomi, janr, kod bo'yicha qidiruv\n"
        f"   • Qismlab yoki to'liq yuklash\n"
        f"   • VIP a'zolik tizimi\n"
        f"   • Referal va cashback tizimi\n"
        f"   • 💎 VIP foydalanuvchilar uchun maxsus kontent\n\n"
        f"📞 <b>Muammo bo'lsa:</b>\n"
        f"   «💬 Murojaat yuborish» tugmasi orqali adminga yozing.\n\n"
        f"📋 <b>Ko'p uchraydigan savollar:</b>\n"
        f"   «📋 FAQ» bo'limiga qarang."
    )
    await message.answer(text, parse_mode="HTML")


# ─── Admin panelga kirish ─────────────────────────────────────────────────────

@router.message(F.text == "🗄 Admin panel")
async def admin_panel_enter(message: Message):
    if not await _is_admin(message.from_user.id):
        return
    await message.answer(
        "🗄 <b>Admin panel</b>\n\nNimani boshqarmoqchisiz?",
        reply_markup=admin_panel_kb(),
        parse_mode="HTML"
    )


@router.message(F.text == "◀️ Orqaga")
async def go_back(message: Message, state: FSMContext):
    await state.clear()
    await message.answer(
        "🏠 Bosh menyu",
        reply_markup=await _get_main_kb(message.from_user.id),
        parse_mode="HTML"
    )
