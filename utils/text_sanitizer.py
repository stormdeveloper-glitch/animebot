import re
from functools import wraps
from typing import Any


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
