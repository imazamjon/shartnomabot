import io
import json
import unittest
from pathlib import Path
from xml.etree import ElementTree as ET
from zipfile import ZipFile, ZIP_DEFLATED

import test_bot
from bot import Bot, CONFIRM, NEW, ADD, NEXT, document_bytes
from ocr import extract_fields, read_document, ReadError, MAX_BYTES
from templates import inspect_template, fill_template, W

ROOT = Path(__file__).resolve().parents[1]
FIXTURES = Path(__file__).parent / 'fixtures'


def make_template():
    base = document_bytes(1, '01.01.2026', test_bot.COMPANY,
                          {'buyer': test_bot.COMPANY, 'items': [{'name': 'Sinov', 'amount': '1.00'}]})
    with ZipFile(io.BytesIO(base)) as archive:
        parts = {n: archive.read(n) for n in archive.namelist()}
    tree = ET.fromstring(parts['word/document.xml'])
    body = tree.find(W + 'body')
    for child in list(body):
        if child.tag != W + 'sectPr':
            body.remove(child)
    for text in ['{{number}} {{date}}', '{{seller_name}}', '{{buyer_name}}', '{{items}}', '{{total}}']:
        p = ET.Element(W + 'p')
        # Test placeholders split across Word runs.
        for chunk in [text[:4], text[4:]]:
            t = ET.SubElement(ET.SubElement(p, W + 'r'), W + 't'); t.text = chunk
        body.insert(len(body) - 1, p)
    parts['word/document.xml'] = ET.tostring(tree)
    out = io.BytesIO()
    with ZipFile(out, 'w', ZIP_DEFLATED) as archive:
        for name, data in parts.items():
            archive.writestr(name, data)
    return out.getvalue()


class FileTests(unittest.TestCase):
    def test_russian_and_spaced_numbers(self):
        fields = extract_fields('ИНН: 123 456 789\nМФО: 00 450\nр/с: 20208 00000 00000 00001\nБанк: Мисол банк')
        self.assertEqual(fields['stir'], '123456789')
        self.assertEqual(fields['mfo'], '00450')
        self.assertEqual(fields['account'], test_bot.COMPANY['account'])

    def test_ambiguous_number_rejected(self):
        with self.assertRaises(ReadError):
            extract_fields('STIR: 123456789\nSTIR: 987654321')

    def test_real_ocr_image_and_scanned_pdf(self):
        for name in ['requisites.png', 'requisites-scan.pdf', 'requisites-text.pdf']:
            with self.subTest(name=name):
                text = read_document((FIXTURES / name).read_bytes(), ROOT)
                fields = extract_fields(text)
                self.assertEqual(fields['stir'], '123456789')
                self.assertEqual(fields['account'], test_bot.COMPANY['account'])
                self.assertEqual(fields['mfo'], '00450')
                self.assertTrue(fields.get('bank'))

    def test_file_limits_and_bad_file(self):
        for data in [b'not a file', b'x' * (MAX_BYTES + 1)]:
            with self.assertRaises(ReadError):
                read_document(data, ROOT)

    def test_template_split_runs_and_multiline(self):
        data = make_template()
        inspect_template(data)
        result = fill_template(data, 42, '14.11.2026', test_bot.COMPANY,
                               {'buyer': test_bot.COMPANY, 'items': [
                                   {'name': 'Kran & <katta>', 'amount': '0.10'},
                                   {'name': 'Rakovina', 'amount': '0.20'}]})
        with ZipFile(io.BytesIO(result)) as archive:
            tree = ET.fromstring(archive.read('word/document.xml'))
        text = ''.join(n.text or '' for n in tree.iter(W + 't'))
        self.assertIn('42 14.11.2026', text)
        self.assertIn('0.30', text)
        self.assertIn('Kran & <katta>', text)
        self.assertNotIn('{{', text)
        self.assertTrue(list(tree.iter(W + 'br')))

    def test_missing_template_tokens_rejected(self):
        with self.assertRaises(ValueError):
            inspect_template(document_bytes(1, 'date', test_bot.COMPANY,
                                           {'buyer': test_bot.COMPANY, 'items': []}))


class BotFilesTests(unittest.TestCase):
    setUp = test_bot.Tests.setUp
    tearDown = test_bot.Tests.tearDown
    send = test_bot.Tests.send

    def attach(self, data, filename='requisites.png'):
        self.api.download = lambda file_id: data
        self.bot.handle({'message': {'chat': {'id': 7, 'type': 'private'},
                                    'from': {'id': 7},
                                    'document': {'file_id': 'file-id', 'file_name': filename, 'file_size': len(data)}}})

    def test_seller_setup_requires_confirmation(self):
        self.send('/sozlash')
        self.send(test_bot.TEXT)
        self.assertEqual(self.store.session(7)['step'], 'seller_confirm')
        self.send(CONFIRM)
        saved = json.loads((self.root / 'company.json').read_text())
        self.assertEqual(saved, test_bot.COMPANY)
        self.assertIsNone(self.store.session(7))

    def test_partial_fields_preserved(self):
        self.send('/sozlash')
        self.send('Nomi: Sinov\nSTIR: 123456789')
        self.assertEqual(self.store.session(7)['prefill']['name'], 'Sinov')
        self.send('Bank: Sinov banki\nMFO: 00450')
        self.assertEqual(self.store.session(7)['prefill']['mfo'], '00450')

    def test_upload_stir_mismatch_does_not_advance(self):
        self.send(NEW); self.send('987654321')
        self.bot.reader = lambda data, root: test_bot.TEXT
        self.attach(b'fake-data')
        self.assertIn('farq', self.api.messages[-1])
        self.assertEqual(self.store.session(7)['step'], 'buyer')

    def test_real_ocr_into_buyer_session(self):
        self.send(NEW); self.send(test_bot.COMPANY['stir'])
        self.bot.reader = lambda data, root: read_document(data, ROOT)
        self.attach((FIXTURES / 'requisites.png').read_bytes())
        self.assertEqual(self.store.session(7)['step'], 'buyer_confirm')
        self.assertEqual(self.store.session(7)['buyer']['account'], test_bot.COMPANY['account'])

    def test_unauthorized_attachment_never_downloaded(self):
        self.api.download = lambda file_id: self.fail('Unauthorized download')
        self.bot.handle({'message': {'chat': {'id': 8, 'type': 'private'}, 'from': {'id': 8},
                                    'document': {'file_id': 'secret'}}})
        self.assertIsNone(self.store.session(8))

    def test_template_upload(self):
        self.send('/shablon')
        self.attach(make_template(), 'contract.docx')
        self.assertTrue((self.root / 'data/templates/7.docx').exists())
        self.assertIsNone(self.store.session(7))

    def test_demo_without_seller(self):
        (self.root / 'company.json').unlink()
        self.send('/namuna')
        with ZipFile(io.BytesIO(self.api.files[-1])) as archive:
            self.assertIn('XAYOLIY', archive.read('word/document.xml').decode())

    def test_complete_setup_ocr_template_contract_and_resend(self):
        (self.root / 'company.json').unlink()
        self.bot.reader = lambda data, root: read_document(data, ROOT)
        self.send('/sozlash')
        self.attach((FIXTURES / 'requisites.png').read_bytes())
        self.assertEqual(self.store.session(7)['step'], 'seller_confirm')
        self.send(CONFIRM)
        self.send('/shablon')
        self.attach(make_template(), 'contract.docx')
        self.send(NEW)
        self.send(test_bot.COMPANY['stir'])
        self.attach((FIXTURES / 'requisites-scan.pdf').read_bytes(), 'requisites.pdf')
        self.assertEqual(self.store.session(7)['step'], 'buyer_confirm')
        for text in [CONFIRM, 'Kran', '0.10', ADD, 'Rakovina', '0.20', NEXT, CONFIRM]:
            self.send(text)
        self.assertIsNone(self.store.session(7))
        with ZipFile(io.BytesIO(self.api.files[-1])) as archive:
            xml = archive.read('word/document.xml').decode()
        self.assertIn('0.30', xml)
        self.assertNotIn('{{', xml)
        self.send('/oxirgi')
        self.assertEqual(self.api.files[-1], self.api.files[-2])

    def test_bad_template_preserves_existing(self):
        previous = make_template()
        (self.root / 'template.docx').write_bytes(previous)
        self.send('/shablon')
        self.attach(b'broken', 'contract.docx')
        self.assertEqual((self.root / 'template.docx').read_bytes(), previous)
        self.assertEqual(self.store.session(7)['step'], 'template')

    def test_attachment_in_wrong_stage_not_downloaded(self):
        self.send(NEW)
        self.api.download = lambda file_id: self.fail('Unexpected download')
        self.bot.handle({'message': {'chat': {'id': 7, 'type': 'private'}, 'from': {'id': 7},
                                    'document': {'file_id': 'x'}}})
        self.assertEqual(self.store.session(7)['step'], 'stir')
