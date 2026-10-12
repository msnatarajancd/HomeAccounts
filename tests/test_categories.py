import tempfile
import unittest
from core import Store,valid_tx,coach
import datetime as dt
from unittest.mock import patch
from setup_flow import save_schema,load_schema,suggested_schema
from categories import STARTER,reconcile,options,suboptions
from pathlib import Path
import os
from streamlit.testing.v1 import AppTest

class CategoryTests(unittest.TestCase):
    def test_opt_in_persistence_and_options(self):
        with tempfile.TemporaryDirectory() as folder:
            store=Store(folder); fields,_=suggested_schema(['date','amount'])
            save_schema(store,fields,'EUR')
            self.assertEqual(load_schema(store)['taxonomy'],[])
            save_schema(store,fields,'EUR',STARTER)
            hierarchy=load_schema(store)['taxonomy']
            self.assertIn('Food',options(hierarchy,[],'expense'))
            self.assertIn('Groceries',suboptions(hierarchy,[],'expense','Food'))
            self.assertNotIn('Salary',suboptions(hierarchy,[],'expense','Food'))
            self.assertTrue(next(f for f in load_schema(store)['fields'] if f['key']=='subcategory')['included'])
    def test_removal_archives_referenced_and_preserves_records(self):
        row=valid_tx({'date':'2026-10-01','type':'expense','amount':'12','currency':'EUR','account':'Demo','category':'Food','subcategory':'Groceries'})
        previous=[{'type':'expense','category':'Food','subcategory':'Groceries','active':True}]
        new=[{'type':'expense','category':'Food','subcategory':'Fresh food','active':True}]
        reconciled=reconcile(new,previous,[row],[])
        self.assertTrue(any(r['subcategory']=='Groceries' and not r['active'] for r in reconciled))
        self.assertEqual(row['subcategory'],'Groceries')
        self.assertNotIn('Groceries',suboptions(reconciled,[row],'expense','Food'))
        self.assertIn('Fresh food',suboptions(reconciled,[row],'expense','Food'))

    def test_confirmed_taxonomy_drives_type_and_category_dropdowns(self):
        with tempfile.TemporaryDirectory() as folder:
            with patch.dict(os.environ,{'HOMEACCOUNTS_DATA_DIR':folder}):
                app=AppTest.from_file(str(Path(__file__).resolve().parents[1]/'app.py'),default_timeout=30).run()
                app.text_area[0].set_value('date, amount, currency')
                next(b for b in app.button if b.label=='Suggest fields from my description').click().run()
                app.selectbox(key='setup_currency').set_value('EUR').run()
                app.checkbox(key='apply_taxonomy').check().run()
                self.assertFalse((Path(folder)/'schema.json').exists())
                next(b for b in app.button if b.label=='Confirm fields & continue').click().run()
                self.assertEqual(list(app.exception),[])

                category=next(s for s in app.selectbox if s.label=='Category')
                self.assertIn('Food',category.options); self.assertNotIn('Employment',category.options)
                category.set_value('Food').run()
                sub=next(s for s in app.selectbox if s.label=='Subcategory')
                self.assertIn('Groceries',sub.options); self.assertNotIn('Salary',sub.options)
                next(s for s in app.selectbox if s.label=='Income / expense / transfer').set_value('income').run()
                self.assertIn('Employment',next(s for s in app.selectbox if s.label=='Category').options)
                self.assertEqual(list(app.exception),[])

    def test_coach_uses_parent_and_child_scope(self):
        records=[valid_tx({'date':'2026-10-01','type':'expense','amount':value,'currency':'EUR','account':'Demo','category':'Food','subcategory':sub}) for value,sub in [('12','Groceries'),('30','Dining out')]]
        state={'transactions':records,'budgets':[],'taxonomy':STARTER}
        answer,proposal=coach('Food groceries spending',state,'2026-10','EUR','Demo',dt.date.today())
        self.assertIn('12.00',answer); self.assertNotIn('42.00',answer); self.assertIsNone(proposal)

if __name__=='__main__': unittest.main()
