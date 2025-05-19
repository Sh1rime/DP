# backend/main.py
from fastapi import FastAPI, File, UploadFile, HTTPException
from fastapi.responses import JSONResponse, FileResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles
from uuid import uuid4
import os

# Импорт Celery-задачи
from backend import tasks  # импортируем модуль tasks.py
# (Celery-приложение и задача `process_pdf` будут зарегистрированы при импорте)

app = FastAPI(title="PDF Analyzer Service")

# Раздача статических файлов (frontend)
app.mount("/static", StaticFiles(directory="frontend/static"), name="static")

# Маршрут для главной страницы (index.html)
@app.get("/", response_class=FileResponse)
def read_root():
    index_path = "frontend/templates/index.html"
    if os.path.exists(index_path):
        return FileResponse(index_path, media_type="text/html")
    else:
        raise HTTPException(status_code=404, detail="Index page not found")

# Эндпойнт для загрузки PDF и постановки задачи
@app.post("/api/v1/pdf")
async def upload_pdf(file: UploadFile = File(...)):
    # Проверяем тип файла (должен быть PDF)
    filename = file.filename or "uploaded.pdf"
    if not filename.lower().endswith(".pdf"):
        raise HTTPException(status_code=400, detail="Only PDF files are supported")
    # Создаем директорию для загрузок, если не существует
    os.makedirs("data", exist_ok=True)
    # Генерируем уникальное имя для сохранения, чтобы избежать коллизий
    save_path = os.path.join("data", f"{uuid4().hex}.pdf")
    # Читаем файл и сохраняем на диск
    try:
        contents = await file.read()  # читаем загруженный файл в байты
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Error reading uploaded file: {e}")
    with open(save_path, "wb") as f:
        f.write(contents)
    # Отправляем задачу на обработку PDF в Celery
    try:
        task = tasks.process_pdf.delay(save_path)
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to send task to Celery: {e}")
    # Возвращаем клиенту ID задачи
    return {"task_id": task.id}

# Эндпойнт для проверки статуса задачи
@app.get("/api/v1/status/{task_id}")
def get_status(task_id: str):
    async_result = tasks.celery.AsyncResult(task_id)
    # async_result.status вернет строку статуса Celery: PENDING, STARTED, SUCCESS, FAILURE
    status = async_result.status
    return {"status": status}

# Эндпойнт для получения результата задачи
@app.get("/api/v1/result/{task_id}")
def get_result(task_id: str):
    async_result = tasks.celery.AsyncResult(task_id)
    if not async_result.ready():
        # Если результат еще не готов, возвращаем 404 или 202
        raise HTTPException(status_code=202, detail="Result not ready")
    if async_result.failed():
        # Если задача завершилась неуспешно
        raise HTTPException(status_code=500, detail="Task failed")
    result = async_result.result  # получаем результат (словарь)
    # Возвращаем JSON-файл в виде вложения (attachment) для загрузки
    return StreamingResponse(
        content=io.BytesIO(tasks.json.dumps(result, ensure_ascii=False).encode('utf-8')),
        media_type="application/json",
        headers={"Content-Disposition": f"attachment; filename=result_{task_id}.json"}
    )
