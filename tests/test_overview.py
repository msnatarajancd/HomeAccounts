import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
from streamlit.testing.v1 import AppTest
from core import Store,read_tables,normalize_import,import_candidates
from setup_flow import save_schema,suggested_schema

ROOT=Path(__file__).resolve().parents[1]

class OverviewTests(unittest.TestCase):
    def setUp(self):
        self.folder=tempfile.TemporaryDirectory()
        self.environment=patch.dict(os.environ,{'HOMEACCOUNTS_DATA_DIR':self.folder.name})
        self.environment.start()
        self.store=Store(self.folder.name)
        fields,_=suggested_schema(['date','amount','currency','category','subcategory'])
        save_schema(self.store,fields,'EUR')
    def tearDown(self):
        self.environment.stop(); self.folder.cleanup()
    def app(self):
        app=AppTest.from_file(str(ROOT/'app.py'),default_timeout=30).run()
        self.assertEqual(list(app.exception),[])
        return app
    def button(self,app,label): return next(b for b in app.button if b.label==label)
    def seed(self,older=False):
        file=ROOT/'sample_data'/'household_demo.csv'; raw=file.read_bytes()
        mapping={'date':'date','merchant':'merchant','description':'particulars','category':'category','subcategory':'subcategory','expense':'expense_amount','income':'income_amount','currency':'currency','account':'account'}
        preview=normalize_import(read_tables(raw,file.name),file.name,raw,mapping,['CSV'],'EUR','Demo',2026,'ISO (YYYY-MM-DD)')
        records=preview['transactions']
        if older:
            for record in records: record['date']=record['date'].replace('2026','2025')
        self.store.commit(records,[],'','synthetic confirmed fixture')
    def test_empty_dashboard_explains_and_navigation_works(self):
        app=self.app()
        self.assertFalse(app.metric)
        self.assertTrue(any('Confirming fields creates your workspace' in i.value for i in app.info))
        self.assertTrue(self.button(app,'View this month’s transactions').disabled)
        self.button(app,'Import transactions').click().run()
        self.assertEqual(app.radio(key='page').value,'Import & review')
        app.radio(key='page').set_value('Overview').run()
        self.button(app,'Add an entry').click().run()
        self.assertEqual(app.radio(key='page').value,'Add transaction')
    def test_older_fixture_defaults_to_populated_month_and_scope(self):
        self.seed(older=True); app=self.app()
        self.assertEqual(app.selectbox(key='report_month_EUR').value,'2025-10')
        metrics={m.label:m.value for m in app.metric}
        self.assertEqual(metrics['Net expenses'],'EUR 232.75')
        self.assertEqual(metrics['Budget remaining'],'Not set')
        self.button(app,'View this month’s transactions').click().run()
        self.assertEqual(app.radio(key='page').value,'Transactions')
        self.assertEqual(app.selectbox(key='tx_category').value,'All')
        self.assertEqual(list(app.exception),[])
    def test_empty_month_and_currency_offer_recovery(self):
        self.seed(older=True); app=self.app()
        app.selectbox(key='report_month_EUR').set_value('2026-10').run()
        self.assertFalse(app.metric)
        self.button(app,'Show latest recorded month').click().run()
        self.assertEqual(app.selectbox(key='report_month_EUR').value,'2025-10')
        app.selectbox(key='active_currency').set_value('INR').run()
        self.assertEqual(app.selectbox(key='report_month_INR').value,'2025-10')
        self.assertEqual(next(m.value for m in app.metric if m.label=='Net expenses'),'INR 2,000.00')
        app.selectbox(key='active_currency').set_value('JPY').run()
        self.assertFalse(app.metric)
        self.assertTrue(any('No confirmed transactions use JPY' in i.value for i in app.info))
    def test_category_drilldown_and_budget_navigation(self):
        self.seed(); app=self.app()
        selector=next(s for s in app.selectbox if s.label=='Category to inspect')
        selector.set_value('Groceries').run()
        self.button(app,'View selected category records').click().run()
        self.assertEqual(app.radio(key='page').value,'Transactions')
        self.assertEqual(app.selectbox(key='tx_category').value,'Groceries')
        app.radio(key='page').set_value('Overview').run()
        self.button(app,'Set or review budgets').click().run()
        self.assertEqual(app.radio(key='page').value,'Budgets')
        self.assertEqual(list(app.exception),[])

if __name__=='__main__': unittest.main()
