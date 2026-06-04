import aiosqlite
from config import DB_PATH

async def init_db():
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute("""
            CREATE TABLE IF NOT EXISTS users (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id INTEGER UNIQUE NOT NULL,
                status TEXT DEFAULT 'Oddiy',
                pul INTEGER DEFAULT 0,
                pul2 INTEGER DEFAULT 0,
                odam INTEGER DEFAULT 0,
                ban TEXT DEFAULT 'unban',
                refid INTEGER DEFAULT NULL,
                joined_at DATETIME DEFAULT CURRENT_TIMESTAMP
            );
        """)
        await db.execute("""
            CREATE TABLE IF NOT EXISTS animelar (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                nom TEXT NOT NULL,
                rams TEXT NOT NULL,
                qismi TEXT NOT NULL,
                davlat TEXT NOT NULL,
                tili TEXT NOT NULL,
                yili TEXT NOT NULL,
                janri TEXT NOT NULL,
                qidiruv INTEGER DEFAULT 0,
                sana TEXT NOT NULL,
                aniType TEXT DEFAULT '',
                fandub TEXT DEFAULT '',
                kanal TEXT DEFAULT '',
                liklar INTEGER DEFAULT 0,
                desliklar INTEGER DEFAULT 0,
                tavsif TEXT DEFAULT '',
                nom_en TEXT DEFAULT ''
            );
        """)
        await db.execute("""
            CREATE TABLE IF NOT EXISTS anime_datas (
                data_id INTEGER PRIMARY KEY AUTOINCREMENT,
                id INTEGER NOT NULL,
                file_id TEXT NOT NULL,
                qism INTEGER NOT NULL,
                sana TEXT,
                msg_id INTEGER DEFAULT NULL,
                chat_id INTEGER DEFAULT NULL
            );
        """)
        await db.execute("""
            CREATE TABLE IF NOT EXISTS watchlist (
                user_id INTEGER NOT NULL,
                anime_id INTEGER NOT NULL,
                created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
                PRIMARY KEY (user_id, anime_id)
            );
        """)
        await db.execute("""
            CREATE TABLE IF NOT EXISTS watch_progress (
                user_id INTEGER NOT NULL,
                anime_id INTEGER NOT NULL,
                last_episode INTEGER DEFAULT 0,
                updated_at DATETIME DEFAULT CURRENT_TIMESTAMP,
                PRIMARY KEY (user_id, anime_id)
            );
        """)
        await db.execute("CREATE INDEX IF NOT EXISTS idx_watchlist_anime ON watchlist(anime_id)")
        await db.execute("CREATE INDEX IF NOT EXISTS idx_watch_progress_user ON watch_progress(user_id)")
        await db.execute("""
            CREATE TABLE IF NOT EXISTS web_profile_links (
                device_id TEXT PRIMARY KEY,
                telegram_id INTEGER UNIQUE NOT NULL,
                telegram_name TEXT DEFAULT '',
                telegram_username TEXT DEFAULT '',
                photo_file_id TEXT DEFAULT '',
                linked_at DATETIME DEFAULT CURRENT_TIMESTAMP
            );
        """)
        await db.execute("""
            CREATE TABLE IF NOT EXISTS web_link_requests (
                request_id TEXT PRIMARY KEY,
                device_id TEXT NOT NULL,
                telegram_id INTEGER NOT NULL,
                status TEXT DEFAULT 'pending',
                created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
                decided_at DATETIME DEFAULT NULL
            );
        """)
        await db.execute("""
            CREATE TABLE IF NOT EXISTS web_saved_animes (
                device_id TEXT NOT NULL,
                anime_id INTEGER NOT NULL,
                created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
                PRIMARY KEY (device_id, anime_id)
            );
        """)
        await db.execute("""
            CREATE TABLE IF NOT EXISTS channels (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                channelId TEXT NOT NULL,
                channelType TEXT NOT NULL,
                channelLink TEXT NOT NULL,
                channelName TEXT DEFAULT ''
            );
        """)
        # Eski DB da channelName ustuni bo'lmasa qo'shamiz
        try:
            await db.execute("ALTER TABLE channels ADD COLUMN channelName TEXT DEFAULT ''")
        except Exception:
            pass  # Ustun allaqachon bor

        # Eski DB da kanal ustuni bo'lmasa qo'shamiz
        try:
            await db.execute("ALTER TABLE animelar ADD COLUMN kanal TEXT DEFAULT ''")
        except Exception:
            pass  # Ustun allaqachon bor

        # Yosh toifasi ustuni
        try:
            await db.execute("ALTER TABLE animelar ADD COLUMN yosh_toifa TEXT DEFAULT 'Barcha yoshlar'")
        except Exception:
            pass  # Ustun allaqachon bor

        # AI tavsif ustuni
        try:
            await db.execute("ALTER TABLE animelar ADD COLUMN tavsif TEXT DEFAULT ''")
        except Exception:
            pass  # Ustun allaqachon bor

        # Anime inglizcha nomi (AniList poster qidirish uchun)
        try:
            await db.execute("ALTER TABLE animelar ADD COLUMN nom_en TEXT DEFAULT ''")
        except Exception:
            pass  # Ustun allaqachon bor
        try:
            await db.execute("ALTER TABLE animelar ADD COLUMN filler_info TEXT DEFAULT ''")
        except Exception:
            pass
        try:
            await db.execute("ALTER TABLE animelar ADD COLUMN filler_image TEXT DEFAULT ''")
        except Exception:
            pass

        # Fasllarni bitta anime guruhida ko'rsatish uchun
        try:
            await db.execute("ALTER TABLE animelar ADD COLUMN season_group_id INTEGER DEFAULT NULL")
        except Exception:
            pass
        try:
            await db.execute("ALTER TABLE animelar ADD COLUMN season_number INTEGER DEFAULT 1")
        except Exception:
            pass
        await db.execute("UPDATE animelar SET season_group_id=id WHERE season_group_id IS NULL")
        await db.execute("UPDATE animelar SET season_number=1 WHERE season_number IS NULL OR season_number < 1")
        await db.execute("CREATE INDEX IF NOT EXISTS idx_animelar_season_group ON animelar(season_group_id, season_number, id)")

        # anime_datas ga msg_id va chat_id ustunlari
        try:
            await db.execute("ALTER TABLE anime_datas ADD COLUMN msg_id INTEGER DEFAULT NULL")
        except Exception:
            pass
        try:
            await db.execute("ALTER TABLE anime_datas ADD COLUMN chat_id INTEGER DEFAULT NULL")
        except Exception:
            pass

        await db.execute("""
            CREATE TABLE IF NOT EXISTS vip_status (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id INTEGER UNIQUE NOT NULL,
                kun INTEGER NOT NULL,
                date TEXT NOT NULL
            );

        """)
        await db.execute("""
            CREATE TABLE IF NOT EXISTS admins (
                user_id INTEGER PRIMARY KEY,
                added_by INTEGER
            );
        """)
        await db.execute("""
            CREATE TABLE IF NOT EXISTS bot_texts (
                key TEXT PRIMARY KEY,
                value TEXT NOT NULL
            );
        """)
        # Default matnlarni kiritish (faqat mavjud bo'lmasa)
        await db.execute("INSERT OR IGNORE INTO bot_texts (key, value) VALUES ('guide', '📚 Foydalanish qo''llanmasi...')")
        await db.execute("INSERT OR IGNORE INTO bot_texts (key, value) VALUES ('ads', '💵 Reklama va Homiylik...')")
        await db.execute("INSERT OR IGNORE INTO bot_texts (key, value) VALUES ('wallet', 'Karta: 8600...')")
        
        await db.execute("""
            CREATE TABLE IF NOT EXISTS bot_settings (
                key TEXT PRIMARY KEY,
                value TEXT NOT NULL
            );
        """)
        await db.execute("""
            CREATE TABLE IF NOT EXISTS custom_buttons (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                text TEXT NOT NULL,
                url TEXT NOT NULL
            );
        """)
        await db.execute("""
            CREATE TABLE IF NOT EXISTS payments (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id INTEGER NOT NULL,
                amount INTEGER NOT NULL,
                purpose TEXT DEFAULT 'balance',
                status TEXT DEFAULT 'pending',
                check_file_id TEXT,
                created_at DATETIME DEFAULT CURRENT_TIMESTAMP
            );
        """)
        # Default sozlamalar
        await db.execute("INSERT OR IGNORE INTO bot_settings (key, value) VALUES ('vip_price', '5000')")
        await db.execute("INSERT OR IGNORE INTO bot_settings (key, value) VALUES ('vip_currency', 'so''m')")
        await db.execute("INSERT OR IGNORE INTO bot_settings (key, value) VALUES ('referral_bonus', '500')")
        await db.execute("INSERT OR IGNORE INTO bot_settings (key, value) VALUES ('cashback_percent', '5')")
        await db.execute("INSERT OR IGNORE INTO bot_settings (key, value) VALUES ('bot_maintenance', '0')")
        await db.execute("INSERT OR IGNORE INTO bot_settings (key, value) VALUES ('web_app_url', '')")
        await db.execute("INSERT OR IGNORE INTO bot_settings (key, value) VALUES ('content_restriction', '0')")
        await db.execute("INSERT OR IGNORE INTO bot_settings (key, value) VALUES ('button_style_default', 'primary')")
        await db.execute("INSERT OR IGNORE INTO bot_settings (key, value) VALUES ('button_style_positive', 'success')")
        await db.execute("INSERT OR IGNORE INTO bot_settings (key, value) VALUES ('button_style_negative', 'danger')")
        await db.execute("INSERT OR IGNORE INTO bot_settings (key, value) VALUES ('button_style_watch', 'success')")
        await db.execute("INSERT OR IGNORE INTO bot_settings (key, value) VALUES ('start_text', 'Assalomu alaykum, {name}!\n\nAnime botiga xush kelibsiz!\nBotimizda minglab animeni o''zbek tilida tomosha qiling!')")
        
        await db.commit()

async def get_db():
    return await aiosqlite.connect(DB_PATH)


# ─── Support Bot jadvallarini yaratish ───────────────────────────────────────
async def init_support_db():
    """Support bot uchun qo'shimcha jadvallar."""
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute("""
            CREATE TABLE IF NOT EXISTS support_tickets (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id INTEGER NOT NULL,
                username TEXT DEFAULT '',
                full_name TEXT DEFAULT '',
                message TEXT NOT NULL,
                group_msg_id INTEGER DEFAULT NULL,
                status TEXT DEFAULT 'open',
                created_at DATETIME DEFAULT CURRENT_TIMESTAMP
            );
        """)
        await db.execute("""
            CREATE TABLE IF NOT EXISTS support_messages (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                ticket_id INTEGER NOT NULL,
                sender_id INTEGER NOT NULL,
                message TEXT NOT NULL,
                is_admin INTEGER DEFAULT 0,
                created_at DATETIME DEFAULT CURRENT_TIMESTAMP
            );
        """)
        await db.execute("""
            CREATE TABLE IF NOT EXISTS support_faq (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                question TEXT NOT NULL,
                answer TEXT NOT NULL,
                order_num INTEGER DEFAULT 0
            );
        """)
        # Default FAQ savollar (faqat bo'sh bo'lsa)
        default_faqs = [
            ("Anime qanday qidiriladi?",
             "🔎 Asosiy botga o'ting va <b>«🔎 Anime izlash»</b> tugmasini bosing.\n"
             "Nom, janr yoki kod orqali qidirishingiz mumkin.", 1),
            ("VIP nima va qanday qilinadi?",
             "💎 <b>VIP</b> — kontent cheklovi bo'lmagan maxsus status.\n\n"
             "VIP olish uchun asosiy botda <b>«💎 VIP»</b> tugmasini bosib, to'lov amalga oshiring.", 2),
            ("Qism yuklanmayapti, nima qilaman?",
             "📥 Agar qism yuklanmasa:\n"
             "• Internetni tekshiring\n"
             "• Botdan chiqib qayta kiring\n"
             "• Biroz kutib, qayta urinib ko'ring\n"
             "Muammo davom etsa, murojaat yuboring.", 3),
            ("Referral tizimi qanday ishlaydi?",
             "👥 <b>Referal</b> — do'stingizni taklif qilsangiz, har biri uchun bonus olasiz.\n\n"
             "Asosiy botda <b>«👥 Referal»</b> tugmasidan o'z havolangizni oling.", 4),
            ("Botdan foydalanish bepulmi?",
             "✅ Asosiy bot <b>bepul</b>!\n\n"
             "💎 VIP status ixtiyoriy bo'lib, qo'shimcha imkoniyatlar beradi.", 5),
        ]
        for q, a, o in default_faqs:
            await db.execute(
                "INSERT OR IGNORE INTO support_faq (question, answer, order_num) VALUES (?, ?, ?)",
                (q, a, o)
            )
        await db.commit()
