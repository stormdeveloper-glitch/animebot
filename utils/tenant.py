"""Klon botlar uchun "tenant" (qaysi bot nomidan ishlayapmiz) konteksti.

Har bir klon bot o'zining alohida SQLite bazasiga ega (data/clones/<bot_id>.db).
Handlerlar hamma joyda aiosqlite.connect(DB_PATH) chaqiradi — install_db_router()
shu chaqiruvni joriy tenant bazasiga yo'naltiradi, shuning uchun handlerlarni
o'zgartirmasdan har bir klonning foydalanuvchilari, sozlamalari, kanallari va
animelari alohida bo'ladi. Asosiy bot (va web server) uchun tenant None.
"""
import os
from contextvars import ContextVar

import aiosqlite
from aiogram import BaseMiddleware

from config import BOT_TOKEN, DATA_DIR, DB_PATH

CLONES_DIR = os.path.join(DATA_DIR, "clones")

try:
    MAIN_BOT_ID = int(BOT_TOKEN.split(":", 1)[0])
except (ValueError, AttributeError):
    MAIN_BOT_ID = 0

# Joriy klon bot ID si (None — asosiy bot)
_current_tenant: ContextVar[int | None] = ContextVar("current_tenant", default=None)
# Klon egasi (owner) — tenant bilan birga o'rnatiladi
_current_owner: ContextVar[int | None] = ContextVar("current_owner", default=None)


def current_tenant() -> int | None:
    return _current_tenant.get()


def current_owner() -> int | None:
    return _current_owner.get()


def set_tenant(bot_id: int | None, owner_id: int | None = None):
    """Kontekstni o'rnatadi; qaytgan tokenlar reset_tenant() ga beriladi."""
    return _current_tenant.set(bot_id), _current_owner.set(owner_id)


def reset_tenant(tokens) -> None:
    tenant_token, owner_token = tokens
    _current_tenant.reset(tenant_token)
    _current_owner.reset(owner_token)


def tenant_db_path(bot_id: int) -> str:
    return os.path.join(CLONES_DIR, f"{int(bot_id)}.db")


_original_connect = aiosqlite.connect


def _routed_connect(database, *args, **kwargs):
    tenant = _current_tenant.get()
    if tenant and os.fspath(database) == DB_PATH:
        database = tenant_db_path(tenant)
    return _original_connect(database, *args, **kwargs)


def install_db_router() -> None:
    """aiosqlite.connect(DB_PATH) ni joriy tenant bazasiga yo'naltiradi."""
    os.makedirs(CLONES_DIR, exist_ok=True)
    aiosqlite.connect = _routed_connect


def main_db_connect(*args, **kwargs):
    """Tenantdan qat'i nazar asosiy bazaga ulanish (klonlar ro'yxati uchun)."""
    return _original_connect(DB_PATH, *args, **kwargs)


class TenantMiddleware(BaseMiddleware):
    """Update qaysi bot orqali kelganiga qarab tenant kontekstini o'rnatadi."""

    async def __call__(self, handler, event, data):
        bot = data.get("bot")
        bot_id = getattr(bot, "id", None)
        if not bot_id or bot_id == MAIN_BOT_ID:
            return await handler(event, data)

        from utils.clones import clone_owner
        tokens = set_tenant(bot_id, clone_owner(bot_id))
        try:
            return await handler(event, data)
        finally:
            reset_tenant(tokens)
