import sqlite3
import os
import time

DB_PATH = os.path.join(os.path.dirname(__file__), "crocodile.db")


def get_connection():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn


def init_db():
    conn = get_connection()
    conn.executescript("""
        CREATE TABLE IF NOT EXISTS chat_settings (
            chat_id INTEGER PRIMARY KEY,
            topic_id INTEGER
        );

        CREATE TABLE IF NOT EXISTS game_state (
            chat_id INTEGER PRIMARY KEY,
            topic_id INTEGER,
            status TEXT NOT NULL DEFAULT 'idle',
            host_user_id INTEGER,
            host_name TEXT,
            host_username TEXT,
            current_word TEXT,
            announce_message_id INTEGER,
            round_start_ts REAL,
            last_no_host_ts REAL
        );

        CREATE TABLE IF NOT EXISTS ratings (
            chat_id INTEGER NOT NULL,
            user_id INTEGER NOT NULL,
            user_name TEXT,
            username TEXT,
            score INTEGER NOT NULL DEFAULT 0,
            PRIMARY KEY (chat_id, user_id)
        );

        CREATE TABLE IF NOT EXISTS words (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            word TEXT NOT NULL UNIQUE,
            added_at REAL DEFAULT 0
        );

        CREATE TABLE IF NOT EXISTS messages_log (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            chat_id INTEGER NOT NULL,
            message_id INTEGER NOT NULL,
            topic_id INTEGER,
            timestamp REAL NOT NULL,
            UNIQUE(chat_id, message_id)
        );
    """)
    conn.commit()
    conn.close()


# ── Настройки чата ───────────────────────────────────────────

def get_topic_id(chat_id: int) -> int | None:
    """Возвращает сохранённый topic_id для чата или None если не задан."""
    conn = get_connection()
    row = conn.execute(
        "SELECT topic_id FROM chat_settings WHERE chat_id = ?", (chat_id,)
    ).fetchone()
    conn.close()
    return row["topic_id"] if row else None


def set_topic_id(chat_id: int, topic_id: int | None):
    """Сохраняет topic_id для чата (None = работать во всех темах)."""
    conn = get_connection()
    conn.execute(
        """
        INSERT INTO chat_settings (chat_id, topic_id) VALUES (?, ?)
        ON CONFLICT(chat_id) DO UPDATE SET topic_id = excluded.topic_id
        """,
        (chat_id, topic_id),
    )
    conn.commit()
    conn.close()


# ── Состояние игры ───────────────────────────────────────────

def get_game(chat_id: int) -> sqlite3.Row | None:
    conn = get_connection()
    row = conn.execute(
        "SELECT * FROM game_state WHERE chat_id = ?", (chat_id,)
    ).fetchone()
    conn.close()
    return row


def upsert_game(chat_id: int, **kwargs):
    conn = get_connection()
    existing = conn.execute(
        "SELECT chat_id FROM game_state WHERE chat_id = ?", (chat_id,)
    ).fetchone()

    if existing:
        if kwargs:
            sets = ", ".join(f"{k} = ?" for k in kwargs)
            vals = list(kwargs.values()) + [chat_id]
            conn.execute(f"UPDATE game_state SET {sets} WHERE chat_id = ?", vals)
    else:
        kwargs["chat_id"] = chat_id
        cols = ", ".join(kwargs.keys())
        placeholders = ", ".join("?" for _ in kwargs)
        conn.execute(
            f"INSERT INTO game_state ({cols}) VALUES ({placeholders})",
            list(kwargs.values()),
        )

    conn.commit()
    conn.close()


# ── Рейтинг ──────────────────────────────────────────────────

def add_score(chat_id: int, user_id: int, user_name: str, username: str | None):
    """Добавляет +1 балл пользователю."""
    conn = get_connection()
    conn.execute(
        """
        INSERT INTO ratings (chat_id, user_id, user_name, username, score)
        VALUES (?, ?, ?, ?, 1)
        ON CONFLICT(chat_id, user_id) DO UPDATE SET
            score = score + 1,
            user_name = excluded.user_name,
            username = excluded.username
        """,
        (chat_id, user_id, user_name, username),
    )
    conn.commit()
    conn.close()


def add_score_direct(chat_id: int, user_id: int, user_name: str, username: str | None, points: int = 1):
    """Добавляет указанное количество баллов пользователю."""
    conn = get_connection()
    conn.execute(
        """
        INSERT INTO ratings (chat_id, user_id, user_name, username, score)
        VALUES (?, ?, ?, ?, ?)
        ON CONFLICT(chat_id, user_id) DO UPDATE SET
            score = score + excluded.score,
            user_name = excluded.user_name,
            username = excluded.username
        """,
        (chat_id, user_id, user_name, username, points),
    )
    conn.commit()
    conn.close()


def get_top(chat_id: int, limit: int = 10) -> list[sqlite3.Row]:
    """Возвращает топ N участников по баллам."""
    conn = get_connection()
    rows = conn.execute(
        """
        SELECT user_name, username, user_id, score
        FROM ratings WHERE chat_id = ?
        ORDER BY score DESC LIMIT ?
        """,
        (chat_id, limit),
    ).fetchall()
    conn.close()
    return rows


def get_all_ratings(chat_id: int) -> list[sqlite3.Row]:
    """Возвращает полный рейтинг всех участников."""
    conn = get_connection()
    rows = conn.execute(
        """
        SELECT user_name, username, user_id, score
        FROM ratings WHERE chat_id = ?
        ORDER BY score DESC
        """,
        (chat_id,),
    ).fetchall()
    conn.close()
    return rows


def get_user_rating(chat_id: int, user_id: int) -> int:
    """Возвращает количество баллов пользователя."""
    conn = get_connection()
    row = conn.execute(
        "SELECT score FROM ratings WHERE chat_id = ? AND user_id = ?",
        (chat_id, user_id),
    ).fetchone()
    conn.close()
    return row["score"] if row else 0


# ── Управление словами ───────────────────────────────────────

def add_word(word: str) -> bool:
    """Добавляет новое слово в БД."""
    conn = get_connection()
    try:
        conn.execute(
            "INSERT INTO words (word, added_at) VALUES (?, ?)",
            (word.lower().strip(), time.time())
        )
        conn.commit()
        conn.close()
        return True
    except sqlite3.IntegrityError:
        # Слово уже существует
        conn.close()
        return False


def delete_word(word: str) -> bool:
    """Удаляет слово из БД. Возвращает True если слово было удалено."""
    conn = get_connection()
    cursor = conn.execute(
        "DELETE FROM words WHERE word = ?",
        (word.lower().strip(),)
    )
    affected = cursor.rowcount
    conn.commit()
    conn.close()
    return affected > 0


def get_all_words() -> list[str]:
    """Возвращает список всех слов из БД."""
    conn = get_connection()
    rows = conn.execute("SELECT word FROM words ORDER BY added_at DESC").fetchall()
    conn.close()
    return [row["word"] for row in rows]


def get_words_count() -> int:
    """Возвращает количество слов в БД."""
    conn = get_connection()
    row = conn.execute("SELECT COUNT(*) as cnt FROM words").fetchone()
    conn.close()
    return row["cnt"] if row else 0


# ── Логирование сообщений для чистки ────────────────────────

def log_message(chat_id: int, message_id: int, topic_id: int | None = None):
    """Логирует отправленное сообщение для последующей чистки."""
    conn = get_connection()
    try:
        conn.execute(
            """
            INSERT INTO messages_log (chat_id, message_id, topic_id, timestamp)
            VALUES (?, ?, ?, ?)
            """,
            (chat_id, message_id, topic_id, time.time())
        )
        conn.commit()
    except sqlite3.IntegrityError:
        pass  # Сообщение уже залогировано
    finally:
        conn.close()


def get_messages_in_topic(chat_id: int, topic_id: int, since_timestamp: float) -> list[int]:
    """Возвращает ID всех сообщений в теме за последний период (по timestamp)."""
    conn = get_connection()
    rows = conn.execute(
        """
        SELECT message_id FROM messages_log
        WHERE chat_id = ? AND topic_id = ? AND timestamp >= ?
        ORDER BY timestamp DESC
        """,
        (chat_id, topic_id, since_timestamp)
    ).fetchall()
    conn.close()
    return [row["message_id"] for row in rows]


def delete_messages_by_range(chat_id: int, topic_id: int, since_timestamp: float) -> int:
    """Удаляет записи о сообщениях в БД логирования. Возвращает количество удалённых записей."""
    conn = get_connection()
    cursor = conn.execute(
        """
        DELETE FROM messages_log
        WHERE chat_id = ? AND topic_id = ? AND timestamp >= ?
        """,
        (chat_id, topic_id, since_timestamp)
    )
    affected = cursor.rowcount
    conn.commit()
    conn.close()
    return affected

def get_user_by_username(chat_id: int, username: str):
    """Ищет пользователя по username в базе"""
    conn = get_connection()
    row = conn.execute(
        "SELECT user_id, user_name FROM ratings WHERE chat_id = ? AND LOWER(username) = ?",
        (chat_id, username.lower().replace("@", ""))
    ).fetchone()
    conn.close()
    return row
