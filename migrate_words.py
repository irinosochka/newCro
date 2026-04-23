#!/usr/bin/env python3
"""
Скрипт для миграции слов из words.txt в SQLite БД.
Используй если у тебя уже есть слова в файле.
"""

import sys
from db import init_db, add_word

def migrate_words_from_file(filepath: str = "words.txt"):
    """Загружает все слова из текстового файла в БД."""
    init_db()
    
    added = 0
    skipped = 0
    
    try:
        with open(filepath, "r", encoding="utf-8") as f:
            for line_num, line in enumerate(f, 1):
                word = line.strip()
                
                # Пропускаем пустые строки и комментарии
                if not word or word.startswith("#"):
                    continue
                
                if add_word(word):
                    added += 1
                    print(f"✓ Добавлено: {word}")
                else:
                    skipped += 1
                    print(f"⚠ Пропущено (дубликат): {word}")
    
    except FileNotFoundError:
        print(f"❌ Файл {filepath} не найден!")
        return False
    except Exception as e:
        print(f"❌ Ошибка: {e}")
        return False
    
    print(f"\n✅ Миграция завершена!")
    print(f"   Добавлено: {added}")
    print(f"   Пропущено дубликатов: {skipped}")
    return True


if __name__ == "__main__":
    filepath = sys.argv[1] if len(sys.argv) > 1 else "words.txt"
    migrate_words_from_file(filepath)