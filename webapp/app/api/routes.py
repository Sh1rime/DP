import os
import uuid
import json
from pathlib import Path

import httpx
import pypdfium2 as pdfium
from fastapi import APIRouter, UploadFile, File, HTTPException, Response

router = APIRouter()

# локальные адреса микросервисов
SERVICES = {
    "pdf":     "http://127.0.0.1:8001",
    "layout":  "http://127.0.0.1:8010",
    "combine": "http://127.0.0.1:8011",
    "errors":  "http://127.0.0.1:8012",
}

BASE_DIR     = Path(__file__).resolve().parent.parent
UPLOAD_BASE  = BASE_DIR / "static" / "uploads"   # …/static/uploads
TIMEOUT      = httpx.Timeout(120,  connect=60)
LONG_TIMEOUT = httpx.Timeout(600,  connect=60)   # 10 мин ожидания

@router.post("/upload", summary="Запустить полный pipeline")
async def upload_and_process(file: UploadFile = File(...)) -> Response:
    if file.content_type != "application/pdf":
        raise HTTPException(400, "Файл должен быть PDF")

    pdf_bytes = await file.read()

    # ── 0) создаём рабочую папку ────────────────────────────────────────────────
    job_id       = uuid.uuid4().hex
    job_dir      = UPLOAD_BASE / job_id
    previews_dir = job_dir / "previews"
    job_dir.mkdir(parents=True, exist_ok=True)
    previews_dir.mkdir(exist_ok=True)

    orig_pdf_path = job_dir / f"{job_id}.pdf"
    orig_pdf_path.write_bytes(pdf_bytes)

    # ── 1) PDF-parser → pdfminer_json ──────────────────────────────────────────
    async with httpx.AsyncClient(timeout=TIMEOUT) as client:
        resp = await client.post(
            f"{SERVICES['pdf']}/parse",
            files={"file": (file.filename, pdf_bytes, file.content_type)}
        )
    resp.raise_for_status()
    pdfminer_json = resp.json()

    # ── 2) layout_analyzer → layout_json ──────────────────────────────────────
    async with httpx.AsyncClient(timeout=TIMEOUT) as client:
        resp = await client.post(
            f"{SERVICES['layout']}/analyze",
            files={"file": (file.filename, pdf_bytes, file.content_type)}
        )
    resp.raise_for_status()
    layout_json = resp.json()

    # ── 3) combiner → combined_json ───────────────────────────────────────────
    async with httpx.AsyncClient(timeout=LONG_TIMEOUT) as client:
        resp = await client.post(
            f"{SERVICES['combine']}/combine",
            files={
                "file":           (file.filename, pdf_bytes, file.content_type),
                "struct_file":    ("layout.json",   json.dumps(layout_json,   ensure_ascii=False), "application/json"),
                "pdfminer_file":  ("miner.json",    json.dumps(pdfminer_json, ensure_ascii=False), "application/json"),
            }
        )
    resp.raise_for_status()
    combined_json = resp.json()

    # ── 4) error_detector → final_json ────────────────────────────────────────
    async with httpx.AsyncClient(timeout=LONG_TIMEOUT) as client:
        resp = await client.post(
            f"{SERVICES['errors']}/detect",
            files={"combined_file": ("combined.json",
                                     json.dumps(combined_json, ensure_ascii=False),
                                     "application/json")}
        )
    resp.raise_for_status()
    final_json = resp.json()

    # ── 5) сохраняем итоговый JSON ────────────────────────────────────────────
    err_json_path = job_dir / f"{job_id}_errors.json"
    err_json_path.write_text(json.dumps(final_json, ensure_ascii=False, indent=2),
                             encoding="utf-8")

    # ── 6) делаем PNG-превью (400 dpi) ────────────────────────────────────────
    pdf = pdfium.PdfDocument(str(orig_pdf_path))
    scale = 400 / 72
    for i in range(len(pdf)):
        page = pdf.get_page(i)
        bmp  = page.render(scale=scale)
        bmp.to_pil().save(previews_dir / f"page_{i+1}.png")
        page.close()
    pdf.close()

    # вернём только job_id
    return Response(content=job_id, media_type="text/plain")
