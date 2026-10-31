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

    found = [e for e, i in EMOJI_IDS.items() if i]
    missing = [e for e, i in EMOJI_IDS.items() if not i]
    logger.info(
        "[custom-emoji] to'plam=%s | animatsiyali: %s | oddiy: %s",
        pack_name or "—", "".join(found) or "—", "".join(missing) or "—",
    )


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
