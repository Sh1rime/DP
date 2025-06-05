import faiss
import json
import numpy as np
from sentence_transformers import SentenceTransformer

# 1. Загружаем индекс и метаданные
index = faiss.read_index("/home/shirime/project/intel_analysis_const_doc/webapp/norms_index.faiss")
with open("/home/shirime/project/intel_analysis_const_doc/webapp/norms_metadata.json", "r", encoding="utf-8") as f:
    metadata = json.load(f)

# 2. Загружаем ту же модель эмбеддингов
model = SentenceTransformer("all-MiniLM-L6-v2")

# 3. Пусть у нас есть фрагмент текста, который мы хотим проверить
fragment = "В данном проекте не указан обязательный допуск на изменение геометрии при расчёте нагрузок"
# 4. Считаем эмбеддинг и нормализуем
emb = model.encode(fragment, convert_to_numpy=True, normalize_embeddings=True).astype("float32")
# 5. Ищем топ-3 наиболее похожих чанка из корпуса нормативов
D, I = index.search(np.array([emb]), k=3)  # I — индексы чанков, D — косинусные сходства
for rank, idx in enumerate(I[0]):
    sim = float(D[0][rank])
    meta = metadata[idx]
    print(f"#{rank+1} (sim={sim:.3f}) из файла {meta['filename']} (слово на позиции {meta['start_idx']}):\n")
    print(meta['text'][:300] + "…")   # первые 300 символов текста чанка
    print("---\n")