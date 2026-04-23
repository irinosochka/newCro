seen_words = set()

with open("words.txt", "r", encoding="utf-8") as f_in, open("words_clean.txt", "w", encoding="utf-8") as f_out:
    for line in f_in:
        stripped = line.strip()
        
        # Оставляем пустые строки и заголовки категорий
        if not stripped or stripped.startswith("#"):
            f_out.write(line)
            continue
            
        # Проверяем слово на уникальность (приводим к нижнему регистру)
        word_lower = stripped.lower()
        if word_lower not in seen_words:
            seen_words.add(word_lower)
            f_out.write(line)

print("Готово! Очищенный список сохранен в words_clean.txt")