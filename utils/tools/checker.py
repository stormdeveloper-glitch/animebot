import requests
from aiogram import types

HEADERS = {
    "User-Agent": "Mozilla/5.0"
}


def check_username(username):
    username = username.replace("@", "").strip()

    if not username:
        return "invalid"

    url = f"https://t.me/{username}"

    try:
        res = requests.get(url, headers=HEADERS, timeout=5)

        if res.status_code == 200:
            if "tgme_page_title" in res.text:
                return "taken"
        return "free"

    except:
        return "error"


async def handle(message: types.Message):
    text = message.text.strip()

    if not text.startswith("@"):
        await message.answer("❌ Username yubor (@ bilan)")
        return

    await message.answer("🔎 Tekshirilmoqda...")

    status = check_username(text)

    if status == "taken":
        await message.answer(f"❌ {text} band")
    elif status == "free":
        await message.answer(f"✅ {text} bo'sh")
    elif status == "invalid":
        await message.answer("⚠️ Noto'g'ri username")
    else:
        await message.answer("❌ Xatolik")
