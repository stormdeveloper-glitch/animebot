"""Animatsiyali (custom) emoji ID larini boshqarish.

Bot ishga tushganda resolve_custom_emojis():
  1. Ma'lum ID larni Telegram orqali tekshiradi (yaroqsizlari o'chiriladi).
  2. Emoji to'plamini aniqlaydi: CUSTOM_EMOJI_PACK yoki ✨ ID si tegishli to'plam.
  3. Shu to'plamdan ID si yo'q emoji larga mos animatsiyani o'zi topadi.
Topilmagan emoji oddiy ko'rinishda qoladi — noto'g'ri animatsiya chiqmaydi.
"""
import logging
import os

from aiogram import Bot

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
