import json
import tempfile
import unittest
from pathlib import Path
from bot import Bot, Store, CONFIRM, CANCEL
from test_bot import COMPANY, FakeAPI, TEXT, NEW, fake_pdf

class CompanyMemoryTests(unittest.TestCase):
    def test_confirm_reuse_edit_restart_and_isolation(self):
        with tempfile.TemporaryDirectory() as temp:
            root=Path(temp)
            (root/'data').mkdir()
            (root/'company.json').write_text(json.dumps(COMPANY))
            store=Store(root/'data/test.sqlite3')
            api=FakeAPI()
            calls=[]
            bot=Bot(api,store,root,{7,8},lookup=lambda stir: calls.append(stir),pdf_exporter=fake_pdf)
            def send(text, user=7):
                bot.handle({'message':{'chat':{'id':user,'type':'private'},'from':{'id':user},'text':text}})
            for text in (NEW,COMPANY['stir'],TEXT): send(text)
            self.assertIsNone(store.saved_company(7,COMPANY['stir']))
            send(CONFIRM)
            self.assertEqual(store.saved_company(7,COMPANY['stir']),COMPANY)
            send(CANCEL)
            store.db.close()
            store=Store(root/'data/test.sqlite3')
            bot.store=store
            calls.clear()
            send(NEW);send(COMPANY['stir'])
            self.assertEqual(calls,[])
            self.assertIn('Shu firmani',api.messages[-1])
            send('Telefon: +998901234567')
            self.assertNotIn('phone',store.saved_company(7,COMPANY['stir']))
            send(CONFIRM)
            self.assertEqual(store.saved_company(7,COMPANY['stir'])['phone'],'+998901234567')
            self.assertIsNone(store.saved_company(8,COMPANY['stir']))
            send(NEW,8);send(COMPANY['stir'],8)
            self.assertEqual(calls,[COMPANY['stir']])
            store.db.close()
