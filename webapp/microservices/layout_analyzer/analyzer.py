import json
import numpy as np
import pypdfium2 as pdfium
from doclayout_yolo import YOLOv10
from ultralytics import YOLO
from huggingface_hub import hf_hub_download

# --- 1. Загрузка моделей один раз при старте --------------------------------

weights1 = hf_hub_download(
    repo_id="juliozhao/DocLayout-YOLO-DocStructBench",
    filename="doclayout_yolo_docstructbench_imgsz1024.pt"
)
model1 = YOLOv10(weights1)

# путь к вашей дообученной модели
model2 = YOLO('weights/best.pt')


# --- 2. Утилиты --------------------------------------------------------------

def iou(boxA, boxB):
    xA, yA = max(boxA[0], boxB[0]), max(boxA[1], boxB[1])
    xB, yB = min(boxA[2], boxB[2]), min(boxA[3], boxB[3])
    interW, interH = max(0, xB - xA), max(0, yB - yA)
    inter = interW * interH
    areaA = (boxA[2] - boxA[0]) * (boxA[3] - boxA[1])
    areaB = (boxB[2] - boxB[0]) * (boxB[3] - boxB[1])
    return inter / (areaA + areaB - inter + 1e-6)

def nms(items, iou_thr=0.9):
    items = sorted(items, key=lambda x: x['conf'], reverse=True)
    keep = []
    for it in items:
        if all(iou(it['bbox'], k['bbox']) < iou_thr for k in keep):
            keep.append(it)
    return keep

def classify_tables(items, page_w, page_h):
    tables = [it for it in items if it['subtype']=='table']
    if not tables: return
    cands = []
    for t in tables:
        cx = (t['bbox'][0] + t['bbox'][2]) / 2
        cy = (t['bbox'][1] + t['bbox'][3]) / 2
        if cx > page_w * 0.5 and cy > page_h * 0.5:
            cands.append(t)
    stamp = max(cands, key=lambda x: x['conf']) if cands else tables[0]
    for t in tables:
        t['subtype'] = 'stamp' if t is stamp else 'specification'

def drop_noisy_tables(items, max_overlaps=2):
    tables = [it for it in items if it['class']=='table']
    others = [it for it in items if it['class']!='table']
    kept = []
    for tbl in tables:
        cnt = sum(
            1 for o in others
            if iou(tbl['bbox'], o['bbox']) > 0
               or (o['bbox'][0] >= tbl['bbox'][0]
                   and o['bbox'][1] >= tbl['bbox'][1]
                   and o['bbox'][2] <= tbl['bbox'][2]
                   and o['bbox'][3] <= tbl['bbox'][3])
        )
        if cnt <= max_overlaps:
            kept.append(tbl)
    return kept + others

def drop_nested_tables(items):
    tables = [it for it in items if it['class']=='table']
    others = [it for it in items if it['class']!='table']
    kept = []
    for tbl in tables:
        x1,y1,x2,y2 = tbl['bbox']
        nested = False
        for o in others:
            ox1,oy1,ox2,oy2 = o['bbox']
            if ox1 <= x1 and oy1 <= y1 and ox2 >= x2 and oy2 >= y2:
                nested = True
                break
        if not nested:
            kept.append(tbl)
    return kept + others

def merge_plain_text(items, gap_thr=7):
    texts = [it for it in items if it['class']=='text']
    others = [it for it in items if it['class']!='text']
    n = len(texts)
    adj = [[] for _ in range(n)]

    for i in range(n):
        bi = texts[i]['bbox']
        for j in range(i+1, n):
            bj = texts[j]['bbox']
            # проверяем пересечения/соседство
            inter = iou(bi, bj) > 0
            inside = (
                (bj[0]>=bi[0] and bj[1]>=bi[1] and bj[2]<=bi[2] and bj[3]<=bi[3]) or
                (bi[0]>=bj[0] and bi[1]>=bj[1] and bi[2]<=bj[2] and bi[3]<=bj[3])
            )
            gap_x = max(0, max(bj[0] - bi[2], bi[0] - bj[2]))
            vert_ov = min(bi[3], bj[3]) - max(bi[1], bj[1])
            neigh_h = (gap_x <= gap_thr) and (vert_ov > 0)
            gap_y = max(0, max(bj[1] - bi[3], bi[1] - bj[3]))
            hor_ov = min(bi[2], bj[2]) - max(bi[0], bj[0])
            neigh_v = (gap_y <= gap_thr) and (hor_ov > 0)

            if inter or inside or neigh_h or neigh_v:
                adj[i].append(j)
                adj[j].append(i)

    seen = [False]*n
    merged_texts = []
    for i in range(n):
        if seen[i]: continue
        stack, group = [i], []
        while stack:
            u = stack.pop()
            if seen[u]: continue
            seen[u] = True
            group.append(u)
            for v in adj[u]:
                if not seen[v]:
                    stack.append(v)
        xs = [texts[k]['bbox'][0] for k in group] + [texts[k]['bbox'][2] for k in group]
        ys = [texts[k]['bbox'][1] for k in group] + [texts[k]['bbox'][3] for k in group]
        bbox = [min(xs), min(ys), max(xs), max(ys)]
        conf = sum(texts[k]['conf'] for k in group) / len(group)
        merged_texts.append({
            'bbox': bbox,
            'conf': conf,
            'class': 'text',
            'subtype': 'plain_text'
        })
    return merged_texts + others

def drop_drawings_with_text(items, min_texts=2):
    drawings = [it for it in items if it['class']=='drawing']
    others   = [it for it in items if it['class']!='drawing']
    texts    = [it for it in items if it['class']=='text' and it['subtype']=='plain_text']
    kept = []
    for dr in drawings:
        cnt = sum(
            1 for t in texts
            if iou(dr['bbox'], t['bbox']) > 0
               or (t['bbox'][0]>=dr['bbox'][0]
                   and t['bbox'][1]>=dr['bbox'][1]
                   and t['bbox'][2]<=dr['bbox'][2]
                   and t['bbox'][3]<=dr['bbox'][3])
        )
        if cnt < min_texts:
            kept.append(dr)
    return kept + others


# --- 3. Главная функция анализа -------------------------------------------

def analyze_pdf(pdf_path: str) -> dict:
    pdf = pdfium.PdfDocument(pdf_path)
    pages = []
    for idx in range(len(pdf)):
        page = pdf.get_page(idx)
        bmp = page.render(scale=400/72)
        img = bmp.to_pil()
        page_w, page_h = img.size
        page.close()

        # две детекции
        res1 = model1.predict(img, imgsz=1024, conf=0.05, iou=0.35, device="cuda:0")[0]
        res2 = model2.predict(img, conf=0.07, iou=0.1)[0]

        items = []
        # из первой модели
        for box, conf, cid in zip(res1.boxes.xyxy.tolist(),
                                   res1.boxes.conf.tolist(),
                                   res1.boxes.cls.tolist()):
            name = res1.names[int(cid)]
            if name == 'figure': continue
            if name == 'table':
                items.append({'bbox': box, 'conf': conf, 'class': 'table', 'subtype': 'table'})
            else:
                items.append({'bbox': box, 'conf': conf, 'class': 'text', 'subtype': name.replace(' ', '_')})
        # из второй модели
        for box, conf, cid in zip(res2.boxes.xyxy.tolist(),
                                   res2.boxes.conf.tolist(),
                                   res2.boxes.cls.tolist()):
            name = res2.names[int(cid)]
            if name in ('specification','stamp','text'): continue
            items.append({'bbox': box, 'conf': conf, 'class': 'drawing', 'subtype': name})

        # пост-обработка
        classify_tables(items, page_w, page_h)
        items = nms(items)
        items = drop_noisy_tables(items)
        items = drop_nested_tables(items)
        items = merge_plain_text(items)
        items = drop_drawings_with_text(items)

        # собираем выход
        objs = [{
            'bbox': [round(x,2) for x in it['bbox']],
            'class': it['class'],
            'subtype': it['subtype']
        } for it in items]

        pages.append({
            'page': idx+1,
            'width': page_w,
            'height': page_h,
            'objects': objs
        })
    pdf.close()
    return {'pages': pages}