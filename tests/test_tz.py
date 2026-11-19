import io,json,unittest
from pathlib import Path
from zipfile import ZipFile
from xml.etree import ElementTree as ET
from decimal import Decimal
from bot import READY,CONFIRM,NEXT,NEW,KEEP,VAT12,VAT0,VAT_OTHER,INCLUDED,EXCLUDED,write_json
from contract_values import calculate_item
from pdf_export import ExportError
import test_bot
TEMPLATE=Path(__file__).resolve().parents[1]/'template.docx'
class TZTests(unittest.TestCase):
    setUp=test_bot.Tests.setUp
    tearDown=test_bot.Tests.tearDown
    send=test_bot.Tests.send
    def configure(self):
        (self.root/'template.docx').write_bytes(TEMPLATE.read_bytes())
        write_json(self.bot.preference_path(7),{'template':'ready'})
    def through_items(self,rate=VAT12,mode=INCLUDED):
        self.configure()
        for v in [NEW,test_bot.COMPANY['stir'],test_bot.TEXT,CONFIRM,rate]:self.send(v)
        if rate!=VAT0:self.send(mode)
        for v in ['Цемент М 400','т','3','800000',NEXT]:self.send(v)
    def xml(self):
        with ZipFile(io.BytesIO(self.api.files[-1])) as z:return z.read('word/document.xml').decode()
    def test_structured_contract_word_and_pdf(self):
        self.through_items();self.send(CONFIRM)
        self.assertIsNone(self.store.session(7));self.assertEqual(len(self.api.files),1);self.assertEqual(len(self.api.pdf_files),1)
        xml=self.xml()
        for v in ['714 285.71','2 142 857.14','257 142.86','2 400 000.00','Цемент М 400']:self.assertIn(v,xml)
        self.assertNotIn('CEMENT PROMAX',xml)
        self.send('/oxirgi');self.assertEqual(len(self.api.pdf_files),2)
    def test_zero_vat(self):
        self.through_items(VAT0);self.send(CONFIRM)
        xml=self.xml();self.assertIn('без НДС',xml);self.assertNotIn('НДС 12%',xml);self.assertNotIn('12 %',xml)
    def test_invalid_quantity_and_price(self):
        self.configure()
        for v in [NEW,test_bot.COMPANY['stir'],test_bot.TEXT,CONFIRM,VAT12,INCLUDED,'Cement','т','0']:self.send(v)
        self.assertEqual(self.store.session(7)['step'],'quantity')
        self.send('3');self.send('-1');self.assertEqual(self.store.session(7)['step'],'price');self.assertEqual(self.store.session(7)['items'],[])
    def test_first_run_onboarding_once(self):
        (self.root/'company.json').unlink();(self.root/'template.docx').write_bytes(TEMPLATE.read_bytes())
        self.send(NEW);self.assertEqual(self.store.session(7)['step'],'template_choice')
        self.send(READY);self.assertEqual(self.store.session(7)['step'],'settings');self.assertEqual(self.store.session(7)['index'],0)
        for v in ['123456789','Seller','Director','Address','Bank','20208000000000000001','00450','-','-',CONFIRM]:self.send(v)
        self.assertEqual(self.store.session(7)['step'],'stir');self.send(NEW);self.assertEqual(self.store.session(7)['step'],'stir')
    def test_changed_seller_stir_clears_old_fields(self):
        self.bot.lookup=lambda _:dict(stir='987654321',name='FOUND',address='NEW',source_url='https://orginfo.uz')
        self.send('/settings');self.send('987654321');v=self.store.session(7)['values']
        self.assertEqual(v['name'],'FOUND');self.assertNotIn('account',v);self.assertNotIn('director',v)
        self.send(KEEP);self.assertEqual(self.store.session(7)['values']['name'],'FOUND')
    def test_pdf_retry_no_second_word_or_number(self):
        self.through_items()
        def fail(_):raise ExportError('test')
        self.bot.pdf_exporter=fail;self.send(CONFIRM);self.assertTrue(self.store.session(7)['word_sent'])
        self.bot.pdf_exporter=test_bot.fake_pdf;self.send(CONFIRM)
        self.assertEqual(len(self.api.files),1);self.assertEqual(len(self.api.pdf_files),1)
        self.assertEqual(self.store.db.execute('SELECT COUNT(*) FROM contracts').fetchone()[0],1)
    def test_discover_template_choice(self):
        from bot import CONTRACT_TEMPLATES,DISCOVER_FILE
        self.configure()
        out=io.BytesIO()
        with ZipFile(TEMPLATE) as src,ZipFile(out,'w') as dst:
            for name in src.namelist():
                data=src.read(name)
                dst.writestr(name,data.replace('ДОГОВОР ПОСТАВКИ'.encode(),b'DISCOVER') if name=='word/document.xml' else data)
        (self.root/DISCOVER_FILE).write_bytes(out.getvalue())
        self.send(NEW);self.assertEqual(self.store.session(7)['step'],'template_pick')
        self.send('nimadir');self.assertEqual(self.store.session(7)['step'],'template_pick')
        self.send(CONTRACT_TEMPLATES[1][0]);s=self.store.session(7)
        self.assertEqual((s['step'],s['template_file']),('stir',DISCOVER_FILE))
        for v in [test_bot.COMPANY['stir'],test_bot.TEXT,CONFIRM,VAT12,INCLUDED,'Цемент','т','3','800000',NEXT,CONFIRM]:self.send(v)
        self.assertIn('DISCOVER',self.xml())
        self.send(NEW);self.send(CONTRACT_TEMPLATES[0][0]);self.assertEqual(self.store.session(7)['template_file'],'template.docx')
    def test_no_choice_without_discover_file(self):
        self.configure();self.send(NEW);self.assertEqual(self.store.session(7)['step'],'stir')
    def test_personal_templates(self):
        self.configure();p=self.root/'data/templates/7.docx';p.parent.mkdir(parents=True);p.write_bytes(TEMPLATE.read_bytes())
        write_json(self.bot.preference_path(7),{'template':'custom'});self.assertEqual(self.bot.template_for(7),p)
        self.assertEqual(self.bot.template_for(8),self.root/'template.docx')
        write_json(self.bot.preference_path(7),{'template':'ready'});self.assertEqual(self.bot.template_for(7),self.root/'template.docx')
    def test_custom_tax_and_excluded_price(self):
        self.configure()
        for v in [NEW,test_bot.COMPANY['stir'],test_bot.TEXT,CONFIRM,VAT_OTHER,'15',EXCLUDED,'Item','dona','2','100',NEXT,CONFIRM]:self.send(v)
        self.assertIn('230.00',self.xml());self.assertIn('НДС 15%',self.xml())
    def test_complete_lookup_can_confirm_and_edit(self):
        self.bot.lookup=lambda _:dict(test_bot.COMPANY,source_url='https://orginfo.uz')
        self.send(NEW);self.send(test_bot.COMPANY['stir'])
        self.assertEqual(self.store.session(7)['step'],'buyer_confirm')
        self.send('Bank: UPDATED')
        self.assertEqual(self.store.session(7)['buyer']['bank'],'UPDATED')

    def test_upload_preserved_when_ocr_fails(self):
        self.send(NEW);self.send(test_bot.COMPANY['stir'])
        self.api.download=lambda _:b'\x89PNGfake-image'
        self.bot.reader=lambda *_:''
        self.bot.handle({'message':{'chat':{'id':7,'type':'private'},'from':{'id':7},'photo':[{'file_id':'photo'}]}})
        files=list((self.root/'data/uploads/7').glob('*.png'))
        self.assertEqual(len(files),1);self.assertEqual(files[0].read_bytes(),b'\x89PNGfake-image')
        self.assertTrue(files[0].with_suffix('.png.json').exists())

class CalculationTests(unittest.TestCase):
    def test_net_unit_line_rounding_reconciles(self):
        u,n,v,g=calculate_item({'price':'800000','quantity':'3'})
        self.assertEqual(u.quantize(Decimal('.01')),Decimal('714285.71'));self.assertEqual(n,(u*3).quantize(Decimal('.01')));self.assertEqual(n+v,g);self.assertEqual(g,Decimal('2400000'))
    def test_excluded_price(self):
        self.assertEqual(calculate_item({'price':'100','quantity':'3'},'12','excluded'),(Decimal('100'),Decimal('300'),Decimal('36'),Decimal('336')))
    def test_other_clauses_preserved(self):
        ref=Path(__file__).resolve().parents[3]/'work/requirements/blank.docx'
        if not ref.exists():self.skipTest('Reference outside deployment')
        from templates import fill_template,W
        with ZipFile(ref) as z:a=ET.fromstring(z.read('word/document.xml')).find(W+'body').findall(W+'p')
        with ZipFile(io.BytesIO(fill_template(TEMPLATE.read_bytes(),3,'01.01.2028',test_bot.COMPANY,dict(buyer=test_bot.COMPANY,items=[dict(name='Test',amount='100')])))) as z:b=ET.fromstring(z.read('word/document.xml')).find(W+'body').findall(W+'p')
        for i,(x,y) in enumerate(zip(a,b)):
            if i not in {0,1,16,58,59,60,64,70}:self.assertEqual(ET.tostring(x),ET.tostring(y),f'Paragraph {i}')
