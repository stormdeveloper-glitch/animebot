from aiogram.types import (
    ReplyKeyboardMarkup, KeyboardButton as AiogramKeyboardButton,
    InlineKeyboardMarkup, InlineKeyboardButton as AiogramInlineKeyboardButton, WebAppInfo
)
from utils.text_sanitizer import fix_mojibake_text

PRIMARY = "primary"
SUCCESS = "success"
DANGER = "danger"
STYLE_VALUES = {PRIMARY, SUCCESS, DANGER}

BUTTON_STYLE_DEFAULTS = {
    "button_style_default": PRIMARY,
    "button_style_positive": SUCCESS,
    "button_style_negative": DANGER,
    "button_style_watch": SUCCESS,
}
BUTTON_STYLES = BUTTON_STYLE_DEFAULTS.copy()


def normalize_button_style(value: str | None, fallback: str = PRIMARY) -> str:
    value = (value or "").strip().lower()
    return value if value in STYLE_VALUES else fallback


def set_button_style(key: str, value: str) -> None:
    if key in BUTTON_STYLES:
        BUTTON_STYLES[key] = normalize_button_style(value, BUTTON_STYLE_DEFAULTS[key])


async def load_button_styles(db_path: str) -> None:
    try:
        import aiosqlite

        async with aiosqlite.connect(db_path) as db:
            async with db.execute(
                "SELECT key, value FROM bot_settings WHERE key LIKE 'button_style_%'"
            ) as cursor:
                rows = await cursor.fetchall()
    except Exception:
        return

    for key, value in rows:
        set_button_style(key, value)


def _style_for(text: str, callback_data: str | None = None, style: str | None = None) -> str:
    if style:
        return normalize_button_style(style)

    raw_text = text.lower()
    raw_callback = (callback_data or "").lower()
    raw = f"{raw_text} {raw_callback}"
    if any(word in raw for word in (
        "bekor", "rad", "yopish", "reject", "cancel", "close", "delete", "del",
        "o'chir", "orqaga", "ortga", "dislike", "yo'q"
    )) or raw_callback.startswith(("back_", "faq_back", "cancel_", "delete_", "del_")):
        return BUTTON_STYLES["button_style_negative"]
    if any(word in raw for word in (
        "tasdiq", "approve", "confirm", "vip", "yuklash", "download", "tomosha",
        "davom", "ko'rish", "korish", "pul kiritish", "like"
    )):
        return BUTTON_STYLES["button_style_positive"]
    if any(word in raw for word in ("watchlist", "saqlash")):
        return BUTTON_STYLES["button_style_watch"]
    return BUTTON_STYLES["button_style_default"]


def KeyboardButton(text: str, style: str | None = None, **kwargs) -> AiogramKeyboardButton:
    text = fix_mojibake_text(text)
    return AiogramKeyboardButton(text=text, style=_style_for(text, style=style), **kwargs)


def InlineKeyboardButton(text: str, style: str | None = None, **kwargs) -> AiogramInlineKeyboardButton:
    text = fix_mojibake_text(text)
    return AiogramInlineKeyboardButton(
        text=text,
        style=_style_for(text, callback_data=kwargs.get("callback_data"), style=style),
        **kwargs
    )

# ── Asosiy menyu ──────────────────────────────────────────────────────────────
def menu_kb(is_admin: bool = False, web_app_url: str = ""):
    keyboard = [
        [KeyboardButton(text="🔎 Anime izlash")],
        [KeyboardButton(text="💎 VIP"), KeyboardButton(text="💰 Hisobim")],
        [KeyboardButton(text="📌 Watchlist"), KeyboardButton(text="▶️ Davom etish")],
        [KeyboardButton(text="🔥 Trendlar"), KeyboardButton(text="🎯 Tavsiyalar")],
        [KeyboardButton(text="➕ Pul kiritish"), KeyboardButton(text="📚 Qo'llanma")],
        [KeyboardButton(text="👥 Referal"), KeyboardButton(text="💸 Pul o'tkazmasi")],
        [KeyboardButton(text="🎁 Cashback"), KeyboardButton(text="💵 Reklama va Homiylik")]
    ]
    if web_app_url:
        if not web_app_url.startswith("https://"):
            web_app_url = "https://" + web_app_url.lstrip("http://").lstrip("https://")
        keyboard.insert(0, [KeyboardButton(text="🌐 Web App", web_app=WebAppInfo(url=web_app_url))])
    if is_admin:
        keyboard.append([KeyboardButton(text="🗄 Boshqarish")])
    return ReplyKeyboardMarkup(keyboard=keyboard, resize_keyboard=True)


def panel_kb(is_super_admin: bool = False):
    keyboard = [
        [KeyboardButton(text="*️⃣ Birlamchi sozlamalar")],
        [KeyboardButton(text="📊 Statistika"), KeyboardButton(text="✉ Xabar Yuborish")],
        [KeyboardButton(text="📬 Post tayyorlash")],
        [KeyboardButton(text="🎥 Animelar sozlash"), KeyboardButton(text="💳 Hamyonlar")],
        [KeyboardButton(text="🔎 Foydalanuvchini boshqarish")],
        [KeyboardButton(text="📢 Kanallar"), KeyboardButton(text="🎛 Tugmalar"), KeyboardButton(text="📃 Matnlar")],
        [KeyboardButton(text="💸 To'lovlarni Tasdiqlash")],
        [KeyboardButton(text="📋 Ro'yxat yuborish")]
    ]
    if is_super_admin:
        keyboard.append([KeyboardButton(text="📋 Adminlar")])
        keyboard.append([KeyboardButton(text="📋 Jurnallar")])
    keyboard.append([KeyboardButton(text="🤖 Bot holati"), KeyboardButton(text="◀️ Orqaga")])
    return ReplyKeyboardMarkup(keyboard=keyboard, resize_keyboard=True)


def back_kb():
    return ReplyKeyboardMarkup(keyboard=[[KeyboardButton(text="◀️ Orqaga")]], resize_keyboard=True)


def boshqarish_kb():
    return ReplyKeyboardMarkup(keyboard=[[KeyboardButton(text="🗄 Boshqarish")]], resize_keyboard=True)


def search_type_kb():
    keyboard = [
        [InlineKeyboardButton(text="🏷 Anime nomi orqali", callback_data="searchByName"),
         InlineKeyboardButton(text="⏱ So'ngi yuklanganlar", callback_data="lastUploads")],
        [InlineKeyboardButton(text="💬 Janr orqali", callback_data="searchByGenre")],
        [InlineKeyboardButton(text="📌 Kod orqali", callback_data="searchByCode"),
         InlineKeyboardButton(text="👁️ Eng ko'p ko'rilgan", callback_data="topViewers")],
        [InlineKeyboardButton(text="🔞 Yosh toifasi bo'yicha", callback_data="searchByAge")],
        [InlineKeyboardButton(text="📚 Barcha animelar", callback_data="allAnimes")]
    ]
    return InlineKeyboardMarkup(inline_keyboard=keyboard)


def vip_shop_kb(price: int, currency: str):
    keyboard = [
        [InlineKeyboardButton(text=f"30 kun - {price} {currency}", callback_data="shop=30")],
        [InlineKeyboardButton(text=f"60 kun - {price * 2} {currency}", callback_data="shop=60")],
        [InlineKeyboardButton(text=f"90 kun - {price * 3} {currency}", callback_data="shop=90")]
    ]
    return InlineKeyboardMarkup(inline_keyboard=keyboard)


# ── Anime kartasi — Web App yoki fallback inline ───────────────────────────────
def download_kb(
    anime_id: int,
    likes: int = 0,
    dislikes: int = 0,
    web_app_url: str = "",
    in_watchlist: bool = False,
    continue_ep: int = 0,
    season_buttons: list | None = None,
):
    """
    Web app bo'lsa ham bo'lmasa ham barcha tugmalar chiqadi.
    Web app bo'lsa — "🎬 Tomosha qilish" qo'shimcha chiqadi.
    """
    total_votes = likes + dislikes
    if total_votes > 0:
        rating = round((likes / total_votes) * 5, 1)
        rating_text = f"⭐ {rating}/5  ({total_votes} ovoz)"
    else:
        rating_text = "⭐ Baholash"

    keyboard = []

    # Web App tugmasi — faqat URL bo'lsa
    if web_app_url:
        keyboard.append([InlineKeyboardButton(text="🎬 Tomosha qilish", web_app=WebAppInfo(url=web_app_url))])

    if season_buttons:
        keyboard.append(season_buttons)

    # Har doim chiqadigan tugmalar
    keyboard += [
        [InlineKeyboardButton(
            text=("✅ Watchlistda" if in_watchlist else "📌 Watchlistga saqlash"),
            callback_data=f"watchlist_toggle={anime_id}"
        )],
        [InlineKeyboardButton(text="📥 Yuklash", callback_data=f"download_menu={anime_id}")],
        [InlineKeyboardButton(
            text=("▶️ Davom etish" if continue_ep > 0 else "▶️ 1-qismdan boshlash"),
            callback_data=f"continue_watch={anime_id}={continue_ep}"
        )],
        [InlineKeyboardButton(text=f"👍 {likes}", callback_data=f"like={anime_id}"),
         InlineKeyboardButton(text=f"👎 {dislikes}", callback_data=f"dislike={anime_id}")],
        [InlineKeyboardButton(text=rating_text, callback_data=f"rate={anime_id}")],
        [InlineKeyboardButton(text="🔁 Ulashish", callback_data=f"share={anime_id}"),
         InlineKeyboardButton(text="❌ Yopish", callback_data="close")],
    ]
    return InlineKeyboardMarkup(inline_keyboard=keyboard)


# ── Qism ko'rish klaviaturasi (qism ichida) ───────────────────────────────────
EPISODES_PER_PAGE = 24

def episodes_kb(anime_id: int, current_ep: int, total_eps_data: list, page: int = 0):
    all_eps = [int(ep['qism']) for ep in total_eps_data]
    total = len(all_eps)
    total_pages = max(1, (total + EPISODES_PER_PAGE - 1) // EPISODES_PER_PAGE)
    page = max(0, min(page, total_pages - 1))

    start = page * EPISODES_PER_PAGE
    end = start + EPISODES_PER_PAGE
    page_eps = all_eps[start:end]

    buttons = []
    for q in page_eps:
        if q == current_ep:
            buttons.append(InlineKeyboardButton(text=f"[ {q} ]", callback_data="null"))
        else:
            buttons.append(InlineKeyboardButton(text=str(q), callback_data=f"yuklanolish={anime_id}={q}"))

    rows = [buttons[i:i + 5] for i in range(0, len(buttons), 5)]

    nav = []
    if page > 0:
        nav.append(InlineKeyboardButton(text="◀️", callback_data=f"ep_page={anime_id}={page - 1}={current_ep}"))
    if page < total_pages - 1:
        nav.append(InlineKeyboardButton(text=f"{page + 1}/{total_pages}", callback_data="null"))
        nav.append(InlineKeyboardButton(text="▶️", callback_data=f"ep_page={anime_id}={page + 1}={current_ep}"))
    elif total_pages > 1:
        nav.append(InlineKeyboardButton(text=f"{page + 1}/{total_pages}", callback_data="null"))
    if nav:
        rows.append(nav)

    rows.append([InlineKeyboardButton(text="⬅ Ortga", callback_data=f"loadAnime={anime_id}")])
    return InlineKeyboardMarkup(inline_keyboard=rows)


def payment_confirm_kb(payment_id: int):
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="✅ Tasdiqlash", callback_data=f"pay_approve={payment_id}")],
        [InlineKeyboardButton(text="❌ Rad etish",  callback_data=f"pay_reject={payment_id}")]
    ])


def vip_plans_kb(price: int, currency: str):
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text=f"30 kun — {price} {currency}",     callback_data="vip_buy=30")],
        [InlineKeyboardButton(text=f"60 kun — {price*2} {currency}",   callback_data="vip_buy=60")],
        [InlineKeyboardButton(text=f"90 kun — {price*3} {currency}",   callback_data="vip_buy=90")],
        [InlineKeyboardButton(text="❌ Bekor", callback_data="vip_cancel")]
    ])


# ── Fallback: download menu (web app yo'q bo'lganda) ─────────────────────────
def download_options_kb(anime_id: int):
    keyboard = [
        [InlineKeyboardButton(text="📂 Qismlab yuklash", callback_data=f"dl_single={anime_id}")],
        [InlineKeyboardButton(text="📦 Hammasini yuklash", callback_data=f"dl_all={anime_id}")],
        [InlineKeyboardButton(text="⬅ Ortga", callback_data=f"loadAnime={anime_id}")],
    ]
    return InlineKeyboardMarkup(inline_keyboard=keyboard)


def select_episode_kb(anime_id: int, episodes: list, page: int = 0):
    PER_PAGE = 24
    all_eps = [int(ep['qism']) for ep in episodes]
    total = len(all_eps)
    total_pages = max(1, (total + PER_PAGE - 1) // PER_PAGE)
    page = max(0, min(page, total_pages - 1))

    start = page * PER_PAGE
    end = start + PER_PAGE
    page_eps = all_eps[start:end]

    buttons = [
        InlineKeyboardButton(text=str(q), callback_data=f"dl_ep={anime_id}={q}")
        for q in page_eps
    ]
    rows = [buttons[i:i + 5] for i in range(0, len(buttons), 5)]

    nav = []
    if page > 0:
        nav.append(InlineKeyboardButton(text="◀️", callback_data=f"dl_page={anime_id}={page - 1}"))
    if page < total_pages - 1:
        nav.append(InlineKeyboardButton(text=f"{page + 1}/{total_pages}", callback_data="null"))
        nav.append(InlineKeyboardButton(text="▶️", callback_data=f"dl_page={anime_id}={page + 1}"))
    elif total_pages > 1:
        nav.append(InlineKeyboardButton(text=f"{page + 1}/{total_pages}", callback_data="null"))
    if nav:
        rows.append(nav)

    rows.append([InlineKeyboardButton(text="⬅ Ortga", callback_data=f"download_menu={anime_id}")])
    return InlineKeyboardMarkup(inline_keyboard=rows)


# ── Yosh kategoriyasi tugmalari ───────────────────────────────────────────────
YOSH_TOIFALAR = [
    ("👶 Barcha yoshlar (0+)", "0+"),
    ("🧒 Bolalar (7+)", "7+"),
    ("👦 O'smirlar (13+)", "13+"),
    ("🧑 Yoshlar (16+)", "16+"),
    ("🔞 Kattalar (18+)", "18+"),
]

def yosh_toifa_kb():
    keyboard = [
        [InlineKeyboardButton(text=text, callback_data=f"set_age={code}")]
        for text, code in YOSH_TOIFALAR
    ]
    return InlineKeyboardMarkup(inline_keyboard=keyboard)

def search_by_age_kb():
    keyboard = [
        [InlineKeyboardButton(text=text, callback_data=f"ageAnimes={code}")]
        for text, code in YOSH_TOIFALAR
    ]
    keyboard.append([InlineKeyboardButton(text="◀️ Orqaga", callback_data="back_to_search")])
    return InlineKeyboardMarkup(inline_keyboard=keyboard)
