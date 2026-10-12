import re
import os
import sys
import logging
import asyncio
import aiosqlite

# Path helper for standalone execution
parent_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if parent_dir not in sys.path:
    sys.path.insert(0, parent_dir)

from config import DB_PATH, DATABASE_URL

logger = logging.getLogger("db_helper")

# Lazy-loaded PostgreSQL pool
_pg_pool = None

# Optional import asyncpg
try:
    import asyncpg
except ImportError:
    asyncpg = None


async def get_pg_pool():
    """Lazily creates and returns the PostgreSQL connection pool."""
    global _pg_pool
    if DATABASE_URL:
        if asyncpg is None:
            raise ImportError(
                "PostgreSQL DATABASE_URL config is set, but 'asyncpg' library is not installed. "
                "Please run: pip install asyncpg"
            )
        if _pg_pool is None:
            # Handle legacy 'postgres://' connection URI replacing it with 'postgresql://'
            url = DATABASE_URL
            if url.startswith("postgres://"):
                url = url.replace("postgres://", "postgresql://", 1)
            logger.info("Initializing PostgreSQL connection pool...")
            _pg_pool = await asyncpg.create_pool(url, min_size=1, max_size=10)
    return _pg_pool


def convert_placeholders(query: str) -> str:
    """Converts PostgreSQL $1, $2 style placeholders to SQLite ? style."""
    return re.sub(r'\$\d+', '?', query)


# --- Basic Executions ---

async def execute_query(query: str, *args):
    """Executes a non-returning SQL query."""
    if DATABASE_URL:
        pool = await get_pg_pool()
        async with pool.acquire() as conn:
            return await conn.execute(query, *args)
    else:
        sqlite_query = convert_placeholders(query)
        async with aiosqlite.connect(DB_PATH) as db:
            await db.execute(sqlite_query, args)
            await db.commit()


async def execute_insert(query: str, *args) -> int:
    """Executes an INSERT query and returns the last inserted primary key row ID."""
    if DATABASE_URL:
        pool = await get_pg_pool()
        async with pool.acquire() as conn:
            # PostgreSQL requires returning clause (e.g. RETURNING id)
            return await conn.fetchval(query, *args)
    else:
        sqlite_query = convert_placeholders(query)
        # Safely strip RETURNING clause for compatibility with standard SQLite engines
        clean_query = re.sub(r'(?i)\s+RETURNING\s+\w+', '', sqlite_query)
        async with aiosqlite.connect(DB_PATH) as db:
            cursor = await db.execute(clean_query, args)
            last_id = cursor.lastrowid
            await db.commit()
            return last_id


async def fetch_all(query: str, *args) -> list[dict]:
    """Fetches all rows for a query and returns them as a list of dicts."""
    if DATABASE_URL:
        pool = await get_pg_pool()
        async with pool.acquire() as conn:
            rows = await conn.fetch(query, *args)
            return [dict(r) for r in rows]
    else:
        sqlite_query = convert_placeholders(query)
        async with aiosqlite.connect(DB_PATH) as db:
            db.row_factory = aiosqlite.Row
            async with db.execute(sqlite_query, args) as cursor:
                rows = await cursor.fetchall()
                return [dict(r) for r in rows]


async def fetch_row(query: str, *args) -> dict | None:
    """Fetches a single row and returns it as a dict or None."""
    if DATABASE_URL:
        pool = await get_pg_pool()
        async with pool.acquire() as conn:
            row = await conn.fetchrow(query, *args)
            return dict(row) if row else None
    else:
        sqlite_query = convert_placeholders(query)
        async with aiosqlite.connect(DB_PATH) as db:
            db.row_factory = aiosqlite.Row
            async with db.execute(sqlite_query, args) as cursor:
                row = await cursor.fetchone()
                return dict(row) if row else None


async def fetch_val(query: str, *args):
    """Fetches a single scalar value (e.g. COUNT(*))."""
    if DATABASE_URL:
        pool = await get_pg_pool()
        async with pool.acquire() as conn:
            return await conn.fetchval(query, *args)
    else:
        sqlite_query = convert_placeholders(query)
        async with aiosqlite.connect(DB_PATH) as db:
            async with db.execute(sqlite_query, args) as cursor:
                row = await cursor.fetchone()
                return row[0] if row else None


# --- Subsystem Database Schema Initialization ---

async def init_db():
    """Initializes support bot database tables and seeds FAQs."""
    if DATABASE_URL:
        logger.info("Initializing PostgreSQL schema for Support bot...")
        queries = [
            """
            CREATE TABLE IF NOT EXISTS support_tickets (
                id SERIAL PRIMARY KEY,
                user_id BIGINT NOT NULL,
                username VARCHAR(255) DEFAULT '',
                full_name VARCHAR(255) DEFAULT '',
                message TEXT NOT NULL,
                group_msg_id BIGINT DEFAULT NULL,
                status VARCHAR(50) DEFAULT 'open',
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            );
            """,
            """
            CREATE TABLE IF NOT EXISTS support_messages (
                id SERIAL PRIMARY KEY,
                ticket_id INTEGER NOT NULL,
                sender_id BIGINT NOT NULL,
                message TEXT NOT NULL,
                is_admin INTEGER DEFAULT 0,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            );
            """,
            """
            CREATE TABLE IF NOT EXISTS support_faq (
                id SERIAL PRIMARY KEY,
                question TEXT NOT NULL,
                answer TEXT NOT NULL,
                order_num INTEGER DEFAULT 0
            );
            """
        ]
        for q in queries:
            await execute_query(q)

        # Seed FAQs if empty
        count = await fetch_val("SELECT COUNT(*) FROM support_faq")
        if count == 0:
            logger.info("Seeding PostgreSQL support FAQs...")
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
                await execute_query(
                    "INSERT INTO support_faq (question, answer, order_num) VALUES ($1, $2, $3)",
                    q, a, o
                )
    else:
        logger.info("Initializing SQLite schema for Support bot...")
        queries = [
            """
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
            """,
            """
            CREATE TABLE IF NOT EXISTS support_messages (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                ticket_id INTEGER NOT NULL,
                sender_id INTEGER NOT NULL,
                message TEXT NOT NULL,
                is_admin INTEGER DEFAULT 0,
                created_at DATETIME DEFAULT CURRENT_TIMESTAMP
            );
            """,
            """
            CREATE TABLE IF NOT EXISTS support_faq (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                question TEXT NOT NULL,
                answer TEXT NOT NULL,
                order_num INTEGER DEFAULT 0
            );
            """
        ]
        for q in queries:
            await execute_query(q)

        # Seed SQLite FAQs
        count = await fetch_val("SELECT COUNT(*) FROM support_faq")
        if count == 0:
            logger.info("Seeding SQLite support FAQs...")
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
                await execute_query(
                    "INSERT INTO support_faq (question, answer, order_num) VALUES ($1, $2, $3)",
                    q, a, o
                )


# --- Unified High-level Support Operations ---

async def create_ticket(user_id: int, username: str, full_name: str, message: str) -> int:
    """Inserts a new ticket and its initial message, returning ticket ID."""
    ticket_id = await execute_insert(
        """INSERT INTO support_tickets (user_id, username, full_name, message, status) 
           VALUES ($1, $2, $3, $4, 'open') RETURNING id""",
        user_id, username, full_name, message
    )
    await add_ticket_message(ticket_id, user_id, message, is_admin=0)
    return ticket_id


async def add_ticket_message(ticket_id: int, sender_id: int, message: str, is_admin: int = 0):
    """Inserts a message history bubble."""
    await execute_query(
        "INSERT INTO support_messages (ticket_id, sender_id, message, is_admin) VALUES ($1, $2, $3, $4)",
        ticket_id, sender_id, message, is_admin
    )


async def get_faqs() -> list[dict]:
    """Fetches FAQs sorted by order_num."""
    return await fetch_all("SELECT id, question, answer, order_num FROM support_faq ORDER BY order_num ASC")


async def get_ticket(ticket_id: int) -> dict | None:
    """Fetches a specific ticket."""
    return await fetch_row(
        "SELECT id, user_id, username, full_name, message, status, group_msg_id, created_at FROM support_tickets WHERE id=$1",
        ticket_id
    )


async def update_ticket_status(ticket_id: int, status: str):
    """Updates the status of a ticket."""
    await execute_query("UPDATE support_tickets SET status=$1 WHERE id=$2", status, ticket_id)


async def update_ticket_group_msg(ticket_id: int, group_msg_id: int):
    """Updates the Telegram group message associated with the ticket."""
    await execute_query("UPDATE support_tickets SET group_msg_id=$1 WHERE id=$2", group_msg_id, ticket_id)


async def get_tickets_for_user(user_id: int, limit: int = 10) -> list[dict]:
    """Gets recent tickets submitted by a specific user."""
    return await fetch_all(
        """SELECT id, message, status, created_at FROM support_tickets 
           WHERE user_id=$1 ORDER BY created_at DESC LIMIT $2""",
        user_id, limit
    )


async def get_all_tickets() -> list[dict]:
    """Fetches all tickets for admin panel review."""
    # Convert dates to string to avoid datetime serialization errors in JSON
    tickets = await fetch_all(
        "SELECT id, user_id, username, full_name, message, status, group_msg_id, created_at FROM support_tickets ORDER BY created_at DESC"
    )
    for t in tickets:
        if t.get("created_at") and not isinstance(t["created_at"], str):
            t["created_at"] = t["created_at"].strftime("%Y-%m-%d %H:%M:%S")
    return tickets


async def get_messages_for_ticket(ticket_id: int) -> list[dict]:
    """Fetches conversation logs for a ticket."""
    messages = await fetch_all(
        "SELECT id, sender_id, message, is_admin, created_at FROM support_messages WHERE ticket_id=$1 ORDER BY created_at ASC",
        ticket_id
    )
    for m in messages:
        if m.get("created_at") and not isinstance(m["created_at"], str):
            m["created_at"] = m["created_at"].strftime("%Y-%m-%d %H:%M:%S")
    return messages


async def get_status_counts() -> dict:
    """Returns total and status breakdown statistics."""
    rows = await fetch_all("SELECT status, COUNT(*) as count FROM support_tickets GROUP BY status")
    stats = {"total": 0, "open": 0, "answered": 0, "closed": 0}
    total = 0
    for r in rows:
        status_name = r["status"]
        count = r["count"]
        if status_name in stats:
            stats[status_name] = count
        total += count
    stats["total"] = total
    return stats


async def get_user_profile(user_id: int) -> dict | None:
    """Fetches user profile status, cash, ban, and join date from main DB."""
    query = "SELECT status, pul, ban, joined_at FROM users WHERE user_id=$1"
    try:
        if DATABASE_URL:
            pool = await get_pg_pool()
            async with pool.acquire() as conn:
                row = await conn.fetchrow(query, user_id)
                if row:
                    d = dict(row)
                    if d.get("joined_at") and not isinstance(d["joined_at"], str):
                        d["joined_at"] = d["joined_at"].strftime("%Y-%m-%d %H:%M:%S")
                    return d
                return None
        else:
            sqlite_query = convert_placeholders(query)
            async with aiosqlite.connect(DB_PATH) as db:
                db.row_factory = aiosqlite.Row
                async with db.execute(sqlite_query, (user_id,)) as cursor:
                    row = await cursor.fetchone()
                    if row:
                        return dict(row)
                    return None
    except Exception as e:
        logger.warning(f"Could not fetch user profile from main users table: {e}")
        return None


async def get_detailed_stats() -> dict:
    """Returns detailed statistics including unique users and tickets created today."""
    counts = await get_status_counts()
    unique_users = await fetch_val("SELECT COUNT(DISTINCT user_id) FROM support_tickets")
    
    if DATABASE_URL:
        today = await fetch_val("SELECT COUNT(*) FROM support_tickets WHERE created_at::date = CURRENT_DATE")
    else:
        today = await fetch_val("SELECT COUNT(*) FROM support_tickets WHERE DATE(created_at)=DATE('now')")
        
    counts["unique_users"] = unique_users or 0
    counts["today"] = today or 0
    return counts


async def get_open_tickets(limit: int = 15) -> list[dict]:
    """Fetches open support tickets ordered oldest to newest."""
    tickets = await fetch_all(
        "SELECT id, full_name, username, message, created_at FROM support_tickets WHERE status='open' ORDER BY created_at ASC LIMIT $1",
        limit
    )
    for t in tickets:
        if t.get("created_at") and not isinstance(t["created_at"], str):
            t["created_at"] = t["created_at"].strftime("%Y-%m-%d %H:%M:%S")
    return tickets


async def get_faq_headers() -> list[dict]:
    """Fetches FAQ ID and question only."""
    return await fetch_all("SELECT id, question FROM support_faq ORDER BY order_num ASC")


async def delete_faq(faq_id: int):
    """Deletes an FAQ item."""
    await execute_query("DELETE FROM support_faq WHERE id=$1", faq_id)


async def add_faq(question: str, answer: str) -> int:
    """Adds a new FAQ item and returns its ID."""
    max_order = await fetch_val("SELECT MAX(order_num) FROM support_faq")
    next_order = (max_order or 0) + 1
    return await execute_insert(
        "INSERT INTO support_faq (question, answer, order_num) VALUES ($1, $2, $3) RETURNING id",
        question, answer, next_order
    )

