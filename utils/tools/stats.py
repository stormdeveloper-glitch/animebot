from aiogram import types


def normalize_username(text):
    text = text.strip()
    if "t.me/" in text:
        return text.split("t.me/")[-1].strip()
    return text.replace("@", "").strip()


async def get_channel_info(bot, username):
    try:
        chat = await bot.get_chat(f"@{username}")
        members = None
        try:
            members = await bot.get_chat_member_count(f"@{username}")
        except:
            pass
        return {
            "title": chat.title,
            "username": username,
            "type": chat.type,
            "members": members
        }
    except:
        return None


async def handle(message: types.Message):
    text = message.text.strip()
    username = normalize_username(text)

    if not username:
        await message.answer("❌ Username yubor (@ yoki link)")
        return

    await message.answer("📊 Tekshirilmoqda...")

    info = await get_channel_info(message.bot, username)

    if not info:
        await message.answer("❌ Kanal topilmadi yoki private")
        return

    msg = (
        f"📢 {info['title']}\n"
        f"👤 @{info['username']}\n"
        f"📦 Turi: {info['type']}\n"
        f"👥 Obunachilar: {info['members'] if info['members'] else 'Nomaʼlum'}"
    )

    await message.answer(msg)
