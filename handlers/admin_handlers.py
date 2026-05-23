import aiosqlite
import aiohttp
import datetime
import html
from aiogram import Router, F, Bot
from aiogram.filters import Command
from aiogram.types import Message, CallbackQuery, InlineKeyboardMarkup
from aiogram.fsm.context import FSMContext
from config import ADMIN_IDS, SUPER_ADMIN_ID, DB_PATH
from keyboards import (
    panel_kb, boshqarish_kb, menu_kb, InlineKeyboardButton,
    normalize_button_style, set_button_style
)
from states import AdminStates, EditAnimeStates, SettingsStates, ButtonStates, PostStates
from utils import is_admin, is_super_admin, get_bot_username, invalidate_channel_cache, invalidate_admin_cache, is_content_restricted, invalidate_restriction_cache
from utils.admin_manager import add_json_admin, remove_json_admin
from utils.logger import log_admin_action
from utils.ai_assistant import chat_with_ai, generate_anime_tavsif

async def _push(event_type, text, color="c"):
    try:
        import sys, os
        sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
        from web_server import push_event
        await push_event(event_type, text, color)
    except Exception:
        pass
from utils.logger import get_logs_text

router = Router()


ANILIST_GRAPHQL_URL = "https://graphql.anilist.co"
ANILIST_POSTER_QUERY = """
query ($search: String) {
  Media(search: $search, type: ANIME, sort: SEARCH_MATCH) {
    title { english romaji native }
    coverImage { extraLarge large medium }
  }
}
"""


async def fetch_anilist_poster(search_title: str) -> dict:
    """AniList'dan anime posteri va topilgan nomini qaytaradi."""
    search_title = (search_title or "").strip()
    if not search_title:
        return {}

    try:
        async with aiohttp.ClientSession() as session:
            async with session.post(
                ANILIST_GRAPHQL_URL,
                json={"query": ANILIST_POSTER_QUERY, "variables": {"search": search_title}},
                headers={"Content-Type": "application/json", "Accept": "application/json"},
                timeout=aiohttp.ClientTimeout(total=12),
            ) as resp:
                data = await resp.json()
    except Exception:
        return {}

    media = data.get("data", {}).get("Media") or {}
    cover = media.get("coverImage") or {}
    title = media.get("title") or {}
    poster_url = cover.get("extraLarge") or cover.get("large") or cover.get("medium") or ""
    matched_title = title.get("english") or title.get("romaji") or title.get("native") or search_title
    if not poster_url:
        return {}
    return {"poster_url": poster_url, "matched_title": matched_title}


async def insert_anime_from_state(data: dict, rams: str) -> int:
    """Admin qo'shish flow'idagi state ma'lumotlari bilan anime yaratadi."""
    sana = datetime.datetime.now().strftime("%H:%M %d.%m.%Y")
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute("""
            INSERT INTO animelar (
                nom, rams, qismi, davlat, tili, yili, janri,
                qidiruv, aniType, fandub, sana, yosh_toifa, nom_en
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, 0, ?, ?, ?, ?, ?)
        """, (
            data['nom'], rams, data['qismi'], data['davlat'], data['tili'],
            data['yili'], data['janri'], data['status'], data['fandub'], sana,
            data.get('yosh_toifa', 'Barcha yoshlar'), data.get('nom_en', '')
        ))
        await db.commit()
        cursor = await db.execute("SELECT last_insert_rowid()")
        anime_id = (await cursor.fetchone())[0]
        await db.execute(
            "UPDATE animelar SET season_group_id=?, season_number=1 WHERE id=?",
            (anime_id, anime_id)
        )
        await db.commit()
    return anime_id


async def notify_watchlist_users(bot: Bot, anime_id: int, anime_name: str, ep_num: int) -> int:
    """Watchlistga saqlagan foydalanuvchilarga yangi qism haqida xabar yuboradi."""
    from config import BOT_USERNAME

    bot_username = (BOT_USERNAME or "").lstrip("@")
    if not bot_username:
        me = await bot.get_me()
        bot_username = me.username

    watch_url = f"https://t.me/{bot_username}?start={anime_id}_{ep_num}"
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text=f"▶️ {ep_num}-qismni ochish", url=watch_url)]
    ])

    async with aiosqlite.connect(DB_PATH) as db:
        async with db.execute(
            "SELECT COALESCE(season_group_id, id) FROM animelar WHERE id=?",
            (anime_id,)
        ) as c:
            row = await c.fetchone()
        group_id = row[0] if row else anime_id
        async with db.execute(
            """
            SELECT DISTINCT w.user_id
            FROM watchlist w
            JOIN animelar a ON a.id=w.anime_id
            WHERE COALESCE(a.season_group_id, a.id)=?
            """,
            (group_id,)
        ) as c:
            users = await c.fetchall()

    sent = 0
    for (user_id,) in users:
        try:
            await bot.send_message(
                user_id,
                f"🆕 <b>Yangi qism chiqdi!</b>\n\n"
                f"🎬 <b>{anime_name}</b>\n"
                f"📺 <b>{ep_num}-qism</b> endi mavjud.",
                reply_markup=kb,
                parse_mode="HTML"
            )
            sent += 1
        except Exception:
            continue
    return sent


# ─── Panel kirish ────────────────────────────────────────────────────────────

@router.message(Command("panel"))
async def cmd_panel(message: Message):
    if not await is_admin(message.from_user.id):
        return
    is_super = await is_super_admin(message.from_user.id)
    await message.answer("<b>🗄 Admin paneliga xush kelibsiz!</b>",
                         reply_markup=panel_kb(is_super), parse_mode="HTML")


@router.message(Command("ai_post"))
async def ai_post_draft(message: Message):
    """
    /ai_post <mavzu>
    Adminlar uchun AI orqali broadcast matn drafti.
    """
    if not await is_admin(message.from_user.id):
        return

    topic = message.text.partition(" ")[2].strip()
    if not topic:
        await message.answer(
            "❌ Foydalanish: <code>/ai_post mavzu</code>\n"
            "Masalan: <code>/ai_post yangi VIP aksiyasi</code>",
            parse_mode="HTML"
        )
        return

    await message.answer("⏳ AI broadcast draft tayyorlamoqda...")

    system_prompt = (
        "You are an Uzbek Telegram marketing copy assistant. "
        "Write short, clear, conversion-oriented broadcast text for a Telegram bot audience. "
        "Output plain text only, max 1200 chars."
    )
    user_prompt = (
        f"Mavzu: {topic}\n"
        "Talab: 1) Kuchli sarlavha, 2) qisqa foyda, 3) aniq CTA."
    )
    draft = await chat_with_ai(system_prompt, user_prompt, temperature=0.5, max_tokens=400)
    if not draft:
        await message.answer("❌ AI javob bermadi. OPENAI_API_KEY ni tekshiring.")
        return

    await message.answer(
        f"🤖 <b>AI Broadcast Draft</b>\n\n{html.escape(draft)}",
        parse_mode="HTML"
    )


# ─── VIP To'lovlarni Tasdiqqlash ──────────────────────────────────────────────

@router.message(Command("linkseason"))
async def link_season_command(message: Message):
    """Bir anime ID ni boshqa anime bilan fasl guruhi sifatida bog'lash."""
    if not await is_admin(message.from_user.id):
        return

    parts = message.text.split()
    if len(parts) != 4 or not all(p.isdigit() for p in parts[1:]):
        await message.answer(
            "<b>Foydalanish:</b>\n"
            "<code>/linkseason ASOSIY_ID FASL_ID FASL_RAQAMI</code>\n\n"
            "Masalan: <code>/linkseason 10 25 2</code>\n"
            "Bu 25-kodli animeni 10-kodli animening 2-fasli qilib bog'laydi.",
            parse_mode="HTML"
        )
        return

    main_id = int(parts[1])
    season_id = int(parts[2])
    season_number = int(parts[3])
    if season_number < 1:
        await message.answer("❌ Fasl raqami 1 yoki undan katta bo'lishi kerak.")
        return

    async with aiosqlite.connect(DB_PATH) as db:
        async with db.execute(
            "SELECT id, nom, COALESCE(season_group_id, id) FROM animelar WHERE id=?",
            (main_id,)
        ) as c:
            main = await c.fetchone()
        async with db.execute("SELECT id, nom FROM animelar WHERE id=?", (season_id,)) as c:
            season = await c.fetchone()

        if not main or not season:
            await message.answer("❌ Asosiy ID yoki fasl ID topilmadi.")
            return

        group_id = main[2] or main_id
        await db.execute(
            "UPDATE animelar SET season_group_id=?, season_number=1 WHERE id=? AND (season_number IS NULL OR season_number < 1)",
            (group_id, main_id)
        )
        await db.execute(
            "UPDATE animelar SET season_group_id=?, season_number=? WHERE id=?",
            (group_id, season_number, season_id)
        )
        await db.commit()

        async with db.execute(
            """
            SELECT id, nom, COALESCE(season_number, 1)
            FROM animelar
            WHERE COALESCE(season_group_id, id)=?
            ORDER BY COALESCE(season_number, 1), id
            """,
            (group_id,)
        ) as c:
            seasons = await c.fetchall()

    lines = "\n".join(f"• {num}-fasl: <b>{html.escape(name)}</b> <code>{aid}</code>" for aid, name, num in seasons)
    await message.answer(
        f"✅ Fasllar bog'landi.\n\n{lines}\n\n"
        "Endi foydalanuvchi anime kartasida barcha fasllarni bitta joyda ko'radi.",
        parse_mode="HTML"
    )


@router.message(Command("unlinkseason"))
async def unlink_season_command(message: Message):
    """Anime ID ni fasl guruhidan ajratish."""
    if not await is_admin(message.from_user.id):
        return
    parts = message.text.split()
    if len(parts) != 2 or not parts[1].isdigit():
        await message.answer("<b>Foydalanish:</b> <code>/unlinkseason ANIME_ID</code>", parse_mode="HTML")
        return

    anime_id = int(parts[1])
    async with aiosqlite.connect(DB_PATH) as db:
        async with db.execute("SELECT nom FROM animelar WHERE id=?", (anime_id,)) as c:
            row = await c.fetchone()
        if not row:
            await message.answer("❌ Anime topilmadi.")
            return
        await db.execute(
            "UPDATE animelar SET season_group_id=id, season_number=1 WHERE id=?",
            (anime_id,)
        )
        await db.commit()

    await message.answer(
        f"✅ <b>{html.escape(row[0])}</b> fasl guruhidan ajratildi.",
        parse_mode="HTML"
    )


@router.message(Command("approve"))
async def approve_vip_payment(message: Message, bot: Bot):
    """VIP to'lovni tasdiqqlash - /approve_USER_ID_DAYS"""
    if not await is_super_admin(message.from_user.id):
        await message.answer("❌ Faqat super admin!")
        return
    
    parts = message.text.split("_")
    if len(parts) < 3:
        await message.answer("❌ Format: /approve_USER_ID_DAYS\nMisol: /approve_123456789_30")
        return
    
    try:
        user_id = int(parts[1])
        days = int(parts[2])
    except ValueError:
        await message.answer("❌ Noto'g'ri format!")
        return
    
    expiry_date = (datetime.datetime.now() + datetime.timedelta(days=days)).strftime("%Y-%m-%d")
    
    async with aiosqlite.connect(DB_PATH) as db:
        async with db.execute("SELECT kun, date FROM vip_status WHERE user_id=?", (user_id,)) as c:
            existing = await c.fetchone()
        
        if existing:
            new_days = existing[0] + days
            await db.execute(
                "UPDATE vip_status SET kun=?, date=? WHERE user_id=?",
                (new_days, expiry_date, user_id)
            )
        else:
            await db.execute(
                "INSERT INTO vip_status (user_id, kun, date) VALUES (?, ?, ?)",
                (user_id, days, expiry_date)
            )
        
        await db.commit()
    
    # Log qilish
    log_admin_action(
        "vip_approved",
        message.from_user.id,
        message.from_user.username or f"ID: {message.from_user.id}",
        new_admin_id=user_id,
        vip_days=days
    )
    
    # User'ga xat
    await bot.send_message(
        user_id,
        f"✅ <b>VIP tasdiqlandi!</b>\n\n"
        f"📅 Muddati: <b>{days} kun</b>\n"
        f"⏰ Tugash: <b>{expiry_date}</b>",
        parse_mode="HTML"
    )
    
    await message.answer(
        f"✅ VIP tasdiqlandi! User {user_id} ga {days} kun VIP berildi.",
        parse_mode="HTML"
    )


@router.message(Command("reject"))
async def reject_vip_payment(message: Message, bot: Bot):
    """VIP to'lovni rad etish - /reject_USER_ID"""
    if not await is_super_admin(message.from_user.id):
        await message.answer("❌ Faqat super admin!")
        return
    
    parts = message.text.split("_")
    if len(parts) < 2:
        await message.answer("❌ Format: /reject_USER_ID\nMisol: /reject_123456789")
        return
    
    try:
        user_id = int(parts[1])
    except ValueError:
        await message.answer("❌ Noto'g'ri format!")
        return
    
    # Log qilish
    log_admin_action(
        "vip_rejected",
        message.from_user.id,
        message.from_user.username or f"ID: {message.from_user.id}",
        details=f"User: {user_id}"
    )
    
    # User'ga xat
    await bot.send_message(
        user_id,
        "❌ <b>VIP to'lovingiz rad etildi!</b>\n\n"
        "Agar savollar bo'lsa, admin bilan bog'laning.",
        parse_mode="HTML"
    )
    
    await message.answer(
        f"❌ VIP rad etildi! User {user_id} ga bildirishnoma yuborildi.",
        parse_mode="HTML"
    )


@router.message(F.text == "🗄 Boshqarish")
async def text_panel(message: Message):
    if not await is_admin(message.from_user.id):
        return
    is_super = await is_super_admin(message.from_user.id)
    await message.answer("<b>🗄 Admin paneliga xush kelibsiz!</b>",
                         reply_markup=panel_kb(is_super), parse_mode="HTML")


# ─── Orqaga ──────────────────────────────────────────────────────────────────

@router.message(F.text == "◀️ Orqaga")
async def go_back(message: Message, state: FSMContext):
    await state.clear()
    await message.answer(
        "🏠 Bosh menyu",
        reply_markup=menu_kb(await is_admin(message.from_user.id))
    )


# ─── Statistika ──────────────────────────────────────────────────────────────

@router.message(F.text == "📊 Statistika")
async def statistics_handler(message: Message):
    if not await is_admin(message.from_user.id):
        return

    async with aiosqlite.connect(DB_PATH) as db:
        async with db.execute("SELECT COUNT(*) FROM users") as c:
            total_users = (await c.fetchone())[0]
        async with db.execute("SELECT COUNT(*) FROM users WHERE ban='unban'") as c:
            active_users = (await c.fetchone())[0]
        async with db.execute("SELECT COUNT(*) FROM users WHERE ban='ban'") as c:
            banned_users = (await c.fetchone())[0]
        async with db.execute("SELECT COUNT(*) FROM animelar") as c:
            total_animes = (await c.fetchone())[0]
        async with db.execute("SELECT COUNT(*) FROM anime_datas") as c:
            total_episodes = (await c.fetchone())[0]
        async with db.execute("SELECT COUNT(*) FROM vip_status") as c:
            vip_users = (await c.fetchone())[0]

    text = (
        f"<b>📊 Bot statistikasi</b>\n\n"
        f"👥 Jami foydalanuvchilar: <b>{total_users}</b>\n"
        f"✅ Faol: <b>{active_users}</b>\n"
        f"🚫 Banned: <b>{banned_users}</b>\n"
        f"💎 VIP: <b>{vip_users}</b>\n\n"
        f"🎬 Jami animelar: <b>{total_animes}</b>\n"
        f"📺 Jami qismlar: <b>{total_episodes}</b>\n"
    )
    await message.answer(text, parse_mode="HTML")


# ─── Xabar yuborish (broadcast) ──────────────────────────────────────────────

@router.message(F.text == "✉ Xabar Yuborish")
async def broadcast_prompt(message: Message, state: FSMContext):
    if not await is_admin(message.from_user.id):
        return
    await message.answer(
        "<b>✉ Barcha foydalanuvchilarga yubormoqchi bo'lgan xabarni yuboring:</b>\n\n"
        "<i>Matn, rasm yoki video yuborishingiz mumkin.</i>",
        reply_markup=boshqarish_kb(), parse_mode="HTML"
    )
    await state.set_state(AdminStates.broadcast)


@router.message(AdminStates.broadcast)
async def process_broadcast(message: Message, state: FSMContext, bot: Bot):
    await state.clear()

    async with aiosqlite.connect(DB_PATH) as db:
        async with db.execute("SELECT user_id FROM users WHERE ban='unban'") as cursor:
            users = await cursor.fetchall()

    sent = 0
    failed = 0
    for (user_id,) in users:
        try:
            await message.copy_to(user_id)
            sent += 1
        except:
            failed += 1

    # Log qilish
    log_admin_action(
        "broadcast_complete",
        message.from_user.id,
        message.from_user.username or f"ID: {message.from_user.id}",
        success=sent,
        failed=failed
    )

    is_super = await is_super_admin(message.from_user.id)
    await message.answer(
        f"✅ Xabar yuborildi!\n\n"
        f"📤 Yuborildi: <b>{sent}</b>\n"
        f"❌ Xatolik: <b>{failed}</b>",
        reply_markup=panel_kb(is_super), parse_mode="HTML"
    )


# ─── Bot holati ───────────────────────────────────────────────────────────────

@router.message(F.text == "🤖 Bot holati")
async def bot_status_handler(message: Message, bot: Bot):
    if not await is_admin(message.from_user.id):
        return
    me = await bot.get_me()

    async with aiosqlite.connect(DB_PATH) as db:
        async with db.execute("SELECT value FROM bot_settings WHERE key='bot_maintenance'") as cursor:
            row = await cursor.fetchone()
            maintenance = row[0] == "1" if row else False

    status_icon = "🔴 O'chirilgan (Texnik ishlar)" if maintenance else "✅ Ishlamoqda"
    toggle_text = "✅ Botni Yoqish" if maintenance else "🔴 Botni O'chirish"
    toggle_cb = "botTurnOn" if maintenance else "botTurnOff"

    text = (
        f"<b>🤖 Bot holati: {status_icon}</b>\n\n"
        f"👤 Ismi: {me.full_name}\n"
        f"🔗 Username: @{me.username}\n"
        f"🆔 ID: <code>{me.id}</code>\n"
        f"🕐 Vaqt: {datetime.datetime.now().strftime('%H:%M:%S %d.%m.%Y')}"
    )
    btn = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text=toggle_text, callback_data=toggle_cb)]
    ])
    await message.answer(text, reply_markup=btn, parse_mode="HTML")


@router.callback_query(F.data.in_({"botTurnOff", "botTurnOn"}))
async def toggle_bot_maintenance(callback: CallbackQuery, bot: Bot):
    if not await is_admin(callback.from_user.id):
        return

    turning_off = callback.data == "botTurnOff"
    new_val = "1" if turning_off else "0"

    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute(
            "INSERT OR REPLACE INTO bot_settings (key, value) VALUES ('bot_maintenance', ?)",
            (new_val,)
        )
        await db.commit()

    me = await bot.get_me()
    status_icon = "🔴 O'chirilgan (Texnik ishlar)" if turning_off else "✅ Ishlamoqda"
    toggle_text = "✅ Botni Yoqish" if turning_off else "🔴 Botni O'chirish"
    toggle_cb = "botTurnOn" if turning_off else "botTurnOff"

    text = (
        f"<b>🤖 Bot holati: {status_icon}</b>\n\n"
        f"👤 Ismi: {me.full_name}\n"
        f"🔗 Username: @{me.username}\n"
        f"🆔 ID: <code>{me.id}</code>\n"
        f"🕐 Vaqt: {datetime.datetime.now().strftime('%H:%M:%S %d.%m.%Y')}"
    )
    btn = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text=toggle_text, callback_data=toggle_cb)]
    ])
    action = "🔴 O'chirildi! Foydalanuvchilar texnik ish xabarini ko'radi." if turning_off else "✅ Yoqildi! Foydalanuvchilar botdan foydalana oladi."
    
    try:
        await callback.message.edit_text(text, reply_markup=btn, parse_mode="HTML")
    except Exception as e:
        if "message is not modified" not in str(e):
            await callback.answer(f"Xato: {str(e)[:50]}", show_alert=True)
    
    await callback.answer(action, show_alert=True)



# ─── Kanallar boshqarish ─────────────────────────────────────────────────────

@router.message(F.text == "📢 Kanallar")
async def channels_handler(message: Message):
    if not await is_admin(message.from_user.id):
        return

    async with aiosqlite.connect(DB_PATH) as db:
        async with db.execute("SELECT * FROM channels") as cursor:
            channels = await cursor.fetchall()

    if not channels:
        text = "<b>📢 Hozircha kanal qo'shilmagan</b>"
    else:
        text = "<b>📢 Qo'shilgan kanallar:</b>\n\n"
        for ch in channels:
            ctype = ""
            if ch[2] == "public": ctype = "Majburiy ochiq"
            elif ch[2] == "request": ctype = "Zayavka yopiq"
            elif ch[2] == "social": ctype = "Ijtimoiy"
            elif ch[2] == "anime": ctype = "Anime"
            elif ch[2] == "ongoing": ctype = "🔸 Ongoing"
            text += f"[{ctype}] ID: <code>{ch[1]}</code> | 🔗 <a href='{ch[3]}'>Link</a>\n"

    buttons = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="➕ Majburiy kanal (ochiq)", callback_data="addChannelType=public")],
        [InlineKeyboardButton(text="➕ Zayavka kanal (yopiq)", callback_data="addChannelType=request")],
        [InlineKeyboardButton(text="➕ Ijtimoiy tarmoq", callback_data="addChannelType=social")],
        [InlineKeyboardButton(text="➕ Anime kanal", callback_data="addChannelType=anime")],
        [InlineKeyboardButton(text="➕ 🔸 Ongoing kanal", callback_data="addChannelType=ongoing")],
        [InlineKeyboardButton(text="🗑 Kanal o'chirish", callback_data="removeChannel")]
    ])
    await message.answer(text, reply_markup=buttons, parse_mode="HTML")


@router.callback_query(F.data.startswith("addChannelType="))
async def add_channel_prompt(callback: CallbackQuery, state: FSMContext):
    ctype = callback.data.split("=")[1]
    await state.update_data(channel_type=ctype)

    if ctype == 'social':
        # Social uchun ID siz, faqat nom va link
        await callback.message.answer(
            "<b>Ijtimoiy tarmoq nomini kiriting:</b>\n\n"
            "<i>Misol: Instagram, YouTube, TikTok</i>",
            parse_mode="HTML"
        )
        await state.set_state(AdminStates.add_channel_name)
    else:
        await callback.message.answer(
            "<b>Kanal ID sini yuboring</b>\n\n"
            "<i>Misol: -1001234567890</i>\n\n"
            "Kanal ID ni bilish uchun @username_to_id_bot dan foydalaning.",
            parse_mode="HTML"
        )
        await state.set_state(AdminStates.add_channel_id)
    await callback.answer()


@router.message(AdminStates.add_channel_name)
async def process_channel_name(message: Message, state: FSMContext):
    """Social tarmoq uchun nom (ID emas)"""
    await state.update_data(channel_id=message.text, channel_name=message.text)
    await message.answer(
        "<b>Ijtimoiy tarmoq linkini yuboring:</b>\n\n"
        "<i>Misol: https://instagram.com/kanal_nomi</i>",
        parse_mode="HTML"
    )
    await state.set_state(AdminStates.add_channel_link)


@router.message(AdminStates.add_channel_id)
async def process_channel_id(message: Message, state: FSMContext):
    await state.update_data(channel_id=message.text, channel_name="")
    await message.answer("<b>Kanal linkini yuboring:</b>\n\n<i>Misol: https://t.me/kanal_nomi</i>", parse_mode="HTML")
    await state.set_state(AdminStates.add_channel_link)


@router.message(AdminStates.add_channel_link)
async def process_channel_link(message: Message, state: FSMContext):
    data = await state.get_data()
    channel_id = data['channel_id']
    channel_type = data.get('channel_type', 'public')
    channel_name = data.get('channel_name', '')
    channel_link = message.text

    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute(
            "INSERT INTO channels (channelId, channelType, channelLink, channelName) VALUES (?, ?, ?, ?)",
            (channel_id, channel_type, channel_link, channel_name)
        )
        await db.commit()
    invalidate_channel_cache()
    await state.clear()
    display = channel_name if channel_name else channel_id
    await message.answer(
        f"✅ Kanal qo'shildi!\n\n📛 Nomi: <b>{display}</b> | Turi: <b>{channel_type}</b>",
        reply_markup=panel_kb(), parse_mode="HTML"
    )


@router.callback_query(F.data == "removeChannel")
async def remove_channel_prompt(callback: CallbackQuery):
    async with aiosqlite.connect(DB_PATH) as db:
        async with db.execute("SELECT * FROM channels") as cursor:
            channels = await cursor.fetchall()

    if not channels:
        await callback.answer("Kanallar yo'q!", show_alert=True)
        return

    buttons = [
        [InlineKeyboardButton(
            text=f"🗑 {ch[1]} ({ch[2]})", callback_data=f"delChannel={ch[0]}"
        )]
        for ch in channels
    ]
    await callback.message.answer(
        "<b>O'chirish uchun kanal tanlang:</b>",
        reply_markup=InlineKeyboardMarkup(inline_keyboard=buttons), parse_mode="HTML"
    )
    await callback.answer()


@router.callback_query(F.data.startswith("delChannel="))
async def delete_channel_callback(callback: CallbackQuery):
    channel_db_id = int(callback.data.split("=")[1])
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute("DELETE FROM channels WHERE id=?", (channel_db_id,))
        await db.commit()
    invalidate_channel_cache()
    await callback.message.edit_text("✅ Kanal o'chirildi!", parse_mode="HTML")
    await callback.answer()


# ─── Foydalanuvchini boshqarish ──────────────────────────────────────────────

@router.message(F.text == "🔎 Foydalanuvchini boshqarish")
async def manage_user_prompt(message: Message, state: FSMContext):
    if not await is_admin(message.from_user.id):
        return
    await message.answer(
        "<b>🔎 Foydalanuvchi ID sini yuboring:</b>",
        reply_markup=boshqarish_kb(), parse_mode="HTML"
    )
    await state.set_state(AdminStates.manage_user)


@router.message(AdminStates.manage_user)
async def process_manage_user(message: Message, state: FSMContext):
    await state.clear()
    if not message.text.isdigit():
        await message.answer("❌ Faqat raqam kiriting!")
        return

    user_id = int(message.text)
    async with aiosqlite.connect(DB_PATH) as db:
        async with db.execute("SELECT * FROM users WHERE user_id=?", (user_id,)) as cursor:
            user = await cursor.fetchone()

    if not user:
        await message.answer("❌ Foydalanuvchi topilmadi!")
        return

    status_text = "🚫 Ban" if user[6] == "ban" else "✅ Faol"
    ban_btn_text = "✅ Ban olib tashla" if user[6] == "ban" else "🚫 Ban qil"
    ban_cb = f"unbanUser={user_id}" if user[6] == "ban" else f"banUser={user_id}"

    text = (
        f"<b>👤 Foydalanuvchi ma'lumotlari</b>\n\n"
        f"🆔 ID: <code>{user_id}</code>\n"
        f"📊 Status: {user[3]}\n"
        f"🚦 Holat: {status_text}\n"
        f"💵 Balans: {user[2]}\n"
        f"👥 Taklif qilganlari: {user[5]}\n"
    )
    buttons = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text=ban_btn_text, callback_data=ban_cb)]
    ])
    await message.answer(text, reply_markup=buttons, parse_mode="HTML")


@router.callback_query(F.data.startswith("banUser="))
async def ban_user(callback: CallbackQuery):
    user_id = int(callback.data.split("=")[1])
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute("UPDATE users SET ban='ban' WHERE user_id=?", (user_id,))
        await db.commit()
    await callback.message.edit_text(f"🚫 Foydalanuvchi <code>{user_id}</code> banlandi!", parse_mode="HTML")
    await callback.answer()


@router.callback_query(F.data.startswith("unbanUser="))
async def unban_user(callback: CallbackQuery):
    user_id = int(callback.data.split("=")[1])
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute("UPDATE users SET ban='unban' WHERE user_id=?", (user_id,))
        await db.commit()
    await callback.message.edit_text(f"✅ Foydalanuvchi <code>{user_id}</code> dan ban olindi!", parse_mode="HTML")
    await callback.answer()


# ─── Anime qo'shish flow ─────────────────────────────────────────────────────

@router.message(F.text == "🎥 Animelar sozlash")
async def anime_settings(message: Message, state: FSMContext):
    if not await is_admin(message.from_user.id):
        return

    restricted = await is_content_restricted()

    toggle_text = "🔓 Kontent ochish" if restricted else "🔐 Kontent cheklash"
    toggle_cb = "setRestriction=0" if restricted else "setRestriction=1"

    buttons = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="➕ Anime qo'shish", callback_data="addAnime")],
        [InlineKeyboardButton(text="➕ Qism qo'shish", callback_data="addEpisode")],
        [InlineKeyboardButton(text="🗑 Anime o'chirish (ID orqali)", callback_data="deleteAnimeByCode")],
        [InlineKeyboardButton(text="✂️ Qism o'chirish", callback_data="deleteEpisode")],
        [InlineKeyboardButton(text="📋 Animelar ro'yxati (tahrirlash)", callback_data="manageAnimesList")],
        [InlineKeyboardButton(text=toggle_text, callback_data=toggle_cb)],
    ])
    await message.answer("<b>🎥 Animelar boshqaruvi:</b>", reply_markup=buttons, parse_mode="HTML")


@router.callback_query(F.data.startswith("setRestriction="))
async def toggle_content_restriction(callback: CallbackQuery):
    if not await is_admin(callback.from_user.id):
        return

    new_val = callback.data.split("=")[1]
    
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute(
            "INSERT OR REPLACE INTO bot_settings (key, value) VALUES ('content_restriction', ?)",
            (new_val,)
        )
        await db.commit()
    
    invalidate_restriction_cache()
    
    # Menuni yangilash
    restricted = new_val == "1"
    toggle_text = "🔓 Kontent ochish" if restricted else "🔐 Kontent cheklash"
    toggle_cb = "setRestriction=0" if restricted else "setRestriction=1"

    buttons = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="➕ Anime qo'shish", callback_data="addAnime")],
        [InlineKeyboardButton(text="➕ Qism qo'shish", callback_data="addEpisode")],
        [InlineKeyboardButton(text="🗑 Anime o'chirish (ID orqali)", callback_data="deleteAnimeByCode")],
        [InlineKeyboardButton(text="✂️ Qism o'chirish", callback_data="deleteEpisode")],
        [InlineKeyboardButton(text="📋 Animelar ro'yxati (tahrirlash)", callback_data="manageAnimesList")],
        [InlineKeyboardButton(text=toggle_text, callback_data=toggle_cb)],
    ])

    try:
        await callback.message.edit_reply_markup(reply_markup=buttons)
    except Exception:
        pass

    status = "yoqildi" if restricted else "o'chirildi"
    await callback.answer(f"✅ Kontentni cheklash {status}!", show_alert=True)


@router.callback_query(F.data == "addAnime")
async def start_add_anime(callback: CallbackQuery, state: FSMContext):
    await callback.message.answer("<b>Anime nomini kiriting:</b>", reply_markup=boshqarish_kb(), parse_mode="HTML")
    await state.set_state(AdminStates.add_anime_name)
    await callback.answer()


@router.message(AdminStates.add_anime_name)
async def process_anime_name(message: Message, state: FSMContext):
    await state.update_data(nom=message.text)
    await message.answer(
        "<b>Anime inglizcha nomini kiriting:</b>\n\n"
        "<i>AniList posterini avtomatik olish uchun. Agar bilmasangiz <code>/skip</code> yuboring.</i>",
        reply_markup=boshqarish_kb(), parse_mode="HTML"
    )
    await state.set_state(AdminStates.add_anime_english_name)
    return
    await message.answer("<b>🎥 Jami qismlar sonini kiriting:</b>", reply_markup=boshqarish_kb(), parse_mode="HTML")
    await state.set_state(AdminStates.add_anime_episodes)


@router.message(AdminStates.add_anime_english_name)
async def process_anime_english_name(message: Message, state: FSMContext):
    english_name = (message.text or "").strip()

    if english_name and english_name.lower() not in {"/skip", "skip", "-"}:
        wait_msg = await message.answer("AniList'dan poster qidirilmoqda...")
        poster = await fetch_anilist_poster(english_name)
        if poster:
            await state.update_data(
                nom_en=english_name,
                anilist_poster_url=poster["poster_url"],
                anilist_matched_title=poster.get("matched_title", english_name)
            )
            try:
                await wait_msg.delete()
            except Exception:
                pass
            await message.answer_photo(
                photo=poster["poster_url"],
                caption=(
                    "AniList posteri topildi!\n\n"
                    f"<b>Topilgan nom:</b> {html.escape(poster.get('matched_title', english_name))}\n"
                    "Shu poster anime kartasida va Telegramda ishlatiladi."
                ),
                parse_mode="HTML"
            )
        else:
            await state.update_data(nom_en=english_name)
            try:
                await wait_msg.edit_text(
                    "AniList'dan poster topilmadi. Oxirida rasmni qo'lda yuborasiz."
                )
            except Exception:
                await message.answer("AniList'dan poster topilmadi. Oxirida rasmni qo'lda yuborasiz.")

    await message.answer("<b>ðŸŽ¥ Jami qismlar sonini kiriting:</b>", reply_markup=boshqarish_kb(), parse_mode="HTML")
    await state.set_state(AdminStates.add_anime_episodes)


@router.message(AdminStates.add_anime_episodes)
async def process_anime_episodes(message: Message, state: FSMContext):
    await state.update_data(qismi=message.text)
    await message.answer("<b>🌍 Qaysi davlat ishlab chiqarganini kiriting:</b>", reply_markup=boshqarish_kb(), parse_mode="HTML")
    await state.set_state(AdminStates.add_anime_country)


@router.message(AdminStates.add_anime_country)
async def process_anime_country(message: Message, state: FSMContext):
    await state.update_data(davlat=message.text)
    await message.answer("<b>🇺🇿 Qaysi tilda ekanligini kiriting:</b>", reply_markup=boshqarish_kb(), parse_mode="HTML")
    await state.set_state(AdminStates.add_anime_language)


@router.message(AdminStates.add_anime_language)
async def process_anime_language(message: Message, state: FSMContext):
    await state.update_data(tili=message.text)
    await message.answer("<b>📆 Qaysi yilda ishlab chiqarilganini kiriting:</b>", reply_markup=boshqarish_kb(), parse_mode="HTML")
    await state.set_state(AdminStates.add_anime_year)


@router.message(AdminStates.add_anime_year)
async def process_anime_year(message: Message, state: FSMContext):
    await state.update_data(yili=message.text)
    await message.answer(
        "<b>🎞 Janrlarini kiriting:</b>\n\n<i>Na'muna: Drama, Fantastika</i>",
        reply_markup=boshqarish_kb(), parse_mode="HTML"
    )
    await state.set_state(AdminStates.add_anime_genre)


@router.message(AdminStates.add_anime_genre)
async def process_anime_genre(message: Message, state: FSMContext):
    await state.update_data(janri=message.text)
    await message.answer(
        "<b>🎙️ Fandub nomini kiriting:</b>\n\n<i>Na'muna: @AnimeLiveUz</i>",
        reply_markup=boshqarish_kb(), parse_mode="HTML"
    )
    await state.set_state(AdminStates.add_anime_fandub)


@router.message(AdminStates.add_anime_fandub)
async def process_anime_fandub(message: Message, state: FSMContext):
    await state.update_data(fandub=message.text)
    await message.answer(
        "<b>📊 Anime holatini kiriting:</b>\n\n<i>Na'muna: 🔸 OnGoing yoki ✅ Yakunlangan</i>",
        reply_markup=boshqarish_kb(), parse_mode="HTML"
    )
    await state.set_state(AdminStates.add_anime_status)


@router.message(AdminStates.add_anime_status)
async def process_anime_status(message: Message, state: FSMContext):
    await state.update_data(status=message.text)
    from keyboards import yosh_toifa_kb
    await message.answer(
        "<b>🔞 Yosh toifasini tanlang:</b>\n\n"
        "<i>Anime qaysi yoshdagi tomoshabinlar uchun mo'ljallangan?</i>",
        reply_markup=yosh_toifa_kb(), parse_mode="HTML"
    )
    await state.set_state(AdminStates.add_anime_age)


@router.callback_query(F.data.startswith("set_age="), AdminStates.add_anime_age)
async def process_anime_age(callback: CallbackQuery, state: FSMContext):
    yosh = callback.data.split("=")[1]
    await state.update_data(yosh_toifa=yosh)
    data = await state.get_data()
    poster_url = data.get("anilist_poster_url")

    if poster_url:
        anime_id = await insert_anime_from_state(data, poster_url)
        await callback.message.answer(
            f"Anime AniList posteri bilan qo'shildi!\n\n"
            f"<b>Anime kodi:</b> <code>{anime_id}</code>",
            reply_markup=panel_kb(), parse_mode="HTML"
        )
        await state.clear()
        await callback.answer()
        return

    await callback.message.answer(
        f"✅ Yosh toifasi: <b>{yosh}</b>\n\n<b>🏞 Rasmini yoki 60 soniyadan oshmagan video yuboring:</b>",
        reply_markup=boshqarish_kb(), parse_mode="HTML"
    )
    await state.set_state(AdminStates.add_anime_picture)
    await callback.answer()


@router.message(AdminStates.add_anime_picture, F.photo | F.video | F.document)
async def process_anime_picture(message: Message, state: FSMContext):
    data = await state.get_data()
    
    if message.photo:
        file_id = message.photo[-1].file_id
    elif message.video:
        file_id = message.video.file_id
    elif message.document:
        if message.document.mime_type and (message.document.mime_type.startswith("image/") or message.document.mime_type.startswith("video/")):
            file_id = message.document.file_id
        else:
            await message.answer("❌ Iltimos, faqat rasm yoki video yuboring (fayl ko'rinishida bo'lsa ham)!")
            return
    else:
        await message.answer("❌ Fayl topilmadi!")
        return
        
    anime_id = await insert_anime_from_state(data, file_id)

    await message.answer(
        f"✅ Anime qo'shildi!\n\n<b>Anime kodi:</b> <code>{anime_id}</code>",
        reply_markup=panel_kb(), parse_mode="HTML"
    )
    await state.clear()


# ─── Qism qo'shish flow ──────────────────────────────────────────────────────

@router.callback_query(F.data == "addEpisode")
async def start_add_episode(callback: CallbackQuery, state: FSMContext):
    await callback.message.answer(
        "<b>📺 Qism qo'shish</b>\n\nAnime kodini (ID) kiriting:",
        reply_markup=boshqarish_kb(), parse_mode="HTML"
    )
    await state.set_state(AdminStates.add_episode_code)
    await callback.answer()


# ─── ID orqali animeni to'liq o'chirish ──────────────────────────────────────

@router.callback_query(F.data == "deleteAnimeByCode")
async def delete_anime_by_code_prompt(callback: CallbackQuery, state: FSMContext):
    await callback.message.answer(
        "<b>🗑 ID orqali animeni o'chirish</b>\n\n"
        "Anime kodini (ID) kiriting:\n\n"
        "<i>⚠️ Diqqat: Anime va unga tegishli BARCHA qismlar o'chib ketadi!</i>",
        reply_markup=boshqarish_kb(), parse_mode="HTML"
    )
    await state.set_state(AdminStates.delete_anime_by_code)
    await callback.answer()


@router.message(AdminStates.delete_anime_by_code)
async def process_delete_anime_by_code(message: Message, state: FSMContext):
    if not message.text.isdigit():
        await message.answer("❌ Faqat raqam kiriting!")
        return

    anime_id = int(message.text)

    async with aiosqlite.connect(DB_PATH) as db:
        async with db.execute("SELECT nom, qismi FROM animelar WHERE id=?", (anime_id,)) as cursor:
            anime = await cursor.fetchone()
        async with db.execute("SELECT COUNT(*) FROM anime_datas WHERE id=?", (anime_id,)) as cursor:
            ep_count = (await cursor.fetchone())[0]

    if not anime:
        await message.answer(f"❌ <b>{anime_id}</b> kodli anime topilmadi!", parse_mode="HTML")
        await state.clear()
        return

    await state.update_data(del_anime_id=anime_id)

    confirm_kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(
            text=f"✅ Ha, o'chirilsin ({ep_count} qism bilan)",
            callback_data=f"confirmDelByCode={anime_id}"
        )],
        [InlineKeyboardButton(text="❌ Bekor qilish", callback_data="cancelDelByCode")]
    ])
    await message.answer(
        f"⚠️ <b>Tasdiqlang:</b>\n\n"
        f"🎬 Anime: <b>{anime[0]}</b>\n"
        f"🆔 Kod: <code>{anime_id}</code>\n"
        f"📺 Qismlar: <b>{ep_count} ta</b>\n\n"
        f"Bu anime va barcha qismlari <b>butunlay o'chib ketadi!</b>",
        reply_markup=confirm_kb, parse_mode="HTML"
    )
    await state.clear()


@router.callback_query(F.data.startswith("confirmDelByCode="))
async def confirm_delete_by_code(callback: CallbackQuery):
    anime_id = int(callback.data.split("=")[1])

    async with aiosqlite.connect(DB_PATH) as db:
        async with db.execute("SELECT nom FROM animelar WHERE id=?", (anime_id,)) as cursor:
            row = await cursor.fetchone()
        anime_nom = row[0] if row else str(anime_id)

        await db.execute("DELETE FROM animelar WHERE id=?", (anime_id,))
        await db.execute("DELETE FROM anime_datas WHERE id=?", (anime_id,))
        await db.commit()

    await callback.message.edit_text(
        f"✅ <b>{anime_nom}</b> va unga tegishli barcha qismlar o'chirildi!",
        parse_mode="HTML"
    )
    await callback.answer("✅ O'chirildi!", show_alert=True)


@router.callback_query(F.data == "cancelDelByCode")
async def cancel_delete_by_code(callback: CallbackQuery):
    await callback.message.edit_text("❌ O'chirish bekor qilindi.")
    await callback.answer()



# ─── Qism o'chirish flow ──────────────────────────────────────────────────────

@router.callback_query(F.data == "deleteEpisode")
async def delete_episode_prompt(callback: CallbackQuery, state: FSMContext):
    await callback.message.answer(
        "<b>✂️ Qism o'chirish</b>\n\n"
        "Anime kodini (ID) kiriting:\n"
        "<i>Anime kodini bilmasangiz, 📋 Animelar ro'yxatidan toping.</i>",
        reply_markup=boshqarish_kb(), parse_mode="HTML"
    )
    await state.set_state(AdminStates.delete_episode_anime_code)
    await callback.answer()


@router.message(AdminStates.delete_episode_anime_code)
async def process_delete_episode_anime_code(message: Message, state: FSMContext):
    if not message.text.isdigit():
        await message.answer("❌ Faqat raqam kiriting!")
        return

    anime_id = int(message.text)
    async with aiosqlite.connect(DB_PATH) as db:
        async with db.execute("SELECT nom FROM animelar WHERE id=?", (anime_id,)) as cursor:
            anime = await cursor.fetchone()
        if not anime:
            await message.answer(f"❌ <b>{anime_id}</b> kodli anime topilmadi!", parse_mode="HTML")
            await state.clear()
            return
        async with db.execute(
            "SELECT qism FROM anime_datas WHERE id=? ORDER BY qism ASC", (anime_id,)
        ) as cursor:
            episodes = await cursor.fetchall()

    if not episodes:
        await message.answer(f"❌ <b>{anime[0]}</b> animesida hech qanday qism yuklanmagan!", parse_mode="HTML")
        await state.clear()
        return

    await state.update_data(del_ep_anime_id=anime_id, del_ep_anime_nom=anime[0])

    buttons = []
    row = []
    for ep in episodes:
        row.append(InlineKeyboardButton(
            text=str(ep[0]), callback_data=f"doDelEp={anime_id}={ep[0]}"
        ))
        if len(row) == 5:
            buttons.append(row)
            row = []
    if row:
        buttons.append(row)
    buttons.append([InlineKeyboardButton(text="❌ Bekor qilish", callback_data="cancelDelEp")])

    await message.answer(
        f"<b>{anime[0]}</b> — o'chirmoqchi bo'lgan qismni tanlang:",
        reply_markup=InlineKeyboardMarkup(inline_keyboard=buttons),
        parse_mode="HTML"
    )
    await state.set_state(AdminStates.delete_episode_number)


@router.callback_query(AdminStates.delete_episode_number, F.data.startswith("doDelEp="))
async def execute_delete_episode(callback: CallbackQuery, state: FSMContext):
    parts = callback.data.split("=")
    anime_id = int(parts[1])
    ep_num = int(parts[2])
    data = await state.get_data()
    anime_nom = data.get("del_ep_anime_nom", str(anime_id))

    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute("DELETE FROM anime_datas WHERE id=? AND qism=?", (anime_id, ep_num))
        await db.commit()
        async with db.execute("SELECT COUNT(*) FROM anime_datas WHERE id=?", (anime_id,)) as c:
            remaining = (await c.fetchone())[0]

    await state.clear()
    await callback.message.edit_text(
        f"✅ <b>{anime_nom}</b> — {ep_num}-qism o'chirildi!\n"
        f"📺 Qolgan qismlar: <b>{remaining}</b> ta",
        parse_mode="HTML"
    )
    await callback.answer("✅ O'chirildi!", show_alert=True)


@router.callback_query(F.data == "cancelDelEp")
async def cancel_delete_episode(callback: CallbackQuery, state: FSMContext):
    await state.clear()
    await callback.message.edit_text("❌ Qism o'chirish bekor qilindi.")
    await callback.answer()


@router.message(AdminStates.add_episode_code)
async def process_episode_code(message: Message, state: FSMContext):
    if not message.text.isdigit():
        await message.answer("❌ Faqat raqam kiriting!")
        return

    anime_id = int(message.text)
    async with aiosqlite.connect(DB_PATH) as db:
        async with db.execute("SELECT nom, qismi FROM animelar WHERE id=?", (anime_id,)) as cursor:
            anime = await cursor.fetchone()

    if not anime:
        await message.answer("❌ Bunday ID li anime topilmadi!")
        return

    await state.update_data(anime_id=anime_id, anime_nom=anime[0])

    # Qaysi qism ekanligini so'rash
    async with aiosqlite.connect(DB_PATH) as db:
        async with db.execute(
            "SELECT MAX(qism) FROM anime_datas WHERE id=?", (anime_id,)
        ) as cursor:
            max_ep = await cursor.fetchone()
            next_ep = (max_ep[0] or 0) + 1

    await message.answer(
        f"✅ Anime: <b>{anime[0]}</b>\n\n"
        f"📺 Keyingi qism raqami: <b>{next_ep}</b>\n\n"
        f"Shu qismni yuborasizmi? Boshqa raqam kiritmoqchi bo'lsangiz raqamni yuboring:",
        parse_mode="HTML"
    )
    await state.update_data(ep_num=next_ep)
    await state.set_state(AdminStates.add_episode_file)

    # Agar admin raqamni o'zgartirmoqchi bo'lsa
@router.message(AdminStates.add_episode_file, F.text)
async def change_episode_number(message: Message, state: FSMContext):
    if not message.text.isdigit():
        await message.answer("❌ Faqat raqam kiriting!")
        return
        
    new_ep = int(message.text)
    await state.update_data(ep_num=new_ep)
    
    data = await state.get_data()
    await message.answer(
        f"✅ Qism raqami <b>{new_ep}</b> ga o'zgartirildi.\n\n"
        f"Endi <b>{data['anime_nom']}</b> uchun {new_ep}-qism videosini yuboring:",
        parse_mode="HTML"
    )


@router.message(AdminStates.add_episode_file, F.video | F.document)
async def process_episode_file(message: Message, state: FSMContext, bot: Bot):
    if message.document:
        if not (message.document.mime_type and message.document.mime_type.startswith("video/")):
            await message.answer("❌ Iltimos, faqat video fayl yuboring!")
            return
        file_id = message.document.file_id
    else:
        file_id = message.video.file_id

    data = await state.get_data()
    anime_id = data['anime_id']
    ep_num = data['ep_num']
    sana = datetime.datetime.now().strftime("%H:%M %d.%m.%Y")
    old_max_ep = 0

    async with aiosqlite.connect(DB_PATH) as db:
        async with db.execute(
            "SELECT COALESCE(MAX(qism), 0) FROM anime_datas WHERE id=?",
            (anime_id,)
        ) as cursor:
            max_row = await cursor.fetchone()
            old_max_ep = max_row[0] if max_row and max_row[0] else 0

        # Avval bu qism mavjudligini tekshir
        async with db.execute(
            "SELECT id FROM anime_datas WHERE id=? AND qism=?", (anime_id, ep_num)
        ) as cursor:
            existing = await cursor.fetchone()

        if existing:
            await db.execute(
                "UPDATE anime_datas SET file_id=?, sana=? WHERE id=? AND qism=?",
                (file_id, sana, anime_id, ep_num)
            )
        else:
            await db.execute(
                "INSERT INTO anime_datas (id, file_id, qism, sana) VALUES (?, ?, ?, ?)",
                (anime_id, file_id, ep_num, sana)
            )
        await db.commit()

    # Barcha ma'lumotlarni yig'ish
    async with aiosqlite.connect(DB_PATH) as db:
        async with db.execute("SELECT * FROM animelar WHERE id=?", (anime_id,)) as cursor:
            anime_info = await cursor.fetchone()
        # Hozir nechta qism yuklangan
        async with db.execute("SELECT COUNT(*) FROM anime_datas WHERE id=?", (anime_id,)) as cursor:
            uploaded_count = (await cursor.fetchone())[0]

    next_ep = ep_num + 1
    await state.update_data(ep_num=next_ep)

    await _push("new_episode", f"{data['anime_nom']} — {ep_num}-qism yuklandi", "cyan" if False else "c")

    # Agar bu haqiqatan yangi qism bo'lsa (oldingi maksimaldan katta) — obunachilarga push
    if ep_num > old_max_ep and old_max_ep > 0:
        sent_count = await notify_watchlist_users(bot, anime_id, data['anime_nom'], ep_num)
        if sent_count:
            await message.answer(f"📨 Watchlist foydalanuvchilariga bildirishnoma yuborildi: {sent_count} ta")

    await message.answer(
        f"✅ <b>{data['anime_nom']}</b> — {ep_num}-qism qo'shildi! ({uploaded_count}/{anime_info[3] if anime_info else '?'} qism yuklandi)\n\n"
        f"🎞 Endi <b>{next_ep}-qism</b> videosini yuboring:\n"
        f"<i>To'xtatish uchun qaytish tugmasini yoki /panel ni bosing.</i>",
        reply_markup=panel_kb(), parse_mode="HTML"
    )

    # Auto-post logikasi
    from config import MAIN_CHANNEL_ID, BOT_USERNAME, MAIN_CHANNEL_USERNAME
    if anime_info:
        nom = anime_info[1]
        janri = anime_info[7]
        rams = anime_info[2]
        total_qism = anime_info[3]
        status = anime_info[10]
        fandub = anime_info[11]
        kanal = anime_info[14] if len(anime_info) > 14 else ""
        yili = anime_info[6]
        tili = anime_info[5]
        davlat = anime_info[4]
        tavsif = anime_info[16] if len(anime_info) > 16 else ""
        fandub = fandub or "Ovoz berilmagan"
        kanal  = kanal  or ""
        tavsif = (tavsif or "").strip()

        if not tavsif:
            tavsif = await generate_anime_tavsif(
                nom=nom, janr=janri or "", holat=status or "", qism=str(total_qism or ""),
                yil=str(yili or ""), til=str(tili or ""), davlat=str(davlat or ""),
            )
            if not tavsif:
                tavsif = f"{nom} — {janri or 'turli'} janridagi anime. Syujetida qiziqarli voqealar rivoji mavjud."

            try:
                async with aiosqlite.connect(DB_PATH) as db_upd:
                    await db_upd.execute("UPDATE animelar SET tavsif=? WHERE id=?", (tavsif, anime_id))
                    await db_upd.commit()
            except Exception:
                pass

        try:
            total_qism_int = int(total_qism)
        except (ValueError, TypeError):
            total_qism_int = None

        # ── Ongoing: qism raqami dastlabki miqdordan oshgan bo'lsa ────────
        if total_qism_int and ep_num > total_qism_int:
            async with aiosqlite.connect(DB_PATH) as db_ch:
                async with db_ch.execute(
                    "SELECT channelId FROM channels WHERE channelType='ongoing' LIMIT 1"
                ) as cur_ch:
                    ongoing_ch = await cur_ch.fetchone()

            if ongoing_ch:
                ongoing_channel_id = ongoing_ch[0]
                AE = '<tg-emoji emoji-id="5373123172420581514">🔥</tg-emoji>'
                ongoing_text = (
                    f"{AE} <b>Anime nomi:</b> {nom}\n"
                    f"╭────────────────\n"
                    f"├‣  <b>Holati:</b> 🔸 OnGoing\n"
                    f"├‣  <b>Yangi qism:</b> {ep_num}-qism 🆕\n"
                    f"├‣  <b>Janrlari:</b> {janri}\n"
                    f"├‣  <b>Ovoz:</b> {fandub}\n"
                    f"├‣  <b>Tavsif:</b> {html.escape(tavsif)}\n"
                    f"╰────────────────\n"
                    f"{AE}  <b>Botimiz:</b> @{BOT_USERNAME}\n"
                    f"{AE}  <b>Anime ID:</b> {anime_id}"
                )
                watch_btn = InlineKeyboardMarkup(inline_keyboard=[
                    [InlineKeyboardButton(
                        text=f"▶️ {ep_num}-qismni ko'rish",
                        url=f"https://t.me/{BOT_USERNAME}?start={anime_id}_{ep_num}"
                    )]
                ])
                try:
                    try:
                        await bot.send_photo(chat_id=ongoing_channel_id, photo=rams, caption=ongoing_text, reply_markup=watch_btn, parse_mode="HTML")
                    except Exception:
                        await bot.send_video(chat_id=ongoing_channel_id, video=rams, caption=ongoing_text, reply_markup=watch_btn, parse_mode="HTML")
                    await message.answer(f"📢 Ongoing kanal: {ep_num}-qism uchun post yuborildi!")
                except Exception as e:
                    await message.answer(f"⚠️ Ongoing kanalga post yuborilmadi: {e}")
            else:
                await message.answer("⚠️ Ongoing kanal topilmadi! 📢 Kanallar bo'limidan ongoing kanal qo'shing.")

        # ── Barcha qismlar to'liq yuklanganda asosiy kanalga post ──────────
        if MAIN_CHANNEL_ID and total_qism_int and uploaded_count >= total_qism_int:
            AE2 = '<tg-emoji emoji-id="5373123172420581514">🔥</tg-emoji>'
            kanal_line = f"├‣  <b>Kanal:</b> {kanal}\n" if kanal else f"├‣  <b>Kanal:</b> @{MAIN_CHANNEL_USERNAME}\n"
            post_text = (
                f"{AE2} <b>Anime nomi:</b> {nom}\n"
                f"╭────────────────\n"
                f"├‣  <b>Holati:</b> {status}\n"
                f"├‣  <b>Qisimi:</b> {total_qism_int}-qisim\n"
                f"├‣  <b>Sifat:</b> 720p - 1080p\n"
                f"├‣  <b>Janrlari:</b> {janri}\n"
                f"{kanal_line}"
                f"├‣  <b>Ovoz:</b> {fandub}\n"
                f"├‣  <b>Tavsif:</b> {html.escape(tavsif)}\n"
                f"╰────────────────\n"
                f"{AE2}  <b>Botimiz:</b> @{BOT_USERNAME}\n"
                f"{AE2}  <b>Anime ID:</b> {anime_id}\n"
                f"{AE2}  <b>Reyting:</b> 5 / 5\n"
                f"{AE2}  <b>Link:</b> https://t.me/{BOT_USERNAME}?start={anime_id}"
            )

            btn = InlineKeyboardMarkup(inline_keyboard=[
                [InlineKeyboardButton(text="✨ Tomosha Qilish ✨", url=f"https://t.me/{BOT_USERNAME}?start={anime_id}")]
            ])

            try:
                try:
                    await bot.send_photo(chat_id=MAIN_CHANNEL_ID, photo=rams, caption=post_text, reply_markup=btn, parse_mode="HTML")
                except Exception:
                    await bot.send_video(chat_id=MAIN_CHANNEL_ID, video=rams, caption=post_text, reply_markup=btn, parse_mode="HTML")
                await message.answer(f"📢 Barcha {total_qism_int} qism yuklandi — kanal post qilindi!")
                await state.clear()
            except Exception as e:
                await message.answer(f"⚠️ Auto-post kanalga yuborilmadi: {e}\n(Bot u kanalda adminligini tekshiring)")


# ─── Matnlar boshqarish ──────────────────────────────────────────────────────

@router.message(F.text == "📃 Matnlar")
async def texts_handler(message: Message):
    if not await is_admin(message.from_user.id): return

    buttons = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="📚 Qo'llanma matni", callback_data="edit_text=guide")],
        [InlineKeyboardButton(text="💵 Reklama matni", callback_data="edit_text=ads")],
        [InlineKeyboardButton(text="🖼 Qidiruv rasmi", callback_data="edit_search_photo")]
    ])
    await message.answer("<b>O'zgartirmoqchi bo'lgan bo'lim matnini tanlang:</b>", reply_markup=buttons, parse_mode="HTML")


# ─── Qidiruv rasmi yuklash ───────────────────────────────────────────────────

@router.callback_query(F.data == "edit_search_photo")
async def edit_search_photo_prompt(callback: CallbackQuery, state: FSMContext):
    if not await is_admin(callback.from_user.id): return
    await callback.message.answer(
        "<b>🖼 Qidiruv uchun yangi rasmni yuboring:</b>\n"
        "<i>Bu rasm foydalanuvchi qidiruv bosqanda chiqadi.</i>",
        parse_mode="HTML"
    )
    await state.set_state(AdminStates.edit_search_photo)
    await callback.answer()


@router.message(AdminStates.edit_search_photo, F.photo)
async def process_search_photo(message: Message, state: FSMContext):
    if not await is_admin(message.from_user.id): return
    photo_id = message.photo[-1].file_id
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute(
            "INSERT OR REPLACE INTO bot_settings (key, value) VALUES ('search_photo_id', ?)",
            (photo_id,)
        )
        await db.commit()
    await state.clear()
    await message.answer_photo(
        photo=photo_id,
        caption="✅ Qidiruv rasmi saqlandi! Endi foydalanuvchilar qidiruv bosqanda shu rasm chiqadi.",
        reply_markup=panel_kb(),
        parse_mode="HTML"
    )


@router.callback_query(F.data.startswith("edit_text="))
async def edit_text_prompt(callback: CallbackQuery, state: FSMContext):
    key = callback.data.split("=")[1]
    await state.update_data(edit_key=key)
    await callback.message.answer(f"<b>Yangi matnni yuboring ({key}):</b>", parse_mode="HTML")
    await state.set_state(AdminStates.edit_text)
    await callback.answer()


@router.message(AdminStates.edit_text)
async def process_edit_text(message: Message, state: FSMContext):
    data = await state.get_data()
    key = data['edit_key']
    new_text = message.text
    
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute("INSERT OR REPLACE INTO bot_texts (key, value) VALUES (?, ?)", (key, new_text))
        await db.commit()
    
    await state.clear()
    await message.answer("✅ Matn yangilandi!", reply_markup=panel_kb(), parse_mode="HTML")


# ─── 💸 To'lovlarni Tasdiqlash ─────────────────────────────────────────────────

@router.message(F.text == "💸 To'lovlarni Tasdiqlash")
async def payment_verification_menu(message: Message):
    """To'lovlarni tasdiqlash menusi"""
    if not await is_admin(message.from_user.id):
        return
    
    admin_id = message.from_user.id
    
    async with aiosqlite.connect(DB_PATH) as db:
        # Kutayotgan to'lovlarni oʻqish
        async with db.execute("""
            SELECT id, user_id, amount, purpose, created_at 
            FROM payments 
            WHERE status='pending'
            ORDER BY created_at DESC
            LIMIT 10
        """) as cursor:
            pending_payments = await cursor.fetchall()
    
    if not pending_payments:
        await message.answer(
            "✅ <b>Kutayotgan to'lovlar yo'q!</b>\n\n"
            "Barcha to'lovlar tasdiqlangan.",
            parse_mode="HTML",
            reply_markup=panel_kb(await is_super_admin(admin_id))
        )
        return
    
    text = f"<b>💸 Kutayotgan To'lovlar ({len(pending_payments)})</b>\n\n"
    
    for payment in pending_payments:
        pay_id, user_id, amount, purpose, created_at = payment
        
        # Maqsad O'zbekchada
        purpose_uz = {
            "vip_subscription": "💎 VIP",
            "balance": "💰 Balans",
            "other": "Boshqa"
        }.get(purpose, purpose)
        
        text += (
            f"<b>ID:</b> <code>{pay_id}</code>\n"
            f"👤 <b>User:</b> <code>{user_id}</code>\n"
            f"💵 <b>Summa:</b> <b>{amount}</b> so'm\n"
            f"📌 <b>Maqsad:</b> {purpose_uz}\n"
            f"⏰ <b>Vaqt:</b> {created_at}\n"
            f"━━━━━━━━\n\n"
        )
    
    # Tugmalar
    buttons = []
    for payment in pending_payments[:5]:
        pay_id = payment[0]
        buttons.append([
            InlineKeyboardButton(text=f"✅ #{pay_id}", callback_data=f"pay_approve={pay_id}"),
            InlineKeyboardButton(text=f"❌ #{pay_id}", callback_data=f"pay_reject={pay_id}")
        ])
    
    await message.answer(
        text,
        reply_markup=InlineKeyboardMarkup(inline_keyboard=buttons),
        parse_mode="HTML"
    )


@router.callback_query(F.data.startswith("pay_approve="))
async def approve_payment(callback: CallbackQuery, bot: Bot, state: FSMContext):
    """To'lovni tasdiqqlash"""
    if not await is_admin(callback.from_user.id):
        await callback.answer("❌ Ruhsat yo'q!", show_alert=True)
        return
    
    try:
        payment_id = int(callback.data.split("=")[1])
    except:
        await callback.answer("❌ Xato!", show_alert=True)
        return
    
    async with aiosqlite.connect(DB_PATH) as db:
        # To'lov ma'lumotlarini o'qish
        async with db.execute("""
            SELECT user_id, amount, purpose 
            FROM payments 
            WHERE id=? AND status='pending'
        """, (payment_id,)) as cursor:
            payment = await cursor.fetchone()
        
        if not payment:
            await callback.answer("❌ To'lov topilmadi!", show_alert=True)
            return
        
        user_id, amount, purpose = payment
        
        # Agar VIP boʻlsa, kunlarni savolash
        if purpose == "vip_subscription":
            await state.update_data(payment_id=payment_id, user_id=user_id, amount=amount)
            await callback.message.answer(
                "💎 <b>VIP kun sonini kiriting:</b>\n"
                "Misol: 30, 60 yoki 90",
                parse_mode="HTML"
            )
            await state.set_state(AdminStates.vip_approve_days)
            await callback.answer()
            return
        
        # Balans to'lovi boʻlsa tesdiq qil
        await db.execute(
            "UPDATE payments SET status='approved' WHERE id=?",
            (payment_id,)
        )
        
        # Balansga qoʻshish
        if purpose == "balance":
            await db.execute(
                "UPDATE users SET pul=pul+? WHERE user_id=?",
                (amount, user_id)
            )
        
        await db.commit()
    
    # Log qilish
    log_admin_action(
        "payment_approved",
        callback.from_user.id,
        callback.from_user.username or f"ID: {callback.from_user.id}",
        details=f"Payment ID: {payment_id}, User: {user_id}, Summa: {amount} so'm"
    )
    
    # User'ga xat
    try:
        await bot.send_message(
            user_id,
            f"✅ <b>To'lovingiz tasdiqlandi!</b>\n\n"
            f"💵 <b>To'langan:</b> {amount} so'm\n"
            f"📌 <b>Balansingiz yangilandi</b>",
            parse_mode="HTML"
        )
    except:
        pass
    
    await callback.message.edit_text(
        f"✅ To'lov #{payment_id} tasdiqlandi!",
        parse_mode="HTML"
    )
    await callback.answer("✅ Tasdiqlandi!")


@router.message(AdminStates.vip_approve_days)
async def approve_vip_days(message: Message, state: FSMContext, bot: Bot):
    """VIP kunlarini qabul qilish"""
    if not message.text.isdigit():
        await message.answer("❌ Faqat raqam yuboring! (30, 60, 90 yoki boshqa)")
        return
    
    days = int(message.text)
    data = await state.get_data()
    payment_id = data.get("payment_id")
    user_id = data.get("user_id")
    amount = data.get("amount")
    
    # VIP qoʻshish
    expiry_date = (datetime.datetime.now() + datetime.timedelta(days=days)).strftime("%Y-%m-%d")
    
    async with aiosqlite.connect(DB_PATH) as db:
        # To'lovni tasdiqlash
        await db.execute(
            "UPDATE payments SET status='approved' WHERE id=?",
            (payment_id,)
        )
        
        # VIP qoʻshish yoki uzaytirish
        async with db.execute("SELECT kun, date FROM vip_status WHERE user_id=?", (user_id,)) as c:
            existing = await c.fetchone()
        
        if existing:
            new_days = existing[0] + days
            await db.execute(
                "UPDATE vip_status SET kun=?, date=? WHERE user_id=?",
                (new_days, expiry_date, user_id)
            )
        else:
            await db.execute(
                "INSERT INTO vip_status (user_id, kun, date) VALUES (?, ?, ?)",
                (user_id, days, expiry_date)
            )
        
        await db.commit()
    
    # Log qilish
    log_admin_action(
        "vip_approved",
        message.from_user.id,
        message.from_user.username or f"ID: {message.from_user.id}",
        details=f"User: {user_id}, Muddati: {days} kun, Payment ID: {payment_id}"
    )
    
    # User'ga xat
    try:
        await bot.send_message(
            user_id,
            f"✅ <b>VIP tasdiqlandi!</b>\n\n"
            f"💎 <b>Muddati:</b> {days} kun\n"
            f"📅 <b>Tugash:</b> {expiry_date}\n"
            f"💵 <b>To'langan:</b> {amount} so'm",
            parse_mode="HTML"
        )
    except:
        pass
    
    is_super = await is_super_admin(message.from_user.id)
    await message.answer(
        f"✅ <b>VIP tasdiqlandi!</b>\n\n"
        f"👤 User: <code>{user_id}</code>\n"
        f"💎 Muddati: <b>{days} kun</b>\n"
        f"📅 Tugash: <b>{expiry_date}</b>",
        reply_markup=panel_kb(is_super),
        parse_mode="HTML"
    )
    
    await state.clear()


@router.callback_query(F.data.startswith("pay_reject="))
async def reject_payment(callback: CallbackQuery, bot: Bot):
    """To'lovni rad etish"""
    if not await is_admin(callback.from_user.id):
        await callback.answer("❌ Ruhsat yo'q!", show_alert=True)
        return
    
    try:
        payment_id = int(callback.data.split("=")[1])
    except:
        await callback.answer("❌ Xato!", show_alert=True)
        return
    
    async with aiosqlite.connect(DB_PATH) as db:
        # To'lov ma'lumotlarini o'qish
        async with db.execute("""
            SELECT user_id, amount 
            FROM payments 
            WHERE id=? AND status='pending'
        """, (payment_id,)) as cursor:
            payment = await cursor.fetchone()
        
        if not payment:
            await callback.answer("❌ To'lov topilmadi!", show_alert=True)
            return
        
        user_id, amount = payment
        
        # To'lovni rad etish
        await db.execute(
            "UPDATE payments SET status='rejected' WHERE id=?",
            (payment_id,)
        )
        
        await db.commit()
    
    # Log qilish
    log_admin_action(
        "payment_rejected",
        callback.from_user.id,
        callback.from_user.username or f"ID: {callback.from_user.id}",
        details=f"Payment ID: {payment_id}, User: {user_id}"
    )
    
    # User'ga xat
    try:
        await bot.send_message(
            user_id,
            f"❌ <b>To'lovingiz rad etildi!</b>\n\n"
            f"💵 <b>Summa:</b> {amount} so'm\n"
            f"📌 <b>Sababni bilish uchun admin bilan bog'laning</b>",
            parse_mode="HTML"
        )
    except:
        pass
    
    await callback.message.edit_text(
        f"❌ To'lov #{payment_id} rad etildi!",
        parse_mode="HTML"
    )
    await callback.answer("❌ Rad etildi!")


@router.message(F.text == "💳 Hamyonlar")
async def wallet_handler(message: Message, state: FSMContext):
    if not await is_admin(message.from_user.id): return
    
    async with aiosqlite.connect(DB_PATH) as db:
        async with db.execute("SELECT value FROM bot_texts WHERE key='wallet'") as cursor:
            row = await cursor.fetchone()
            current_wallet = row[0] if row else "Hali o'rnatilmagan"
            
    await message.answer(f"<b>Hozirgi hamyon:</b>\n\n<code>{current_wallet}</code>\n\nYangi hamyon ma'lumotlarini yuboring:", parse_mode="HTML")
    await state.set_state(AdminStates.edit_wallet)


@router.message(AdminStates.edit_wallet)
async def process_edit_wallet(message: Message, state: FSMContext):
    new_wallet = message.text
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute("INSERT OR REPLACE INTO bot_texts (key, value) VALUES (?, ?)", ('wallet', new_wallet))
        await db.commit()
    
    await state.clear()
    await message.answer("✅ Hamyon yangilandi!", reply_markup=panel_kb(), parse_mode="HTML")


# ─── Animelar sozlash (Edit/Delete) ──────────────────────────────────────────

@router.message(F.text == "🎥 Animelar sozlash (eski)")
async def manage_animes_handler(message: Message):
    if not await is_admin(message.from_user.id): return
    await _show_animes_list(message)


@router.callback_query(F.data == "manageAnimesList")
async def manage_animes_list_callback(callback: CallbackQuery):
    await _show_animes_list(callback.message)
    await callback.answer()


async def _show_animes_list(message: Message, page: int = 0, edit: bool = False):
    PER_PAGE = 10
    offset = page * PER_PAGE

    async with aiosqlite.connect(DB_PATH) as db:
        async with db.execute("SELECT COUNT(*) FROM animelar") as c:
            total = (await c.fetchone())[0]
        async with db.execute(
            "SELECT id, nom, yosh_toifa FROM animelar ORDER BY id DESC LIMIT ? OFFSET ?",
            (PER_PAGE, offset)
        ) as cursor:
            animes = await cursor.fetchall()

    if not animes:
        await message.answer("Bazada hech qanday anime yo'q!")
        return

    total_pages = max(1, (total + PER_PAGE - 1) // PER_PAGE)
    YOSH_EMOJI = {"0+": "👶", "7+": "🧒", "13+": "👦", "16+": "🧑", "18+": "🔞", "Barcha yoshlar": "📺", "Belgilanmagan": "📺"}
    
    text = f"<b>🎬 Animelar ro'yxati ({page+1}/{total_pages} sahifa, jami {total} ta):</b>"
    buttons = []
    for anime in animes:
        yosh = anime[2] if anime[2] else "—"
        emoji = YOSH_EMOJI.get(yosh, "📺")
        buttons.append([InlineKeyboardButton(
            text=f"{emoji} {anime[1]} [{yosh}]",
            callback_data=f"manageAnime={anime[0]}"
        )])

    nav = []
    if page > 0:
        nav.append(InlineKeyboardButton(text="◀️ Oldingi", callback_data=f"animeListPage={page-1}"))
    if page < total_pages - 1:
        nav.append(InlineKeyboardButton(text="Keyingi ▶️", callback_data=f"animeListPage={page+1}"))
    if nav:
        buttons.append(nav)

    markup = InlineKeyboardMarkup(inline_keyboard=buttons)
    if edit:
        try:
            await message.edit_text(text, reply_markup=markup, parse_mode="HTML")
            return
        except Exception:
            pass
    await message.answer(text, reply_markup=markup, parse_mode="HTML")


@router.callback_query(F.data.startswith("manageAnime="))
async def manage_anime_callback(callback: CallbackQuery):
    anime_id = int(callback.data.split("=")[1])
    
    async with aiosqlite.connect(DB_PATH) as db:
        async with db.execute("SELECT * FROM animelar WHERE id=?", (anime_id,)) as cursor:
            anime = await cursor.fetchone()

    if not anime:
        await callback.answer("Anime topilmadi!", show_alert=True)
        return

    yosh_toifa = anime[15] if len(anime) > 15 and anime[15] else "Belgilanmagan"
    text = (
        f"<b>🎬 Anime: {anime[1]}</b>\n\n"
        f"<b>Holati:</b> {anime[10]}\n"
        f"<b>Qismlar soni:</b> {anime[3]}\n"
        f"<b>Janri:</b> {anime[7]}\n"
        f"<b>Yili:</b> {anime[6]}\n"
        f"<b>Yosh toifasi:</b> {yosh_toifa}\n\n"
        "Nima qilmoqchisiz?"
    )
    
    buttons = [
        [InlineKeyboardButton(text="📝 Ma'lumotlarni tahrirlash", callback_data=f"editAnimeOpts={anime_id}")],
        [InlineKeyboardButton(text="🗑 Animeni o'chirish", callback_data=f"prepDelAnime={anime_id}")],
        [InlineKeyboardButton(text="⬅️ Ortga", callback_data="refreshAnimeList")]
    ]
    await callback.message.edit_text(text, reply_markup=InlineKeyboardMarkup(inline_keyboard=buttons), parse_mode="HTML")
    await callback.answer()


@router.callback_query(F.data == "refreshAnimeList")
async def refresh_anime_list_callback(callback: CallbackQuery):
    try:
        await callback.message.delete()
    except Exception:
        pass
    await _show_animes_list(callback.message)
    await callback.answer()


@router.callback_query(F.data.startswith("editAnimeOpts="))
async def edit_anime_options(callback: CallbackQuery):
    anime_id = int(callback.data.split("=")[1])
    
    buttons = [
        [InlineKeyboardButton(text="Nomini o'zgartirish", callback_data=f"editAField={anime_id}=nom")],
        [InlineKeyboardButton(text="Qismlar sonini oshirish", callback_data=f"editAField={anime_id}=qismi")],
        [InlineKeyboardButton(text="Holati (OnGoing/Yakunlangan)", callback_data=f"editAField={anime_id}=aniType")],
        [InlineKeyboardButton(text="Janrini o'zgartirish", callback_data=f"editAField={anime_id}=janri")],
        [InlineKeyboardButton(text="Rasm/Video (Poster)", callback_data=f"editAField={anime_id}=rams")],
        [InlineKeyboardButton(text="Filler qismlar", callback_data=f"editAField={anime_id}=filler_info")],
        [InlineKeyboardButton(text="Filler rasmi", callback_data=f"editAField={anime_id}=filler_image")],
        [InlineKeyboardButton(text="🔞 Yosh toifasi", callback_data=f"editAge={anime_id}")],
        [InlineKeyboardButton(text="⬅️ Ortga", callback_data=f"manageAnime={anime_id}")]
    ]
    await callback.message.edit_text("<b>Tahrirlash uchun maydonni tanlang:</b>", 
                                     reply_markup=InlineKeyboardMarkup(inline_keyboard=buttons), parse_mode="HTML")
    await callback.answer()


@router.callback_query(F.data.startswith("editAge="))
async def edit_anime_age_callback(callback: CallbackQuery, state: FSMContext):
    anime_id = int(callback.data.split("=")[1])
    await state.update_data(edit_anime_id=anime_id, edit_field="yosh_toifa")
    from keyboards import yosh_toifa_kb
    await callback.message.answer(
        "<b>🔞 Yangi yosh toifasini tanlang:</b>",
        reply_markup=yosh_toifa_kb(), parse_mode="HTML"
    )
    await state.set_state(EditAnimeStates.edit_field)
    await callback.answer()


@router.callback_query(F.data.startswith("set_age="), EditAnimeStates.edit_field)
async def edit_anime_age_select(callback: CallbackQuery, state: FSMContext):
    data = await state.get_data()
    if data.get("edit_field") != "yosh_toifa":
        return
    anime_id = data["edit_anime_id"]
    yosh = callback.data.split("=")[1]
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute("UPDATE animelar SET yosh_toifa=? WHERE id=?", (yosh, anime_id))
        await db.commit()
    await state.clear()
    await callback.message.answer(f"✅ Yosh toifasi <b>{yosh}</b> ga o'zgartirildi!", reply_markup=panel_kb(), parse_mode="HTML")
    await callback.answer()


@router.callback_query(F.data.startswith("animeListPage="))
async def anime_list_page_callback(callback: CallbackQuery):
    page = int(callback.data.split("=")[1])
    await _show_animes_list(callback.message, page, edit=True)
    await callback.answer()


@router.callback_query(F.data.startswith("editAField="))
async def edit_anime_field_prompt(callback: CallbackQuery, state: FSMContext):
    parts = callback.data.split("=")
    anime_id = int(parts[1])
    field = parts[2]

    allowed_fields = {"nom", "qismi", "aniType", "janri", "rams", "filler_info", "filler_image"}
    if field not in allowed_fields:
        await callback.answer("❌ Noto'g'ri maydon tanlandi.", show_alert=True)
        return
    
    await state.update_data(edit_anime_id=anime_id, edit_field=field)
    
    prompt = f"<b>Yangi qiymatni yuboring ({field}):</b>"
    if field == "nom":
        prompt = "<b>Yangi anime nomini yuboring:</b>"
    elif field == "qismi":
        async with aiosqlite.connect(DB_PATH) as db:
            async with db.execute("SELECT qismi FROM animelar WHERE id=?", (anime_id,)) as c:
                row = await c.fetchone()
        current_qismi = int(row[0]) if row and str(row[0]).isdigit() else 0
        await state.update_data(current_qismi=current_qismi)
        prompt = (
            f"<b>Hozirgi jami qism soni:</b> <code>{current_qismi}</code>\n\n"
            "<b>Nechta qismgacha oshiray?</b>\n"
            "<i>Faqat raqam yuboring (masalan: 24).</i>"
        )
    elif field == "aniType":
        prompt = "<b>Yangi holatni yuboring:</b>\n<i>Masalan: 🔸 OnGoing yoki ✅ Yakunlangan</i>"
    elif field == "janri":
        prompt = "<b>Yangi janr(lar)ni yuboring:</b>\n<i>Masalan: Action, Fantasy, Comedy</i>"
    elif field == "rams":
        prompt = "<b>Yangi rasm yoki 60 soniyali video yuboring:</b>"
    elif field == "filler_info":
        prompt = (
            "<b>Filler qismlar oraliqlarini yuboring:</b>\n\n"
            "<i>Masalan: <code>136-215</code> yoki <code>26, 97, 101-106</code>.</i>\n"
            "<i>Tozalash uchun <code>-</code> yuboring.</i>"
        )
    elif field == "filler_image":
        prompt = (
            "<b>Filler uchun rasm yuboring:</b>\n\n"
            "<i>Rasm yuboring yoki Telegram file_id/URL yuboring. Tozalash uchun <code>-</code>.</i>"
        )
        
    await callback.message.answer(prompt, parse_mode="HTML")
    await state.set_state(EditAnimeStates.edit_field)
    await callback.answer()


@router.message(EditAnimeStates.edit_field)
async def process_edit_anime_field(message: Message, state: FSMContext):
    data = await state.get_data()
    anime_id = data['edit_anime_id']
    field = data['edit_field']

    allowed_fields = {"nom", "qismi", "aniType", "janri", "rams", "yosh_toifa", "filler_info", "filler_image"}
    if field not in allowed_fields:
        await state.clear()
        await message.answer("❌ Maydon noto'g'ri, qaytadan urinib ko'ring.", reply_markup=panel_kb())
        return

    new_value = None
    if field == "yosh_toifa":
        # yosh_toifa faqat set_age= callback orqali o'zgartirilishi kerak
        await message.answer("❌ Yosh toifasini o'zgartirish uchun inline tugmadan foydalaning.")
        return
    elif field == "qismi":
        value = (message.text or "").strip()
        if not value.isdigit():
            await message.answer("❌ Qismlar soni uchun faqat raqam kiriting!")
            return
        new_qismi = int(value)
        current_qismi = int(data.get("current_qismi", 0) or 0)

        if new_qismi <= 0:
            await message.answer("❌ Qismlar soni 1 dan katta bo'lishi kerak!")
            return
        if new_qismi <= current_qismi:
            await message.answer(
                f"❌ Faqat oshirish mumkin.\nHozirgi son: <b>{current_qismi}</b>\n"
                f"Iltimos <b>{current_qismi + 1}</b> yoki undan katta son yuboring.",
                parse_mode="HTML"
            )
            return
        new_value = str(new_qismi)
    elif field == "nom":
        value = (message.text or "").strip()
        if not value:
            await message.answer("❌ Nom bo'sh bo'lmasligi kerak!")
            return
        new_value = value
    elif field == "rams":
        if message.photo:
            new_value = message.photo[-1].file_id
        elif message.video:
            new_value = message.video.file_id
        elif message.document and message.document.mime_type and (message.document.mime_type.startswith("image/") or message.document.mime_type.startswith("video/")):
            new_value = message.document.file_id
        else:
            await message.answer("❌ Faqat rasm yoki video yuboring!")
            return
    elif field == "filler_image":
        if message.photo:
            new_value = message.photo[-1].file_id
        elif message.document and message.document.mime_type and message.document.mime_type.startswith("image/"):
            new_value = message.document.file_id
        else:
            value = (message.text or "").strip()
            if value == "-":
                new_value = ""
            elif value:
                new_value = value
            else:
                await message.answer("Rasm, file_id yoki URL yuboring!")
                return
    elif field == "filler_info":
        value = (message.text or "").strip()
        new_value = "" if value == "-" else value
    else:
        value = (message.text or "").strip()
        if not value:
            await message.answer("❌ Qiymat bo'sh bo'lmasligi kerak!")
            return
        new_value = value

    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute(f"UPDATE animelar SET {field}=? WHERE id=?", (new_value, anime_id))
        await db.commit()
    
    await state.clear()
    if field == "qismi":
        await message.answer(
            f"✅ Qismlar soni muvaffaqiyatli oshirildi: <b>{current_qismi}</b> ➜ <b>{new_qismi}</b>",
            reply_markup=panel_kb(),
            parse_mode="HTML"
        )
        return
    await message.answer("✅ Ma'lumot yangilandi!", reply_markup=panel_kb())


@router.callback_query(F.data.startswith("prepDelAnime="))
async def prepare_delete_anime(callback: CallbackQuery, state: FSMContext):
    anime_id = int(callback.data.split("=")[1])
    
    buttons = [
        [InlineKeyboardButton(text="✅ Ha, o'chirilsin", callback_data=f"execDelAnime={anime_id}")],
        [InlineKeyboardButton(text="❌ Yo'q, qolsin", callback_data=f"manageAnime={anime_id}")]
    ]
    await callback.message.edit_text("<b>⚠️ Diqqat! Ushbu animeni va unga tegishli BARCHA QISMLARNI o'chirib yubormoqchimisiz?</b>",
                                     reply_markup=InlineKeyboardMarkup(inline_keyboard=buttons), parse_mode="HTML")
    await callback.answer()


@router.callback_query(F.data.startswith("execDelAnime="))
async def execute_delete_anime(callback: CallbackQuery):
    anime_id = int(callback.data.split("=")[1])
    
    async with aiosqlite.connect(DB_PATH) as db:
        # Anime o'zi
        await db.execute("DELETE FROM animelar WHERE id=?", (anime_id,))
        # Unga tegishli qismlar
        await db.execute("DELETE FROM anime_datas WHERE id=?", (anime_id,))
        await db.commit()
        
    await callback.message.edit_text("✅ Anime va barcha qismlari butkul o'chirildi!")
    await callback.answer()


# ─── Stub handlerlar (hozircha) ──────────────────────────────────────────────


# ─── *️⃣ Birlamchi sozlamalar ─────────────────────────────────────────────────

SETTINGS_LABELS = {
    "vip_price":      "💰 VIP narxi",
    "vip_currency":   "💱 VIP valyuta",
    "referral_bonus": "👥 Referal bonus (so'm)",
    "cashback_percent": "🎁 Cashback (%)",
    "web_app_url": "🌐 Web App URL (bo'sh = o'chiq)",
    "start_text":     "👋 Start xabari",
}

BUTTON_STYLE_LABELS = {
    "button_style_default": "🔵 Oddiy tugmalar rangi",
    "button_style_positive": "🟢 Asosiy/ijobiy tugmalar rangi",
    "button_style_negative": "🔴 Bekor/rad/o'chirish tugmalari rangi",
    "button_style_watch": "🟢 Watchlist/saqlash tugmalari rangi",
}


@router.message(F.text == "*️⃣ Birlamchi sozlamalar")
async def basic_settings_handler(message: Message, state: FSMContext):
    if not await is_admin(message.from_user.id):
        return

    async with aiosqlite.connect(DB_PATH) as db:
        async with db.execute("SELECT key, value FROM bot_settings") as cursor:
            rows = await cursor.fetchall()

    settings = {r[0]: r[1] for r in rows}

    is_super = await is_super_admin(message.from_user.id)
    labels = SETTINGS_LABELS | (BUTTON_STYLE_LABELS if is_super else {})

    text = "<b>*️⃣ Birlamchi sozlamalar:</b>\n\n"
    for key, label in labels.items():
        val = settings.get(key, "—")
        text += f"{label}: <b>{val}</b>\n"

    if is_super:
        text += "\n<i>Rang qiymatlari: primary, success, danger</i>"

    buttons = [
        [InlineKeyboardButton(text=f"✏️ {label}", callback_data=f"editSetting={key}")]
        for key, label in labels.items()
    ]
    await message.answer(text, reply_markup=InlineKeyboardMarkup(inline_keyboard=buttons), parse_mode="HTML")


@router.callback_query(F.data.startswith("editSetting="))
async def edit_setting_prompt(callback: CallbackQuery, state: FSMContext):
    key = callback.data.split("=")[1]
    if key.startswith("button_style_") and not await is_super_admin(callback.from_user.id):
        await callback.answer("❌ Bu sozlama faqat superadmin uchun!", show_alert=True)
        return

    label = (SETTINGS_LABELS | BUTTON_STYLE_LABELS).get(key, key)
    await state.update_data(setting_key=key)
    extra = "\n\n<i>Rang uchun faqat: primary, success, danger</i>" if key.startswith("button_style_") else ""
    await callback.message.answer(
        f"<b>✏️ {label}</b> uchun yangi qiymatni yuboring:{extra}",
        parse_mode="HTML"
    )
    await state.set_state(SettingsStates.edit_value)
    await callback.answer()


@router.message(SettingsStates.edit_value)
async def process_setting_value(message: Message, state: FSMContext):
    # URL, oddiy matn, entity — barchasini qabul qilish
    value = message.text or message.caption or ""
    # Agar entity (link) bo'lsa — undan ham olamiz
    if not value and message.entities:
        for entity in message.entities:
            if entity.type == "url":
                value = message.text[entity.offset:entity.offset + entity.length]
                break

    if not value:
        await message.answer("❌ Qiymat bo'sh bo'lishi mumkin emas!")
        return

    data = await state.get_data()
    key = data.get("setting_key")
    if not key:
        return
    if key.startswith("button_style_"):
        if not await is_super_admin(message.from_user.id):
            await message.answer("❌ Bu sozlama faqat superadmin uchun!")
            return
        normalized = normalize_button_style(value, "")
        if not normalized:
            await message.answer("❌ Rang qiymati noto'g'ri. Faqat: primary, success, danger")
            return
        value = normalized

    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute(
            "INSERT OR REPLACE INTO bot_settings (key, value) VALUES (?, ?)",
            (key, value)
        )
        await db.commit()

    if key.startswith("button_style_"):
        set_button_style(key, value)

    label = (SETTINGS_LABELS | BUTTON_STYLE_LABELS).get(key, key)
    await state.clear()
    is_super = await is_super_admin(message.from_user.id)
    await message.answer(
        f"✅ <b>{label}</b> yangilandi: <code>{value}</code>",
        reply_markup=panel_kb(is_super), parse_mode="HTML"
    )


# ─── 📋 Jurnallar ─────────────────────────────────────────────────────────────

@router.message(F.text == "📋 Jurnallar")
async def logs_handler(message: Message):
    if not await is_super_admin(message.from_user.id):
        await message.answer("❌ Bu bo'lim faqat Asosiy Admin uchun!", parse_mode="HTML")
        return
    
    logs_text = get_logs_text(limit=20)  # Saytlar uchun 20 log
    keyboard = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="🔄 Yangilash", callback_data="refresh_logs_20")],
        [InlineKeyboardButton(text="📊 Barcha logs (50)", callback_data="refresh_logs_50")],
        [InlineKeyboardButton(text="◀️ Orqaga", callback_data="back_to_panel_from_logs")]
    ])
    await message.answer(logs_text, parse_mode="HTML", reply_markup=keyboard)


@router.callback_query(F.data == "refresh_logs_20")
async def refresh_logs_20(callback: CallbackQuery):
    if not await is_super_admin(callback.from_user.id):
        await callback.answer("❌ Ruhsat yo'q!", show_alert=True)
        return
    
    try:
        logs_text = get_logs_text(limit=20)
        keyboard = InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="🔄 Yangilash", callback_data="refresh_logs_20")],
            [InlineKeyboardButton(text="📊 Barcha logs (50)", callback_data="refresh_logs_50")],
            [InlineKeyboardButton(text="◀️ Orqaga", callback_data="back_to_panel_from_logs")]
        ])
        
        # Xabar o'zgargan bo'lsa tahrir qil
        if callback.message.text != logs_text or callback.message.reply_markup != keyboard:
            await callback.message.edit_text(logs_text, parse_mode="HTML", reply_markup=keyboard)
        
        await callback.answer("✅ Yangilandi!")
    except Exception as e:
        # "message is not modified" xatosini ignorir qil
        if "message is not modified" in str(e):
            await callback.answer("✅ Allaqachon yangi!", show_alert=False)
        else:
            await callback.answer(f"❌ Xato: {str(e)[:50]}", show_alert=True)


@router.callback_query(F.data == "refresh_logs_50")
async def refresh_logs_50(callback: CallbackQuery):
    if not await is_super_admin(callback.from_user.id):
        await callback.answer("❌ Ruhsat yo'q!", show_alert=True)
        return
    
    try:
        logs_text = get_logs_text(limit=50)
        keyboard = InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="🔄 Yangilash", callback_data="refresh_logs_50")],
            [InlineKeyboardButton(text="📋 Kami logs (20)", callback_data="refresh_logs_20")],
            [InlineKeyboardButton(text="◀️ Orqaga", callback_data="back_to_panel_from_logs")]
        ])
        
        # Xabar o'zgargan bo'lsa tahrir qil
        if callback.message.text != logs_text or callback.message.reply_markup != keyboard:
            await callback.message.edit_text(logs_text, parse_mode="HTML", reply_markup=keyboard)
        
        await callback.answer("✅ Yangilandi!")
    except Exception as e:
        # "message is not modified" xatosini ignorir qil
        if "message is not modified" in str(e):
            await callback.answer("✅ Allaqachon yangi!", show_alert=False)
        else:
            await callback.answer(f"❌ Xato: {str(e)[:50]}", show_alert=True)


@router.callback_query(F.data == "back_to_panel_from_logs")
async def back_to_panel_from_logs(callback: CallbackQuery):
    try:
        is_super = await is_super_admin(callback.from_user.id)
        panel_text = "<b>🗄 Admin paneliga xush kelibsiz!</b>"
        panel_kb_obj = panel_kb(is_super)
        
        # Xabar o'zgargan bo'lsa tahrir qil
        if callback.message.text != panel_text or callback.message.reply_markup != panel_kb_obj:
            await callback.message.edit_text(panel_text, reply_markup=panel_kb_obj, parse_mode="HTML")
        
        await callback.answer()
    except Exception as e:
        # "message is not modified" xatosini ignorir qil
        if "message is not modified" in str(e):
            await callback.answer()
        else:
            await callback.answer(f"❌ Xato: {str(e)[:50]}", show_alert=True)


# ─── 📋 Adminlar ─────────────────────────────────────────────────────────────

@router.message(F.text == "📋 Adminlar")
async def admins_menu(message: Message):
    if not await is_super_admin(message.from_user.id):
        await message.answer("❌ Bu bo'lim faqat Asosiy Admin uchun!")
        return

    async with aiosqlite.connect(DB_PATH) as db:
        async with db.execute("SELECT user_id, added_by FROM admins") as cursor:
            admins_list = await cursor.fetchall()

    if not admins_list:
        text = "<b>📋 Qo'shimcha adminlar yo'q.</b>"
    else:
        text = "<b>📋 Tasdiqlangan Adminlar:</b>\n\n"
        for a in admins_list:
            text += f"👤 ID: <code>{a[0]}</code> (Qo'shgan: {a[1]})\n"

    buttons = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="➕ Admin qo'shish", callback_data="addAdmin_prompt")],
        [InlineKeyboardButton(text="🗑 Admin o'chirish", callback_data="removeAdmin_prompt")]
    ])
    await message.answer(text, reply_markup=buttons, parse_mode="HTML")


@router.callback_query(F.data == "addAdmin_prompt")
async def process_add_admin_prompt(callback: CallbackQuery, state: FSMContext):
    if not await is_super_admin(callback.from_user.id):
        await callback.answer("❌ Faqat asosiy admin bu amalni bajarav oladi!", show_alert=True)
        return
    await callback.message.answer(
        "<b>Yangi adminning Telegram ID sini yuboring:</b>\n\n<i>Misol: 123456789</i>",
        parse_mode="HTML"
    )
    await state.set_state(AdminStates.add_admin)
    await callback.answer()


@router.message(AdminStates.add_admin)
async def process_add_admin_id(message: Message, state: FSMContext, bot: Bot):
    if not message.text or not message.text.isdigit():
        await message.answer("❌ ID faqat raqamlardan iborat bo'lishi kerak!")
        return
    
    new_admin_id = int(message.text)
    
    # Avval tekshiramiz — bu user allaqachon admin bo'lmali
    if await is_admin(new_admin_id):
        await message.answer(
            f"⚠️ <code>{new_admin_id}</code> allaqachon admin!",
            parse_mode="HTML"
        )
        await state.clear()
        return
    
    async with aiosqlite.connect(DB_PATH) as db:
        try:
            await db.execute(
                "INSERT INTO admins (user_id, added_by) VALUES (?, ?)",
                (new_admin_id, message.from_user.id)
            )
            await db.commit()
            
            # admin.json fayliga ham saqlash
            username = message.from_user.username or "Unknown"
            add_json_admin(new_admin_id, username)
            
            # Log qilish
            log_admin_action(
                "admin_added",
                message.from_user.id,
                message.from_user.username or f"ID: {message.from_user.id}",
                new_admin_id=new_admin_id
            )
            
            invalidate_admin_cache(new_admin_id)
            
            await message.answer(
                f"✅ <code>{new_admin_id}</code> adminlarga qo'shildi!",
                parse_mode="HTML", 
                reply_markup=panel_kb()
            )
            
            # Admin tizimga kiritish log'i
            await bot.send_message(
                chat_id=message.from_user.id,
                text=f"📝 <b>Admin qo'shildi:</b> <code>{new_admin_id}</code>\nQo'shgan: {message.from_user.first_name}",
                parse_mode="HTML"
            )
            
        except Exception as e:
            print(f"[ADMIN ERROR] {e}")
            await message.answer(
                f"❌ Xato: {str(e)[:100]}\n\nAdmin qo'shish muvaffaqiyatsiz bo'ldi!",
                parse_mode="HTML"
            )
    
    await state.clear()



@router.callback_query(F.data == "removeAdmin_prompt")
async def remove_admin_prompt(callback: CallbackQuery):
    if not await is_super_admin(callback.from_user.id):
        await callback.answer("❌ Faqat asosiy admin bu amalni bajarav olaA!", show_alert=True)
        return
        
    async with aiosqlite.connect(DB_PATH) as db:
        async with db.execute("SELECT user_id FROM admins") as cursor:
            admins_list = await cursor.fetchall()

    if not admins_list:
        await callback.answer("O'chirish uchun adminlar yo'q!", show_alert=True)
        return

    buttons = []
    for a in admins_list:
        buttons.append([InlineKeyboardButton(text=f"🗑 {a[0]}", callback_data=f"delAdmin={a[0]}")])

    await callback.message.answer(
        "<b>O'chirish uchun adminni tanlang:</b>",
        reply_markup=InlineKeyboardMarkup(inline_keyboard=buttons), parse_mode="HTML"
    )
    await callback.answer()


@router.callback_query(F.data.startswith("delAdmin="))
async def delete_admin_callback(callback: CallbackQuery):
    if not await is_super_admin(callback.from_user.id):
        await callback.answer("❌ Faqat asosiy admin bu amalni bajarav olaA!", show_alert=True)
        return
    
    try:
        admin_to_del = int(callback.data.split("=")[1])
    except (ValueError, IndexError):
        await callback.answer("❌ Xato: Noto'g'ri admin ID!", show_alert=True)
        return
    
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute("DELETE FROM admins WHERE user_id=?", (admin_to_del,))
        await db.commit()
    
    # admin.json fayildan ham o'chirish
    remove_json_admin(admin_to_del)
    
    # Log qilish
    log_admin_action(
        "admin_removed",
        callback.from_user.id,
        callback.from_user.username or f"ID: {callback.from_user.id}",
        removed_admin_id=admin_to_del
    )
    
    invalidate_admin_cache(admin_to_del)
    await callback.message.edit_text(
        f"✅ Admin <code>{admin_to_del}</code> o'chirildi!",
        parse_mode="HTML"
    )
    await callback.answer()



# ─── 📬 Post tayyorlash ───────────────────────────────────────────────────────


# ─── 🎛 Tugmalar ─────────────────────────────────────────────────────────────

@router.message(F.text == "🎛 Tugmalar")
async def buttons_handler(message: Message):
    if not await is_admin(message.from_user.id):
        return

    async with aiosqlite.connect(DB_PATH) as db:
        async with db.execute("SELECT id, text, url FROM custom_buttons") as cursor:
            btns = await cursor.fetchall()

    if not btns:
        text = "<b>🎛 Hozircha hech qanday tugma qo'shilmagan.</b>\n\nTugmalar 📬 Post tayyorlashda ishlatiladi."
    else:
        text = "<b>🎛 Qo'shilgan tugmalar:</b>\n\n"
        for b in btns:
            text += f"• <b>{b[1]}</b> → <code>{b[2]}</code>\n"

    action_buttons = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="➕ Tugma qo'shish", callback_data="addCustomBtn")],
        [InlineKeyboardButton(text="🗑 Tugma o'chirish", callback_data="removeCustomBtn")],
    ])
    await message.answer(text, reply_markup=action_buttons, parse_mode="HTML")


@router.callback_query(F.data == "addCustomBtn")
async def add_custom_btn_prompt(callback: CallbackQuery, state: FSMContext):
    await callback.message.answer(
        "<b>➕ Tugma matni kiriting:</b>\n\n<i>Misol: 🌐 Bizning kanal</i>",
        parse_mode="HTML"
    )
    await state.set_state(ButtonStates.add_btn_text)
    await callback.answer()


@router.message(ButtonStates.add_btn_text)
async def process_btn_text(message: Message, state: FSMContext):
    await state.update_data(btn_text=message.text)
    await message.answer(
        "<b>🔗 Tugma URL sini kiriting:</b>\n\n<i>Misol: https://t.me/kanal_nomi</i>",
        parse_mode="HTML"
    )
    await state.set_state(ButtonStates.add_btn_url)


@router.message(ButtonStates.add_btn_url)
async def process_btn_url(message: Message, state: FSMContext):
    if not message.text.startswith("http"):
        await message.answer("❌ URL noto'g'ri! https:// bilan boshlashi kerak.")
        return
    data = await state.get_data()
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute(
            "INSERT INTO custom_buttons (text, url) VALUES (?, ?)",
            (data['btn_text'], message.text)
        )
        await db.commit()
    await state.clear()
    await message.answer(
        f"✅ Tugma qo'shildi!\n\n<b>{data['btn_text']}</b> → <code>{message.text}</code>",
        reply_markup=panel_kb(), parse_mode="HTML"
    )


@router.callback_query(F.data == "removeCustomBtn")
async def remove_custom_btn_prompt(callback: CallbackQuery):
    async with aiosqlite.connect(DB_PATH) as db:
        async with db.execute("SELECT id, text, url FROM custom_buttons") as cursor:
            btns = await cursor.fetchall()
    if not btns:
        await callback.answer("Hech qanday tugma yo'q!", show_alert=True)
        return
    buttons = [
        [InlineKeyboardButton(text=f"🗑 {b[1]}", callback_data=f"delCustomBtn={b[0]}")]
        for b in btns
    ]
    await callback.message.answer(
        "<b>O'chirish uchun tugmani tanlang:</b>",
        reply_markup=InlineKeyboardMarkup(inline_keyboard=buttons), parse_mode="HTML"
    )
    await callback.answer()


@router.callback_query(F.data.startswith("delCustomBtn="))
async def delete_custom_btn(callback: CallbackQuery):
    btn_id = int(callback.data.split("=")[1])
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute("DELETE FROM custom_buttons WHERE id=?", (btn_id,))
        await db.commit()
    await callback.message.edit_text("✅ Tugma o'chirildi!")
    await callback.answer()


@router.message(F.text == "📬 Post tayyorlash")
async def post_prepare_handler(message: Message, state: FSMContext):
    if not await is_admin(message.from_user.id):
        return

    await message.answer(
        "<b>📬 Post tayyorlash</b>\n\n"
        "1️⃣ Rasm yoki video yuboring\n"
        "<i>(Faqat matn post bo'lsa /skip yozing)</i>",
        reply_markup=boshqarish_kb(), parse_mode="HTML"
    )
    await state.set_state(PostStates.media)


@router.message(PostStates.media, F.photo | F.video | F.document)
async def post_get_media(message: Message, state: FSMContext):
    if message.photo:
        await state.update_data(media_type="photo", media_id=message.photo[-1].file_id)
    elif message.video:
        await state.update_data(media_type="video", media_id=message.video.file_id)
    elif message.document:
        await state.update_data(media_type="document", media_id=message.document.file_id)

    await message.answer(
        "2️⃣ Post matni (caption) ni yuboring:\n<i>(/skip — matnsiz)</i>",
        parse_mode="HTML"
    )
    await state.set_state(PostStates.caption)


@router.message(PostStates.media, F.text)
async def post_skip_media(message: Message, state: FSMContext):
    if message.text == "/skip":
        await state.update_data(media_type=None, media_id=None)
        await message.answer("2️⃣ Post matni (caption) ni yuboring:")
        await state.set_state(PostStates.caption)
    else:
        await message.answer("❌ Rasm, video yuboring yoki /skip yozing.")


@router.message(PostStates.caption, F.text)
async def post_get_caption(message: Message, state: FSMContext):
    caption = None if message.text == "/skip" else message.text
    await state.update_data(caption=caption)

    # Saqlangan tugmalarni ko'rsat
    async with aiosqlite.connect(DB_PATH) as db:
        async with db.execute("SELECT id, text, url FROM custom_buttons") as cursor:
            saved_btns = await cursor.fetchall()

    if saved_btns:
        btn_list = "\n".join([f"• {b[1]}" for b in saved_btns])
        btns_ui = InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="✅ Saqlangan tugmalarni qo'sh", callback_data="postUseSavedBtns")],
            [InlineKeyboardButton(text="✏️ Yangi tugma qo'shish", callback_data="postAddNewBtn")],
            [InlineKeyboardButton(text="🚫 Tugrumsiz yuborish", callback_data="postNoBtns")],
        ])
        await message.answer(
            f"3️⃣ Tugmalar:\n\n<b>Saqlangan tugmalar:</b>\n{btn_list}\n\nQaysi variantni tanlaysiz?",
            reply_markup=btns_ui, parse_mode="HTML"
        )
    else:
        btns_ui = InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="✏️ Yangi tugma qo'shish", callback_data="postAddNewBtn")],
            [InlineKeyboardButton(text="🚫 Tugrumsiz yuborish", callback_data="postNoBtns")],
        ])
        await message.answer("3️⃣ Tugmalar qo'shmoqchimisiz?", reply_markup=btns_ui)

    await state.set_state(PostStates.buttons)


@router.callback_query(PostStates.buttons, F.data == "postUseSavedBtns")
async def post_use_saved_btns(callback: CallbackQuery, state: FSMContext):
    async with aiosqlite.connect(DB_PATH) as db:
        async with db.execute("SELECT text, url FROM custom_buttons") as cursor:
            btns = await cursor.fetchall()
    await state.update_data(post_buttons=[[b[0], b[1]] for b in btns])
    await callback.message.answer("✅ Saqlangan tugmalar qo'shildi! Preview ko'ring:")
    await show_post_preview(callback.message, state)
    await callback.answer()


@router.callback_query(PostStates.buttons, F.data == "postAddNewBtn")
async def post_add_new_btn(callback: CallbackQuery, state: FSMContext):
    await callback.message.answer(
        "✏️ Tugma matni va URL ni quyidagi formatda yuboring:\n\n"
        "<code>Tugma matni | https://t.me/kanal</code>",
        parse_mode="HTML"
    )
    await callback.answer()


@router.message(PostStates.buttons, F.text)
async def post_get_custom_btn(message: Message, state: FSMContext):
    if "|" not in message.text:
        await message.answer("❌ Format noto'g'ri! \n<code>Matn | URL</code> ko'rinishida yuboring.", parse_mode="HTML")
        return
    parts = message.text.split("|", 1)
    btn_text = parts[0].strip()
    btn_url = parts[1].strip()
    if not btn_url.startswith("http"):
        await message.answer("❌ URL https:// bilan boshlanishi kerak!")
        return

    data = await state.get_data()
    existing = data.get("post_buttons", [])
    existing.append([btn_text, btn_url])
    await state.update_data(post_buttons=existing)
    await message.answer(f"✅ Tugma qo'shildi: <b>{btn_text}</b>\n\nYana qo'shish uchun yuboring yoki preview ko'rish uchun /done yozing.", parse_mode="HTML")


@router.message(PostStates.buttons, F.text == "/done")
async def post_done_buttons(message: Message, state: FSMContext):
    await show_post_preview(message, state)


@router.callback_query(PostStates.buttons, F.data == "postNoBtns")
async def post_no_buttons(callback: CallbackQuery, state: FSMContext):
    await state.update_data(post_buttons=[])
    await show_post_preview(callback.message, state)
    await callback.answer()


async def show_post_preview(message: Message, state: FSMContext):
    data = await state.get_data()
    media_type = data.get("media_type")
    media_id = data.get("media_id")
    caption = data.get("caption", "")
    post_buttons = data.get("post_buttons", [])

    markup = None
    if post_buttons:
        markup = InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text=b[0], url=b[1])] for b in post_buttons
        ])

    confirm_kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="📤 Kanalga yuborish", callback_data="postSendNow")],
        [InlineKeyboardButton(text="❌ Bekor qilish", callback_data="postCancel")],
    ])

    await message.answer("<b>👁 Post ko'rinishi:</b>", parse_mode="HTML")

    try:
        if media_type == "photo":
            await message.answer_photo(media_id, caption=caption, reply_markup=markup, parse_mode="HTML")
        elif media_type == "video":
            await message.answer_video(media_id, caption=caption, reply_markup=markup, parse_mode="HTML")
        elif media_type == "document":
            await message.answer_document(media_id, caption=caption, reply_markup=markup, parse_mode="HTML")
        else:
            await message.answer(caption or "📭 Matn yo'q", reply_markup=markup, parse_mode="HTML")
    except Exception as e:
        await message.answer(f"⚠️ Preview xatosi: {e}")

    await message.answer("Postni kanalga yuborasizmi?", reply_markup=confirm_kb)
    await state.set_state(PostStates.confirm)


@router.callback_query(PostStates.confirm, F.data == "postSendNow")
async def post_send_now(callback: CallbackQuery, state: FSMContext, bot: Bot):
    from config import MAIN_CHANNEL_ID
    data = await state.get_data()
    media_type = data.get("media_type")
    media_id = data.get("media_id")
    caption = data.get("caption", "")
    post_buttons = data.get("post_buttons", [])

    markup = None
    if post_buttons:
        markup = InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text=b[0], url=b[1])] for b in post_buttons
        ])

    try:
        if media_type == "photo":
            await bot.send_photo(MAIN_CHANNEL_ID, media_id, caption=caption, reply_markup=markup, parse_mode="HTML")
        elif media_type == "video":
            await bot.send_video(MAIN_CHANNEL_ID, media_id, caption=caption, reply_markup=markup, parse_mode="HTML")
        elif media_type == "document":
            await bot.send_document(MAIN_CHANNEL_ID, media_id, caption=caption, reply_markup=markup, parse_mode="HTML")
        else:
            await bot.send_message(MAIN_CHANNEL_ID, caption or ".", reply_markup=markup, parse_mode="HTML")

        await callback.message.answer("✅ Post muvaffaqiyatli kanalga yuborildi!", reply_markup=panel_kb())
    except Exception as e:
        await callback.message.answer(f"❌ Xatolik: {e}\n(Bot kanalda admin ekanligini tekshiring)")

    await state.clear()
    await callback.answer()


@router.callback_query(PostStates.confirm, F.data == "postCancel")
async def post_cancel(callback: CallbackQuery, state: FSMContext):
    await state.clear()
    await callback.message.answer("❌ Post bekor qilindi.", reply_markup=panel_kb())
    await callback.answer()


# ─── 📋 Ro'yxat yuborish (kanal + pin) ───────────────────────────────────────

ROYXAT_PER_PAGE = 40  # Har bir postda nechta anime

@router.message(F.text == "📋 Ro'yxat yuborish")
async def royxat_yuborish_handler(message: Message, bot: Bot):
    if not await is_admin(message.from_user.id):
        return

    from config import MAIN_CHANNEL_ID, BOT_USERNAME

    if not MAIN_CHANNEL_ID:
        await message.answer("❌ MAIN_CHANNEL_ID sozlanmagan! .env ni tekshiring.")
        return

    # DB dan barcha animelarni tartib bo'yicha olamiz
    async with aiosqlite.connect(DB_PATH) as db:
        async with db.execute("SELECT id, nom FROM animelar ORDER BY id ASC") as cursor:
            animelar = await cursor.fetchall()

    if not animelar:
        await message.answer("❌ Bazada hech qanday anime yo'q!")
        return

    total = len(animelar)
    chunks = [animelar[i:i + ROYXAT_PER_PAGE] for i in range(0, total, ROYXAT_PER_PAGE)]

    progress_msg = await message.answer(
        f"⏳ Ro'yxat tayyorlanmoqda...\n"
        f"📊 Jami: <b>{total}</b> ta anime | <b>{len(chunks)}</b> ta post",
        parse_mode="HTML"
    )

    sent_count = 0
    pin_errors = 0

    for i, chunk in enumerate(chunks):
        start_num = i * ROYXAT_PER_PAGE + 1
        end_num   = start_num + len(chunk) - 1

        # ── Post matni ──
        header = f"🗒---♣◇Animelar ro'yxati ({start_num}-{end_num})◇♣---🗒\n\n"
        lines = []
        for idx, (anime_id, nom) in enumerate(chunk):
            num = start_num + idx
            link = f"https://t.me/{BOT_USERNAME}?start={anime_id}"
            lines.append(f'{num} - <a href="{link}">[ {nom} ]</a>')

        text = header + "\n".join(lines)

        try:
            sent = await bot.send_message(
                chat_id=MAIN_CHANNEL_ID,
                text=text,
                parse_mode="HTML",
                disable_web_page_preview=True
            )
            sent_count += 1

            # Har bir xabarni pin qilamiz (notification chiqarmay)
            try:
                await bot.pin_chat_message(
                    chat_id=MAIN_CHANNEL_ID,
                    message_id=sent.message_id,
                    disable_notification=True
                )
            except Exception as pin_err:
                pin_errors += 1
                # Pin qila olmasa ham davom etamiz

        except Exception as send_err:
            await message.answer(f"❌ {i+1}-post yuborishda xato: {send_err}")
            break

        # Flood limitdan himoya uchun kichik kutish
        if i < len(chunks) - 1:
            import asyncio
            await asyncio.sleep(1.5)

    # Natija
    result_text = (
        f"✅ Ro'yxat yuborildi!\n\n"
        f"📤 Yuborilgan postlar: <b>{sent_count}/{len(chunks)}</b>\n"
        f"📌 Pin qilinganlar: <b>{sent_count - pin_errors}</b>\n"
        f"🎬 Jami animelar: <b>{total}</b> ta"
    )
    if pin_errors:
        result_text += f"\n⚠️ Pin xatolari: <b>{pin_errors}</b> (Bot kanalda admin va pin huquqi borligini tekshiring)"

    is_super = await is_super_admin(message.from_user.id)
    await progress_msg.delete()
    await message.answer(result_text, reply_markup=panel_kb(is_super), parse_mode="HTML")
