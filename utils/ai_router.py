import asyncio
import aiohttp
from config import AI_API_KEY, AI_BASE_URL, AI_MODEL

ALLOWED = {"pinterest", "downloader", "checker", "stats", "anime"}


async def _detect_tool_ai_async(text: str):
    if not AI_API_KEY:
        return None
    try:
        async with aiohttp.ClientSession() as session:
            async with session.post(
                f"{AI_BASE_URL}/chat/completions",
                headers={
                    "Authorization": f"Bearer {AI_API_KEY}",
                    "Content-Type": "application/json"
                },
                json={
                    "model": AI_MODEL or "gpt-4o-mini",
                    "temperature": 0,
                    "messages": [
                        {
                            "role": "system",
                            "content": (
                                "You are a strict router. "
                                "Return ONLY one word from this list:\n"
                                "pinterest, downloader, checker, stats, anime.\n"
                                "Do not explain anything. No extra text."
                            )
                        },
                        {
                            "role": "user",
                            "content": text
                        }
                    ]
                },
                timeout=aiohttp.ClientTimeout(total=10)
            ) as res:
                data = await res.json()
    except Exception:
        return None

    try:
        tool = data["choices"][0]["message"]["content"].strip().lower()
    except Exception:
        return None

    if tool in ALLOWED:
        return tool
    return None


def detect_tool_ai(text: str):
    """
    Sync wrapper:
    - event loop ichida ishlasa bloklamaslik uchun None qaytaradi
    - loop tashqarisida asyncio.run orqali ishlaydi
    """
    try:
        asyncio.get_running_loop()
        return None
    except RuntimeError:
        return asyncio.run(_detect_tool_ai_async(text))
