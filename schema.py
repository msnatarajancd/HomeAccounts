"""Framework-independent field schema and settings persistence."""
import datetime as dt
from decimal import Decimal, InvalidOperation
import json
import os
import re
import uuid
from currencies import CODES
from categories import reconcile,catalog

BASE=[('date','Date','Date',True),('type','Income / expense / transfer','Text',True),('amount','Amount','Number',True),('currency','Currency','Text',True),('description','Particulars','Text',False),('merchant','Merchant / income source','Text',False),('category','Category','Text',False),('subcategory','Subcategory','Text',False),('account','Account','Text',False)]
ALIASES={'date':['date','தேதி'],'type':['type','transaction type'],'amount':['amount','expense amount','income amount','expense','income','செலவு','வரவு'],'currency':['currency'],'description':['particulars','description','notes'],'merchant':['merchant','source','விவரம்'],'category':['category'],'subcategory':['subcategory','sub category'],'account':['account']}

def schema_path(store): return store.path/'schema.json'
def load_schema(store):
    path=schema_path(store)
    if path.exists(): return json.loads(path.read_text(encoding='utf-8'))
    return {'fields':[{'key':k,'label':label,'type':typ,'included':True,'required':required,'source':''} for k,label,typ,required in BASE]}

def suggested_schema(names):
    names=[str(n).strip() for n in names if str(n).strip()]
    understood=set(); result=[]
    for key,label,typ,required in BASE:
        found=[n for n in names if n.casefold().replace('_',' ') in ALIASES[key]]
        understood.update(found)
        result.append({'key':key,'label':label,'type':typ,'included':bool(found) or required,'required':required,'source':found[0] if len(found)==1 else ' / '.join(found)})
    notes=[]
    for name in names:
        if name in understood: continue
        if any(w in name.casefold() for w in ('budget','alloted')):
            notes.append(f'“{name}” is a budget amount. It will be reviewed separately with its month/category, not added to transaction totals.'); continue
        key='custom_'+re.sub(r'\W+','_',name.casefold()).strip('_')
        result.append({'key':key,'label':name,'type':'Text','included':True,'required':False,'source':name})
    return result,notes

def interpret_fields(text):
    text=re.sub(r'^(?:i (?:want|would like) to (?:track|use)|please (?:use|track)|fields?\s*:?)\s*','',text.strip(),flags=re.I)
    names=[n.strip(' .') for n in re.split(r',|;|\n|\s+and\s+',text) if n.strip(' .')]
    if not names: raise ValueError('Describe a few fields, such as date, category and particulars.')
    if len(names)>30: raise ValueError('Start with at most 30 fields.')
    return suggested_schema(names)

def validate_schema(rows):
    result=[]; keys=set(); labels=set()
    canonical={k:(typ,required) for k,_,typ,required in BASE}
    for row in rows:
        title=str(row.get('label','')).strip()
        if not title: raise ValueError('Each field needs a name. Remove an optional row or name it.')
        key=str(row.get('key','')).strip()
        if not key or key=='None' or key=='nan': key='custom_'+re.sub(r'\W+','_',title.casefold()).strip('_')
        if not key: raise ValueError('Choose a field name containing letters or numbers.')
        included=bool(row.get('included',True)); typ=str(row.get('type','Text'))
        required=key in canonical and canonical[key][1]
        if key in canonical:
            if typ!=canonical[key][0]: raise ValueError(f'{title} must keep type {canonical[key][0]}. Its displayed name may change.')
            if required and not included: raise ValueError(f'{title} is required for reliable dates, amounts and currency totals.')
        elif typ not in ('Text','Number','Date','Boolean'): raise ValueError('Custom fields support Text, Number, Date and Boolean. Files, formulas and linked tables are not supported.')
        if key in keys or title.casefold() in labels: raise ValueError('Field keys and displayed names must be unique.')
        keys.add(key); labels.add(title.casefold())
        result.append({'key':key,'label':title,'type':typ,'included':included,'required':required,'source':str(row.get('source','') or '').strip()})
    if not {'date','type','amount','currency'}<=keys: raise ValueError('Keep Date, Type, Amount and Currency. Optional fields can be removed.')
    return result

def save_schema(store,rows,curr,taxonomy=None):
    rows=validate_schema(rows)
    if curr not in CODES: raise ValueError('Choose your currency before confirming setup.')
    store.path.mkdir(parents=True,exist_ok=True)
    previous=load_schema(store).get('taxonomy',[])
    current=store.load()
    if taxonomy is not None:
        # Imported and manually confirmed choices also belong to the shared
        # catalog. Removing them archives their references instead of renaming.
        known=current.get('known_categories',[])
        existing=[r for r in catalog(previous,current['transactions'],current['budgets'],known)
                  if r['source'] in ('schema','confirmed')]
        taxonomy=reconcile(taxonomy,existing,current['transactions'],current['budgets'],known)
        taxonomy=[{k:r[k] for k in ('type','category','subcategory','active')} for r in taxonomy]
    else:
        taxonomy=previous
    if taxonomy:
        for key in ('category','subcategory'):
            if not any(f['key']==key for f in rows):
                base=next(r for r in BASE if r[0]==key); rows.append({'key':key,'label':base[1],'type':base[2],'included':True,'required':False,'source':''})
        for field in rows:
            if field['key'] in ('category','subcategory'): field['included']=True
    for filename,content in [('schema.json',{'fields':rows,'taxonomy':taxonomy}),('preferences.json',{'currency':curr})]:
        tmp=store.path/(uuid.uuid4().hex+'.tmp')
        tmp.write_text(json.dumps(content,ensure_ascii=False),encoding='utf-8')
        os.replace(tmp,store.path/filename)

def custom_definitions(schema): return [f for f in schema['fields'] if f['key'].startswith('custom_') and f['included']]

def parse_custom(value,typ):
    if value is None or str(value).strip()=='': return ''
    if typ=='Text': return str(value)
    if typ=='Number':
        try: val=Decimal(str(value))
        except InvalidOperation: raise ValueError('Custom Number field needs a number.')
        if not val.is_finite(): raise ValueError('Custom Number field must be finite.')
        return str(val)
    if typ=='Date': return dt.date.fromisoformat(str(value)).isoformat()
    if typ=='Boolean':
        if str(value).lower() in ('true','yes','1'): return True
        if str(value).lower() in ('false','no','0'): return False
        raise ValueError('Custom Boolean field needs yes/no or true/false.')
    raise ValueError('Unsupported custom field type.')
