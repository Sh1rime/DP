import json
import cv2
import numpy as np
import pypdfium2 as pdfium
import pytesseract

try:
    import easyocr
    easy_reader = easyocr.Reader(['ru'], gpu=False)
except ImportError:
    easy_reader = None

from sklearn.cluster import DBSCAN

# параметры рендеринга
RENDER_DPI = 400
SCALE = RENDER_DPI / 72.0

def adjust_bbox_pdfminer(bbox_pts, page_height_pts):
    x0, y0, x1, y1 = bbox_pts
    # PDFMiner даёт координаты от нижнего левого угла, конвертируем в пиксели и систему сверху
    y0_ref = page_height_pts - y1
    y1_ref = page_height_pts - y0
    return [int(x0 * SCALE), int(y0_ref * SCALE),
            int(x1 * SCALE), int(y1_ref * SCALE)]

def ocr_preprocess(img):
    gray = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)
    blur = cv2.GaussianBlur(gray, (5,5), 0)
    return cv2.adaptiveThreshold(blur, 255,
                                 cv2.ADAPTIVE_THRESH_GAUSSIAN_C,
                                 cv2.THRESH_BINARY, 11, 2)

def ocr_tesseract(img):
    pre = ocr_preprocess(img)
    data = pytesseract.image_to_data(
        pre, lang='rus',
        config='--oem 1 --psm 6',
        output_type=pytesseract.Output.DICT
    )
    words = [w for w in data.get('text', []) if isinstance(w, str) and w.strip()]
    confs = []
    for c in data.get('conf', []):
        try:
            cval = float(c)
            if cval >= 0:
                confs.append(cval)
        except:
            continue
    conf = (sum(confs) / len(confs)) if confs else None
    text = " ".join(words).strip()
    return text, conf

def ocr_combined(img):
    text, conf = ocr_tesseract(img)
    source = 'ocr_tesseract'
    if easy_reader and (not text or len(text) < 3):
        results = easy_reader.readtext(img)
        texts = [res[1] for res in results]
        text = " ".join(texts).strip()
        source = 'ocr_easy'
        conf = None
    return text, source, conf

def detect_table_cells(img):
    if img.size == 0:
        return []
    gray = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)
    _, bw = cv2.threshold(gray, 0, 255,
                          cv2.THRESH_BINARY_INV + cv2.THRESH_OTSU)
    hor = cv2.getStructuringElement(cv2.MORPH_RECT,
                                    (img.shape[1]//15, 1))
    ver = cv2.getStructuringElement(cv2.MORPH_RECT,
                                    (1, img.shape[0]//15))
    hmask = cv2.morphologyEx(bw, cv2.MORPH_OPEN, hor)
    vmask = cv2.morphologyEx(bw, cv2.MORPH_OPEN, ver)
    grid = cv2.bitwise_and(hmask, vmask)
    pts = cv2.findNonZero(grid)
    if pts is None:
        return []
    pts = pts.reshape(-1,2)
    clustering = DBSCAN(eps=10, min_samples=3).fit(pts)
    centers = [
        tuple(map(int, pts[clustering.labels_==lbl].mean(axis=0)))
        for lbl in set(clustering.labels_) if lbl != -1
    ]
    ys = sorted({y for _,y in centers})
    xs = sorted({x for x,_ in centers})
    cells = []
    for r in range(len(ys)-1):
        for c in range(len(xs)-1):
            cells.append({
                'bbox': [xs[c], ys[r], xs[c+1], ys[r+1]],
                'texts': [],
                'id': None
            })
    return cells

def combine_structure(struct_data: list, pdfminer_data: dict, pdf_path: str) -> list:
    """
    struct_data: output from layout_analyzer (list of pages with 'objects')
    pdfminer_data: output from pdf_parser {'pages': [...]}
    pdf_path: path to PDF file to render pages
    """
    # 1. Рендерим все страницы и запоминаем высоты
    pdf = pdfium.PdfDocument(pdf_path)
    page_images = []
    page_heights_pts = []
    for i in range(len(pdf)):
        pg = pdf.get_page(i)
        _, h_pts = pg.get_size()
        page_heights_pts.append(h_pts)
        bmp = pg.render(scale=RENDER_DPI/72.0)
        img = bmp.to_pil()
        page_images.append(cv2.cvtColor(np.array(img), cv2.COLOR_RGB2BGR))
        pg.close()
    pdf.close()

    combined = []
    id_counters = {'table': 0, 'cell': 0, 'text': 0}

    # 2. Проходим по каждому результату layout_analyzer
    for pg in struct_data:
        idx = pg['page'] - 1
        img = page_images[idx]
        h_pts = page_heights_pts[idx]
        # находим соответствующую страницу из pdfminer
        pm_page = next(
            (p for p in pdfminer_data.get('pages', [])
             if p.get('page_number') == pg['page']),
            {}
        )
        pm_objs = pm_page.get('objects', [])
        used = set()

        out = {
            'page': pg['page'],
            'dpi': RENDER_DPI,
            'scale': SCALE,
            'tables': [],
            'plain_text': [],
            'drawings': []
        }

        # 2.1 Таблицы и ячейки
        for tbl in [o for o in pg['objects'] if o['class'] == 'table']:
            id_counters['table'] += 1
            tbl_id = f"t{id_counters['table']}"
            x1, y1, x2, y2 = map(int, tbl['bbox'])
            x1c, y1c = max(0, x1), max(0, y1)
            x2c, y2c = min(img.shape[1], x2), min(img.shape[0], y2)
            cells = []
            if x2c > x1c and y2c > y1c:
                crop = img[y1c:y2c, x1c:x2c]
                raw_cells = detect_table_cells(crop)
                for cell in raw_cells:
                    id_counters['cell'] += 1
                    cell['id'] = f"c{id_counters['cell']}"
                    bx1, by1, bx2, by2 = cell['bbox']
                    cell_bbox = [bx1 + x1c, by1 + y1c,
                                 bx2 + x1c, by2 + y1c]
                    cell['bbox'] = cell_bbox
                    # прилипление текстов из pdfminer
                    for i_obj, obj in enumerate(pm_objs):
                        if obj.get('type') != 'text' or i_obj in used:
                            continue
                        pt = adjust_bbox_pdfminer(obj['bbox'], h_pts)
                        if (pt[0] >= cell_bbox[0] and pt[1] >= cell_bbox[1]
                            and pt[2] <= cell_bbox[2] and pt[3] <= cell_bbox[3]):
                            cell['texts'].append({
                                'text': obj['text'],
                                'source': 'pdfminer',
                                'confidence': None
                            })
                            used.add(i_obj)
                    # OCR, если не удалось найти текст
                    if not cell['texts']:
                        snippet = img[cell_bbox[1]:cell_bbox[3],
                                      cell_bbox[0]:cell_bbox[2]]
                        txt, src, conf = ocr_combined(snippet)
                        if txt:
                            cell['texts'].append({
                                'text': txt,
                                'source': src,
                                'confidence': conf
                            })
                    cells.append(cell)
            out['tables'].append({
                'id': tbl_id,
                'bbox': tbl['bbox'],
                'subtype': tbl['subtype'],
                'cells': cells
            })

        # 2.2 Слияние plain_text и OCR для текстовых блоков
        for txt in [o for o in pg['objects'] if o['class'] == 'text']:
            bb = list(map(int, txt['bbox']))
            bb = [ max(0, bb[0]), max(0, bb[1]),
                   min(img.shape[1], bb[2]), min(img.shape[0], bb[3]) ]
            if bb[2] <= bb[0] or bb[3] <= bb[1]:
                continue
            matched = False
            for i_obj, obj in enumerate(pm_objs):
                if obj.get('type') != 'text' or i_obj in used:
                    continue
                pt = adjust_bbox_pdfminer(obj['bbox'], h_pts)
                # проверяем пересечение
                if not (pt[2] < bb[0] or pt[0] > bb[2]
                        or pt[3] < bb[1] or pt[1] > bb[3]):
                    id_counters['text'] += 1
                    out['plain_text'].append({
                        'id': f"x{id_counters['text']}",
                        'bbox': bb,
                        'text': obj['text'],
                        'source': 'pdfminer',
                        'confidence': None
                    })
                    used.add(i_obj)
                    matched = True
                    break
            if not matched:
                snippet = img[bb[1]:bb[3], bb[0]:bb[2]]
                txt_str, src, conf = ocr_combined(snippet)
                id_counters['text'] += 1
                out['plain_text'].append({
                    'id': f"x{id_counters['text']}",
                    'bbox': bb,
                    'text': txt_str,
                    'source': src,
                    'confidence': conf
                })

        # 2.3 Оставшийся текст из pdfminer без соответствия
        for i_obj, obj in enumerate(pm_objs):
            if i_obj in used or obj.get('type') != 'text':
                continue
            bb = adjust_bbox_pdfminer(obj['bbox'], h_pts)
            id_counters['text'] += 1
            out['plain_text'].append({
                'id': f"x{id_counters['text']}",
                'bbox': bb,
                'text': obj['text'],
                'source': 'pdfminer',
                'confidence': None
            })

        # 2.4 Чертежи / рисунки
        for dr in [o for o in pg['objects'] if o['class'] == 'drawing']:
            out['drawings'].append({
                'bbox': dr['bbox'],
                'subtype': dr['subtype']
            })

        combined.append(out)

    return combined
