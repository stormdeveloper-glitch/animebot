"""
support_bot/handlers/admin_handlers.py
Admin handlerlari:
  - Guruhda ticket tugmalari (Javob berish / Yopish)
  - PM da admin javobi (FSM)
  - PM da support statistika, ochiq murojaatlar, FAQ boshqarish
"""
import aiosqlite
from datetime import datetime
from aiogram import Router, F, Bot
from aiogram.filters import Command
from aiogram.types import Message, CallbackQuery
from aiogram.fsm.context import FSMContext

from config import DB_PATH, SUPPORT_GROUP_ID, ADMIN_IDS, SUPER_ADMIN_ID
from support_bot.states import SupportAdminStates
from support_bot.keyboards import (
    ticket_admin_kb, ticket_closed_kb, ticket_answered_kb,
    confirm_reply_kb, admin_panel_kb, admin_main_kb
)

router = Router()

# ─── Yordamchi ───────────────────────────────────────────────────────────────

async def _is_admin(user_id: int) -> bool:
    return user_id == SUPER_ADMIN_ID or user_id in ADMIN_IDS


async def _get_ticket(ticket_id: int) -> dict | None:
    async with aiosqlite.connect(DB_PATH) as db:
        async with db.execute(
            "SELECT id, user_id, username, full_name, message, status FROM support_tickets WHERE id=?",
            (ticket_id,)
        ) as c:
            row = await c.fetchone()
    if not row:
        return None
    return {
        "id": row[0], "user_id": row[1], "username": row[2],
        "full_name": row[3], "message": row[4], "status": row[5]
    }


# ─── Guruh: Javob berish tugmasi ─────────────────────────────────────────────

@router.callback_query(F.data.startswith("sup_reply="))
async def cb_reply_ticket(callback: CallbackQuery, state: FSMContext, bot: Bot):
    """Admin guruhda 'Javob berish' ni bosdi → unga PM da so'raydi."""
    if not await _is_admin(callback.from_user.id):
        await callback.answer("❌ Faqat adminlar!", show_alert=True)
        return

    parts = callback.data.split("=")
    ticket_id = int(parts[1])
    user_id = int(parts[2])

    ticket = await _get_ticket(ticket_id)
    if not ticket:
        await callback.answer("❌ Murojaat topilmadi!", show_alert=True)
        return

    if ticket["status"] == "closed":
        await callback.answer("🔒 Bu murojaat yopilgan!", show_alert=True)
        return

    admin_id = callback.from_user.id

    # Admin PM da state saqlash
    try:
        await bot.send_message(
            admin_id,
            f"✍️ <b>Ticket #{ticket_id} ga javob yozmoqdasiz</b>\n\n"
            f"👤 Foydalanuvchi: {ticket['full_name']} "
            f"({'@' + ticket['username'] if ticket['username'] else 'username yoq'})\n\n"
            f"💬 <b>Murojaat:</b>\n{ticket['message']}\n\n"
            f"<i>Javobingizni yozing:</i>",
            parse_mode="HTML"
        )
    except Exception as e:
        await callback.answer(
            f"❌ Sizga PM yuborib bo'lmadi! Avval @{(await bot.get_me()).username} bilan chatni oching.",
            show_alert=True
        )
        return

    # Admin PM kontekstida state saqlash (FSMContext chat_id = admin_id bo'lishi kerak)
    # Bu yerda guruh kontekstida state saqlanadi — runner.py da buni hal qilamiz
    # Oddiy dict ishlatamiz (persistent emas, lekin ishonchli)
    _pending_replies[admin_id] = {
        "ticket_id": ticket_id,
        "target_user_id": user_id,
        "draft": None
    }

    await callback.answer("✅ PM ga javob yubordim. Xabarni yozing.", show_alert=False)


# ─── Guruh: Yopish tugmasi ────────────────────────────────────────────────────

@router.callback_query(F.data.startswith("sup_close="))
async def cb_close_ticket(callback: CallbackQuery, bot: Bot):
    if not await _is_admin(callback.from_user.id):
        await callback.answer("❌ Faqat adminlar!", show_alert=True)
        return

    parts = callback.data.split("=")
    ticket_id = int(parts[1])

    ticket = await _get_ticket(ticket_id)
    if not ticket:
        await callback.answer("❌ Murojaat topilmadi!", show_alert=True)
        return

    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute(
            "UPDATE support_tickets SET status='closed' WHERE id=?", (ticket_id,)
        )
        await db.commit()

    # Guruh xabarini yangilash
    try:
        await callback.message.edit_reply_markup(
            reply_markup=ticket_closed_kb(ticket_id)
        )
    except Exception:
        pass

    # Foydalanuvchiga xabar
    try:
        await bot.send_message(
            ticket["user_id"],
            f"🔒 <b>Murojaatingiz yopildi</b>\n\n"
            f"🎫 Ticket #{ticket_id}\n\n"
            f"Yangi savol bo'lsa, yana murojaat yuboring.",
            parse_mode="HTML"
        )
    except Exception:
        pass

    await callback.answer(f"✅ Ticket #{ticket_id} yopildi.")


# ─── Guruh: Profil tugmasi ────────────────────────────────────────────────────

@router.callback_query(F.data.startswith("sup_profile="))
async def cb_user_profile(callback: CallbackQuery):
    if not await _is_admin(callback.from_user.id):
        await callback.answer("❌ Faqat adminlar!", show_alert=True)
        return

    user_id = int(callback.data.split("=")[1])

    async with aiosqlite.connect(DB_PATH) as db:
        # Asosiy bot DB dan ma'lumot
        async with db.execute(
            "SELECT status, pul, ban, joined_at FROM users WHERE user_id=?", (user_id,)
        ) as c:
            user_row = await c.fetchone()

        # Ticket soni
        async with db.execute(
            "SELECT COUNT(*) FROM support_tickets WHERE user_id=?", (user_id,)
        ) as c:
            ticket_count = (await c.fetchone())[0]

    if user_row:
        status, pul, ban, joined = user_row
        profile_text = (
            f"👤 <b>Foydalanuvchi profili</b>\n\n"
            f"🆔 ID: <code>{user_id}</code>\n"
            f"📌 Status: {status}\n"
            f"💰 Balans: {pul} so'm\n"
            f"🚫 Ban: {ban}\n"
            f"📅 Qo'shilgan: {(joined or '')[:10]}\n"
            f"🎫 Jami murojaatlar: {ticket_count}"
        )
    else:
        profile_text = (
            f"👤 <b>Foydalanuvchi profili</b>\n\n"
            f"🆔 ID: <code>{user_id}</code>\n"
            f"🎫 Jami murojaatlar: {ticket_count}\n\n"
            f"<i>Asosiy botda ro'yxatdan o'tmagan</i>"
        )

    await callback.answer(profile_text[:200], show_alert=True)


# ─── null callback (tugmalar uchun) ──────────────────────────────────────────

@router.callback_query(F.data == "null")
async def cb_null(callback: CallbackQuery):
    await callback.answer()


# ─── PM: Admin javobi (pending_replies dict orqali) ──────────────────────────
# Admin botda PM da xabar yuborganda — pending_replies ni tekshiramiz

_pending_replies: dict[int, dict] = {}
# {admin_id: {"ticket_id": int, "target_user_id": int, "draft": str|None}}


@router.message(F.chat.type == "private", F.text)
async def handle_admin_pm(message: Message, bot: Bot):
    """Admin PM da xabar yuborganda — ticket javobimi yoki boshqa narsami tekshirish."""
    admin_id = message.from_user.id

    if not await _is_admin(admin_id):
        return  # Admin emas, user_handlers hal qiladi

    # Pending reply bor?
    pending = _pending_replies.get(admin_id)
    if not pending:
        return  # Pending yo'q, boshqa handlerlar ishlaydi

    text = message.text.strip()

    # Bekor qilish
    if text in ("❌ Bekor", "/bekor", "bekor", "cancel"):
        _pending_replies.pop(admin_id, None)
        await message.answer("❌ Javob bekor qilindi.", reply_markup=admin_main_kb())
        return

    ticket_id = pending["ticket_id"]
    target_user_id = pending["target_user_id"]

    # Tasdiqlash so'rash
    _pending_replies[admin_id]["draft"] = text

    ticket = await _get_ticket(ticket_id)
    preview_msg = text[:300] + ("..." if len(text) > 300 else "")

    await message.answer(
        f"📝 <b>Javob ko'rish (Ticket #{ticket_id})</b>\n\n"
        f"{preview_msg}\n\n"
        f"<i>Yuborasizmi?</i>",
        reply_markup=confirm_reply_kb(ticket_id),
        parse_mode="HTML"
    )


@router.callback_query(F.data.startswith("confirm_reply="))
async def confirm_reply(callback: CallbackQuery, bot: Bot):
    admin_id = callback.from_user.id
    ticket_id = int(callback.data.split("=")[1])

    pending = _pending_replies.get(admin_id)
    if not pending or pending["ticket_id"] != ticket_id:
        await callback.answer("❌ Javob topilmadi!", show_alert=True)
        return

    draft = pending.get("draft")
    target_user_id = pending["target_user_id"]

    if not draft:
        await callback.answer("❌ Xabar bo'sh!", show_alert=True)
        return

    # Foydalanuvchiga yuborish
    try:
        await bot.send_message(
            target_user_id,
            f"📬 <b>Murojaatingizga javob (Ticket #{ticket_id})</b>\n\n"
            f"{draft}\n\n"
            f"<i>Agar qo'shimcha savollaringiz bo'lsa, yana murojaat yuboring.</i>",
            parse_mode="HTML"
        )
        user_notified = True
    except Exception as e:
        user_notified = False
        print(f"[SupportBot] Foydalanuvchiga yuborishda xato: {e}")

    # DB yangilash
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute(
            "UPDATE support_tickets SET status='answered' WHERE id=?", (ticket_id,)
        )
        await db.execute(
            "INSERT INTO support_messages (ticket_id, sender_id, message, is_admin) VALUES (?, ?, ?, 1)",
            (ticket_id, admin_id, draft)
        )
        await db.commit()

        # Guruh xabarini yangilash
        async with db.execute(
            "SELECT group_msg_id FROM support_tickets WHERE id=?", (ticket_id,)
        ) as c:
            row = await c.fetchone()
            group_msg_id = row[0] if row else None

    if group_msg_id and SUPPORT_GROUP_ID:
        try:
            await bot.edit_message_reply_markup(
                chat_id=SUPPORT_GROUP_ID,
                message_id=group_msg_id,
                reply_markup=ticket_answered_kb(ticket_id)
            )
        except Exception:
            pass

    _pending_replies.pop(admin_id, None)

    status_icon = "✅" if user_notified else "⚠️"
    status_text = "foydalanuvchiga yuborildi" if user_notified else "yuborib bo'lmadi (PM bloklangan bo'lishi mumkin)"

    await callback.message.edit_text(
        f"{status_icon} <b>Javob {status_text}!</b>\n\n"
        f"🎫 Ticket #{ticket_id} — javob berildi deb belgilandi.",
        parse_mode="HTML"
    )
    await callback.answer("✅ Yuborildi!")


@router.callback_query(F.data.startswith("rewrite_reply="))
async def rewrite_reply(callback: CallbackQuery):
    admin_id = callback.from_user.id
    ticket_id = int(callback.data.split("=")[1])

    pending = _pending_replies.get(admin_id)
    if pending:
        _pending_replies[admin_id]["draft"] = None

    await callback.message.edit_text(
        f"✍️ Ticket #{ticket_id} uchun qayta javob yozing:",
        parse_mode="HTML"
    )
    await callback.answer()


@router.callback_query(F.data == "cancel_reply")
async def cancel_reply_cb(callback: CallbackQuery):
    admin_id = callback.from_user.id
    _pending_replies.pop(admin_id, None)
    await callback.message.edit_text("❌ Javob bekor qilindi.")
    await callback.answer()


# ─── Admin panel: Statistika ──────────────────────────────────────────────────

@router.message(F.text == "📊 Support statistika", F.chat.type == "private")
async def support_stats(message: Message):
    if not await _is_admin(message.from_user.id):
        return

    async with aiosqlite.connect(DB_PATH) as db:
        async with db.execute("SELECT COUNT(*) FROM support_tickets") as c:
            total = (await c.fetchone())[0]
        async with db.execute("SELECT COUNT(*) FROM support_tickets WHERE status='open'") as c:
            open_count = (await c.fetchone())[0]
        async with db.execute("SELECT COUNT(*) FROM support_tickets WHERE status='answered'") as c:
            answered = (await c.fetchone())[0]
        async with db.execute("SELECT COUNT(*) FROM support_tickets WHERE status='closed'") as c:
            closed = (await c.fetchone())[0]
        async with db.execute("SELECT COUNT(DISTINCT user_id) FROM support_tickets") as c:
            unique_users = (await c.fetchone())[0]
        # Bugun
        async with db.execute(
            "SELECT COUNT(*) FROM support_tickets WHERE DATE(created_at)=DATE('now')"
        ) as c:
            today = (await c.fetchone())[0]

    await message.answer(
        f"📊 <b>Support statistikasi</b>\n\n"
        f"📨 Jami murojaatlar: <b>{total}</b>\n"
        f"🟡 Kutilmoqda: <b>{open_count}</b>\n"
        f"✅ Javob berilgan: <b>{answered}</b>\n"
        f"🔒 Yopilgan: <b>{closed}</b>\n"
        f"👤 Noyob foydalanuvchilar: <b>{unique_users}</b>\n"
        f"📅 Bugun: <b>{today}</b>",
        parse_mode="HTML"
    )


# ─── Admin panel: Ochiq murojaatlar ──────────────────────────────────────────

@router.message(F.text == "📋 Ochiq murojaatlar", F.chat.type == "private")
async def open_tickets(message: Message):
    if not await _is_admin(message.from_user.id):
        return

    async with aiosqlite.connect(DB_PATH) as db:
        async with db.execute(
            """SELECT id, full_name, username, message, created_at
               FROM support_tickets WHERE status='open'
               ORDER BY created_at ASC LIMIT 15"""
        ) as c:
            tickets = await c.fetchall()

    if not tickets:
        await message.answer("✅ Ochiq murojaatlar yo'q!")
        return

    lines = [f"📋 <b>Ochiq murojaatlar ({len(tickets)} ta):</b>\n"]
    for t in tickets:
        tid, fname, uname, msg, created = t
        user_str = f"@{uname}" if uname else fname
        short = msg[:50] + ("..." if len(msg) > 50 else "")
        dt = (created or "")[:16]
        lines.append(f"🟡 <b>#{tid}</b> — {user_str}\n   <i>{short}</i>\n   🕐 {dt}\n")

    await message.answer("\n".join(lines), parse_mode="HTML")


# ─── Admin panel: FAQ boshqarish ─────────────────────────────────────────────

@router.message(F.text == "❓ FAQ boshqarish", F.chat.type == "private")
async def faq_manage(message: Message):
    if not await _is_admin(message.from_user.id):
        return

    async with aiosqlite.connect(DB_PATH) as db:
        async with db.execute(
            "SELECT id, question FROM support_faq ORDER BY order_num"
        ) as c:
            faqs = await c.fetchall()

    from aiogram.types import InlineKeyboardMarkup
    from support_bot.keyboards import InlineKeyboardButton
    keyboard = [
        [InlineKeyboardButton(
            text=f"🗑 #{f[0]}: {f[1][:40]}",
            callback_data=f"faq_del={f[0]}"
        )]
        for f in faqs
    ]
    keyboard.append([InlineKeyboardButton(text="➕ Yangi savol qo'shish", callback_data="faq_add")])

    await message.answer(
        f"❓ <b>FAQ boshqarish</b>\n\nJami: {len(faqs)} ta savol\n\nO'chirish uchun bosing:",
        reply_markup=InlineKeyboardMarkup(inline_keyboard=keyboard),
        parse_mode="HTML"
    )


@router.callback_query(F.data.startswith("faq_del="))
async def faq_delete(callback: CallbackQuery):
    if not await _is_admin(callback.from_user.id):
        await callback.answer("❌ Faqat adminlar!", show_alert=True)
        return

    faq_id = int(callback.data.split("=")[1])
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute("DELETE FROM support_faq WHERE id=?", (faq_id,))
        await db.commit()

    await callback.answer(f"✅ FAQ #{faq_id} o'chirildi!", show_alert=True)
    await callback.message.delete()


@router.callback_query(F.data == "faq_add")
async def faq_add_start(callback: CallbackQuery, state: FSMContext):
    if not await _is_admin(callback.from_user.id):
        await callback.answer("❌ Faqat adminlar!", show_alert=True)
        return

    await state.set_state(SupportAdminStates.adding_faq_question)
    await callback.message.answer("❓ Yangi savolni yozing:")
    await callback.answer()


@router.message(SupportAdminStates.adding_faq_question, F.text, F.chat.type == "private")
async def faq_add_question(message: Message, state: FSMContext):
    await state.update_data(faq_question=message.text)
    await state.set_state(SupportAdminStates.adding_faq_answer)
    await message.answer("💬 Endi javobni yozing (HTML format qabul qilinadi):")


@router.message(SupportAdminStates.adding_faq_answer, F.text, F.chat.type == "private")
async def faq_add_answer(message: Message, state: FSMContext):
    data = await state.get_data()
    question = data.get("faq_question", "")
    answer = message.text
    await state.clear()

    async with aiosqlite.connect(DB_PATH) as db:
        async with db.execute("SELECT MAX(order_num) FROM support_faq") as c:
            row = await c.fetchone()
            next_order = (row[0] or 0) + 1
        await db.execute(
            "INSERT INTO support_faq (question, answer, order_num) VALUES (?, ?, ?)",
            (question, answer, next_order)
        )
        await db.commit()

    await message.answer(
        f"✅ <b>FAQ qo'shildi!</b>\n\n"
        f"❓ {question}\n💬 {answer[:100]}...",
        parse_mode="HTML"
    )
