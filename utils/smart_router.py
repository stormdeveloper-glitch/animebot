def detect_tool_fast(text: str):
    t = text.lower().strip()

    # 🔗 link → downloader
    if "http" in t:
        return "downloader"

    # @username → checker
    if t.startswith("@"):
        return "checker"

    # telegram kanal → stats
    if "t.me/" in t:
        return "stats"

    # anime keyword
    if any(x in t for x in ["anime", "qism", "episode"]):
        return "anime"

    # default → pinterest
    return "pinterest"