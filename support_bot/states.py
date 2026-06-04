from aiogram.fsm.state import State, StatesGroup


class SupportUserStates(StatesGroup):
    """Foydalanuvchi murojaati."""
    writing_message = State()    # Xabar yozish
    waiting_response = State()   # Admin javobini kutish


class SupportAdminStates(StatesGroup):
    """Admin javobi (PM da)."""
    replying = State()           # Ticket ga javob yozish
    adding_faq_question = State()
    adding_faq_answer = State()
