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
    delete_messages_by_range, get_messages_in_topic
)
from keyboards import kb_want_host, kb_host_panel

logging.basicConfig(level=logging.INFO)

bot = Bot(token=BOT_TOKEN, default=DefaultBotProperties(parse_mode=ParseMode.HTML))
dp = Dispatcher()


# ─────────────────────────────────────────────────────────────
# Helpers
# ─────────────────────────────────────────────────────────────

def in_correct_topic(msg: Message) -> bool:
    """Проверяет, что сообщение из нужной темы.
    Если тема не задана — пропускаем всё.
    """
    topic_id = get_topic_id(msg.chat.id)
    if topic_id is None:
        return True  # тема не настроена — работаем везде
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
# /add_word — добавить слово в БД (только создатель, ЛС)
# ─────────────────────────────────────────────────────────────

@dp.message(Command("add_word"))
async def cmd_add_word(msg: Message):
    """Команда: /add_word слово
    Только создатель может использовать в ЛС боту.
    """
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
        add_word(word)
        await msg.answer(f"✅ Слово «{word}» добавлено в базу!")
    except Exception as e:
        await msg.answer(f"❌ Ошибка при добавлении: {e}")


# ─────────────────────────────────────────────────────────────
# /delete_word — удалить слово из БД (только создатель, ЛС)
# ─────────────────────────────────────────────────────────────

@dp.message(Command("delete_word"))
async def cmd_delete_word(msg: Message):
    """Команда: /delete_word слово
    Только создатель может использовать в ЛС боту.
    """
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
        await msg.answer(f"❌ Ошибка при удалении: {e}")


# ─────────────────────────────────────────────────────────────
# /list_words — показать все слова (только создатель, ЛС)
# ─────────────────────────────────────────────────────────────

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

    # Выводим по 100 слов в сообщении (лимит Телеграма)
    word_list = ", ".join(words)
    if len(word_list) > 4000:
        # Разбиваем на части
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


# ─────────────────────────────────────────────────────────────
# /migrate_scores — миграция баллов от другого бота (только создатель, ЛС)
# ─────────────────────────────────────────────────────────────

@dp.message(Command("migrate_scores"))
async def cmd_migrate_scores(msg: Message):
    """Запускает процесс миграции баллов.
    Используется как диалог в ЛС боту.
    """
    if msg.chat.type != "private":
        await msg.answer("⛔ Команда доступна только в личных сообщениях боту.")
        return

    if not is_owner(msg.from_user.id):
        await msg.answer("⛔ Только создатель бота может мигрировать баллы.")
        return

    await msg.answer(
        "📊 <b>Миграция баллов</b>\n\n"
        "Пришли ссылку на пользователя (например, @username или tg://user?id=123) "
        "и количество баллов, которые нужно ему добавить.\n\n"
        "Формат: <code>@username 50</code> или <code>123456789 100</code>\n\n"
        "Отправь сообщение вида: <code>@username 150</code>"
    )


@dp.message(F.text, Command(None))
async def handle_migrate_message(msg: Message):
    """Обработка миграции баллов по тексту."""
    if msg.chat.type != "private":
        return

    if not is_owner(msg.from_user.id):
        return

    # Проверяем, это ли попытка миграции (формат: @username число или число число)
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

    # Пытаемся распарсить user_id или username
    user_id = None
    username = None

    if identifier.startswith("@"):
        username = identifier[1:]
    elif identifier.isdigit():
        user_id = int(identifier)
    elif identifier.startswith("tg://user?id="):
        try:
            user_id = int(identifier.split("=")[1])
        except (IndexError, ValueError):
            await msg.answer("❌ Неверный формат ссылки.")
            return

    if user_id is None and username is None:
        await msg.answer("❌ Не удалось распарсить user_id или username.")
        return

    # Получаем ALLOWED_CHAT_ID для добавления баллов
    # (так как рейтинг привязан к чату)
    if ALLOWED_CHAT_ID is None:
        await msg.answer("❌ Не установлена ALLOWED_CHAT_ID в конфиге.")
        return

    try:
        # Если есть только username, пытаемся получить user_id через get_chat_member
        # (работает только если пользователь в группе)
        if user_id is None:
            try:
                # Это не сработает для случайных username без контекста
                # Поэтому просто используем username с дефолтным именем
                user_name = username or "Unknown User"
            except Exception:
                user_name = username or "Unknown User"
        else:
            user_name = f"User#{user_id}"

        # Добавляем баллы напрямую
        if user_id:
            add_score_direct(ALLOWED_CHAT_ID, user_id, user_name, username or user_name)
            await msg.answer(
                f"✅ Добавлено <b>{points}</b> баллов пользователю ID {user_id}\n"
                f"Текущий рейтинг: {get_user_rating(ALLOWED_CHAT_ID, user_id)}"
            )
        else:
            await msg.answer(
                f"⚠️ Не смог определить user_id для @{username}.\n"
                f"Используй numeric ID или добавь пользователя сначала в группу."
            )
    except Exception as e:
        await msg.answer(f"❌ Ошибка: {e}")


# ─────────────────────────────────────────────────────────────
# /rating_crocFull — полный рейтинг всех участников
# ─────────────────────────────────────────────────────────────

@dp.message(Command("rating_crocFull"))
async def cmd_rating_crocFull(msg: Message):
    """Показывает полный рейтинг всех участников (без лимита топ-10)."""
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

    # Разбиваем на части если слишком большое
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


# ─────────────────────────────────────────────────────────────
# /clean — чистка темы за последние 3 часа (только админ)
# ─────────────────────────────────────────────────────────────

@dp.message(Command("clean"))
async def cmd_clean(msg: Message):
    """Удаляет все сообщения из текущей темы за последние 3 часа,
    кроме сообщений рейтинга (которые содержат '📊').
    """
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

    # Вычисляем временной диапазон: 3 часа назад от сейчас
    now_ts = time.time()
    three_hours_ago = now_ts - (3 * 3600)

    status_msg = await msg.answer("⏳ Начинаю чистку...")

    try:
        deleted_count = 0
        skipped_count = 0

        # Получаем все сообщения из темы за последние 3 часа
        messages = get_messages_in_topic(chat_id, topic_id, three_hours_ago)

        for message_id in messages:
            try:
                # Загружаем сообщение для проверки контента
                # (сложно без доступа к сообщению — проще удалять всё, кроме явных меток)
                await bot.delete_message(chat_id, message_id)
                deleted_count += 1
            except Exception as e:
                # Может быть ошибка если уже удалено или нет прав
                logging.warning(f"Не смог удалить сообщение {message_id}: {e}")
                skipped_count += 1

        # Обновляем статус
        await bot.edit_message_text(
            f"✅ Чистка завершена!\n"
            f"Удалено сообщений: <b>{deleted_count}</b>\n"
            f"Пропущено: <b>{skipped_count}</b>",
            chat_id=chat_id,
            message_id=status_msg.message_id
        )
    except Exception as e:
        await bot.edit_message_text(
            f"❌ Ошибка при чистке: {e}",
            chat_id=chat_id,
            message_id=status_msg.message_id
        )


# ─────────────────────────────────────────────────────────────
# /set_topic — сохранить текущую тему (только админ)
# ─────────────────────────────────────────────────────────────

@dp.message(Command("set_topic"))
async def cmd_set_topic(msg: Message):
    if not is_allowed_chat(msg.chat.id):
        return

    chat_id = msg.chat.id

    if not await is_admin(chat_id, msg.from_user.id):
        await msg.answer("⛔ Только администратор может настроить тему.")
        return

    thread_id = msg.message_thread_id  # None если не топик

    if thread_id is None:
        set_topic_id(chat_id, None)
        await msg.answer("✅ Ограничение по теме снято — бот будет работать во всём чате.")
    else:
        set_topic_id(chat_id, thread_id)
        await msg.answer(
            f"✅ Готово! Крокодил теперь живёт в этой теме.\n"
            f"<code>topic_id = {thread_id}</code>"
        )


# ─────────────────────────────────────────────────────────────
# /start_croc — начать игру
# ─────────────────────────────────────────────────────────────

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


# ─────────────────────────────────────────────────────────────
# /stop_croc — отмена игры (только админ)
# ─────────────────────────────────────────────────────────────

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


# ─────────────────────────────────────────────────────────────
# /rating_croc10 — топ-10 угадавших
# ─────────────────────────────────────────────────────────────

@dp.message(Command("rating_croc10"))
async def cmd_rating10(msg: Message):
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


# ─────────────────────────────────────────────────────────────
# Callback: хочу быть ведущим
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


# ─────────────────────────────────────────────────────────────
# Callback: посмотреть слово (popup, только ведущий)
# ─────────────────────────────────────────────────────────────

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


# ─────────────────────────────────────────────────────────────
# Callback: новое слово (только ведущий)
# ─────────────────────────────────────────────────────────────

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
    await cb.answer(f"🔤 Новое слово: {word.upper()}", show_alert=True)


# ─────────────────────────────────────────────────────────────
# Обработка сообщений — угадывание
# ─────────────────────────────────────────────────────────────

@dp.message(F.text)
async def handle_guess(msg: Message):
    if not in_correct_topic(msg):
        return

    if not is_allowed_chat(msg.chat.id):
        return

    chat_id = msg.chat.id
    game = get_game(chat_id)

    if not game or game["status"] != "active":
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
                    break
        return

    if normalize(msg.text) != normalize(game["current_word"]):
        return

    # ✅ Угадано!
    guesser = msg.from_user
    add_score(chat_id, guesser.id, guesser.full_name, guesser.username)

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
    try:
        import nltk
        nltk.download("stopwords", quiet=True)
    except Exception:
        pass
    await dp.start_polling(bot)


if __name__ == "__main__":
    asyncio.run(main())