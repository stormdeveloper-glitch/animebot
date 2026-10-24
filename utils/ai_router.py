import asyncio

from utils.ai_provider import chat_completion

ALLOWED = {"pinterest", "downloader", "checker", "stats", "anime"}


async def _detect_tool_ai_async(text: str):
    result = await chat_completion(
        [
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
        ],
        temperature=0,
        max_tokens=8,
        timeout=12,
        max_attempts=2,
    )
    if not result:
        return None

    tool = result.strip().lower().strip(".,`'\"")
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
