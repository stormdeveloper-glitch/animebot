import aiosqlite
import html
from aiogram import Router, F, Bot
from aiogram.filters import CommandStart, Command
from aiogram.types import (
    Message, CallbackQuery, ChatJoinRequest,
    InlineKeyboardMarkup, WebAppInfo
)
from aiogram.fsm.context import FSMContext
from datetime import datetime, timedelta

from config import DB_PATH, ADMIN_IDS, SUPER_ADMIN_ID
from keyboards import (
    menu_kb, search_type_kb, download_kb, episodes_kb,
    payment_confirm_kb, vip_plans_kb, download_options_kb, select_episode_kb,
    search_by_age_kb, YOSH_TOIFALAR, InlineKeyboardButton
)
import urllib.parse
from utils import check_subscription, get_subscription_keyboard, is_admin, is_maintenance, get_bot_username, is_content_restricted
from utils.logger import log_admin_action
from utils.ai_assistant import generate_anime_tavsif
from states import UserStates, AdminStates, PaymentStates, VipStates, TransferStates

async def _push(event_type, text, color="c"):
    """Web serverga hodisa yuboradi (xato bo'lsa jim o'tadi)."""
    try:
        import sys, os
        sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
        from web_server import push_event
        await push_event(event_type, text, color)
    except Exception:
        pass

router = Router()

# ─── Animated Emoji helpers ───────────────────────────────────────────────────
def ae(emoji_id: str, fallback: str) -> str:
    """Animated emoji — Premium foydalanuvchilarda animatsiyalanadi, boshqalarda oddiy ko'rinadi."""
    return f'<tg-emoji emoji-id="{emoji_id}">{fallback}</tg-emoji>'

# Eng ko'p ishlatiladigan animated emojilar
STAR      = ae("5368324170671202286", "✨")   # yulduzcha
FIRE      = ae("5373123172420581514", "🔥")   # olov
HEART     = ae("5346698606479917895", "❤️")  # yurak
CLAP      = ae("5368324170671202286", "👏")   # qarsak
PARTY     = ae("5373141891321699086", "🎉")   # bayram
CHECK     = ae("5368324170671202286", "✅")   # tayyor
SEARCH    = ae("5373141891321699086", "🔍")   # qidiruv
ANIME     = ae("5373123172420581514", "🎬")   # kino
DIAMOND   = ae("5346698606479917895", "💎")   # olmos
MONEY     = ae("5373141891321699086", "💰")   # pul
GIFT      = ae("5373123172420581514", "🎁")   # sovg'a
ROCKET    = ae("5368324170671202286", "🚀")   # raketa
WAVE      = ae("5346698606479917895", "👋")   # salom
CROWN     = ae("5373141891321699086", "👑")   # toj


async def get_watch_state(user_id: int, anime_id: int) -> tuple[bool, int]:
    """Foydalanuvchining watchlist/progress holati."""
    async with aiosqlite.connect(DB_PATH) as db:
        async with db.execute(
            "SELECT 1 FROM watchlist WHERE user_id=? AND anime_id=?",
            (user_id, anime_id)
        ) as c:
            is_saved = await c.fetchone() is not None

        async with db.execute(
            "SELECT last_episode FROM watch_progress WHERE user_id=? AND anime_id=?",
            (user_id, anime_id)
        ) as c:
            row = await c.fetchone()

    continue_ep = row[0] if row and row[0] else 0
    return is_saved, continue_ep


async def set_watch_progress(user_id: int, anime_id: int, ep_num: int) -> None:
    """Oxirgi ko'rilgan qismni saqlaydi."""
    if ep_num <= 0:
        return
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute(
            """
            INSERT INTO watch_progress (user_id, anime_id, last_episode, updated_at)
            VALUES (?, ?, ?, CURRENT_TIMESTAMP)
            ON CONFLICT(user_id, anime_id) DO UPDATE SET
                last_episode = CASE
                    WHEN excluded.last_episode > watch_progress.last_episode
                    THEN excluded.last_episode
                    ELSE watch_progress.last_episode
                END,
                updated_at = CURRENT_TIMESTAMP
            """,
            (user_id, anime_id, ep_num),
        )
        await db.commit()


DOWNLOAD_BATCH_SIZE = 50


def download_next_range_kb(anime_id: int, next_offset: int, total_count: int, episodes: list):
    if next_offset >= total_count:
        return None
    end_offset = min(next_offset + DOWNLOAD_BATCH_SIZE, total_count)
    first_ep = episodes[next_offset][0]
    last_ep = episodes[end_offset - 1][0]
    return InlineKeyboardMarkup(inline_keyboard=[[
        InlineKeyboardButton(
            text=f"{first_ep}-{last_ep} qismlarni yuklash",
            callback_data=f"dl_all={anime_id}={next_offset}"
        )
    ]])


async def send_download_batch(message: Message, bot: Bot, anime_id: int, episodes: list, anime_name: str, restricted: bool):
    import asyncio

    success = 0
    failed = 0
    max_sent_ep = 0
    for ep_num, file_id in episodes:
        caption = await build_episode_caption(anime_id, ep_num, anime_name, bot)
        try:
            try:
                await message.answer_video(
                    video=file_id, caption=caption, parse_mode="HTML",
                    protect_content=restricted
                )
            except Exception:
                await message.answer_document(
                    document=file_id, caption=caption, parse_mode="HTML",
                    protect_content=restricted
                )
            success += 1
            if ep_num > max_sent_ep:
                max_sent_ep = ep_num
        except Exception:
            failed += 1
        await asyncio.sleep(0.5)
    return success, failed, max_sent_ep


async def get_season_buttons(anime_id: int) -> list:
    """Shu anime bilan bog'langan fasllar uchun inline tugmalar."""
    async with aiosqlite.connect(DB_PATH) as db:
        async with db.execute(
            "SELECT COALESCE(season_group_id, id) FROM animelar WHERE id=?",
            (anime_id,)
        ) as c:
            row = await c.fetchone()
        if not row:
            return []
        group_id = row[0] or anime_id
        async with db.execute(
            """
            SELECT id, COALESCE(season_number, 1)
            FROM animelar
            WHERE COALESCE(season_group_id, id)=?
            ORDER BY COALESCE(season_number, 1), id
            """,
            (group_id,)
        ) as c:
            seasons = await c.fetchall()

    if len(seasons) <= 1:
        return []
    buttons = []
    for sid, season_num in seasons:
        text = f"âœ… {season_num}-fasl" if int(sid) == int(anime_id) else f"{season_num}-fasl"
        callback_data = "null" if int(sid) == int(anime_id) else f"loadAnime={sid}"
        buttons.append(InlineKeyboardButton(text=text, callback_data=callback_data))
    return buttons


async def get_watchlist_items(user_id: int):
    async with aiosqlite.connect(DB_PATH) as db:
        async with db.execute(
            """
            SELECT a.id, a.nom, COALESCE(wp.last_episode, 0) AS last_ep
            FROM watchlist w
            JOIN animelar a ON a.id = w.anime_id
            LEFT JOIN watch_progress wp
                ON wp.user_id = w.user_id AND wp.anime_id = w.anime_id
            WHERE w.user_id=?
            ORDER BY w.created_at DESC
            LIMIT 30
            """,
            (user_id,),
        ) as c:
            return await c.fetchall()


def extract_webapp_url(reply_markup) -> str:
    if not reply_markup:
        return ""
    for row in getattr(reply_markup, "inline_keyboard", []):
        for btn in row:
            web_app = getattr(btn, "web_app", None)
            if web_app and getattr(web_app, "url", ""):
                return web_app.url
    return ""


@router.chat_join_request()
async def auto_approve_join_request(request: ChatJoinRequest, bot: Bot):
    """Foydalanuvchi kanalga qo'shilish so'rovi yuborganda avtomatik tasdiqlaydi."""
    try:
        await request.approve()
        await bot.send_message(
            request.from_user.id,
            "<b>✅ Kanallarga obuna so'rovingiz qabul qilindi!</b>\n\n"
            "Endi botdan to'liq foydalanishingiz mumkin.",
            parse_mode="HTML"
        )
    except Exception as e:
        print(f"ChatJoinRequest error: {e}")


MAINTENANCE_MSG = (
    "⚠️ <b>Bot tamirlanyapti</b>\n"
    "Baza bilan aloqa yo'q\n\n"
    "<i>Tez orada ishga tushadi, kuting...</i>"
)


@router.message(CommandStart())
async def command_start_handler(message: Message, state: FSMContext, bot: Bot):
    user_id = message.from_user.id

    # Admin bo'lmasa texnik ish rejimini tekshir
    if not await is_admin(user_id) and await is_maintenance():
        await message.answer(MAINTENANCE_MSG, parse_mode="HTML")
        return

    if not await check_subscription(user_id, bot):
        keyboard = await get_subscription_keyboard(user_id, bot)
        await message.answer(
            "<b>Botdan foydalanish uchun quyidagi kanallarga obuna bo'ling❗️</b>",
            reply_markup=keyboard, parse_mode="HTML"
        )
        return

    async with aiosqlite.connect(DB_PATH) as db:
        async with db.execute("SELECT 1 FROM users WHERE user_id=?", (user_id,)) as c:
            exists = await c.fetchone()
        await db.execute("INSERT OR IGNORE INTO users (user_id) VALUES (?)", (user_id,))
        await db.commit()

    if not exists:
        name = message.from_user.first_name or f"ID:{user_id}"
        await _push("new_user", f"Yangi foydalanuvchi: {name}", "gr")

    await state.clear()

    # Start parametrini tekshirish
    args = message.text.split()
    if len(args) > 1:
        param = args[1]

        # Format: add_ep_ANIMEID - adminni shu anime uchun qism qo'shishga olib kiradi
        if param.startswith("add_ep_") and param[7:].isdigit():
            if not await is_admin(user_id):
                await message.answer("Bu havola faqat adminlar uchun.")
                return
            anime_id_p = int(param[7:])
            async with aiosqlite.connect(DB_PATH) as db:
                async with db.execute("SELECT nom FROM animelar WHERE id=?", (anime_id_p,)) as cursor:
                    anime = await cursor.fetchone()
                async with db.execute("SELECT COALESCE(MAX(qism), 0) FROM anime_datas WHERE id=?", (anime_id_p,)) as cursor:
                    max_ep = await cursor.fetchone()
            if not anime:
                await message.answer("Anime topilmadi.")
                return
            next_ep = (max_ep[0] if max_ep else 0) + 1
            await state.update_data(anime_id=anime_id_p, anime_nom=anime[0], ep_num=next_ep)
            await state.set_state(AdminStates.add_episode_file)
            await message.answer(
                f"<b>{html.escape(anime[0])}</b> uchun qism qo'shish.\n\n"
                f"Keyingi qism raqami: <b>{next_ep}</b>\n"
                "Boshqa raqam kerak bo'lsa raqam yuboring yoki shu qism videosini yuboring.",
                parse_mode="HTML"
            )
            return

        # Format: ANIMEID_EPNUM — to'g'ridan-to'g'ri qism ochish (ongoing tugma)
        if "_" in param:
            parts = param.split("_", 1)
            if parts[0].isdigit() and parts[1].isdigit():
                anime_id_p = int(parts[0])
                ep_num_p = int(parts[1])
                await show_episode_direct(message, anime_id_p, ep_num_p)
                return

        # Format: faqat raqam — referal yoki anime ko'rsatish
        if param.isdigit():
            ref_id = int(param)
            if ref_id != user_id:
                async with aiosqlite.connect(DB_PATH) as db:
                    async with db.execute("SELECT refid FROM users WHERE user_id=?", (user_id,)) as c:
                        row = await c.fetchone()
                    if row and row[0] is None:
                        async with db.execute(
                            "SELECT value FROM bot_settings WHERE key='referral_bonus'"
                        ) as c:
                            bonus_row = await c.fetchone()
                        bonus = int(bonus_row[0]) if bonus_row else 500
                        await db.execute(
                            "UPDATE users SET refid=?, pul2=pul2+? WHERE user_id=?",
                            (ref_id, bonus, user_id)
                        )
                        await db.execute(
                            "UPDATE users SET pul=pul+?, odam=odam+1 WHERE user_id=?",
                            (bonus, ref_id)
                        )
                        await db.commit()
                        try:
                            await bot.send_message(
                                ref_id,
                                f"🎉 Yangi taklif! Foydalanuvchi <code>{user_id}</code> botga qo'shildi.\n"
                                f"💰 Sizga <b>{bonus}</b> so'm bonus qo'shildi!",
                                parse_mode="HTML"
                            )
                        except:
                            pass
            await show_anime(message, ref_id)
            return

    async with aiosqlite.connect(DB_PATH) as db:
        async with db.execute(
            "SELECT value FROM bot_settings WHERE key='web_app_url'"
        ) as c:
            web_row = await c.fetchone()
        web_url = (web_row[0] if web_row else "") or ""

        async with db.execute(
            "SELECT value FROM bot_settings WHERE key='start_text'"
        ) as c:
            st_row = await c.fetchone()

    default_start = (
        f"{WAVE} Assalomu alaykum, {{name}}!\n\n"
        f"{ANIME} Anime botiga xush kelibsiz!\n"
        f"{STAR} Botimizda minglab animeni o'zbek tilida tomosha qiling!"
    )
    start_template = st_row[0] if st_row else default_start
    start_text = start_template.replace("{name}", message.from_user.first_name or "")

    await message.answer(
        start_text,
        reply_markup=menu_kb(await is_admin(user_id), web_app_url=web_url), parse_mode="HTML"
    )


# ─── Obuna tekshirish callback ─────────────────────────────────────────────────

@router.callback_query(F.data == "check_subscription")
async def check_subscription_callback(callback: CallbackQuery, bot: Bot):
    user_id = callback.from_user.id
    if not await is_admin(user_id) and await is_maintenance():
        await callback.answer("⚠️ Bot tamirlanyapti, kuting...", show_alert=True)
        return
    if await check_subscription(user_id, bot):
        async with aiosqlite.connect(DB_PATH) as db:
            await db.execute("INSERT OR IGNORE INTO users (user_id) VALUES (?)", (user_id,))
            await db.commit()
            async with db.execute("SELECT value FROM bot_settings WHERE key='web_app_url'") as c:
                web_row = await c.fetchone()
            web_url = (web_row[0] if web_row else "") or ""
        await callback.message.delete()
        await callback.message.answer(
            f"{CHECK} Obuna tasdiqlandi!\n\n{WAVE} Xush kelibsiz, <b>{callback.from_user.first_name}</b>!\n{STAR} Botdan to'liq foydalanishingiz mumkin!",
            reply_markup=menu_kb(await is_admin(user_id), web_app_url=web_url), parse_mode="HTML"
        )
    else:
        await callback.answer("❌ Siz hali barcha kanallarga obuna bo'lmagansiz!", show_alert=True)


# ─── Anime ko'rsatish (ichki funksiya) ────────────────────────────────────────


def _tme_url(value: str | None, start: str | None = None) -> str:
    value = (value or "").strip()
    if not value:
        return ""
    if value.startswith("http://") or value.startswith("https://"):
        return value
    value = value.replace("https://t.me/", "").replace("http://t.me/", "").lstrip("@")
    if not value:
        return ""
    url = f"https://t.me/{value}"
    if start:
        url += f"?start={start}"
    return url


def _caption_link(label: str, url: str) -> str:
    return f'<a href="{url}">{label}</a>' if url else label


def episode_caption_footer(anime_id: int, channel_value: str | None = None) -> str:
    from config import BOT_USERNAME, MAIN_CHANNEL_USERNAME

    bot_url = _tme_url(BOT_USERNAME, str(anime_id))
    channel_url = _tme_url(channel_value or MAIN_CHANNEL_USERNAME)
    return (
        "\n\n"
        f"{_caption_link('🤖 BOTIMIZ', bot_url)} | "
        f"{_caption_link('📢 KANAL', channel_url)}"
    )


async def build_episode_caption(anime_id: int, ep_num: int, anime_name: str, bot) -> str:
    """Qism caption'ini yaratadi — kanal faqat oxirgi qismda ko'rinadi."""
    async with aiosqlite.connect(DB_PATH) as db:
        async with db.execute(
            "SELECT MAX(qism) FROM anime_datas WHERE id=?", (anime_id,)
        ) as c:
            max_ep_row = await c.fetchone()
        max_ep = max_ep_row[0] if max_ep_row else ep_num

        async with db.execute(
            "SELECT kanal FROM animelar WHERE id=?", (anime_id,)
        ) as c:
            kanal_row = await c.fetchone()
        kanal = kanal_row[0] if kanal_row and kanal_row[0] else None

    AE = '<tg-emoji emoji-id="5373123172420581514">🔥</tg-emoji>'

    if ep_num == max_ep and kanal:
        kanal_line = f"\n{AE} <b>Kanal:</b> {kanal}"
    else:
        kanal_line = ""

    caption = (
        f"<b>{anime_name}</b>\n"
        f"<i>{ep_num} - qism</i>"
        f"{kanal_line}"
        f"{episode_caption_footer(anime_id, kanal)}"
    )
    return caption


async def update_prev_episode_caption(anime_id: int, prev_ep: int, anime_name: str, bot) -> None:
    """Oldingi qismdan kanal qatorini o'chiradi (caption'ni yangilaydi)."""
    async with aiosqlite.connect(DB_PATH) as db:
        async with db.execute(
            "SELECT msg_id, chat_id FROM anime_datas WHERE id=? AND qism=?",
            (anime_id, prev_ep)
        ) as c:
            row = await c.fetchone()

    if not row or not row[0] or not row[1]:
        return

    msg_id, chat_id = row[0], row[1]
    new_caption = (
        f"<b>{anime_name}</b>\n"
        f"<i>{prev_ep} - qism</i>"
        f"{episode_caption_footer(anime_id)}"
    )

    try:
        await bot.edit_message_caption(
            chat_id=chat_id,
            message_id=msg_id,
            caption=new_caption,
            parse_mode="HTML"
        )
    except Exception:
        pass  # Xabar topilmasa yoki o'zgartirib bo'lmasa — o'tib ketadi


async def save_episode_msg_id(anime_id: int, ep_num: int, msg_id: int, chat_id: int) -> None:
    """Yuborilgan qism xabarining msg_id va chat_id sini saqlab qo'yadi."""
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute(
            "UPDATE anime_datas SET msg_id=?, chat_id=? WHERE id=? AND qism=?",
            (msg_id, chat_id, anime_id, ep_num)
        )
        await db.commit()


async def show_episode_direct(message: Message, anime_id: int, ep_num: int, viewer_id: int | None = None):
    """Ongoing tugmadan kelganda to'g'ridan-to'g'ri qismni yuboradi."""
    current_user_id = viewer_id if viewer_id is not None else message.from_user.id
    async with aiosqlite.connect(DB_PATH) as db:
        async with db.execute(
            "SELECT * FROM anime_datas WHERE id=? AND qism=?", (anime_id, ep_num)
        ) as cursor:
            episode = await cursor.fetchone()
        async with db.execute("SELECT nom FROM animelar WHERE id=?", (anime_id,)) as cursor:
            anime_row = await cursor.fetchone()
        async with db.execute(
            "SELECT qism FROM anime_datas WHERE id=? ORDER BY qism ASC", (anime_id,)
        ) as cursor:
            all_eps = await cursor.fetchall()
            all_eps_list = [{'qism': row[0]} for row in all_eps]
        
        async with db.execute("SELECT value FROM bot_settings WHERE key='content_restriction'") as cursor:
            row = await cursor.fetchone()
            restricted = row[0] == "1" if row else False

    if not episode or not anime_row:
        await message.answer("❌ Qism topilmadi.")
        return

    anime_name = anime_row[0]
    file_id = episode[2]

    from keyboards import episodes_kb, EPISODES_PER_PAGE
    all_ep_nums = [e['qism'] for e in all_eps_list]
    ep_index = all_ep_nums.index(ep_num) if ep_num in all_ep_nums else 0
    page = ep_index // EPISODES_PER_PAGE

    kb = episodes_kb(anime_id, ep_num, all_eps_list, page)

    caption = await build_episode_caption(anime_id, ep_num, anime_name, message.bot)

    sent = None
    try:
        sent = await message.answer_video(
            video=file_id, caption=caption, reply_markup=kb, parse_mode="HTML",
            protect_content=restricted
        )
    except Exception:
        try:
            sent = await message.answer_document(
                document=file_id, caption=caption, reply_markup=kb, parse_mode="HTML",
                protect_content=restricted
            )
        except Exception as e:
            await message.answer(f"❌ Qismni yuklashda xatolik: {e}")

    if sent:
        await save_episode_msg_id(anime_id, ep_num, sent.message_id, sent.chat.id)
        await set_watch_progress(current_user_id, anime_id, ep_num)
        # Oldingi qismdan kanal qatorini o'chirish
        if ep_num > 1:
            await update_prev_episode_caption(anime_id, ep_num - 1, anime_name, message.bot)


async def show_anime(message: Message, anime_id: int):
    user_id = message.from_user.id
    async with aiosqlite.connect(DB_PATH) as db:
        async with db.execute("SELECT * FROM animelar WHERE id=?", (anime_id,)) as cursor:
            anime = await cursor.fetchone()

    if not anime:
        await message.answer("❌ Ma'lumot topilmadi.")
        return

    async with aiosqlite.connect(DB_PATH) as db:
        new_views = (anime[8] or 0) + 1
        await db.execute("UPDATE animelar SET qidiruv=? WHERE id=?", (new_views, anime_id))
        await db.commit()

    async with aiosqlite.connect(DB_PATH) as db:
        async with db.execute("SELECT COUNT(*) FROM anime_datas WHERE id=?", (anime_id,)) as count_cs:
            qismlar_soni = (await count_cs.fetchone())[0]

    # anime ustunlari:
    # 0=id, 1=nom, 2=rams, 3=qismi, 4=davlat, 5=tili, 6=yili,
    # 7=janri, 8=qidiruv, 9=sana, 10=aniType, 11=fandub, 12=liklar, 13=desliklar
    # 14=kanal, 15=yosh_toifa

    from config import MAIN_CHANNEL_USERNAME
    nom      = anime[1]
    holat    = anime[10] if anime[10] else "OnGoing"
    yosh_toifa = (anime[15] if len(anime) > 15 and anime[15] else "Barcha yoshlar")
    janr     = anime[7] if anime[7] else "—"
    davlat   = anime[4] if anime[4] else "—"
    tili     = anime[5] if anime[5] else "—"
    yili     = anime[6] if anime[6] else "—"
    fandub   = anime[11] if anime[11] else "Ovoz berilmagan"
    likes    = anime[12] or 0
    dislikes = anime[13] or 0
    views    = anime[8] or 0
    kanal    = (anime[14] if len(anime) > 14 and anime[14] else None) or MAIN_CHANNEL_USERNAME or "—"
    tavsif   = anime[16] if len(anime) > 16 and anime[16] else ""

    if not tavsif:
        tavsif = await generate_anime_tavsif(
            nom=nom, janr=janr, holat=holat, qism=str(anime[3] or ""),
            yil=str(yili or ""), til=str(tili or ""), davlat=str(davlat or ""),
        )
        if not tavsif:
            tavsif = f"{nom} — {janr} janridagi anime. Qisqa qilib aytganda, tomoshabinni qiziqtiradigan syujetga ega."

        try:
            async with aiosqlite.connect(DB_PATH) as db:
                await db.execute("UPDATE animelar SET tavsif=? WHERE id=?", (tavsif, anime_id))
                await db.commit()
        except Exception:
            pass

    total_votes = likes + dislikes
    if total_votes > 0:
        rating = round((likes / total_votes) * 5, 1)
        rating_str = f"{rating} / 5"
    else:
        rating_str = "5 / 5"

    bot_username = await get_bot_username(message.bot)

    # Animated emoji — premium da animatsiyalanadi, boshqalarda oddiy ko'rinadi
    AE = '<tg-emoji emoji-id="5373123172420581514">🔥</tg-emoji>'

    # Oxirgi qism raqami
    async with aiosqlite.connect(DB_PATH) as db:
        async with db.execute(
            "SELECT qism FROM anime_datas WHERE id=? ORDER BY qism DESC LIMIT 1", (anime_id,)
        ) as c:
            last_ep_row = await c.fetchone()
        
        async with db.execute("SELECT value FROM bot_settings WHERE key='content_restriction'") as cursor:
            row = await cursor.fetchone()
            restricted = row[0] == "1" if row else False

    last_ep = last_ep_row[0] if last_ep_row else qismlar_soni
    in_watchlist, continue_ep = await get_watch_state(user_id, anime_id)
    if continue_ep > last_ep:
        continue_ep = last_ep
    season_buttons = await get_season_buttons(anime_id)

    caption = (
        f"{AE} <b>Anime nomi:</b> {nom}\n"
        f"╭────────────────\n"
        f"├‣  <b>Holati:</b> {holat}\n"
        f"├‣  <b>Qisimi:</b> {last_ep}-qisim\n"
        f"├‣  <b>Sifat:</b> 720p - 1080p\n"
        f"├‣  <b>Janrlari:</b> {janr}\n"
        f"├‣  <b>Kanal:</b> {kanal}\n"
        f"├‣  <b>Ovoz:</b> {fandub}\n"
        f"├‣  <b>Tavsif:</b> {html.escape(tavsif)}\n"
        f"├‣  <b>Yosh toifasi:</b> {yosh_toifa}\n"
        f"╰────────────────\n"
        f"{AE}  <b>Botimiz:</b> @{bot_username}\n"
        f"{AE}  <b>Anime ID:</b> {anime_id}\n"
        f"{AE}  <b>Reyting:</b> {rating_str}\n"
        f"{AE}  <b>Link:</b> https://t.me/{bot_username}?start={anime_id}"
    )

    # Web App URL olish
    async with aiosqlite.connect(DB_PATH) as db:
        async with db.execute("SELECT value FROM bot_settings WHERE key='web_app_url'") as c:
            wa_row = await c.fetchone()
    wa_base = (wa_row[0] if wa_row else "") or ""

    if wa_base:
        if not wa_base.startswith("https://"):
            wa_base = "https://" + wa_base.lstrip("http://").lstrip("https://")
        wa_params = urllib.parse.urlencode({
            "anime_id": anime_id,
            "total":    last_ep,
            "current":  (continue_ep if continue_ep > 0 else last_ep),
            "name":     nom,
            "holat":    holat,
            "janr":     janr,
            "yil":      yili,
            "fandub":   fandub,
            "kanal":    kanal,
            "banner":   anime[2] if anime[2] and anime[2].startswith("http") else "",
            "likes":    likes,
            "dislikes": dislikes,
            "bot":      bot_username,
        })
        full_wa_url = f"{wa_base}?{wa_params}"
        kb = download_kb(
            anime_id, likes, dislikes,
            web_app_url=full_wa_url,
            in_watchlist=in_watchlist,
            continue_ep=continue_ep,
            season_buttons=season_buttons
        )
    else:
        kb = download_kb(
            anime_id, likes, dislikes,
            in_watchlist=in_watchlist,
            continue_ep=continue_ep,
            season_buttons=season_buttons
        )

    try:
        await message.answer_photo(
            photo=anime[2], caption=caption,
            reply_markup=kb, parse_mode="HTML",
            protect_content=restricted
        )
    except:
        try:
            await message.answer_video(
                video=anime[2], caption=caption,
                reply_markup=kb, parse_mode="HTML",
                protect_content=restricted
            )
        except:
            await message.answer(caption, reply_markup=kb, parse_mode="HTML")


# ─── Anime izlash menyusi ──────────────────────────────────────────────────────

@router.message(F.text == "🔎 Anime izlash")
async def search_anime_menu(message: Message):
    if not await is_admin(message.from_user.id) and await is_maintenance():
        await message.answer(MAINTENANCE_MSG, parse_mode="HTML")
        return
    await message.answer(f"<b>{SEARCH} Qidiruv turini tanlang:</b>",
                         reply_markup=search_type_kb(), parse_mode="HTML")



async def send_search_guide(target, bot):
    """Qidiruv boshlanganda yo'riqnoma rasm + xabar yuboradi."""
    text = (
        "<b>Hurmatli obunachi</b>\n"
        "<i>Iltimos Anime qidirayotganda aniq, lotin harflarini ishlatgan holda "
        "qidirsangiz maqsadga muvofiq bo'lar edi!</i>\n\n"
        "<b>Masalan:</b> <code>Kung Fu Panda</code>\n\n"
        "⚠️ Agar Anime nomini aniq bilmasangiz — kanalimizning chat guruhidan so'rashingiz mumkin!"
    )
    async with aiosqlite.connect(DB_PATH) as db:
        async with db.execute(
            "SELECT value FROM bot_settings WHERE key='search_photo_id'"
        ) as c:
            row = await c.fetchone()
    photo_id = row[0] if row and row[0] else None

    try:
        if photo_id:
            await target.answer_photo(photo=photo_id, caption=text, parse_mode="HTML")
        else:
            await target.answer(text, parse_mode="HTML")
    except Exception:
        pass

@router.message(F.text == "🔎 Anime izlash")
async def search_anime_menu(message: Message):
    if not await is_admin(message.from_user.id) and await is_maintenance():
        await message.answer(MAINTENANCE_MSG, parse_mode="HTML")
        return
    await message.answer(f"<b>{SEARCH} Qidiruv turini tanlang:</b>",
                         reply_markup=search_type_kb(), parse_mode="HTML")



@router.callback_query(F.data == "searchByName")
async def search_by_name_prompt(callback: CallbackQuery, state: FSMContext):
    await send_search_guide(callback.message, callback.bot)
    await callback.message.answer("<b>🔎 Anime nomini yuboring:</b>", parse_mode="HTML")
    await state.set_state(UserStates.search_by_name)
    await callback.answer()


@router.message(UserStates.search_by_name)
async def process_search_by_name(message: Message, state: FSMContext):
    query = message.text
    async with aiosqlite.connect(DB_PATH) as db:
        async with db.execute(
            "SELECT * FROM animelar WHERE nom LIKE ? LIMIT 10", (f"%{query}%",)
        ) as cursor:
            results = await cursor.fetchall()

    await state.clear()

    if not results:
        await message.answer("<b>Hech narsa topilmadi 😔</b>", parse_mode="HTML")
        return

    buttons = [
        [InlineKeyboardButton(text=f"{i+1}. {a[1]}", callback_data=f"loadAnime={a[0]}")]
        for i, a in enumerate(results)
    ]
    await message.answer(
        "<b>⬇️ Qidiruv natijalari:</b>",
        reply_markup=InlineKeyboardMarkup(inline_keyboard=buttons), parse_mode="HTML"
    )


# ─── Kod orqali izlash ───────────────────────────────────────────────────────

@router.callback_query(F.data == "searchByCode")
async def search_by_code_prompt(callback: CallbackQuery, state: FSMContext):
    await send_search_guide(callback.message, callback.bot)
    await callback.message.answer("<b>🔢 Anime kodini yuboring:</b>", parse_mode="HTML")
    await state.set_state(UserStates.search_by_code)
    await callback.answer()


@router.message(UserStates.search_by_code)
async def process_search_by_code(message: Message, state: FSMContext):
    await state.clear()
    if not message.text.isdigit():
        await message.answer("❌ Raqam kiriting!")
        return
    await show_anime(message, int(message.text))


# ─── Janr orqali izlash ──────────────────────────────────────────────────────

@router.callback_query(F.data == "searchByGenre")
async def search_by_genre_prompt(callback: CallbackQuery, state: FSMContext):
    await send_search_guide(callback.message, callback.bot)
    await callback.message.answer(
        "<b>🎞 Janrni yuboring:</b>\n\n<i>Masalan: Drama, Fantastika, Romantika</i>",
        parse_mode="HTML"
    )
    await state.set_state(UserStates.search_by_genre)
    await callback.answer()


@router.message(UserStates.search_by_genre)
async def process_search_by_genre(message: Message, state: FSMContext):
    query = message.text
    async with aiosqlite.connect(DB_PATH) as db:
        async with db.execute(
            "SELECT * FROM animelar WHERE janri LIKE ? LIMIT 10", (f"%{query}%",)
        ) as cursor:
            results = await cursor.fetchall()

    await state.clear()

    if not results:
        await message.answer("<b>Bu janrda hech narsa topilmadi 😔</b>", parse_mode="HTML")
        return

    buttons = [
        [InlineKeyboardButton(text=f"{i+1}. {a[1]}", callback_data=f"loadAnime={a[0]}")]
        for i, a in enumerate(results)
    ]
    await message.answer(
        f"<b>🎞 «{query}» janridagi animelar:</b>",
        reply_markup=InlineKeyboardMarkup(inline_keyboard=buttons), parse_mode="HTML"
    )


# ─── So'nggi yuklanganlar ────────────────────────────────────────────────────

@router.callback_query(F.data == "lastUploads")
async def last_uploads_callback(callback: CallbackQuery):
    async with aiosqlite.connect(DB_PATH) as db:
        async with db.execute(
            "SELECT id, nom FROM animelar ORDER BY id DESC LIMIT 10"
        ) as cursor:
            results = await cursor.fetchall()

    if not results:
        await callback.answer("Hozircha anime yo'q!", show_alert=True)
        return

    buttons = [
        [InlineKeyboardButton(text=f"{i+1}. {a[1]}", callback_data=f"loadAnime={a[0]}")]
        for i, a in enumerate(results)
    ]
    await callback.message.answer(
        "<b>⏱ So'nggi yuklangan animelar:</b>",
        reply_markup=InlineKeyboardMarkup(inline_keyboard=buttons), parse_mode="HTML"
    )
    await callback.answer()


# ─── Eng ko'p ko'rilgan ──────────────────────────────────────────────────────

@router.callback_query(F.data == "topViewers")
async def top_viewers_callback(callback: CallbackQuery):
    async with aiosqlite.connect(DB_PATH) as db:
        async with db.execute(
            "SELECT id, nom, qidiruv FROM animelar ORDER BY qidiruv DESC LIMIT 10"
        ) as cursor:
            results = await cursor.fetchall()

    if not results:
        await callback.answer("Hozircha anime yo'q!", show_alert=True)
        return

    buttons = [
        [InlineKeyboardButton(
            text=f"{i+1}. {a[1]} 👁{a[2]}", callback_data=f"loadAnime={a[0]}"
        )]
        for i, a in enumerate(results)
    ]
    await callback.message.answer(
        "<b>👁️ Eng ko'p ko'rilgan animelar:</b>",
        reply_markup=InlineKeyboardMarkup(inline_keyboard=buttons), parse_mode="HTML"
    )
    await callback.answer()


# ─── Barcha animelar ────────────────────────────────────────────────────────

@router.callback_query(F.data == "allAnimes")
async def all_animes_callback(callback: CallbackQuery):
    async with aiosqlite.connect(DB_PATH) as db:
        async with db.execute(
            "SELECT id, nom FROM animelar ORDER BY nom ASC LIMIT 20"
        ) as cursor:
            results = await cursor.fetchall()

    if not results:
        await callback.answer("Hozircha anime yo'q!", show_alert=True)
        return

    buttons = [
        [InlineKeyboardButton(text=f"📺 {a[1]}", callback_data=f"loadAnime={a[0]}")]
        for a in results
    ]
    await callback.message.answer(
        "<b>📚 Barcha animelar (alifbo tartibida):</b>",
        reply_markup=InlineKeyboardMarkup(inline_keyboard=buttons), parse_mode="HTML"
    )
    await callback.answer()


# ─── Yosh toifasi bo'yicha qidirish ─────────────────────────────────────────

@router.callback_query(F.data == "searchByAge")
async def search_by_age_callback(callback: CallbackQuery):
    await callback.message.answer(
        "<b>🔞 Yosh toifasini tanlang:</b>\n\n"
        "<i>Qaysi yoshga mo'ljallangan animelarni ko'rishni xohlaysiz?</i>",
        reply_markup=search_by_age_kb(), parse_mode="HTML"
    )
    await callback.answer()


@router.callback_query(F.data.startswith("ageAnimes="))
async def age_animes_callback(callback: CallbackQuery):
    yosh = callback.data.split("=")[1]

    # Yosh toifasi tartibi — kichikdan kattaga
    YOSH_TARTIB = ["0+", "7+", "13+", "16+", "18+"]

    # Tanlangan yoshdan PAST yoki TENG bo'lgan barcha toifalar ko'rsatiladi
    # Masalan: 16+ tanlansa => 0+, 7+, 13+, 16+ animelar chiqadi (18+ chiqmaydi)
    if yosh in YOSH_TARTIB:
        chegara = YOSH_TARTIB.index(yosh)
        ruxsat_etilgan = YOSH_TARTIB[:chegara + 1]
    else:
        ruxsat_etilgan = [yosh]

    # Tanlangan yosh toifasining nomini topish
    yosh_nom = yosh
    for text, code in YOSH_TOIFALAR:
        if code == yosh:
            yosh_nom = text
            break

    placeholders = ",".join("?" * len(ruxsat_etilgan))
    async with aiosqlite.connect(DB_PATH) as db:
        async with db.execute(
            f"SELECT id, nom, yosh_toifa FROM animelar WHERE yosh_toifa IN ({placeholders}) ORDER BY id DESC LIMIT 30",
            ruxsat_etilgan
        ) as cursor:
            results = await cursor.fetchall()

    if not results:
        await callback.answer(f"Bu toifada hali anime yo'q!", show_alert=True)
        return

    # Yosh belgisi qo'shish
    YOSH_EMOJI = {"0+": "👶", "7+": "🧒", "13+": "👦", "16+": "🧑", "18+": "🔞"}
    buttons = [
        [InlineKeyboardButton(
            text=f"{YOSH_EMOJI.get(a[2], '📺')} {a[1]} [{a[2]}]",
            callback_data=f"loadAnime={a[0]}"
        )]
        for a in results
    ]
    await callback.message.answer(
        f"<b>{yosh_nom} uchun animelar:</b>\n"
        f"<i>({', '.join(ruxsat_etilgan)} toifalar — {len(results)} ta anime)</i>",
        reply_markup=InlineKeyboardMarkup(inline_keyboard=buttons), parse_mode="HTML"
    )
    await callback.answer()


@router.callback_query(F.data == "back_to_search")
async def back_to_search_callback(callback: CallbackQuery):
    from keyboards import search_type_kb
    await callback.message.answer(
        "<b>🔎 Qidirish turini tanlang:</b>",
        reply_markup=search_type_kb(), parse_mode="HTML"
    )
    await callback.answer()


# ─── Anime yuklash (callback) ────────────────────────────────────────────────

@router.callback_query(F.data.startswith("loadAnime="))
async def load_anime_callback(callback: CallbackQuery):
    if not await is_admin(callback.from_user.id) and await is_maintenance():
        await callback.answer("⚠️ Bot tamirlanyapti, kuting...", show_alert=True)
        return
    parts = callback.data.split("=")
    anime_id = int(parts[1])
    try:
        await callback.message.delete()
    except:
        pass
    await show_anime(callback.message, anime_id)
    await callback.answer()


# ─── Qism yuklash ───────────────────────────────────────────────────────────

@router.callback_query(F.data.startswith("yuklanolish="))
async def episode_list_callback(callback: CallbackQuery):
    if not await is_admin(callback.from_user.id) and await is_maintenance():
        await callback.answer("⚠️ Bot tamirlanyapti, kuting...", show_alert=True)
        return
    parts = callback.data.split("=")
    anime_id = int(parts[1])
    ep_num = int(parts[2]) if len(parts) > 2 else 1

    async with aiosqlite.connect(DB_PATH) as db:
        async with db.execute(
            "SELECT * FROM anime_datas WHERE id=? AND qism=?", (anime_id, ep_num)
        ) as cursor:
            episode_data = await cursor.fetchone()

        async with db.execute("SELECT nom FROM animelar WHERE id=?", (anime_id,)) as cursor:
            anime_name = await cursor.fetchone()
            anime_name = anime_name[0] if anime_name else "Unknown"

        async with db.execute(
            "SELECT qism FROM anime_datas WHERE id=? ORDER BY qism ASC", (anime_id,)
        ) as cursor:
            all_eps = await cursor.fetchall()
            all_eps_list = [{'qism': row[0]} for row in all_eps]

        async with db.execute("SELECT value FROM bot_settings WHERE key='content_restriction'") as cursor:
            row = await cursor.fetchone()
            restricted = row[0] == "1" if row else False

    if not episode_data:
        await callback.answer("❌ Qism topilmadi", show_alert=True)
        return

    file_id = episode_data[2]

    # Qaysi sahifada ekanini avtomatik hisoblash
    from keyboards import EPISODES_PER_PAGE
    all_ep_nums = [int(e['qism']) for e in all_eps_list]
    ep_index = all_ep_nums.index(ep_num) if ep_num in all_ep_nums else 0
    page = ep_index // EPISODES_PER_PAGE

    # Agar bu sahifaning OXIRGI qismi bo'lsa va keyingi sahifa bo'lsa — keyingi sahifaga o't
    total_pages = max(1, (len(all_ep_nums) + EPISODES_PER_PAGE - 1) // EPISODES_PER_PAGE)
    page_last_index = (page + 1) * EPISODES_PER_PAGE - 1
    if ep_index == min(page_last_index, len(all_ep_nums) - 1) and page < total_pages - 1:
        page = page + 1

    kb = episodes_kb(anime_id, ep_num, all_eps_list, page)

    try:
        await callback.message.edit_reply_markup(reply_markup=None)
    except Exception:
        pass

    caption = await build_episode_caption(anime_id, ep_num, anime_name, callback.bot)

    sent = None
    try:
        sent = await callback.message.answer_video(
            video=file_id, caption=caption, reply_markup=kb, parse_mode="HTML",
            protect_content=restricted
        )
    except Exception:
        try:
            sent = await callback.message.answer_document(
                document=file_id, caption=caption, reply_markup=kb, parse_mode="HTML",
                protect_content=restricted
            )
        except Exception as e:
            await callback.answer(f"Xatolik: {e}", show_alert=True)

    if sent:
        await save_episode_msg_id(anime_id, ep_num, sent.message_id, sent.chat.id)
        await set_watch_progress(callback.from_user.id, anime_id, ep_num)
        # Oldingi qismdan kanal qatorini o'chirish
        if ep_num > 1:
            await update_prev_episode_caption(anime_id, ep_num - 1, anime_name, callback.bot)


# ─── Qismlar sahifalash (pagination tugmalari) ────────────────────────────────

@router.callback_query(F.data.startswith("ep_page="))
async def ep_page_callback(callback: CallbackQuery):
    parts = callback.data.split("=")
    anime_id = int(parts[1])
    page = int(parts[2])
    current_ep = int(parts[3])

    async with aiosqlite.connect(DB_PATH) as db:
        async with db.execute(
            "SELECT qism FROM anime_datas WHERE id=? ORDER BY qism ASC", (anime_id,)
        ) as cursor:
            all_eps = await cursor.fetchall()
            all_eps_list = [{'qism': row[0]} for row in all_eps]

    kb = episodes_kb(anime_id, current_ep, all_eps_list, page)
    try:
        await callback.message.edit_reply_markup(reply_markup=kb)
    except Exception:
        pass
    await callback.answer()





# ─── Menyu tugmalari ─────────────────────────────────────────────────────────

@router.message(F.text == "📌 Watchlist")
async def watchlist_menu(message: Message):
    if not await is_admin(message.from_user.id) and await is_maintenance():
        await message.answer(MAINTENANCE_MSG, parse_mode="HTML")
        return

    rows = await get_watchlist_items(message.from_user.id)
    if not rows:
        await message.answer(
            "📌 Watchlist bo'sh.\n\nAnime kartasidagi <b>«Watchlistga saqlash»</b> tugmasi orqali qo'shing.",
            parse_mode="HTML"
        )
        return

    buttons = []
    for anime_id, nom, last_ep in rows:
        suffix = f" (davom: {last_ep}-qism)" if last_ep else ""
        buttons.append([
            InlineKeyboardButton(text=f"🎬 {nom}{suffix}", callback_data=f"loadAnime={anime_id}")
        ])

    await message.answer(
        "<b>📌 Sizning watchlist'ingiz:</b>",
        reply_markup=InlineKeyboardMarkup(inline_keyboard=buttons),
        parse_mode="HTML"
    )


@router.message(F.text == "▶️ Davom etish")
async def continue_watching_menu(message: Message):
    if not await is_admin(message.from_user.id) and await is_maintenance():
        await message.answer(MAINTENANCE_MSG, parse_mode="HTML")
        return

    async with aiosqlite.connect(DB_PATH) as db:
        async with db.execute(
            """
            SELECT wp.anime_id, wp.last_episode, a.nom
            FROM watch_progress wp
            JOIN animelar a ON a.id = wp.anime_id
            WHERE wp.user_id=?
            ORDER BY wp.updated_at DESC
            LIMIT 1
            """,
            (message.from_user.id,)
        ) as c:
            row = await c.fetchone()

    if not row:
        await message.answer("▶️ Davom etish uchun hali tarix yo'q. Avval biror qismni oching.")
        return

    anime_id, last_episode, anime_name = row
    ep_to_open = last_episode if (last_episode and last_episode > 0) else 1
    await message.answer(
        f"▶️ <b>{anime_name}</b> davom ettirilmoqda...\n<i>{ep_to_open}-qism ochildi.</i>",
        parse_mode="HTML"
    )
    await show_episode_direct(message, anime_id, ep_to_open)


@router.message(F.text == "🔥 Trendlar")
async def trends_menu(message: Message):
    if not await is_admin(message.from_user.id) and await is_maintenance():
        await message.answer(MAINTENANCE_MSG, parse_mode="HTML")
        return

    async with aiosqlite.connect(DB_PATH) as db:
        async with db.execute(
            """
            SELECT id, nom, COALESCE(qidiruv,0) AS views, COALESCE(liklar,0) AS likes
            FROM animelar
            ORDER BY views DESC, likes DESC
            LIMIT 10
            """
        ) as c:
            rows = await c.fetchall()

    if not rows:
        await message.answer("🔥 Hozircha trend uchun ma'lumot yo'q.")
        return

    buttons = []
    for idx, (anime_id, nom, views, likes) in enumerate(rows, start=1):
        buttons.append([
            InlineKeyboardButton(
                text=f"{idx}. {nom} 👁{views} 👍{likes}",
                callback_data=f"loadAnime={anime_id}"
            )
        ])

    await message.answer(
        "<b>🔥 Haftaning trend animelari:</b>",
        reply_markup=InlineKeyboardMarkup(inline_keyboard=buttons),
        parse_mode="HTML"
    )


@router.message(F.text == "🎯 Tavsiyalar")
async def recommendations_menu(message: Message):
    if not await is_admin(message.from_user.id) and await is_maintenance():
        await message.answer(MAINTENANCE_MSG, parse_mode="HTML")
        return

    user_id = message.from_user.id
    async with aiosqlite.connect(DB_PATH) as db:
        async with db.execute(
            """
            SELECT a.id, a.janri
            FROM watch_progress wp
            JOIN animelar a ON a.id = wp.anime_id
            WHERE wp.user_id=?
            ORDER BY wp.updated_at DESC
            LIMIT 1
            """,
            (user_id,)
        ) as c:
            last = await c.fetchone()

        if not last:
            async with db.execute(
                """
                SELECT id, nom, COALESCE(qidiruv,0) AS views
                FROM animelar
                ORDER BY views DESC
                LIMIT 10
                """
            ) as c:
                fallback = await c.fetchall()
            if not fallback:
                await message.answer("🎯 Tavsiyalar hozircha mavjud emas.")
                return
            buttons = [[InlineKeyboardButton(text=f"🎬 {r[1]} 👁{r[2]}", callback_data=f"loadAnime={r[0]}")] for r in fallback]
            await message.answer(
                "<b>🎯 Siz uchun tavsiyalar (trend asosida):</b>",
                reply_markup=InlineKeyboardMarkup(inline_keyboard=buttons),
                parse_mode="HTML"
            )
            return

        last_anime_id, genres = last
        genres = genres or ""
        primary_genre = genres.split(",")[0].strip() if genres else ""

        if primary_genre:
            async with db.execute(
                """
                SELECT id, nom, COALESCE(qidiruv,0) AS views
                FROM animelar
                WHERE id != ? AND janri LIKE ?
                ORDER BY views DESC
                LIMIT 10
                """,
                (last_anime_id, f"%{primary_genre}%")
            ) as c:
                recs = await c.fetchall()
        else:
            recs = []

        if not recs:
            async with db.execute(
                """
                SELECT id, nom, COALESCE(qidiruv,0) AS views
                FROM animelar
                WHERE id != ?
                ORDER BY views DESC
                LIMIT 10
                """,
                (last_anime_id,)
            ) as c:
                recs = await c.fetchall()

    buttons = [[InlineKeyboardButton(text=f"🎬 {r[1]} 👁{r[2]}", callback_data=f"loadAnime={r[0]}")] for r in recs]
    if not buttons:
        await message.answer("🎯 Tavsiyalar hozircha mavjud emas.")
        return
    title = "<b>🎯 Sizga mos tavsiyalar:</b>"
    if primary_genre:
        title += f"\n<i>Asosiy janr: {primary_genre}</i>"
    await message.answer(
        title,
        reply_markup=InlineKeyboardMarkup(inline_keyboard=buttons),
        parse_mode="HTML"
    )


@router.message(F.text == "💎 VIP")
async def vip_menu(message: Message):
    user_id = message.from_user.id
    
    # Hozirgi VIP holati va narxni o'qish
    async with aiosqlite.connect(DB_PATH) as db:
        async with db.execute("SELECT kun, date FROM vip_status WHERE user_id=?", (user_id,)) as c:
            vip_info = await c.fetchone()
        
        # VIP narxini o'qish
        async with db.execute("SELECT value FROM bot_settings WHERE key='vip_price'") as c:
            price_row = await c.fetchone()
        async with db.execute("SELECT value FROM bot_settings WHERE key='vip_currency'") as c:
            currency_row = await c.fetchone()
    
    vip_price = int(price_row[0]) if price_row else 5000
    vip_currency = currency_row[0] if currency_row else "so'm"
    
    text = (
        f"<b>{DIAMOND} VIP a'zolik imtiyozlari:</b>\n\n"
        f"{CHECK} Barcha animelarga cheksiz kirish\n"
        f"{CHECK} Reklama ko'rsatilmaydi\n"
        f"{CHECK} Yangi epizodlar birinchi bo'lib keladi\n\n"
    )
    
    if vip_info:
        text += f"<b>{CROWN} Siz VIP a'zo!</b>\n"
        text += f"📅 Tugash vaqti: <b>{vip_info[1]}</b> ({vip_info[0]} kun qoldi)"
        keyboard = vip_plans_kb(vip_price, vip_currency)
    else:
        text += f"<b>💰 VIP Paketlari:</b>\n"
        keyboard = vip_plans_kb(vip_price, vip_currency)
    
    await message.answer(text, reply_markup=keyboard, parse_mode="HTML")


# ─── Hisobim (kengaytirilgan) ──────────────────────────────────────────────────────────────

@router.message(F.text == "💰 Hisobim")
async def my_balance(message: Message):
    user_id = message.from_user.id
    async with aiosqlite.connect(DB_PATH) as db:
        async with db.execute("SELECT pul, pul2, odam, status FROM users WHERE user_id=?", (user_id,)) as cursor:
            user = await cursor.fetchone()
        async with db.execute("SELECT kun, date FROM vip_status WHERE user_id=?", (user_id,)) as c:
            vip = await c.fetchone()

    if not user:
        await message.answer("❌ Siz ro'yxatdan o'tmagansiz. /start ni bosing.")
        return

    ref_link = f"https://t.me/{await get_bot_username(message.bot)}?start={user_id}"
    vip_line = f"\n💎 VIP: <b>{vip[1]} dan {vip[0]} kun</b>" if vip else ""

    text = (
        f"<b>{MONEY} Mening hisobim</b>\n\n"
        f"🆔 ID: <code>{user_id}</code>\n"
        f"👤 Status: <b>{user[3]}</b>{vip_line}\n"
        f"💵 Balans: <b>{user[0]}</b> so'm\n"
        f"{GIFT} Bonus: <b>{user[1]}</b> so'm\n"
        f"👥 Taklif qilinganlar: <b>{user[2]}</b> kishi\n\n"
        f"🔗 Referal link:\n<code>{ref_link}</code>"
    )
    await message.answer(text, parse_mode="HTML")


# ─── Pul kiritish (to'lov tizimi) ───────────────────────────────────────────────

@router.message(F.text == "➕ Pul kiritish")
async def deposit_menu(message: Message, state: FSMContext):
    async with aiosqlite.connect(DB_PATH) as db:
        async with db.execute("SELECT value FROM bot_texts WHERE key='wallet'") as cursor:
            row = await cursor.fetchone()
            wallet_text = row[0] if row else "Hali hamyon o'rnatilmagan."

    await message.answer(
        f"<b>➕ Hisobni to'ldirish</b>\n\n"
        f"To'lov uchun hamyon:\n<code>{wallet_text}</code>\n\n"
        f"<i>Qancha pul kiritmoqchisiz? (raqam kiriting):</i>",
        parse_mode="HTML"
    )
    await state.set_state(PaymentStates.enter_amount)


@router.message(PaymentStates.enter_amount, F.text)
async def deposit_enter_amount(message: Message, state: FSMContext):
    if not message.text.isdigit() or int(message.text) < 1000:
        await message.answer("❌ Kamida 1000 so'm kiriting! Faqat raqam yozing.")
        return
    await state.update_data(deposit_amount=int(message.text))
    await message.answer(
        f"📸 Endi to'lov chekini (screenshot yoki kvitansiya) yuboring:",
        parse_mode="HTML"
    )
    await state.set_state(PaymentStates.send_check)


@router.message(PaymentStates.send_check, F.photo | F.document)
async def deposit_check_received(message: Message, state: FSMContext, bot: Bot):
    data  = await state.get_data()
    user_id = message.from_user.id
    amount  = data.get('deposit_amount', 0)
    file_id = message.photo[-1].file_id if message.photo else message.document.file_id

    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute(
            "INSERT INTO payments (user_id, amount, purpose, status, check_file_id) VALUES (?,?,?,?,?)",
            (user_id, amount, "balance", "pending", file_id)
        )
        await db.commit()
        async with db.execute("SELECT last_insert_rowid()") as c:
            pay_id = (await c.fetchone())[0]

    await message.answer("✅ Chek qabul qilindi! Admin tez orada tasdiqlaydi.")

    notify_ids = list(ADMIN_IDS) + [SUPER_ADMIN_ID]
    for admin_id in set(notify_ids):
        try:
            caption_text = (
                f"💳 <b>Balans to'ldirilishi</b>\n\n"
                f"👤 User: <code>{user_id}</code>\n"
                f"💰 Summa: <b>{amount} so'm</b>\n"
                f"🆔 To'lov ID: #{pay_id}"
            )
            if message.photo:
                await bot.send_photo(
                    admin_id, 
                    file_id,
                    caption=caption_text,
                    reply_markup=payment_confirm_kb(pay_id),
                    parse_mode="HTML"
                )
            else:
                await bot.send_document(
                    admin_id,
                    file_id,
                    caption=caption_text,
                    reply_markup=payment_confirm_kb(pay_id),
                    parse_mode="HTML"
                )
        except Exception as e:
            print(f"Send payment notification error: {e}")
    
    await state.clear()



# ─── Referal tizimi ────────────────────────────────────────────────────────────────

@router.message(F.text == "👥 Referal")
async def referal_menu(message: Message, bot: Bot):
    user_id  = message.from_user.id
    ref_link = f"https://t.me/{await get_bot_username(bot)}?start={user_id}"

    async with aiosqlite.connect(DB_PATH) as db:
        async with db.execute("SELECT odam, pul2 FROM users WHERE user_id=?", (user_id,)) as c:
            row = await c.fetchone()
        async with db.execute("SELECT value FROM bot_settings WHERE key='referral_bonus'") as c:
            bonus_row = await c.fetchone()

    invited = row[0] if row else 0
    earned  = row[1] if row else 0
    bonus   = bonus_row[0] if bonus_row else 500

    text = (
        f"<b>👥 Referal tizimi</b>\n\n"
        f"{GIFT} Har bir do'stingiz uchun <b>{bonus} so'm</b> bonus olasiz!\n\n"
        f"👥 Taklif qilganlaringiz: <b>{invited}</b> kishi\n"
        f"{MONEY} Jami ishlab topgan: <b>{earned}</b> so'm\n\n"
        f"🔗 Sizning referal havolangiz:\n"
        f"<code>{ref_link}</code>"
    )
    await message.answer(text, parse_mode="HTML")




# ─── Pul o'tkazmasi ──────────────────────────────────────────────────────────

@router.message(F.text == "💸 Pul o'tkazmasi")
async def transfer_menu(message: Message, state: FSMContext):
    """Pul o'tkazmasi menusi"""
    user_id = message.from_user.id
    
    async with aiosqlite.connect(DB_PATH) as db:
        async with db.execute("SELECT pul, pul2 FROM users WHERE user_id=?", (user_id,)) as c:
            user_data = await c.fetchone()
    
    if not user_data:
        await message.answer("❌ Foydalanuvchi topilmadi!")
        return
    
    main_balance = user_data[0]
    bonus_balance = user_data[1]
    total = main_balance + bonus_balance
    
    text = (
        f"<b>💸 Pul o'tkazmasi</b>\n\n"
        f"💰 Asosiy balans: <b>{main_balance}</b> so'm\n"
        f"🎁 Bonus balans: <b>{bonus_balance}</b> so'm\n"
        f"📊 Jami: <b>{total}</b> so'm\n\n"
        f"<i>Otkazmoqchi bo'lgan foydalanuvchining ID sini yuboring:</i>"
    )
    
    await message.answer(text, parse_mode="HTML")
    await state.set_state(TransferStates.enter_user_id)


@router.message(TransferStates.enter_user_id)
async def transfer_enter_recipient(message: Message, state: FSMContext):
    """Pul qabul qiluvchining ID'sini o'qish"""
    recipient_id_text = message.text.strip()
    
    if not recipient_id_text.isdigit():
        await message.answer("❌ Faqat raqam yuboring! Misol: 123456789")
        return
    
    recipient_id = int(recipient_id_text)
    sender_id = message.from_user.id
    
    # Oʻziga pul otkazmaslik
    if recipient_id == sender_id:
        await message.answer("❌ Oʻzingizga pul otkazolmasiz!")
        return
    
    # Qabul qiluvchi mavjud bo'lsami
    async with aiosqlite.connect(DB_PATH) as db:
        async with db.execute("SELECT 1 FROM users WHERE user_id=?", (recipient_id,)) as c:
            exists = await c.fetchone()
    
    if not exists:
        await message.answer(f"❌ User ID {recipient_id} topilmadi!")
        return
    
    await state.update_data(recipient_id=recipient_id)
    await message.answer(
        f"✅ Qabul qiluvchi: <code>{recipient_id}</code>\n\n"
        f"<i>Qancha pul o'tkazmoqchisiz? (raqam yuboring, kamida 1000 so'm):</i>",
        parse_mode="HTML"
    )
    await state.set_state(TransferStates.enter_amount)


@router.message(TransferStates.enter_amount)
async def transfer_enter_amount(message: Message, state: FSMContext):
    """Oʻtkazmoqchi boʻlgan miqdorni oʻqish"""
    if not message.text.isdigit():
        await message.answer("❌ Faqat raqam yuboring!")
        return
    
    amount = int(message.text)
    
    if amount < 1000:
        await message.answer("❌ Kamida 1000 so'm o'tkazishi kerak!")
        return
    
    sender_id = message.from_user.id
    data = await state.get_data()
    recipient_id = data.get("recipient_id")
    
    # Balansni tekshirish
    async with aiosqlite.connect(DB_PATH) as db:
        async with db.execute("SELECT pul FROM users WHERE user_id=?", (sender_id,)) as c:
            user_balance = (await c.fetchone())[0]
    
    if user_balance < amount:
        await message.answer(
            f"❌ Yetarli balansingiz yo'q!\n"
            f"Sizda: {user_balance} so'm\n"
            f"Talab: {amount} so'm",
            parse_mode="HTML"
        )
        return
    
    # Confirmation
    await state.update_data(amount=amount)
    text = (
        f"<b>💸 Tasdiqlash</b>\n\n"
        f"📤 O'tkaza qatnashchi: <code>{recipient_id}</code>\n"
        f"💰 Miqdori: <b>{amount}</b> so'm\n\n"
        f"<b>✅ Tasdiqlaysizmi? (ha/yo'q):</b>"
    )
    await message.answer(text, parse_mode="HTML", reply_markup=InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text="✅ Ha", callback_data="transfer_confirm_yes")],
            [InlineKeyboardButton(text="❌ Yo'q", callback_data="transfer_confirm_no")]
        ]
    ))


@router.callback_query(F.data == "transfer_confirm_yes")
async def transfer_confirm(callback: CallbackQuery, state: FSMContext, bot: Bot):
    """Pul o'tkazmani amalga oshirish"""
    sender_id = callback.from_user.id
    data = await state.get_data()
    recipient_id = data.get("recipient_id")
    amount = data.get("amount")
    
    async with aiosqlite.connect(DB_PATH) as db:
        # Pul o'tkazish (double check balans)
        async with db.execute("SELECT pul FROM users WHERE user_id=?", (sender_id,)) as c:
            sender_balance = (await c.fetchone())[0]
        
        if sender_balance < amount:
            await callback.answer("❌ Yetarli balansingiz yo'q!", show_alert=True)
            await state.clear()
            return
        
        # O'tkazish
        await db.execute("UPDATE users SET pul=pul-? WHERE user_id=?", (amount, sender_id))
        await db.execute("UPDATE users SET pul=pul+? WHERE user_id=?", (amount, recipient_id))
        await db.commit()
    
    # Log transfer
    log_admin_action(
        "money_transfer",
        sender_id,
        callback.from_user.username or f"ID: {sender_id}",
        details=f"Oluvchi: {recipient_id}, Miqdor: {amount} so'm"
    )
    
    # Sender'ga xat
    await callback.message.edit_text(
        f"✅ <b>Pul o'tkazildi!</b>\n\n"
        f"📤 O'tkazildi: <code>{recipient_id}</code> ga\n"
        f"💰 Miqdor: <b>{amount}</b> so'm",
        parse_mode="HTML"
    )
    
    # Recipient'ga xat
    try:
        await bot.send_message(
            recipient_id,
            f"💰 <b>Pul qabul qildingiz!</b>\n\n"
            f"📥 Yuboruvchi: <code>{sender_id}</code>\n"
            f"💵 Miqdor: <b>{amount}</b> so'm",
            parse_mode="HTML"
        )
    except:
        pass
    
    await state.clear()
    await callback.answer("✅ O'tkaza muvaffaqiyatli!")


@router.callback_query(F.data == "transfer_confirm_no")
async def transfer_cancel(callback: CallbackQuery, state: FSMContext):
    """Pul o'tkazmani bekor qilish"""
    await state.clear()
    await callback.message.edit_text("❌ O'tkaza bekor qilindi.")
    await callback.answer()


# ─── Cashback ────────────────────────────────────────────────────────────────────

@router.message(F.text == "🎁 Cashback")
async def cashback_menu(message: Message):
    user_id = message.from_user.id
    async with aiosqlite.connect(DB_PATH) as db:
        async with db.execute("SELECT pul2 FROM users WHERE user_id=?", (user_id,)) as c:
            row = await c.fetchone()
        async with db.execute("SELECT value FROM bot_settings WHERE key='cashback_percent'") as c:
            pct_row = await c.fetchone()

    bonus  = row[0] if row else 0
    pct    = pct_row[0] if pct_row else 5

    text = (
        f"<b>{GIFT} Cashback tizimi</b>\n\n"
        f"{FIRE} Har bir to'lovdan <b>{pct}%</b> cashback olasiz!\n"
        f"Cashback bonus sifatida hisoblanadi.\n\n"
        f"{MONEY} Sizning cashback balansiz: <b>{bonus}</b> so'm"
    )
    await message.answer(text, parse_mode="HTML")


@router.message(F.text == "📚 Qo'llanma")
async def guide_menu(message: Message):
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(
            text="📖 Qo'llanmani ochish",
            web_app=WebAppInfo(url="https://animeuz.up.railway.app/qollanma")
        )]
    ])
    await message.answer(
        "<b>📚 Qo'llanma</b>\n\n"
        "Botdan to'liq foydalanish bo'yicha qo'llanma <b>Web sahifa</b> sifatida tayyorlangan.\n\n"
        "👇 Tugmani bosib Telegram ichida oching:",
        reply_markup=kb,
        parse_mode="HTML"
    )


@router.message(F.text == "💵 Reklama va Homiylik")
async def ads_menu(message: Message):
    async with aiosqlite.connect(DB_PATH) as db:
        async with db.execute("SELECT value FROM bot_texts WHERE key='ads'") as cursor:
            row = await cursor.fetchone()
            ads_text = row[0] if row else "💵 Reklama matni hali kiritilmagan."

    await message.answer(f"<b>💵 Reklama</b>\n\n{ads_text}", parse_mode="HTML")



# ─── Like / Dislike callbacklar ──────────────────────────────────────────────

@router.callback_query(F.data.startswith("like="))
async def like_callback(callback: CallbackQuery):
    parts = callback.data.split("=")
    anime_id = int(parts[1])
    user_id = callback.from_user.id
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute("UPDATE animelar SET liklar=liklar+1 WHERE id=?", (anime_id,))
        await db.commit()
        async with db.execute("SELECT liklar, desliklar FROM animelar WHERE id=?", (anime_id,)) as c:
            row = await c.fetchone()
    likes, dislikes = row[0] or 0, row[1] or 0
    in_watchlist, continue_ep = await get_watch_state(user_id, anime_id)
    wa_url = extract_webapp_url(callback.message.reply_markup)
    try:
        await callback.message.edit_reply_markup(
            reply_markup=download_kb(
                anime_id, likes, dislikes,
                web_app_url=wa_url,
                in_watchlist=in_watchlist,
                continue_ep=continue_ep
            )
        )
    except:
        pass
    await _push("like", f"Anime #{anime_id} — like bosildi", "p")
    await callback.answer("👍 Like qo'shildi!")


@router.callback_query(F.data.startswith("dislike="))
async def dislike_callback(callback: CallbackQuery):
    parts = callback.data.split("=")
    anime_id = int(parts[1])
    user_id = callback.from_user.id
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute("UPDATE animelar SET desliklar=desliklar+1 WHERE id=?", (anime_id,))
        await db.commit()
        async with db.execute("SELECT liklar, desliklar FROM animelar WHERE id=?", (anime_id,)) as c:
            row = await c.fetchone()
    likes, dislikes = row[0] or 0, row[1] or 0
    in_watchlist, continue_ep = await get_watch_state(user_id, anime_id)
    wa_url = extract_webapp_url(callback.message.reply_markup)
    try:
        await callback.message.edit_reply_markup(
            reply_markup=download_kb(
                anime_id, likes, dislikes,
                web_app_url=wa_url,
                in_watchlist=in_watchlist,
                continue_ep=continue_ep
            )
        )
    except:
        pass
    await callback.answer("👎 Dislike qo'shildi!")


@router.callback_query(F.data.startswith("share="))
async def share_callback(callback: CallbackQuery):
    anime_id = int(callback.data.split("=")[1])
    bot_username = await get_bot_username(callback.bot)
    link = f"https://t.me/{bot_username}?start={anime_id}"
    await callback.answer(f"🔗 Link: {link}", show_alert=True)


@router.callback_query(F.data.startswith("rate="))
async def rate_callback(callback: CallbackQuery):
    await callback.answer("👍 yoki 👎 tugmasini bosing!", show_alert=True)


@router.callback_query(F.data.startswith("watchlist_toggle="))
async def watchlist_toggle_callback(callback: CallbackQuery):
    anime_id = int(callback.data.split("=")[1])
    user_id = callback.from_user.id

    async with aiosqlite.connect(DB_PATH) as db:
        async with db.execute(
            "SELECT 1 FROM watchlist WHERE user_id=? AND anime_id=?",
            (user_id, anime_id)
        ) as c:
            exists = await c.fetchone()

        if exists:
            await db.execute(
                "DELETE FROM watchlist WHERE user_id=? AND anime_id=?",
                (user_id, anime_id)
            )
            message_text = "📌 Watchlistdan olib tashlandi"
        else:
            await db.execute(
                "INSERT OR IGNORE INTO watchlist (user_id, anime_id) VALUES (?, ?)",
                (user_id, anime_id)
            )
            message_text = "✅ Watchlistga qo'shildi"
        await db.commit()

        async with db.execute("SELECT liklar, desliklar FROM animelar WHERE id=?", (anime_id,)) as c:
            row = await c.fetchone()

    likes, dislikes = (row[0] or 0, row[1] or 0) if row else (0, 0)
    in_watchlist, continue_ep = await get_watch_state(user_id, anime_id)
    wa_url = extract_webapp_url(callback.message.reply_markup)

    try:
        await callback.message.edit_reply_markup(
            reply_markup=download_kb(
                anime_id, likes, dislikes,
                web_app_url=wa_url,
                in_watchlist=in_watchlist,
                continue_ep=continue_ep
            )
        )
    except Exception:
        pass
    await callback.answer(message_text, show_alert=True)


@router.callback_query(F.data.startswith("continue_watch="))
async def continue_watch_callback(callback: CallbackQuery):
    parts = callback.data.split("=")
    anime_id = int(parts[1])
    continue_ep = int(parts[2]) if len(parts) > 2 and parts[2].isdigit() else 0
    ep_to_open = continue_ep if continue_ep > 0 else 1
    await callback.answer()
    await show_episode_direct(callback.message, anime_id, ep_to_open, viewer_id=callback.from_user.id)


# ─── Yuklash menyusi ─────────────────────────────────────────────────────────

@router.callback_query(F.data.startswith("download_menu="))
async def download_menu_callback(callback: CallbackQuery):
    """'📥 Yuklash' bosilganda 2ta variant ko'rsatadi."""
    anime_id = int(callback.data.split("=")[1])
    try:
        await callback.message.edit_reply_markup(reply_markup=download_options_kb(anime_id))
    except Exception:
        pass
    await callback.answer()


# ─── Qismlab yuklash ─────────────────────────────────────────────────────────

@router.callback_query(F.data.startswith("dl_single="))
async def dl_single_callback(callback: CallbackQuery):
    """Qismlab yuklash — qism tanlash klaviaturasini ko'rsatadi."""
    anime_id = int(callback.data.split("=")[1])
    async with aiosqlite.connect(DB_PATH) as db:
        async with db.execute(
            "SELECT qism FROM anime_datas WHERE id=? ORDER BY qism ASC", (anime_id,)
        ) as cursor:
            all_eps = await cursor.fetchall()
            all_eps_list = [{'qism': row[0]} for row in all_eps]

    if not all_eps_list:
        await callback.answer("❌ Qismlar topilmadi!", show_alert=True)
        return

    await callback.message.answer(
        "📂 <b>Qaysi qismni yuklamoqchisiz? Tanlang:</b>",
        reply_markup=select_episode_kb(anime_id, all_eps_list, page=0),
        parse_mode="HTML"
    )
    await callback.answer()


@router.callback_query(F.data.startswith("dl_page="))
async def dl_page_callback(callback: CallbackQuery):
    """Qism tanlash sahifalarini almashtirish."""
    parts = callback.data.split("=")
    anime_id = int(parts[1])
    page = int(parts[2])
    async with aiosqlite.connect(DB_PATH) as db:
        async with db.execute(
            "SELECT qism FROM anime_datas WHERE id=? ORDER BY qism ASC", (anime_id,)
        ) as cursor:
            all_eps = await cursor.fetchall()
            all_eps_list = [{'qism': row[0]} for row in all_eps]

    try:
        await callback.message.edit_reply_markup(
            reply_markup=select_episode_kb(anime_id, all_eps_list, page=page)
        )
    except Exception:
        pass
    await callback.answer()


@router.callback_query(F.data.startswith("dl_ep="))
async def dl_episode_callback(callback: CallbackQuery):
    """Tanlangan qismni foydalanuvchiga yuboradi."""
    if not await is_admin(callback.from_user.id) and await is_maintenance():
        await callback.answer("⚠️ Bot tamirlanyapti, kuting...", show_alert=True)
        return

    parts = callback.data.split("=")
    anime_id = int(parts[1])
    ep_num = int(parts[2])

    async with aiosqlite.connect(DB_PATH) as db:
        async with db.execute(
            "SELECT * FROM anime_datas WHERE id=? AND qism=?", (anime_id, ep_num)
        ) as cursor:
            episode_data = await cursor.fetchone()
        async with db.execute("SELECT nom FROM animelar WHERE id=?", (anime_id,)) as cursor:
            anime_row = await cursor.fetchone()
        async with db.execute("SELECT value FROM bot_settings WHERE key='content_restriction'") as cursor:
            row = await cursor.fetchone()
            restricted = row[0] == "1" if row else False

    if not episode_data:
        await callback.answer("❌ Qism topilmadi!", show_alert=True)
        return

    anime_name = anime_row[0] if anime_row else "Anime"
    file_id = episode_data[2]
    caption = await build_episode_caption(anime_id, ep_num, anime_name, callback.bot)

    try:
        await callback.message.answer_video(
            video=file_id, caption=caption, parse_mode="HTML",
            protect_content=restricted
        )
    except Exception:
        try:
            await callback.message.answer_document(
                document=file_id, caption=caption, parse_mode="HTML",
                protect_content=restricted
            )
        except Exception as e:
            await callback.answer(f"❌ Xatolik: {e}", show_alert=True)
            return

    await set_watch_progress(callback.from_user.id, anime_id, ep_num)
    await callback.answer(f"✅ {ep_num}-qism yuborildi!")


# ─── Hammasini yuklash ────────────────────────────────────────────────────────

@router.callback_query(F.data.startswith("dl_all="))
async def dl_all_callback(callback: CallbackQuery):
    """Barcha qismlarni ketma-ket avtomatik yuboradi."""
    if not await is_admin(callback.from_user.id) and await is_maintenance():
        await callback.answer("⚠️ Bot tamirlanyapti, kuting...", show_alert=True)
        return

    parts = callback.data.split("=")
    anime_id = int(parts[1])
    offset = int(parts[2]) if len(parts) > 2 and parts[2].isdigit() else 0
    await callback.answer("⏳ Barcha qismlar yuklanmoqda...", show_alert=True)

    async with aiosqlite.connect(DB_PATH) as db:
        async with db.execute(
            "SELECT qism, file_id FROM anime_datas WHERE id=? ORDER BY qism ASC", (anime_id,)
        ) as cursor:
            all_eps = await cursor.fetchall()
        async with db.execute("SELECT nom FROM animelar WHERE id=?", (anime_id,)) as cursor:
            anime_row = await cursor.fetchone()
        async with db.execute("SELECT value FROM bot_settings WHERE key='content_restriction'") as cursor:
            row = await cursor.fetchone()
            restricted = row[0] == "1" if row else False

    if not all_eps:
        await callback.message.answer("❌ Qismlar topilmadi!")
        return

    anime_name = anime_row[0] if anime_row else "Anime"

    total_count = len(all_eps)
    offset = max(0, min(offset, total_count))
    batch = all_eps[offset:offset + DOWNLOAD_BATCH_SIZE]
    if not batch:
        await callback.message.answer("Yuklanadigan qism qolmadi.")
        return

    first_ep = batch[0][0]
    last_ep = batch[-1][0]
    await callback.message.answer(
        f"<b>{anime_name}</b>\n"
        f"<b>{first_ep}-{last_ep}</b> qismlar yuklanmoqda...\n"
        f"Jami: <b>{total_count}</b> ta qism. Har safar <b>{DOWNLOAD_BATCH_SIZE}</b> tagacha yuboriladi.",
        parse_mode="HTML"
    )

    success, failed, max_sent_ep = await send_download_batch(
        callback.message, callback.bot, anime_id, batch, anime_name, restricted
    )

    next_offset = offset + DOWNLOAD_BATCH_SIZE
    result_text = f"<b>{anime_name}</b> — {first_ep}-{last_ep} qismlar yuborildi!\nMuvaffaqiyatli: {success} ta"
    if failed:
        result_text += f"\nYuborilmadi: {failed} ta"
    if max_sent_ep > 0:
        await set_watch_progress(callback.from_user.id, anime_id, max_sent_ep)
    if next_offset < total_count:
        next_first = all_eps[next_offset][0]
        next_last = all_eps[min(next_offset + DOWNLOAD_BATCH_SIZE, total_count) - 1][0]
        result_text += f"\n\nDavom ettirish uchun: <b>{next_first}-{next_last}</b> qismlarni yuklang."

    await callback.message.answer(
        result_text,
        reply_markup=download_next_range_kb(anime_id, next_offset, total_count, all_eps),
        parse_mode="HTML"
    )
    return

    await callback.message.answer(
        f"📦 <b>{anime_name}</b>\n"
        f"Jami <b>{len(all_eps)}</b> ta qism yuklanmoqda...\n"
        f"<i>Iltimos kuting, qismlar ketma-ket yuboriladi.</i>",
        parse_mode="HTML"
    )

    import asyncio
    success = 0
    failed = 0
    max_sent_ep = 0

    for ep_num, file_id in all_eps:
        caption = await build_episode_caption(anime_id, ep_num, anime_name, callback.bot)
        try:
            try:
                await callback.message.answer_video(
                    video=file_id, caption=caption, parse_mode="HTML",
                    protect_content=restricted
                )
            except Exception:
                await callback.message.answer_document(
                    document=file_id, caption=caption, parse_mode="HTML",
                    protect_content=restricted
                )
            success += 1
            if ep_num > max_sent_ep:
                max_sent_ep = ep_num
        except Exception:
            failed += 1
        # Flood limitdan qochish uchun kichik pauza
        await asyncio.sleep(0.5)

    result_text = f"✅ <b>{anime_name}</b> — barcha qismlar yuborildi!\n📊 Muvaffaqiyatli: {success} ta"
    if failed:
        result_text += f"\n❌ Yuborilmadi: {failed} ta"
    if max_sent_ep > 0:
        await set_watch_progress(callback.from_user.id, anime_id, max_sent_ep)
    await callback.message.answer(result_text, parse_mode="HTML")


# ─── Null callback (hech narsa qilmaydigan) ──────────────────────────────────

@router.callback_query(F.data == "null")
async def null_callback(callback: CallbackQuery):
    await callback.answer()


# ─── Yopish callback ─────────────────────────────────────────────────────────

@router.callback_query(F.data == "close")
async def close_callback(callback: CallbackQuery):
    try:
        await callback.message.delete()
    except:
        pass
    await callback.answer()


# ─── VIP Xaridi ──────────────────────────────────────────────────────────────

@router.callback_query(F.data.startswith("web_link_ok="))
async def web_link_approve_callback(callback: CallbackQuery):
    request_id = callback.data.split("=", 1)[1]
    user = callback.from_user

    async with aiosqlite.connect(DB_PATH) as db:
        async with db.execute(
            "SELECT device_id, telegram_id, status FROM web_link_requests WHERE request_id=?",
            (request_id,)
        ) as c:
            row = await c.fetchone()

        if not row:
            await callback.answer("So'rov topilmadi yoki eskirgan.", show_alert=True)
            return

        device_id, telegram_id, status = row
        if int(telegram_id) != user.id:
            await callback.answer("Bu so'rov boshqa Telegram ID uchun.", show_alert=True)
            return
        if status != "pending":
            await callback.answer("Bu so'rov allaqachon yakunlangan.", show_alert=True)
            return

        await db.execute(
            "UPDATE web_link_requests SET status='approved', decided_at=CURRENT_TIMESTAMP WHERE request_id=?",
            (request_id,)
        )
        await db.execute("""
            INSERT OR REPLACE INTO web_profile_links
                (device_id, telegram_id, telegram_name, telegram_username, linked_at)
            VALUES (?, ?, ?, ?, CURRENT_TIMESTAMP)
        """, (device_id, user.id, user.full_name or "", user.username or ""))

        async with db.execute(
            "SELECT anime_id FROM web_saved_animes WHERE device_id=?",
            (device_id,)
        ) as c:
            saved_rows = await c.fetchall()
        for (anime_id,) in saved_rows:
            await db.execute(
                "INSERT OR IGNORE INTO watchlist (user_id, anime_id) VALUES (?, ?)",
                (user.id, anime_id)
            )

        await db.commit()

    try:
        await callback.message.edit_text(
            "✅ Web profilingiz Telegram profilingiz bilan ulandi.\n\n"
            "Endi webdagi saqlashlar botdagi watchlist bilan sinxron ishlaydi."
        )
    except Exception:
        pass
    await callback.answer("Ulandi!")


@router.callback_query(F.data.startswith("web_link_no="))
async def web_link_reject_callback(callback: CallbackQuery):
    request_id = callback.data.split("=", 1)[1]
    user_id = callback.from_user.id

    async with aiosqlite.connect(DB_PATH) as db:
        async with db.execute(
            "SELECT telegram_id, status FROM web_link_requests WHERE request_id=?",
            (request_id,)
        ) as c:
            row = await c.fetchone()
        if not row:
            await callback.answer("So'rov topilmadi yoki eskirgan.", show_alert=True)
            return
        telegram_id, status = row
        if int(telegram_id) != user_id:
            await callback.answer("Bu so'rov boshqa Telegram ID uchun.", show_alert=True)
            return
        if status == "pending":
            await db.execute(
                "UPDATE web_link_requests SET status='rejected', decided_at=CURRENT_TIMESTAMP WHERE request_id=?",
                (request_id,)
            )
            await db.commit()

    try:
        await callback.message.edit_text("❌ Web profil ulash rad etildi.")
    except Exception:
        pass
    await callback.answer("Rad etildi")


@router.callback_query(F.data.startswith("vip_buy="))
async def vip_purchase(callback: CallbackQuery, state: FSMContext, bot: Bot):
    """VIP paketni tanlash"""
    try:
        days = int(callback.data.split("=")[1])
    except:
        await callback.answer("❌ Noto'g'ri paket!", show_alert=True)
        return
    
    user_id = callback.from_user.id
    
    # VIP narxini o'qish
    async with aiosqlite.connect(DB_PATH) as db:
        async with db.execute("SELECT value FROM bot_settings WHERE key='vip_price'") as c:
            price_row = await c.fetchone()
        async with db.execute("SELECT value FROM bot_settings WHERE key='vip_currency'") as c:
            currency_row = await c.fetchone()
    
    vip_price = int(price_row[0]) if price_row else 5000
    vip_currency = currency_row[0] if currency_row else "so'm"
    total_price = vip_price * (days // 30)
    
    # To'lov tasdiqlovchi admin'ni tanlash
    super_admin_id = SUPER_ADMIN_ID or (ADMIN_IDS[0] if ADMIN_IDS else None)
    
    if not super_admin_id:
        await callback.answer("❌ Admin topilmadi!", show_alert=True)
        return
    
    text = (
        f"<b>💎 VIP Xaridi Tasdiqlanmoqda</b>\n\n"
        f"📅 Muddati: <b>{days} kun</b>\n"
        f"💰 Narx: <b>{total_price} {vip_currency}</b>\n\n"
        f"To'lovni amalga oshiring va to'lov ko'rinmasini yuboring."
    )
    
    await callback.message.answer(text, parse_mode="HTML")
    await state.update_data(vip_days=days, vip_price=total_price)
    await state.set_state(VipStates.send_check)
    await callback.answer()


@router.message(VipStates.send_check)
async def vip_send_check(message: Message, state: FSMContext, bot: Bot):
    """To'lov ko'rinmasini yuborish"""
    user_id = message.from_user.id
    data = await state.get_data()
    vip_days = data.get("vip_days")
    vip_price = data.get("vip_price")
    
    if not message.photo and not message.document:
        await message.answer("❌ Faqat rasm yoki dokument yuboring!")
        return
    
    # To'lov tasdiqlovchi admin'ni tanlash
    super_admin_id = SUPER_ADMIN_ID or (ADMIN_IDS[0] if ADMIN_IDS else None)
    
    # File ID ni olish
    file_id = message.photo[0].file_id if message.photo else message.document.file_id
    
    # To'lov ma'lumotlarini saqqlash
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute("""
            INSERT INTO payments (user_id, amount, purpose, status, check_file_id)
            VALUES (?, ?, 'vip_subscription', 'pending', ?)
        """, (user_id, vip_price, file_id))
        
        # To'lov ID sini oʻqish
        async with db.execute("SELECT last_insert_rowid()") as c:
            payment_id = (await c.fetchone())[0]
        
        await db.commit()
    
    # Super admin'ga screenshot bilan xat yuborish
    caption_text = (
        f"<b>💎 Yangi VIP To'lov So'rovi</b>\n\n"
        f"👤 User: <code>{user_id}</code>\n"
        f"📅 Muddati: <b>{vip_days} kun</b>\n"
        f"💰 Summa: <b>{vip_price} so'm</b>\n"
        f"🆔 To'lov ID: #{payment_id}"
    )
    
    try:
        if message.photo:
            await bot.send_photo(
                chat_id=super_admin_id,
                photo=file_id,
                caption=caption_text,
                reply_markup=payment_confirm_kb(payment_id),
                parse_mode="HTML"
            )
        else:
            await bot.send_document(
                chat_id=super_admin_id,
                document=file_id,
                caption=caption_text,
                reply_markup=payment_confirm_kb(payment_id),
                parse_mode="HTML"
            )
    except Exception as e:
        print(f"Admin notification error: {e}")
    
    # Log qilish
    log_admin_action(
        "vip_request",
        user_id,
        message.from_user.username or f"ID: {user_id}",
        details=f"{vip_days} kun, {vip_price} so'm, Payment ID: {payment_id}"
    )
    
    await _push("vip_pending", f"VIP so'rovi #{user_id} — {vip_days} kun", "g")
    await message.answer(
        "✅ To'lovingiz tasdiqlanmoqda!\n\n"
        "Admin tasdiqlagach, VIP status aktiv bo'ladi.",
        reply_markup=menu_kb(await is_admin(user_id))
    )
    await state.clear()


@router.callback_query(F.data == "vip_cancel")
async def vip_cancel(callback: CallbackQuery, state: FSMContext):
    """VIP xaridni bekor qilish"""
    await state.clear()
    await callback.message.answer("❌ VIP xaridi bekor qilindi.", parse_mode="HTML")
    await callback.answer()


# ─── VIP Avtomatik Amallar ───────────────────────────────────────────────────

async def add_vip_to_user(user_id: int, days: int):
    """Foydalanuvchiga VIP qo'shish"""
    expiry_date = (datetime.now() + timedelta(days=days)).strftime("%Y-%m-%d")
    
    async with aiosqlite.connect(DB_PATH) as db:
        # Agar VIP allaqachon bo'lsa, unga qo'shish
        async with db.execute("SELECT kun, date FROM vip_status WHERE user_id=?", (user_id,)) as c:
            existing = await c.fetchone()
        
        if existing:
            # Mavjud VIP'ga qo'shish
            new_days = existing[0] + days
            await db.execute(
                "UPDATE vip_status SET kun=?, date=? WHERE user_id=?",
                (new_days, expiry_date, user_id)
            )
        else:
            # Yangi VIP qo'shish
            await db.execute(
                "INSERT INTO vip_status (user_id, kun, date) VALUES (?, ?, ?)",
                (user_id, days, expiry_date)
            )
        
        await db.commit()
    
    return True


async def remove_expired_vips():
    """Vaqti tugagan VIP'larni o'chirish (cron job'da chaqirish kerak)"""
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute(
            "DELETE FROM vip_status WHERE date < date('now')"
        )
        await db.commit()


# ─── Raqam yozilganda anime ko'rsatish ───────────────────────────────────────

@router.message(F.text.regexp(r"^\d+$"))
async def handle_anime_code(message: Message, state: FSMContext, bot: Bot):
    """Foydalanuvchi oddiy raqam yozsa — o'sha ID dagi animeni ko'rsatadi."""
    # Agar biror state'da bo'lsa — bu handler ishlamasin (masalan qidiruv holati)
    current_state = await state.get_state()
    if current_state is not None:
        return

    user_id = message.from_user.id

    if not await is_admin(user_id) and await is_maintenance():
        await message.answer(MAINTENANCE_MSG, parse_mode="HTML")
        return

    if not await check_subscription(user_id, bot):
        keyboard = await get_subscription_keyboard(user_id, bot)
        await message.answer(
            "<b>Botdan foydalanish uchun quyidagi kanallarga obuna bo'ling❗️</b>",
            reply_markup=keyboard, parse_mode="HTML"
        )
        return

    anime_id = int(message.text)
    await show_anime(message, anime_id)


# ─── Web App data handler ─────────────────────────────────────────────────────

@router.message(F.web_app_data)
async def web_app_data_handler(message: Message, bot: Bot):
    """Mini App dan kelgan ma'lumotlarni qayta ishlaydi."""
    import json
    import asyncio

    user_id = message.from_user.id

    try:
        data = json.loads(message.web_app_data.data)
    except Exception:
        return

    action   = data.get("action", "")
    anime_id = int(data.get("anime_id", 0))

    # ── Like ──
    if action == "like":
        async with aiosqlite.connect(DB_PATH) as db:
            await db.execute("UPDATE animelar SET liklar=liklar+1 WHERE id=?", (anime_id,))
            await db.commit()
        await _push("like", f"Anime #{anime_id} — like bosildi", "p")
        return

    # ── Dislike ──
    if action == "dislike":
        async with aiosqlite.connect(DB_PATH) as db:
            await db.execute("UPDATE animelar SET desliklar=desliklar+1 WHERE id=?", (anime_id,))
            await db.commit()
        return

    # ── Ulashish ──
    if action == "share":
        bot_uname = await get_bot_username(bot)
        link = f"https://t.me/{bot_uname}?start={anime_id}"
        await message.answer(f"🔗 <b>Ulashish havolasi:</b>\n<code>{link}</code>", parse_mode="HTML")
        return

    # ── Bitta qism yuklash ──
    if action == "episode":
        ep_num = int(data.get("episode", 1))
        if not await is_admin(user_id) and await is_maintenance():
            await message.answer(MAINTENANCE_MSG, parse_mode="HTML")
            return
        async with aiosqlite.connect(DB_PATH) as db:
            async with db.execute(
                "SELECT * FROM anime_datas WHERE id=? AND qism=?", (anime_id, ep_num)
            ) as cursor:
                episode_data = await cursor.fetchone()
            async with db.execute("SELECT nom FROM animelar WHERE id=?", (anime_id,)) as cursor:
                anime_row = await cursor.fetchone()
            async with db.execute(
                "SELECT qism FROM anime_datas WHERE id=? ORDER BY qism ASC", (anime_id,)
            ) as cursor:
                all_eps = await cursor.fetchall()
                all_eps_list = [{'qism': r[0]} for r in all_eps]
            async with db.execute("SELECT value FROM bot_settings WHERE key='content_restriction'") as cursor:
                row = await cursor.fetchone()
                restricted = row[0] == "1" if row else False

        if not episode_data:
            await message.answer("❌ Qism topilmadi!")
            return

        anime_name = anime_row[0] if anime_row else "Anime"
        file_id    = episode_data[2]

        from keyboards import EPISODES_PER_PAGE
        all_ep_nums = [e['qism'] for e in all_eps_list]
        ep_index    = all_ep_nums.index(ep_num) if ep_num in all_ep_nums else 0
        page        = ep_index // EPISODES_PER_PAGE
        kb          = episodes_kb(anime_id, ep_num, all_eps_list, page)
        caption     = await build_episode_caption(anime_id, ep_num, anime_name, bot)

        sent = None
        try:
            sent = await message.answer_video(
                video=file_id, caption=caption, reply_markup=kb,
                parse_mode="HTML", protect_content=restricted
            )
        except Exception:
            try:
                sent = await message.answer_document(
                    document=file_id, caption=caption, reply_markup=kb,
                    parse_mode="HTML", protect_content=restricted
                )
            except Exception as e:
                await message.answer(f"❌ Qismni yuklashda xatolik: {e}")

        if sent:
            await save_episode_msg_id(anime_id, ep_num, sent.message_id, sent.chat.id)
            if ep_num > 1:
                await update_prev_episode_caption(anime_id, ep_num - 1, anime_name, bot)
        return

    # ── Hammasini yuklash ──
    if action == "dl_all":
        if not await is_admin(user_id) and await is_maintenance():
            await message.answer(MAINTENANCE_MSG, parse_mode="HTML")
            return

        async with aiosqlite.connect(DB_PATH) as db:
            async with db.execute(
                "SELECT qism, file_id FROM anime_datas WHERE id=? ORDER BY qism ASC", (anime_id,)
            ) as cursor:
                all_eps = await cursor.fetchall()
            async with db.execute("SELECT nom FROM animelar WHERE id=?", (anime_id,)) as cursor:
                anime_row = await cursor.fetchone()
            async with db.execute("SELECT value FROM bot_settings WHERE key='content_restriction'") as cursor:
                row = await cursor.fetchone()
                restricted = row[0] == "1" if row else False

        if not all_eps:
            await message.answer("❌ Qismlar topilmadi!")
            return

        anime_name = anime_row[0] if anime_row else "Anime"
        offset = int(data.get("offset", 0) or 0)
        total_count = len(all_eps)
        offset = max(0, min(offset, total_count))
        batch = all_eps[offset:offset + DOWNLOAD_BATCH_SIZE]
        if not batch:
            await message.answer("Yuklanadigan qism qolmadi.")
            return

        first_ep = batch[0][0]
        last_ep = batch[-1][0]
        await message.answer(
            f"<b>{anime_name}</b>\n"
            f"<b>{first_ep}-{last_ep}</b> qismlar yuklanmoqda...\n"
            f"Jami: <b>{total_count}</b> ta qism. Har safar <b>{DOWNLOAD_BATCH_SIZE}</b> tagacha yuboriladi.",
            parse_mode="HTML"
        )

        success, failed, max_sent_ep = await send_download_batch(
            message, bot, anime_id, batch, anime_name, restricted
        )

        next_offset = offset + DOWNLOAD_BATCH_SIZE
        result = f"<b>{anime_name}</b> — {first_ep}-{last_ep} qismlar yuborildi!\nMuvaffaqiyatli: {success} ta"
        if failed:
            result += f"\nYuborilmadi: {failed} ta"
        if max_sent_ep > 0:
            await set_watch_progress(user_id, anime_id, max_sent_ep)
        if next_offset < total_count:
            next_first = all_eps[next_offset][0]
            next_last = all_eps[min(next_offset + DOWNLOAD_BATCH_SIZE, total_count) - 1][0]
            result += f"\n\nDavom ettirish uchun: <b>{next_first}-{next_last}</b> qismlarni yuklang."
        await message.answer(
            result,
            reply_markup=download_next_range_kb(anime_id, next_offset, total_count, all_eps),
            parse_mode="HTML"
        )
        return

        await message.answer(
            f"📦 <b>{anime_name}</b>\n"
            f"Jami <b>{len(all_eps)}</b> ta qism yuklanmoqda...\n"
            f"<i>Iltimos kuting.</i>",
            parse_mode="HTML"
        )

        success = 0
        failed  = 0
        for ep_num, file_id in all_eps:
            caption = await build_episode_caption(anime_id, ep_num, anime_name, bot)
            try:
                try:
                    await message.answer_video(
                        video=file_id, caption=caption,
                        parse_mode="HTML", protect_content=restricted
                    )
                except Exception:
                    await message.answer_document(
                        document=file_id, caption=caption,
                        parse_mode="HTML", protect_content=restricted
                    )
                success += 1
            except Exception:
                failed += 1
            await asyncio.sleep(0.5)

        result = f"✅ <b>{anime_name}</b> — barcha qismlar yuborildi!\n📊 Muvaffaqiyatli: {success} ta"
        if failed:
            result += f"\n❌ Yuborilmadi: {failed} ta"
        await message.answer(result, parse_mode="HTML")


@router.message(Command("ai"))
async def ai_handler(message: Message):
    """AI bilan muloqot buyrug'i."""
    user_msg = message.text.replace("/ai", "").strip()
    if not user_msg:
        await message.answer("<b>AI yordamchi:</b>\nMenga biron bir savol bering yoki anime topishni so'rang.\n\nMasalan: <code>/ai Yozakura oilasi haqida ma'lumot ber</code>", parse_mode="HTML")
        return

    # Userga o'ylayotganini bildirish
    wait_msg = await message.answer("⏳ <i>AI o'ylamoqda...</i>", parse_mode="HTML")

    try:
        from web_server import get_ai_reply
        reply = await get_ai_reply(user_msg)
        await wait_msg.delete()

        # [ANIME_CARD:ID|Nom|RasmURL] formatini tekshirish
        import re
        match = re.search(r'\[ANIME_CARD:(.*?)\]', reply)
        if match:
            parts = match.group(1).split('|')
            if len(parts) >= 2:
                anime_id = parts[0]
                name = parts[1]
                reply_text = reply.replace(match.group(0), "").strip()

                async with aiosqlite.connect(DB_PATH) as db:
                    async with db.execute("SELECT rams FROM animelar WHERE id=?", (anime_id,)) as c:
                        row = await c.fetchone()
                
                if row and row[0]:
                    rams = row[0]
                    from keyboards import InlineKeyboardMarkup, InlineKeyboardButton
                    kb = InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text="🎬 KO'RISH", callback_data=f"info_{anime_id}")]])
                    
                    try:
                        await message.answer_photo(photo=rams, caption=f"<b>{name}</b>\n\n{reply_text}", reply_markup=kb, parse_mode="HTML")
                        return
                    except Exception:
                        pass # Agar rasm yuborib bo'lmasa matn ko'rinishida yuboramiz

        await message.answer(reply)
    except Exception as e:
        await wait_msg.edit_text(f"❌ AI bilan bog'lanishda xatolik: {e}")
