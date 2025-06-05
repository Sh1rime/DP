from pathlib import Path
import json
from fastapi import FastAPI, Request, HTTPException
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates

from app.api.routes import router as api_router

BASE_DIR = Path(__file__).resolve().parent

app = FastAPI(
    title="API Gateway — Интеллектуальный анализ строительных проектов",
    description="Фронтенд + маршруты к микросервисам",
)

# статика
app.mount("/static", StaticFiles(directory=BASE_DIR / "static"), name="static")
templates = Jinja2Templates(directory=BASE_DIR / "templates")

# REST-роуты
app.include_router(api_router, prefix="/api", tags=["microservices"])

@app.get("/", include_in_schema=False)
async def index(request: Request):
    return templates.TemplateResponse("index.html", {"request": request})

@app.get("/errors/{job_id}", include_in_schema=False)
async def show_errors(request: Request, job_id: str):
    job_dir = BASE_DIR / "static" / "uploads" / job_id
    json_path = job_dir / f"{job_id}_errors.json"
    if not json_path.exists():
        raise HTTPException(404, "Результат не найден")

    with open(json_path, encoding="utf-8") as f:
        errors_data = json.load(f)

    return templates.TemplateResponse(
        "errors.html",
        {
            "request":     request,
            "errors":      errors_data,                
            "preview_uri": f"/static/uploads/{job_id}/previews"
        }
    )