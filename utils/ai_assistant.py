import json
import re
import hashlib
import aiohttp
import asyncio
from collections import OrderedDict
from typing import Any, Dict, Optional

from config import AI_API_KEY, AI_BASE_URL, AI_MODEL


class LRUCache:
    def __init__(self, maxsize: int = 100, ttl_seconds: int = 3600):
        self.maxsize = maxsize
        self.ttl_seconds = ttl_seconds
        self.cache: OrderedDict[str, tuple[Any, float]] = OrderedDict()

    def _cleanup(self):
        import time
        now = time.time()
        keys_to_del = []
        for key, (_, timestamp) in self.cache.items():
            if now - timestamp > self.ttl_seconds:
                keys_to_del.append(key)
        for key in keys_to_del:
            del self.cache[key]

    def get(self, key: str) -> Optional[Any]:
        self._cleanup()
        if key not in self.cache:
            return None
        self.cache.move_to_end(key)
        return self.cache[key][0]

    def set(self, key: str, value: Any):
        import time
        self._cleanup()
        if len(self.cache) >= self.maxsize:
            self.cache.popitem(last=False)
        self.cache[key] = (value, time.time())


_cache = LRUCache(maxsize=200, ttl_seconds=1800)


def _hash_prompt(system_prompt: str, user_prompt: str, temperature: float, max_tokens: int, model: str) -> str:
    combined = f"{system_prompt}|{user_prompt}|{temperature}|{max_tokens}|{model}"
    return hashlib.md5(combined.encode()).hexdigest()


async def chat_with_ai(
    system_prompt: str,
    user_prompt: str,
    temperature: float = 0.3,
    max_tokens: int = 500,
    retries: int = 2,
    use_cache: bool = True
) -> Optional[str]:
    """OpenAI-compatible Chat Completions orqali javob oladi. Xato bo'lsa None qaytaradi."""
    if not AI_API_KEY:
        return None

    model = AI_MODEL or "gpt-4o-mini"
    cache_key = _hash_prompt(system_prompt, user_prompt, temperature, max_tokens, model)

    if use_cache:
        cached = _cache.get(cache_key)
        if cached is not None:
            return cached

    payload = {
        "model": model,
        "temperature": temperature,
        "max_tokens": max_tokens,
        "messages": [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_prompt},
        ],
    }

    for attempt in range(retries + 1):
        try:
            async with aiohttp.ClientSession() as session:
                async with session.post(
                    f"{AI_BASE_URL}/chat/completions",
                    headers={
                        "Authorization": f"Bearer {AI_API_KEY}",
                        "Content-Type": "application/json",
                    },
                    json=payload,
                    timeout=aiohttp.ClientTimeout(total=30),
                ) as resp:
                    if resp.status == 429:
                        if attempt < retries:
                            retry_after = int(resp.headers.get("Retry-After", 2 ** (attempt + 1)))
                            await asyncio.sleep(retry_after)
                            continue
                        return None

                    data = await resp.json()

                    try:
                        result = data["choices"][0]["message"]["content"].strip()
                        if use_cache:
                            _cache.set(cache_key, result)
                        return result
                    except (KeyError, IndexError):
                        return None
        except Exception:
            if attempt < retries:
                await asyncio.sleep(2 ** (attempt + 1))
                continue
            return None

    return None


def sanitize_ai_text(text: str, max_len: int = 260) -> str:
    """AI javobidan markdown/ortiqcha belgilarni tozalaydi."""
    if not text:
        return ""

    cleaned = text.replace("\r", " ").replace("\n", " ")
    cleaned = re.sub(r"\[(.*?)\]\((.*?)\)", r"\1", cleaned)
    cleaned = re.sub(r"[*_`~#>\[\]\(\)]", "", cleaned)
    cleaned = re.sub(r"<[^>]+>", "", cleaned)
    cleaned = re.sub(r"\s{2,}", " ", cleaned).strip(" -:;,.")

    if len(cleaned) > max_len:
        cleaned = cleaned[:max_len].rsplit(" ", 1)[0].strip(" -:;,.") + "..."

    return cleaned


async def generate_anime_tavsif(
    nom: str,
    janr: str = "",
    holat: str = "",
    qism: str = "",
    yil: str = "",
    til: str = "",
    davlat: str = "",
) -> str:
    """Anime uchun qisqa tavsif generatsiya qiladi (markdownsiz)."""
    system_prompt = (
        "Siz anime tavsif yozuvchi yordamchisiz. "
        "Faqat o'zbek tilida 1-2 gap yozing. "
        "Matn oddiy bo'lsin, markdown belgilar (*, _, #, `, [ ]) ishlatmang."
    )
    user_prompt = (
        f"Anime nomi: {nom}\n"
        f"Janr: {janr or 'Noma`lum'}\n"
        f"Holati: {holat or 'Noma`lum'}\n"
        f"Qismlar: {qism or 'Noma`lum'}\n"
        f"Yili: {yil or 'Noma`lum'}\n"
        f"Tili: {til or 'Noma`lum'}\n"
        f"Davlat: {davlat or 'Noma`lum'}\n\n"
        "Natija: mazkur anime haqida qisqa va qiziqarli tavsif."
    )

    raw = await chat_with_ai(system_prompt, user_prompt, temperature=0.4, max_tokens=180)
    return sanitize_ai_text(raw or "")


async def support_ai_triage(user_text: str, faq_items: list, main_bot_username: str = "") -> dict | None:
    """
    Support savoliga AI javob + eskalatsiya qarorini qaytaradi:
    {"reply": "...", "escalate": true|false}
    """
    faq_lines = []
    for item in faq_items[:12]:
        # item format: (id, question, answer, order_num)
        faq_lines.append(f"Q: {item[1]}\nA: {item[2]}")
    faq_text = "\n\n".join(faq_lines) if faq_lines else "FAQ mavjud emas."

    main_bot = f"@{main_bot_username}" if main_bot_username else "asosiy bot"

    system_prompt = (
        "You are an Uzbek Telegram support assistant for anime bot users. "
        "Answer in Uzbek, concise and practical. "
        "If issue is account-specific, payment proof, VIP approval, ban, or anything that needs human action, set escalate=true. "
        "Otherwise set escalate=false. "
        "Return STRICT JSON only with keys: reply (string), escalate (boolean)."
    )
    user_prompt = (
        f"Main bot: {main_bot}\n\n"
        f"FAQ:\n{faq_text}\n\n"
        f"User message:\n{user_text}"
    )

    raw = await chat_with_ai(system_prompt, user_prompt, temperature=0.2, max_tokens=350)
    if not raw:
        return None

    try:
        parsed = json.loads(raw)
        reply = str(parsed.get("reply", "")).strip()
        escalate = bool(parsed.get("escalate", True))
        if not reply:
            return None
        return {"reply": reply, "escalate": escalate}
    except Exception:
        return None
