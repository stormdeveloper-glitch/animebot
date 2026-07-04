import sys
import os
import asyncio
import logging
from collections import deque
import random
import time
import aiosqlite
import aiohttp
from aiohttp import web
from aiogram import Bot

# Dynamic import configuration for standalone subsystem operation
parent_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if parent_dir not in sys.path:
    sys.path.insert(0, parent_dir)

from config import SUPPORT_BOT_TOKEN, SUPPORT_GROUP_ID, DB_PATH
from database import init_support_db

# --- Live Logging Config ---
class LiveLogHandler(logging.Handler):
    def __init__(self, maxlen=120):
        super().__init__()
        self.logs = deque(maxlen=maxlen)

    def emit(self, record):
        try:
            log_entry = self.format(record)
            self.logs.append(log_entry)
        except Exception:
            self.handleError(record)

live_log_handler = LiveLogHandler()
live_log_handler.setFormatter(logging.Formatter('%(asctime)s [%(name)s] %(levelname)s: %(message)s'))
live_log_handler.setLevel(logging.INFO)

# Root logging setup
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(name)s] %(levelname)s: %(message)s",
    handlers=[logging.StreamHandler(sys.stdout), live_log_handler]
)
logger = logging.getLogger("support_system")

# --- Bug & Simulation State ---
BUG_STATES = {
    "db_lock": False,
    "tg_rate_limit": False,
    "tg_network_fail": False,
    "memory_leak": False
}

# Simulated stats
SIMULATED_RAM = 34.0

async def simulate_memory_leak_task():
    """Background task to simulate memory leak climbing to 98% when active."""
    global SIMULATED_RAM
    while True:
        try:
            if BUG_STATES["memory_leak"]:
                if SIMULATED_RAM < 98.0:
                    SIMULATED_RAM = min(98.0, SIMULATED_RAM + random.uniform(3.5, 7.0))
                    logger.warning(f"[SIMULATED] [MEM_LEAK] RAM consumption increasing: {SIMULATED_RAM:.1f}%")
            else:
                # Fluctuate back to normal
                if SIMULATED_RAM > 38.0:
                    SIMULATED_RAM = max(34.0, SIMULATED_RAM - random.uniform(8.0, 15.0))
                else:
                    SIMULATED_RAM = max(25.0, min(42.0, SIMULATED_RAM + random.uniform(-1.5, 1.5)))
        except Exception as e:
            logger.error(f"Error in memory simulation: {e}")
        await asyncio.sleep(5)

# --- Helper functions for bug application ---

async def apply_db_latency():
    """Simulates database locking if active."""
    if BUG_STATES["db_lock"]:
        delay = 3.0
        logger.warning(f"[SIMULATED] [DB_LOCK] Database operation delayed by {delay}s due to simulated table lock.")
        await asyncio.sleep(delay)

def verify_telegram_connectivity():
    """Raises simulated exceptions for Telegram API calls if bug is active."""
    if BUG_STATES["tg_network_fail"]:
        logger.error("[SIMULATED] [NET_OUTAGE] Failed to establish connection to api.telegram.org. Connection timed out.")
        raise Exception("Telegram connection timeout (Network Outage)")
    if BUG_STATES["tg_rate_limit"]:
        logger.error("[SIMULATED] [RATE_LIMIT] Telegram API returned HTTP 429: Too Many Requests. Retry after 9 seconds.")
        raise Exception("Telegram API returned HTTP 429. Flood control active (Retry in 9s).")

# --- Database helpers ---

async def fetch_all_tickets():
    await apply_db_latency()
    from support_bot.db_helper import get_all_tickets
    return await get_all_tickets()

async def fetch_messages_for_ticket(ticket_id: int):
    await apply_db_latency()
    from support_bot.db_helper import get_messages_for_ticket
    return await get_messages_for_ticket(ticket_id)

# --- Global Bot Reference & Profile Cache ---
shared_bot = None

PROFILE_CACHE = {
    "last_fetched": 0,
    "main_bot": None,
    "admins": None
}

async def get_telegram_photo(request):
    """Proxy route to download and serve a Telegram profile picture on-the-fly."""
    global shared_bot
    file_id = request.match_info["file_id"]
    if not shared_bot:
        return web.Response(text="Bot offline", status=503)
        
    try:
        file = await shared_bot.get_file(file_id)
        import io
        dest = io.BytesIO()
        await shared_bot.download_file(file.file_path, dest)
        dest.seek(0)
        return web.Response(body=dest.read(), content_type="image/jpeg")
    except Exception as e:
        logger.error(f"Error fetching telegram photo {file_id}: {e}")
        return web.Response(text=str(e), status=404)

# --- Web Route Handlers ---

async def serve_index(request):
    """Serve index.html dashboard file."""
    index_path = os.path.join(os.path.dirname(__file__), "index.html")
    if not os.path.exists(index_path):
        return web.Response(text="Dashboard index.html file not found", status=404)
    with open(index_path, "r", encoding="utf-8") as f:
        return web.Response(text=f.read(), content_type="text/html", charset="utf-8")

async def get_bot_status(request):
    """Retrieve Telegram status, DB stats, metrics, and admin profiles."""
    global shared_bot
    status_data = {
        "bot_name": "Support Bot (Offline)",
        "bot_username": "offline",
        "bot_id": "N/A",
        "support_group_id": SUPPORT_GROUP_ID,
        "webhook_url": None,
        "webhook_details": {},
        "system_healthy": True,
        "stats": {"total": 0, "open": 0, "answered": 0, "closed": 0},
        "metrics": {
            "cpu": random.randint(6, 12),
            "ram": round(SIMULATED_RAM, 1),
            "db_size_kb": 0,
            "db_percentage": 5,
            "ping": random.randint(14, 25)
        },
        "main_bot": None,
        "admins": []
    }

    # Apply network fail simulation to status check
    if BUG_STATES["tg_network_fail"]:
        status_data["metrics"]["ping"] = 999
        status_data["system_healthy"] = False

    # Fetch bot data from Telegram API if active
    if shared_bot and not BUG_STATES["tg_network_fail"]:
        try:
            me = await shared_bot.get_me()
            status_data["bot_name"] = me.full_name
            status_data["bot_username"] = me.username
            status_data["bot_id"] = me.id
            
            # Check Webhook info
            webhook_info = await shared_bot.get_webhook_info()
            status_data["webhook_url"] = webhook_info.url
            status_data["webhook_details"] = {
                "url": webhook_info.url,
                "pending_update_count": webhook_info.pending_update_count,
                "max_connections": webhook_info.max_connections,
                "ip_address": webhook_info.ip_address,
                "last_error_date": webhook_info.last_error_date,
                "last_error_message": webhook_info.last_error_message
            }
        except Exception as e:
            logger.error(f"Error fetching bot data from Telegram: {e}")
            status_data["system_healthy"] = False
            status_data["webhook_details"] = {"last_error_message": str(e)}

    # Fetch database metrics & stats
    try:
        if os.path.exists(DB_PATH):
            size_bytes = os.path.getsize(DB_PATH)
            size_kb = round(size_bytes / 1024, 1)
            status_data["metrics"]["db_size_kb"] = size_kb
            # DB gauge math (max limit estimate 10MB = 10240KB)
            status_data["metrics"]["db_percentage"] = min(100, max(5, int((size_kb / 10240) * 100)))

        from support_bot.db_helper import get_status_counts
        status_data["stats"] = await get_status_counts()
    except Exception as e:
        logger.error(f"Error fetching DB ticket counts: {e}")
        status_data["system_healthy"] = False

    # Cache profile fetching to avoid Telegram Rate Limits
    if shared_bot and not BUG_STATES["tg_network_fail"]:
        now = time.time()
        if not PROFILE_CACHE["main_bot"] or (now - PROFILE_CACHE["last_fetched"] > 300):
            try:
                from config import SUPER_ADMIN_ID, ADMIN_IDS, MAIN_BOT_USERNAME
                
                # Fetch Main Bot details
                main_bot_info = {
                    "name": "Asosiy Bot",
                    "username": MAIN_BOT_USERNAME or "unknown",
                    "link": f"https://t.me/{MAIN_BOT_USERNAME}" if MAIN_BOT_USERNAME else "#",
                    "photo_url": None
                }
                if MAIN_BOT_USERNAME:
                    try:
                        bot_chat = await shared_bot.get_chat("@" + MAIN_BOT_USERNAME)
                        main_bot_info["name"] = bot_chat.first_name or bot_chat.title or "Asosiy Bot"
                        if bot_chat.photo:
                            main_bot_info["photo_url"] = f"/api/telegram-photo/{bot_chat.photo.big_file_id}"
                    except Exception as ex:
                        logger.warning(f"Could not fetch main bot chat photo: {ex}")
                
                # Fetch Admin details
                admins_list = []
                all_admin_ids = list(set([SUPER_ADMIN_ID] + ADMIN_IDS))
                for admin_id in all_admin_ids:
                    if not admin_id:
                        continue
                    admin_info = {
                        "id": admin_id,
                        "name": f"Admin ({admin_id})",
                        "username": None,
                        "link": f"tg://user?id={admin_id}",
                        "photo_url": None,
                        "role": "Super Admin" if admin_id == SUPER_ADMIN_ID else "Admin"
                    }
                    try:
                        admin_chat = await shared_bot.get_chat(admin_id)
                        admin_info["name"] = f"{admin_chat.first_name or ''} {admin_chat.last_name or ''}".strip() or f"Admin ({admin_id})"
                        if admin_chat.username:
                            admin_info["username"] = admin_chat.username
                            admin_info["link"] = f"https://t.me/{admin_chat.username}"
                        if admin_chat.photo:
                            admin_info["photo_url"] = f"/api/telegram-photo/{admin_chat.photo.big_file_id}"
                    except Exception as ex:
                        logger.warning(f"Could not fetch admin {admin_id} chat photo: {ex}")
                    admins_list.append(admin_info)
                
                PROFILE_CACHE["main_bot"] = main_bot_info
                PROFILE_CACHE["admins"] = admins_list
                PROFILE_CACHE["last_fetched"] = now
            except Exception as e:
                logger.error(f"Error preparing profile cache: {e}")

        status_data["main_bot"] = PROFILE_CACHE["main_bot"]
        status_data["admins"] = PROFILE_CACHE["admins"]
    else:
        # Fallback values if offline
        status_data["main_bot"] = {
            "name": "Asosiy Bot (Offline)",
            "username": "unknown",
            "link": "#",
            "photo_url": None
        }
        status_data["admins"] = []

    # Check overall system health status
    if any(BUG_STATES.values()):
        status_data["system_healthy"] = False

    return web.json_response(status_data)

async def get_tickets(request):
    """Get all tickets."""
    try:
        tickets = await fetch_all_tickets()
        return web.json_response(tickets)
    except Exception as e:
        logger.error(f"API tickets fetch error: {e}")
        return web.json_response({"error": str(e)}, status=500)

async def get_ticket_messages(request):
    """Get message history of a specific ticket."""
    ticket_id = int(request.match_info["ticket_id"])
    try:
        messages = await fetch_messages_for_ticket(ticket_id)
        return web.json_response(messages)
    except Exception as e:
        logger.error(f"API messages fetch error: {e}")
        return web.json_response({"error": str(e)}, status=500)

async def reply_to_ticket(request):
    """Sends a Telegram reply message to user, inserts it into DB, and marks ticket as answered."""
    global shared_bot
    ticket_id = int(request.match_info["ticket_id"])
    body = await request.json()
    reply_text = body.get("message", "").strip()

    if not reply_text:
        return web.json_response({"error": "Message content is required"}, status=400)

    if not shared_bot:
        return web.json_response({"error": "Telegram Bot is offline. Token missing."}, status=503)

    try:
        # Check simulated Telegram network fail / rate limits
        verify_telegram_connectivity()

        # Load ticket to get user_id and group message ID
        from support_bot.db_helper import get_ticket, add_ticket_message, update_ticket_status
        ticket = await get_ticket(ticket_id)

        if not ticket:
            return web.json_response({"error": "Ticket not found"}, status=404)

        user_id = ticket["user_id"]
        group_msg_id = ticket["group_msg_id"]

        # Send response via Telegram Bot API
        logger.info(f"Sending admin reply message to Telegram user {user_id} for ticket #{ticket_id}")
        await shared_bot.send_message(
            chat_id=user_id,
            text=f"✉️ <b>Admin javobi:</b>\n\n{reply_text}",
            parse_mode="HTML"
        )

        # Write to database (support_messages & update support_tickets)
        await add_ticket_message(ticket_id, 0, reply_text, is_admin=1)
        await update_ticket_status(ticket_id, 'answered')

        # Update inline reply markup in support Telegram group (if active)
        if SUPPORT_GROUP_ID and group_msg_id:
            try:
                from support_bot.keyboards import ticket_answered_kb
                await shared_bot.edit_message_reply_markup(
                    chat_id=SUPPORT_GROUP_ID,
                    message_id=group_msg_id,
                    reply_markup=ticket_answered_kb(ticket_id)
                )
            except Exception as e:
                logger.warning(f"Could not update Telegram Group reply markup: {e}")

        logger.info(f"Admin reply successfully delivered to ticket #{ticket_id}")
        return web.json_response({"ok": True})

    except Exception as e:
        logger.exception(f"Error executing ticket reply: {e}")
        return web.json_response({"error": str(e)}, status=500)

async def close_ticket(request):
    """Closes support ticket and notifies user."""
    global shared_bot
    ticket_id = int(request.match_info["ticket_id"])

    if not shared_bot:
        return web.json_response({"error": "Telegram Bot is offline."}, status=503)

    try:
        verify_telegram_connectivity()

        # Get ticket details
        from support_bot.db_helper import get_ticket, update_ticket_status
        ticket = await get_ticket(ticket_id)

        if not ticket:
            return web.json_response({"error": "Ticket not found"}, status=404)

        user_id = ticket["user_id"]
        group_msg_id = ticket["group_msg_id"]

        # Save to DB
        await update_ticket_status(ticket_id, 'closed')

        # Notify user
        try:
            await shared_bot.send_message(
                chat_id=user_id,
                text=f"🔒 <b>Murojaatingiz yopildi</b>\n\n🎫 Ticket #{ticket_id}\n\nYangi savol bo'lsa, yana murojaat yuboring.",
                parse_mode="HTML"
            )
        except Exception as e:
            logger.warning(f"Could not notify user of ticket close: {e}")

        # Update Telegram support group markup
        if SUPPORT_GROUP_ID and group_msg_id:
            try:
                from support_bot.keyboards import ticket_closed_kb
                await shared_bot.edit_message_reply_markup(
                    chat_id=SUPPORT_GROUP_ID,
                    message_id=group_msg_id,
                    reply_markup=ticket_closed_kb(ticket_id)
                )
            except Exception as e:
                logger.warning(f"Could not update Telegram Group reply markup: {e}")

        logger.info(f"Ticket #{ticket_id} closed successfully.")
        return web.json_response({"ok": True})

    except Exception as e:
        logger.exception(f"Error closing ticket: {e}")
        return web.json_response({"error": str(e)}, status=500)

async def get_bugs(request):
    """Retrieve simulated bug statuses."""
    return web.json_response(BUG_STATES)

async def trigger_bug(request):
    """Activate/Deactivate simulated bugs."""
    body = await request.json()
    bug_name = body.get("bug")
    active = body.get("active", False)

    if bug_name not in BUG_STATES:
        return web.json_response({"error": f"Invalid bug type. Options: {list(BUG_STATES.keys())}"}, status=400)

    BUG_STATES[bug_name] = active
    
    state_str = "ACTIVATED" if active else "DEACTIVATED"
    logger.warning(f"[SIMULATED] [BUG_TRIGGER] Bug state '{bug_name}' was {state_str} by administrator dashboard.")
    return web.json_response({"ok": True, "bug": bug_name, "active": active})

async def resolve_bugs(request):
    """Reset all active simulated glitches."""
    for bug in BUG_STATES:
        BUG_STATES[bug] = False
    logger.info("[SIMULATED] [SYSTEM_RESTORE] All simulated exceptions resolved. System health recovered.")
    return web.json_response({"ok": True})

async def get_logs(request):
    """Get console live stream logs."""
    return web.json_response(list(live_log_handler.logs))

async def send_test_alert(request):
    """Direct Telegram connection checker: sends test message to guruh/channel."""
    global shared_bot
    body = await request.json()
    message_text = body.get("message", "").strip()

    if not message_text:
        return web.json_response({"error": "Message is required"}, status=400)

    if not shared_bot:
        return web.json_response({"error": "Telegram Bot is offline. Token missing."}, status=503)

    if not SUPPORT_GROUP_ID:
        return web.json_response({"error": "SUPPORT_GROUP_ID is not configured in environment/config"}, status=400)

    try:
        verify_telegram_connectivity()

        logger.info(f"Sending test admin check message to Telegram support group {SUPPORT_GROUP_ID}")
        await shared_bot.send_message(
            chat_id=SUPPORT_GROUP_ID,
            text=message_text,
            parse_mode="HTML"
        )
        return web.json_response({"ok": True})
    except Exception as e:
        logger.exception(f"Telegram Connection Test failure: {e}")
        return web.json_response({"error": str(e)}, status=500)

# --- Server setup ---

def make_app():
    app = web.Application()
    app.router.add_get("/", serve_index)
    app.router.add_get("/api/bot-status", get_bot_status)
    app.router.add_get("/api/telegram-photo/{file_id}", get_telegram_photo)
    app.router.add_get("/api/tickets", get_tickets)
    app.router.add_get("/api/tickets/{ticket_id}/messages", get_ticket_messages)
    app.router.add_post("/api/tickets/{ticket_id}/reply", reply_to_ticket)
    app.router.add_post("/api/tickets/{ticket_id}/close", close_ticket)
    app.router.add_get("/api/bugs", get_bugs)
    app.router.add_post("/api/bugs/trigger", trigger_bug)
    app.router.add_post("/api/bugs/resolve", resolve_bugs)
    app.router.add_get("/api/logs", get_logs)
    app.router.add_post("/api/telegram/send-test", send_test_alert)
    return app

# --- Bot polling background loop ---

async def start_bot_polling():
    """Runs the aiogram support bot polling loop in background."""
    global shared_bot
    if not SUPPORT_BOT_TOKEN:
        logger.warning("[SupportBot] SUPPORT_BOT_TOKEN is empty. Background Telegram bot will not start.")
        return

    logger.info("[SupportBot] Initializing Telegram Bot instance...")
    shared_bot = Bot(token=SUPPORT_BOT_TOKEN)

    # We defer the actual runner execution
    from support_bot.runner import run_support_bot
    try:
        # Check connection once safely
        me = await shared_bot.get_me()
        logger.info(f"[SupportBot] Connection validated. Username: @{me.username} (ID: {me.id})")
        
        # Start the polling loop inside an asyncio Task
        asyncio.create_task(run_support_bot(bot=shared_bot))
        logger.info("[SupportBot] Background polling task successfully scheduled.")
    except Exception as e:
        logger.error(f"[SupportBot] Failed to boot Telegram polling: {e}")
        print(f"❌ Support Bot polling failed to start: {e}")

async def main():
    # Ensure database tables exist
    await init_support_db()

    # Start bot in background
    await start_bot_polling()

    # Start RAM simulation task in background
    asyncio.create_task(simulate_memory_leak_task())

    # Build and launch Aiohttp Web Application
    app = make_app()
    runner = web.AppRunner(app)
    await runner.setup()

    port = int(os.getenv("SUPPORT_PORT", 8081))
    site = web.TCPSite(runner, "0.0.0.0", port)
    
    await site.start()
    logger.info(f"🌐 Support Dashboard Web Server running at http://localhost:{port}")
    print(f"✅ Standalone Support Subsystem running at http://localhost:{port}")

    # Keep server running infinitely
    try:
        while True:
            await asyncio.sleep(3600)
    except (KeyboardInterrupt, asyncio.CancelledError):
        pass
    finally:
        await runner.cleanup()
        logger.info("Server shut down.")

if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        print("\nShutdown support bot subsystem.")
