import json
from pdfminer.high_level import extract_pages
from pdfminer.layout import LTTextBox, LTTextLine, LTImage, LTFigure

def parse_layout(element):
    objs = []
    if isinstance(element, (LTTextBox, LTTextLine)):
        text = element.get_text().strip()
        if text:
            objs.append({
                "type": "text",
                "text": text,
                "bbox": [element.x0, element.y0, element.x1, element.y1]
            })
    elif isinstance(element, LTImage):
        objs.append({
            "type": "image",
            "name": element.name,
            "bbox": [element.x0, element.y0, element.x1, element.y1]
        })
    elif isinstance(element, LTFigure):
        for child in element:
            objs.extend(parse_layout(child))
    return objs

def parse_pdf(pdf_path):
    document = {"pages": []}
    for page_number, layout in enumerate(extract_pages(pdf_path), start=1):
        page_obj = {"page_number": page_number, "objects": []}
        for element in layout:
            page_obj["objects"].extend(parse_layout(element))
        document["pages"].append(page_obj)
    return document