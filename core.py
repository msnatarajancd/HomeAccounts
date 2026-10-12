"""Validated finance operations. Money uses each currency's integer minor units."""
import csv
import datetime as dt
from decimal import Decimal, InvalidOperation
import hashlib
import io
import json
import os
from pathlib import Path
import re
import time
import uuid
from server import read_xlsx
from currencies import validate, digits, scale
from categories import key as category_key, record_categories

TX_FIELDS = ['id','date','type','amount','currency','description','merchant','category','subcategory','account','source_ref','custom_fields']
BUDGET_FIELDS = ['id','period','category','subcategory','amount','currency','source_ref']
MONTHS = 'Jan Feb Mar Apr May Jun Jul Aug Sep Oct Nov Dec'.split()

def cents(value, allow_negative=False, curr=None):
    try:
        n = Decimal(str(value).strip().replace(',',''))
    except InvalidOperation:
        raise ValueError('Enter a valid amount.')
    if not n.is_finite() or abs(n)>Decimal('1000000000'):
        raise ValueError('Amount must be finite and at most 1,000,000,000.')
    if n != n.quantize(Decimal(1).scaleb(-digits(curr))):
        raise ValueError(f'Amounts in {curr or "this currency"} support at most {digits(curr)} decimal places.')
    if n < 0 and not allow_negative:
        raise ValueError('This amount cannot be negative.')
    if abs(n) > Decimal('1000000000'):
        raise ValueError('Amount is too large.')
    return int(n * scale(curr))

def amount(value,curr=None):
    return f'{Decimal(value)/scale(curr):.{digits(curr)}f}'

def currency(value):
    return validate(value)

def valid_tx(row):
    out = {k:str(row.get(k,'')).strip() for k in TX_FIELDS}
    out['id'] = out['id'] or uuid.uuid4().hex[:12]
    out['date'] = dt.date.fromisoformat(out['date']).isoformat()
    if out['type'] not in ('income','expense','transfer'): raise ValueError('Type must be income, expense or transfer.')
    out['currency'] = currency(out['currency'])
    value = cents(out['amount'], out['type'] in ('expense','transfer'),out['currency'])
    if value == 0: raise ValueError('A transaction amount cannot be zero.')
    out['amount'] = amount(value,out['currency'])
    if not out['account']: raise ValueError('Choose an account.')
    out['category'] = out['category'] or 'Uncategorized'
    custom=json.loads(out['custom_fields'] or '{}')
    if not isinstance(custom,dict) or any(not isinstance(v,(str,int,float,bool)) for v in custom.values()): raise ValueError('Custom fields must contain text, numbers, dates or booleans.')
    out['custom_fields']=json.dumps(custom,ensure_ascii=False,sort_keys=True,allow_nan=False)
    if any(len(v)>2000 for v in out.values()): raise ValueError('A field is too long.')
    return out

def valid_budget(row):
    out = {k:str(row.get(k,'')).strip() for k in BUDGET_FIELDS}
    out['id'] = out['id'] or uuid.uuid4().hex[:12]
    if not re.fullmatch(r'\d{4}-\d{2}',out['period']): raise ValueError('Period must be YYYY-MM.')
    dt.date.fromisoformat(out['period']+'-01')
    if not out['category']: raise ValueError('Budget needs a category.')
    out['currency'] = currency(out['currency'])
    out['amount'] = amount(cents(out['amount'],curr=out['currency']),out['currency'])
    return out

def budget_key(b):
    return tuple(b[k] for k in ('period','currency','category','subcategory'))

def replace_budgets(budgets, rows, before=()):
    """Replace the reviewed identities, including a corrected limit's old scope."""
    replaced={b['id'] for b in before}|{b['id'] for b in rows}
    remaining=[b for b in budgets if b['id'] not in replaced]
    occupied={budget_key(b) for b in remaining}
    for row in rows:
        if budget_key(row) in occupied:
            raise ValueError('A budget already exists for that month, currency, category and subcategory. Review that limit directly.')
        occupied.add(budget_key(row))
    return remaining+list(rows)

def fingerprint(t):
    return tuple(t[k].casefold() for k in ('date','type','amount','currency','description','merchant','category','subcategory','account'))

def csv_bytes(rows, fields):
    buf=io.StringIO(newline='')
    writer=csv.DictWriter(buf,fieldnames=fields)
    writer.writeheader()
    writer.writerows(rows)
    return buf.getvalue().encode('utf-8-sig')

class Store:
    """Two CSVs per immutable revision, with one atomic pointer and undo history.

    A failed write cannot expose one CSV without the other. A short exclusive
    lock and expected-revision check prevent lost updates between browser tabs.
    """
    def __init__(self, path): self.path=Path(path)

    def load(self):
        pointer=self.path/'current.json'
        if not pointer.exists(): return {'revision':'','transactions':[],'budgets':[],'history':[],'imported_refs':[]}
        info=json.loads(pointer.read_text(encoding='utf-8'))
        rev=self.path/'revisions'/info['revision']
        def read(name):
            with (rev/name).open(encoding='utf-8-sig',newline='') as f: return list(csv.DictReader(f))
        return {**info,'transactions':read('transactions.csv'),'budgets':read('budgets.csv')}

    def _pointer(self, info):
        tmp=self.path/(uuid.uuid4().hex+'.tmp')
        try:
            with tmp.open('w',encoding='utf-8') as f:
                json.dump(info,f); f.flush(); os.fsync(f.fileno())
            for attempt in range(6):
                try:
                    os.replace(tmp,self.path/'current.json')
                    break
                except PermissionError as exc:
                    # Windows readers/AV may briefly hold a handle without
                    # delete sharing. Keep the old pointer until replace wins.
                    if getattr(exc,'winerror',None) not in (5,32,33) or attempt==5:
                        raise
                    time.sleep(.02*(2**attempt))
        except BaseException:
            try: tmp.unlink(missing_ok=True)
            except OSError: pass  # Preserve the original write/replace failure.
            raise

    def commit(self, tx, budgets, expected, label, *, reset_imports=False):
        self.path.mkdir(parents=True,exist_ok=True)
        lock=self.path/'write.lock'
        try: lock.mkdir()
        except FileExistsError: raise ValueError('Another write is in progress. Retry; if the app crashed, see recovery instructions.')
        try:
            old=self.load()
            if old['revision']!=expected: raise ValueError('Records changed since this preview. Refresh and review again.')
            tx=[valid_tx(t) for t in tx]
            budgets=[valid_budget(b) for b in budgets]
            if len({t['id'] for t in tx})!=len(tx): raise ValueError('Transaction IDs must be unique.')
            if len({b['id'] for b in budgets})!=len(budgets): raise ValueError('Budget IDs must be unique.')
            if len({budget_key(b) for b in budgets})!=len(budgets): raise ValueError('Only one budget per month, currency, category and subcategory is allowed.')
            revision=uuid.uuid4().hex
            folder=self.path/'revisions'/revision
            folder.mkdir(parents=True)
            for name,rows,fields in [('transactions.csv',tx,TX_FIELDS),('budgets.csv',budgets,BUDGET_FIELDS)]:
                with (folder/name).open('wb') as f:
                    f.write(csv_bytes(rows,fields)); f.flush(); os.fsync(f.fileno())
            refs=(set() if reset_imports else set(old.get('imported_refs',[])))|{t['source_ref'] for t in tx if t['source_ref']}
            # Keep confirmed category identities with the same atomic revision as
            # the records. Clearing/deleting records must not lose their choices.
            known={category_key(r):r for r in [*old.get('known_categories',[]),
                *record_categories(old['transactions'],old['budgets']),*record_categories(tx,budgets)]}
            info={'revision':revision,'history':old['history']+[old['revision']], 'imported_refs':sorted(refs),
                  'known_categories':[known[k] for k in sorted(known)],'label':label,'time':dt.datetime.now().isoformat(timespec='seconds')}
            (folder/'metadata.json').write_text(json.dumps(info),encoding='utf-8')
            self._pointer(info)
            return revision
        finally: lock.rmdir()

    def undo(self, expected):
        self.path.mkdir(parents=True,exist_ok=True)
        lock=self.path/'write.lock'
        try: lock.mkdir()
        except FileExistsError: raise ValueError('Another write is in progress.')
        try:
            current=self.load()
            if current['revision']!=expected: raise ValueError('Records changed. Refresh before undo.')
            if not current['history']: raise ValueError('Nothing to undo.')
            previous=current['history'][-1]
            if previous:
                info=json.loads((self.path/'revisions'/previous/'metadata.json').read_text(encoding='utf-8'))
                self._pointer(info)
            else:
                (self.path/'current.json').unlink()
        finally: lock.rmdir()

def parse_date(value, style='ISO (YYYY-MM-DD)', excel=False):
    value=str(value).strip()
    if excel and re.fullmatch(r'\d+(\.0+)?',value):
        return (dt.date(1899,12,30)+dt.timedelta(days=int(float(value)))).isoformat()
    formats={'ISO (YYYY-MM-DD)':'%Y-%m-%d','US (MM/DD/YYYY)':'%m/%d/%Y','Day first (DD/MM/YYYY)':'%d/%m/%Y'}
    return dt.datetime.strptime(value,formats[style]).date().isoformat()

def read_tables(data, filename):
    if filename.lower().endswith('.xlsx'): return read_xlsx(data)
    text=data.decode('utf-8-sig')
    delimiter='\t' if filename.lower().endswith('.tsv') else ','
    return {'CSV':list(csv.reader(io.StringIO(text),delimiter=delimiter))}

def normalize_import(tables, filename, data, mapping, selected, default_currency, account, year, style, kind='Transactions'):
    tx=[]; budgets=[]; issues=[]; skipped=0
    digest=hashlib.sha256(data).hexdigest()
    for sheet in selected:
        rows=tables[sheet]
        if not rows: continue
        header=[str(h).strip() for h in rows[0]]
        if 'record_kind' in header and 'as_of' in header:
            issues.append({'sheet':sheet,'row':1,'error':'Balance snapshots, dues and wish lists are not transactions.','values':''}); continue
        if kind=='Transactions' and not any(mapping.get(k) in header for k in ('amount','expense','income')):
            issues.append({'sheet':sheet,'row':1,'error':'Map an Amount column with Type, or Expense / Income columns. For budget-only files, choose Budgets.','values':''}); continue
        def cell(row,field):
            col=mapping.get(field,'(none)')
            if col not in header: return ''
            i=header.index(col)
            return str(row[i]).strip() if len(row)>i else ''
        for index,row in enumerate(rows[1:],2):
            if not any(str(v).strip() for v in row): continue
            ref=f'{digest}:{sheet}:{index}'
            try:
                if kind=='Budgets':
                    cat=cell(row,'category')
                    if cat.lower() in ('total','') or not cell(row,'budget'): skipped+=1; continue
                    period=cell(row,'period')
                    if not period:
                        month=sheet.replace(' Budget','')
                        if month not in MONTHS: raise ValueError('Map a period column (YYYY-MM).')
                        period=f'{year}-{MONTHS.index(month)+1:02}'
                    budgets.append(valid_budget({'period':period,'category':cat,'subcategory':cell(row,'subcategory'), 'amount':cell(row,'budget'),'currency':cell(row,'currency') or default_currency,'source_ref':ref}))
                    continue
                expense=cell(row,'expense'); income=cell(row,'income'); value=cell(row,'amount')
                if not any((expense,income,value)): skipped+=1; continue
                if expense and income: raise ValueError('Both income and expense are populated. Split the source row before import.')
                typ=('expense' if expense else 'income') if expense or income else cell(row,'type').lower()
                custom={}
                if 'custom_fields' in header:
                    pos=header.index('custom_fields')
                    custom=json.loads(row[pos] or '{}') if len(row)>pos else {}
                    if not isinstance(custom,dict): raise ValueError('Exported custom fields must be an object.')
                custom.update({key:cell(row,key) for key in mapping if key.startswith('custom_') and mapping[key] in header})
                tx.append(valid_tx({'date':parse_date(cell(row,'date'),style,filename.lower().endswith('.xlsx')), 'type':typ,'amount':expense or income or value,'currency':cell(row,'currency') or default_currency,'description':cell(row,'description') or cell(row,'merchant'),'merchant':cell(row,'merchant'),'category':cell(row,'category'),'subcategory':cell(row,'subcategory'),'account':cell(row,'account') or account,'source_ref':ref,'custom_fields':json.dumps(custom,ensure_ascii=False)}))
            except (ValueError,OverflowError) as exc:
                issues.append({'sheet':sheet,'row':index,'error':str(exc),'values':str(row[:8])})
    return {'transactions':tx,'budgets':budgets,'issues':issues,'skipped':skipped,'filename':filename}

def import_candidates(preview, state):
    # Provenance stops repeat imports without discarding identical genuine rows.
    existing_refs=set(state.get('imported_refs',[]))|{t['source_ref'] for t in state['transactions'] if t['source_ref']}
    incoming=[t for t in preview['transactions'] if t['source_ref'] not in existing_refs]
    seen={fingerprint(t) for t in state['transactions']}
    possible=[]
    for t in incoming:
        if fingerprint(t) in seen: possible.append(t)
        seen.add(fingerprint(t))
    keys={budget_key(b):b for b in state['budgets']}
    new_budgets=[]; conflicts=[]
    for b in preview['budgets']:
        key=budget_key(b)
        if key in keys:
            if keys[key]['amount']!=b['amount']: conflicts.append(b)
        else: new_budgets.append(b); keys[key]=b
    return incoming,new_budgets,possible,conflicts

def spending(tx, period, curr, category=None, subcategory=None):
    return sum(cents(t['amount'],True,curr) for t in tx if t['type']=='expense' and t['date'][:7]==period and t['currency']==curr and (category is None or t['category']==category) and (not subcategory or t['subcategory']==subcategory))

def income(tx, period, curr):
    return sum(cents(t['amount'],curr=curr) for t in tx if t['type']=='income' and t['date'][:7]==period and t['currency']==curr)

def total_budget(budgets, period, curr):
    bs=[b for b in budgets if b['period']==period and b['currency']==curr]
    parents={b['category'] for b in bs if not b['subcategory']}
    return sum(cents(b['amount'],curr=curr) for b in bs if not b['subcategory'] or b['category'] not in parents)

def impacts(state, proposed, replaced_id=None):
    remaining=[t for t in state['transactions'] if t['id']!=replaced_id]
    result=[]
    if proposed['type']!='expense': return result
    for b in state['budgets']:
        if b['period']==proposed['date'][:7] and b['currency']==proposed['currency'] and b['category']==proposed['category'] and (not b['subcategory'] or b['subcategory']==proposed['subcategory']):
            spent=spending(remaining,b['period'],b['currency'],b['category'],b['subcategory'])
            curr=b['currency']; limit=cents(b['amount'],curr=curr)
            new=spent+cents(proposed['amount'],True,curr)
            result.append({'category':b['category'],'subcategory':b['subcategory'],'currency':curr,'budget':amount(limit,curr),'current':amount(spent,curr),'proposed_total':amount(new,curr),'over_budget':amount(max(0,new-limit),curr)})
    return result

SMALL=dict(zip('zero one two three four five six seven eight nine ten eleven twelve thirteen fourteen fifteen sixteen seventeen eighteen nineteen'.split(),range(20)))
TENS=dict(zip('twenty thirty forty fifty sixty seventy eighty ninety'.split(),range(20,100,10)))

def word_number(text):
    total=0; part=0
    for w in text.lower().replace('-',' ').split():
        if w=='and': continue
        if w in SMALL: part+=SMALL[w]
        elif w in TENS: part+=TENS[w]
        elif w=='hundred': part=max(part,1)*100
        elif w=='thousand': total+=max(part,1)*1000; part=0
        else: raise ValueError('Could not interpret the amount.')
    return total+part

def parse_sentence(text, reference_date, curr, account, tx,taxonomy=None):
    lower=text.lower().strip()
    if re.search(r'(?:\b(?:and|then|plus)\b|[;\n])\s*(?:i\s+)?(?:also\s+)?(?:(?:spent|paid|earned|received|bought)\b|[$€₹¥£]?\s*\d)',lower):
        raise ValueError('Enter one transaction at a time, or use the split form. Review each amount separately.')
    # Explicit currency codes override the selected default; ambiguous symbols
    # only resolve when compatible with that selection.
    from currencies import CODES
    code_tokens=re.findall(r'\b[A-Z]{3}\b',text)+[c.upper() for c in re.findall(r'\d(?:[\d,.]*)\s+([a-zA-Z]{3})\b',text)]
    explicit_codes=[code for code in code_tokens if code in CODES]
    if len(set(explicit_codes))>1: raise ValueError('Multiple currencies found. Use the form to split the records.')
    curr=currency(explicit_codes[0] if explicit_codes else curr)
    families={'$':{'USD','CAD','AUD','NZD','SGD','HKD','MXN','ARS','CLP','COP','BBD','BMD','BSD','BZD','FJD','GYD','KYD','LRD','NAD','SBD','SRD','TTD','TWD','XCD'},'€':{'EUR'},'₹':{'INR'},'¥':{'JPY','CNY'},'£':{'GBP','EGP','LBP','SSP','SYP'}}
    markers=set(ch for ch in text if ch in families)
    if 'dollars' in lower: markers.add('$')
    if 'euros' in lower: markers.add('€')
    if 'yen' in lower: markers.add('¥')
    if 'pounds' in lower: markers.add('£')
    if 'rupees' in lower and curr not in {'INR','PKR','NPR','LKR','MUR','SCR'}: raise ValueError('Rupees do not match the selected currency. Choose the intended currency or write an ISO code.')
    for symbol in markers:
        if curr not in families[symbol]: raise ValueError(f'{symbol} does not match selected {curr}. Choose the intended currency or write an explicit ISO code.')
    if not re.search(r'\b(spent|paid|bought|earned|received|refund)\b',lower): raise ValueError('Try “I spent forty-five dollars at Walmart yesterday” or “I earned 1000 yesterday”.')
    typ='income' if re.search(r'\b(earned|received)\b',lower) and 'refund' not in lower else 'expense'
    m=re.search(r'[$€₹¥£]\s*(\d[\d,]*(?:\.\d+)?)',lower)
    # Prefer an amount directly after the verb so ISO dates never become amounts.
    numeric=re.search(r'\b(?:spent|paid|earned|received|refund(?:ed)?)\s+(?:me\s+)?(?:[$€₹¥£]\s*)?(\d[\d,]*(?:\.\d+)?)',lower)
    if numeric: value=cents(numeric.group(1),curr=curr)
    else:
        words=re.search(r'\b(?:spent|paid|earned|received|refund)\s+([a-z -]+?)\s+(?:dollars|rupees|euros|pounds|yen|'+curr.lower()+r')\b',lower)
        if words: value=word_number(words.group(1))*scale(curr)
        elif m: value=cents(m.group(1),curr=curr)
        else: raise ValueError('No clear amount found. Use the form to enter it.')
    if 'refund' in lower: value=-value
    date=reference_date
    explicit=re.search(r'\b\d{4}-\d{2}-\d{2}\b',lower)
    if explicit: date=dt.date.fromisoformat(explicit.group())
    elif 'yesterday' in lower: date-=dt.timedelta(days=1)
    elif 'today' not in lower and re.search(r'\b(last|tomorrow|monday|tuesday|wednesday|thursday|friday|saturday|sunday)\b',lower):
        raise ValueError('Use today, yesterday or an explicit YYYY-MM-DD date.')
    merchant=''
    match=re.search(r'\b(?:at|from|to)\s+(.+?)(?=\s+(?:yesterday|today|on\s+\d{4}|for\b)|$)',text,re.I)
    if match: merchant=match.group(1).strip(' .')
    # Category hints are suggestions; never invent an absent source.
    cat='Uncategorized'; sub=''; note='Choose a category before confirming.'
    rules=[('grocer','American Grocery'),('household','Household'),('restaurant','Restaurant'),('rent','Rent'),('salary','Income'),('gas','Transportation')]
    for hint,suggested in rules:
        if re.search(r'\b'+hint+r'\w*\b',lower): cat=suggested; note='Suggested from your description; review it.'; break
    if taxonomy:
        active=[r for r in taxonomy if r['type']==typ and r['active']]
        inferred=next((r for r in active if r['subcategory'] and r['subcategory'].casefold() in lower),None)
        if inferred: cat=inferred['category']; sub=inferred['subcategory']; note='Suggested from your chosen hierarchy and description; review it.'
    if cat=='Uncategorized' and merchant:
        history={(t['category'],t['subcategory']) for t in tx if t['merchant'].casefold()==merchant.casefold() and t['type']==typ}
        if len(history)==1:
            cat,sub=next(iter(history)); note='Suggested from prior confirmed records; review it.'
        elif len(history)>1: note='This merchant has multiple categories. Choose one or split the expense in the form.'
    if typ=='income' and cat=='Uncategorized': cat='Income'; note='Income source stays blank unless you provide one.'
    return valid_tx({'date':date.isoformat(),'type':typ,'amount':amount(value,curr),'currency':curr,'description':text,'merchant':merchant,'category':cat,'subcategory':sub,'account':account}),note

def monthly_summary(state,period,curr):
    inc=income(state['transactions'],period,curr); exp=spending(state['transactions'],period,curr)
    return f'Confirmed records for {period} ({curr}): income {amount(inc,curr)}, net expenses {amount(exp,curr)}, income minus expenses {amount(inc-exp,curr)}. These are recorded totals, not a forecast.'

def coach(text, state, period, curr, account, reference_date):
    lower=text.lower().strip()
    if re.match(r'(?:i\s+)?(?:spent|paid|earned|received|refund|bought)\b',lower):
        t,note=parse_sentence(text,reference_date,curr,account,state['transactions'],state.get('taxonomy'))
        return note, {'kind':'add','rows':[t]}
    delete=re.fullmatch(r'delete transaction ([a-f0-9]+)',lower)
    edit=re.fullmatch(r'change transaction ([a-f0-9]+) amount to (\d+(?:\.\d+)?)',lower)
    if delete or edit:
        id=(delete or edit).group(1)
        old=next((t for t in state['transactions'] if t['id']==id),None)
        if not old: raise ValueError('Transaction ID not found. Copy its full ID from Transactions.')
        if delete: return 'Review the exact record before deleting.',{'kind':'delete','before':[old],'rows':[]}
        new=valid_tx({**old,'amount':edit.group(2)})
        return 'Review the original and proposed amount.',{'kind':'edit','before':[old],'rows':[new]}
    b=re.fullmatch(r'set (.+?) budget to (\d+(?:\.\d+)?) for (\d{4}-\d{2})',lower)
    if b:
        names={x['category'].casefold():x['category'] for x in state['transactions']+state['budgets']}
        category=names.get(b.group(1),b.group(1).title())
        new=valid_budget({'period':b.group(3),'category':category,'amount':b.group(2),'currency':curr})
        old=next((x for x in state['budgets'] if budget_key(x)==budget_key(new)),None)
        if old: new['id']=old['id']; new['source_ref']=old['source_ref']
        return 'Review the budget and overall monthly effect.',{'kind':'budget','before':[old] if old else [],'rows':[new]}
    if any(x in lower for x in ('budget','remaining','over')):
        bs=[b for b in state['budgets'] if b['period']==period and b['currency']==curr]
        over=[b for b in bs if spending(state['transactions'],period,curr,b['category'],b['subcategory'])>cents(b['amount'],curr=curr)]
        return f'{period} ({curr}): total planned budget {amount(total_budget(bs,period,curr),curr)}; net expenses {amount(spending(state["transactions"],period,curr),curr)}. {len(over)} category/subcategory budgets are over. See Budgets for exact amounts. Budget changes require your confirmation.',None
    if lower.rstrip(' ?.!')=='income' or re.search(r'\b(?:total|my|much|monthly) income\b(?!\s+tax)',lower):
        return monthly_summary(state,period,curr),None
    hierarchy=state.get('taxonomy',[])
    children={(t['category'],t['subcategory']) for t in state['transactions'] if t['subcategory']}
    children|={(r['category'],r['subcategory']) for r in hierarchy if r['active'] and r['subcategory']}
    matching_children=[(cat,sub) for cat,sub in children if sub.casefold() in lower and (cat.casefold() in lower or not any(othercat.casefold() in lower for othercat,_ in children))]
    if matching_children:
        longest=max(len(sub) for _,sub in matching_children)
        matching_children=[r for r in matching_children if len(r[1])==longest]
        if len(matching_children)>1: return 'That subcategory appears under several categories. Include the parent category in your question.',None
        category,subcategory=matching_children[0]
        value=spending(state['transactions'],period,curr,category,subcategory)
        return f'Confirmed net expense for {category} / {subcategory} in {period} ({curr}): {amount(value,curr)}. Refunds reduce this amount.',None
    categories={t['category'].casefold():t['category'] for t in state['transactions']}
    categories.update({r['category'].casefold():r['category'] for r in hierarchy if r['active']})
    matching=next((name for key,name in sorted(categories.items(),key=lambda x:-len(x[0])) if key in lower),None)
    if matching:
        value=spending(state['transactions'],period,curr,matching)
        return f'Confirmed net expense for {matching} in {period} ({curr}): {amount(value,curr)}. Refunds reduce this amount.',None
    if any(x in lower for x in ('income','expense','spent','saving','summary','month','total')):
        return monthly_summary(state,period,curr),None
    return 'I use local rules and your saved records. Ask “monthly summary”, “Household spending” or “remaining budget”. To add a record, try “I spent 45 at a shop yesterday”. For other wording, use the forms. Proposed changes always need your confirmation.',None

def apply_proposal(store, state, proposal):
    tx=list(state['transactions']); budgets=list(state['budgets'])
    kind=proposal['kind']; rows=proposal.get('rows',[])
    if kind=='add': tx+=rows
    elif kind=='clear': tx=[]
    elif kind in ('edit','delete'):
        ids={t['id'] for t in proposal['before']}
        tx=[t for t in tx if t['id'] not in ids]+rows
    elif kind=='budget':
        budgets=replace_budgets(budgets,rows,proposal.get('before',[]))
    elif kind=='import':
        tx+=rows; budgets+=proposal['budgets']
    else: raise ValueError('Unknown proposal.')
    return store.commit(tx,budgets,proposal['revision'],kind,reset_imports=kind=='clear')
