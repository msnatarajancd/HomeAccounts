import os
from pathlib import Path
import tempfile
import unittest
from streamlit.testing.v1 import AppTest

APP=Path(__file__).resolve().parents[1]/'app.py'

class AppFlowTests(unittest.TestCase):
    def setUp(self):
        self.folder=tempfile.TemporaryDirectory()
        self.old=os.environ.get('HOMEACCOUNTS_DATA_DIR')
        os.environ['HOMEACCOUNTS_DATA_DIR']=self.folder.name
        self.app=AppTest.from_file(str(APP),default_timeout=30)
        self.app.session_state['manual_start']=True
        self.app.run()
        self.app.selectbox(key='active_currency').set_value('USD').run()
    def tearDown(self):
        if self.old is None: os.environ.pop('HOMEACCOUNTS_DATA_DIR',None)
        else: os.environ['HOMEACCOUNTS_DATA_DIR']=self.old
        self.folder.cleanup()
    def button(self,label): return next(b for b in self.app.button if b.label==label)
    def check_clean(self): self.assertEqual(list(self.app.exception),[])
    def page(self,name): self.app.radio(key='page').set_value(name).run(); self.check_clean()

    def test_all_empty_screens(self):
        for name in ['Overview','Import & review','Add transaction','Transactions','Budgets','Coach','Planning & Goals']: self.page(name)

    def test_sentence_save_requires_confirmation_and_undo(self):
        self.page('Add transaction')
        next(r for r in self.app.radio if r.label=='Entry method').set_value('Sentence').run()
        self.app.text_area[0].set_value('I earned 1000 yesterday')
        self.button('Interpret sentence').click().run(); self.check_clean()
        self.assertTrue(self.app.session_state['pending'])
        from core import Store
        store=Store(self.folder.name)
        self.assertEqual(store.load()['transactions'],[])
        self.button('Confirm save').click().run(); self.check_clean()
        self.assertEqual(store.load()['transactions'][0]['amount'],'1000.00')
        next(c for c in self.app.checkbox if c.label=='Review undo of last save').check().run()
        self.button('Confirm undo').click().run(); self.check_clean()
        self.assertEqual(store.load()['transactions'],[])

    def test_sample_import_confirmation_and_reimport(self):
        self.page('Import & review')
        next(r for r in self.app.radio if r.label=='Data source').set_value('Fictional household demo').run()
        self.button('Prepare import review').click().run(); self.check_clean()
        self.button('Stage reviewed import').click().run(); self.check_clean()
        self.assertFalse(self.button('Confirm save').disabled)
        self.button('Confirm save').click().run(); self.check_clean()
        from core import Store
        self.assertEqual(len(Store(self.folder.name).load()['transactions']),12)
        self.button('Prepare import review').click().run(); self.check_clean()
        self.assertTrue(self.button('Stage reviewed import').disabled)
        next(r for r in self.app.radio if r.label=='Import as').set_value('Budgets').run()
        self.button('Prepare import review').click().run(); self.check_clean()
        self.button('Stage reviewed import').click().run(); self.check_clean()
        self.button('Confirm save').click().run(); self.check_clean()
        self.assertEqual(len(Store(self.folder.name).load()['budgets']),8)
        self.page('Overview'); self.page('Transactions'); self.page('Budgets'); self.page('Coach')

if __name__=='__main__': unittest.main()
