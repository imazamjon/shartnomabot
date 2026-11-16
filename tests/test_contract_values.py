import unittest
from contract_values import build_values, words_ru
from test_bot import COMPANY


class ContractValueTests(unittest.TestCase):
    def test_source_vat_calculation(self):
        values,rows=build_values(182,'09.11.2026',COMPANY,{'buyer':COMPANY,'items':[
            {'name':'Цемент М 400','unit':'т','quantity':'3','amount':'2400000.00'}]})
        self.assertEqual(rows[0]['item_unit_price'],'714 285.71')
        self.assertEqual(values['net_total'],'2 142 857.14')
        self.assertEqual(values['vat_total'],'257 142.86')
        self.assertEqual(values['total'],'2 400 000.00')
        self.assertEqual(values['total_words'],'Два миллиона четыреста тысяч сум 00 тийин')
        self.assertEqual(values['date_long'],'«09» ноября 2026 г.')

    def test_unknown_quantity_not_invented(self):
        values,rows=build_values(1,'14.11.2026',COMPANY,{'buyer':COMPANY,'items':[{'name':'Tovar','amount':'1000.50'}]})
        self.assertEqual(rows[0]['item_quantity'],'—')
        self.assertEqual(rows[0]['item_unit_price'],'—')
        self.assertIn('50 тийин',values['total_words'])

    def test_russian_grammar(self):
        for number,text in [(0,'ноль'),(1000,'одна тысяча'),(2000,'две тысячи'),(11000,'одиннадцать тысяч'),
                            (21000,'двадцать одна тысяча'),(1000001,'один миллион один')]:
            self.assertEqual(words_ru(number),text)
