from utils.smart_router import detect_tool_fast
from utils.ai_router import detect_tool_ai

# 🔒 ruxsat berilgan tool lar
ALLOWED = {
    "pinterest",
    "downloader",
    "checker",
    "stats",
    "anime",
    "admin"
}


def detect_tool(text: str):
    if not text:
        return None

    text = text.strip()

    # ⚡ 1. FAST LOGIC (eng tez)
    tool = detect_tool_fast(text)

    if tool in ALLOWED:
        return tool

    # 🤖 2. AI FALLBACK
    ai_tool = detect_tool_ai(text)

    if ai_tool in ALLOWED:
        return ai_tool

    # 🔥 3. FINAL FALLBACK
    return "pinterest"