"""Animatsiyali (custom) emoji ID larini boshqarish.

Bot ishga tushganda resolve_custom_emojis():
  1. Ma'lum ID larni Telegram orqali tekshiradi (yaroqsizlari o'chiriladi).
  2. Emoji to'plamini aniqlaydi: CUSTOM_EMOJI_PACK yoki ✨ ID si tegishli to'plam.
  3. Shu to'plamdan ID si yo'q emoji larga mos animatsiyani o'zi topadi.
Topilmagan emoji oddiy ko'rinishda qoladi — noto'g'ri animatsiya chiqmaydi.
"""
import logging
import os
import re

from aiogram import Bot
from aiogram.utils.text_decorations import html_decoration

logger = logging.getLogger(__name__)

# emoji → custom_emoji_id (None — hali topilmagan)
EMOJI_IDS: dict[str, str | None] = {
    "✨": "4999015678238262018",
    "🔥": None,
    "❤️": None,
    "👏": None,
    "🎉": None,
    "✅": None,
    "🔍": None,
    "🎬": None,
    "💎": None,
    "💰": None,
    "🎁": None,
    "🚀": None,
    "👋": None,
    "👑": None,
}

CUSTOM_EMOJI_PACK = os.getenv("CUSTOM_EMOJI_PACK", "").strip()

# Asosiy menyu tugmalari uchun animatsiyali ikonkalar (KeyboardButton.icon_custom_emoji_id).
# To'plamlar: t.me/addemoji/NewsEmoji va t.me/addemoji/statuspack_uz
MENU_ICON_IDS: dict[str, str | None] = {
    "🌐 Web App":             "5447410659077661506",  # 🌐
    "🔎 Anime izlash":        "5231012545799666522",  # 🔍
    "💎 VIP":                 "5427168083074628963",  # 💎
    "💰 Hisobim":             "5409048419211682843",  # 💵
    "📌 Watchlist":           "5397782960512444700",  # 📌
    "▶️ Davom etish":         "5264919878082509254",  # ▶️
    "🔥 Trendlar":            "5424972470023104089",  # 🔥
    "🎯 Tavsiyalar":          "5438496463044752972",  # ⭐️
    "➕ Pul kiritish":        "5397916757333654639",  # ➕
    "📚 Qo'llanma":           "5334544901428229844",  # ℹ️
    "👥 Referal":             "5460795800101594035",  # 🗣
    "💸 Pul o'tkazmasi":      "5233326571099534068",  # 💸
    "🎁 Cashback":            "5330312778093704176",  # 🎁
    "💵 Reklama va Homiylik": "5424818078833715060",  # 📣
    "🗄 Boshqarish":          "5341715473882955310",  # ⚙️
}


def menu_icon_label(text: str) -> str:
    """Ikonka bilan ko'rsatiladigan tugma matni (boshidagi oddiy emoji siz)."""
    return text.split(" ", 1)[1] if " " in text else text


# Ikonkali tugma bosilganda Telegram faqat label ni yuboradi — handlerlar
# to'liq matnni ("🔎 Anime izlash") kutadi, shuning uchun qaytarib tiklaymiz.
MENU_LABEL_TO_TEXT: dict[str, str] = {menu_icon_label(t): t for t in MENU_ICON_IDS}


def _base(emoji: str | None) -> str:
    """Variation selector (U+FE0F) siz solishtirish uchun."""
    return (emoji or "").replace("️", "")


async def resolve_custom_emojis(bot: Bot) -> None:
    known = {e: i for e, i in EMOJI_IDS.items() if i}
    pack_name = CUSTOM_EMOJI_PACK

    if known:
        try:
            stickers = await bot.get_custom_emoji_stickers(custom_emoji_ids=list(known.values()))
        except Exception as e:
            logger.warning("[custom-emoji] ID larni tekshirib bo'lmadi: %s", e)
            stickers = None
        if stickers is not None:
            valid = {s.custom_emoji_id: s for s in stickers}
            for emoji, emoji_id in known.items():
                if emoji_id not in valid:
                    logger.warning("[custom-emoji] %s yaroqsiz ID, o'chirildi: %s", emoji, emoji_id)
                    EMOJI_IDS[emoji] = None
                elif not pack_name and valid[emoji_id].set_name:
                    pack_name = valid[emoji_id].set_name

    if pack_name:
        try:
            sticker_set = await bot.get_sticker_set(name=pack_name)
        except Exception as e:
            logger.warning("[custom-emoji] '%s' to'plamini o'qib bo'lmadi: %s", pack_name, e)
            sticker_set = None
        if sticker_set is not None:
            by_emoji: dict[str, str] = {}
            for sticker in sticker_set.stickers:
                if sticker.custom_emoji_id:
                    by_emoji.setdefault(_base(sticker.emoji), sticker.custom_emoji_id)
            for emoji, emoji_id in EMOJI_IDS.items():
                if not emoji_id and _base(emoji) in by_emoji:
                    EMOJI_IDS[emoji] = by_emoji[_base(emoji)]

    menu_ids = [i for i in MENU_ICON_IDS.values() if i]
    if menu_ids:
        try:
            stickers = await bot.get_custom_emoji_stickers(custom_emoji_ids=menu_ids)
        except Exception as e:
            logger.warning("[custom-emoji] menyu ikonkalarini tekshirib bo'lmadi: %s", e)
            stickers = None
        if stickers is not None:
            valid_ids = {s.custom_emoji_id for s in stickers}
            for text, emoji_id in MENU_ICON_IDS.items():
                if emoji_id and emoji_id not in valid_ids:
                    logger.warning("[custom-emoji] menyu '%s' ikonkasi yaroqsiz: %s", text, emoji_id)
                    MENU_ICON_IDS[text] = None

    found = [e for e, i in EMOJI_IDS.items() if i]
    missing = [e for e, i in EMOJI_IDS.items() if not i]
    logger.info(
        "[custom-emoji] to'plam=%s | animatsiyali: %s | oddiy: %s",
        pack_name or "—", "".join(found) or "—", "".join(missing) or "—",
    )
    logger.info(
        "[custom-emoji] menyu ikonkalari: %d/%d",
        sum(1 for i in MENU_ICON_IDS.values() if i), len(MENU_ICON_IDS),
    )


class MenuIconTextMiddleware:
    """Ikonkali menyu tugmasidan kelgan label ni to'liq tugma matniga qaytaradi.

    Update darajasida (NavigationStateClearMiddleware dan oldin) ulanadi, shunda
    FSM tozalash va F.text == "🔎 Anime izlash" filtrlari o'zgarishsiz ishlaydi.
    """

    async def __call__(self, handler, event, data):
        message = getattr(event, "message", None)
        text = getattr(message, "text", None)
        if text and text in MENU_LABEL_TO_TEXT:
            event = event.model_copy(
                update={"message": message.model_copy(update={"text": MENU_LABEL_TO_TEXT[text]})}
            )
        return await handler(event, data)


# ─── Admin yozgan matndagi custom emoji larni saqlash ─────────────────────────
# Telegram custom emoji ni matn ichida emas, alohida entity (offset/length UTF-16
# bo'yicha) sifatida yuboradi. message.text ni o'zini saqlasak ular yo'qoladi,
# shuning uchun matnni <tg-emoji> teglari bilan HTML ko'rinishida saqlaymiz.

_RAW_HTML_RE = re.compile(
    r"</?(b|strong|i|em|u|ins|s|strike|del|a|code|pre|blockquote|tg-spoiler|tg-emoji|span)\b",
    re.IGNORECASE,
)
_TG_EMOJI_RE = re.compile(r"<tg-emoji\b[^>]*>(.*?)</tg-emoji>", re.IGNORECASE | re.DOTALL)


def _insert_custom_emoji_tags(text: str, entities) -> str:
    """Xom matnga faqat <tg-emoji> teglarini qo'yadi (offsetlar UTF-16 da)."""
    raw = text.encode("utf-16-le")
    parts: list[str] = []
    pos = 0
    for e in sorted(entities, key=lambda e: e.offset):
        start, end = e.offset * 2, (e.offset + e.length) * 2
        if start < pos:
            continue
        parts.append(raw[pos:start].decode("utf-16-le"))
        emoji = raw[start:end].decode("utf-16-le")
        parts.append(f'<tg-emoji emoji-id="{e.custom_emoji_id}">{emoji}</tg-emoji>')
        pos = end
    parts.append(raw[pos:].decode("utf-16-le"))
    return "".join(parts)


def message_to_html(text: str, entities) -> str:
    """Admin xabarini custom emoji va formatlash bilan HTML ga aylantiradi.

    Admin teglarni qo'lda yozgan bo'lsa (<b> va h.k.) matn o'zgarmaydi, faqat
    custom emoji lar <tg-emoji> bilan o'raladi. Aks holda Telegram entity lari
    (qalin, havola, custom emoji...) to'liq HTML ga o'giriladi.
    """
    entities = list(entities or [])
    if not text or not entities:
        return text
    if _RAW_HTML_RE.search(text):
        return _insert_custom_emoji_tags(
            text, [e for e in entities if e.type == "custom_emoji"]
        )
    return html_decoration.unparse(text, entities)


def strip_custom_emoji(text: str) -> str:
    """<tg-emoji> teglarini olib tashlaydi — ichidagi oddiy emoji qoladi."""
    return _TG_EMOJI_RE.sub(r"\1", text)
