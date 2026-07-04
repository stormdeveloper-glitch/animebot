import aiosqlite
from config import DB_PATH, DATABASE_URL

async def init_db():
    if DATABASE_URL:
        # PostgreSQL initialization
        import asyncpg
        url = DATABASE_URL
        if url.startswith("postgres://"):
            url = url.replace("postgres://", "postgresql://", 1)
        print("🔗 PostgreSQL bazasiga ulanmoqda...")
        conn = await asyncpg.connect(url)
        try:
            # Create main bot tables in PostgreSQL
            await conn.execute("""
                CREATE TABLE IF NOT EXISTS users (
                    id SERIAL PRIMARY KEY,
                    user_id BIGINT UNIQUE NOT NULL,
                    status VARCHAR(100) DEFAULT 'Oddiy',
                    pul INTEGER DEFAULT 0,
                    pul2 INTEGER DEFAULT 0,
                    odam INTEGER DEFAULT 0,
                    ban VARCHAR(50) DEFAULT 'unban',
                    refid BIGINT DEFAULT NULL,
                    joined_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                );
            """)
            await conn.execute("""
                CREATE TABLE IF NOT EXISTS animelar (
                    id SERIAL PRIMARY KEY,
                    nom VARCHAR(512) NOT NULL,
                    rams TEXT NOT NULL,
                    qismi VARCHAR(255) NOT NULL,
                    davlat VARCHAR(255) NOT NULL,
                    tili VARCHAR(255) NOT NULL,
                    yili VARCHAR(255) NOT NULL,
                    janri VARCHAR(512) NOT NULL,
                    qidiruv INTEGER DEFAULT 0,
                    sana VARCHAR(255) NOT NULL,
                    aniType VARCHAR(100) DEFAULT '',
                    fandub VARCHAR(255) DEFAULT '',
                    kanal VARCHAR(255) DEFAULT '',
                    liklar INTEGER DEFAULT 0,
                    desliklar INTEGER DEFAULT 0,
                    tavsif TEXT DEFAULT '',
                    nom_en VARCHAR(512) DEFAULT '',
                    filler_info TEXT DEFAULT '',
                    filler_image TEXT DEFAULT '',
                    season_group_id INTEGER DEFAULT NULL,
                    season_number INTEGER DEFAULT 1,
                    yosh_toifa VARCHAR(100) DEFAULT 'Barcha yoshlar'
                );
            """)
            await conn.execute("""
                CREATE TABLE IF NOT EXISTS anime_datas (
                    data_id SERIAL PRIMARY KEY,
                    id INTEGER NOT NULL,
                    file_id VARCHAR(512) NOT NULL,
                    qism INTEGER NOT NULL,
                    sana VARCHAR(255),
                    msg_id BIGINT DEFAULT NULL,
                    chat_id BIGINT DEFAULT NULL
                );
            """)
            await conn.execute("""
                CREATE TABLE IF NOT EXISTS watchlist (
                    user_id BIGINT NOT NULL,
                    anime_id INTEGER NOT NULL,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    PRIMARY KEY (user_id, anime_id)
                );
            """)
            await conn.execute("""
                CREATE TABLE IF NOT EXISTS watch_progress (
                    user_id BIGINT NOT NULL,
                    anime_id INTEGER NOT NULL,
                    last_episode INTEGER DEFAULT 0,
                    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    PRIMARY KEY (user_id, anime_id)
                );
            """)
            await conn.execute("""
                CREATE TABLE IF NOT EXISTS web_profile_links (
                    device_id VARCHAR(255) PRIMARY KEY,
                    telegram_id BIGINT UNIQUE NOT NULL,
                    telegram_name VARCHAR(255) DEFAULT '',
                    telegram_username VARCHAR(255) DEFAULT '',
                    photo_file_id VARCHAR(512) DEFAULT '',
                    linked_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                );
            """)
            await conn.execute("""
                CREATE TABLE IF NOT EXISTS web_link_requests (
                    request_id VARCHAR(255) PRIMARY KEY,
                    device_id VARCHAR(255) NOT NULL,
                    telegram_id BIGINT NOT NULL,
                    status VARCHAR(100) DEFAULT 'pending',
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    decided_at TIMESTAMP DEFAULT NULL
                );
            """)
            await conn.execute("""
                CREATE TABLE IF NOT EXISTS web_saved_animes (
                    device_id VARCHAR(255) NOT NULL,
                    anime_id INTEGER NOT NULL,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    PRIMARY KEY (device_id, anime_id)
                );
            """)
            await conn.execute("""
                CREATE TABLE IF NOT EXISTS channels (
                    id SERIAL PRIMARY KEY,
                    channelId VARCHAR(255) NOT NULL,
                    channelType VARCHAR(100) NOT NULL,
                    channelLink VARCHAR(512) NOT NULL,
                    channelName VARCHAR(255) DEFAULT ''
                );
            """)
            await conn.execute("""
                CREATE TABLE IF NOT EXISTS vip_status (
                    id SERIAL PRIMARY KEY,
                    user_id BIGINT UNIQUE NOT NULL,
                    kun INTEGER NOT NULL,
                    date VARCHAR(100) NOT NULL
                );
            """)
            await conn.execute("""
                CREATE TABLE IF NOT EXISTS admins (
                    user_id BIGINT PRIMARY KEY,
                    added_by BIGINT
                );
            """)
            await conn.execute("""
                CREATE TABLE IF NOT EXISTS bot_texts (
                    key VARCHAR(255) PRIMARY KEY,
                    value TEXT NOT NULL
                );
            """)
            await conn.execute("""
                CREATE TABLE IF NOT EXISTS bot_settings (
                    key VARCHAR(255) PRIMARY KEY,
                    value TEXT NOT NULL
                );
            """)
            await conn.execute("""
                CREATE TABLE IF NOT EXISTS custom_buttons (
                    id SERIAL PRIMARY KEY,
                    text VARCHAR(255) NOT NULL,
                    url VARCHAR(512) NOT NULL
                );
            """)
            await conn.execute("""
                CREATE TABLE IF NOT EXISTS payments (
                    id SERIAL PRIMARY KEY,
                    user_id BIGINT NOT NULL,
                    amount INTEGER NOT NULL,
                    purpose VARCHAR(255) DEFAULT 'balance',
                    status VARCHAR(100) DEFAULT 'pending',
                    check_file_id VARCHAR(512),
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                );
            """)

            # Default texts
            await conn.execute("INSERT INTO bot_texts (key, value) VALUES ('guide', '📚 Foydalanish qo''llanmasi...') ON CONFLICT DO NOTHING")
            await conn.execute("INSERT INTO bot_texts (key, value) VALUES ('ads', '💵 Reklama va Homiylik...') ON CONFLICT DO NOTHING")
            await conn.execute("INSERT INTO bot_texts (key, value) VALUES ('wallet', 'Karta: 8600...') ON CONFLICT DO NOTHING")

            # Default settings
            default_settings = [
                ('vip_price', '5000'),
                ('vip_currency', 'so\'m'),
                ('referral_bonus', '500'),
                ('cashback_percent', '5'),
                ('bot_maintenance', '0'),
                ('web_app_url', ''),
                ('content_restriction', '0'),
                ('button_style_default', 'primary'),
                ('button_style_positive', 'success'),
                ('button_style_negative', 'danger'),
                ('button_style_watch', 'success'),
                ('start_text', 'Assalomu alaykum, {name}!\n\nAnime botiga xush kelibsiz!\nBotimizda minglab animeni o\'zbek tilida tomosha qiling!')
            ]
            for key, val in default_settings:
                await conn.execute("INSERT INTO bot_settings (key, value) VALUES ($1, $2) ON CONFLICT DO NOTHING", key, val)

            print("✅ PostgreSQL jadvallari yaratildi/tekshirildi.")
            # Trigger migration of tables
            await migrate_sqlite_to_postgres(conn)

        except Exception as e:
            print(f"❌ PostgreSQL-ni ishga tushirishda xatolik: {e}")
            import traceback
            traceback.print_exc()
        finally:
            await conn.close()
    else:
        # Original SQLite implementation
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


async def migrate_sqlite_to_postgres(pg_conn):
    """SQLite data migration to PostgreSQL."""
    if not os.path.exists(DB_PATH):
        print(f"ℹ️ SQLite bazasi topilmadi ({DB_PATH}). Migratsiya o'tkazib yuborildi.")
        return

    print("🔄 SQLite-dan PostgreSQL-ga ma'lumotlarni nusxalash (migratsiya) boshlandi...")
    
    tables = [
        "users", "animelar", "anime_datas", "watchlist", "watch_progress", 
        "web_profile_links", "web_link_requests", "web_saved_animes", 
        "channels", "vip_status", "admins", "bot_texts", "bot_settings", 
        "custom_buttons", "payments", "support_tickets", "support_messages", "support_faq"
    ]

    async with aiosqlite.connect(DB_PATH) as db:
        # Get list of existing tables in SQLite
        cursor = await db.execute("SELECT name FROM sqlite_master WHERE type='table'")
        sqlite_tables = [r[0] for r in await cursor.fetchall()]
        
        for table in tables:
            if table not in sqlite_tables:
                continue
                
            try:
                # Check if PostgreSQL table is empty
                pg_count = await pg_conn.fetchval(f"SELECT COUNT(*) FROM {table}")
                if pg_count > 0:
                    # Skip to avoid conflicts or duplicating data
                    print(f"ℹ️ '{table}' jadvalida allaqachon ma'lumot bor. Nusxalash o'tkazib yuborildi.")
                    continue
                    
                print(f"📦 '{table}' jadvalidan ma'lumotlar ko'chirilmoqda...")
                
                db.row_factory = aiosqlite.Row
                async with db.execute(f"SELECT * FROM {table}") as sqlite_cursor:
                    rows = await sqlite_cursor.fetchall()
                    if not rows:
                        print(f"ℹ️ '{table}' SQLite jadvali bo'sh. Nusxalash hojati yo'q.")
                        continue
                        
                    cols = [d[0] for d in sqlite_cursor.description]
                    # Quote column names for PostgreSQL to avoid keyword conflicts
                    cols_quoted = [f'"{c}"' for c in cols]
                    col_str = ", ".join(cols_quoted)
                    val_str = ", ".join([f"${i+1}" for i in range(len(cols))])
                    
                    insert_query = f"INSERT INTO {table} ({col_str}) VALUES ({val_str}) ON CONFLICT DO NOTHING"
                    
                    # Insert rows
                    count = 0
                    for row in rows:
                        vals = tuple(row)
                        await pg_conn.execute(insert_query, *vals)
                        count += 1
                        
                print(f"✅ '{table}' jadvalidan {count} ta qator muvaffaqiyatli nusxalandi.")
            except Exception as e:
                print(f"⚠️ '{table}' jadvalini nusxalashda xatolik yuz berdi: {e}")
                
    print("🎉 SQLite-dan PostgreSQL-ga ma'lumotlar migratsiyasi yakunlandi.")

async def get_db():
    return await aiosqlite.connect(DB_PATH)


# ─── Support Bot jadvallarini yaratish ───────────────────────────────────────
async def init_support_db():
    """Support bot uchun jadvallarni db_helper orqali yaratish."""
    from support_bot.db_helper import init_db as init_subsystem_db
    await init_subsystem_db()
