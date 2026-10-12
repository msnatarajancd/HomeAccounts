"""Local HTTP API for the routed Home Accounts UI; domain logic remains in core."""
import base64
import csv
import datetime as dt
from decimal import Decimal, InvalidOperation
import hashlib
import hmac
import json
import mimetypes
import os
from pathlib import Path
import re
import secrets
import shutil
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import urlsplit, parse_qs
from core import Store,TX_FIELDS,BUDGET_FIELDS,MONTHS,read_tables,normalize_import,import_candidates,valid_tx,valid_budget,budget_key,replace_budgets,spending,income,total_budget,cents,amount,impacts,coach,apply_proposal,csv_bytes,fingerprint
from currencies import CODES,label,validate,display_minor,scale,digits,search_terms
from schema import load_schema,save_schema,schema_path,suggested_schema,interpret_fields,validate_schema,custom_definitions,parse_custom
from categories import STARTER,reconcile,catalog,additions_for
from planning import compound_growth,fire_target,variance
from ai_client import configured,model_name,connected_coach,field_suggestions,base_url,provider_name,connection_info
import live_voice
import audio_transcription

ROOT=Path(__file__).resolve().parent
ROUTES={'/','/overview','/transactions','/budgets','/coach','/planning','/import','/entry','/settings','/setup','/learn'}

class Service:
    def __init__(self,folder=None,backup=True):
        self.store=Store(folder or os.environ.get('HOMEACCOUNTS_DATA_DIR',str(ROOT/'data')))
        self.lock=threading.RLock(); self.proposals={}; self.files={}; self.token=secrets.token_urlsafe(32)
        self.settings_path=self.store.path/'ui-settings.json'
        if backup and self.store.path.exists() and not self.settings_path.exists() and any(self.store.path.iterdir()):
            target=self.store.path.parent/(self.store.path.name+'-backups')/(dt.datetime.now().strftime('%Y%m%d-%H%M%S')+'-'+secrets.token_hex(3))
            shutil.copytree(self.store.path,target)
        self.settings=self.read_settings()
        if not self.settings_path.exists(): self.save_settings({})
    def read_settings(self):
        legacy=self.store.path/'preferences.json'
        previous=json.loads(legacy.read_text(encoding='utf-8')) if legacy.exists() else {}
        values=json.loads(self.settings_path.read_text(encoding='utf-8')) if self.settings_path.exists() else {}
        return {'theme':'light','home':'overview','currency':previous.get('currency'),**values}
    def save_settings(self,values):
        allowed={'theme','home','currency'}
        if not set(values)<=allowed: raise ValueError('Unsupported setting.')
        current={**self.settings,**values}
        if current['theme'] not in ('light','dark','bright') or current['home'] not in ('overview','coach'): raise ValueError('Choose a supported theme and home screen.')
        if current['currency'] is not None: current['currency']=validate(current['currency'])
        self.store.path.mkdir(parents=True,exist_ok=True)
        temp=self.settings_path.with_suffix('.tmp'); temp.write_text(json.dumps(current),encoding='utf-8'); os.replace(temp,self.settings_path)
        self.settings=current
        # Legacy app still reads the same currency preference.
        legacy=self.store.path/'preferences.json'
        prior=json.loads(legacy.read_text(encoding='utf-8')) if legacy.exists() else {}
        temp=legacy.with_suffix('.tmp'); temp.write_text(json.dumps({**prior,'currency':current['currency']}),encoding='utf-8'); os.replace(temp,legacy)
        return current
    def state(self):
        state=self.store.load()
        schema=load_schema(self.store)
        return {**state,'schema':schema,'settings':self.settings,
            'category_catalog':self.category_catalog(state,schema),
            'setup_complete':schema_path(self.store).exists() or bool(state['revision']),
            'currencies':[{'code':c,'label':label(c),'digits':digits(c),'search_terms':search_terms(c)} for c in CODES],
            'ai':connection_info(),'live_voice':live_voice.connection_info(),'transcription':audio_transcription.connection_info(),'starter_taxonomy':STARTER,'today':dt.date.today().isoformat(),'csrf':self.token}
    def category_catalog(self,state,schema=None):
        schema=load_schema(self.store) if schema is None else schema
        return catalog(schema.get('taxonomy',[]),state['transactions'],state['budgets'],state.get('known_categories',[]))
    def catalog_signature(self,choices):
        return hashlib.sha256(json.dumps(choices,sort_keys=True,ensure_ascii=False).encode()).hexdigest()
    def validate_categories(self,proposal,state):
        choices=self.category_catalog(state)
        kind=proposal['kind']
        rows=[{**r,'type':'expense'} for r in proposal['rows']] if kind=='budget' else proposal.get('rows',[])
        rows=rows+[{**r,'type':'expense'} for r in proposal.get('budgets',[])]
        before=[{**r,'type':'expense'} for r in proposal.get('before',[])] if kind=='budget' else proposal.get('before',[])
        return additions_for(rows,choices,before,importing=kind=='import'),self.catalog_signature(choices)
    def overview(self,curr,period):
        curr=validate(curr); dt.date.fromisoformat(period+'-01')
        state=self.store.load(); tx=state['transactions']; budgets=state['budgets']
        scoped=[t for t in tx if t['currency']==curr and t['date'][:7]==period]
        bs=[b for b in budgets if b['currency']==curr and b['period']==period]
        inc=income(tx,period,curr); exp=spending(tx,period,curr); planned=total_budget(bs,period,curr)
        def metric(n): return {'minor':n,'amount':amount(n,curr),'display':display_minor(n,curr)}
        cats=sorted({t['category'] for t in scoped if t['type']=='expense'}|{b['category'] for b in bs})
        rows=[]
        for cat in cats:
            part=[b for b in bs if b['category']==cat]; actual=spending(tx,period,curr,cat); limit=total_budget(part,period,curr)
            rows.append({'category':cat,'actual':metric(actual),'budget':metric(limit) if part else None,'remaining':metric(limit-actual) if part else None})
        months=sorted({t['date'][:7] for t in tx if t['currency']==curr})
        reports=[{'month':m,'income':metric(income(tx,m,curr)),'expenses':metric(spending(tx,m,curr))} for m in months]
        limits=[{**b,'spent':metric(spending(tx,period,curr,b['category'],b['subcategory'])),
            'remaining':metric(cents(b['amount'],curr=curr)-spending(tx,period,curr,b['category'],b['subcategory']))} for b in bs]
        return {'month':period,'currency':curr,'count':len(scoped),'all_count':len(tx),'record_currencies':sorted({t['currency'] for t in tx}),
            'income':metric(inc),'expenses':metric(exp),'surplus':metric(inc-exp),'budget':metric(planned) if bs else None,
            'remaining':metric(planned-exp) if bs else None,'categories':rows,'months':reports,'budgets':limits,
            'recent':sorted(scoped,key=lambda t:t['date'],reverse=True)[:8]}
    def export_transactions(self,query):
        """Apply the grid's filters and ordering without changing saved records."""
        custom={f['key']:f for f in custom_definitions(load_schema(self.store))}
        allowed={'date','type','description','category','subcategory','amount','currency','account'}|set(custom)
        filters={name.removeprefix('column_'):str(value).strip().casefold()
                 for name,value in query.items() if name.startswith('column_')}
        if set(filters)-allowed:
            raise ValueError('Unsupported export column filter. Choose a displayed transaction column.')
        sort=str(query.get('sort','date')).strip()
        direction=str(query.get('sort_dir','desc')).strip().lower()
        if sort not in allowed: raise ValueError('Unsupported export sort column. Choose a displayed transaction column.')
        if direction not in ('asc','desc'): raise ValueError('Export sort direction must be asc or desc.')
        def value(row,column):
            if column not in custom: return str(row.get(column,''))
            try: values=json.loads(row.get('custom_fields') or '{}')
            except (ValueError,TypeError): return ''
            item=values.get(column,'') if isinstance(values,dict) else ''
            if isinstance(item,bool): return str(item).lower()
            return '' if item is None else str(item)
        scope={name:str(query.get(name,'')).strip() for name in ('currency','month','category','type','search')}
        rows=[row for row in self.store.load()['transactions']
              if (not scope['currency'] or row['currency']==scope['currency'])
              and (not scope['month'] or row['date'][:7]==scope['month'])
              and (not scope['category'] or row['category']==scope['category'])
              and (not scope['type'] or row['type']==scope['type'])
              and (not scope['search'] or scope['search'].casefold() in ' '.join(row.values()).casefold())
              and all(text in value(row,column).casefold() for column,text in filters.items())]
        reverse=direction=='desc'
        if sort=='amount' or custom.get(sort,{}).get('type')=='Number':
            numeric=[]; other=[]
            for row in rows:
                try:
                    number=Decimal(value(row,sort).strip())
                    if not number.is_finite(): raise InvalidOperation
                    numeric.append((number,row))
                except (InvalidOperation,ValueError): other.append(row)
            # Missing/invalid legacy custom values stay last in either direction.
            return [row for _,row in sorted(numeric,key=lambda item:item[0],reverse=reverse)]+sorted(other,key=lambda row:value(row,sort).casefold(),reverse=reverse)
        return sorted(rows,key=lambda row:value(row,sort).casefold(),reverse=reverse)
    def valid_record(self,row):
        schema=load_schema(self.store)
        values=row.get('custom_fields',{})
        if isinstance(values,str): values=json.loads(values or '{}')
        if not isinstance(values,dict): raise ValueError('Custom fields must be an object.')
        values={**values}
        for field in custom_definitions(schema): values[field['key']]=parse_custom(values.get(field['key'],''),field['type'])
        return valid_tx({**row,'custom_fields':json.dumps(values,ensure_ascii=False)})
    def stage(self,proposal,state=None):
        state=state or self.store.load()
        proposal={**proposal,'revision':state['revision']}
        kind=proposal['kind']
        if kind in ('add','edit'): proposal['rows']=[self.valid_record(row) for row in proposal['rows']]
        if kind=='budget': proposal['rows']=[valid_budget(row) for row in proposal['rows']]
        if kind in ('add','edit','budget','import'):
            proposal['category_additions'],proposal['catalog_signature']=self.validate_categories(proposal,state)
        token=secrets.token_urlsafe(24)
        review=self.preview(token,proposal,state)
        self.proposals={k:v for k,v in self.proposals.items() if v['expires']>time.time()}
        self.proposals[token]={'proposal':proposal,'expires':time.time()+3600}
        return review
    def preview(self,token,proposal,state):
        base=[t for t in state['transactions'] if t['id'] not in {b['id'] for b in proposal.get('before',[]) }]
        combined=base+proposal.get('rows',[]) if proposal['kind']!='budget' else state['transactions']
        effects=[]
        changed=proposal.get('rows',[])+proposal.get('before',[])
        if proposal['kind']!='budget':
            for b in state['budgets']:
                if any(r.get('type')=='expense' and r['date'][:7]==b['period'] and r['currency']==b['currency'] and r['category']==b['category'] and (not b['subcategory'] or r['subcategory']==b['subcategory']) for r in changed):
                    curr=b['currency']; old=spending(state['transactions'],b['period'],curr,b['category'],b['subcategory']); new=spending(combined,b['period'],curr,b['category'],b['subcategory']); limit=cents(b['amount'],curr=curr)
                    effects.append({'category':b['category'],'subcategory':b['subcategory'],'currency':curr,'budget':b['amount'],'current':amount(old,curr),'proposed_total':amount(new,curr),'over_budget':amount(max(0,new-limit),curr)})
        proposed_budgets=list(proposal.get('budgets',[])) if proposal['kind']=='undo' else list(state['budgets'])
        incoming=proposal.get('rows',[]) if proposal['kind']=='budget' else proposal.get('budgets',[])
        if proposal['kind']=='budget':
            proposed_budgets=replace_budgets(state['budgets'],incoming,proposal.get('before',[]))
        elif incoming and proposal['kind']!='undo':
            keys={budget_key(b) for b in incoming}; proposed_budgets=[b for b in proposed_budgets if budget_key(b) not in keys]+incoming
        scopes={(r['date'][:7],r['currency']) for r in changed if 'date' in r}|{(b['period'],b['currency']) for b in incoming}
        if proposal['kind']=='budget': scopes|={(b['period'],b['currency']) for b in proposal.get('before',[])}
        if proposal['kind']=='undo':
            scopes|={(b['period'],b['currency']) for b in state['budgets']+proposed_budgets}
            effects=[]
        changes=[{'month':period,'currency':curr,'current_expenses':amount(spending(state['transactions'],period,curr),curr),'proposed_expenses':amount(spending(combined,period,curr),curr),'current_income':amount(income(state['transactions'],period,curr),curr),'proposed_income':amount(income(combined,period,curr),curr),'current_budget':amount(total_budget(state['budgets'],period,curr),curr),'proposed_budget':amount(total_budget(proposed_budgets,period,curr),curr)} for period,curr in sorted(scopes)]
        seen={fingerprint(t) for t in base}; duplicate=[]
        for row in proposal.get('rows',[]) if proposal['kind']!='budget' else []:
            if fingerprint(row) in seen: duplicate.append(row['id'])
            seen.add(fingerprint(row))
        uncategorized=any(t.get('category')=='Uncategorized' for t in proposal.get('rows',[]) if proposal['kind']!='budget')
        return {'token':token,'proposal':proposal,'effects':effects,'duplicates':duplicate,'uncategorized':uncategorized,'changes':changes,
            'category_additions':proposal.get('category_additions',[])}
    def confirm(self,body):
        item=self.proposals.get(body['token'])
        if not item or item['expires']<time.time(): raise ValueError('This preview expired. Prepare a new review.')
        state=self.store.load(); proposal=item['proposal']
        if state['revision']!=proposal['revision']: raise ValueError('Records changed since preview. Prepare and review again.')
        if proposal['kind'] in ('add','edit','budget','import'):
            additions,signature=self.validate_categories(proposal,state)
            if signature!=proposal.get('catalog_signature'):
                raise ValueError('Category choices changed since preview. Prepare and review again.')
            if additions and body.get('accept_categories') is not True:
                raise ValueError('Review and acknowledge the new shared category/subcategory choices before saving.')
        if proposal['kind']=='clear' and body.get('confirm_clear') is not True:
            raise ValueError('Acknowledge that this clears all transactions across every month and currency.')
        check=self.preview(body['token'],proposal,state)
        if check['duplicates'] and not body.get('accept_duplicates'): raise ValueError('Review and acknowledge possible duplicates.')
        if check['uncategorized'] and not body.get('accept_uncategorized'): raise ValueError('Review and acknowledge uncategorized records.')
        revision=apply_proposal(self.store,state,proposal)
        self.proposals.pop(body['token'],None)
        message='All transactions cleared. Budgets and settings kept. Undo is available.' if proposal['kind']=='clear' else 'Confirmed and saved. Undo is available.'
        return {'revision':revision,'message':message}
    def correct(self,body):
        item=self.proposals.get(body['token'])
        if not item or item['expires']<time.time(): raise ValueError('Preview expired.')
        proposal=item['proposal']; kind=proposal['kind']
        if kind not in ('add','edit','budget'): raise ValueError('Correct imports through their source mapping.')
        rows=body['rows']
        if len(rows)!=len(proposal['rows']): raise ValueError('Keep the same number of proposed records.')
        validated=[]
        for current,row in zip(proposal['rows'],rows):
            merged={**current,**row,'id':current['id'],'source_ref':current.get('source_ref','')}
            validated.append(valid_budget(merged) if kind=='budget' else self.valid_record(merged))
        state=self.store.load()
        if state['revision']!=proposal['revision']: self.stale()
        review=self.stage({**proposal,'rows':validated},state)
        self.proposals.pop(body['token'],None)
        return review
    def stale(self): raise ValueError('Records changed since preview. Start again.')
    def upload(self,body):
        filename=Path(str(body.get('filename',''))).name
        if not filename.lower().endswith(('.csv','.tsv','.xlsx')): raise ValueError('Choose CSV, TSV or XLSX.')
        try: raw=base64.b64decode(body.get('data',''),validate=True)
        except ValueError: raise ValueError('Invalid uploaded file encoding.') from None
        if len(raw)>10_000_000: raise ValueError('Maximum file size is 10 MB.')
        tables=read_tables(raw,filename)
        available=[name for name,rows in tables.items() if rows and any(rows[0])]
        if not available: raise ValueError('This file has no headers. Describe fields instead.')
        selected=next((s for s in MONTHS if s in available),available[0])
        fields,notes=suggested_schema(tables[selected][0]); token=secrets.token_urlsafe(24)
        self.files[token]={'raw':raw,'filename':filename,'tables':tables,'expires':time.time()+3600}
        snapshot=filename.casefold()=='cash in hand.xlsx' or 'Desired Items' in tables or any({'record kind','as of'}<={str(h).casefold().replace('_',' ') for h in rows[0]} for rows in tables.values() if rows)
        self.files[token]['snapshot']=snapshot
        return {'snapshot':snapshot,'file_token':token,'filename':filename,'sheets':available,'selected':selected,'headers':tables[selected][0],
            'sample':tables[selected][1:6],'fields':fields,'notes':notes}
    def import_preview(self,body):
        file=self.files.get(body['file_token'])
        if not file or file['expires']<time.time(): raise ValueError('Upload expired. Choose the file again.')
        if file.get('snapshot'):
            return {'issues':[{'row':1,'error':'This file contains balance snapshots, dues or wishes, not transaction history.'}],'conflicts':[],'skipped':0,'repeated':0,'transactions':[],'budgets':[],'possible_duplicates':[]}
        selected=body['selected']
        if not selected or any(s not in file['tables'] for s in selected): raise ValueError('Select valid sheets.')
        preview=normalize_import(file['tables'],file['filename'],file['raw'],body['mapping'],selected,body['currency'],
            body.get('account','Unspecified account'),int(body.get('year',dt.date.today().year)),body.get('date_style','ISO (YYYY-MM-DD)'),body.get('kind','Transactions'))
        for row in preview['transactions']:
            row['id']=hashlib.sha256((row['source_ref']+':transaction').encode()).hexdigest()[:12]
            try: row.update(self.valid_record(row))
            except ValueError as exc: preview['issues'].append({'row':row['source_ref'],'error':str(exc)})
        state=self.store.load(); tx,bs,duplicates,conflicts=import_candidates(preview,state)
        ids={t['id'] for t in tx}
        excluded=set(body.get('exclude',[]))
        if not excluded<=ids: raise ValueError('Exclude only records in this preview.')
        tx=[t for t in tx if t['id'] not in excluded]
        result={'issues':preview['issues'],'conflicts':conflicts,'skipped':preview['skipped'],'repeated':len(preview['transactions'])-len(tx)-len(excluded),
            'transactions':tx,'budgets':bs,'possible_duplicates':duplicates}
        if not preview['issues'] and not conflicts and (tx or bs): result['review']=self.stage({'kind':'import','rows':tx,'budgets':bs},state)
        return result
    def require_provider_consent(self,body):
        info=connection_info()
        if not info['configured']: raise ValueError(info.get('error') or 'Connected API is not configured. Use local mode.')
        if body.get('provider_endpoint')!=info['endpoint']:
            raise ValueError('Provider configuration changed or consent is missing. Refresh, review the destination and enable connected mode again.')

    def chat(self,body):
        text=str(body.get('text','')).strip()
        if not text or len(text)>6000: raise ValueError('Enter a question of at most 6,000 characters.')
        state=self.store.load(); state['taxonomy']=self.category_catalog(state)
        curr=validate(body['currency']); period=body['month']; dt.date.fromisoformat(period+'-01')
        reference=dt.date.fromisoformat(body.get('reference_date',dt.date.today().isoformat()))
        lower=text.casefold()
        links=[]
        navigation={'overview':'/overview','transaction':'/transactions','budget':'/budgets','import':'/import','upload':'/import','field':'/setup','categor':'/setup','compound':'/planning?tab=growth','fire':'/planning?tab=fire','saving goal':'/planning?tab=goals','variance':'/planning?tab=variance','learn':'/learn','theme':'/settings','setting':'/settings','export':'/transactions','split':'/entry','refund':'/entry','transfer':'/entry'}
        record_request=bool(re.match(r'(?:(?:i\s+)?(?:spent|paid|earned|received|refund|bought)\b|(?:change|delete) transaction\b|set .+? budget\b)',lower))
        matched=set()
        for word,href in navigation.items():
            pattern={'categor':r'categor(?:y|ies)','saving goal':r'savings? goals?'}.get(word,re.escape(word)+r's?')
            if re.search(r'\b'+pattern+r'\b',lower):
                matched.add(word)
                links.append({'label':'Open '+('Categories' if word=='categor' else word.title()),'href':href})
        if lower in ('undo','undo last save','undo the last save'):
            if not state['history']: return {'answer':'There is no saved change to undo.','links':links}
            previous=state['history'][-1]
            if previous:
                folder=self.store.path/'revisions'/previous
                def read(name):
                    with (folder/name).open(encoding='utf-8-sig',newline='') as file: return list(csv.DictReader(file))
                restored_tx=read('transactions.csv'); restored_budgets=read('budgets.csv')
            else: restored_tx=[]; restored_budgets=[]
            old={r['id']:r for r in state['transactions']}; restored={r['id']:r for r in restored_tx}
            changed_before=[r for id,r in old.items() if restored.get(id)!=r]
            changed_after=[r for id,r in restored.items() if old.get(id)!=r]
            proposal={'kind':'undo','revision':state['revision'],'before':changed_before,'rows':changed_after,
                'budgets':restored_budgets,'budget_before':state['budgets'],'undo_counts':{'current_transactions':len(state['transactions']),'restored_transactions':len(restored_tx),'current_budgets':len(state['budgets']),'restored_budgets':len(restored_budgets)}}
            review=self.stage(proposal,state)
            return {'answer':'Review the exact records and counts that undo restores.','review':review,'links':links}
        if any(lower.startswith(prefix) for prefix in ('open ','show me the ','go to ')) and links:
            return {'answer':'Use this workspace to inspect records or review changes. Nothing has been saved.','links':links}
        tool_words={'compound','fire','saving goal','variance','export','upload','import','field','theme','setting','split'}
        if (not record_request and matched&tool_words) or 'split' in matched:
            return {'answer':'I can open the right tool. Enter your assumptions or upload locally there, then review the results. Calculators never change records; imports and record changes require confirmation.','links':links}
        if body.get('use_ai') is True: self.require_provider_consent(body)
        answer,proposal=connected_coach(text,state,period,curr,body.get('account','Unspecified account'),reference,enabled=True,history=body.get('history',[])[:6]) if body.get('use_ai') is True else coach(text,state,period,curr,body.get('account','Unspecified account'),reference)
        return {'answer':answer,'review':self.stage(proposal,state) if proposal else None,'links':links}
    def dispatch(self,path,body):
        with self.lock:
            if path=='/api/settings': return self.save_settings(body)
            if path=='/api/voice/transcribe':
                return audio_transcription.transcribe(body.get('audio'),body.get('mime'),enabled=body.get('transcription_consent') is True,
                    provider_endpoint=body.get('provider_endpoint'),language=body.get('language',''))
            if path=='/api/voice/session':
                context=body.get('context') if isinstance(body.get('context'),dict) else {}
                return live_voice.create_session(body.get('sdp'),enabled=body.get('live_consent') is True,
                    provider_endpoint=body.get('provider_endpoint'),page=context.get('page'),
                    scope={k:context[k] for k in ('currency','month') if k in context})
            if path=='/api/fields/suggest':
                if body.get('use_ai') is True: self.require_provider_consent(body)
                fields,notes=field_suggestions(body.get('description',''),enabled=True) if body.get('use_ai') is True else interpret_fields(body.get('description',''))
                return {'fields':fields,'notes':notes}
            if path=='/api/setup':
                rows=validate_schema(body['fields']); curr=validate(body['currency'])
                current=load_schema(self.store).get('taxonomy',[])
                taxonomy=body.get('taxonomy')
                state=self.store.load()
                if taxonomy is not None: reconcile(taxonomy,current,state['transactions'],state['budgets'])
                save_schema(self.store,rows,curr,taxonomy); self.save_settings({'currency':curr})
                return {'message':'Fields confirmed. Existing records are preserved. Imports still require a separate confirmation.'}
            if path=='/api/upload': return self.upload(body)
            if path=='/api/upload/sheet':
                file=self.files.get(body['file_token'])
                if not file or file['expires']<time.time(): raise ValueError('Upload expired.')
                sheet=body['sheet']
                if sheet not in file['tables'] or not file['tables'][sheet]: raise ValueError('Sheet not found.')
                return {'headers':file['tables'][sheet][0],'sample':file['tables'][sheet][1:6]}
            if path=='/api/observed':
                curr=validate(body['currency']); year=str(body['year'])
                if not re.fullmatch(r'\d{4}',year): raise ValueError('Choose an observed year.')
                rows=[t for t in self.store.load()['transactions'] if t['currency']==curr and t['date'].startswith(year)]
                months={t['date'][:7] for t in rows}
                net=sum(cents(t['amount'],True,curr) for t in rows if t['type']=='expense' and t['category'] not in body.get('exclude',[]))
                estimate=round(max(0,net)*12/len(months)) if months else 0
                dates=sorted(t['date'] for t in rows)
                note=f'Observed {dates[0]} to {dates[-1]} across {len(months)} months; net expense {amount(net,curr)} {curr}. Annualized = observed net expense / observed months x 12; partial history can distort this estimate. Override as needed.' if dates else 'No observed records. Enter your own annual expense assumption.'
                return {'estimate':amount(estimate,curr),'note':note}

            if path=='/api/demo':
                filename=body.get('filename','household_demo.csv')
                if filename not in ('household_demo.csv','balances_wishlist_demo.csv','us_household_transactions.csv','us_household_budgets.csv'): raise ValueError('Unknown sample.')
                return self.upload({'filename':filename,'data':base64.b64encode((ROOT/'sample_data'/filename).read_bytes()).decode()})
            if path=='/api/import/review': return self.import_preview(body)
            if path=='/api/transactions/clear/review':
                state=self.store.load()
                if not state['transactions']: raise ValueError('There are no transactions to clear.')
                return self.stage({'kind':'clear','rows':[],'before':state['transactions'],
                    'clear_count':len(state['transactions'])},state)
            if path=='/api/proposal':
                state=self.store.load(); kind=body['kind']
                if kind not in ('add','edit','delete','budget'): raise ValueError('Unsupported action.')
                before=[]; rows=body.get('rows',[])
                if kind in ('edit','delete'):
                    old=next((t for t in state['transactions'] if t['id']==body.get('id')),None)
                    if not old: raise ValueError('Record no longer exists.')
                    before=[old]
                    rows=[{**old,**rows[0],'id':old['id'],'source_ref':old['source_ref']}] if kind=='edit' else []
                if kind=='add':
                    if not 1<=len(rows)<=2: raise ValueError('Add one record or a two-way split.')
                    rows=[{**row,'id':'','source_ref':''} for row in rows]
                    if body.get('split'):
                        if len(rows)!=1: raise ValueError('Split one expense at a time.')
                        row=self.valid_record(rows[0]); split=body['split']; curr=row['currency']
                        total=cents(row['amount'],True,curr); second=cents(split['amount'],curr=curr)
                        if row['type']!='expense' or not 0<second<total: raise ValueError('A split needs a positive expense and second amount between zero and total.')
                        rows=[{**row,'amount':amount(total-second,curr),'id':''},{**row,'amount':amount(second,curr),'id':'','category':split['category'],'subcategory':split.get('subcategory','')}]

                if kind=='budget':
                    if len(rows)!=1: raise ValueError('Propose one budget at a time.')
                    row=valid_budget({**rows[0],'id':'','source_ref':''})
                    old=next((b for b in state['budgets'] if budget_key(b)==budget_key(row)),None)
                    if old: row.update(id=old['id'],source_ref=old['source_ref']); before=[old]
                    rows=[row]
                return self.stage({'kind':kind,'rows':rows,'before':before},state)
            if path=='/api/proposal/correct': return self.correct(body)
            if path=='/api/proposal/confirm':
                item=self.proposals.get(body.get('token'))
                if item and item['proposal']['kind']=='undo':
                    if item['expires']<time.time(): raise ValueError('This undo preview expired.')
                    self.store.undo(item['proposal']['revision']); self.proposals.pop(body['token'],None); return {'message':'Last save undone.'}
                return self.confirm(body)
            if path=='/api/undo/review':
                return self.chat({'text':'undo','currency':body['currency'],'month':body['month']})
            if path=='/api/chat': return self.chat(body)
            if path=='/api/planning':
                curr=validate(body['currency']); kind=body['kind']; args=body.get('inputs',{})
                if kind=='verified': return {'amount':amount(cents(args['value'],curr=curr),curr),'currency':curr}
                if kind=='growth': return {'rows':compound_growth(args['principal'],args['contribution'],int(args['years']),args['annual_rate'],int(args['periods']),args['frequency'],args['timing'],args['inflation'],curr)}
                if kind=='fire':
                    target=fire_target(args['annual_expenses'],args['withdrawal_rate'],curr)
                    portfolio=cents(args['portfolio'],curr=curr)/scale(curr)
                    rows=compound_growth(args['portfolio'],args['contribution'],int(args['years']),args['annual_rate'],1,args['frequency'],'End',args['inflation'],curr)
                    inflated=target*(1+float(args['inflation'])/100)**int(args['years'])
                    result={'target':target,'multiple':100/float(args['withdrawal_rate']),'progress':portfolio/target*100 if target else None,'rows':rows,'horizon_target':inflated}
                    if args.get('other_return'):
                        other=compound_growth(args['portfolio'],args['contribution'],int(args['years']),args['other_return'],1,args['frequency'],'End',args['inflation'],curr)[-1]
                        result['comparison']={'rate':float(args['other_return']),'value':other['Projected value']}
                    return result
                if kind=='variance': return variance(args['budget'],args['actual'],curr)
                if kind=='goals':
                    target=cents(args['target'],curr=curr); saved=cents(args['saved'],curr=curr); horizon=int(args['months'])
                    if not 1<=horizon<=1200: raise ValueError('Goal horizon must be 1–1,200 months.')
                    percent=float(args.get('percent',20))
                    if not 0<=percent<=100: raise ValueError('Allocation must be 0–100%.')
                    state=self.store.load(); inc=income(state['transactions'],body['month'],curr); exp=spending(state['transactions'],body['month'],curr)
                    return {'remaining':amount(max(0,target-saved),curr),'monthly':max(0,target-saved)/horizon/scale(curr),'allocation':inc*percent/100/scale(curr),'surplus':amount(inc-exp,curr),'progress':min(100,saved/target*100) if target else 0}
                raise ValueError('Unknown calculator.')
            raise ValueError('Unknown API operation.')

class Handler(BaseHTTPRequestHandler):
    server_version='HomeAccounts/2'
    def log_message(self,*args): pass  # Never log uploaded records, prompts or credentials.
    def send(self,status,body,mime='application/json'):
        raw=json.dumps(body,ensure_ascii=False,allow_nan=False).encode() if mime=='application/json' else body
        self.send_response(status); self.send_header('Content-Type',mime); self.send_header('Content-Length',str(len(raw)))
        self.send_header('Cache-Control','no-store'); self.send_header('X-Content-Type-Options','nosniff'); self.send_header('Referrer-Policy','no-referrer')
        self.send_header('Content-Security-Policy',"default-src 'self'; script-src 'self'; style-src 'self' 'unsafe-inline'; img-src 'self' data:; connect-src 'self'; frame-ancestors 'none'; base-uri 'self'; form-action 'self'")
        self.end_headers(); self.wfile.write(raw)
    def safe_origin(self):
        host=self.headers.get('Host','')
        if host not in (f'127.0.0.1:{self.server.server_port}',f'localhost:{self.server.server_port}'): return False
        origin=self.headers.get('Origin')
        if origin and origin not in ('http://'+host,): return False
        return self.headers.get('Sec-Fetch-Site') not in ('cross-site',)
    def do_GET(self):
        if not self.safe_origin(): return self.send(403,{'error':'Local same-origin access required.'})
        url=urlsplit(self.path); path=url.path
        service=self.server.service
        try:
            if path=='/api/health': return self.send(200,{'status':'ok'})
            if path=='/api/state': return self.send(200,service.state())
            query={k:v[0] for k,v in parse_qs(url.query).items()}
            if path=='/api/overview': return self.send(200,service.overview(query['currency'],query['month']))
            if path=='/api/export':
                state=service.store.load(); kind=query.get('kind','transactions')
                if kind=='budgets': rows=state['budgets']; fields=BUDGET_FIELDS
                else:
                    rows=service.export_transactions(query); fields=TX_FIELDS
                return self.send(200,csv_bytes(rows,fields),'text/csv; charset=utf-8')
            if path=='/samples/homeaccounts-template.csv': return self.send(200,csv_bytes([],['date','type','amount','currency','particulars','category']),'text/csv; charset=utf-8')
            if path.startswith('/samples/'):
                name=path.removeprefix('/samples/')
                if name not in ('household_demo.csv','balances_wishlist_demo.csv','us_household_transactions.csv','us_household_budgets.csv'): return self.send(404,{'error':'Sample not found.'})
                return self.send(200,(ROOT/'sample_data'/name).read_bytes(),'text/csv; charset=utf-8')
            if path in ROUTES: return self.send(200,(ROOT/'web'/'index.html').read_bytes(),'text/html; charset=utf-8')
            if path.startswith('/assets/'):
                target=(ROOT/'web'/path.removeprefix('/assets/')).resolve()
                if target.is_relative_to((ROOT/'web').resolve()) and target.is_file():
                    mime={'.js':'text/javascript; charset=utf-8','.css':'text/css; charset=utf-8'}.get(target.suffix,mimetypes.guess_type(str(target))[0] or 'application/octet-stream')
                    return self.send(200,target.read_bytes(),mime)
            return self.send(404,{'error':'Not found.'})
        except (ValueError,KeyError,TypeError,OSError) as exc: return self.send(400,{'error':str(exc)[:400]})
    def do_POST(self):
        if not self.safe_origin() or not hmac.compare_digest(self.headers.get('X-HomeAccounts-Token',''),self.server.service.token): return self.send(403,{'error':'Refresh the app before making changes.'})
        try:
            size=int(self.headers.get('Content-Length','0'))
            if not 0<size<=14_000_000: raise ValueError('Request is empty or too large.')
            if not self.headers.get('Content-Type','').startswith('application/json'): raise ValueError('JSON required.')
            body=json.loads(self.rfile.read(size)); result=self.server.service.dispatch(urlsplit(self.path).path,body)
            return self.send(200,result)
        except (ValueError,KeyError,TypeError,OSError,OverflowError) as exc: return self.send(400,{'error':str(exc)[:400]})

def make_server(port=8501,folder=None,backup=True):
    server=ThreadingHTTPServer(('127.0.0.1',port),Handler); server.service=Service(folder,backup); return server

if __name__=='__main__':
    import argparse
    parser=argparse.ArgumentParser(); parser.add_argument('--port',type=int,default=8501); args=parser.parse_args()
    server=make_server(args.port,backup=os.environ.get('HOMEACCOUNTS_TEST_MODE')!='1')
    print(f'Home Accounts · http://127.0.0.1:{args.port} · local only',flush=True)
    try: server.serve_forever()
    except KeyboardInterrupt: pass
    finally: server.server_close()
