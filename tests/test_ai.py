import datetime as dt
import io
import json
import unittest
from unittest.mock import patch
import urllib.error
import ai_client as ai
from core import valid_tx

class AITests(unittest.TestCase):
    def state(self):
        return {'transactions':[valid_tx({'date':'2026-10-01','type':'expense','amount':'12.50','currency':'EUR','account':'Demo','category':'Food'})], 'budgets':[]}
    def test_explicit_opt_in_and_safe_http_error(self):
        with patch.object(ai,'api_key',return_value='synthetic-key'),patch.object(ai,'open_request') as send:
            with self.assertRaisesRegex(ValueError,'Enable connected'): ai.request_proposal('test',{}, {},'',enabled=False)
            send.assert_not_called()
            send.side_effect=urllib.error.HTTPError('https://api.openai.com',401,'secret error body',{},None)
            with self.assertRaises(ValueError) as error: ai.request_proposal('test',{}, {},'',enabled=True)
            self.assertNotIn('secret',str(error.exception)); self.assertIn('401',str(error.exception))
    def test_strict_transport_and_complete_response(self):
        response={'status':'completed','output':[{'type':'function_call','name':'test','arguments':'{"value":"demo"}'}]}
        with patch.object(ai,'api_key',return_value='synthetic-key'),patch.object(ai,'open_request',return_value=io.StringIO(json.dumps(response))) as send:
            self.assertEqual(ai.request_proposal('test',{'value':{'type':'string'}},{'fictional':'fields'},'Rules',enabled=True),{'value':'demo'})
            body=json.loads(send.call_args.args[0].data)
            self.assertFalse(body['store']); self.assertTrue(body['tools'][0]['strict'])
            self.assertFalse(body['parallel_tool_calls']); self.assertNotIn('synthetic-key',json.dumps(body))
        response['status']='incomplete'
        with patch.object(ai,'api_key',return_value='synthetic-key'),patch.object(ai,'open_request',return_value=io.StringIO(json.dumps(response))):
            with self.assertRaisesRegex(ValueError,'complete'): ai.request_proposal('test',{}, {},'',enabled=True)
    def test_verified_fact_selection_and_currency_scope(self):
        state=self.state(); state['transactions'].append(valid_tx({'date':'2026-10-01','type':'expense','amount':'999','currency':'INR','account':'Demo'}))
        with patch.object(ai,'request_proposal',return_value={'kind':'answer','fact_ids':['expenses']}) as request:
            answer,proposal=ai.connected_coach('spent?',state,'2026-10','EUR','Demo',dt.date(2026,10,11),enabled=True)
            self.assertIn('12.50',answer); self.assertNotIn('999',answer); self.assertIsNone(proposal)
            context=request.call_args.args[2]; self.assertEqual(context['records_sent'],1)
        with patch.object(ai,'request_proposal',return_value={'kind':'answer','fact_ids':['invented']}):
            with self.assertRaisesRegex(ValueError,'verified'): ai.connected_coach('?',state,'2026-10','EUR','Demo',dt.date.today(),enabled=True)
    def test_action_validation_and_no_mutation(self):
        state=self.state(); original=json.dumps(state)
        proposed={'kind':'add','date':'2026-10-11','type':'income','amount':'1000','currency':'EUR','description':'Fictional earning','merchant':'','category':'Income','subcategory':''}
        with patch.object(ai,'request_proposal',return_value=proposed):
            _,p=ai.connected_coach('earned 1000',state,'2026-10','EUR','Demo',dt.date.today(),enabled=True)
            self.assertEqual(p['rows'][0]['merchant'],''); self.assertEqual(json.dumps(state),original)
        proposed['amount']='NaN'
        with patch.object(ai,'request_proposal',return_value=proposed):
            with self.assertRaises(ValueError): ai.connected_coach('earned',state,'2026-10','EUR','Demo',dt.date.today(),enabled=True)
        with patch.object(ai,'request_proposal',return_value={'kind':'delete','transaction_id':'unknown'}):
            with self.assertRaisesRegex(ValueError,'selected scope'): ai.connected_coach('delete',state,'2026-10','EUR','Demo',dt.date.today(),enabled=True)
    def test_fields_keep_required_structure(self):
        with patch.object(ai,'request_proposal',return_value={'fields':[{'name':'payment method','type':'Text'},{'name':'priority','type':'Number'}]}):
            fields,_=ai.field_suggestions('fictional fields',enabled=True)
            self.assertTrue({'date','type','amount','currency'}<={f['key'] for f in fields})
            self.assertEqual(next(f for f in fields if f['key']=='custom_priority')['type'],'Number')

class ConfigurationTests(unittest.TestCase):
    def test_compatible_endpoint_and_invalid_endpoint_keep_local_available(self):
        with patch.object(ai,'environment',side_effect=lambda name,default='':{'OPENAI_BASE_URL':'https://compatible.example/v1','OPENAI_API_KEY':'synthetic','HOMEACCOUNTS_AI_PROVIDER':'Fictional provider'}.get(name,default)):
            self.assertEqual(ai.base_url(),'https://compatible.example/v1')
            self.assertEqual(ai.connection_info()['endpoint'],'https://compatible.example/v1/responses')
        for url in ('http://untrusted.example/v1','https://user:secret@example.com/v1','https://example.com/v1?key=secret'):
            with patch.object(ai,'environment',side_effect=lambda name,default='',url=url:url if name=='OPENAI_BASE_URL' else default):
                self.assertFalse(ai.connection_info()['configured'])
                self.assertNotIn('secret',str(ai.connection_info()))
    def test_redirects_refused_and_loopback_provider_allowed(self):
        with self.assertRaisesRegex(ValueError,'redirects'):
            ai.NoRedirect().redirect_request(None,None,None,None,None,None)
        with patch.object(ai,'environment',side_effect=lambda name,default='':'http://127.0.0.1:9000/v1' if name=='OPENAI_BASE_URL' else default):
            self.assertEqual(ai.base_url(),'http://127.0.0.1:9000/v1')

if __name__=='__main__': unittest.main()
