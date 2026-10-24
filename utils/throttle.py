import time
from collections import defaultdict, deque
from typing import Any, Awaitable, Callable

from aiogram import BaseMiddleware


class UserRateLimitMiddleware(BaseMiddleware):
    """Per-user Telegram update throttle for messages and callbacks."""

    def __init__(self, limit: int = 80, window_seconds: int = 60):
        self.limit = max(1, int(limit))
        self.window_seconds = max(1, int(window_seconds))
        self._hits: dict[int, deque[float]] = defaultdict(deque)
        self._last_notice: dict[int, float] = {}

    async def __call__(
        self,
        handler: Callable[[Any, dict[str, Any]], Awaitable[Any]],
        event: Any,
        data: dict[str, Any],
    ) -> Any:
        user = data.get("event_from_user") or getattr(event, "from_user", None)
        if not user:
            return await handler(event, data)

        now = time.monotonic()
        hits = self._hits[int(user.id)]
        while hits and now - hits[0] > self.window_seconds:
            hits.popleft()

        if len(hits) >= self.limit:
            await self._notify_once(event, int(user.id), now)
            return None

        hits.append(now)
        return await handler(event, data)

    async def _notify_once(self, event: Any, user_id: int, now: float) -> None:
        if now - self._last_notice.get(user_id, 0.0) < 10:
            return
        self._last_notice[user_id] = now
        try:
            if hasattr(event, "answer"):
                if event.__class__.__name__ == "CallbackQuery":
                    await event.answer("Juda ko'p so'rov. Biroz kuting.", show_alert=True)
                else:
                    await event.answer("⚠️ Juda ko'p so'rov. Biroz kutib qayta urinib ko'ring.")
        except Exception:
            pass
