"""
Admin va Bot amallarni log qilish modulli
Barcha xabarlar O'zbekchada saqlanadi
"""
import os
import json
from datetime import datetime
from config import DATA_DIR, SUPER_ADMIN_ID

LOGS_FILE = os.path.join(DATA_DIR, "admin_logs.json")

# Logs papkasi mavjud bo'lmasa yaratish
os.makedirs(DATA_DIR, exist_ok=True)


def get_timestamp():
    """Hozirgi vaqtni format qilish"""
    return datetime.now().strftime("%Y-%m-%d %H:%M:%S")


def write_log(action_type: str, user_id: int, username: str = "", details: str = ""):
    """
    Admin amalini log fayliga yozish
    
    action_type: 'admin_added', 'admin_removed', 'broadcast', 'anime_added', 'user_banned', 'setting_changed' va boshqalar
    user_id: Amalni bajargan foydalanuvchi ID
    username: Foydalanuvchi username
    details: Qoʻshimcha ma'lumot
    """
    try:
        # Eski loglarni oʻqish
        logs = []
        if os.path.exists(LOGS_FILE):
            try:
                with open(LOGS_FILE, 'r', encoding='utf-8') as f:
                    logs = json.load(f)
            except:
                logs = []
        
        # Yangi log entry
        new_log = {
            "vaqt": get_timestamp(),
            "amal_turi": action_type,
            "user_id": user_id,
            "username": username or f"ID: {user_id}",
            "details": details,
            "id": len(logs) + 1
        }
        
        logs.append(new_log)
        
        # Oxirgi 1000 logni saqlash (hajmni cheklash)
        if len(logs) > 1000:
            logs = logs[-1000:]
        
        # Faylga yozish
        with open(LOGS_FILE, 'w', encoding='utf-8') as f:
            json.dump(logs, f, indent=2, ensure_ascii=False)
        
        return True
    except Exception as e:
        print(f"[LOG XATOSI] {e}")
        return False


def get_logs(limit: int = 50) -> list:
    """Oxirgi N log'ni oʻqish"""
    try:
        if not os.path.exists(LOGS_FILE):
            return []
        
        with open(LOGS_FILE, 'r', encoding='utf-8') as f:
            logs = json.load(f)
        
        # Oxirgi log'larni koʻrsatish
        return logs[-limit:][::-1]  # Teskari tartibda (yangi first)
    except:
        return []


def get_logs_text(limit: int = 50) -> str:
    """Loglarni tezt format'ida qaytarish"""
    logs = get_logs(limit)
    
    if not logs:
        return "📋 Hozircha loglar yo'q"
    
    # Amal turining O'zbekcha nomi
    action_names = {
        "admin_added": "✅ Admin qoʼshildi",
        "admin_removed": "🗑️  Admin oʼchirildi",
        "broadcast": "📬 Broadcast yuborildi",
        "broadcast_complete": "📬 Broadcast yakunlandi",
        "anime_added": "🎬 Anime qoʼshildi",
        "anime_removed": "🎬 Anime oʼchirildi",
        "anime_edited": "✏️  Anime tahrirland",
        "episode_added": "📺 Qism qoʼshildi",
        "episode_removed": "📺 Qism oʼchirildi",
        "user_banned": "🚫 User ban",
        "user_unbanned": "✅ User ban ochildi",
        "channel_added": "📢 Kanal qoʼshildi",
        "channel_removed": "📢 Kanal oʼchirildi",
        "setting_changed": "⚙️  Sozlama oʼzgartirildi",
        "vip_request": "💎 VIP so'rovi",
        "vip_approved": "✅ VIP tasdiqlandi",
        "vip_rejected": "❌ VIP rad etildi",
        "money_transfer": "💸 Pul o'tkazildi",
        "payment_approved": "✅ To'lov tasdiqlandi",
        "payment_rejected": "❌ To'lov rad etildi"
    }
    
    text = "<b>📋 Admin Xulosa Jurnali</b>\n"
    text += "━━━━━━━━━━━━━━━━━━━\n\n"
    
    # Telegram'da maksimum 4096 belgisiga cheklamani hisobga olib
    max_chars = 3500  # Tugmalar uchun joy qoldirish
    
    for log in logs:
        if len(text) > max_chars:
            text += f"\n<i>...yana {len(logs) - logs.index(log)} ta log ko'rsatilmadi</i>"
            break
        
        amal = action_names.get(log['amal_turi'], log['amal_turi'])
        vaqt = log['vaqt']
        user = log['username']
        details = log.get('details', '')
        
        log_entry = f"<b>{amal}</b>\n"
        log_entry += f"⏰ {vaqt}\n"
        log_entry += f"👤 {user}\n"
        if details:
            log_entry += f"📝 {details}\n"
        log_entry += "─────────────\n"
        
        # Agar qo'shmak o'limligi mumkin bo'lsa, qo'shish
        if len(text) + len(log_entry) <= max_chars:
            text += log_entry
        else:
            text += f"\n<i>...yana {len(logs) - logs.index(log)} ta log ko'rsatilmadi</i>"
            break
    
    return text


def log_admin_action(action: str, user_id: int, username: str, **kwargs):
    """Qulay log yozish funksiyasi - butun ma'lumotlar bilan"""
    details = ""
    
    # Har bir amal turi uchun tafsil
    if action == "admin_added":
        new_admin = kwargs.get("new_admin_id", "")
        details = f"Yangi admin: {new_admin}"
    
    elif action == "admin_removed":
        removed_admin = kwargs.get("removed_admin_id", "")
        details = f"Oʼchirilgan admin: {removed_admin}"
    
    elif action == "broadcast":
        user_count = kwargs.get("user_count", 0)
        details = f"{user_count} ta foydalanuvchiga yuborildi"
    
    elif action == "broadcast_complete":
        success = kwargs.get("success", 0)
        failed = kwargs.get("failed", 0)
        details = f"✅ {success} | ❌ {failed}"
    
    elif action == "anime_added":
        anime_name = kwargs.get("anime_name", "")
        details = f"Anime: {anime_name}"
    
    elif action == "episode_added":
        anime_name = kwargs.get("anime_name", "")
        ep_num = kwargs.get("episode_num", "")
        details = f"{anime_name} - Qism {ep_num}"
    
    elif action == "user_banned":
        target_user = kwargs.get("target_user_id", "")
        details = f"Banqlangan user: {target_user}"
    
    elif action == "setting_changed":
        setting_name = kwargs.get("setting_name", "")
        old_val = kwargs.get("old_value", "")
        new_val = kwargs.get("new_value", "")
        details = f"{setting_name}: {old_val} → {new_val}"
    
    elif action == "channel_added":
        channel_type = kwargs.get("channel_type", "")
        details = f"Turi: {channel_type}"
    
    elif action == "vip_request":
        details = kwargs.get("details", "")
    
    elif action == "vip_approved":
        new_admin = kwargs.get("new_admin_id", "")
        vip_days = kwargs.get("vip_days", "")
        details = f"User: {new_admin}, Muddati: {vip_days} kun"
    
    elif action == "vip_rejected":
        details = kwargs.get("details", "")
    
    elif action == "money_transfer":
        details = kwargs.get("details", "")
    
    elif action == "payment_approved":
        details = kwargs.get("details", "")
    
    elif action == "payment_rejected":
        details = kwargs.get("details", "")
    
    else:
        details = str(kwargs.get("details", ""))
    
    write_log(action, user_id, username, details)
