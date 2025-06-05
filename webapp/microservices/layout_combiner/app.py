import os
import json
import tempfile

from fastapi import FastAPI, UploadFile, File, HTTPException
from fastapi.responses import JSONResponse

from combiner import combine_structure

app = FastAPI(title="Layout Combiner Service")

@app.post("/combine", summary="Объединить layout и pdfminer JSON")
async def combine_endpoint(
    file: UploadFile = File(..., description="Исходный PDF"),
    struct_file: UploadFile = File(..., description="JSON от layout_analyzer"),
    pdfminer_file: UploadFile = File(..., description="JSON от pdf_parser")
):
    # 1) Проверяем, что первым пришёл PDF
    if file.content_type != "application/pdf":
        raise HTTPException(status_code=400, detail="Требуется PDF-файл")

    # 2) Загружаем JSON с layout-анализом
    raw_struct = await struct_file.read()
    try:
        struct_dict = json.loads(raw_struct)
    except json.JSONDecodeError as e:
        raise HTTPException(status_code=400, detail=f"Невалидный JSON struct_file: {e}")

    pages = struct_dict.get("pages")
    if not isinstance(pages, list):
        raise HTTPException(
            status_code=400,
            detail="JSON от layout_analyzer должен быть словарём с ключом 'pages' (список страниц)"
        )

    # 3) Загружаем JSON от PDFParser
    raw_pdfm = await pdfminer_file.read()
    try:
        pdfm_dict = json.loads(raw_pdfm)
    except json.JSONDecodeError as e:
        raise HTTPException(status_code=400, detail=f"Невалидный JSON pdfminer_file: {e}")

    # 4) Сохраняем PDF во временный файл
    pdf_bytes = await file.read()
    with tempfile.NamedTemporaryFile(delete=False, suffix=".pdf") as tmp:
        tmp.write(pdf_bytes)
        pdf_path = tmp.name

    try:
        # 5) Вызываем объединитель, передаём список страниц и полный pdfminer-словарь
        combined = combine_structure(pages, pdfm_dict, pdf_path)
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Ошибка в combine_structure: {e}")
    finally:
        os.remove(pdf_path)

    # 6) Возвращаем готовый объединённый JSON
    return JSONResponse(content=combined)

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8011, reload=True)