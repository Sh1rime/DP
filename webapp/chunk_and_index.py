import os
import json
import math
from pathlib import Path
from sentence_transformers import SentenceTransformer
import numpy as np
import faiss

# Путь к директории с нормами
NORMS_DIR = Path(__file__).resolve().parent / "norms_corpus"

# Параметры разбиения на чанки
WORDS_PER_CHUNK    = 300   # размер чанка в словах
OVERLAP_WORDS      = 50    # пересечение соседних чанков


def read_txt(file_path: Path) -> str:
    """Читает весь файл целиком как строку."""
    return file_path.read_text(encoding="utf-8")


def split_to_chunks(text: str, words_per_chunk: int, overlap: int) -> list:
    """
    Разбивает текст (строка) на чанки по N слов с перекрытием overlap.
    Возвращает список словарей: {'start_idx': int, 'text': str}.
    """
    # 1) Разбиваем по пробелам на слова
    all_words = text.split()
    total_words = len(all_words)
    chunks = []
    start = 0

    while start < total_words:
        end = start + words_per_chunk
        if end > total_words:
            end = total_words
        chunk_words = all_words[start:end]
        chunk_text = " ".join(chunk_words)
        chunks.append({
            "start_idx": start,
            "text": chunk_text
        })
        # сдвигаем старт на (WORDS_PER_CHUNK - OVERLAP_WORDS)
        if end == total_words:
            break
        start = start + (words_per_chunk - overlap)
    return chunks


def main():
    # 0) Проверки: есть ли вообще папка и файлы
    if not NORMS_DIR.exists() or not NORMS_DIR.is_dir():
        print(f"❌ Папка {NORMS_DIR} не найдена. Создайте и положите туда *.txt нормативы.")
        return

    txt_files = sorted(NORMS_DIR.glob("*.txt"))
    if not txt_files:
        print(f"❌ В {NORMS_DIR} нет txt-файлов.")
        return

    # 1) Загружаем модель эмбеддингов
    print("⏳ Загружаем модель sentence-transformers (all-MiniLM-L6-v2)…")
    model = SentenceTransformer("all-MiniLM-L6-v2")

    # Будем собирать все эмбеддинги в один массив (float32)
    embeddings_list = []
    metadata = []  # список метаданных для каждого чанка

    chunk_id = 0
    for txt_path in txt_files:
        print(f"─ Обрабатываем {txt_path.name}…")
        raw = read_txt(txt_path)

        # 2) Разбиваем на чанки
        chunks = split_to_chunks(raw, WORDS_PER_CHUNK, OVERLAP_WORDS)
        print(f"  • Найдено чанков: {len(chunks)}")

        # 3) Для каждого чанка считаем эмбеддинг
        for ch in chunks:
            text = ch["text"]
            emb = model.encode(text, convert_to_numpy=True, normalize_embeddings=True)
            embeddings_list.append(emb.astype("float32"))

            # 4) Записываем метаданные
            metadata.append({
                "id":        chunk_id,
                "filename":  txt_path.name,
                "start_idx": ch["start_idx"],
                "text":      text
            })
            chunk_id += 1

    if not embeddings_list:
        print("❌ Не удалось получить эмбеддинги.")
        return

    # 5) Собираем единый numpy-массив
    print(f"ℹ️ Всего чанков: {len(embeddings_list)}. Собираем в матрицу…")
    emb_matrix = np.vstack(embeddings_list)  # shape = (num_chunks, embedding_dim)

    # 6) Создаём FAISS-индекс (Flat L2 с нормализацией векторов → косинус)
    dim = emb_matrix.shape[1]
    index = faiss.IndexFlatIP(dim)  # Inner Product на нормализованных embeddings = косинусное сходство
    faiss.normalize_L2(emb_matrix)
    index.add(emb_matrix)

    # 7) Сохраняем индекс на диск и метаданные
    index_path = Path(__file__).resolve().parent / "norms_index.faiss"
    meta_path  = Path(__file__).resolve().parent / "norms_metadata.json"

    print(f"💾 Сохраняем FAISS-индекс в {index_path.name} …")
    faiss.write_index(index, str(index_path))

    print(f"💾 Сохраняем метаданные в {meta_path.name} …")
    with open(meta_path, "w", encoding="utf-8") as f:
        json.dump(metadata, f, ensure_ascii=False, indent=2)

    print("✅ Индексация нормативов завершена.")


if __name__ == "__main__":
    main()