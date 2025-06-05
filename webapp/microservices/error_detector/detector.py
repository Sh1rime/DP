import json
import requests
from concurrent.futures import ThreadPoolExecutor

LT_URL = "https://api.languagetool.org/v2/check"

def group_paragraphs(blocks, gap=20):
    """
    Группирует блоки текста в параграфы по вертикальному отступу.
    """
    if not blocks:
        return []
    # Сортируем по y0, затем x0
    blocks = sorted(blocks, key=lambda b: (b['bbox'][1], b['bbox'][0]))
    paras, cur = [], [blocks[0]]
    for prev, blk in zip(blocks, blocks[1:]):
        if blk['bbox'][1] - prev['bbox'][3] <= gap:
            cur.append(blk)
        else:
            paras.append(cur)
            cur = [blk]
    paras.append(cur)
    return paras

def check_text_lt(text):
    """
    Отправляет текст в LanguageTool и возвращает список совпадений.
    """
    resp = requests.post(
        LT_URL,
        data={
            'text': text,
            'language': 'ru',
            'enabledOnly': False
        },
        timeout=10
    )
    resp.raise_for_status()
    return resp.json()['matches']

def process_paragraph(paragraph):
    """
    Обрабатывает один параграф (список блоков), возвращает список ошибок.
    """
    full = " ".join(b['text'] for b in paragraph)
    matches = check_text_lt(full)
    errors = []
    for m in matches:
        off, length = m['offset'], m['length']
        cum = 0
        # находим, в каком именно блоке параграфа произошла ошибка
        for blk in paragraph:
            blk_len = len(blk['text']) + 1
            if cum <= off < cum + blk_len:
                local = off - cum
                # берём не более трёх вариантов замены
                repl = [r['value'] for r in m['replacements']][:3]
                errors.append({
                    'id':             blk['id'],
                    'bbox':           blk['bbox'],
                    'error_text':     blk['text'][local:local+length],
                    'offset':         local,
                    'length':         length,
                    'message':        m['message'],
                    'shortMessage':   m.get('shortMessage'),
                    'replacements':   repl,
                    'ruleId':         m['rule']['id'],
                    'issueType':      m['rule']['issueType'],
                    'category':       m['rule']['category']['id'],
                    'context':        m['context']['text']
                })
                break
            cum += blk_len
    return errors

def detect_errors(data: list) -> list:
    """
    Проходит по каждой странице в data, ищет ошибки в plain_text и в ячейках таблиц,
    добавляет поле 'errors' со списком ошибок и возвращает модифицированный data.
    """
    for page in data:
        # 1) параграфы из plain_text
        paras = group_paragraphs(page.get('plain_text', []))
        page_errors = []
        with ThreadPoolExecutor(max_workers=4) as ex:
            for errs in ex.map(process_paragraph, paras):
                page_errors.extend(errs)

        # 2) ячейки таблиц
        for tbl in page.get('tables', []):
            for cell in tbl.get('cells', []):
                txt = " ".join(t['text'] for t in cell.get('texts', []))
                if not txt:
                    continue
                matches = check_text_lt(txt)
                for m in matches:
                    repl = [r['value'] for r in m['replacements']][:3]
                    page_errors.append({
                        'id':           cell['id'],
                        'bbox':         cell['bbox'],
                        'error_text':   txt[m['offset']:m['offset']+m['length']],
                        'offset':       m['offset'],
                        'length':       m['length'],
                        'message':      m['message'],
                        'shortMessage': m.get('shortMessage'),
                        'replacements': repl,
                        'ruleId':       m['rule']['id'],
                        'issueType':    m['rule']['issueType'],
                        'category':     m['rule']['category']['id'],
                        'context':      m['context']['text']
                    })

        page['errors'] = page_errors

    return data