import json
import os
from typing import Dict, List, Optional
from config import DATA_DIR, SUPER_ADMIN_ID, ADMIN_IDS

ADMINS_JSON_PATH = os.path.join(DATA_DIR, "admins.json")

# Default permissions for a new JSON admin
DEFAULT_PERMISSIONS = {
    "stats": False,
    "broadcast": False,
    "channels": False,
    "users": False,
    "anime": False,
    "settings": False
}

def load_admins() -> Dict[str, Dict]:
    if not os.path.exists(ADMINS_JSON_PATH):
        return {}
    try:
        with open(ADMINS_JSON_PATH, 'r', encoding='utf-8') as f:
            return json.load(f)
    except Exception as e:
        print(f"Error loading admins.json: {e}")
        return {}

def save_admins(admins: Dict[str, Dict]):
    try:
        with open(ADMINS_JSON_PATH, 'w', encoding='utf-8') as f:
            json.dump(admins, f, indent=4, ensure_ascii=False)
    except Exception as e:
        print(f"Error saving admins.json: {e}")

def add_json_admin(user_id: int, username: str = "Unknown"):
    admins = load_admins()
    str_id = str(user_id)
    if str_id not in admins:
        admins[str_id] = {
            "username": username,
            "permissions": DEFAULT_PERMISSIONS.copy()
        }
        save_admins(admins)
        return True
    return False

def remove_json_admin(user_id: int):
    admins = load_admins()
    str_id = str(user_id)
    if str_id in admins:
        del admins[str_id]
        save_admins(admins)
        return True
    return False

def update_permissions(user_id: int, permissions: Dict[str, bool]):
    admins = load_admins()
    str_id = str(user_id)
    if str_id in admins:
        admins[str_id]["permissions"].update(permissions)
        save_admins(admins)
        return True
    return False

def get_admin_permissions(user_id: int) -> Optional[Dict[str, bool]]:
    # Super Admin and Env Admins have full access
    if user_id == SUPER_ADMIN_ID or user_id in ADMIN_IDS:
        return {k: True for k in DEFAULT_PERMISSIONS.keys()}
    
    admins = load_admins()
    str_id = str(user_id)
    if str_id in admins:
        return admins[str_id]["permissions"]
    return None

async def has_permission(user_id: int, permission: str) -> bool:
    perms = get_admin_permissions(user_id)
    if perms is None:
        return False
    return perms.get(permission, False)

def is_json_admin(user_id: int) -> bool:
    admins = load_admins()
    return str(user_id) in admins
