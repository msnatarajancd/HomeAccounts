"""Isolated Playwright server. Test-only reset is absent from the production server."""
import json
import threading
import tempfile
from pathlib import Path
from http.server import ThreadingHTTPServer
import sys
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from local_api import Service,Handler
from core import read_tables,normalize_import,import_candidates
from schema import suggested_schema,save_schema
import local_api
import ai_client

# Never inherit the developer's real API key for any speech or text endpoint.
ai_client.api_key=lambda:''
local_api.configured=lambda:False
local_api.connection_info=lambda:{'configured':False,'key_available':False,'provider':'OpenAI','model':'gpt-4.1-mini','base_url':'https://api.openai.com/v1','endpoint':'https://api.openai.com/v1/responses','error':None}
root=tempfile.TemporaryDirectory(prefix='homeaccounts-e2e-')
case=0
class FixtureService(Service):
    def state(self):return {**super().state(),'today':'2026-10-11'}
def fixture(seed):
    global case
    case+=1
    service=FixtureService(Path(root.name)/f'case-{case}',backup=False)
    if seed:
        file=Path(__file__).resolve().parents[1]/'sample_data'/'household_demo.csv';raw=file.read_bytes();tables=read_tables(raw,file.name)
        fields,_=suggested_schema(tables['CSV'][0]);save_schema(service.store,fields,'EUR')
        service.save_settings({'currency':'EUR'})
        mapping={'date':'date','description':'particulars','merchant':'merchant','category':'category','subcategory':'subcategory','expense':'expense_amount','income':'income_amount','currency':'currency','account':'account','custom_payment_method':'payment_method'}
        transactions=normalize_import(tables,file.name,raw,mapping,['CSV'],'EUR','Demo',2026,'ISO (YYYY-MM-DD)')['transactions']
        budget_preview=normalize_import(tables,file.name,raw,{'period':'budget_period','category':'category','subcategory':'subcategory','budget':'monthly_budget','currency':'currency'},['CSV'],'EUR','Demo',2026,'ISO (YYYY-MM-DD)','Budgets')
        budgets=import_candidates(budget_preview,service.store.load())[1]
        service.store.commit(transactions,budgets,'','fictional Playwright fixture')
    return service
class TestHandler(Handler):
    def do_POST(self):
        if self.path=='/api/test/stop':
            if self.headers.get('X-HomeAccounts-Token')!=self.server.service.token:return self.send(403,{'error':'Invalid test stop token.'})
            self.send(200,{'status':'stopping'});threading.Thread(target=self.server.shutdown,daemon=True).start();return
        if self.path=='/api/test/reset':
            if not self.safe_origin() or self.headers.get('X-HomeAccounts-Token')!=self.server.service.token:return self.send(403,{'error':'Invalid test reset token.'})
            body=json.loads(self.rfile.read(int(self.headers['Content-Length'])));self.server.service=fixture(body.get('seed',True));return self.send(200,{'status':'reset'})
        return super().do_POST()
if __name__=='__main__':
    server=ThreadingHTTPServer(('127.0.0.1',8765),TestHandler);server.service=fixture(True)
    print('Isolated fictional Playwright server: http://127.0.0.1:8765',flush=True)
    try:server.serve_forever()
    except KeyboardInterrupt:pass
    finally:server.server_close();root.cleanup()
