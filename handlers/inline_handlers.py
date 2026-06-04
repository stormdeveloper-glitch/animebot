import aiosqlite
from aiogram import Router
from aiogram.types import (
    InlineQuery,
    InlineQueryResultCachedPhoto,
    InlineQueryResultCachedVideo,
    InlineQueryResultArticle,
    InputTextMessageContent,
    InlineKeyboardMarkup,
)
from config import DB_PATH, BOT_USERNAME
from keyboards import InlineKeyboardButton

router = Router()


@router.inline_query()
async def inline_search(query: InlineQuery):
    search_text = query.query.strip()

    async with aiosqlite.connect(DB_PATH) as db:
        if search_text:
            # 1) Avval to'liq mos keluvchilar (nom boshidan)
            async with db.execute(
                """
                SELECT id, nom, janri, rams, aniType, qismi, fandub, yili
                FROM animelar
                WHERE nom LIKE ?
                ORDER BY qidiruv DESC
                LIMIT 50
                """,
                (f"{search_text}%",)
            ) as cursor:
                starts_with = await cursor.fetchall()

            # 2) Ichida uchraydigan qolganlar
            starts_ids = {r[0] for r in starts_with}
            async with db.execute(
                """
                SELECT id, nom, janri, rams, aniType, qismi, fandub, yili
                FROM animelar
                WHERE nom LIKE ?
                ORDER BY qidiruv DESC
                LIMIT 50
                """,
                (f"%{search_text}%",)
            ) as cursor:
                contains = await cursor.fetchall()

            # 3) So'zma-so'z qidiruv — har bir so'z alohida tekshiriladi
            words = search_text.split()
            word_results = []
            if len(words) > 1:
                word_conditions = " AND ".join(["nom LIKE ?" for _ in words])
                word_params = [f"%{w}%" for w in words]
                async with db.execute(
                    f"""
                    SELECT id, nom, janri, rams, aniType, qismi, fandub, yili
                    FROM animelar
                    WHERE {word_conditions}
                    ORDER BY qidiruv DESC
                    LIMIT 50
                    """,
                    word_params
                ) as cursor:
                    word_results = await cursor.fetchall()

            # 4) Transliteratsiya — lotin/kiril aralashtirgan yozuvlar uchun
            # Masalan "naрuto" yoki "NARUTO" ham topsın
            search_lower = search_text.lower()
            async with db.execute(
                """
                SELECT id, nom, janri, rams, aniType, qismi, fandub, yili
                FROM animelar
                WHERE LOWER(nom) LIKE ?
                ORDER BY qidiruv DESC
                LIMIT 50
                """,
                (f"%{search_lower}%",)
            ) as cursor:
                lower_results = await cursor.fetchall()

            # Barcha natijalarni birlashtirish — takrorlanmasdan, tartib saqlangan holda
            seen = set()
            animes = []
            for r in starts_with + word_results + contains + lower_results:
                if r[0] not in seen:
                    seen.add(r[0])
                    animes.append(r)
            animes = animes[:50]

        else:
            async with db.execute(
                """
                SELECT id, nom, janri, rams, aniType, qismi, fandub, yili
                FROM animelar
                ORDER BY id DESC
                LIMIT 50
                """
            ) as cursor:
                animes = await cursor.fetchall()

    results = []
    for anime in animes:
        anime_id, nom, janri, rams, status, qismi, fandub, yili = anime
        status = status or "OnGoing"
        fandub = fandub or "Ovoz berilmagan"
        janri  = janri  or "—"
        qismi  = qismi  or "?"
        yili   = yili   or "—"

        btn = InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(
                text="🎬 Ko'rish",
                url=f"https://t.me/{BOT_USERNAME}?start={anime_id}"
            )]
        ])

        caption = (
            f"🎬 <b>{nom}</b>\n"
            f"📖 {janri}\n"
            f"╭───────────\n"
            f"├ <b>Holati:</b> {status}\n"
            f"├ <b>Qismlar:</b> {qismi} ta\n"
            f"├ <b>Yil:</b> {yili}\n"
            f"├ <b>Ovoz:</b> {fandub}\n"
            f"╰───────────"
        )

        description = f"{janri} | {status} | {qismi} qism"

        # rams URL bo'lsa InlineQueryResultPhoto, file_id bo'lsa CachedPhoto
        is_url = rams and (rams.startswith("http://") or rams.startswith("https://"))
        is_file_id = rams and not is_url

        if is_url:
            from aiogram.types import InlineQueryResultPhoto
            result = InlineQueryResultPhoto(
                id=str(anime_id),
                photo_url=rams,
                thumbnail_url=rams,
                title=nom,
                description=description,
                caption=caption,
                reply_markup=btn,
                parse_mode="HTML",
            )
        elif is_file_id:
            try:
                result = InlineQueryResultCachedPhoto(
                    id=str(anime_id),
                    photo_file_id=rams,
                    title=nom,
                    description=description,
                    caption=caption,
                    reply_markup=btn,
                    parse_mode="HTML",
                )
            except Exception:
                result = InlineQueryResultArticle(
                    id=str(anime_id),
                    title=f"🎬 {nom}",
                    description=description,
                    input_message_content=InputTextMessageContent(
                        message_text=caption,
                        parse_mode="HTML"
                    ),
                    reply_markup=btn,
                )
        else:
            result = InlineQueryResultArticle(
                id=str(anime_id),
                title=f"🎬 {nom}",
                description=description,
                input_message_content=InputTextMessageContent(
                    message_text=caption,
                    parse_mode="HTML"
                ),
                reply_markup=btn,
            )

        results.append(result)

    if not results:
        results = [
            InlineQueryResultArticle(
                id="not_found",
                title="😔 Hech narsa topilmadi",
                description=f"«{search_text}» bo'yicha natija yo'q",
                input_message_content=InputTextMessageContent(
                    message_text=f"😔 <b>«{search_text}»</b> bo'yicha hech narsa topilmadi.",
                    parse_mode="HTML"
                )
            )
        ]

    # Pagination — 50 dan ko'p anime bo'lsa keyingi sahifa
    offset = int(query.offset) if query.offset and query.offset.isdigit() else 0
    page_results = results[offset:offset + 50]
    next_offset = str(offset + 50) if len(results) > offset + 50 else ""

    await query.answer(
        results=page_results,
        cache_time=0,
        is_personal=True,
        next_offset=next_offset
    )
