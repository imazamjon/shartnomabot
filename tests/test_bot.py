import io
import json
import tempfile
import unittest
from pathlib import Path
from xml.etree import ElementTree
from zipfile import ZipFile

from bot import (ACCESS_DENIED, ADD, CANCEL, CONFIRM, NEW, NEXT, Bot, Store, amount,
                 document_bytes, parse_company, validate_company)

COMPANY = dict(name='Misol & Hamkor MCHJ', stir='123456789', director='Ism Familiya',
               address='Toshkent', bank='Misol bank', account='20208000000000000001', mfo='00450')
TEXT = '\n'.join(f'{label}: {COMPANY[key]}' for key, label in [
    ('name', 'Nomi'), ('stir', 'STIR'), ('director', 'Direktor'), ('address', 'Manzil'),
    ('bank', 'Bank'), ('account', 'Hisob'), ('mfo', 'MFO')])


class FakeAPI:
    def __init__(self):
        self.messages, self.files, self.buttons = [], [], []
        self.pdf_files = []
        self.fail_upload = False

    def send(self, chat, text, buttons=None):
        self.messages.append(text)
        self.buttons.append(buttons)

    def document(self, chat, path):
        if self.fail_upload:
            raise RuntimeError('Temporary upload failure')
        (self.pdf_files if path.suffix == '.pdf' else self.files).append(path.read_bytes())


def fake_pdf(path):
    pdf=path.with_suffix('.pdf');pdf.write_bytes(b'%PDF-1.4 test');return pdf


class Tests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        (self.root / 'data').mkdir()
        (self.root / 'data/companies.json').write_text('{}')
        (self.root / 'company.json').write_text(json.dumps(COMPANY))
        self.store = Store(self.root / 'data/test.sqlite3')
        self.api = FakeAPI()
        self.bot = Bot(self.api, self.store, self.root, {7}, lookup=lambda stir: None, pdf_exporter=fake_pdf)
        self.store.set_next_number('stir:123456789', 1)

    def tearDown(self):
        self.store.db.close()
        self.temp.cleanup()

    def send(self, text, user=7):
        self.bot.handle({'message': {'chat': {'id': user, 'type': 'private'},
                                    'from': {'id': user}, 'text': text}})

    def prepare(self):
        for text in [NEW, COMPANY['stir'], TEXT, CONFIRM, 'Kran <katta>', '0.10',
                     ADD, 'Rakovina', '0,20', NEXT]:
            self.send(text)

    def test_full_flow_and_exact_total(self):
        self.prepare()
        self.assertIn('0.30 so‘m', self.api.messages[-1])
        self.send(CONFIRM)
        self.assertEqual(len(self.api.files), 1)
        self.assertIsNone(self.store.session(7))
        with ZipFile(io.BytesIO(self.api.files[0])) as archive:
            for path in archive.namelist():
                ElementTree.fromstring(archive.read(path))
            xml = archive.read('word/document.xml').decode()
            self.assertIn('Kran &lt;katta&gt;', xml)
            self.assertIn('0.30', xml)
        self.send('/oxirgi')
        self.assertEqual(len(self.api.files), 2)

    def test_upload_retry_reuses_number(self):
        self.prepare()
        self.api.fail_upload = True
        with self.assertRaises(RuntimeError):
            self.send(CONFIRM)
        self.assertEqual(self.store.session(7)['step'], 'delivery')
        self.api.fail_upload = False
        self.send(CONFIRM)
        self.assertEqual(self.store.db.execute('SELECT COUNT(*) FROM contracts').fetchone()[0], 1)

    def test_invalid_amount_does_not_advance(self):
        for text in [NEW, COMPANY['stir'], TEXT, CONFIRM, 'Kran', '-10']:
            self.send(text)
        self.assertEqual(self.store.session(7)['step'], 'amount')
        self.assertEqual(self.store.session(7)['items'], [])

    def test_stir_mismatch(self):
        with self.assertRaisesRegex(ValueError, 'farq'):
            parse_company(TEXT, '987654321')

    def test_validation(self):
        for value in ['nan', 'inf', '0', '-1', '1.234', '1e9', '1000000000000']:
            with self.assertRaises(ValueError, msg=value):
                amount(value)
        self.assertEqual(amount('27 000 000,50'), '27000000.50')
        with self.assertRaises(ValueError):
            validate_company({**COMPANY, 'account': '123'})

    def test_access_and_cancel(self):
        self.send(NEW, user=8)
        self.assertIsNone(self.store.session(8))
        self.send(NEW)
        self.send(CANCEL)
        self.assertIsNone(self.store.session(7))

    def test_every_command_denied_for_non_admin(self):
        for text in ['/start', '/id', '/oxirgi', '/sozlash', '/shablon', '/namuna', '/holat', '/yordam', NEW, CONFIRM, '123456789']:
            self.send(text, user=8)
            self.assertEqual(self.api.messages[-1], ACCESS_DENIED)
            self.assertEqual(self.api.buttons[-1], [])
            self.assertIsNone(self.store.session(8))
        self.assertFalse(self.api.files)

    def test_persistence_and_numbering(self):
        self.prepare()
        other = Store(self.root / 'data/test.sqlite3')
        self.assertEqual(other.session(7)['step'], 'confirm')
        other.db.close()
        self.send(CONFIRM)
        self.prepare()
        self.send(CONFIRM)
        self.assertEqual(self.store.last_file(7).parent.name, '000002')
        self.assertTrue(self.store.last_file(7).name.startswith('Shartnoma №'))

    def test_local_lookup(self):
        (self.root / 'data/companies.json').write_text(json.dumps({COMPANY['stir']: COMPANY}))
        self.send(NEW)
        self.send(COMPANY['stir'])
        self.assertEqual(self.store.session(7)['step'], 'buyer_confirm')


if __name__ == '__main__':
    unittest.main()
