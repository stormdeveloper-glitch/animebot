import os
from dotenv import load_dotenv

load_dotenv()

BOT_TOKEN = os.getenv("BOT_TOKEN")
BOT_USERNAME = os.getenv("BOT_USERNAME")
SUPER_ADMIN_ID = int(os.getenv("SUPER_ADMIN_ID", 0))
ADMIN_IDS = [int(x) for x in os.getenv("ADMIN_IDS", "").split(",") if x]
MAIN_CHANNEL_ID = os.getenv("MAIN_CHANNEL_ID")
MAIN_CHANNEL_USERNAME = os.getenv("MAIN_CHANNEL_USERNAME", "")
# --- AI: OpenRouter (faqat bepul modellar) ---
OPENROUTER_API_KEY = os.getenv("OPENROUTER_API_KEY", "").strip()
OPENROUTER_BASE_URL = os.getenv("OPENROUTER_BASE_URL", "https://openrouter.ai/api/v1").rstrip("/")
OPENROUTER_MODELS = [m.strip() for m in os.getenv("OPENROUTER_MODELS", "").split(",") if m.strip()]
OPENROUTER_APP_NAME = os.getenv("OPENROUTER_APP_NAME", "ANIME UZ").strip()
OPENROUTER_SITE_URL = os.getenv("OPENROUTER_SITE_URL", "").strip()

# --- GROQ AI (qo'shimcha bepul provayder, ixtiyoriy) ---
GROQ_API_KEY = os.getenv("GROQ_API_KEY", "").strip()
GROQ_MODEL_GENERAL = os.getenv("GROQ_MODEL_GENERAL", "llama-3.3-70b-versatile")

# Provayderlar tartibi va model limitiga yetganda almashish
AI_PROVIDER_ORDER = [p.strip().lower() for p in os.getenv("AI_PROVIDER_ORDER", "openrouter,groq").split(",") if p.strip()]
AI_MODEL_COOLDOWN_SECONDS = int(os.getenv("AI_MODEL_COOLDOWN_SECONDS", "600"))
AI_MAX_MODEL_ATTEMPTS = int(os.getenv("AI_MAX_MODEL_ATTEMPTS", "4"))

# --- AI chat: kunlik bepul urinishlar ---
AI_DAILY_LIMIT = max(1, int(os.getenv("AI_DAILY_LIMIT", "5")))
AI_QUOTA_TZ_OFFSET = int(os.getenv("AI_QUOTA_TZ_OFFSET", "5"))  # Toshkent (UTC+5)
AI_IP_DAILY_GUARD = int(os.getenv("AI_IP_DAILY_GUARD", "60"))
WEB_PUBLIC_ORIGIN = os.getenv("WEB_PUBLIC_ORIGIN", "").rstrip("/")
WEB_SESSION_TTL_HOURS = int(os.getenv("WEB_SESSION_TTL_HOURS", "24"))
WEB_RATE_LIMIT_PER_MIN = int(os.getenv("WEB_RATE_LIMIT_PER_MIN", "180"))
WEB_API_RATE_LIMIT_PER_MIN = int(os.getenv("WEB_API_RATE_LIMIT_PER_MIN", "90"))
WEB_MEDIA_RATE_LIMIT_PER_MIN = int(os.getenv("WEB_MEDIA_RATE_LIMIT_PER_MIN", "120"))
WEB_MAX_CONCURRENT_REQUESTS = int(os.getenv("WEB_MAX_CONCURRENT_REQUESTS", "80"))
WEB_REQUEST_TIMEOUT_SECONDS = int(os.getenv("WEB_REQUEST_TIMEOUT_SECONDS", "25"))
BOT_USER_RATE_LIMIT_PER_MIN = int(os.getenv("BOT_USER_RATE_LIMIT_PER_MIN", "80"))

# --- Animatsiyali (custom) emoji ---
# Telegram custom emoji (<tg-emoji>) ni faqat Fragment'da username sotib olgan botlar
# yoki egasi Premium bo'lgan botlar yubora oladi. Aks holda Telegram butun xabarni
# rad etadi ("can't parse entities") va foydalanuvchi hech narsa ko'rmaydi.
# Shuning uchun standart holatda oddiy emoji yuboriladi; "1" qilib yoqsangiz animatsiyali.
CUSTOM_EMOJI_ENABLED = os.getenv("CUSTOM_EMOJI_ENABLED", "0").strip().lower() in {"1", "true", "yes", "on"}

# --- ANILIST API ---
ANILIST_CLIENT_ID = os.getenv("ANILIST_CLIENT_ID", "").strip()
ANILIST_CLIENT_SECRET = os.getenv("ANILIST_CLIENT_SECRET", "").strip()
ANILIST_REDIRECT_URI = os.getenv("ANILIST_REDIRECT_URI", "").strip()

# ── Support Bot ───────────────────────────────────────────────────────────────
SUPPORT_BOT_TOKEN   = os.getenv("SUPPORT_BOT_TOKEN", "")       # Support botning tokeni
SUPPORT_GROUP_ID    = int(os.getenv("SUPPORT_GROUP_ID", 0))    # Admin guruhi ID (-100...)
SUPPORT_BOT_USERNAME = os.getenv("SUPPORT_BOT_USERNAME", "")   # @support_bot_username
MAIN_BOT_USERNAME   = os.getenv("BOT_USERNAME", "")            # Asosiy bot username (info uchun)

# Google OAuth
GOOGLE_CLIENT_ID     = os.getenv("GOOGLE_CLIENT_ID", "")
GOOGLE_CLIENT_SECRET = os.getenv("GOOGLE_CLIENT_SECRET", "")
GOOGLE_REDIRECT_URI  = os.getenv("GOOGLE_REDIRECT_URI", "")  # https://yoursite.railway.app/callback

# Spotify OAuth
SPOTIFY_CLIENT_ID     = os.getenv("SPOTIFY_CLIENT_ID", "")
SPOTIFY_CLIENT_SECRET = os.getenv("SPOTIFY_CLIENT_SECRET", "")
SPOTIFY_REDIRECT_URI  = os.getenv("SPOTIFY_REDIRECT_URI", "")  # https://yoursite.railway.app/callbackspotify

BASE_DIR = os.path.dirname(os.path.abspath(__file__))

# Railway Volume uchun yo'lni tekshirish
if os.path.exists("/app/data"):
    DATA_DIR = "/app/data"
else:
    DATA_DIR = os.path.join(BASE_DIR, "data")

DB_PATH = os.path.join(DATA_DIR, "bot.db")
DATABASE_URL = os.getenv("DATABASE_URL", "")
MYSQL_URL = os.getenv("MYSQL_URL", "")

BUCKET = os.getenv("BUCKET", "")
REGION = os.getenv("REGION", "")
ENDPOINT = os.getenv("ENDPOINT", "")
ACCESS_KEY_ID = os.getenv("ACCESS_KEY_ID", "")
SECRET_ACCESS_KEY = os.getenv("SECRET_ACCESS_KEY", "")

# Instagram Graph API — professional akkauntdagi reel/postlarni import qilish uchun
INSTAGRAM_ACCESS_TOKEN = os.getenv("INSTAGRAM_ACCESS_TOKEN", "")
INSTAGRAM_USER_ID = os.getenv("INSTAGRAM_USER_ID", "")
INSTAGRAM_API_VERSION = os.getenv("INSTAGRAM_API_VERSION", "v24.0")

# Papkani yaratish (agar yo'q bo'lsa)
os.makedirs(DATA_DIR, exist_ok=True)
