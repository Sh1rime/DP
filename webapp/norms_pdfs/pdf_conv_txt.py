import re
import sys
from pathlib import Path

try:
    import fitz  # PyMuPDF
except ImportError:
    print(
        "Ошибка: не установлен модуль PyMuPDF (fitz).\n"
        "Установите его командой: pip install PyMuPDF",
        file=sys.stderr
    )
    sys.exit(1)


def extract_raw_text_from_pdf(pdf_path: Path) -> str:
    """
    Открывает PDF через PyMuPDF (fitz) и возвращает весь собранный текст
    из всех страниц в одну большую строку с переносами '\n'.
    """
    try:
        doc = fitz.open(str(pdf_path))
    except Exception as e:
        raise RuntimeError(f"Не удалось открыть PDF '{pdf_path.name}': {e}")

    pages = []
    for page in doc:
        pages.append(page.get_text("text"))
    doc.close()
    return "\n".join(pages)


def merge_hyphenated(text: str) -> str:
    """
    Убирает дефисные переносы: «слово-\nпродолжение» → «словопродолжение».
    """
    # Шаблон: дефис в конце строки (включая пробел перед \n) → убираем дефис и разрыв
    return re.sub(r"-\s*\n\s*", "", text)


def fix_hanging_letters(lines: list) -> list:
    """
    Исправляет «висячие» одиночные буквы или пары букв:
    если строка состоит ровно из 1–2 кириллических букв, присоединяет без пробела
    к предыдущей строке.
    """
    result = []
    for ln in lines:
        stripped = ln.strip()
        # Если ровно 1–2 буквы в кириллице
        if re.fullmatch(r"[А-Яа-яЁё]{1,2}", stripped):
            if result:
                # Пришиваем к предыдущей без пробела
                result[-1] = result[-1].rstrip() + stripped
            else:
                # Если нет предыдущей, просто сохраняем
                result.append(stripped)
        else:
            result.append(ln)
    return result


def should_join(prev: str, curr: str) -> bool:
    """
    Решаем, склеивать ли две подряд идущие строки в один абзац:
      • prev не оканчивается на .?!;:
      • curr не пустая строка,
      • curr не выглядит как «номер раздела» (например, «1.1  Общие положения»),
      • curr не начинается с точного двух-трёх пробелов (либо отступа), что может означать новую секцию,
      • в противном случае скорее всего это просто «разрыв по ширине».
    """
    if not prev or not curr:
        return False

    # Если prev заканчивается на пунктуацию, не склеиваем —
    # скорее всего конец предложения/абзаца.
    if re.search(r"[.?!;:]$", prev.rstrip()):
        return False

    # Если curr начинается с цифр+точка+пробел (номер секции), не склеиваем
    if re.match(r"^\d+(\.\d+)*\s+", curr.lstrip()):
        return False

    # Если curr начинается с двух пробелов (отступ), не склеиваем
    if curr.startswith("  "):
        return False

    # Иначе склеиваем
    return True


def normalize_whitespace(line: str) -> str:
    """
    Сводит подряд идущие пробельные символы (пробел, таб) в один пробел,
    обрезает пробелы в начале и конце.
    """
    ln = re.sub(r"[ \t]+", " ", line)
    return ln.strip()


def normalize_text(raw: str) -> list:
    """
    Основной «конвейер» преобразований:
      1) merge_hyphenated — убрать дефисные переносы.
      2) splitlines → получаем список строк pagesplit.
      3) fix_hanging_letters — склеить одиночные буквы с предыдущими строками.
      4) объединить «Broken lines» в абзацы: если should_join(prev,curr) == True.
      5) normalize_whitespace — убрать лишние пробелы.
      6) сохранить итоговый список строк final_lines (без удаления каких-либо фрагментов).
    """
    # 1) Дефисные переносы
    step1 = merge_hyphenated(raw)

    # 2) Разбить на строки
    pagesplit = step1.splitlines()

    # 3) Исправить висячие буквы-пары
    step3 = fix_hanging_letters(pagesplit)

    # 4) Объединить строки в абзацы
    paras = []
    prev = ""
    for ln in step3:
        stripped_ln = ln.rstrip()
        if prev and should_join(prev, stripped_ln):
            paras[-1] = paras[-1] + " " + stripped_ln
            prev = paras[-1]
        else:
            paras.append(stripped_ln)
            prev = stripped_ln

    # 5) Нормализовать пробельные символы
    final_lines = []
    for ln in paras:
        norm = normalize_whitespace(ln)
        final_lines.append(norm)

    return final_lines


def process_pdf(pdf_path: Path):
    """
    Для каждого PDF:
      • извлечь «сырошный» текст (extract_raw_text_from_pdf),
      • передать через normalize_text,
      • записать результат в <stem>_normalized.txt.
    """
    print(f"[Обработка] {pdf_path.name} …", end=" ", flush=True)
    try:
        raw = extract_raw_text_from_pdf(pdf_path)
    except Exception as e:
        print(f"❌ Ошибка при чтении PDF: {e}")
        return

    normalized = normalize_text(raw)
    if not normalized:
        print("⚠️ Результат пуст.")
        return

    out_file = pdf_path.with_name(pdf_path.stem + "_normalized.txt")
    try:
        with open(out_file, "w", encoding="utf-8") as f:
            for ln in normalized:
                f.write(ln + "\n")
        print("✅ Сохранено.")
    except Exception as e:
        print(f"❌ Ошибка при записи: {e}")


def main():
    folder = Path(__file__).resolve().parent
    pdf_files = sorted(folder.glob("*.pdf"))
    if not pdf_files:
        print("Нет PDF-файлов для обработки.")
        return

    for pdf in pdf_files:
        process_pdf(pdf)

    print("\nВсе PDF обработаны.")


if __name__ == "__main__":
    main()