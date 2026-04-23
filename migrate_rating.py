#!/usr/bin/env python3
"""
Скрипт для миграции рейтинга из старой БД в новую.

Используй если у тебя уже есть данные рейтинга в crocodile.db от другого бота.

Важно: новая БД должна быть инициализирована (запусти bot.py хотя бы раз)
"""

import sqlite3
import sys
from pathlib import Path

def migrate_ratings(old_db_path: str, new_db_path: str, chat_id: int):
    """Копирует рейтинг из старой БД в новую."""
    
    if not Path(old_db_path).exists():
        print(f"❌ Старая БД {old_db_path} не найдена!")
        return False
    
    if not Path(new_db_path).exists():
        print(f"❌ Новая БД {new_db_path} не найдена! Запусти сначала bot.py")
        return False
    
    try:
        # Подключимся к обеим БД
        old_conn = sqlite3.connect(old_db_path)
        old_conn.row_factory = sqlite3.Row
        new_conn = sqlite3.connect(new_db_path)
        
        # Получаем все рейтинги из старой БД
        old_ratings = old_conn.execute(
            "SELECT user_id, user_name, username, score FROM ratings"
        ).fetchall()
        
        if not old_ratings:
            print("⚠ В старой БД нет данных рейтинга!")
            return False
        
        # Вставляем в новую БД
        inserted = 0
        for rating in old_ratings:
            try:
                new_conn.execute(
                    """
                    INSERT OR IGNORE INTO ratings 
                    (chat_id, user_id, user_name, username, score) 
                    VALUES (?, ?, ?, ?, ?)
                    """,
                    (
                        chat_id,
                        rating["user_id"],
                        rating["user_name"],
                        rating["username"],
                        rating["score"]
                    )
                )
                print(f"✓ Мигрирован: {rating['user_name']} — {rating['score']} баллов")
                inserted += 1
            except Exception as e:
                print(f"⚠ Ошибка при миграции {rating['user_name']}: {e}")
        
        new_conn.commit()
        
        print(f"\n✅ Миграция завершена!")
        print(f"   Мигрировано рейтингов: {inserted}")
        print(f"   Чат ID: {chat_id}")
        
        old_conn.close()
        new_conn.close()
        return True
    
    except Exception as e:
        print(f"❌ Ошибка: {e}")
        return False


if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("Использование: python migrate_ratings.py <CHAT_ID> [old_db.db] [new_db.db]")
        print("\nПримеры:")
        print("  python migrate_ratings.py -1001234567890")
        print("  python migrate_ratings.py -1001234567890 old_crocodile.db crocodile.db")
        sys.exit(1)
    
    chat_id = int(sys.argv[1])
    old_db = sys.argv[2] if len(sys.argv) > 2 else "old_crocodile.db"
    new_db = sys.argv[3] if len(sys.argv) > 3 else "crocodile.db"
    
    migrate_ratings(old_db, new_db, chat_id)