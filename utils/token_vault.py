"""Klon bot tokenlarini shifrlash (Fernet: AES-128-CBC + HMAC-SHA256).

Kalit faqat BOT_TOKEN_ENC_KEY muhit o'zgaruvchisida turadi — bazada faqat
shifrlangan matn saqlanadi. Kalit bo'lmasa klon yaratish o'chirilgan bo'ladi.
Token hech qachon logga, admin panelga yoki web API ga chiqarilmaydi.
"""
import hashlib
import hmac
import os

from cryptography.fernet import Fernet, InvalidToken

_KEY = os.getenv("BOT_TOKEN_ENC_KEY", "").strip()
_fernet: Fernet | None = None
if _KEY:
    try:
        _fernet = Fernet(_KEY.encode())
    except (ValueError, TypeError):
        _fernet = None


def vault_ready() -> bool:
    return _fernet is not None


def encrypt_token(token: str) -> str:
    if _fernet is None:
        raise RuntimeError("BOT_TOKEN_ENC_KEY o'rnatilmagan")
    return _fernet.encrypt(token.encode()).decode()


def decrypt_token(token_enc: str) -> str:
    if _fernet is None:
        raise RuntimeError("BOT_TOKEN_ENC_KEY o'rnatilmagan")
    try:
        return _fernet.decrypt(token_enc.encode()).decode()
    except InvalidToken as exc:
        raise RuntimeError("Token shifrini ochib bo'lmadi (kalit o'zgarganmi?)") from exc


def webhook_secret(bot_id: int) -> str:
    """Webhook so'rovi rostdan Telegram'dan kelganini tekshirish uchun sir."""
    return hmac.new(_KEY.encode(), f"webhook:{bot_id}".encode(), hashlib.sha256).hexdigest()
