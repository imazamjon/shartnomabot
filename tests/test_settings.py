import json
import unittest
from pathlib import Path
from zipfile import ZipFile
import io
import test_bot
from bot import CONFIRM, CANCEL, KEEP, NEW, NEXT, Bot


class SettingsTests(unittest.TestCase):
    setUp = test_bot.Tests.setUp
    tearDown = test_bot.Tests.tearDown
    send = test_bot.Tests.send

    def fill(self, name='NEW SELLER'):
        self.send('/settings')
        for value in ['123456789',name,'Direktor','Manzil','Bank','20208000000000000001','00450','-']:
            self.send(value)

    def test_settings_saved_after_confirmation_only(self):
        self.fill()
        path = self.bot.seller_path(7)
        self.assertFalse(path.exists())
        self.assertEqual(self.store.session(7)['step'], 'seller_confirm')
        self.send(CONFIRM)
        self.assertEqual(json.loads(path.read_text())['name'], 'NEW SELLER')
        self.assertEqual(json.loads((self.root/'company.json').read_text()),test_bot.COMPANY)

    def test_admins_have_separate_sellers(self):
        self.fill('FIRST SELLER');self.send(CONFIRM)
        self.bot.allowed.add(8)
        self.send('/settings',8)
        for value in ['987654321','SECOND SELLER','Rahbar','Manzil','Bank','20208000000000000002','00451','-']:
            self.send(value,8)
        self.send(CONFIRM,8)
        self.assertEqual(self.bot.seller_for(7)['name'],'FIRST SELLER')
        self.assertEqual(self.bot.seller_for(8)['name'],'SECOND SELLER')

    def test_cancel_keeps_previous_profile(self):
        self.fill('OLD');self.send(CONFIRM)
        previous=self.bot.seller_path(7).read_bytes()
        self.send('/settings');self.send('UNSAVED');self.send(CANCEL)
        self.assertEqual(self.bot.seller_path(7).read_bytes(),previous)

    def test_bad_stir_does_not_advance(self):
        self.send('/settings');self.send('123')
        self.assertEqual(self.store.session(7)['index'],0)

    def test_keep_and_optional_fields(self):
        self.send('/settings')
        for _ in range(7):self.send(KEEP)
        self.send('69201');self.send(CONFIRM)
        seller=self.bot.seller_for(7)
        self.assertEqual(seller['name'],test_bot.COMPANY['name'])
        self.assertEqual(seller['oked'],'69201')

    def test_settings_survive_new_bot_instance(self):
        self.fill('PERSISTED');self.send(CONFIRM)
        another=Bot(self.api,self.store,self.root,{7},lookup=lambda _:None)
        self.assertEqual(another.seller_for(7)['name'],'PERSISTED')

    def test_in_progress_contract_uses_seller_snapshot(self):
        self.fill('ORIGINAL SELLER');self.send(CONFIRM)
        for value in [NEW,test_bot.COMPANY['stir'],test_bot.TEXT,CONFIRM,'Tovar','100',NEXT]:self.send(value)
        path=self.bot.seller_path(7)
        changed=json.loads(path.read_text());changed['name']='LATER SELLER';path.write_text(json.dumps(changed))
        self.send(CONFIRM)
        with ZipFile(io.BytesIO(self.api.files[-1])) as z:xml=z.read('word/document.xml').decode()
        self.assertIn('ORIGINAL SELLER',xml)
        self.assertNotIn('LATER SELLER',xml)

    def test_optional_quantity_is_recorded(self):
        for value in [NEW,test_bot.COMPANY['stir'],test_bot.TEXT,CONFIRM,'Цемент М 400 | т | 3','2400000']:
            self.send(value)
        self.assertEqual(self.store.session(7)['items'][0],{'name':'Цемент М 400','unit':'т','quantity':'3','amount':'2400000.00'})

    def test_unauthorized_settings_denied(self):
        self.send('/settings',8)
        self.assertIsNone(self.store.session(8))
        self.assertFalse(self.bot.seller_path(8).exists())
