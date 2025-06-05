import json
import tempfile

from fastapi import FastAPI, UploadFile, File, HTTPException
from fastapi.responses import JSONResponse

from detector import detect_errors

app = FastAPI(
    title="Error Detector Service",
    description="Принимает объединённый JSON и возвращает его же с полем errors",
    version="1.0.0",
)

@app.post("/detect", summary="Найти ошибки в тексте по LanguageTool API")
async def detect_endpoint(
    combined_file: UploadFile = File(..., description="JSON, полученный после combine")
):
    # Проверяем content-type
    if combined_file.content_type not in ("application/json", "text/json"):
        raise HTTPException(status_code=400, detail="Требуется JSON-файл")

    # Читаем и парсим JSON
    payload = await combined_file.read()
    try:
        data = json.loads(payload)
    except Exception as e:
        raise HTTPException(status_code=400, detail=f"Неверный JSON: {e}")

    # Запускаем детектор ошибок
    try:
        result = detect_errors(data)
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Ошибка при detect_errors: {e}")

    return JSONResponse(content=result)

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8012, reload=True)