"""🌐 Ekotizim: barcha botlar animelari katalogi va pullik kirish so'rovlari."""
import html

import aiosqlite
from aiogram import Bot, F, Router
from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery, InlineKeyboardMarkup, Message

from config import DB_PATH
from keyboards import InlineKeyboardButton
from states import EcoStates
from utils import is_admin, payment_admin_ids
from utils import eco

router = Router()

ECO_TEXT = "🌐 Ekotizim"


def _som(amount: int) -> str:
    return f"{amount:,}".replace(",", " ") + " so'm"


def _bot_label(bot_id: int, current_id: int) -> str:
    info = eco.bot_info(bot_id)
    name = info[2] if info else "Bot"
    return f"{name} (shu bot)" if bot_id == current_id else name


async def _home_markup(current_id: int) -> InlineKeyboardMarkup:
    buttons = [[InlineKeyboardButton(text="🔎 Barcha botlardan qidirish", callback_data="ecoSearch")]]
    for bot_id, username, name in eco.ecosystem_bots():
        count = await eco.anime_count(bot_id)
        label = f"🤖 {name}{' (shu bot)' if bot_id == current_id else ''} — {count} anime"
        buttons.append([InlineKeyboardButton(text=label, callback_data=f"ecoBot={bot_id}:0")])
    return InlineKeyboardMarkup(inline_keyboard=buttons)


ECO_HOME_TEXT = (
    "<b>🌐 Anime ekotizimi</b>\n\n"
    "Bizning tizimdagi barcha botlar animelari shu yerda. "
    "Botni tanlang yoki hamma botlardan qidiring."
)


@router.message(F.text == ECO_TEXT)
async def eco_home(message: Message, bot: Bot):
    await message.answer(ECO_HOME_TEXT, reply_markup=await _home_markup(bot.id), parse_mode="HTML")


@router.callback_query(F.data == "ecoHome")
async def eco_home_cb(callback: CallbackQuery, bot: Bot):
    await callback.message.edit_text(ECO_HOME_TEXT, reply_markup=await _home_markup(bot.id), parse_mode="HTML")
    await callback.answer()


@router.callback_query(F.data.startswith("ecoBot="))
async def eco_bot_page(callback: CallbackQuery, bot: Bot):
    bot_id, page = (int(x) for x in callback.data.split("=", 1)[1].split(":"))
    if not eco.bot_info(bot_id):
        await callback.answer("Bu bot hozir ishlamayapti", show_alert=True)
        return
    rows = await eco.anime_page(bot_id, page)
    total = await eco.anime_count(bot_id)
    buttons = [
        [InlineKeyboardButton(text=f"🎬 {nom}", callback_data=f"ecoAni={bot_id}:{anime_id}")]
        for anime_id, nom in rows
    ]
    nav = []
    if page > 0:
        nav.append(InlineKeyboardButton(text="⬅️", callback_data=f"ecoBot={bot_id}:{page - 1}"))
    if (page + 1) * eco.PAGE_SIZE < total:
        nav.append(InlineKeyboardButton(text="➡️", callback_data=f"ecoBot={bot_id}:{page + 1}"))
    if nav:
        buttons.append(nav)
    buttons.append([InlineKeyboardButton(text="◀️ Botlar ro'yxati", callback_data="ecoHome")])

    price = await eco.access_price(bot_id)
    text = f"<b>🤖 {html.escape(_bot_label(bot_id, bot.id))}</b> — {total} anime"
    if price:
        text += f"\n💰 Ko'rish uchun kirish narxi: <b>{_som(price)}</b>"
    if not rows:
        text += "\n\nBu botda hali anime yo'q."
    await callback.message.edit_text(
        text, reply_markup=InlineKeyboardMarkup(inline_keyboard=buttons), parse_mode="HTML"
    )
    await callback.answer()


@router.callback_query(F.data.startswith("ecoAni="))
async def eco_anime_card(callback: CallbackQuery, bot: Bot):
    bot_id, anime_id = (int(x) for x in callback.data.split("=", 1)[1].split(":"))
    info = eco.bot_info(bot_id)
    card = await eco.anime_card(bot_id, anime_id) if info else None
    if not card:
        await callback.answer("❌ Anime topilmadi", show_alert=True)
        return

    tavsif = (card["tavsif"] or "").strip()
    if len(tavsif) > 400:
        tavsif = tavsif[:400].rsplit(" ", 1)[0] + "…"
    text = (
        f"<b>🎬 {html.escape(card['nom'])}</b>\n\n"
        f"🤖 Bot: <b>{html.escape(_bot_label(bot_id, bot.id))}</b>\n"
        f"🎞 Qismlar: <b>{card['uploaded']}/{html.escape(str(card['qismi']))}</b>\n"
        f"🌍 Davlat: {html.escape(card['davlat'] or '—')}\n"
        f"🇺🇿 Tili: {html.escape(card['tili'] or '—')}\n"
        f"📆 Yili: {html.escape(card['yili'] or '—')}\n"
        f"🎭 Janri: {html.escape(card['janri'] or '—')}"
    )
    if tavsif:
        text += f"\n\n{html.escape(tavsif)}"
    if card["price"]:
        text += (
            f"\n\n💰 Kirish narxi: <b>{_som(card['price'])}</b>"
            "\n<i>To'lov chekini yuborasiz, bot egasi tasdiqlagach ko'rish ochiladi.</i>"
        )

    if bot_id == bot.id:
        watch = InlineKeyboardButton(text="▶️ Ko'rish", callback_data=f"loadAnime={anime_id}")
    else:
        watch = InlineKeyboardButton(
            text=f"▶️ @{info[1]} da ko'rish", url=f"https://t.me/{info[1]}?start={anime_id}"
        )
    markup = InlineKeyboardMarkup(inline_keyboard=[
        [watch],
        [InlineKeyboardButton(text="◀️ Orqaga", callback_data=f"ecoBot={bot_id}:0")],
    ])
    await callback.message.edit_text(text, reply_markup=markup, parse_mode="HTML")
    await callback.answer()


@router.callback_query(F.data == "ecoSearch")
async def eco_search_prompt(callback: CallbackQuery, state: FSMContext):
    await state.set_state(EcoStates.search)
    await callback.message.answer("🔎 Anime nomini yozing — barcha botlardan qidiraman:")
    await callback.answer()


@router.message(EcoStates.search, F.text)
async def eco_search(message: Message, state: FSMContext, bot: Bot):
    query = message.text.strip()
    if len(query) < 2:
        await message.answer("Kamida 2 ta harf yozing.")
        return
    await state.clear()
    results = await eco.search_all(query)
    if not results:
        await message.answer("😔 Hech narsa topilmadi.")
        return
    buttons = [
        [InlineKeyboardButton(
            text=f"🎬 {nom} · {_bot_label(bot_id, bot.id)}", callback_data=f"ecoAni={bot_id}:{anime_id}"
        )]
        for bot_id, anime_id, nom in results
    ]
    await message.answer(
        f"🔎 «{html.escape(query)}» bo'yicha natijalar:",
        reply_markup=InlineKeyboardMarkup(inline_keyboard=buttons), parse_mode="HTML",
    )


# ─── Pullik kirish ────────────────────────────────────────────────────────────

async def check_access(event: Message | CallbackQuery, user_id: int | None = None) -> bool:
    """Qismni ko'rishdan oldin: bot pullik bo'lsa va ruxsat yo'q bo'lsa — to'xtatadi."""
    user_id = user_id or event.from_user.id
    price = await eco.access_price()
    if not price or await is_admin(user_id) or await eco.has_access(user_id):
        return True

    message = event.message if isinstance(event, CallbackQuery) else event
    if isinstance(event, CallbackQuery):
        await event.answer()
    await message.answer(
        f"🔐 <b>Bu botdagi animelarni ko'rish pullik</b>\n\n"
        f"💰 Kirish narxi: <b>{_som(price)}</b>\n"
        "To'lov qilib chekni yuboring — bot egasi tasdiqlagach barcha animelar ochiladi.",
        reply_markup=InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="💳 To'lov qilish", callback_data="ecoPay")]
        ]),
        parse_mode="HTML",
    )
    return False


@router.callback_query(F.data == "ecoPay")
async def eco_pay(callback: CallbackQuery, state: FSMContext):
    price = await eco.access_price()
    async with aiosqlite.connect(DB_PATH) as db:
        async with db.execute("SELECT value FROM bot_texts WHERE key='wallet'") as c:
            row = await c.fetchone()
    wallet = row[0] if row else "Hamyon hali o'rnatilmagan — bot egasiga murojaat qiling."
    await state.set_state(EcoStates.send_check)
    await callback.message.answer(
        f"💰 Summa: <b>{_som(price)}</b>\n"
        f"💳 Hamyon:\n<code>{html.escape(wallet)}</code>\n\n"
        "To'lovdan keyin chek rasmini shu yerga yuboring.",
        parse_mode="HTML",
    )
    await callback.answer()


@router.message(EcoStates.send_check, F.photo | F.document)
async def eco_send_check(message: Message, state: FSMContext, bot: Bot):
    file_id = message.photo[-1].file_id if message.photo else message.document.file_id
    request_id = await eco.create_access_request(message.from_user.id, file_id)
    await state.clear()
    await message.answer("✅ Chek yuborildi. Bot egasi tasdiqlashini kuting.")

    caption = (
        f"🔐 <b>Kirish so'rovi #{request_id}</b>\n\n"
        f"👤 {html.escape(message.from_user.full_name)} (<code>{message.from_user.id}</code>)\n"
        f"💰 {_som(await eco.access_price())}"
    )
    markup = InlineKeyboardMarkup(inline_keyboard=[[
        InlineKeyboardButton(text="✅ Tasdiqlash", callback_data=f"ecoOk={request_id}"),
        InlineKeyboardButton(text="❌ Rad etish", callback_data=f"ecoNo={request_id}"),
    ]])
    for admin_id in payment_admin_ids():
        try:
            if message.photo:
                await bot.send_photo(admin_id, file_id, caption=caption, reply_markup=markup, parse_mode="HTML")
            else:
                await bot.send_document(admin_id, file_id, caption=caption, reply_markup=markup, parse_mode="HTML")
        except Exception:
            pass


@router.message(EcoStates.send_check)
async def eco_send_check_invalid(message: Message):
    await message.answer("❌ Chekni rasm yoki fayl ko'rinishida yuboring.")


@router.callback_query(F.data.startswith(("ecoOk=", "ecoNo=")))
async def eco_resolve(callback: CallbackQuery, bot: Bot):
    if not await is_admin(callback.from_user.id):
        await callback.answer("❌ Faqat bot egasi", show_alert=True)
        return
    approve = callback.data.startswith("ecoOk=")
    request_id = int(callback.data.split("=", 1)[1])
    user_id = await eco.resolve_access_request(request_id, approve)
    if user_id is None:
        await callback.answer("Bu so'rov allaqachon ko'rib chiqilgan", show_alert=True)
        return
    status = "✅ Tasdiqlandi" if approve else "❌ Rad etildi"
    try:
        await callback.message.edit_caption(
            caption=(callback.message.caption or "") + f"\n\n{status}", reply_markup=None
        )
    except Exception:
        pass
    try:
        await bot.send_message(
            user_id,
            "✅ To'lovingiz tasdiqlandi! Endi barcha animelarni ko'rishingiz mumkin."
            if approve else "❌ To'lovingiz rad etildi. Savollar bo'lsa bot egasiga yozing.",
        )
    except Exception:
        pass
    await callback.answer(status)
