import os
import sys
import argparse
import base64
import zipfile
import tempfile
from pathlib import Path
from xml.etree import ElementTree as ET
from ebooklib import epub
import warnings

# Create covers directory if not exists
COVERS_DIR = 'covers'
os.makedirs(COVERS_DIR, exist_ok=True)

# Отключаем предупреждения
warnings.filterwarnings("ignore", category=UserWarning, module='ebooklib.epub')
warnings.filterwarnings("ignore", category=FutureWarning, module='ebooklib.epub')

def extract_from_zip(zip_path, target_extensions):
    """Извлекает файлы из ZIP-архива."""
    extracted_files = []
    try:
        with zipfile.ZipFile(zip_path, 'r') as zip_ref:
            for file in zip_ref.namelist():
                if any(file.lower().endswith(ext) for ext in target_extensions):
                    temp_dir = tempfile.mkdtemp()
                    extracted_path = os.path.join(temp_dir, os.path.basename(file))
                    with open(extracted_path, 'wb') as f:
                        f.write(zip_ref.read(file))
                    extracted_files.append(extracted_path)
        return extracted_files
    except Exception as e:
        print(f"Ошибка при распаковке {zip_path}: {e}", file=sys.stderr)
        return []

def parse_epub_metadata(epub_path):
    """Парсит метаданные из EPUB файла."""
    try:
        book = epub.read_epub(epub_path, options={'ignore_ncx': True})

        def get_metadata(field):
            return book.get_metadata('DC', field)[0][0] if book.get_metadata('DC', field) else ""

        metadata = {
            "Обложка": None,
            "Название": get_metadata('title') or "Без названия",
            "Автор": ", ".join([a[0] for a in book.get_metadata('DC', 'creator')]) or "Неизвестен",
            "Серия": get_metadata('series') or "",
            "Жанр": ", ".join([g[0] for g in book.get_metadata('DC', 'subject')]) or "",
            "Описание": get_metadata('description') or "Нет описания",
            "Файл": os.path.basename(epub_path)
        }

        # Поиск обложки
        cover_item = next((item for item in book.get_items()
                           if isinstance(item, epub.EpubImage) or
                           (hasattr(item, 'get_name') and 'cover' in item.get_name().lower(), None)))

        if cover_item:
            cover_path = os.path.join(COVERS_DIR, f"cover_{os.path.basename(epub_path)}.jpg")
        with open(cover_path, 'wb') as f:
            f.write(cover_item.get_content())
        metadata["Обложка"] = cover_path

        return metadata
    except Exception as e:
        print(f"Ошибка при обработке EPUB {epub_path}: {e}", file=sys.stderr)
        return None

def parse_fb2_metadata(fb2_path):
    """Парсит метаданные из FB2 файла."""
    try:
        tree = ET.parse(fb2_path)
        root = tree.getroot()
        ns = {'fb': 'http://www.gribuser.ru/xml/fictionbook/2.0'}

        title_info = root.find('fb:description/fb:title-info', ns)
        if title_info is None:
            raise ValueError("Не найден title-info")

        def get_text(element):
            return element.text if element is not None else ""

        metadata = {
            "Обложка": None,
            "Название": get_text(title_info.find('fb:book-title', ns)) or "Без названия",
            "Автор": ", ".join([
                f"{get_text(a.find('fb:first-name', ns))} {get_text(a.find('fb:last-name', ns))}".strip()
                for a in title_info.findall('fb:author', ns)
            ]) or "Неизвестен",
            "Серия": (f"{title_info.find('fb:sequence', ns).get('name', '')} "
                      f"(№{title_info.find('fb:sequence', ns).get('number', '')})").strip(' ()')
            if title_info.find('fb:sequence', ns) is not None
               and title_info.find('fb:sequence', ns).get('name')
            else "",
            "Жанр": ", ".join(filter(None, [
                g.text for g in title_info.findall('fb:genre', ns)
            ])) or "",
            "Описание": ET.tostring(
                title_info.find('fb:annotation', ns),
                encoding='unicode', method='text'
            ).strip() if title_info.find('fb:annotation', ns) is not None else "Нет описания"
            # "Файл": os.path.basename(fb2_path)
        }

        # Поиск обложки
        for binary in root.findall('fb:binary', ns):
            if binary.get('id', '').startswith('cover'):
                cover_path = os.path.join(COVERS_DIR, f"cover_{os.path.basename(fb2_path)}.jpg")
                with open(cover_path, 'wb') as f:
                    f.write(base64.b64decode(binary.text))
                metadata["Обложка"] = cover_path
                break

        return metadata
    except Exception as e:
        print(f"Ошибка при обработке FB2 {fb2_path}: {e}", file=sys.stderr)
        return None

def process_zip(zip_path):
    """Обрабатывает ZIP-архив с книгами."""
    metadata_list = []
    for ext in ['.epub', '.fb2']:
        extracted_files = extract_from_zip(zip_path, [ext])
        for file in extracted_files:
            try:
                meta = parse_epub_metadata(file) if ext == '.epub' else parse_fb2_metadata(file)
                if meta:
                    metadata_list.append(meta)
            finally:
                try:
                    if os.path.exists(file):
                        os.remove(file)
                        dir_path = os.path.dirname(file)
                        if os.path.exists(dir_path):
                            os.rmdir(dir_path)
                except Exception as e:
                    print(f"Ошибка очистки {file}: {e}", file=sys.stderr)
    return metadata_list

def process_file(file_path):
    """Обрабатывает файл любого поддерживаемого формата."""
    file_path = str(file_path)
    if file_path.lower().endswith('.zip'):
        return process_zip(file_path)
    elif file_path.lower().endswith('.epub'):
        meta = parse_epub_metadata(file_path)
        return [meta] if meta else []
    elif file_path.lower().endswith('.fb2'):
        meta = parse_fb2_metadata(file_path)
        return [meta] if meta else []
    return []

def apply_filters(metadata_list, filters):
    """Применяет фильтры к списку метаданных."""
    if not filters:
        return metadata_list

    filtered = []
    for meta in metadata_list:
        match = True
        for field, value in filters.items():
            if field in meta and value.lower() not in str(meta[field]).lower():
                match = False
                break
        if match:
            filtered.append(meta)
    return filtered

def sort_metadata(metadata_list, sort_field, reverse=False):
    """Сортирует метаданные по указанному полю."""
    if not sort_field:
        return metadata_list

    return sorted(
        metadata_list,
        key=lambda x: str(x.get(sort_field, "")).lower(),
        reverse=reverse
    )

def metadata_to_html(metadata_list):
    """Генерирует HTML-представление списка метаданных в отчет."""
    css = """<style>
    body {
        font-family: 'Segoe UI', Tahoma, Geneva, Verdana, sans-serif;
        line-height: 1.6;
        color: #333;
        max-width: 1200px;
        margin: 0 auto;
        padding: 20px;
        background-color: #f9f9f9;
    }
    
    h1 {
        text-align: center;
        color: #2c3e50;
        margin-bottom: 30px;
        font-size: 2.2em;
        border-bottom: 2px solid #3498db;
        padding-bottom: 10px;
    }
    
    .book {
        background-color: white;
        border-radius: 8px;
        box-shadow: 0 4px 8px rgba(0, 0, 0, 0.1);
        margin-bottom: 30px;
        overflow: hidden;
        transition: transform 0.3s ease, box-shadow 0.3s ease;
    }
    
    .book:hover {
        transform: translateY(-5px);
        box-shadow: 0 6px 12px rgba(0, 0, 0, 0.15);
    }
    
    .cover {
        float: left;
        width: 180px;
        height: 270px;
        margin-right: 20px;
        border: 1px solid #ddd;
        border-radius: 4px;
        object-fit: cover;
        background-color: #f5f5f5;
    }
    
    .no-cover {
        display: flex;
        align-items: center;
        justify-content: center;
        background: #eaeaea;
        color: #777;
        border: 1px dashed #aaa;
        font-style: italic;
        font-size: 0.9em;
    }
    
    .meta {
        padding: 20px;
        margin-left: 200px;
    }
    
    .title {
        margin-top: 0;
        color: #2c3e50;
        font-size: 1.4em;
        border-bottom: 1px solid #eee;
        padding-bottom: 10px;
    }
    
    .meta p {
        margin: 8px 0;
    }
    
    strong {
        color: #2c3e50;
    }
    
    .clear {
        clear: both;
    }
    
    /* Адаптивность для мобильных устройств */
    @media (max-width: 768px) {
        .cover {
            float: none;
            display: block;
            margin: 0 auto 15px;
        }
        
        .meta {
            margin-left: 0;
        }
        
        .title {
            text-align: center;
        }
    }
    </style>\n\n"""

    html = f"""
    <!DOCTYPE html>
    <html lang="ru">
    <head>
        <meta charset="UTF-8">
        <meta name="viewport" content="width=device-width, initial-scale=1.0">
        <title>Каталог книг</title>
        {css}
    </head>
    
    <body>
    <h1>Каталог книг</h1>\n\n
    """

    for meta in metadata_list:
        html += '<div class="book">\n'

        # Обложка
        if meta['Обложка']:
            cover_rel_path = os.path.join(COVERS_DIR, os.path.basename(meta['Обложка']))
            html += f'<img src="{cover_rel_path}" class="cover">\n'
        else:
            html += '<div class="cover no-cover">Нет обложки</div>\n'

        # Метаданные
        html += (
            '<div class="meta">\n'
            f'<h2 class="title">{meta["Название"]}</h2>\n'
            f'<p><strong>Автор:</strong> {meta["Автор"]}</p>\n'
            f'<p><strong>Серия:</strong> {meta["Серия"] or "—"}</p>\n'
            f'<p><strong>Жанр:</strong> {meta["Жанр"] or "—"}</p>\n'
            # f'<p><strong>Файл:</strong> <code>{meta["Файл"]}</code></p>\n'
            f'<p><strong>Описание:</strong><br>\n{meta["Описание"]}</p>\n'
            '</div>\n'
            '<div style="clear:both;"></div>\n'
            '</div>\n\n'
        )

    html += '</body>\n</html>\n'
    return html

def main():
    parser = argparse.ArgumentParser(
        description='Извлечение метаданных из книг (FB2/EPUB/ZIP)',
        formatter_class=argparse.ArgumentDefaultsHelpFormatter
    )
    parser.add_argument('input', help='Файл или директория с книгами')
    parser.add_argument('-o', '--output', default='books_metadata.html',
                        help='Выходной HTML файл')

    # Параметры сортировки
    parser.add_argument('--sort', choices=['Автор', 'Серия', 'Жанр', 'Название'],
                        help='Поле для сортировки')
    parser.add_argument('--reverse', action='store_true',
                        help='Сортировать в обратном порядке')

    # Параметры фильтрации
    parser.add_argument('--filter-author', help='Фильтр по автору (подстрока)')
    parser.add_argument('--filter-series', help='Фильтр по серии (подстрока)')
    parser.add_argument('--filter-genre', help='Фильтр по жанру (подстрока)')

    args = parser.parse_args()

    try:
        # Собираем метаданные
        metadata = []
        input_path = Path(args.input)

        if input_path.is_file():
            metadata = process_file(input_path)
        elif input_path.is_dir():
            for file in input_path.rglob('*'):
                if file.suffix.lower() in ('.epub', '.fb2', '.zip'):
                    metadata.extend(process_file(file))
        else:
            raise FileNotFoundError("Указанный путь не существует")

        if not metadata:
            raise ValueError("Не найдено книг для обработки")

        # Применяем фильтры
        filters = {}
        if args.filter_author:
            filters['Автор'] = args.filter_author
        if args.filter_series:
            filters['Серия'] = args.filter_series
        if args.filter_genre:
            filters['Жанр'] = args.filter_genre

        filtered_metadata = apply_filters(metadata, filters)

        # Сортируем
        sorted_metadata = sort_metadata(
            filtered_metadata,
            args.sort,
            args.reverse
        )

        # Сохраняем результат
        with open(args.output, 'w', encoding='utf-8') as f:
            f.write(metadata_to_html(sorted_metadata))

        print(f"Обработано: {len(metadata)} книг | "
              f"После фильтрации: {len(filtered_metadata)} | "
              f"Сохранено в: {args.output}")

    except Exception as e:
        print(f"Ошибка: {e}", file=sys.stderr)
        sys.exit(1)

if __name__ == '__main__':
    main()