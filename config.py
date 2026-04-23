import os
import random
from dotenv import load_dotenv

load_dotenv()

BOT_TOKEN: str = os.environ["BOT_TOKEN"]

# ID создателя бота (для управления словами и миграции)
OWNER_ID: int = int(os.environ.get("OWNER_ID", "0"))

# ID группы, в которой работает бот (None = везде)
# Установи сюда chat_id своей группы чтобы бот работал только там
ALLOWED_CHAT_ID: int | None = None
try:
    allowed = os.environ.get("ALLOWED_CHAT_ID")
    if allowed and allowed != "None" and allowed != "":
        ALLOWED_CHAT_ID = int(allowed)
except (ValueError, TypeError):
    ALLOWED_CHAT_ID = None

# Через сколько секунд считать раунд «зависшим» и разрешить новую игру
ROUND_TIMEOUT: int = int(os.getenv("ROUND_TIMEOUT", "300"))  # 5 минут


def random_word() -> str:
    """Возвращает случайное слово из БД."""
    from db import get_all_words
    words = get_all_words()
    if not words:
        return "слово"  # Фолбэк если БД пуста
    return random.choice(words)


def user_mention(name: str, user_id: int) -> str:
    """Возвращает вечную inline-ссылку на пользователя по user_id."""
    return f'<a href="tg://user?id={user_id}">{name}</a>'


def normalize(text: str) -> str:
    """Нормализует строку для сравнения угадывания.
    - регистр не важен
    - е и ё считаются одинаковыми
    - дефис и пробел взаимозаменяемы
    """
    t = text.strip().lower()
    t = t.replace("ё", "е")
    t = t.replace("-", " ")
    return t