from aiogram import types
from aiogram.types import ReplyKeyboardMarkup, KeyboardButton
from config import SUPER_ADMIN_ID, DATA_DIR
import json, os

# Har ikki joy ham bir xil DB ishlatsin
ANIME_DB = os.path.join(DATA_DIR, "anime.json")

os.makedirs(DATA_DIR, exist_ok=True)


def load_db():
    if not os.path.exists(ANIME_DB):
        with open(ANIME_DB, "w") as f:
            json.dump([], f)
    with open(ANIME_DB) as f:
        return json.load(f)


def save_db(data):
    with open(ANIME_DB, "w") as f:
        json.dump(data, f, indent=2)


# ===== KEYBOARD (aiogram v3 uslubi) =====
def admin_menu():
    return ReplyKeyboardMarkup(
        keyboard=[
            [KeyboardButton(text="🎬 Anime")],
            [KeyboardButton(text="📊 Stats")],
            [KeyboardButton(text="⬅️ Exit")]
        ],
        resize_keyboard=True
    )


def anime_menu():
    return ReplyKeyboardMarkup(
        keyboard=[
            [KeyboardButton(text="➕ Add Anime"), KeyboardButton(text="➕ Add Episode")],
            [KeyboardButton(text="❌ Delete Anime"), KeyboardButton(text="📋 List Anime")],
            [KeyboardButton(text="⬅️ Back")]
        ],
        resize_keyboard=True
    )


# ===== STATE =====
admin_states = {}


# ===== FUNCTIONS =====
def add_anime(title, desc):
    data = load_db()
    data.append({
        "title": title,
        "description": desc,
        "episodes": []
    })
    save_db(data)


def add_episode(title, file_id):
    data = load_db()
    for a in data:
        if a["title"].lower() == title.lower():
            a["episodes"].append(file_id)
            save_db(data)
            return True
    return False


# ===== HANDLER =====
async def handle(message: types.Message):
    if message.from_user.id != SUPER_ADMIN_ID:
        return await message.answer("❌ Ruxsat yo'q")

    chat_id = message.chat.id
    text = message.text

    # ROOT
    if text == "/admin":
        return await message.answer("Admin panel", reply_markup=admin_menu())

    if text == "🎬 Anime":
        return await message.answer("Anime panel", reply_markup=anime_menu())

    # ADD ANIME
    if text == "➕ Add Anime":
        admin_states[chat_id] = "add_anime"
        return await message.answer("Format:\nnomi|desc")

    if admin_states.get(chat_id) == "add_anime":
        try:
            title, desc = text.split("|", 1)
            add_anime(title.strip(), desc.strip())
            admin_states.pop(chat_id)
            return await message.answer("✅ Qo'shildi")
        except:
            return await message.answer("❌ Format xato. Masalan: Naruto|Ninja haqida anime")

    # ADD EPISODE
    if text == "➕ Add Episode":
        admin_states[chat_id] = "episode_title"
        return await message.answer("Anime nomi:")

    if admin_states.get(chat_id) == "episode_title":
        admin_states[chat_id] = {"state": "episode_video", "title": text}
        return await message.answer("Video yubor")

    if isinstance(admin_states.get(chat_id), dict):
        st = admin_states[chat_id]

        if st["state"] == "episode_video":
            if not message.video:
                return await message.answer("❌ Video yubor")

            ok = add_episode(st["title"], message.video.file_id)
            admin_states.pop(chat_id)

            return await message.answer("✅ Qo'shildi" if ok else "❌ Anime topilmadi")

    # LIST
    if text == "📋 List Anime":
        data = load_db()
        return await message.answer("\n".join(a["title"] for a in data) or "Bo'sh")

    # DELETE
    if text == "❌ Delete Anime":
        admin_states[chat_id] = "delete"
        return await message.answer("Anime nomi:")

    if admin_states.get(chat_id) == "delete":
        data = load_db()
        data = [a for a in data if a["title"].lower() != text.lower()]
        save_db(data)
        admin_states.pop(chat_id)
        return await message.answer("🗑 O'chirildi")

    if text in ["⬅️ Exit", "⬅️ Back"]:
        admin_states.pop(chat_id, None)
        return await message.answer("Chiqildi")
