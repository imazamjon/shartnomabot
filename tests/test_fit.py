import io
import unittest
from pathlib import Path
from zipfile import ZipFile

import fit
from pdf_export import available
from templates import fill_template
from test_bot import COMPANY

TEMPLATE = Path(__file__).resolve().parents[1] / 'template.docx'


def contract(items=1):
    session = {'buyer': {**COMPANY, 'stir': '987654321'}, 'vat_rate': '12', 'price_mode': 'included',
               'items': [{'name': f'Sement M400 partiya {i}', 'unit': 'т', 'quantity': '20',
                          'price': '700000.00', 'amount': '14000000.00'} for i in range(items)]}
    return fill_template(TEMPLATE.read_bytes(), 182, '14.11.2026', COMPANY, session)


class FitTests(unittest.TestCase):
    def test_template_has_no_phone(self):
        with ZipFile(TEMPLATE) as z:
            xml = z.read('word/document.xml').decode()
        self.assertNotIn('phone', xml)
        self.assertNotIn('Тел:', xml)

    def test_fake_converter_shrinks_until_fits(self):
        calls = []

        def converter(data):
            calls.append(data)
            return b'%PDF-fake'
        pages = iter([(3, 1), (2, 1)])
        original = fit.section_pages
        fit.section_pages = lambda pdf, marker: next(pages)
        try:
            result, pdf = fit.fit_document(contract(), converter)
        finally:
            fit.section_pages = original
        self.assertEqual(len(calls), 2)
        self.assertEqual(pdf, b'%PDF-fake')
        self.assertNotEqual(result, calls[0])
        with ZipFile(io.BytesIO(result)) as z:
            xml = z.read('word/document.xml').decode()
        self.assertIn('w:val="20"', xml)  # 10.5pt body text reduced to 10pt.

    def test_failed_converter_keeps_document(self):
        def converter(_):
            raise fit.ExportError('none')
        data = contract()
        self.assertEqual(fit.fit_document(data, converter), (data, None))

    @unittest.skipUnless(available(), 'LibreOffice yo‘q')
    def test_real_layout_is_two_plus_one_pages(self):
        for items in (1, 20):
            _, pdf = fit.fit_document(contract(items))
            self.assertIsNotNone(pdf)
            main, spec = fit.section_pages(pdf, 'Приложение №1')
            self.assertEqual((main, spec), (2, 1), items)


if __name__ == '__main__':
    unittest.main()
