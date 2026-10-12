import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
from local_api import Service,make_server
from schema import suggested_schema,save_schema
from core import valid_tx,valid_budget,Store
from categories import STARTER
import threading
import urllib.request
import urllib.error
import json

class APITests(unittest.TestCase):
    def setUp(self):
        self.folder=tempfile.TemporaryDirectory();self.path=Path(self.folder.name)/'records';self.api=Service(self.path,backup=False)
        rows,_=suggested_schema(['date','particulars','amount','currency','category','subcategory','payment method'])
        self.api.dispatch('/api/setup',{'fields':rows,'currency':'EUR','taxonomy':STARTER})
    def tearDown(self):self.folder.cleanup()
    def test_transcription_routes_only_explicit_consent_and_never_changes_records(self):
        before=self.api.store.load()
        with patch('audio_transcription.transcribe',return_value={'text':'Fictional grocery note'}) as transcribe:
            for consent in (True,False,'true',1,None):
                result=self.api.dispatch('/api/voice/transcribe',{'audio':'fictional','mime':'audio/webm',
                    'transcription_consent':consent,'provider_endpoint':'https://api.openai.com/v1/audio/transcriptions','language':'en'})
                self.assertEqual(result,{'text':'Fictional grocery note'})
                self.assertIs(transcribe.call_args.kwargs['enabled'],consent is True)
                self.assertEqual(transcribe.call_args.kwargs['language'],'en')
        self.assertEqual(self.api.store.load(),before)
    def row(self,**values):return {'date':'2026-10-11','type':'expense','amount':'45','currency':'EUR','account':'Demo','category':'Household','subcategory':'Supplies',**values}
    def test_preview_cannot_mutate_and_confirmation_ignores_client_rows(self):
        review=self.api.dispatch('/api/proposal',{'kind':'add','rows':[self.row(custom_fields={'custom_payment_method':'Demo cash'})]})
        self.assertEqual(self.api.store.load()['transactions'],[])
        self.api.dispatch('/api/proposal/confirm',{'token':review['token'],'rows':[self.row(amount='999')]})
        saved=self.api.store.load()['transactions'][0]
        self.assertEqual(saved['amount'],'45.00');self.assertIn('Demo cash',saved['custom_fields'])
        with self.assertRaises(ValueError):self.api.dispatch('/api/proposal/confirm',{'token':review['token']})
    def test_correction_and_stale_review(self):
        review=self.api.dispatch('/api/proposal',{'kind':'add','rows':[self.row()]})
        updated=self.api.dispatch('/api/proposal/correct',{'token':review['token'],'rows':[self.row(amount='30')]})
        self.api.dispatch('/api/proposal/confirm',{'token':updated['token']})
        with self.assertRaisesRegex(ValueError,'expired'):self.api.dispatch('/api/proposal/confirm',{'token':review['token']})
    def test_split_and_combined_budget_impact(self):
        state=self.api.store.load();b=valid_budget({'period':'2026-10','currency':'EUR','category':'Household','amount':'50'})
        self.api.store.commit([], [b],state['revision'],'synthetic budget')
        review=self.api.dispatch('/api/proposal',{'kind':'add','rows':[self.row(amount='60')],'split':{'amount':'20','category':'Household','subcategory':'Furniture'}})
        self.assertEqual([r['amount'] for r in review['proposal']['rows']],['40.00','20.00'])
        self.assertEqual(len(review['effects']),1);self.assertEqual(review['effects'][0]['current'],'0.00');self.assertEqual(review['effects'][0]['proposed_total'],'60.00');self.assertEqual(review['effects'][0]['over_budget'],'10.00')
        self.assertEqual(self.api.store.load()['transactions'],[])
        with self.assertRaises(ValueError):self.api.dispatch('/api/proposal',{'kind':'add','rows':[self.row(amount='-10')],'split':{'amount':'5','category':'Food'}})
    def test_currency_precision_refunds_and_transfers(self):
        with self.assertRaises(ValueError):self.api.dispatch('/api/proposal',{'kind':'add','rows':[self.row(amount='1.25',currency='JPY')]})
        records=[valid_tx(self.row(amount='100')),valid_tx(self.row(amount='-10')),valid_tx(self.row(type='transfer',amount='1000')),valid_tx(self.row(type='income',amount='500')),valid_tx(self.row(currency='INR',amount='999'))]
        self.api.store.commit(records,[],'','synthetic fixture')
        report=self.api.overview('EUR','2026-10');self.assertEqual(report['expenses']['amount'],'90.00');self.assertEqual(report['surplus']['amount'],'410.00')
    def test_demo_snapshot_and_repeat_import(self):
        file=self.api.dispatch('/api/demo',{})
        mapping={'date':'date','description':'particulars','merchant':'merchant','category':'category','subcategory':'subcategory','expense':'expense_amount','income':'income_amount','currency':'currency','account':'account'}
        body={'file_token':file['file_token'],'selected':['CSV'],'mapping':mapping,'currency':'EUR'}
        first=self.api.dispatch('/api/import/review',body);self.assertEqual(len(first['transactions']),12)
        self.api.dispatch('/api/proposal/confirm',{'token':first['review']['token'],'accept_categories':True})
        repeated=self.api.dispatch('/api/import/review',body);self.assertEqual(repeated['transactions'],[]);self.assertNotIn('review',repeated)
        file=self.api.dispatch('/api/demo',{'filename':'balances_wishlist_demo.csv'})
        result=self.api.dispatch('/api/import/review',{**body,'file_token':file['file_token'],'mapping':{'amount':'amount'}})
        self.assertTrue(result['issues']);self.assertNotIn('review',result)
    def test_settings_persist_preserve_legacy_currency_and_records(self):
        self.api.save_settings({'theme':'bright','home':'coach','currency':'INR'})
        loaded=Service(self.path,backup=False);self.assertEqual(loaded.settings,{'theme':'bright','home':'coach','currency':'INR'})
        self.assertEqual(json.loads((self.path/'preferences.json').read_text())['currency'],'INR')
        self.assertEqual(loaded.store.load()['transactions'],[])
        with self.assertRaises(ValueError):loaded.save_settings({'theme':'invented'})
    def test_local_chat_navigation_and_undo_without_model_calls(self):
        with patch('local_api.connected_coach') as model:
            result=self.api.dispatch('/api/chat',{'text':'Open compound growth','currency':'EUR','month':'2026-10','use_ai':False})
            self.assertEqual(result['links'][0]['href'],'/planning?tab=growth');model.assert_not_called()
        add=self.api.dispatch('/api/proposal',{'kind':'add','rows':[self.row()]});self.api.dispatch('/api/proposal/confirm',{'token':add['token']})
        undo=self.api.dispatch('/api/undo/review',{'currency':'EUR','month':'2026-10'})
        self.assertEqual(len(self.api.store.load()['transactions']),1)
        self.api.dispatch('/api/proposal/confirm',{'token':undo['review']['token']})
        self.assertEqual(self.api.store.load()['transactions'],[])
    def test_calculators_are_read_only_and_zero_budget_explicit(self):
        result=self.api.dispatch('/api/planning',{'kind':'growth','currency':'JPY','inputs':{'principal':'1000','contribution':'100','years':0,'annual_rate':5,'periods':1,'frequency':'Annual','timing':'End','inflation':2}})
        self.assertEqual(result['rows'][-1]['Projected value'],1000)
        result=self.api.dispatch('/api/planning',{'kind':'variance','currency':'EUR','inputs':{'budget':'0','actual':'15'}})
        self.assertIsNone(result['percent']);self.assertEqual(self.api.store.load()['revision'],'')

    def test_chat_entry_does_not_get_intercepted_by_tool_words(self):
        for text in ('I spent 45 at Springfield yesterday', 'I paid 45 for fire insurance today',
                     'I spent 45 on imported household supplies today'):
            with self.subTest(text=text):
                result=self.api.chat({'text':text,'currency':'EUR','month':'2026-10','reference_date':'2026-10-11'})
                self.assertIsNotNone(result.get('review'))
                self.assertEqual(result['review']['proposal']['rows'][0]['amount'],'45.00')
        self.assertEqual(self.api.store.load()['transactions'],[])

    def test_budget_correction_moves_limit_and_previews_both_months(self):
        old=valid_budget({'period':'2026-10','currency':'EUR','category':'Household','amount':'50'})
        self.api.store.commit([], [old], '', 'fictional budget')
        review=self.api.dispatch('/api/proposal',{'kind':'budget','rows':[{**old,'amount':'60'}]})
        updated=self.api.correct({'token':review['token'],'rows':[{'period':'2026-11','category':'Insurance','amount':'70'}]})
        changes={c['month']:c for c in updated['changes']}
        self.assertEqual(changes['2026-10']['proposed_budget'],'0.00')
        self.assertEqual(changes['2026-11']['proposed_budget'],'70.00')
        self.assertEqual(self.api.store.load()['budgets'],[old])
        self.api.confirm({'token':updated['token'],'accept_categories':True})
        saved=self.api.store.load()['budgets']
        self.assertEqual(len(saved),1)
        self.assertEqual((saved[0]['id'],saved[0]['period'],saved[0]['category']),(old['id'],'2026-11','Insurance'))
        undo=self.api.dispatch('/api/undo/review',{'currency':'EUR','month':'2026-11'})
        self.api.dispatch('/api/proposal/confirm',{'token':undo['review']['token']})
        self.assertEqual(self.api.store.load()['budgets'],[old])

    def test_budget_correction_collision_is_rejected_before_confirmation(self):
        budgets=[valid_budget({'period':'2026-10','currency':'EUR','category':category,'amount':'50'})
                 for category in ('Household','Insurance')]
        self.api.store.commit([],budgets,'','fictional budgets')
        review=self.api.dispatch('/api/proposal',{'kind':'budget','rows':[{**budgets[0],'amount':'60'}]})
        with self.assertRaisesRegex(ValueError,'already exists'):
            self.api.correct({'token':review['token'],'rows':[{'category':'Insurance'}]})
        self.assertEqual(self.api.store.load()['budgets'],budgets)

    def test_successful_correction_retires_original_preview(self):
        review=self.api.dispatch('/api/proposal',{'kind':'add','rows':[self.row()]})
        updated=self.api.correct({'token':review['token'],'rows':[{'amount':'30'}]})
        with self.assertRaisesRegex(ValueError,'expired'):
            self.api.confirm({'token':review['token']})
        self.assertEqual(self.api.store.load()['transactions'],[])
        self.api.confirm({'token':updated['token']})
        self.assertEqual(self.api.store.load()['transactions'][0]['amount'],'30.00')

    def test_other_save_still_rejects_a_stale_preview(self):
        first=self.api.dispatch('/api/proposal',{'kind':'add','rows':[self.row()]})
        other=self.api.dispatch('/api/proposal',{'kind':'add','rows':[self.row(amount='20')]})
        self.api.confirm({'token':other['token']})
        with self.assertRaisesRegex(ValueError,'changed'):
            self.api.confirm({'token':first['token']})
        self.assertEqual(len(self.api.store.load()['transactions']),1)
    def test_backup_keeps_existing_revision_usable(self):
        self.api.store.commit([valid_tx(self.row())],[],'','synthetic')
        old=self.api.store.load()['revision'];self.api.settings_path.unlink()
        loaded=Service(self.path,backup=True);self.assertEqual(loaded.store.load()['revision'],old)
        backups=list((self.path.parent/'records-backups').iterdir());self.assertEqual(len(backups),1)
        self.assertEqual(Store(backups[0]).load()['revision'],old)

    def test_provider_destination_change_requires_new_consent(self):
        info={'configured':True,'endpoint':'https://compatible.example/v1/responses','error':None}
        with patch('local_api.connection_info',return_value=info),patch('local_api.connected_coach') as model:
            with self.assertRaisesRegex(ValueError,'consent'):
                self.api.dispatch('/api/chat',{'text':'monthly summary','currency':'EUR','month':'2026-10','use_ai':True,'provider_endpoint':'https://api.openai.com/v1/responses'})
            model.assert_not_called()
            model.return_value=('Verified fictional response.',None)
            result=self.api.dispatch('/api/chat',{'text':'monthly summary','currency':'EUR','month':'2026-10','use_ai':True,'provider_endpoint':info['endpoint']})
            self.assertEqual(result['answer'],'Verified fictional response.')

class HTTPTests(unittest.TestCase):
    def test_routes_same_origin_and_confirmation_token(self):
        with tempfile.TemporaryDirectory() as folder:
            server=make_server(0,folder,False);thread=threading.Thread(target=server.serve_forever,daemon=True);thread.start();url=f'http://127.0.0.1:{server.server_port}'
            try:
                self.assertIn(b'Home Accounts',urllib.request.urlopen(url+'/budgets').read())
                request=urllib.request.Request(url+'/api/settings',data=b'{"theme":"dark"}',headers={'Content-Type':'application/json'})
                with self.assertRaises(urllib.error.HTTPError) as error:urllib.request.urlopen(request)
                self.assertEqual(error.exception.code,403)
                request=urllib.request.Request(url+'/api/state',headers={'Origin':'https://example.org'})
                with self.assertRaises(urllib.error.HTTPError):urllib.request.urlopen(request)
                state=json.load(urllib.request.urlopen(url+'/api/state'));self.assertNotIn('api_key',state['ai'])
                request=urllib.request.Request(url+'/api/settings',data=b'{"theme":"dark"}',headers={'Content-Type':'application/json','X-HomeAccounts-Token':state['csrf']})
                self.assertEqual(json.load(urllib.request.urlopen(request))['theme'],'dark')
            finally:server.shutdown();server.server_close();thread.join()

if __name__=='__main__':unittest.main()
