import logging
import re
from functools import wraps
from typing import Any

try:  # aiogram mavjud bo'lmasa ham modul yuklanishi kerak
    from aiogram.exceptions import TelegramBadRequest
except Exception:  # pragma: no cover
    TelegramBadRequest = None  # type: ignore[assignment]


logger = logging.getLogger(__name__)


MOJIBAKE_RE = re.compile(
    r"[ -ÿŒœŠšŸŽžˆ˜€"
    r"–—‘’‚“”„†‡•…‰‹›™]+"
)


def fix_mojibake_text(value: Any) -> Any:
    """Repair common UTF-8-as-Windows-1252 mojibake before sending text."""
    if not isinstance(value, str) or not value:
        return value

    def repair(match: re.Match[str]) -> str:
        chunk = match.group(0)
        try:
            return chunk.encode("cp1252").decode("utf-8")
        except (UnicodeEncodeError, UnicodeDecodeError):
            return chunk

    previous = None
    fixed = value
    # Some text can be double-mojibaked; keep this bounded.
    for _ in range(2):
        if fixed == previous:
            break
        previous = fixed
        fixed = MOJIBAKE_RE.sub(repair, fixed)
    return fixed


def sanitize_reply_markup(markup: Any) -> Any:
    if not markup:
        return markup
    rows = getattr(markup, "inline_keyboard", None) or getattr(markup, "keyboard", None)
    if not rows:
        return markup
    for row in rows:
        for button in row:
            text = getattr(button, "text", None)
            if isinstance(text, str):
                try:
                    button.text = fix_mojibake_text(text)
                except Exception:
                    pass
    return markup


def sanitize_send_kwargs(kwargs: dict[str, Any]) -> dict[str, Any]:
    for key in ("text", "caption"):
        if key in kwargs:
            kwargs[key] = fix_mojibake_text(kwargs[key])
    if "reply_markup" in kwargs:
        kwargs["reply_markup"] = sanitize_reply_markup(kwargs["reply_markup"])
    return kwargs


# Formatlash xatosi (masalan, rad etilgan <tg-emoji> yoki buzilgan HTML) uchun izlar
PARSE_ERROR_MARKERS = (
    "can't parse entities",
    "can't parse",
    "unsupported start tag",
    "wrong message entity",
)

_TAG_RE = re.compile(r"</?[a-zA-Z][^>]*>")


def _is_parse_error(exc: Exception) -> bool:
    text = str(exc).lower()
    return any(marker in text for marker in PARSE_ERROR_MARKERS)


def _strip_formatting(args: tuple, kwargs: dict[str, Any], text_index: int | None) -> tuple:
    """parse_mode ni olib tashlaydi va HTML teglarini matndan tozalaydi."""
    kwargs = dict(kwargs)
    kwargs.pop("parse_mode", None)
    for key in ("text", "caption"):
        if isinstance(kwargs.get(key), str):
            kwargs[key] = _TAG_RE.sub("", kwargs[key])
    if text_index is not None and len(args) > text_index and isinstance(args[text_index], str):
        args = list(args)
        args[text_index] = _TAG_RE.sub("", args[text_index])
        args = tuple(args)
    return args, kwargs


def _wrap_async_method(cls: type, method_name: str, text_index: int | None = None) -> None:
    original = getattr(cls, method_name, None)
    if not original or getattr(original, "_az_sanitized", False):
        return

    @wraps(original)
    async def wrapper(self, *args, **kwargs):
        args = list(args)
        if text_index is not None and len(args) > text_index:
            args[text_index] = fix_mojibake_text(args[text_index])
        sanitize_send_kwargs(kwargs)
        try:
            return await original(self, *args, **kwargs)
        except Exception as exc:
            # Telegram xabarni formatlash xatosi sababli rad etsa — foydalanuvchi
            # umuman javob olmaydi. Shu sababli formatlashsiz (tegsiz) qayta
            # yuboramiz va xatoni logga yozamiz.
            if (
                TelegramBadRequest is None
                or not isinstance(exc, TelegramBadRequest)
                or not kwargs.get("parse_mode")
                or not _is_parse_error(exc)
            ):
                raise
            logger.warning(
                "[send-fallback] %s formatlash xatosi — parse_mode'siz qayta yuborildi: %s",
                type(self).__name__,
                exc,
            )
            args, kwargs = _strip_formatting(tuple(args), kwargs, text_index)
            return await original(self, *args, **kwargs)

    wrapper._az_sanitized = True
    setattr(cls, method_name, wrapper)


def patch_aiogram_text_sanitizer() -> None:
    """Patch common aiogram send/edit methods to filter mojibake globally."""
    try:
        from aiogram import Bot
        from aiogram.types import CallbackQuery, Message
    except Exception:
        return

    for name in ("answer", "reply", "edit_text"):
        _wrap_async_method(Message, name, text_index=0)
    for name in ("answer_photo", "answer_video", "answer_document", "reply_photo", "reply_video", "reply_document"):
        _wrap_async_method(Message, name)

    _wrap_async_method(CallbackQuery, "answer", text_index=0)

    _wrap_async_method(Bot, "send_message", text_index=1)
    _wrap_async_method(Bot, "edit_message_text", text_index=0)
    for name in ("send_photo", "send_video", "send_document", "edit_message_caption"):
        _wrap_async_method(Bot, name)
