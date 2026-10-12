import datetime as dt
import json
import os
from pathlib import Path
import tempfile
import unittest
from streamlit.testing.v1 import AppTest
from core import *
from currencies import display,display_minor,digits
from setup_flow import interpret_fields,suggested_schema,save_schema,load_schema,validate_schema

ROOT=Path(__file__).resolve().parents[1]

class CurrencyAndSchemaTests(unittest.TestCase):
    def test_currency_precision_and_isolation(self):
        def row(curr,val): return valid_tx({'date':'2026-10-01','type':'expense','amount':val,'currency':curr,'account':'Demo','description':'Fictional'})
        tx=[row('INR','50.25'),row('EUR','90.10'),row('JPY','1000'),row('KWD','1.234')]
        self.assertEqual(spending(tx,'2026-10','INR'),5025)
        self.assertEqual(spending(tx,'2026-10','EUR'),9010)
        self.assertEqual(spending(tx,'2026-10','JPY'),1000)
        self.assertEqual(spending(tx,'2026-10','KWD'),1234)
        self.assertEqual(digits('JPY'),0); self.assertEqual(digits('KWD'),3)
        self.assertIn('JPY 1,000',display_minor(1000,'JPY'))
        self.assertIn('KWD 1.234',display_minor(1234,'KWD'))
        self.assertIn('INR',display(50.25,'INR'))
        with self.assertRaises(ValueError): row('JPY','1.25')
        with self.assertRaises(ValueError): row('ZZZ','1')

    def test_sentence_currency_symbols_and_explicit_codes(self):
        today=dt.date(2026,10,11)
        for text,curr,expected in [('I spent 45 yesterday','INR','INR'),('I spent €45 yesterday','EUR','EUR'),('I spent 45 EUR yesterday','INR','EUR'),('I spent 45 eur yesterday','INR','EUR'),('I spent ₹45 yesterday','INR','INR')]:
            row,_=parse_sentence(text,today,curr,'Demo',[]); self.assertEqual(row['currency'],expected)
        with self.assertRaises(ValueError): parse_sentence('I spent $45 yesterday',today,'INR','Demo',[])
        with self.assertRaises(ValueError): parse_sentence('I spent forty-five rupees yesterday',today,'EUR','Demo',[])

    def test_schema_names_and_custom_roundtrip(self):
        rows,notes=interpret_fields('date, category, particulars, expense amount, income amount, monthly budget, payment method')
        self.assertTrue(any('separately' in n for n in notes))
        desc=next(r for r in rows if r['key']=='description'); desc['label']='Memo'
        with tempfile.TemporaryDirectory() as folder:
            store=Store(folder); save_schema(store,rows,'INR')
            self.assertEqual(next(r for r in load_schema(store)['fields'] if r['key']=='description')['label'],'Memo')
            t=valid_tx({'date':'2026-10-11','type':'expense','amount':'25.50','currency':'INR','account':'Demo','custom_fields':json.dumps({'custom_payment_method':'Demo cash'})})
            store.commit([t],[],'','custom')
            exported=csv_bytes(store.load()['transactions'],TX_FIELDS)
            mappings={k:k for k in TX_FIELDS}
            p=normalize_import(read_tables(exported,'export.csv'),'export.csv',exported,mappings,['CSV'],'EUR','Demo',2026,'ISO (YYYY-MM-DD)')
            self.assertEqual(p['transactions'][0]['currency'],'INR')
            self.assertEqual(json.loads(p['transactions'][0]['custom_fields'])['custom_payment_method'],'Demo cash')
        with self.assertRaises(ValueError): validate_schema([r for r in rows if r['key']!='date'])

    def test_portable_mock_data_and_snapshot_block(self):
        path=ROOT/'sample_data'/'household_demo.csv'; raw=path.read_bytes(); tables=read_tables(raw,path.name)
        mapping={'date':'date','merchant':'merchant','description':'particulars','category':'category','subcategory':'subcategory','expense':'expense_amount','income':'income_amount','currency':'currency','account':'account','custom_payment_method':'payment_method'}
        p=normalize_import(tables,path.name,raw,mapping,['CSV'],'JPY','Demo',2026,'ISO (YYYY-MM-DD)')
        self.assertEqual(len(p['transactions']),12); self.assertEqual(p['issues'],[])
        self.assertEqual(spending(p['transactions'],'2026-10','EUR'),23275)
        self.assertEqual(spending(p['transactions'],'2026-10','INR'),200000)
        b=normalize_import(tables,path.name,raw,{'category':'category','budget':'monthly_budget','period':'budget_period','currency':'currency'},['CSV'],'JPY','Demo',2026,'ISO (YYYY-MM-DD)','Budgets')
        self.assertEqual(len(import_candidates(b,{'transactions':[],'budgets':[]})[1]),8)
        snapshot=ROOT/'sample_data'/'balances_wishlist_demo.csv'; raw=snapshot.read_bytes()
        p=normalize_import(read_tables(raw,snapshot.name),snapshot.name,raw,{'amount':'amount'},['CSV'],'EUR','Demo',2026,'ISO (YYYY-MM-DD)')
        self.assertEqual(p['transactions'],[]); self.assertTrue(p['issues'])

class WelcomeTests(unittest.TestCase):
    def setUp(self):
        self.folder=tempfile.TemporaryDirectory(); self.old=os.environ.get('HOMEACCOUNTS_DATA_DIR')
        os.environ['HOMEACCOUNTS_DATA_DIR']=self.folder.name
        self.app=AppTest.from_file(str(ROOT/'app.py'),default_timeout=30).run()
    def tearDown(self):
        if self.old is None: os.environ.pop('HOMEACCOUNTS_DATA_DIR',None)
        else: os.environ['HOMEACCOUNTS_DATA_DIR']=self.old
        self.folder.cleanup()
    def button(self,label): return next(b for b in self.app.button if b.label==label)
    def clean(self): self.assertEqual(list(self.app.exception),[])
    def test_minimal_welcome(self):
        self.clean(); self.assertFalse(self.app.radio); self.assertFalse(self.app.metric)
        self.assertEqual([t.label for t in self.app.tabs],['Upload a file','Describe your fields'])
    def test_description_confirm_custom_entry_and_revisit(self):
        self.app.text_area[0].set_value('date, category, particulars, expense amount, income amount, monthly budget, payment method')
        self.button('Suggest fields from my description').click().run(); self.clean()
        self.assertFalse(self.app.radio)
        self.assertTrue(self.button('Confirm fields & continue').disabled)
        self.assertTrue(any('One step left' in w.value for w in self.app.warning))
        self.app.selectbox(key='setup_currency').set_value('INR').run()
        self.assertFalse(self.button('Confirm fields & continue').disabled)
        self.button('Confirm fields & continue').click().run(); self.clean()
        self.assertTrue(self.app.radio)
        next(t for t in self.app.text_input if t.label=='Particulars').set_value('Fictional purchase')
        next(t for t in self.app.text_input if t.label=='payment method').set_value('Demo cash')
        next(t for t in self.app.selectbox if t.label=='Category').set_value('Household')
        self.button('Review transaction').click().run(); self.clean()
        self.assertEqual(Store(self.folder.name).load()['transactions'],[])
        self.button('Confirm save').click().run(); self.clean()
        saved=Store(self.folder.name).load()['transactions'][0]
        self.assertEqual(saved['currency'],'INR'); self.assertEqual(json.loads(saved['custom_fields'])['custom_payment_method'],'Demo cash')
        self.button('Review field setup').click().run(); self.clean()
        self.assertFalse(self.app.radio); self.assertEqual(len(Store(self.folder.name).load()['transactions']),1)
        self.button('Return to your workspace').click().run(); self.clean()
    def test_demo_upload_proposal_confirmation_workspace(self):
        self.button('Try demo data').click().run(); self.clean()
        self.assertFalse(self.app.radio)
        self.app.selectbox(key='setup_currency').set_value('EUR').run()
        self.button('Confirm fields & continue').click().run(); self.clean()
        self.button('Prepare import review').click().run(); self.clean()
        self.button('Stage reviewed import').click().run(); self.clean()
        self.assertEqual(Store(self.folder.name).load()['transactions'],[])
        self.button('Confirm save').click().run(); self.clean()
        self.assertEqual(len(Store(self.folder.name).load()['transactions']),12)
        self.app.radio(key='page').set_value('Overview').run(); self.clean()
        existing=AppTest.from_file(str(ROOT/'app.py'),default_timeout=30).run()
        self.assertEqual(list(existing.exception),[]); self.assertTrue(existing.radio)

if __name__=='__main__': unittest.main()
