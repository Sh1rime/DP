# backend/tasks.py
from celery import Celery
import fitz  # PyMuPDF
import pdfplumber
import camelot
import pytesseract
from PIL import Image
import io
import os

# Инициализация Celery приложения
celery = Celery("pdf_analyzer",
                broker=os.getenv("CELERY_BROKER_URL", "redis://redis:6379/0"),
                backend=os.getenv("CELERY_RESULT_BACKEND", "redis://redis:6379/0"))
# Настройки Celery (опционально можно настроить очереди, таймауты и др.)
celery.conf.update(task_track_started=True)  # Позволяет отслеживать статус STARTED

@celery.task(name="backend.tasks.process_pdf")
def process_pdf(file_path: str):
    """
    Задача Celery: Анализирует PDF по заданному пути и возвращает результат в виде словаря JSON-совместимой структуры.
    """
    result = {"pages": []}
    if not os.path.exists(file_path):
        # Если файл не найден, сразу возвращаем ошибочный результат
        return {"error": "File not found"}

    # Открываем PDF через PyMuPDF
    doc = fitz.open(file_path)
    num_pages = len(doc)

    # Также откроем PDF через pdfplumber для получения деталей (например, шрифты, символы)
    pdf = pdfplumber.open(file_path)

    for page_index in range(num_pages):
        page_number = page_index + 1
        page = doc[page_index]
        page_plumber = pdf.pages[page_index]

        # Структура для текущей страницы
        page_data = {
            "page_number": page_number,
            "text": [],       # список текстовых элементов со свойствами
            "tables": [],     # распознанные таблицы
            "images": []      # информация об изображениях
        }

        # 1. Извлечение текстовых блоков, координат и шрифтов
        page_dict = page.get_text("dict")  # Получаем структуру с блоками текста и изображений
        for block in page_dict.get("blocks", []):
            if block.get("type") == 0:  # текстовый блок
                for line in block.get("lines", []):
                    for span in line.get("spans", []):
                        text = span.get("text", "")
                        if text.strip():
                            page_data["text"].append({
                                "text": text.strip(),
                                "x0": span.get("bbox", [None]*4)[0],  # левая координата
                                "y0": span.get("bbox", [None]*4)[1],  # верхняя координата
                                "x1": span.get("bbox", [None]*4)[2],  # правая координата
                                "y1": span.get("bbox", [None]*4)[3],  # нижняя координата
                                "font": span.get("font", ""),
                                "size": span.get("size", None)
                            })
            elif block.get("type") == 1:  # блок изображения
                # Сохраняем метаданные изображения (координаты, размеры)
                img_bbox = block.get("bbox", [None]*4)
                page_data["images"].append({
                    "x0": img_bbox[0],
                    "y0": img_bbox[1],
                    "x1": img_bbox[2],
                    "y1": img_bbox[3],
                    "width": block.get("width", None),
                    "height": block.get("height", None)
                })

        # 2. OCR: Если на странице мало или нет текста, распознаем изображение страницы 
        #    (например, для сканированных страниц без текстового слоя)
        if not page_data["text"]:
            try:
                # Рендерим всю страницу в изображение (растровое) для OCR
                pix = page.get_pixmap()
                img_bytes = pix.png_data  # PNG-данные изображения страницы
                img = Image.open(io.BytesIO(img_bytes))
                ocr_text = pytesseract.image_to_string(img, lang="eng")  # распознавание (по умолчанию англ. язык)
                if ocr_text.strip():
                    page_data["text"].append({
                        "text": ocr_text.strip(),
                        "ocr": True  # помечаем, что текст получен через OCR всей страницы
                    })
            except Exception as e:
                # Логируем или обрабатываем ошибки OCR (например, если Tesseract не настроен для нужного языка)
                page_data["text"].append({
                    "text": "",
                    "ocr": True,
                    "error": str(e)
                })

        # 3. Извлечение таблиц с помощью Camelot
        try:
            tables = camelot.read_pdf(file_path, pages=str(page_number), flavor="stream")
            # Camelot возвращает список таблиц (если есть)
            for table in tables:
                table_data = {
                    "shape": (table.df.shape[0], table.df.shape[1]),  # размерность таблицы (строки x столбцы)
                    "data": table.df.fillna("").values.tolist()       # содержимое таблицы как список списков (без NaN)
                }
                page_data["tables"].append(table_data)
        except Exception as e:
            # Если произошла ошибка при обработке таблиц (например, Ghostscript не установлен и т.д.)
            page_data["tables_error"] = str(e)

        # 4. OCR на вложенных изображениях (опционально): 
        # Можно пройтись по сохраненным изображениям страницы и попытаться извлечь текст из них.
        # Здесь для простоты выполняем OCR для каждого изображения блока, если таковые есть.
        for img_meta in page_data["images"]:
            try:
                # Получаем изображение по его XREF через PyMuPDF
                xref = None
                # Найдем изображение с такими же координатами в самом PDF (PyMuPDF)
                # (Примечание: PyMuPDF позволяет получать изображение по XREF; 
                # более точную привязку можно реализовать при необходимости)
                for img in page.get_images(full=True):
                    # img: (xref, smask, width, height, bpc, colorspace, alt, name)
                    if img[2] == img_meta["width"] and img[3] == img_meta["height"]:
                        xref = img[0]
                        break
                if xref:
                    pix = page.get_pixmap(xref)
                    img = Image.open(io.BytesIO(pix.png_data))
                    ocr_img_text = pytesseract.image_to_string(img, lang="eng")
                    if ocr_img_text.strip():
                        page_data["text"].append({
                            "text": ocr_img_text.strip(),
                            "ocr": True,
                            "image_ocr": True,
                            "img_bbox": [img_meta["x0"], img_meta["y0"], img_meta["x1"], img_meta["y1"]]
                        })
            except Exception as e:
                # Игнорируем ошибки OCR на отдельных изображениях
                pass

        result["pages"].append(page_data)

    # Закрываем PDF-документы
    pdf.close()
    doc.close()
    return result
