import os
from dotenv import load_dotenv

load_dotenv()

# ── Support Bot Standalone Configuration ──────────────────────────────────────
SUPPORT_BOT_TOKEN    = os.getenv("SUPPORT_BOT_TOKEN", "")       # Support bot tokeni
SUPPORT_GROUP_ID     = int(os.getenv("SUPPORT_GROUP_ID", 0))    # Admin guruhi IDsi
SUPPORT_BOT_USERNAME = os.getenv("SUPPORT_BOT_USERNAME", "")   # Bot username
SUPER_ADMIN_ID       = int(os.getenv("SUPER_ADMIN_ID", 0))
ADMIN_IDS            = [int(x) for x in os.getenv("ADMIN_IDS", "").split(",") if x]

BASE_DIR = os.path.dirname(os.path.abspath(__file__))

# Railway Volume yoki mahalliy saqlash yo'li
if os.path.exists("/app/data"):
    DATA_DIR = "/app/data"
else:
    # Asosiy bot papkasiga nisbatan 'data' papkasini olish
    DATA_DIR = os.path.join(os.path.dirname(BASE_DIR), "data")

DB_PATH = os.path.join(DATA_DIR, "bot.db")

# Ma'lumotlar bazasi ulanish sozlamalari
DATABASE_URL = os.getenv("DATABASE_URL", "")
MYSQL_URL = os.getenv("MYSQL_URL", "")

# S3 Bucket (Chelak) sozlamalari
BUCKET = os.getenv("BUCKET", "")
REGION = os.getenv("REGION", "")
ENDPOINT = os.getenv("ENDPOINT", "")
ACCESS_KEY_ID = os.getenv("ACCESS_KEY_ID", "")
SECRET_ACCESS_KEY = os.getenv("SECRET_ACCESS_KEY", "")

# Papkani yaratish
os.makedirs(DATA_DIR, exist_ok=True)
