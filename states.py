from aiogram.fsm.state import State, StatesGroup

class UserStates(StatesGroup):
    search_by_name = State()
    search_by_code = State()
    search_by_genre = State()

class AdminStates(StatesGroup):
    broadcast = State()
    
    # Add Anime Flow
    add_anime_name = State()
    add_anime_english_name = State()
    add_anime_episodes = State()
    add_anime_country = State()
    add_anime_language = State()
    add_anime_year = State()
    add_anime_genre = State()
    add_anime_fandub = State()
    add_anime_status = State() # Yangi: OnGoing yoki Yakunlangan
    add_anime_age = State()    # Yangi: Yosh toifasi
    add_anime_picture = State()
    
    # Add Episode Flow
    add_episode_code = State()
    add_episode_file = State()

    # Delete Anime by Code
    delete_anime_by_code = State()

    # Delete Episode
    delete_episode_anime_code = State()
    delete_episode_number = State()

    # Channel Management
    add_channel_type = State()
    add_channel_name = State()   # Social tarmoq uchun nom
    add_channel_id = State()
    add_channel_link = State()

    # User Management
    manage_user = State()

    # Admin Management
    add_admin = State()
    vip_approve_days = State()

    # Settings Management
    edit_text = State()
    edit_wallet = State()
    edit_search_photo = State()

class EditAnimeStates(StatesGroup):
    select_anime = State()
    edit_field = State()
    confirm_delete = State()

class SettingsStates(StatesGroup):
    edit_value = State()

class ButtonStates(StatesGroup):
    add_btn_text = State()
    add_btn_url = State()

class PostStates(StatesGroup):
    media = State()
    caption = State()
    buttons = State()
    confirm = State()

class PaymentStates(StatesGroup):
    enter_amount = State()
    send_check = State()

class VipStates(StatesGroup):
    choose_plan = State()
    send_check = State()

class TransferStates(StatesGroup):
    enter_user_id = State()
    enter_amount = State()
    confirm = State()
