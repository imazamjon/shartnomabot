"""Local OCR. Uploaded requisites never go to an external AI service."""
import os
import re
import shutil
import subprocess
import tempfile
import hashlib
import time
from collections import OrderedDict
from pathlib import Path

MAX_BYTES = 10 * 1024 * 1024
_TEXT_CACHE = OrderedDict()
ALIASES = {
    'name': r'nomi|korxona(?: nomi)?|наименование(?: организации)?|название(?: организации)?',
    'stir': r'stir|inn|инн|стир',
    'director': r'direktor|rahbar|директор|руководитель',
    'address': r'manzil[i]?|адрес(?: организации| местонахождения)?|юридический адрес',
    'bank': r'bank(?: nomi)?|банк|наименование банка',
    'account': r'hisob(?: raqami)?|h/r|р/с|расч[её]тный сч[её]т|сч[её]т',
    'mfo': r'mfo|мфо',
    'phone': r'tel(?:efon)?\.?|тел(?:ефон)?\.?|phone',
}
PHONE = re.compile(r'\+?[0-9][0-9 ()-]{5,22}[0-9]')


class ReadError(ValueError):
    pass


def extract_fields(text):
    result = {}
    lines = text.replace('\r', '').splitlines()
    for key, aliases in ALIASES.items():
        values = []
        pattern = re.compile(r'^\s*(?:' + aliases + r')\s*(?:[:=—–-]\s*|\s+)(.*?)\s*$', re.I)
        label_only = re.compile(r'^\s*(?:' + aliases + r')\s*[:=]?\s*$', re.I)
        for i, line in enumerate(lines):
            match = pattern.match(line)
            value = match[1].strip(' :;') if match else ''
            if not value and label_only.fullmatch(line) and i + 1 < len(lines):
                value = lines[i + 1].strip()
            if not value:
                continue
            if key in ('stir', 'account', 'mfo'):
                length = {'stir': 9, 'account': 20, 'mfo': 5}[key]
                value = re.sub(r'[\s-]', '', value)
                if not re.fullmatch(r'[0-9]{' + str(length) + '}', value):
                    continue
            if key == 'phone':
                match = PHONE.search(value)
                if not match or len(re.sub(r'[^0-9]', '', match[0])) < 7:
                    continue
                value = ' '.join(match[0].split())
                if values:  # Bir nechta telefon bo‘lsa birinchisi olinadi.
                    continue
            if value not in values:
                values.append(value)
        if len(values) > 1:
            raise ReadError('Hujjatda bir maydon uchun turli qiymatlar bor. Rekvizitlarni matn bilan yuboring.')
        if values:
            result[key] = values[0][:500]
    return result


def run(args, env=None, timeout=30):
    try:
        result = subprocess.run(args, capture_output=True, timeout=timeout, env=env)
    except (OSError, subprocess.TimeoutExpired):
        raise ReadError('Hujjatni o‘qish bajarilmadi. Aniqroq rasm yoki matn yuboring.') from None
    if result.returncode:
        raise ReadError('Faylni o‘qib bo‘lmadi. Himoyalanmagan PDF yoki aniqroq rasm yuboring.')
    return result.stdout.decode('utf-8', errors='replace')


def file_kind(data):
    if data.startswith(b'%PDF-'):
        return '.pdf'
    if data.startswith(b'\x89PNG\r\n\x1a\n'):
        return '.png'
    if data.startswith(b'\xff\xd8\xff'):
        return '.jpg'
    if data[:4] in (b'II*\0', b'MM\0*'):
        return '.tiff'
    if data.startswith(b'RIFF') and data[8:12] == b'WEBP':
        return '.webp'
    raise ReadError('JPG, PNG, WEBP, TIFF rasm yoki PDF yuboring.')


def read_document(data, root):
    if not data or len(data) > MAX_BYTES:
        raise ReadError('Fayl hajmi 10 MB dan oshmasin.')
    key = (str(Path(root).resolve()), hashlib.sha256(data).digest())
    cached = _TEXT_CACHE.get(key)
    if cached and time.monotonic() - cached[0] < 900:
        _TEXT_CACHE.move_to_end(key)
        return cached[1]
    text = _read_document(data, root)
    _TEXT_CACHE[key] = (time.monotonic(), text)
    while len(_TEXT_CACHE) > 16:
        _TEXT_CACHE.popitem(last=False)
    return text


def _read_document(data, root):
    kind = file_kind(data)
    runtime = Path(root) / 'runtime'
    binary = runtime / 'usr/bin/tesseract'
    env = dict(os.environ, OMP_THREAD_LIMIT='1')
    if binary.exists():
        env['LD_LIBRARY_PATH'] = str(runtime / 'usr/lib/x86_64-linux-gnu')
        env['TESSDATA_PREFIX'] = str(runtime / 'usr/share/tesseract-ocr/5/tessdata')
    else:
        binary = shutil.which('tesseract')
    with tempfile.TemporaryDirectory(prefix='shartnoma-ocr-') as folder:
        folder = Path(folder)
        source = folder / ('input' + kind)
        source.write_bytes(data)
        images = [source]
        if kind == '.pdf':
            info = run(['pdfinfo', str(source)])
            pages = re.search(r'^Pages:\s+(\d+)', info, re.M)
            if not pages or int(pages[1]) > 5:
                raise ReadError('PDF 5 betdan oshmasin. Faqat rekvizitlar betini yuboring.')
            text = run(['pdftotext', '-layout', str(source), '-'])
            # Scans have no text layer. If any bank field is missing, also OCR.
            fields = extract_fields(text)
            if len(text.strip()) >= 30 and fields:
                return text
            run(['pdftoppm', '-scale-to', '2400', '-png', str(source), str(folder / 'page')], timeout=45)
            images = sorted(folder.glob('page-*.png'))
        else:
            text = ''
        if not binary:
            raise ReadError('OCR dasturi topilmadi. Administrator runtime papkasini tekshirsin.')
        output = []
        for image in images:
            output.append(run([str(binary), str(image), 'stdout', '-l', 'uzb+rus+eng', '--psm', '6'], env=env))
        recognized = '\n'.join(output)
        if not recognized.strip() and not text.strip():
            raise ReadError('Rasmdan matn topilmadi. Aniqroq rasm yuboring.')
        # Prefer full OCR result for scans, text layer otherwise. Avoid mixing
        # two inconsistent readings of the same numbers.
        return text if len(extract_fields(text)) > len(extract_fields(recognized)) else recognized
