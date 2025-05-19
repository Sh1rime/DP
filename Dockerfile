# Dockerfile
FROM python:3.10-slim

# Установим системные пакеты: tesseract (для OCR) и ghostscript (для PDF разметки Camelot)
RUN apt-get update && apt-get install -y --no-install-recommends \
    tesseract-ocr \ 
    ghostscript && \
    rm -rf /var/lib/apt/lists/*

# Устанавливаем рабочую директорию
WORKDIR /app

# Копируем файлы зависимостей и устанавливаем их
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Копируем весь исходный код проекта в контейнер
COPY . .

# Открываем порт для веб-сервиса
EXPOSE 8000

# Определяем команду запуска по умолчанию (запуск сервера FastAPI через Uvicorn)
CMD ["uvicorn", "backend.main:app", "--host", "0.0.0.0", "--port", "8000"]
