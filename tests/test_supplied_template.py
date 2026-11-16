import hashlib
import io
import unittest
from pathlib import Path
from zipfile import ZipFile
from xml.etree import ElementTree as ET

from templates import fill_template, inspect_template, W
from test_bot import COMPANY

TEMPLATE = Path(__file__).resolve().parents[1] / 'template.docx'


class SuppliedTemplateTests(unittest.TestCase):
    def test_dynamic_parties_and_repeated_product_rows(self):
        source = TEMPLATE.read_bytes()
        inspect_template(source)
        seller = {**COMPANY, 'name': 'NEW SELLER', 'director': 'SELLER DIRECTOR'}
        buyer = {**COMPANY, 'name': 'NEW BUYER', 'director': 'BUYER DIRECTOR', 'stir': '987654321'}
        result = fill_template(source, 701, '14.11.2026', seller, {'buyer': buyer, 'items': [
            {'name': 'FIRST ITEM', 'unit': 'т', 'quantity': '3', 'amount': '2400000.00'},
            {'name': 'SECOND ITEM', 'unit': 'шт', 'quantity': '2', 'amount': '112.00'},
        ]})
        with ZipFile(io.BytesIO(result)) as z:
            tree = ET.fromstring(z.read('word/document.xml'))
            text = ''.join(t.text or '' for t in tree.iter(W+'t'))
            self.assertNotIn('{{', text)
            self.assertNotIn('STRUCTA', text)
            self.assertNotIn('CEMENT PROMAX', text)
            self.assertGreaterEqual(text.count('NEW SELLER'), 3)
            self.assertGreaterEqual(text.count('NEW BUYER'), 3)
            self.assertIn('2 400 112.00', text)
            self.assertIn('257 154.86', text)
            self.assertIn('14» ноября 2026', text)
            tables = tree.find(W+'body').findall(W+'tbl')
            self.assertEqual(len(tables[2].findall(W+'tr')), 4)
            with ZipFile(io.BytesIO(source)) as original:
                for name in original.namelist():
                    if name != 'word/document.xml':
                        self.assertEqual(z.read(name), original.read(name), name)

    def test_profile_changes_propagate_to_all_party_blocks(self):
        result = fill_template(TEMPLATE.read_bytes(), 702, '01.01.2027',
                               {**COMPANY, 'name': 'REPLACED SELLER', 'account': '20208000000000000009'},
                               {'buyer': COMPANY, 'items': [{'name':'ITEM','amount':'100.50'}]})
        with ZipFile(io.BytesIO(result)) as z:
            tree = ET.fromstring(z.read('word/document.xml'))
        text = ''.join(t.text or '' for t in tree.iter(W+'t'))
        self.assertEqual(text.count('20208000000000000009'), 2)
        self.assertIn('2027 года', text)
        self.assertNotIn('2026', text)
