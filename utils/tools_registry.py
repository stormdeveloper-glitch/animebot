from utils.tools import (
    pinterest,
    downloader,
    checker,
    stats,
    anime,
    admin
)

TOOLS = {
    "pinterest": pinterest.handle,
    "downloader": downloader.handle,
    "checker": checker.handle,
    "stats": stats.handle,
    "anime": anime.handle,
    "admin": admin.handle
}


def get_tool(name: str):
    return TOOLS.get(name)


def tool_exists(name: str):
    return name in TOOLS


def list_tools():
    return list(TOOLS.keys())
