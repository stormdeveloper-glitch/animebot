from aiogram.types import (
    ReplyKeyboardMarkup, KeyboardButton as AiogramKeyboardButton,
    InlineKeyboardMarkup, InlineKeyboardButton as AiogramInlineKeyboardButton
)

PRIMARY = "primary"
SUCCESS = "success"
DANGER = "danger"


def _style_for(text: str, callback_data: str | None = None, style: str | None = None) -> str:
    if style:
        return style

    raw = f"{text} {callback_data or ''}".lower()
    if any(word in raw for word in (
        "bekor", "rad", "yopish", "close", "cancel", "del", "delete", "o'chir",
        "orqaga", "back"
    )):
        return DANGER
    if any(word in raw for word in (
        "tasdiq", "confirm", "yubor", "reply", "faq_add", "admin", "success"
    )):
        return SUCCESS
    return PRIMARY


def KeyboardButton(text: str, style: str | None = None, **kwargs) -> AiogramKeyboardButton:
    return AiogramKeyboardButton(text=text, style=_style_for(text, style=style), **kwargs)


def InlineKeyboardButton(text: str, style: str | None = None, **kwargs) -> AiogramInlineKeyboardButton:
    return AiogramInlineKeyboardButton(
        text=text,
        style=_style_for(text, callback_data=kwargs.get("callback_data"), style=style),
        **kwargs
    )


# ── Foydalanuvchi menyusi ─────────────────────────────────────────────────────
def user_main_kb() -> ReplyKeyboardMarkup:
    return ReplyKeyboardMarkup(
        keyboard=[
            [KeyboardButton(text="💬 Murojaat yuborish")],
            [KeyboardButton(text="📋 FAQ — Ko'p so'raladigan savollar")],
            [KeyboardButton(text="📊 Mening murojaatlarim")],
            [KeyboardButton(text="🤖 Bot haqida")],
        ],
        resize_keyboard=True
    )


def cancel_kb() -> ReplyKeyboardMarkup:
    return ReplyKeyboardMarkup(
        keyboard=[[KeyboardButton(text="❌ Bekor qilish")]],
        resize_keyboard=True
    )


def back_kb() -> ReplyKeyboardMarkup:
    return ReplyKeyboardMarkup(
        keyboard=[[KeyboardButton(text="◀️ Orqaga")]],
        resize_keyboard=True
    )


# ── Admin guruhi tugmalari ─────────────────────────────────────────────────────
def ticket_admin_kb(ticket_id: int, user_id: int) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        [
            InlineKeyboardButton(
                text="💬 Javob berish",
                callback_data=f"sup_reply={ticket_id}={user_id}"
            ),
            InlineKeyboardButton(
                text="🔒 Yopish",
                callback_data=f"sup_close={ticket_id}={user_id}"
            ),
        ],
        [
            InlineKeyboardButton(
                text="👤 Foydalanuvchi profili",
                callback_data=f"sup_profile={user_id}"
            ),
        ]
    ])


def ticket_closed_kb(ticket_id: int) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(
            text=f"✅ #{ticket_id} — Yopilgan",
            callback_data="null"
        )]
    ])


def ticket_answered_kb(ticket_id: int) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(
            text=f"✅ #{ticket_id} — Javob berildi",
            callback_data="null"
        )],
        [InlineKeyboardButton(
            text="🔒 Yopish",
            callback_data=f"sup_close={ticket_id}=0"
        )]
    ])


# ── FAQ tugmalari ─────────────────────────────────────────────────────────────
def faq_list_kb(faqs: list) -> InlineKeyboardMarkup:
    """faqs: [(id, question, answer, order_num), ...]"""
    keyboard = [
        [InlineKeyboardButton(
            text=f"❓ {faq[1][:50]}",
            callback_data=f"faq={faq[0]}"
        )]
        for faq in faqs
    ]
    keyboard.append([InlineKeyboardButton(text="◀️ Orqaga", callback_data="faq_back")])
    return InlineKeyboardMarkup(inline_keyboard=keyboard)


def faq_answer_kb(faq_id: int, total: int, current_index: int) -> InlineKeyboardMarkup:
    nav = []
    if current_index > 0:
        nav.append(InlineKeyboardButton(text="◀️", callback_data=f"faq_nav={current_index - 1}"))
    nav.append(InlineKeyboardButton(text=f"{current_index + 1}/{total}", callback_data="null"))
    if current_index < total - 1:
        nav.append(InlineKeyboardButton(text="▶️", callback_data=f"faq_nav={current_index + 1}"))

    keyboard = []
    if nav:
        keyboard.append(nav)
    keyboard.append([InlineKeyboardButton(text="📋 Barcha savollar", callback_data="faq_list")])
    keyboard.append([InlineKeyboardButton(text="◀️ Bosh menyu", callback_data="faq_back")])
    return InlineKeyboardMarkup(inline_keyboard=keyboard)


# ── Admin paneli (PM) ─────────────────────────────────────────────────────────
def admin_panel_kb() -> ReplyKeyboardMarkup:
    return ReplyKeyboardMarkup(
        keyboard=[
            [KeyboardButton(text="📊 Support statistika")],
            [KeyboardButton(text="📋 Ochiq murojaatlar")],
            [KeyboardButton(text="❓ FAQ boshqarish")],
            [KeyboardButton(text="◀️ Orqaga")],
        ],
        resize_keyboard=True
    )


def admin_main_kb() -> ReplyKeyboardMarkup:
    return ReplyKeyboardMarkup(
        keyboard=[
            [KeyboardButton(text="💬 Murojaat yuborish")],
            [KeyboardButton(text="📋 FAQ — Ko'p so'raladigan savollar")],
            [KeyboardButton(text="📊 Mening murojaatlarim")],
            [KeyboardButton(text="🤖 Bot haqida")],
            [KeyboardButton(text="🗄 Admin panel")],
        ],
        resize_keyboard=True
    )


def confirm_reply_kb(ticket_id: int) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        [
            InlineKeyboardButton(text="✅ Yuborish", callback_data=f"confirm_reply={ticket_id}"),
            InlineKeyboardButton(text="✏️ Qayta yozish", callback_data=f"rewrite_reply={ticket_id}"),
            InlineKeyboardButton(text="❌ Bekor", callback_data="cancel_reply"),
        ]
    ])


def ai_escalate_kb() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="🧑‍💼 Baribir adminga yuborish", callback_data="sup_send_admin")]
    ])
