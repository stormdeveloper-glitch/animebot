import json
import os
from aiogram import types
from config import DATA_DIR

DB_PATH = os.path.join(DATA_DIR, "anime.json")


def load_db():
    if not os.path.exists(DB_PATH):
        with open(DB_PATH, "w") as f:
            json.dump([], f)
    with open(DB_PATH, "r") as f:
        return json.load(f)


def save_db(data):
    with open(DB_PATH, "w") as f:
        json.dump(data, f, indent=2)


def search_anime(query):
    data = load_db()
    result = []
    for anime in data:
        if query.lower() in anime["title"].lower():
            result.append(anime)
    return result


def format_anime(anime):
    msg = f"🎬 {anime['title']}\n\n{anime['description']}"
    if anime.get("genres"):
        msg += f"\n\n🎭 {' ,'.join(anime['genres'])}"
    return msg


async def handle(message: types.Message):
    text = message.text.strip()

    results = search_anime(text)

    if not results:
        await message.answer("❌ Anime topilmadi")
        return

    for anime in results[:3]:
        await message.answer(format_anime(anime))

        for i, ep in enumerate(anime.get("episodes", [])[:5], start=1):
            await message.answer(f"🎥 {i}-qism: {ep}")
