"""Telegram shartnoma bot — Python standard library only."""
from __future__ import annotations

import json
import logging
import os
import re
import sqlite3
import time
import uuid
import threading
from collections import OrderedDict
import requests
from datetime import datetime
from decimal import Decimal, InvalidOperation
from pathlib import Path
from zoneinfo import ZoneInfo
from orginfo import Orginfo, LookupUnavailable
from ocr import MAX_BYTES, ReadError, read_document, extract_fields
from templates import inspect_template, fill_template
from document import document_bytes
from contract_values import calculate_item
from pdf_export import export_pdf, ExportError, available as pdf_available
from fit import fit_document

ROOT = Path(__file__).resolve().parent
ACCESS_DENIED = (
    '🔒 Siz admin emassiz\n\n'
    'Ushbu botdan faqat ruxsat berilgan adminlar foydalanishi mumkin.\n\n'
    '👤 Admin bo‘lish uchun @azamjonbro ga murojaat qiling.'
)
NEW, ADD, NEXT, CONFIRM, CANCEL = (
    '📄 Yangi shartnoma', '➕ Yana tovar', '➡️ Davom etish',
    '✅ Tasdiqlash', '❌ Bekor qilish',
)
FIELDS = ('name', 'stir', 'director', 'address', 'bank', 'account', 'mfo')
LABELS = ('Nomi', 'STIR', 'Direktor', 'Manzil', 'Bank', 'Hisob', 'MFO')
OPTIONAL_FIELDS = ('phone', 'oked')
# Telefon shartnomaga yozilmaydi, shuning uchun sozlamada so‘ralmaydi.
SETTINGS_FIELDS = ('stir', 'name', 'director', 'address', 'bank', 'account', 'mfo', 'oked')
SETTINGS_LABELS = ('STIR', 'Nomi', 'Direktor', 'Manzil', 'Bank', 'Hisob', 'MFO', 'OKED / IFUT (ixtiyoriy)')
KEEP = '⏭ Hozirgisini qoldirish'
NUMBER_SETTINGS = '🔢 Raqamlash sozlamalari'
EDIT_NUMBER, EDIT_DATE, TODAY = '✏️ Raqamni o‘zgartirish', '📅 Sanani o‘zgartirish', '📅 Bugungi sana'
READY, CUSTOM = '📑 Tayyor shablondan foydalanish', '📤 O‘z shablonimni ulash'
VAT12, VAT0, VAT_OTHER = 'QQS 12%', 'QQSsiz', 'Boshqa QQS stavkasi'
INCLUDED, EXCLUDED = 'Narx QQS bilan', 'Narx QQSsiz'
# Har yangi shartnomada qaysi namuna ishlatilishi so‘raladi (fayl mavjud bo‘lsa).
DISCOVER_FILE = 'template-discover-invest.docx'
CONTRACT_TEMPLATES = (('📑 Umumiy shartnoma', 'template.docx'),
                      ('🏢 Discover Invest shartnomasi', DISCOVER_FILE))
EXAMPLE = ('Nomi: MISOL MCHJ\nSTIR: {stir}\nDirektor: Ism Familiya\n'
           'Manzil: Toshkent\nBank: Bank nomi\nHisob: 20208000000000000001\nMFO: 00450')


def storage_status(root):
    """Railway volume data/ ga ulanganmi — ma'lumotlar deploy'dan keyin saqlanadimi."""
    data = (Path(root) / 'data').resolve()
    mount = os.environ.get('RAILWAY_VOLUME_MOUNT_PATH', '').rstrip('/')
    if mount and Path(mount).resolve() == data:
        return True, f'💾 Ma’lumotlar doimiy: Railway volume ulangan ({mount}).'
    if mount:
        return False, f'⚠️ Volume {mount} ga ulangan, lekin kerakli joy {data}. Mount path’ni /app/data qiling.'
    if os.path.ismount(data):
        return True, '💾 Ma’lumotlar doimiy: data/ alohida diskda.'
    if os.environ.get('RAILWAY_ENVIRONMENT') or os.environ.get('RAILWAY_PROJECT_ID'):
        return False, '⚠️ Railway volume ulanmagan! Deploy’da raqamlash va sozlamalar o‘chadi.'
    return True, '💾 Ma’lumotlar mahalliy diskda saqlanadi.'


def load_env(path):
    if path.exists():
        for line in path.read_text().splitlines():
            if line.strip() and not line.lstrip().startswith('#') and '=' in line:
                key, value = line.split('=', 1)
                os.environ.setdefault(key.strip(), value.strip().strip('\"\''))


def amount(text):
    value = re.sub(r'[\s\u00a0]', '', text).replace(',', '.')
    if not re.fullmatch(r'\d{1,15}(?:\.\d{1,2})?', value):
        raise ValueError('Summani 27000000 yoki 27000000.50 shaklida kiriting.')
    try:
        number = Decimal(value)
    except InvalidOperation:
        raise ValueError('Summa noto‘g‘ri.') from None
    if not Decimal('0') < number <= Decimal('999999999999.99'):
        raise ValueError('Summa 0 dan katta va 999 999 999 999.99 dan oshmasin.')
    return str(number.quantize(Decimal('0.01')))


def contract_number(text):
    if not re.fullmatch(r'[0-9]{1,9}', text) or not 1 <= int(text) <= 999999998:
        raise ValueError('Shartnoma raqami 1–999999998 oralig‘idagi butun son bo‘lsin.')
    return int(text)


def contract_date(text):
    try:
        result = datetime.strptime(text, '%d.%m.%Y')
    except ValueError:
        raise ValueError('Sanani KK.OO.YYYY shaklida kiriting. Masalan: 14.11.2026') from None
    if not 1900 <= result.year <= 2100:
        raise ValueError('Sana yili 1900–2100 oralig‘ida bo‘lsin.')
    return result.strftime('%d.%m.%Y')


def money(value):
    return f'{Decimal(value):,.2f}'.replace(',', ' ') + ' so‘m'


def validate_company(company, stir=None):
    if any(not str(company.get(key, '')).strip() for key in FIELDS):
        raise ValueError('Barcha rekvizitlarni to‘ldiring: ' + ', '.join(LABELS))
    for key, length in [('stir', 9), ('account', 20), ('mfo', 5)]:
        if not re.fullmatch(r'[0-9]{' + str(length) + '}', str(company[key])):
            raise ValueError(f'{dict(zip(FIELDS, LABELS))[key]} {length} ta raqam bo‘lishi kerak.')
    if stir and company['stir'] != stir:
        raise ValueError('⚠️ Rekvizitlardagi STIR kiritilgan STIRdan farq qiladi. Tekshirib qayta yuboring.')
    result = {key: str(company[key]).strip() for key in FIELDS}
    for key in OPTIONAL_FIELDS:
        if key in company:
            result[key] = str(company[key]).strip()
    return result


def write_json(path, data):
    path.parent.mkdir(parents=True, exist_ok=True)
    temp = path.with_suffix('.tmp')
    temp.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding='utf-8')
    temp.chmod(0o600)
    temp.replace(path)


def parse_company(text, stir, defaults=None):
    pairs = {key: value for key, value in (defaults or {}).items() if key in FIELDS}
    labels = {label.casefold(): key for key, label in zip(FIELDS, LABELS)}
    for line in text.splitlines():
        label, sep, value = line.partition(':')
        key = labels.get(label.strip().casefold())
        if sep and key:
            pairs[key] = value.strip()
    return validate_company(pairs, stir)


def company_text(company):
    lines = [f'{label}: {company.get(key) or "—"}' for key, label in zip(FIELDS, LABELS)]
    lines += [f'OKED / IFUT: {company["oked"]}'] if company.get('oked') else []
    return '\n'.join(lines)


def summary(session):
    lines = []
    for i, item in enumerate(session['items'], 1):
        detail = f" — {item['quantity']} {item.get('unit', '')} × {money(item['price'])}" if 'price' in item else ''
        lines.append(f'{i}. {item["name"]}{detail} → {money(item["amount"])}')
    total = sum((Decimal(item['amount']) for item in session['items']), Decimal(0))
    return '\n'.join(lines + [f'Jami: {money(total)}'])


class Store:
    def __init__(self, path):
        self.db = sqlite3.connect(path)
        self.db.executescript('''
            CREATE TABLE IF NOT EXISTS sessions (chat INTEGER PRIMARY KEY, data TEXT NOT NULL);
            CREATE TABLE IF NOT EXISTS contracts (
                id INTEGER PRIMARY KEY AUTOINCREMENT, chat INTEGER NOT NULL,
                date TEXT NOT NULL, data TEXT NOT NULL, file TEXT NOT NULL DEFAULT '');
            CREATE TABLE IF NOT EXISTS meta (key TEXT PRIMARY KEY, value TEXT NOT NULL);
        ''')
        columns = {row[1] for row in self.db.execute('PRAGMA table_info(contracts)')}
        for column in ('display_number', 'scope'):
            if column not in columns:
                self.db.execute(f"ALTER TABLE contracts ADD COLUMN {column} TEXT NOT NULL DEFAULT ''")
        self.db.execute('CREATE TABLE IF NOT EXISTS numbering (scope TEXT PRIMARY KEY, next_number INTEGER NOT NULL)')
        self.db.execute("CREATE UNIQUE INDEX IF NOT EXISTS contract_number_scope ON contracts(scope, display_number) WHERE scope!='' AND display_number!=''")
        # Preserve numbers already issued before separate business numbering.
        for identity, chat, raw in self.db.execute("SELECT id,chat,data FROM contracts WHERE scope='' AND display_number=''").fetchall():
            try:
                old = json.loads(raw)
                stir = old.get('seller_snapshot', {}).get('stir') if old.get('seller_snapshot') else None
                if stir:
                    scope = f'stir:{stir}'
                    self.db.execute('UPDATE contracts SET scope=?,display_number=? WHERE id=?', (scope, str(identity), identity))
                    self.db.execute('INSERT INTO numbering VALUES (?,?) ON CONFLICT(scope) DO UPDATE SET next_number=MAX(next_number,excluded.next_number)', (scope, identity + 1))
            except (ValueError, TypeError, AttributeError):
                continue
        # Raqamlash endi admin emas, sotuvchi korxona (STIR) bo‘yicha umumiy:
        # bir korxonaning bir nechta xodimi bir xil № bermasligi uchun.
        for scope, value in self.db.execute("SELECT scope,next_number FROM numbering WHERE scope NOT LIKE 'stir:%'").fetchall():
            match = re.fullmatch(r'\d+:(\d{9})', scope)
            if not match:
                continue
            shared = 'stir:' + match[1]
            self.db.execute('INSERT INTO numbering VALUES (?,?) ON CONFLICT(scope) DO UPDATE SET next_number=MAX(next_number,excluded.next_number)', (shared, value))
            self.db.execute('DELETE FROM numbering WHERE scope=?', (scope,))
        for identity, scope in self.db.execute("SELECT id,scope FROM contracts WHERE scope!='' AND scope NOT LIKE 'stir:%'").fetchall():
            match = re.fullmatch(r'\d+:(\d{9})', scope)
            if match:
                self.db.execute('UPDATE OR IGNORE contracts SET scope=? WHERE id=?', ('stir:' + match[1], identity))
        self.db.commit()

    def next_number(self, scope):
        row = self.db.execute('SELECT next_number FROM numbering WHERE scope=?', (scope,)).fetchone()
        return row[0] if row else None

    def number_used(self, scope, number):
        return self.db.execute('SELECT 1 FROM contracts WHERE scope=? AND display_number=?', (scope, str(number))).fetchone() is not None

    def set_next_number(self, scope, number):
        number = contract_number(str(number))
        if self.number_used(scope, number):
            raise ValueError('Bu raqam shu korxona uchun avval ishlatilgan. Boshqa raqam kiriting.')
        with self.db:
            self.db.execute('INSERT OR REPLACE INTO numbering VALUES (?,?)', (scope, number))

    def session(self, chat):
        row = self.db.execute('SELECT data FROM sessions WHERE chat=?', (chat,)).fetchone()
        return json.loads(row[0]) if row else None

    def save(self, chat, data):
        with self.db:
            self.db.execute('INSERT OR REPLACE INTO sessions VALUES (?,?)', (chat, json.dumps(data)))

    def clear(self, chat):
        with self.db:
            self.db.execute('DELETE FROM sessions WHERE chat=?', (chat,))

    def create_contract(self, chat, session):
        date = contract_date(session.get('contract_date') or datetime.now(ZoneInfo('Asia/Tashkent')).strftime('%d.%m.%Y'))
        scope = session.get('number_scope', '')
        number = session.get('contract_number')
        if number is not None:
            number = contract_number(str(number))
        try:
            with self.db:
                result = self.db.execute('INSERT INTO contracts(chat,date,data,display_number,scope) VALUES (?,?,?,?,?)',
                                         (chat, date, json.dumps(session), str(number) if number else '', scope))
                if scope and number:
                    next_value = max(number + 1, self.next_number(scope) or 1)
                    self.db.execute('INSERT OR REPLACE INTO numbering VALUES (?,?)', (scope, next_value))
        except sqlite3.IntegrityError:
            raise ValueError('Bu shartnoma raqami avval ishlatilgan. Raqamni o‘zgartiring.') from None
        return result.lastrowid, date

    def last_file(self, chat):
        row = self.db.execute("SELECT file FROM contracts WHERE chat=? AND file!='' ORDER BY id DESC LIMIT 1", (chat,)).fetchone()
        return Path(row[0]) if row else None

    def set_file(self, number, path):
        with self.db:
            self.db.execute('UPDATE contracts SET file=? WHERE id=?', (str(path), number))

    def offset(self, value=None):
        if value is not None:
            with self.db:
                self.db.execute("INSERT OR REPLACE INTO meta VALUES ('offset',?)", (str(value),))
        row = self.db.execute("SELECT value FROM meta WHERE key='offset'").fetchone()
        return int(row[0]) if row else 0


class Telegram:
    def __init__(self, token):
        self.base = f'https://api.telegram.org/bot{token}/'
        self.local = threading.local()
        self.file_cache = OrderedDict()
        self.cache_size = 0

    def session(self):
        if not hasattr(self.local, 'session'):
            self.local.session = requests.Session()
        return self.local.session

    def request(self, method, payload=None, body=None, content_type='application/json'):
        started = time.monotonic()
        timeout = (4, 35 if method == 'getUpdates' else 12)
        data = body if body is not None else json.dumps(payload or {}).encode()
        try:
            with self.session().post(self.base + method, data=data,
                                     headers={'Content-Type': content_type}, timeout=timeout,
                                     allow_redirects=False) as response:
                if response.status_code != 200:
                    raise RuntimeError(f'Telegram HTTP {response.status_code}')
                result = response.json()
        except (requests.RequestException, ValueError):
            # Exception URLs include credentials. Only log sanitized messages.
            raise RuntimeError('Telegramga ulanishda xato') from None
        finally:
            if method != 'getUpdates':
                logging.info('telegram method=%s seconds=%.3f', method, time.monotonic() - started)
        if not isinstance(result, dict) or not result.get('ok') or 'result' not in result:
            raise RuntimeError('Telegram so‘rovni qabul qilmadi')
        return result['result']

    def progress(self, chat):
        # Status animation cannot delay downloading or recognizing the file.
        def show():
            try:
                self.request('sendChatAction', {'chat_id': chat, 'action': 'typing'})
            except RuntimeError:
                pass
            finally:
                self.session().close()
                del self.local.session
        threading.Thread(target=show, daemon=True).start()

    def send(self, chat, text, buttons=None):
        markup = {'keyboard': [[{'text': button}] for button in (buttons or [NEW])],
                  'resize_keyboard': True}
        if buttons == []:
            markup = {'remove_keyboard': True}
        # Telegram counts UTF-16 code units; keep headroom for emoji.
        while text:
            chunk, text = text[:1800], text[1800:]
            result = self.request('sendMessage', {'chat_id': chat, 'text': chunk, 'reply_markup': markup})
        return result

    def document(self, chat, path):
        boundary = 'Upload' + uuid.uuid4().hex
        body = (f'--{boundary}\r\nContent-Disposition: form-data; name="chat_id"\r\n\r\n{chat}\r\n'
                f'--{boundary}\r\nContent-Disposition: form-data; name="document"; filename="{path.name}"\r\n'
                f'Content-Type: {"application/pdf" if path.suffix.lower() == ".pdf" else "application/vnd.openxmlformats-officedocument.wordprocessingml.document"}\r\n\r\n').encode()
        body += path.read_bytes() + f'\r\n--{boundary}--\r\n'.encode()
        return self.request('sendDocument', body=body, content_type=f'multipart/form-data; boundary={boundary}')

    def download(self, file_id):
        cached = self.file_cache.get(file_id)
        if cached and time.monotonic() - cached[0] < 900:
            self.file_cache.move_to_end(file_id)
            return cached[1]
        if cached:
            self.cache_size -= len(self.file_cache.pop(file_id)[1])
        info = self.request('getFile', {'file_id': file_id})
        if info.get('file_size', 0) > MAX_BYTES:
            raise ReadError('Fayl hajmi 10 MB dan oshmasin.')
        path = info.get('file_path', '')
        if not re.fullmatch(r'[A-Za-z0-9_./-]+', path) or '..' in path.split('/') or path.startswith('/'):
            raise ReadError('Telegram fayl manzili noto‘g‘ri.')
        token_part = self.base.removeprefix('https://api.telegram.org/bot').rstrip('/')
        url = 'https://api.telegram.org/file/bot' + token_part + '/' + path
        try:
            with self.session().get(url, timeout=(4, 12), stream=True, allow_redirects=False) as response:
                if response.status_code != 200:
                    raise ReadError('Telegram faylini yuklab bo‘lmadi. Qayta yuboring.')
                data = bytearray()
                for chunk in response.iter_content(65536):
                    data.extend(chunk)
                    if len(data) > MAX_BYTES:
                        raise ReadError('Fayl hajmi 10 MB dan oshmasin.')
        except requests.RequestException:
            raise ReadError('Telegram faylini yuklab bo‘lmadi. Qayta yuboring.') from None
        data = bytes(data)
        self.file_cache[file_id] = (time.monotonic(), data)
        self.cache_size += len(data)
        while len(self.file_cache) > 8 or self.cache_size > 32 * 1024 * 1024:
            self.cache_size -= len(self.file_cache.popitem(last=False)[1][1])
        return data


class Bot:
    def __init__(self, api, store, root, allowed, lookup=None, reader=read_document, pdf_exporter=export_pdf,
                 fitter=None):
        self.api, self.store, self.root, self.allowed = api, store, root, allowed
        self.lookup = lookup if lookup is not None else Orginfo(cache_path=root / 'data/orginfo-cache.json').lookup
        self.reader = reader
        self.pdf_exporter = pdf_exporter
        # Shartnoma 2 bet + spetsifikatsiya 1 bet bo‘lishi uchun shrift moslanadi.
        self.fitter = fitter if fitter is not None else (fit_document if pdf_exporter is export_pdf else None)

    def seller_path(self, chat):
        return self.root / 'data' / 'sellers' / f'{int(chat)}.json'

    def seller_for(self, chat):
        path = self.seller_path(chat)
        if not path.exists():
            path = self.root / 'company.json'  # Existing installations only.
        try:
            return validate_company(json.loads(path.read_text()))
        except (OSError, ValueError, TypeError):
            return None

    def preference_path(self, chat):
        return self.root / 'data' / 'preferences' / f'{int(chat)}.json'

    def template_for(self, chat):
        personal = self.root / 'data' / 'templates' / f'{int(chat)}.docx'
        try:
            choice = json.loads(self.preference_path(chat).read_text()).get('template')
        except (OSError, ValueError):
            choice = None
        if personal.exists() and choice != 'ready':
            return personal
        return self.root / 'template.docx'

    def structured(self, chat, template=None):
        template = template or self.template_for(chat)
        if not template.exists():
            return False
        from zipfile import ZipFile
        with ZipFile(template) as z:
            return b'{{item_quantity}}' in z.read('word/document.xml')

    def start_contract(self, chat):
        seller = self.seller_for(chat)
        if not seller:
            session = {'step': 'settings', 'index': 0, 'values': {}, 'resume_start': True}
            self.store.save(chat, session)
            self.api.send(chat, 'Avval sotuvchi — o‘z korxonangizni bir marta sozlaymiz. STIR bo‘yicha ma’lumot qidiraman.')
            self.settings_prompt(chat, session)
            return
        choices = self.template_choices(chat)
        if len(choices) > 1:
            self.store.save(chat, {'step': 'template_pick', 'items': [], 'seller_snapshot': seller})
            self.api.send(chat, 'Shartnoma namunasining qaysi biridan foydalanamiz?',
                          [label for label, _ in choices] + [CANCEL])
            return
        self.store.save(chat, {'step': 'stir', 'items': [], 'seller_snapshot': seller,
                               'structured': self.structured(chat)})
        self.api.send(chat, 'Hamkor korxonaning 9 xonali STIR raqamini kiriting.', [CANCEL])

    def template_choices(self, chat):
        """Namunalar ro‘yxati. Shaxsiy shablon ulangan bo‘lsa tanlov so‘ralmaydi."""
        if self.template_for(chat) != self.root / 'template.docx':
            return []
        return [(label, name) for label, name in CONTRACT_TEMPLATES if self.named_template(name).is_file()]

    def named_template(self, name):
        """Yuklangan shablon data/ ichida (Railway volume), standart nusxa loyiha ildizida."""
        uploaded = self.root / 'data' / name
        return uploaded if uploaded.is_file() else self.root / name

    def session_template(self, chat, s):
        name = s.get('template_file')
        if name in {file for _, file in CONTRACT_TEMPLATES} and self.named_template(name).is_file():
            return self.named_template(name)
        return self.template_for(chat)

    def number_scope(self, chat, seller=None):
        seller = seller or self.seller_for(chat)
        if not seller:
            raise ValueError('Avval sotuvchini /settings orqali kiriting.')
        return f'stir:{seller["stir"]}'

    def confirmation(self, chat, session):
        session['step'] = 'confirm'
        self.store.save(chat, session)
        text = (f'📄 Shartnoma № {session["contract_number"]}\n📅 Sana: {session["contract_date"]}\n\n'
                + company_text(session['buyer']) + '\n\n' + summary(session))
        if session.get('structured'):
            text += f'\nQQS: {session.get("vat_rate", "12")}%'
        self.api.send(chat, text + '\n\nWord va PDF tayyorlansinmi?', [CONFIRM, EDIT_NUMBER, EDIT_DATE, CANCEL])

    def sample_document(self, chat):
        demo = dict(name='SINOV KORXONASI (XAYOLIY)', stir='000000000', director='Sinov Ismi',
                    address='Sinov manzili', bank='Sinov banki', account='00000000000000000000', mfo='00000')
        sample = {'buyer': demo, 'items': [{'name': 'SINOV — sement', 'unit': 'т', 'quantity': '3', 'price': '800000.00'}], 'vat_rate': '12', 'price_mode': 'included', 'demo': True}
        sample['items'][0]['amount'] = str(calculate_item(sample['items'][0])[3])
        sample_path = self.root / 'contracts' / f'SINOV-namuna-{int(chat)}.docx'
        sample_path.parent.mkdir(exist_ok=True)
        date = datetime.now(ZoneInfo('Asia/Tashkent')).strftime('%d.%m.%Y')
        template = self.template_for(chat)
        content = (fill_template(template.read_bytes(), 'SINOV', date, demo, sample) if template.exists()
                   else document_bytes('SINOV', date, demo, sample))
        self.write_document(sample_path, content)
        return sample_path

    def write_document(self, path, content):
        """Save DOCX (fitted to page limits) and, when already rendered, its PDF."""
        pdf = None
        if self.fitter:
            try:
                content, pdf = self.fitter(content)
            except Exception:  # Layout tuning must never block the contract.
                logging.exception('fit failed; original layout used')
                pdf = None
        temp = path.with_suffix('.tmp')
        temp.write_bytes(content)
        temp.replace(path)
        if pdf:
            target = path.with_suffix('.pdf')
            temporary = target.with_suffix('.pdf.tmp')
            temporary.write_bytes(pdf)
            temporary.replace(target)
        else:
            path.with_suffix('.pdf').unlink(missing_ok=True)

    def deliver_pdf(self, chat, path):
        try:
            pdf = self.pdf_exporter(path)
        except ExportError as error:
            logging.warning('pdf export failed: %s', error)
            self.api.send(chat, 'Word tayyor. PDF yaratilmadi; qayta urinish uchun /pdf yuboring.')
            return False
        self.api.document(chat, pdf)
        return True

    def settings_prompt(self, chat, session):
        index = session['index']
        key, label = SETTINGS_FIELDS[index], SETTINGS_LABELS[index]
        current = session['values'].get(key, '')
        text = f'⚙️ Sotuvchi sozlamalari — {index + 1}/{len(SETTINGS_FIELDS)}\n\n{label}ni kiriting.'
        if current:
            text += f'\nHozirgi qiymat: {current}\nSaqlab qolish uchun pastdagi tugmani bosing.'
        if key in OPTIONAL_FIELDS:
            text += '\nKiritmaslik uchun «-» yuboring.'
        self.api.send(chat, text, ([KEEP] if current else []) + [NUMBER_SETTINGS, CANCEL])

    def handle(self, update):
        msg = update.get('message', {})
        if msg.get('chat', {}).get('type') != 'private':
            return
        chat, user = msg['chat']['id'], msg.get('from', {}).get('id')
        text = msg.get('text', '').strip()
        if user not in self.allowed:
            self.api.send(chat, ACCESS_DENIED, [])
            return
        if text == '/id':
            self.api.send(chat, f'Sizning Telegram ID: {user}')
            return
        if text == '/yordam':
            self.api.send(chat, '📄 /start — yangi shartnoma\n⚙️ /settings — sotuvchi sozlamalari\n🏢 /sozlash — rekvizitlarni bir xabarda kiritish\n'
                          '🔢 /raqamlash — keyingi shartnoma raqami\n📑 /shablon — Word shablon ulash\n🏢 /discover — Discover Invest shablonini yuklash\n🧪 /namuna — sinov hujjati\n'
                          '📋 /holat — sozlamalar\n📎 /oxirgi — Word va PDF\n📕 /pdf — PDFni qayta olish\n❌ /bekor — bekor qilish')
            return
        if text == '/holat':
            seller = self.seller_for(chat)
            status = '✅ ' + company_text(seller) if seller else '⏳ Sotuvchi kiritilmagan. /settings yuboring.'
            template = '✅ Word shablon ulangan' if self.template_for(chat).exists() else '📝 Hozir umumiy LOYIHA yaratiladi'
            if seller:
                status += '\n🔢 Keyingi raqam: ' + str(self.store.next_number(self.number_scope(chat, seller)) or 'sozlanmagan — /raqamlash')
            pdf = '📕 PDF: LibreOffice bor' if pdf_available() else '⚠️ PDF: LibreOffice topilmadi'
            self.api.send(chat, status + '\n' + template + '\n' + storage_status(self.root)[1] + '\n' + pdf
                          + '\n📷 Rasm va PDF rekvizitlar o‘qiladi.')
            return
        if text in ('/raqamlash', NUMBER_SETTINGS):
            seller = self.seller_for(chat)
            if not seller:
                self.api.send(chat, 'Avval /settings orqali sotuvchi rekvizitlarini saqlang.', [CANCEL])
                return
            scope = self.number_scope(chat, seller)
            current = self.store.next_number(scope)
            self.store.save(chat, {'step': 'number_settings', 'number_scope': scope})
            self.api.send(chat, f'🔢 {seller["name"]}\nKeyingi raqam: {current or "sozlanmagan"}\n\nNavbatdagi shartnomaga qo‘yiladigan raqamni kiriting. Masalan, oxirgisi 283 bo‘lsa 284 yozing. Har yangi hujjatda raqam va sanani tahrirlash mumkin. Raqamlash shu korxona (STIR) uchun barcha xodimlarga umumiy.', [CANCEL])
            return
        if text == '/settings':
            session = {'step': 'settings', 'index': 0, 'values': self.seller_for(chat) or {}}
            self.store.save(chat, session)
            self.settings_prompt(chat, session)
            return
        if text == '/sozlash':
            self.store.save(chat, {'step': 'seller'})
            self.api.send(chat, 'Sotuvchi rekvizitlarini yuboring (matn, rasm yoki PDF):\n\n'
                          + EXAMPLE.format(stir='123456789') + '\n\nBu namuna, haqiqiy rekvizitlaringizni kiriting.', [CANCEL])
            return
        if text == '/shablon':
            self.store.save(chat, {'step': 'template'})
            if self.template_for(chat).exists():
                self.api.document(chat, self.template_for(chat))
            self.api.send(chat, 'Shartnoma .docx faylini yuboring. Majburiy maydonlar:\n'
                          '{{number}}, {{date}}, {{seller_name}}, {{buyer_name}}, {{items}}, {{total}}\n\n'
                          'Rekvizitlar: {{seller_stir}}, {{seller_director}}, {{seller_address}}, '
                          '{{seller_bank}}, {{seller_account}}, {{seller_mfo}}. '
                          'Xaridor uchun seller o‘rniga buyer yoziladi.\n'
                          'Shablonni ulashdan oldin barcha shartlarini o‘zingiz tekshiring.', [CANCEL])
            return
        if text == '/discover':
            self.store.save(chat, {'step': 'template', 'target': DISCOVER_FILE})
            if self.named_template(DISCOVER_FILE).exists():
                self.api.document(chat, self.named_template(DISCOVER_FILE))
            self.api.send(chat, 'Discover Invest shartnomasining maydonli .docx shablonini yuboring. '
                          'U barcha adminlar uchun «🏢 Discover Invest shartnomasi» tugmasi bilan chiqadi.', [CANCEL])
            return
        if text == '/namuna':
            sample_path = self.sample_document(chat)
            self.api.document(chat, sample_path)
            self.deliver_pdf(chat, sample_path)
            self.api.send(chat, '🧪 Sinov fayli yuborildi. Ma’lumotlar xayoliy, haqiqiy shartnoma emas. '
                          'O‘z korxonangizni /settings orqali kiriting.')
            return
        if text in ('/start', '/yangi', NEW):
            if self.template_for(chat).exists() and not self.preference_path(chat).exists():
                self.store.save(chat, {'step': 'template_choice'})
                self.api.document(chat, self.sample_document(chat))
                self.api.send(chat, 'Yuqoridagi hujjat xayoliy ma’lumotlar bilan to‘ldirilgan SINOV namunasi. Shartnoma shablonini bir marta tanlang. Tayyor namunamizdan foydalanasizmi yoki o‘z shartnomangizni ulaysizmi? Namuna ko‘rish: /namuna', [READY, CUSTOM, CANCEL])
            else:
                self.start_contract(chat)
            return
        if text in ('/bekor', CANCEL):
            self.store.clear(chat)
            self.api.send(chat, 'Bekor qilindi.')
            return
        if text in ('/oxirgi', '/pdf'):
            path = self.store.last_file(chat)
            if path and path.is_file():
                if text == '/oxirgi':
                    self.api.document(chat, path)
                completed = self.deliver_pdf(chat, path)
                session = self.store.session(chat)
                if completed and session and session.get('step') == 'delivery' and session.get('file') == str(path) and session.get('word_sent'):
                    self.store.clear(chat)
            else:
                self.api.send(chat, 'Saqlangan shartnoma topilmadi.')
            return
        s = self.store.session(chat)
        if not s:
            self.api.send(chat, 'Boshlash uchun yangi shartnomani tanlang.')
            return
        if msg.get('photo') or msg.get('document'):
            self.handle_file(chat, s, msg)
            return
        if not text or len(text) > 3500:
            self.api.send(chat, 'Matn, rekvizitlar rasmi yoki PDF yuboring.', [CANCEL])
            return
        if s['step'] in ('buyer', 'buyer_confirm') and re.fullmatch(r'[0-9]{9}', text):
            # A new bare STIR restarts partner lookup, not requisites parsing.
            # Never carry the previous company's fields into the new result.
            s = {'step': 'stir', 'stir': text, 'items': [], 'seller_snapshot': s.get('seller_snapshot'), 'structured': s.get('structured', False)}
            self.store.save(chat, s)
        try:
            self.advance(chat, s, text)
        except ValueError as error:
            self.api.send(chat, str(error), [CANCEL])

    def accept_fields(self, chat, s, fields):
        expected = s.get('stir') if s['step'] == 'buyer' else None
        if expected and fields.get('stir') and fields['stir'] != expected:
            raise ValueError('⚠️ Hujjatdagi STIR kiritilgan STIRdan farq qiladi. Rekvizitlarni tekshiring.')
        merged = dict(s.get('prefill', {}))
        merged.update(fields)
        missing = [label for key, label in zip(FIELDS, LABELS) if not merged.get(key)]
        if missing:
            s['prefill'] = merged
            self.store.save(chat, s)
            self.api.send(chat, company_text(merged) + '\n\nQuyidagi maydonlarni «Maydon: qiymat» shaklida yuboring: '
                          + ', '.join(missing), [CANCEL])
            return
        company = validate_company(merged, expected)
        key = 'seller' if s['step'] == 'seller' else 'buyer'
        s[key], s['step'] = company, key + '_confirm'
        self.store.save(chat, s)
        self.api.send(chat, company_text(company) + '\n\n⚠️ Hisob, MFO va STIRni diqqat bilan tekshiring. Tasdiqlaysizmi?', [CONFIRM, CANCEL])

    def handle_file(self, chat, s, msg):
        if s['step'] not in ('buyer', 'buyer_confirm', 'seller', 'template'):
            self.api.send(chat, 'Hozir fayl kutilmayapti. Rekvizitlarni kiritish bosqichida yuboring.', [CANCEL])
            return
        if s['step'] == 'buyer_confirm':
            s['step'], s['prefill'] = 'buyer', dict(s['buyer'])
        attachment = msg.get('document') or msg['photo'][-1]
        try:
            if attachment.get('file_size', 0) > MAX_BYTES:
                raise ReadError('Fayl hajmi 10 MB dan oshmasin.')
            if s['step'] == 'template' and not attachment.get('file_name', '').lower().endswith('.docx'):
                raise ValueError('Shablon uchun .docx Word faylini yuboring.')
            started = time.monotonic()
            if hasattr(self.api, 'progress'):
                self.api.progress(chat)
            data = self.api.download(attachment['file_id'])
            downloaded = time.monotonic()
            if s['step'] == 'template':
                inspect_template(data)
                if s.get('target') == DISCOVER_FILE:
                    dest = self.root / 'data' / DISCOVER_FILE
                    tmp = dest.with_suffix('.tmp')
                    tmp.write_bytes(data)
                    tmp.replace(dest)
                    self.store.clear(chat)
                    self.api.send(chat, '✅ Discover Invest shabloni saqlandi. /start bosilganda namuna tanlanadi.')
                    return
                dest = self.root / 'data' / 'templates' / f'{int(chat)}.docx'
                dest.parent.mkdir(parents=True, exist_ok=True)
                tmp = dest.with_suffix('.tmp')
                tmp.write_bytes(data)
                tmp.replace(dest)
                write_json(self.preference_path(chat), {'template': 'custom'})
                self.store.clear(chat)
                self.api.send(chat, '✅ Shaxsiy shabloningiz saqlandi. Keyingi shartnomalar shu shablonda bo‘ladi.')
                if s.get('resume_start'):
                    self.start_contract(chat)
            else:
                import hashlib
                folder = self.root / 'data' / 'uploads' / str(int(chat))
                folder.mkdir(parents=True, exist_ok=True)
                folder.chmod(0o700)
                extension = '.pdf' if data.startswith(b'%PDF-') else '.png' if data.startswith(b'\x89PNG') else '.jpg' if data.startswith(b'\xff\xd8') else '.bin'
                saved = folder / (datetime.now(ZoneInfo('Asia/Tashkent')).strftime('%Y%m%d-%H%M%S-') + uuid.uuid4().hex[:12] + extension)
                saved.write_bytes(data)
                saved.chmod(0o600)
                write_json(saved.with_suffix(saved.suffix + '.json'), {'chat_id': chat, 'step': s['step'], 'stir': s.get('stir'), 'sha256': hashlib.sha256(data).hexdigest()})
                fields = extract_fields(self.reader(data, self.root))
                recognized = time.monotonic()
                logging.info('file download=%.3f ocr=%.3f total=%.3f',
                             downloaded - started, recognized - downloaded, recognized - started)
                if not fields:
                    raise ReadError('Rekvizitlar aniqlanmadi. Aniqroq rasm yoki matn yuboring.')
                self.accept_fields(chat, s, fields)
                logging.info('file response_total=%.3f', time.monotonic() - started)
        except ValueError as error:
            self.api.send(chat, str(error), [CANCEL])

    def advance(self, chat, s, text):
        step = s['step']
        if step == 'number_settings':
            value = contract_number(text)
            if self.store.number_used(s['number_scope'], value):
                raise ValueError('Bu raqam avval ishlatilgan. Boshqa raqam kiriting.')
            s.update(step='number_settings_confirm', next_number=value)
            self.store.save(chat, s)
            self.api.send(chat, f'Keyingi shartnoma № {value} bo‘lsinmi? Keyingilari avtomatik davom etadi.', [CONFIRM, CANCEL])
            return
        if step == 'number_settings_confirm':
            if text != CONFIRM:
                raise ValueError('Tasdiqlang yoki /bekor yuboring.')
            self.store.set_next_number(s['number_scope'], s['next_number'])
            self.store.clear(chat)
            self.api.send(chat, f'✅ Keyingi raqam {s["next_number"]} qilib saqlandi. O‘zgartirish: /settings → Raqamlash sozlamalari. Sana har hujjat oldidan tasdiqlanadi yoki tahrirlanadi.')
            return
        if step in ('contract_number', 'edit_number'):
            number = contract_number(text)
            if self.store.number_used(s['number_scope'], number):
                raise ValueError('Bu raqam shu korxona uchun avval ishlatilgan. Boshqa raqam kiriting.')
            s['contract_number'] = number
            if step == 'contract_number':
                s['step'] = 'contract_date'
                self.store.save(chat, s)
                self.api.send(chat, 'Shartnoma sanasini KK.OO.YYYY shaklida kiriting yoki bugungi sanani tanlang.', [TODAY, CANCEL])
            else:
                self.confirmation(chat, s)
            return
        if step in ('contract_date', 'edit_date'):
            value = datetime.now(ZoneInfo('Asia/Tashkent')).strftime('%d.%m.%Y') if text == TODAY else text
            s['contract_date'] = contract_date(value)
            self.confirmation(chat, s)
            return
        if step == 'template_pick':
            chosen = dict(CONTRACT_TEMPLATES).get(text)
            if not chosen or not self.named_template(chosen).is_file():
                raise ValueError('Pastdagi tugmalardan shartnoma namunasini tanlang.')
            s.update(step='stir', template_file=chosen, structured=self.structured(chat, self.named_template(chosen)))
            self.store.save(chat, s)
            self.api.send(chat, f'{text} tanlandi.\nHamkor korxonaning 9 xonali STIR raqamini kiriting.', [CANCEL])
            return
        if step == 'template_choice':
            if text == READY:
                write_json(self.preference_path(chat), {'template': 'ready'})
                self.start_contract(chat)
                return
            if text == CUSTOM:
                self.store.save(chat, {'step': 'template', 'resume_start': True})
                self.api.document(chat, self.root / 'template.docx')
                self.api.send(chat, 'O‘z shartnomangizning botga moslangan .docx shablonini yuboring. Moslash uchun hozir yuborilgan maydonli Word faylini asos qilib oling: {{number}}, {{date_long}}, {{seller_name}}, {{buyer_name}}, {{total}} va tovar jadvalidagi {{item_name}} kabi maydonlarni saqlang. Oddiy to‘ldirilmagan Word o‘rniga shu maydonli shablon kerak. Bir marta ulaysiz. Batafsil: /shablon', [CANCEL])
                return
            raise ValueError('Tayyor yoki shaxsiy shablonni tanlang.')
        if step == 'settings':
            key = SETTINGS_FIELDS[s['index']]
            if text == KEEP:
                if not s['values'].get(key):
                    raise ValueError('Hali qiymat kiritilmagan.')
                value = s['values'][key]
            else:
                value = text.strip()
                if key in OPTIONAL_FIELDS and value == '-':
                    value = ''
                if key in ('stir', 'account', 'mfo', 'oked'):
                    value = re.sub(r'\s', '', value)
                    length = {'stir': 9, 'account': 20, 'mfo': 5, 'oked': 5}[key]
                    if not (key == 'oked' and not value) and not re.fullmatch(r'[0-9]{' + str(length) + '}', value):
                        raise ValueError(f'{SETTINGS_LABELS[s["index"]]} {length} ta raqam bo‘lishi kerak.')
                elif not value or len(value) > (40 if key == 'phone' else 500):
                    if not (key == 'phone' and value == ''):
                        raise ValueError('Qiymat bo‘sh yoki juda uzun. Qayta kiriting.')
            if key == 'stir' and value != s['values'].get('stir'):
                s['values'] = {'stir': value}
                try:
                    found = self.lookup(value)
                except LookupUnavailable as error:
                    found = None
                    self.api.send(chat, str(error) + '\nMa’lumotlarni qo‘lda kiritishingiz mumkin.', [CANCEL])
                if found:
                    if found.get('stir', value) != value:
                        raise ValueError('Manbadagi STIR mos kelmadi.')
                    s['values'].update({k: str(found[k]) for k in SETTINGS_FIELDS if found.get(k)})
                    if found.get('cache_status') == 'stale':
                        self.api.send(chat, '⚠️ Orginfo hozir javob bermadi. Oldin saqlangan ma’lumot topildi; eskirmaganini tekshiring.', [CANCEL])
                    self.api.send(chat, 'Orginfo’dan topildi. Har bir maydonni tekshirib tasdiqlang.\n' + company_text(s['values']) + '\nManba: ' + found.get('source_url', 'https://orginfo.uz'), [CANCEL])
            s['values'][key] = value
            s['index'] += 1
            if s['index'] < len(SETTINGS_FIELDS):
                self.store.save(chat, s)
                self.settings_prompt(chat, s)
            else:
                s['seller'] = validate_company(s['values'])
                s['step'] = 'seller_confirm'
                self.store.save(chat, s)
                self.api.send(chat, company_text(s['seller']) + '\n\nBu sotuvchi faqat sizning sozlamangizda saqlansinmi?', [CONFIRM, CANCEL])
            return
        elif step == 'seller':
            fields = extract_fields(text)
            if not fields:
                raise ValueError('Rekvizitlarni «Nomi: ...», «STIR: ...» shaklida yuboring.')
            self.accept_fields(chat, s, fields)
            return
        elif step == 'seller_confirm':
            if text != CONFIRM:
                raise ValueError('Tasdiqlash tugmasini bosing yoki /bekor yuboring.')
            write_json(self.seller_path(chat), s['seller'])
            self.store.clear(chat)
            self.api.send(chat, '✅ Sotuvchi rekvizitlaringiz saqlandi. O‘zgartirish: /settings. Yangi shartnoma: /start')
            if s.get('resume_start'):
                self.start_contract(chat)
            return
        elif step == 'template':
            raise ValueError('Shablon uchun .docx Word faylini yuboring yoki /bekor yozing.')
        elif step == 'stir':
            if not re.fullmatch(r'[0-9]{9}', text):
                raise ValueError('STIR aynan 9 ta raqamdan iborat bo‘lishi kerak.')
            s['stir'] = text
            company_file = self.root / 'data/companies.json'
            companies = json.loads(company_file.read_text()) if company_file.exists() else {}
            if text in companies:
                s['buyer'] = validate_company(companies[text], text)
                s['step'] = 'buyer_confirm'
                reply, buttons = company_text(s['buyer']) + '\n\nMa’lumotlar to‘g‘rimi?', [CONFIRM, CANCEL]
            else:
                s['step'] = 'buyer'
                reason = 'Orginfo’da topilmadi.'
                try:
                    found = self.lookup(text)
                except LookupUnavailable as error:
                    found, reason = None, str(error)
                if found:
                    s['prefill'] = found
                    missing = [label for key, label in zip(FIELDS, LABELS) if not found.get(key)]
                    if not missing:
                        s['buyer'] = validate_company(found, text)
                        s['step'] = 'buyer_confirm'
                    origin = '✅ Orginfo’dan topildi:'
                    if found.get('cache_status') in ('cached', 'stale'):
                        stamp = datetime.fromtimestamp(found['retrieved_at'], ZoneInfo('Asia/Tashkent')).strftime('%d.%m.%Y %H:%M')
                        origin = f'📋 Orginfo’dan oldin olingan ma’lumot ({stamp}):'
                        if found['cache_status'] == 'stale':
                            origin += '\n⚠️ Orginfo hozir javob bermadi. Saqlangan rekvizitlarni tekshiring.'
                    reply = (origin + '\n' + company_text(found)
                             + '\nManba: ' + found['source_url']
                             + '\n\n📷 Rekvizitlar rasmi yoki PDF yuborishingiz mumkin.\n'
                             + 'Quyidagi yetishmagan maydonlarni '
                             '«Maydon: qiymat» shaklida yuboring: ' + ', '.join(missing)
                             + '\nMasalan:\nBank: Bank nomi\nHisob: 20208000000000000001\nMFO: 00450'
                             + '\nBoshqa maydonlarni ham shu usulda tuzatish mumkin.')
                else:
                    reply = (reason + '\nRekvizitlarni qo‘lda shu shaklda yuboring:\n\n'
                             + EXAMPLE.format(stir=text)
                             + '\n\nBoshqa STIRni tekshirish uchun yangi 9 xonali raqam yuboring.')
                if s['step'] == 'buyer_confirm':
                    reply = company_text(s['buyer']) + '\nManba: ' + found.get('source_url', 'https://orginfo.uz') + '\n\nMa’lumotlar to‘g‘rimi?'
                    buttons = [CONFIRM, CANCEL]
                else:
                    buttons = [CANCEL]
        elif step == 'buyer':
            fields = extract_fields(text)
            if not fields:
                raise ValueError('Rekvizitlarni «Bank: ...», «Hisob: ...» shaklida yuboring.')
            self.accept_fields(chat, s, fields)
            return
        elif step == 'buyer_confirm':
            if text != CONFIRM:
                fields = extract_fields(text)
                if not fields:
                    raise ValueError('Tasdiqlash tugmasini bosing yoki rekvizitlarni «Maydon: qiymat» shaklida tuzating.')
                s['step'], s['prefill'] = 'buyer', dict(s['buyer'])
                self.accept_fields(chat, s, fields)
                return
            s['step'] = 'vat_rate' if s.get('structured') else 'item'
            if s.get('structured'):
                self.store.save(chat, s)
                self.api.send(chat, 'QQS stavkasini tanlang.', [VAT12, VAT0, VAT_OTHER, CANCEL])
                return
            reply, buttons = ('Tovar nomini kiriting.\nMiqdor kerak bo‘lsa: Nom | birlik | miqdor\n'
                              'Masalan: Цемент М 400 | т | 3', [CANCEL])
        elif step in ('vat_rate', 'vat_custom'):
            if text == VAT_OTHER:
                s['step'] = 'vat_custom'
                reply, buttons = 'QQS stavkasini foizda kiriting (0–100). Masalan: 12', [CANCEL]
            else:
                value = '12' if text == VAT12 else '0' if text == VAT0 else text.replace(',', '.')
                if not re.fullmatch(r'\d{1,3}(?:\.\d{1,2})?', value) or not 0 <= Decimal(value) <= 100:
                    raise ValueError('QQS stavkasini 0–100 oralig‘ida kiriting.')
                s['vat_rate'] = value
                s['step'] = 'price_mode' if Decimal(value) else 'item'
                s['price_mode'] = 'included'
                reply, buttons = ('Kiritadigan bir birlik narxingiz QQS bilanmi yoki QQSsizmi?', [INCLUDED, EXCLUDED, CANCEL]) if Decimal(value) else ('Tovar nomini kiriting.', [CANCEL])
        elif step == 'price_mode':
            if text not in (INCLUDED, EXCLUDED):
                raise ValueError('Narx QQS bilan yoki QQSsiz tugmasini bosing.')
            s['price_mode'] = 'included' if text == INCLUDED else 'excluded'
            s['step'] = 'item'
            reply, buttons = 'Tovar nomini kiriting.', [CANCEL]
        elif step == 'unit':
            if len(text) > 20:
                raise ValueError('Birlik 20 belgidan oshmasin. Masalan: dona, т, кг, м².')
            s['pending_unit'], s['step'] = text, 'quantity'
            reply, buttons = 'Miqdorni kiriting. Masalan: 3 yoki 2.5', [CANCEL]
        elif step == 'quantity':
            quantity = text.replace(',', '.')
            if not re.fullmatch(r'[0-9]{1,12}(?:\.[0-9]{1,6})?', quantity) or Decimal(quantity) <= 0:
                raise ValueError('Miqdor 0 dan katta son bo‘lsin (6 ta kasrgacha).')
            s['pending_quantity'], s['step'] = quantity, 'price'
            kind = 'QQS bilan' if s.get('price_mode') == 'included' and Decimal(s['vat_rate']) else 'QQSsiz'
            reply, buttons = f'Bir birlik narxini so‘mda kiriting ({kind}). Jami summani emas, bir birlik narxini yozing.', [CANCEL]
        elif step == 'price':
            item = {'name': s['pending_item'], 'unit': s['pending_unit'], 'quantity': s['pending_quantity'], 'price': amount(text)}
            unit, net, vat, gross = calculate_item(item, s['vat_rate'], s['price_mode'])
            item['amount'] = str(gross)
            candidate = dict(s, items=s['items'] + [item])
            from contract_values import build_values
            build_values('0', '01.01.2026', {}, dict(candidate, buyer={}))
            s['items'].append(item)
            for key in ('pending_item', 'pending_unit', 'pending_quantity'):
                s.pop(key, None)
            s['step'] = 'items'
            reply = summary(s) + f'\nBirlik narxi QQSsiz: {money(unit)}\nQQSsiz summa: {money(net)}\nQQS: {money(vat)}'
            buttons = [ADD, NEXT, CANCEL]
        elif step == 'item':
            if len(text) > 200:
                raise ValueError('Tovar nomi 200 belgidan oshmasin.')
            if s.get('structured'):
                s['pending_item'], s['step'] = text, 'unit'
                self.store.save(chat, s)
                self.api.send(chat, 'O‘lchov birligini kiriting. Masalan: dona, т, кг, м²', [CANCEL])
                return
            pieces = [piece.strip() for piece in text.split('|')]
            if len(pieces) not in (1, 3) or any(not piece for piece in pieces):
                raise ValueError('Tovar nomini yoki «Nom | birlik | miqdor» shaklini yuboring.')
            if len(pieces) == 3:
                quantity = pieces[2].replace(',', '.')
                if not re.fullmatch(r'[0-9]{1,12}(?:\.[0-9]{1,6})?', quantity) or Decimal(quantity) <= 0:
                    raise ValueError('Miqdor 0 dan katta son bo‘lsin. Masalan: Цемент М 400 | т | 3')
                s['pending_unit'], s['pending_quantity'] = pieces[1], quantity
            s['pending_item'], s['step'] = pieces[0], 'amount'
            reply, buttons = 'Shu tovar bo‘yicha jami summani so‘mda kiriting (QQS bilan yakuniy summa).', [CANCEL]
        elif step == 'amount':
            value = amount(text)
            item = {'name': s.pop('pending_item'), 'amount': value}
            if 'pending_quantity' in s:
                item.update(quantity=s.pop('pending_quantity'), unit=s.pop('pending_unit'))
            s['items'].append(item)
            s['step'] = 'items'
            reply, buttons = summary(s), [ADD, NEXT, CANCEL]
        elif step == 'items':
            if text == ADD and len(s['items']) < 20:
                s['step'] = 'item'
                reply, buttons = 'Keyingi tovar nomini kiriting.', [CANCEL]
            elif text == NEXT:
                s['number_scope'] = self.number_scope(chat, s.get('seller_snapshot'))
                next_number = self.store.next_number(s['number_scope'])
                s['contract_date'] = datetime.now(ZoneInfo('Asia/Tashkent')).strftime('%d.%m.%Y')
                if next_number is None:
                    s['step'] = 'contract_number'
                    self.store.save(chat, s)
                    self.api.send(chat, 'Navbatdagi shartnoma raqamini kiriting. Masalan, oxirgisi 283 bo‘lsa 284 yozing. Keyingi hujjatlarda raqam avtomatik davom etadi.', [CANCEL])
                else:
                    s['contract_number'] = next_number
                    self.confirmation(chat, s)
                return
            else:
                raise ValueError('Davom etish yoki yana tovar tugmasini bosing. Ko‘pi bilan 20 ta tovar.')
        elif step in ('confirm', 'delivery'):
            if step == 'confirm' and 'contract_number' not in s:
                s['number_scope'] = self.number_scope(chat, s.get('seller_snapshot'))
                proposed = self.store.next_number(s['number_scope'])
                s['contract_date'] = datetime.now(ZoneInfo('Asia/Tashkent')).strftime('%d.%m.%Y')
                if proposed is None:
                    s['step'] = 'contract_number'
                    self.store.save(chat, s)
                    self.api.send(chat, 'Avval navbatdagi shartnoma raqamini kiriting.', [CANCEL])
                else:
                    s['contract_number'] = proposed
                    self.confirmation(chat, s)
                return
            if step == 'confirm' and text in (EDIT_NUMBER, EDIT_DATE):
                s['step'] = 'edit_number' if text == EDIT_NUMBER else 'edit_date'
                self.store.save(chat, s)
                self.api.send(chat, 'Yangi shartnoma raqamini kiriting.' if text == EDIT_NUMBER else 'Sanani KK.OO.YYYY shaklida kiriting.', [CANCEL] if text == EDIT_NUMBER else [TODAY, CANCEL])
                return
            if text != CONFIRM:
                raise ValueError('Tasdiqlash tugmasini bosing yoki /bekor yuboring.')
            if step == 'confirm':
                seller = s.get('seller_snapshot') or self.seller_for(chat)
                if not seller:
                    raise ValueError('Sotuvchi rekvizitlarini /settings orqali kiriting. Sinov fayli uchun /namuna.')
                seller = validate_company(seller)
                number, date = self.store.create_contract(chat, s)
                path = self.root / 'contracts' / f'shartnoma-{number:06d}.docx'
                path.parent.mkdir(exist_ok=True)
                template = self.session_template(chat, s)
                content = (fill_template(template.read_bytes(), s.get('contract_number', number), date, seller, s) if template.exists()
                           else document_bytes(s.get('contract_number', number), date, seller, s))
                if hasattr(self.api, 'progress'):
                    self.api.progress(chat)
                self.write_document(path, content)
                self.store.set_file(number, path)
                s.update(step='delivery', file=str(path), word_sent=False)
                self.store.save(chat, s)
            if not s.get('word_sent'):
                self.api.document(chat, Path(s['file']))
                s['word_sent'] = True
                self.store.save(chat, s)
            pdf_sent = self.deliver_pdf(chat, Path(s['file']))
            if not pdf_sent:
                return
            self.store.clear(chat)
            self.api.send(chat, '✅ Word va PDF tayyor, papkaga saqlandi. Qayta olish: /oxirgi')
            return
        else:
            raise ValueError('Suhbatni /start orqali qayta boshlang.')
        self.store.save(chat, s)
        self.api.send(chat, reply, buttons)


def main():
    # A second polling process would cause Telegram 409 conflicts.
    import fcntl
    # Railway: data/ — doimiy volume; Docker'da contracts/ unga havola.
    (ROOT / 'data' / 'contracts').mkdir(parents=True, exist_ok=True)
    lock = (ROOT / 'data/bot.lock').open('w')
    try:
        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
    except BlockingIOError:
        raise SystemExit('Bot allaqachon ishga tushgan.') from None
    load_env(ROOT / '.env')
    token = os.getenv('BOT_TOKEN', '')
    if not re.fullmatch(r'\d+:[A-Za-z0-9_-]+', token):
        raise SystemExit('.env ichiga BotFather bergan BOT_TOKENni kiriting.')
    try:
        allowed = {int(value.strip()) for value in os.getenv('ALLOWED_USER_IDS', '').split(',') if value.strip()}
    except ValueError:
        raise SystemExit('ALLOWED_USER_IDS faqat vergul bilan ajratilgan raqamlar bo‘lsin.') from None
    api, store = Telegram(token), Store(ROOT / 'data/bot.sqlite3')
    bot = Bot(api, store, ROOT, allowed)
    logging.basicConfig(level=logging.INFO, format='%(asctime)s %(levelname)s %(message)s')
    logging.info('Bot ishga tushdi. To‘xtatish: Ctrl+C')
    persistent, message = storage_status(ROOT)
    (logging.info if persistent else logging.warning)('%s', message)
    logging.info('PDF: %s', 'LibreOffice bor' if pdf_available() else 'LibreOffice topilmadi')
    try:
        while True:
            try:
                updates = api.request('getUpdates', {'offset': store.offset(), 'timeout': 30,
                                                     'allowed_updates': ['message']})
                for update in updates:
                    try:
                        bot.handle(update)
                    except RuntimeError:
                        # State was saved before sending. Do not replay user input
                        # into the next step when a reply/upload failed.
                        logging.warning('Xabar yuborilmadi. Suhbat saqlandi; fayl uchun /oxirgi yuboring.')
                    except (OSError, sqlite3.Error, json.JSONDecodeError):
                        logging.error('Sozlamalar yoki saqlash xatosi. Mahalliy fayllarni tekshiring.')
                    store.offset(update['update_id'] + 1)
            except RuntimeError as error:
                logging.warning('%s. 5 soniyadan keyin qayta uriniladi.', error)
                time.sleep(5)
            except (OSError, sqlite3.Error, json.JSONDecodeError):
                logging.error('Mahalliy fayl yoki baza xatosi. Sozlamalarni tekshiring.')
                time.sleep(5)
    except KeyboardInterrupt:
        logging.info('Bot to‘xtatildi.')


if __name__ == '__main__':
    main()
