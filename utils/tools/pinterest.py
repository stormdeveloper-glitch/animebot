import requests
from bs4 import BeautifulSoup
from aiogram import types
from aiogram.types import InputMediaPhoto


HEADERS = {
    "User-Agent": "Mozilla/5.0",
    "Accept-Language": "en-US,en;q=0.9"
}


def extract_images(html, limit=15):
    soup = BeautifulSoup(html, "html.parser")
    images = []

    for img in soup.find_all("img"):
        src = img.get("src")
        if not src:
            continue
        if any(x in src for x in ["60x60", "75x75", "236x"]):
            continue
        if "originals" in src or "736x" in src:
            images.append(src)

    if not images:
        for img in soup.find_all("img"):
            src = img.get("src")
            if src:
                images.append(src)

    return list(dict.fromkeys(images))[:limit]


def search_pinterest(query, limit=10):
    url = f"https://www.pinterest.com/search/pins/?q={query}"
    try:
        res = requests.get(url, headers=HEADERS, timeout=10)
        if res.status_code != 200:
            return []
        return extract_images(res.text, limit)
    except:
        return []


async def handle(message: types.Message):
    query = message.text.strip()

    if not query:
        await message.answer("❌ So'rov yuborilmadi")
        return

    await message.answer("🔍 Qidirilyapti...")

    images = search_pinterest(query, limit=8)

    if not images:
        await message.answer("❌ Hech narsa topilmadi")
        return

    sent = 0
    for img in images:
        try:
            await message.answer_photo(img)
            sent += 1
        except:
            continue

    if sent == 0:
        await message.answer("❌ Rasm yuborib bo'lmadi")
