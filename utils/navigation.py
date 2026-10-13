"""Navigatsiya tugmalari FSM holatidan ustun bo'lishi uchun middleware.

Muammo: user panel tugmalari (📚 Qo'llanma, 👥 Referal, 🎁 Cashback, ...) va
admin panel tugmalarining ayrimlari handlerlar ro'yxatida keyinroq joylashgan.
Faqat faol FSM holatini tekshiruvchi handlerlar (masalan, PaymentStates.enter_amount,
UserStates.search_by_name) ularni "o'z matni" sifatida yutib yuboradi —
foydalanuvchi tugma bosganda to'g'ri menyu o'rniga noto'g'ri javob chiqadi
(masalan "Kamida 1000 so'm kiriting!").

Bu middleware xabar qabul qilinishdan oldin: matn navigatsiya tugmasiga to'g'ri
kelsa, faol holatni tozalaydi (faqat matn kiritish talab qilinadigan admin
oqimlaridan tashqari), shunda tegishli tugma ishlaydi.
"""
from aiogram import BaseMiddleware
from aiogram.types import Message

from keyboards import menu_kb, panel_kb, back_kb, boshqarish_kb, BACK_TO_MENU_TEXTS
from states import (
    AdminStates, EditAnimeStates, SettingsStates, ButtonStates, PostStates,
)


def _texts(keyboard) -> frozenset[str]:
    return frozenset(
        button.text
        for row in keyboard.keyboard
        for button in row
        if getattr(button, "text", None)
    )


# Buyruqlar har qanday holatdan ham tozalash kerak — ular matn kiritish
# oqimiga qo'lib qolmasligi kerak (masalan, broadcast ichida /start).
NAV_COMMANDS: frozenset[str] = frozenset({"/start", "/menu", "/panel", "/ai"})

# Barcha navigatsiya matnlari: menyu + admin panel + "orqaga" variantlari + buyruqlar
NAV_TEXTS: frozenset[str] = frozenset(
    _texts(menu_kb(is_admin=True))
    | _texts(panel_kb(is_super_admin=True))
    | _texts(back_kb())
    | _texts(boshqarish_kb())
    | set(BACK_TO_MENU_TEXTS)
    | NAV_COMMANDS
)

# Matn kiritiladigan admin oqimlari: bu yerda kiritilgan matn navigatsiya
# tugmasiga o'xshab tushishi mumkin (masalan, "Menyu" degan matnni tahrirlash),
# shuning uchun bunda holat tozalanmaydi — mavjud oqim buzilmasin.
COMPOSITION_STATES: frozenset[str] = frozenset({
    AdminStates.broadcast.state,
    AdminStates.ai_post_draft.state,
    AdminStates.add_anime_name.state,
    AdminStates.add_anime_english_name.state,
    AdminStates.add_anime_year.state,
    AdminStates.add_anime_country.state,
    AdminStates.add_anime_language.state,
    AdminStates.add_anime_genre.state,
    AdminStates.add_anime_fandub.state,
    AdminStates.add_anime_status.state,
    AdminStates.add_anime_age.state,
    AdminStates.add_anime_description.state,
    AdminStates.add_channel_name.state,
    AdminStates.add_channel_id.state,
    AdminStates.add_channel_link.state,
    AdminStates.edit_text.state,
    AdminStates.edit_wallet.state,
    EditAnimeStates.edit_field.state,
    SettingsStates.edit_value.state,
    ButtonStates.add_btn_text.state,
    ButtonStates.add_btn_url.state,
    PostStates.media.state,
    PostStates.caption.state,
    PostStates.buttons.state,
    PostStates.confirm.state,
})


def _message_of(event) -> Message | None:
    """Update ichidan xabarni oladi (message-level middleware da esa o'zi Message)."""
    if isinstance(event, Message):
        return event
    return getattr(event, "message", None) or getattr(event, "edited_message", None)


class NavigationStateClearMiddleware(BaseMiddleware):
    """Navigatsiya matni kelganda faol FSM holatini tozalaydi."""

    async def __call__(self, handler, event, data):
        message = _message_of(event)
        text = (message.text or "").strip() if isinstance(message, Message) else ""
        if text and text in NAV_TEXTS:
            state = data.get("state")
            if state is not None:
                # aiogram state filtrlari data["raw_state"] ni o'qiydi — shuning
                # uchun uni ham tozalash shart, aks holda eski holat ishlaydi.
                raw_state = data.get("raw_state")
                if raw_state is None:
                    raw_state = await state.get_state()
                if raw_state and (text in NAV_COMMANDS or raw_state not in COMPOSITION_STATES):
                    await state.clear()
                    data["raw_state"] = None
        return await handler(event, data)
