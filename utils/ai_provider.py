"""
Yagona AI provayder qatlami.

Qoidalar:
- Faqat BEPUL modellar ishlatiladi (OpenRouter `pricing.prompt/completion == 0`).
- Bitta model limitiga yetsa (429/402/5xx/timeout), u cooldown'ga o'tadi va
  so'rov avtomatik keyingi modelga uzatiladi.
- OpenAI/ChatGPT ishlatilmaydi.

Bu modul `utils.ai_assistant`, `utils.ai_router` va `web_server.get_ai_reply`
uchun yagona kirish nuqtasidir.
"""

from __future__ import annotations

import time

import aiohttp

from config import (
    AI_MAX_MODEL_ATTEMPTS,
    AI_MODEL_COOLDOWN_SECONDS,
    AI_PROVIDER_ORDER,
    GROQ_API_KEY,
    GROQ_MODEL_GENERAL,
    OPENROUTER_API_KEY,
    OPENROUTER_APP_NAME,
    OPENROUTER_BASE_URL,
    OPENROUTER_MODELS,
    OPENROUTER_SITE_URL,
)

_FREE_MODELS_TTL = 3600
_FREE_MODELS_FALLBACK = [
    "meta-llama/llama-3.3-70b-instruct:free",
    "deepseek/deepseek-chat-v3-0324:free",
    "qwen/qwen-2.5-72b-instruct:free",
    "google/gemma-3-27b-it:free",
    "mistralai/mistral-small-3.1-24b-instruct:free",
]

_PREFERRED_KEYWORDS = (
    "deepseek",
    "llama-3.3-70b",
    "qwen-2.5-72b",
    "gpt-oss",
    "gemma-3-27b",
    "mistral-small",
    "llama-3.1-70b",
)

_free_models_cache: dict = {"ts": 0.0, "models": []}
_cooldowns: dict[str, float] = {}
_last_used: dict[str, str] = {}


def _is_free_model(model: dict) -> bool:
    pricing = model.get("pricing") or {}
    try:
        prompt = float(pricing.get("prompt") or 0)
        completion = float(pricing.get("completion") or 0)
    except (TypeError, ValueError):
        return False
    if prompt != 0 or completion != 0:
        return False
    modality = ((model.get("architecture") or {}).get("modality") or "text").lower()
    return "text" in modality


def _sort_key(model: dict) -> tuple:
    model_id = model.get("id", "").lower()
    for index, keyword in enumerate(_PREFERRED_KEYWORDS):
        if keyword in model_id:
            return (index, len(model_id), model_id)
    return (len(_PREFERRED_KEYWORDS), len(model_id), model_id)


async def _fetch_free_models() -> list[str]:
    if not OPENROUTER_API_KEY:
        return []
    try:
        async with aiohttp.ClientSession() as session:
            async with session.get(
                f"{OPENROUTER_BASE_URL}/models",
                headers={"Authorization": f"Bearer {OPENROUTER_API_KEY}"},
                timeout=aiohttp.ClientTimeout(total=10),
            ) as resp:
                if resp.status != 200:
                    return []
                data = await resp.json()
    except Exception:
        return []

    models = [m for m in (data.get("data") or []) if isinstance(m, dict) and _is_free_model(m)]
    models.sort(key=_sort_key)
    return [m["id"] for m in models if m.get("id")]


async def get_free_models(force: bool = False) -> list[str]:
    """OpenRouter bepul modellari ro'yxati (1 soatga keshlanadi)."""
    if OPENROUTER_MODELS:
        return list(OPENROUTER_MODELS)

    now = time.time()
    if not force and _free_models_cache["models"] and now - _free_models_cache["ts"] < _FREE_MODELS_TTL:
        return list(_free_models_cache["models"])

    models = await _fetch_free_models()
    if models:
        _free_models_cache["ts"] = now
        _free_models_cache["models"] = models
        return list(models)

    if _free_models_cache["models"]:
        return list(_free_models_cache["models"])
    return list(_FREE_MODELS_FALLBACK)


def _cooldown_key(provider: str, model: str) -> str:
    return f"{provider}:{model}"


def _is_cooling(key: str) -> bool:
    until = _cooldowns.get(key, 0)
    return until > time.time()


def _mark_cooldown(key: str, retry_after: float | None = None) -> None:
    seconds = AI_MODEL_COOLDOWN_SECONDS
    if retry_after and retry_after > 0:
        seconds = min(max(retry_after, 5), 3600)
    _cooldowns[key] = time.time() + seconds


def _retry_after_seconds(resp: aiohttp.ClientResponse) -> float | None:
    for header in ("Retry-After", "X-RateLimit-Reset"):
        raw = resp.headers.get(header)
        if not raw:
            continue
        try:
            value = float(raw)
        except ValueError:
            continue
        # X-RateLimit-Reset ba'zan unix timestamp bo'ladi
        if value > 1_000_000_000:
            value = value - time.time()
        if value > 0:
            return value
    return None


async def _call_openrouter(
    model: str,
    messages: list[dict],
    temperature: float,
    max_tokens: int,
    timeout: float,
) -> tuple[bool, str | None, float | None]:
    headers = {
        "Authorization": f"Bearer {OPENROUTER_API_KEY}",
        "Content-Type": "application/json",
        "X-Title": OPENROUTER_APP_NAME or "ANIME UZ",
    }
    if OPENROUTER_SITE_URL:
        headers["HTTP-Referer"] = OPENROUTER_SITE_URL

    payload = {
        "model": model,
        "messages": messages,
        "temperature": temperature,
        "max_tokens": max_tokens,
    }
    try:
        async with aiohttp.ClientSession() as session:
            async with session.post(
                f"{OPENROUTER_BASE_URL}/chat/completions",
                headers=headers,
                json=payload,
                timeout=aiohttp.ClientTimeout(total=timeout),
            ) as resp:
                if resp.status != 200:
                    body = await resp.text()
                    print(f"⚠️ OpenRouter {model} xatosi ({resp.status}): {body[:200]}")
                    return False, None, _retry_after_seconds(resp)
                data = await resp.json()
    except Exception as exc:
        print(f"⚠️ OpenRouter {model} ulanish xatosi: {exc}")
        return False, None, None

    try:
        text = (data["choices"][0]["message"]["content"] or "").strip()
    except (KeyError, IndexError, TypeError):
        return False, None, None
    if not text:
        return False, None, None
    return True, text, None


async def _call_groq(
    model: str,
    messages: list[dict],
    temperature: float,
    max_tokens: int,
    timeout: float,
) -> tuple[bool, str | None, float | None]:
    payload = {
        "model": model,
        "messages": messages,
        "temperature": temperature,
        "max_tokens": max_tokens,
    }
    try:
        async with aiohttp.ClientSession() as session:
            async with session.post(
                "https://api.groq.com/openai/v1/chat/completions",
                headers={
                    "Authorization": f"Bearer {GROQ_API_KEY}",
                    "Content-Type": "application/json",
                },
                json=payload,
                timeout=aiohttp.ClientTimeout(total=timeout),
            ) as resp:
                if resp.status != 200:
                    body = await resp.text()
                    print(f"⚠️ Groq {model} xatosi ({resp.status}): {body[:200]}")
                    return False, None, _retry_after_seconds(resp)
                data = await resp.json()
    except Exception as exc:
        print(f"⚠️ Groq {model} ulanish xatosi: {exc}")
        return False, None, None

    try:
        text = (data["choices"][0]["message"]["content"] or "").strip()
    except (KeyError, IndexError, TypeError):
        return False, None, None
    if not text:
        return False, None, None
    return True, text, None


async def _candidates(max_attempts: int) -> list[tuple[str, str]]:
    candidates: list[tuple[str, str]] = []
    order = AI_PROVIDER_ORDER or ["openrouter"]

    if "openrouter" in order and OPENROUTER_API_KEY:
        for model in await get_free_models():
            candidates.append(("openrouter", model))

    if "groq" in order and GROQ_API_KEY:
        candidates.append(("groq", GROQ_MODEL_GENERAL))

    available = [(p, m) for p, m in candidates if not _is_cooling(_cooldown_key(p, m))]
    if len(available) < max_attempts:
        # Hammasi cooldown'da bo'lsa ham eng erta bo'shaydiganlarini sinab ko'ramiz.
        cooling = [(p, m) for p, m in candidates if _is_cooling(_cooldown_key(p, m))]
        cooling.sort(key=lambda pm: _cooldowns.get(_cooldown_key(*pm), 0))
        available.extend(cooling)

    return available[:max_attempts]


async def chat_completion(
    messages: list[dict],
    temperature: float = 0.5,
    max_tokens: int = 1024,
    timeout: float = 30,
    max_attempts: int | None = None,
    deadline: float | None = None,
) -> str | None:
    """Bepul modeldan javob oladi. Ishlaydigan model topilmasa None.

    `deadline` — `time.monotonic()` bo'yicha umumiy tugash vaqti. Berilsa,
    qolgan vaqtga qarab har bir model uchun timeout qisqartiriladi.
    """
    limit = max_attempts or AI_MAX_MODEL_ATTEMPTS
    candidates = await _candidates(limit)
    if not candidates:
        print("❌ AI provayder sozlanmagan (OPENROUTER_API_KEY / GROQ_API_KEY yo'q).")
        return None

    for provider, model in candidates:
        attempt_timeout = timeout
        if deadline is not None:
            remaining = deadline - time.monotonic()
            if remaining <= 3:
                break
            attempt_timeout = min(timeout, remaining)

        key = _cooldown_key(provider, model)
        if provider == "openrouter":
            ok, text, retry_after = await _call_openrouter(model, messages, temperature, max_tokens, attempt_timeout)
        else:
            ok, text, retry_after = await _call_groq(model, messages, temperature, max_tokens, attempt_timeout)

        if ok and text:
            _cooldowns.pop(key, None)
            _last_used["provider"] = provider
            _last_used["model"] = model
            return text

        _mark_cooldown(key, retry_after)

    print("❌ Barcha bepul AI modellari band yoki ishlamayapti.")
    return None


def last_used() -> dict:
    """Oxirgi muvaffaqiyatli provayder (log/debug uchun)."""
    return dict(_last_used)
