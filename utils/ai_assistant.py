import json
import re
import aiohttp

from config import AI_API_KEY, AI_BASE_URL, AI_MODEL


async def chat_with_ai(system_prompt: str, user_prompt: str, temperature: float = 0.3, max_tokens: int = 500):
    """OpenAI-compatible Chat Completions orqali javob oladi. Xato bo'lsa None qaytaradi."""
    if not AI_API_KEY:
        return None

    payload = {
        "model": AI_MODEL or "gpt-4o-mini",
        "temperature": temperature,
        "max_tokens": max_tokens,
        "messages": [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_prompt},
        ],
    }

    try:
        async with aiohttp.ClientSession() as session:
            async with session.post(
                f"{AI_BASE_URL}/chat/completions",
                headers={
                    "Authorization": f"Bearer {AI_API_KEY}",
                    "Content-Type": "application/json",
                },
                json=payload,
                timeout=aiohttp.ClientTimeout(total=20),
            ) as resp:
                data = await resp.json()
    except Exception:
        return None

    try:
        return data["choices"][0]["message"]["content"].strip()
    except Exception:
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
