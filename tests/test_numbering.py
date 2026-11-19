import io,json,sqlite3,unittest
from pathlib import Path
from zipfile import ZipFile
from bot import NEW,NEXT,CONFIRM,CANCEL,EDIT_NUMBER,EDIT_DATE,TODAY,NUMBER_SETTINGS,Store,contract_number,contract_date
import test_bot

class NumberingTests(unittest.TestCase):
    setUp=test_bot.Tests.setUp
    tearDown=test_bot.Tests.tearDown
    send=test_bot.Tests.send
    prepare=test_bot.Tests.prepare
    def test_settings_confirm_and_cancel(self):
        self.send('/settings');self.send(NUMBER_SETTINGS);self.send('284')
        self.assertEqual(self.store.next_number('stir:123456789'),1)
        self.send(CANCEL);self.assertEqual(self.store.next_number('stir:123456789'),1)
        self.send('/raqamlash');self.send('284');self.send(CONFIRM)
        self.assertEqual(self.store.next_number('stir:123456789'),284)
    def test_number_and_date_edit_fill_word(self):
        self.prepare();self.send(EDIT_NUMBER);self.send('283');self.send(EDIT_DATE);self.send('09.11.2026');self.send(CONFIRM)
        with ZipFile(io.BytesIO(self.api.files[-1])) as z:xml=z.read('word/document.xml').decode()
        self.assertIn('283',xml);self.assertIn('09.11.2026',xml)
        row=self.store.db.execute('SELECT id,display_number,date FROM contracts').fetchone()
        self.assertEqual(row,(1,'283','09.11.2026'));self.assertEqual(self.store.next_number('stir:123456789'),284)
    def test_auto_increments_only_after_confirm(self):
        self.store.set_next_number('stir:123456789',284)
        self.prepare();self.assertEqual(self.store.session(7)['contract_number'],284)
        self.send(CANCEL);self.assertEqual(self.store.next_number('stir:123456789'),284)
        self.prepare();self.send(CONFIRM);self.prepare()
        self.assertEqual(self.store.session(7)['contract_number'],285)
    def test_first_number_then_date(self):
        self.store.db.execute('DELETE FROM numbering');self.store.db.commit()
        self.prepare();self.assertEqual(self.store.session(7)['step'],'contract_number')
        self.send('284');self.assertEqual(self.store.session(7)['step'],'contract_date')
        self.send(TODAY);self.assertEqual(self.store.session(7)['step'],'confirm')
        self.send(CONFIRM);self.assertEqual(self.store.next_number('stir:123456789'),285)
    def test_duplicate_rejected_and_lower_number_does_not_rewind(self):
        self.prepare();self.send(CONFIRM)
        self.prepare();self.send(EDIT_NUMBER);self.send('1')
        self.assertEqual(self.store.session(7)['step'],'edit_number')
        self.assertIn('avval',self.api.messages[-1])
        self.store.set_next_number('stir:123456789',284)
        self.send('100');self.send(CONFIRM)
        self.assertEqual(self.store.next_number('stir:123456789'),284)
    def test_shared_numbering_and_restart(self):
        self.store.set_next_number('stir:123456789',284)
        self.store.set_next_number('stir:987654321',50)
        another=Store(self.root/'data/test.sqlite3')
        try:
            self.assertEqual(another.next_number('stir:123456789'),284)
            self.assertEqual(another.next_number('stir:987654321'),50)
        finally:another.db.close()
    def test_two_employees_share_company_sequence(self):
        self.store.set_next_number('stir:123456789',284)
        self.bot.allowed.add(8)
        self.prepare();self.send(CONFIRM)
        [self.send(v,8) for v in [NEW,test_bot.COMPANY['stir'],test_bot.TEXT,CONFIRM,'Kran','0.10',NEXT]];self.assertEqual(self.store.session(8)['contract_number'],285)
    def test_old_per_admin_scopes_merge(self):
        self.store.db.execute("INSERT INTO numbering VALUES ('7:555555555',10),('8:555555555',30)");self.store.db.commit()
        another=Store(self.root/'data/test.sqlite3')
        try:
            self.assertEqual(another.next_number('stir:555555555'),30)
            self.assertIsNone(another.next_number('7:555555555'))
        finally:another.db.close()
    def test_delivery_retry_no_extra_number(self):
        self.prepare();self.api.fail_upload=True
        with self.assertRaises(RuntimeError):self.send(CONFIRM)
        self.assertEqual(self.store.next_number('stir:123456789'),2)
        self.api.fail_upload=False;self.send(CONFIRM)
        self.assertEqual(self.store.next_number('stir:123456789'),2)
        self.assertEqual(self.store.db.execute('SELECT COUNT(*) FROM contracts').fetchone()[0],1)
    def test_invalid_date_and_number_keep_edit_step(self):
        self.prepare();self.send(EDIT_NUMBER)
        for v in ['0','-1','abc','2.5']:self.send(v)
        self.assertEqual(self.store.session(7)['step'],'edit_number')
        self.send('283');self.send(EDIT_DATE);self.send('31.02.2026')
        self.assertEqual(self.store.session(7)['step'],'edit_date')
    def test_old_contract_migration_preserves_issued_numbers(self):
        self.store.db.execute('INSERT INTO contracts(chat,date,data) VALUES (?,?,?)',(7,'14.11.2026',json.dumps({'seller_snapshot':test_bot.COMPANY})))
        self.store.db.commit()
        another=Store(self.root/'data/test.sqlite3')
        try:
            self.assertTrue(another.number_used('stir:123456789',1))
            self.assertEqual(another.next_number('stir:123456789'),2)
        finally:another.db.close()
    def test_supplied_template_repeats_number_and_date(self):
        from templates import fill_template,W
        from xml.etree import ElementTree as E
        source=(Path(__file__).resolve().parents[1]/'template.docx').read_bytes()
        data=fill_template(source,283,'09.11.2026',test_bot.COMPANY,dict(buyer=test_bot.COMPANY,items=[dict(name='Item',amount='112')]))
        with ZipFile(io.BytesIO(data)) as z:text=''.join(t.text or '' for t in E.fromstring(z.read('word/document.xml')).iter(W+'t'))
        self.assertEqual(text.count('283'),2);self.assertEqual(text.count('09» ноября 2026'),3)
