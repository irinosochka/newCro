from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton


def kb_want_host() -> InlineKeyboardMarkup:
    """Кнопка после угадывания слова — хочу стать ведущим."""
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="🐊 Хочу быть ведущим!", callback_data="want_host")]
    ])


def kb_host_panel() -> InlineKeyboardMarkup:
    """Панель ведущего — посмотреть слово и взять новое."""
    return InlineKeyboardMarkup(inline_keyboard=[
        [
            InlineKeyboardButton(text="👁 Посмотреть слово", callback_data="show_word"),
            InlineKeyboardButton(text="🔄 Новое слово", callback_data="new_word"),
        ]
    ])