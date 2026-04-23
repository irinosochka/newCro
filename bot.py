import asyncio
import logging
import time
from datetime import datetime, timedelta

from aiogram import Bot, Dispatcher, F
from aiogram.client.default import DefaultBotProperties
from aiogram.enums import ParseMode
from aiogram.filters import Command
from aiogram.types import Message, CallbackQuery

from config import BOT_TOKEN, ROUND_TIMEOUT, random_word, normalize, user_mention, OWNER_ID, ALLOWED_CHAT_ID

# Морфологический анализатор + стеммер для проверки однокоренных слов
try:
    import pymorphy3
    from nltk.stem.snowball import SnowballStemmer
    _morph = pymorphy3.MorphAnalyzer()
    _stemmer = SnowballStemmer("russian")

    def get_variants(word: str) -> set[str]:
        """Возвращает лемму и стем слова — для широкой проверки однокоренных."""
        w = word.strip().lower().replace("ё", "е")
        parsed = _morph.parse(w)
        lemma = parsed[0].normal_form if parsed else w
        stem = _stemmer.stem(w)
        return {lemma, stem}

    MORPH_AVAILABLE = True
except ImportError:
    MORPH_AVAILABLE = False
    def get_variants(word: str) -> set[str]:
        w = word.strip().lower().replace("ё", "е")
        return {w}

from db import (
    init_db, get_game, upsert_game, add_score, get_top,
    get_topic_id, set_topic_id,
    add_word, delete_word, get_all_words,
    add_score_direct, get_user_rating, get_all_ratings,
    delete_messages_by_range, get_messages_in_topic,
    get_user_by_username
)
from keyboards import kb_want_host, kb_host_panel

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

bot = Bot(token=BOT_TOKEN, default=DefaultBotProperties(parse_mode=ParseMode.HTML))
dp = Dispatcher()


# ─────────────────────────────────────────────────────────────
# Helpers
# ─────────────────────────────────────────────────────────────

def in_correct_topic(msg: Message) -> bool:
    """Проверяет, что сообщение из нужной темы."""
    topic_id = get_topic_id(msg.chat.id)
    if topic_id is None:
        return True
    return msg.message_thread_id == topic_id


def in_correct_topic_cb(cb: CallbackQuery) -> bool:
    if not cb.message:
        return True
    topic_id = get_topic_id(cb.message.chat.id)
    if topic_id is None:
        return True
    return cb.message.message_thread_id == topic_id


def is_owner(user_id: int) -> bool:
    """Проверяет, что это создатель бота."""
    return user_id == OWNER_ID


def is_allowed_chat(chat_id: int) -> bool:
    """Проверяет, что чат — разрешённая группа."""
    if ALLOWED_CHAT_ID is None:
        return True
    return chat_id == ALLOWED_CHAT_ID


async def is_admin(chat_id: int, user_id: int) -> bool:
    member = await bot.get_chat_member(chat_id, user_id)
    return member.status in ("administrator", "creator")


def medals(pos: int) -> str:
    m = {1: "🥇", 2: "🥈", 3: "🥉"}
    return m.get(pos, f"{pos}.")


# ─────────────────────────────────────────────────────────────
# КОМАНДЫ (регистрируются ПЕРВЫМИ)
# ─────────────────────────────────────────────────────────────

@dp.message(Command("add_word"))
async def cmd_add_word(msg: Message):
    """Команда: /add_word слово"""
    if msg.chat.type != "private":
        await msg.answer("⛔ Команда доступна только в личных сообщениях боту.")
        return

    if not is_owner(msg.from_user.id):
        await msg.answer("⛔ Только создатель бота может добавлять слова.")
        return

    parts = msg.text.split(maxsplit=1)
    if len(parts) < 2:
        await msg.answer("📝 Использование: <code>/add_word слово</code>")
        return

    word = parts[1].strip().lower()
    if not word:
        await msg.answer("❌ Слово не может быть пустым.")
        return

    try:
        if add_word(word):
            await msg.answer(f"✅ Слово «{word}» добавлено в базу!")
        else:
            await msg.answer(f"⚠️ Слово «{word}» уже существует в базе.")
    except Exception as e:
        logger.error(f"Ошибка при добавлении слова: {e}")
        await msg.answer(f"❌ Ошибка при добавлении: {e}")


@dp.message(Command("delete_word"))
async def cmd_delete_word(msg: Message):
    """Команда: /delete_word слово"""
    if msg.chat.type != "private":
        await msg.answer("⛔ Команда доступна только в личных сообщениях боту.")
        return

    if not is_owner(msg.from_user.id):
        await msg.answer("⛔ Только создатель бота может удалять слова.")
        return

    parts = msg.text.split(maxsplit=1)
    if len(parts) < 2:
        await msg.answer("📝 Использование: <code>/delete_word слово</code>")
        return

    word = parts[1].strip().lower()
    if not word:
        await msg.answer("❌ Слово не может быть пустым.")
        return

    try:
        deleted = delete_word(word)
        if deleted:
            await msg.answer(f"✅ Слово «{word}» удалено из базы.")
        else:
            await msg.answer(f"⚠️ Слово «{word}» не найдено в базе.")
    except Exception as e:
        logger.error(f"Ошибка при удалении слова: {e}")
        await msg.answer(f"❌ Ошибка при удалении: {e}")


@dp.message(Command("list_words"))
async def cmd_list_words(msg: Message):
    """Показывает все слова из БД."""
    if msg.chat.type != "private":
        await msg.answer("⛔ Команда доступна только в личных сообщениях боту.")
        return

    if not is_owner(msg.from_user.id):
        await msg.answer("⛔ Только создатель бота может просматривать слова.")
        return

    words = get_all_words()
    if not words:
        await msg.answer("📭 База слов пуста.")
        return

    word_list = ", ".join(words)
    if len(word_list) > 4000:
        chunks = []
        current = []
        for w in words:
            if sum(len(x) + 2 for x in current) + len(w) + 2 > 3900:
                chunks.append(", ".join(current))
                current = [w]
            else:
                current.append(w)
        if current:
            chunks.append(", ".join(current))

        for i, chunk in enumerate(chunks, 1):
            await msg.answer(f"<b>Слова (часть {i}/{len(chunks)}):</b>\n{chunk}")
    else:
        await msg.answer(f"<b>Все слова ({len(words)} шт.):</b>\n{word_list}")


@dp.message(Command("migrate_scores"))
async def cmd_migrate_scores(msg: Message):
    """Запускает процесс миграции баллов в ЛС."""
    if msg.chat.type != "private":
        await msg.answer("⛔ Команда доступна только в личных сообщениях боту.")
        return

    if not is_owner(msg.from_user.id):
        await msg.answer("⛔ Только создатель бота может мигрировать баллы.")
        return

    await msg.answer(
        "📊 <b>Миграция баллов</b>\n\n"
        "Пришли ссылку на пользователя и количество баллов.\n\n"
        "Формат: <code>@username 50</code> или <code>123456789 100</code>\n\n"
        "Отправь сообщение вида: <code>@username 150</code>"
    )


@dp.message(Command("full_rating"))
async def cmd_full_rating(msg: Message):
    """Показывает полный рейтинг всех участников."""
    if not in_correct_topic(msg):
        return

    if not is_allowed_chat(msg.chat.id):
        return

    rows = get_all_ratings(msg.chat.id)
    if not rows:
        await msg.answer("📊 Пока никто ничего не угадал.")
        return

    lines = ["📊 <b>Полный рейтинг:</b>\n"]
    for i, row in enumerate(rows, 1):
        mention = user_mention(row["user_name"], row["user_id"])
        lines.append(f"{medals(i)} {mention} — <b>{row['score']}</b> сл.")

    text = "\n".join(lines)
    if len(text) > 4000:
        chunks = []
        current_chunk = ["📊 <b>Полный рейтинг:</b>\n"]
        for line in lines[1:]:
            if len("\n".join(current_chunk) + "\n" + line) > 3900:
                chunks.append("\n".join(current_chunk))
                current_chunk = [line]
            else:
                current_chunk.append(line)
        if current_chunk:
            chunks.append("\n".join(current_chunk))

        for i, chunk in enumerate(chunks, 1):
            await msg.answer(f"{chunk}\n(часть {i}/{len(chunks)})")
    else:
        await msg.answer(text)


@dp.message(Command("clean"))
async def cmd_clean(msg: Message):
    """Удаляет все сообщения из текущей темы за последние 3 часа."""
    if not in_correct_topic(msg):
        return

    if not is_allowed_chat(msg.chat.id):
        return

    chat_id = msg.chat.id
    if not await is_admin(chat_id, msg.from_user.id):
        await msg.answer("⛔ Только администратор может чистить тему.")
        return

    topic_id = msg.message_thread_id
    if topic_id is None:
        await msg.answer("❌ Команда работает только в темах (topical groups).")
        return

    now_ts = time.time()
    three_hours_ago = now_ts - (3 * 3600)

    status_msg = await msg.answer("⏳ Начинаю чистку...")

    try:
        deleted_count = 0
        skipped_count = 0

        messages = get_messages_in_topic(chat_id, topic_id, three_hours_ago)

        for message_id in messages:
            try:
                await bot.delete_message(chat_id, message_id)
                deleted_count += 1
            except Exception as e:
                logger.warning(f"Не смог удалить сообщение {message_id}: {e}")
                skipped_count += 1

        await bot.edit_message_text(
            f"✅ Чистка завершена!\n"
            f"Удалено сообщений: <b>{deleted_count}</b>\n"
            f"Пропущено: <b>{skipped_count}</b>",
            chat_id=chat_id,
            message_id=status_msg.message_id
        )
    except Exception as e:
        logger.error(f"Ошибка при чистке: {e}")
        await bot.edit_message_text(
            f"❌ Ошибка при чистке: {e}",
            chat_id=chat_id,
            message_id=status_msg.message_id
        )


@dp.message(Command("set_topic"))
async def cmd_set_topic(msg: Message):
    if not is_allowed_chat(msg.chat.id):
        return

    chat_id = msg.chat.id

    if not await is_admin(chat_id, msg.from_user.id):
        await msg.answer("⛔ Только администратор может настроить тему.")
        return

    thread_id = msg.message_thread_id

    if thread_id is None:
        set_topic_id(chat_id, None)
        await msg.answer("✅ Ограничение по теме снято — бот будет работать во всём чате.")
    else:
        set_topic_id(chat_id, thread_id)
        await msg.answer(
            f"✅ Готово! Крокодил теперь живёт в этой теме.\n"
            f"<code>topic_id = {thread_id}</code>"
        )


@dp.message(Command("start_croc"))
async def cmd_start_croc(msg: Message):
    if not in_correct_topic(msg):
        return

    if not is_allowed_chat(msg.chat.id):
        await msg.answer("❌ Этот бот работает только в определённой группе.")
        return

    chat_id = msg.chat.id
    game = get_game(chat_id)
    now = time.time()

    if game:
        status = game["status"]

        if status == "waiting_host":
            await msg.answer("⏳ Уже ждём ведущего! Нажми кнопку «Хочу быть ведущим».")
            return

        if status == "active":
            elapsed = now - (game["round_start_ts"] or now)
            remaining = ROUND_TIMEOUT - elapsed
            if remaining > 0:
                mins = int(remaining // 60)
                secs = int(remaining % 60)
                await msg.answer(
                    f"🎮 Игра уже идёт! Подожди {mins}:{secs:02d} — "
                    f"если ведущий пропал, тогда можно начать заново."
                )
                return

    word = random_word()
    logger.info(f"[START] chat={chat_id} word={word}")
    upsert_game(
        chat_id,
        topic_id=msg.message_thread_id,
        status="waiting_host",
        host_user_id=None,
        host_name=None,
        host_username=None,
        current_word=word,
        announce_message_id=None,
        round_start_ts=now,
        last_no_host_ts=now,
    )

    sent = await msg.answer(
        "🐊 <b>Новый раунд Крокодила!</b>\n\nКто хочет объяснять слово?",
        reply_markup=kb_want_host(),
    )
    upsert_game(chat_id, announce_message_id=sent.message_id)


@dp.message(Command("stop_croc"))
async def cmd_stop_croc(msg: Message):
    if not in_correct_topic(msg):
        return

    if not is_allowed_chat(msg.chat.id):
        return

    chat_id = msg.chat.id
    if not await is_admin(chat_id, msg.from_user.id):
        await msg.answer("⛔ Только администратор может остановить игру.")
        return

    game = get_game(chat_id)
    if not game or game["status"] == "idle":
        await msg.answer("Игры нет, нечего останавливать.")
        return

    upsert_game(chat_id, status="idle")
    await msg.answer("🛑 Игра остановлена администратором.")


@dp.message(Command("rating_croc"))
async def cmd_rating(msg: Message):
    if not in_correct_topic(msg):
        return

    if not is_allowed_chat(msg.chat.id):
        return

    rows = get_top(msg.chat.id, limit=10)
    if not rows:
        await msg.answer("📊 Пока никто ничего не угадал.")
        return

    lines = ["📊 <b>Топ-10 угадавших:</b>\n"]
    for i, row in enumerate(rows, 1):
        mention = user_mention(row["user_name"], row["user_id"])
        lines.append(f"{medals(i)} {mention} — <b>{row['score']}</b> сл.")

    await msg.answer("\n".join(lines))


@dp.message(Command("debug_game"))
async def cmd_debug_game(msg: Message):
    """DEBUG: показывает состояние игры."""
    if not is_owner(msg.from_user.id):
        return
    
    game = get_game(msg.chat.id)
    
    if not game:
        await msg.answer("❌ Нет игры в этом чате")
        return
    
    await msg.answer(
        f"<b>🔍 DEBUG INFO:</b>\n"
        f"Chat ID: {msg.chat.id}\n"
        f"Status: <code>{game['status']}</code>\n"
        f"Current word: <code>{game['current_word']}</code>\n"
        f"Host ID: {game['host_user_id']}\n"
        f"Host name: {game['host_name']}"
    )


# ─────────────────────────────────────────────────────────────
# CALLBACK QUERIES (кнопки)
# ─────────────────────────────────────────────────────────────

@dp.callback_query(F.data == "want_host")
async def cb_want_host(cb: CallbackQuery):
    if not in_correct_topic_cb(cb):
        await cb.answer()
        return

    if not is_allowed_chat(cb.message.chat.id):
        await cb.answer("❌ Этот бот работает только в определённой группе.")
        return

    chat_id = cb.message.chat.id
    game = get_game(chat_id)

    if not game or game["status"] != "waiting_host":
        await cb.answer("Ведущий уже выбран или игры нет.", show_alert=True)
        return

    user = cb.from_user
    upsert_game(
        chat_id,
        status="active",
        host_user_id=user.id,
        host_name=user.full_name,
        host_username=user.username,
        round_start_ts=time.time(),
    )

    mention = user_mention(user.full_name, user.id)

    try:
        win_text = game["last_win_text"]
        if win_text:
            await cb.message.edit_text(win_text, reply_markup=None)
        else:
            await cb.message.edit_reply_markup(reply_markup=None)
    except Exception:
        pass

    await bot.send_message(
        chat_id,
        f"🎤 {mention}, ты ведущий! Нажми кнопку чтобы узнать слово.",
        reply_markup=kb_host_panel(),
        message_thread_id=cb.message.message_thread_id,
    )

    await cb.answer("Ты теперь ведущий! 🐊")


@dp.callback_query(F.data == "show_word")
async def cb_show_word(cb: CallbackQuery):
    chat_id = cb.message.chat.id

    if not is_allowed_chat(chat_id):
        await cb.answer()
        return

    game = get_game(chat_id)

    if not game or game["status"] != "active":
        await cb.answer("Игры нет.", show_alert=True)
        return

    if cb.from_user.id != game["host_user_id"]:
        await cb.answer("Это не для тебя 😏", show_alert=True)
        return

    await cb.answer(f"🔤 Твоё слово: {game['current_word'].upper()}", show_alert=True)


@dp.callback_query(F.data == "new_word")
async def cb_new_word(cb: CallbackQuery):
    chat_id = cb.message.chat.id

    if not is_allowed_chat(chat_id):
        await cb.answer()
        return

    game = get_game(chat_id)

    if not game or game["status"] != "active":
        await cb.answer("Игры нет.", show_alert=True)
        return

    if cb.from_user.id != game["host_user_id"]:
        await cb.answer("Только ведущий может взять новое слово.", show_alert=True)
        return

    word = random_word()
    upsert_game(chat_id, current_word=word)
    logger.info(f"[NEW_WORD] chat={chat_id} host={cb.from_user.username} word={word}")
    await cb.answer(f"🔤 Новое слово: {word.upper()}", show_alert=True)


# ─────────────────────────────────────────────────────────────
# ⚠️ ОБРАБОТЧИК МИГРАЦИИ БАЛЛОВ (только в ЛС, только создатель)
# Должен быть ПЕРЕД handle_guess
# ─────────────────────────────────────────────────────────────

@dp.message(F.chat.type == "private", F.text)
async def handle_migrate_message(msg: Message):
    """Обработка миграции баллов (только в ЛС).
    Формат: @username 50 или 123456789 100
    """
    if not is_owner(msg.from_user.id):
        return

    parts = msg.text.split()
    if len(parts) != 2:
        return

    identifier = parts[0]
    try:
        points = int(parts[1])
    except ValueError:
        return

    if points <= 0:
        await msg.answer("❌ Количество баллов должно быть положительным числом.")
        return

    user_id = None
    username = None

    # Парсим identifier
    if identifier.startswith("@"):
        username = identifier[1:]
    elif identifier.isdigit():
        user_id = int(identifier)
    else:
        return

    if ALLOWED_CHAT_ID is None:
        await msg.answer("❌ ALLOWED_CHAT_ID не установлена в конфиге.")
        return

    try:
        # Если передан username, пытаемся найти user_id в БД
        if username and not user_id:
            user_data = get_user_by_username(ALLOWED_CHAT_ID, username)
            if user_data:
                user_id = user_data["user_id"]
                user_name = user_data["user_name"]
            else:
                await msg.answer(
                    f"⚠️ Пользователь @{username} не найден в БД.\n"
                    f"Перешли сообщение от этого пользователя, или используй его numeric ID."
                )
                return
        else:
            user_name = f"User#{user_id}" if user_id else "Unknown"

        # Добавляем баллы
        if user_id:
            add_score_direct(ALLOWED_CHAT_ID, user_id, user_name, username or user_name, points)
            current_score = get_user_rating(ALLOWED_CHAT_ID, user_id)
            await msg.answer(
                f"✅ Добавлено <b>{points}</b> баллов пользователю {user_name}\n"
                f"ID: {user_id}\n"
                f"Новый рейтинг: <b>{current_score}</b>"
            )
    except Exception as e:
        logger.error(f"Ошибка при добавлении баллов: {e}")
        await msg.answer(f"❌ Ошибка: {e}")


# ─────────────────────────────────────────────────────────────
# ⚠️ ОБРАБОТЧИК УГАДЫВАНИЯ (САМЫЙ ПОСЛЕДНИЙ)
# Ловит ВСЕ остальные текстовые сообщения в группе
# ─────────────────────────────────────────────────────────────

@dp.message(F.text, F.chat.type.in_({"group", "supergroup"}))
async def handle_guess(msg: Message):
    """Обработка угадывания слов в игре."""
    logger.info(f"[HANDLE_GUESS_ENTRY] Получено сообщение в группе: '{msg.text[:50]}' от {msg.from_user.username}")
    
    if not in_correct_topic(msg):
        logger.info(f"[HANDLE_GUESS] Неправильная тема, выходим")
        return

    chat_id = msg.chat.id
    game = get_game(chat_id)
    logger.info(f"[HANDLE_GUESS] game exists={game is not None}, status={game['status'] if game else 'NO_GAME'}")

    if not game or game["status"] != "active":
        logger.info(f"[HANDLE_GUESS] Игры нет или не active, выходим")
        return

    # ⚠️ Проверяем, что слово в БД не пусто
    if not game["current_word"]:
        logger.error(f"🚨 current_word пуста в chat {chat_id}! Переинициализируем...")
        new_word = random_word()
        upsert_game(chat_id, current_word=new_word)
        return

    if msg.from_user.id == game["host_user_id"]:
        # Проверяем однокоренные слова у ведущего
        if MORPH_AVAILABLE:
            word_variants = get_variants(game["current_word"])
            PUNCT = ".,!?;:'()[]"
            words_in_msg = [w.strip(PUNCT) for w in msg.text.split()]
            for w in words_in_msg:
                if len(w) < 3:
                    continue
                if get_variants(w) & word_variants:
                    new_w = random_word()
                    upsert_game(chat_id, current_word=new_w)
                    host_mention = user_mention(msg.from_user.full_name, msg.from_user.id)
                    await msg.answer(
                        f"🚫 Аяяй, {host_mention}! Нельзя объяснять однокоренными словами!\n"
                        f"Слово изменено на новое 👇",
                        reply_markup=kb_host_panel(),
                    )
                    return
        return

    # Проверяем угадывание
    normalized_guess = normalize(msg.text).strip()
    normalized_word = normalize(game["current_word"]).strip()
    
    logger.info(f"[GUESS] chat={chat_id} | user={msg.from_user.username} | "
                f"guess='{normalized_guess}' | word='{normalized_word}' | match={normalized_guess == normalized_word}")
    
    if normalized_guess != normalized_word:
        return

    # ✅ Угадано!
    guesser = msg.from_user
    add_score(chat_id, guesser.id, guesser.full_name, guesser.username)
    logger.info(f"[WIN] chat={chat_id} | guesser={guesser.username} | word={game['current_word']}")

    new_word = random_word()
    upsert_game(
        chat_id,
        status="waiting_host",
        host_user_id=None,
        host_name=None,
        host_username=None,
        current_word=new_word,
        round_start_ts=time.time(),
    )

    guesser_mention = user_mention(guesser.full_name, guesser.id)
    host_mention = user_mention(game["host_name"] or "Ведущий", game["host_user_id"])

    win_text = (
        f"🎉 {guesser_mention} угадал(а) слово <b>{game['current_word']}</b>!\n"
        f"Объяснял(а): {host_mention}"
    )
    sent = await msg.answer(
        win_text + "\n\nКто хочет объяснять следующим?",
        reply_markup=kb_want_host(),
    )
    upsert_game(chat_id, last_win_text=win_text)
    upsert_game(chat_id, announce_message_id=sent.message_id)


# ─────────────────────────────────────────────────────────────
# Точка входа
# ─────────────────────────────────────────────────────────────

async def main():
    init_db()
    logger.info("🐊 Крокодил бот запущен!")
    try:
        import nltk
        nltk.download("stopwords", quiet=True)
    except Exception:
        pass
    await dp.start_polling(bot)


if __name__ == "__main__":
    asyncio.run(main())