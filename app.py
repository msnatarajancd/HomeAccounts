import datetime as dt
import os
import hashlib
import json
import uuid
from pathlib import Path
import pandas as pd
import plotly.express as px
import streamlit as st
from core import (Store, MONTHS, TX_FIELDS, BUDGET_FIELDS, read_tables, normalize_import,
                  import_candidates, cents, amount, valid_tx, valid_budget, fingerprint,
                  budget_key, spending, income, total_budget, impacts, parse_sentence,
                  coach, apply_proposal, csv_bytes)
from planning_ui import show_planning
from overview import show_overview
from currencies import CODES, label as currency_label, scale, digits, display_minor
from setup_flow import show_setup,load_schema,schema_path,custom_definitions,custom_inputs,parse_custom
from categories import options as category_options,suboptions
from ai_client import configured,model_name,connected_coach

ROOT=Path(__file__).resolve().parent
store=Store(os.environ.get('HOMEACCOUNTS_DATA_DIR',str(ROOT/'data')))
st.set_page_config(page_title='Home Accounts',page_icon='◈',layout='wide')
st.markdown('''<style>
.stApp {background:#f6f8fa} [data-testid="stSidebar"] {background:#112b32}
[data-testid="stSidebar"] * {color:#e9f3f1} [data-testid="stSidebar"] input {color:#132e35}
[data-testid="stSidebar"] .stButton>button[kind="secondary"], [data-testid="stSidebar"] .stButton>button[kind="secondary"] p {color:#12333b}
[data-testid="stMetric"] {background:white;border:1px solid #e3e9ed;border-radius:14px;padding:20px}
[data-testid="stMetricLabel"] {color:#61737a} h1,h2,h3 {color:#12333b}
[data-testid="stMetricValue"] {font-size:clamp(1rem,1.5vw,1.6rem)}
[data-testid="stMetricValue"] div {white-space:normal;overflow:visible;text-overflow:clip}
[data-testid="stMetricLabel"] p {white-space:normal;font-size:.82rem}
[data-testid="stMetric"] {min-height:138px}
.hero {padding:26px 30px;border-radius:18px;background:linear-gradient(120deg,#12333b,#246c67);color:white;margin-bottom:24px}
.hero h2 {color:white;margin:0} .hero p {color:#cce5df;margin-bottom:0}
.stButton>button[kind="primary"]:not(:disabled) {background:#126b60;border-color:#126b60;color:#ffffff;font-weight:650;box-shadow:0 3px 9px #126b6020}
.stButton>button[kind="primary"]:not(:disabled):hover {background:#0a5149;border-color:#0a5149;color:#ffffff}
.stButton>button:focus-visible {outline:3px solid #e2a333;outline-offset:3px}
.stButton>button[kind="primary"]:disabled {background:#e1e7e9;border-color:#b6c4c8;color:#43575d;opacity:1;cursor:not-allowed}
.welcome-hero {background:linear-gradient(120deg,#e4f4ed,#e8eefc);border:1px solid #cbdedb;border-radius:22px;padding:28px 32px;margin:0 0 24px}
.welcome-hero h1 {font-size:2.5rem;margin:0 0 12px}.welcome-hero h3 {margin:0;line-height:1.35}
[data-testid="stTabs"] [role="tablist"] {background:#ffffff;border:1px solid #dce7e6;border-radius:12px;padding:7px;gap:8px}
[data-testid="stTabs"] [role="tab"] {padding:10px 20px;font-weight:600}
[data-testid="stTabs"] [role="tab"][aria-selected="true"] {background:#d9eee7;color:#0d5148;border-radius:8px}
</style>''',unsafe_allow_html=True)

def frame(rows, fields=None):
    return pd.DataFrame(rows,columns=fields) if fields else pd.DataFrame(rows)

def notify():
    if st.session_state.get('notice'): st.success(st.session_state.pop('notice'))

def stage(proposal, state):
    proposal['revision']=state['revision']
    st.session_state.pending=proposal
    st.session_state.review_key=st.session_state.get('review_key',0)+1
    st.rerun()

def money(value,curr): return display_minor(value,curr)

try: state=store.load()
except (OSError,ValueError,KeyError) as exc:
    st.error(f'Could not read saved CSV data: {exc}. Restore a backup before continuing.'); st.stop()
tx=state['transactions']; budgets=state['budgets']
categories=sorted({r['category'] for r in tx+budgets}|{'Income','Household','Groceries','Dining','Transport','Uncategorized'})

onboarded=bool(state['revision']) or schema_path(store).exists() or st.session_state.get('manual_start',False)
if not onboarded or st.session_state.get('revisit_setup',False):
    show_setup(store,revisit=onboarded)
    st.stop()
schema=load_schema(store)
taxonomy=schema.get('taxonomy',[])
state['taxonomy']=taxonomy
field_labels={f['key']:f['label'] for f in schema['fields']}
enabled={f['key'] for f in schema['fields'] if f['included']}
def field_label(key,fallback): return field_labels.get(key,fallback)
def transaction_view(records):
    result=[]
    for record in records:
        shown={field_label(k,k.replace('_',' ').title()):v for k,v in record.items() if k not in ('source_ref','custom_fields')}
        for k,v in json.loads(record.get('custom_fields','{}') or '{}').items(): shown[field_label(k,k.removeprefix('custom_').replace('_',' '))]=v
        result.append(shown)
    return frame(result)

preferences=store.path/'preferences.json'
try: saved_currency=json.loads(preferences.read_text(encoding='utf-8')).get('currency') if preferences.exists() else None
except (OSError,ValueError): saved_currency=None
currency_choices=['(Choose currency)']+CODES

def choose_currency():
    chosen=st.selectbox('Your currency',currency_choices,index=currency_choices.index(saved_currency) if saved_currency in CODES else 0,format_func=lambda c:currency_label(c) if c in CODES else c,key='active_currency',help='Used for new entries, missing file currencies, reports and planning. Existing records keep their own currency.')
    if chosen in CODES and chosen!=saved_currency:
        store.path.mkdir(parents=True,exist_ok=True)
        tmp=store.path/(uuid.uuid4().hex+'.tmp')
        tmp.write_text(json.dumps({'currency':chosen}),encoding='utf-8'); os.replace(tmp,preferences)
    return chosen

if onboarded:
  with st.sidebar:
    st.title('◈ Home Accounts')
    st.caption('PERSONAL FINANCE WORKSPACE')
    page=st.radio('Workspace',['Overview','Import & review','Add transaction','Transactions','Budgets','Coach','Planning & Goals'],key='page')
    st.divider()
    curr=choose_currency()
    populated=sorted({t['date'][:7] for t in tx if t['currency']==curr},reverse=True)
    budget_periods=sorted({b['period'] for b in budgets if b['currency']==curr},reverse=True)
    today_month=dt.date.today().strftime('%Y-%m')
    periods=sorted(set(populated+budget_periods+[today_month]),reverse=True)
    preferred=populated[0] if populated else budget_periods[0] if budget_periods else today_month
    report_key='report_month_'+curr
    if st.session_state.get(report_key) not in periods: st.session_state[report_key]=preferred
    period=st.selectbox('Reporting month',periods,index=None,key=report_key)
    if populated: st.caption('Available record months: '+', '.join(populated))
    st.caption('Currencies are reported separately. No exchange-rate conversion.')
    st.caption('Coach: local rules or optional connected AI')
    st.caption(f'{len(tx)} confirmed transactions')
    if st.button('Review field setup'):
        st.session_state.revisit_setup=True; st.rerun()
    if state['history']:
        undo=st.checkbox('Review undo of last save')
        if undo:
            st.write('Undo restores both CSVs to the previous revision.')
            if st.button('Confirm undo',type='primary'):
                try:
                    store.undo(state['revision']); st.session_state.pop('pending',None)
                    st.session_state.notice='Last save undone.'; st.rerun()
                except ValueError as exc: st.error(str(exc))
else:
    page='Import & review'
    period=dt.date.today().strftime('%Y-%m')
    st.title('Review your file')
    curr=choose_currency()

if curr not in CODES:
    st.info('Choose your currency to continue. If your file contains currency codes, those values will be preserved.')
    st.stop()

notify()
st.caption('HOME ACCOUNTS / '+page.upper())

if page=='Overview':
    show_overview(tx,budgets,period,curr,transaction_view)

elif page=='Import & review':
    st.subheader('Understand your data before importing')
    st.write('1. Choose a source. 2. Confirm fields and defaults. 3. Review records and issues. 4. Confirm the import.')
    source=st.radio('Data source',['Upload CSV / TSV / Excel','Fictional household demo','Fictional balances & wishes'],horizontal=True) if onboarded else 'Upload CSV / TSV / Excel'
    data=None; filename=''
    if source.startswith('Upload'):
        upload=st.file_uploader('Choose a file',type=['csv','tsv','xlsx']) if onboarded else None
        if st.session_state.get('onboarding_file') and not upload:
            filename,data=st.session_state.onboarding_file
            st.caption('File: '+filename)
            if st.button('Choose a different file'):
                st.session_state.pop('onboarding_file',None); st.session_state.pop('pending',None); st.rerun()
        elif upload:
            if upload.size>10_000_000: st.error('Maximum upload size is 10 MB.')
            else: data=upload.getvalue(); filename=upload.name
    else:
        filename='household_demo.csv' if source=='Fictional household demo' else 'balances_wishlist_demo.csv'
        sample=ROOT/'sample_data'/filename
        if sample.exists(): data=sample.read_bytes()
        else: st.error('Sample file was not found. Use upload instead.')
    if data:
        try: tables=read_tables(data,filename)
        except Exception as exc: st.error(f'Cannot read file: {exc}'); st.stop()
        if filename=='Cash In Hand.xlsx' or any('Desired Items'==s for s in tables) or any('record_kind' in rows[0] and 'as_of' in rows[0] for rows in tables.values() if rows):
            st.warning('This workbook contains account balances, bills due, wish lists and balance-transfer offers. These are not dated transaction records. Review the source below; transaction import is disabled for this layout.')
            sheet=st.selectbox('Source sheet',list(tables)); st.dataframe(pd.DataFrame(tables[sheet]),hide_index=True)
        else:
            kind=st.radio('Import as',['Transactions','Budgets'],horizontal=True)
            default_sheets=[s for s in tables if s in MONTHS] if kind=='Transactions' else [s for s in tables if s.endswith(' Budget')]
            if 'CSV' in tables: default_sheets=['CSV']
            available=[s for s in tables if tables[s] and any(tables[s][0])]
            selected=st.multiselect('Sheets to review (summary/chart sheets are excluded by default)',available,default=[s for s in default_sheets if s in available],key=f'sheets_{filename}_{kind}')
            if selected:
                header=[str(h).strip() for h in tables[selected[0]][0] if str(h).strip()]
                st.caption('Source headers: '+', '.join(header))
                x,y,z=st.columns(3)
                default_currency=x.text_input('Currency when a row has none',value=curr,key=f'import_currency_{curr}')
                account=y.text_input('Default account (confirm your own label)',value='Unspecified account')
                year=z.number_input('Budget year for month-named sheets',min_value=1900,max_value=2100,value=2026)
                style=st.selectbox('Text date format',['ISO (YYYY-MM-DD)','US (MM/DD/YYYY)','Day first (DD/MM/YYYY)'])
                st.caption('Excel serial dates use the 1900 calendar. Currency/account defaults apply only when the source omits them.')
                aliases={'date':['தேதி','date','Date'],'merchant':['விவரம்','merchant','Merchant','source'],'description':['Particulars','particulars','description','Description'],'category':['Category','category'],'expense':['செலவு','expense_amount','expense','Expense'],'income':['வரவு','income_amount','income','Income'],'amount':['amount','Amount'],'type':['type','Type'],'currency':['currency','Currency'],'account':['account','Account'],'subcategory':['subcategory','Subcategory'],'period':['period','budget_period','Period'],'budget':['Amount Alloted','monthly_budget','budget','amount','Amount']}
                fields=['date','merchant','description','category','expense','income','amount','type','currency','account','subcategory'] if kind=='Transactions' else ['period','category','subcategory','budget','currency']
                mapping={}
                with st.expander('Confirm field mapping',expanded=True):
                    cols=st.columns(3)
                    for i,field in enumerate(fields):
                        choices=['(none)']+header
                        schema_source=next((f['source'] for f in schema['fields'] if f['key']==field),'')
                        normalized=lambda value:str(value).strip().casefold().replace('_',' ')
                        default=schema_source if schema_source in header else next((h for h in header if normalized(h) in {normalized(a) for a in aliases[field]}),'(none)')
                        mapping[field]=cols[i%3].selectbox(field.replace('_',' ').title(),choices,index=choices.index(default),key=f'map_{filename}_{kind}_{field}_{selected[0]}')
                    custom_map={}
                    if kind=='Transactions':
                        for definition in custom_definitions(schema):
                            choices=['(none)']+header
                            source=definition['source'] if definition['source'] in header else '(none)'
                            custom_map[definition['key']]=st.selectbox(definition['label']+' source',choices,index=choices.index(source),key='custom_map_'+definition['key']+filename)
                st.write('Proposed screens: monthly overview → transaction list → optional budgets → entry and coach → Planning & Goals. Transactions and monthly budgets stay separate.')
                st.dataframe(pd.DataFrame(tables[selected[0]][1:6],columns=None),hide_index=True,width='stretch')
                context=(hashlib.sha256(data).hexdigest(),kind,tuple(selected),tuple(mapping.items()),tuple(custom_map.items()),default_currency,account,int(year),style)
                if st.button('Prepare import review',type='primary'):
                    preview=normalize_import(tables,filename,data,{**mapping,**custom_map},selected,default_currency,account,int(year),style,kind)
                    for record in preview['transactions']:
                        values=json.loads(record.get('custom_fields','{}'))
                        for definition in custom_definitions(schema):
                            try: values[definition['key']]=parse_custom(values.get(definition['key'],''),definition['type'])
                            except ValueError as exc: preview['issues'].append({'row':record['source_ref'],'error':definition['label']+': '+str(exc)})
                        record['custom_fields']=json.dumps(values,ensure_ascii=False)
                    st.session_state.import_preview=preview
                    st.session_state.import_context=context
                preview=st.session_state.get('import_preview')
                if preview and preview['filename']==filename and st.session_state.get('import_context')==context:
                    incoming,new_budgets,possible,conflicts=import_candidates(preview,state)
                    st.subheader('Normalized import review')
                    st.write(f'{len(incoming)} new transactions · {len(new_budgets)} new monthly budgets · {preview["skipped"]} blank/template/total rows skipped')
                    st.caption(f'{len(preview["transactions"])-len(incoming)} previously imported source rows skipped. Identical same-file source rows retain their separate row identities.')
                    if incoming: st.dataframe(transaction_view(incoming),hide_index=True,width='stretch')
                    if new_budgets: st.dataframe(frame(new_budgets)[['period','category','subcategory','amount','currency']],hide_index=True,width='stretch')
                    if preview['issues']:
                        st.error(f'{len(preview["issues"])} invalid rows. Correct the source/mapping and prepare review again; import is blocked.')
                        st.dataframe(frame(preview['issues']),hide_index=True)
                    if conflicts:
                        st.error('Conflicting budgets exist for the same month/category. Existing budgets will not be overwritten. Change them in Budgets or correct the source.')
                        st.dataframe(frame(conflicts),hide_index=True)
                    if possible:
                        st.warning(f'{len(possible)} possible duplicate records. They may be genuine repeated purchases/refunds. Review them before keeping all or excluding selected records.')
                        st.dataframe(frame(possible),hide_index=True,width='stretch')
                    excluded=st.multiselect('Exclude records from this import (optional)',[t['id'] for t in incoming],format_func=lambda id:next(f'{t["date"]} · {t["merchant"]} · {t["amount"]} · {id}' for t in incoming if t['id']==id)) if incoming else []
                    keep=[t for t in incoming if t['id'] not in excluded]
                    if any(cents(t['amount'],True,t['currency'])<0 for t in keep): st.info('Negative expense amounts are retained as refunds and reduce category spending; they are not relabeled as income.')
                    if any(t['category']=='ATM Withdrawal' for t in keep): st.caption('ATM Withdrawal retains its source category. If it is an internal transfer, edit its Type to transfer after import; transfers are excluded from income and spending. Planning excludes this category by default.')
                    if st.button('Stage reviewed import',disabled=bool(preview['issues'] or conflicts or not (keep or new_budgets))):
                        stage({'kind':'import','rows':keep,'budgets':new_budgets,'duplicates':bool(possible),'filename':filename},state)

elif page=='Add transaction':
    st.title('Record what happened')
    st.caption('Review the interpreted details and budget impact before every save.')
    method=st.radio('Entry method',['Traditional form','Sentence'],horizontal=True)
    if method=='Sentence':
        text=st.text_area('Describe a transaction',placeholder=f'I spent 45 {curr} at a shop yesterday')
        a,b,c=st.columns(3)
        reference=a.date_input('Today / reference date',value=dt.date.today())
        entry_curr=b.text_input('Currency',curr,key='sentence_curr_'+curr)
        entry_account=c.text_input('Account','Unspecified account',key='sentence_account')
        st.caption('Write an amount, today/yesterday or a YYYY-MM-DD date, and optionally a shop or income source. Simple local rules interpret it; review the result before saving. Currency symbols must match your selected currency.')
        if st.button('Interpret sentence',type='primary'):
            try:
                row,note=parse_sentence(text,reference,entry_curr,entry_account,tx,taxonomy)
                stage({'kind':'add','rows':[row],'note':note},state)
            except ValueError as exc: st.error(str(exc))
    else:
        with st.container(border=True):
            a,b,c=st.columns(3)
            date=a.date_input(field_label('date','Date')); typ=b.selectbox(field_label('type','Type'),['expense','income','transfer']); val=c.text_input(field_label('amount','Amount'),'45')
            a,b,c=st.columns(3)
            entry_curr=a.text_input(field_label('currency','Currency'),curr)
            merchant=b.text_input(field_label('merchant','Merchant / income source')) if 'merchant' in enabled else ''
            account=c.text_input(field_label('account','Account'),'Unspecified account') if 'account' in enabled else 'Unspecified account'
            description=st.text_input(field_label('description','Particulars')) if 'description' in enabled else ''
            a,b=st.columns(2)
            choices=category_options(taxonomy,tx,typ) if taxonomy else categories
            cat=a.selectbox(field_label('category','Category'),choices,index=choices.index('Uncategorized')) if 'category' in enabled else 'Uncategorized'
            sub=b.selectbox(field_label('subcategory','Subcategory'),suboptions(taxonomy,tx,typ,cat)) if 'subcategory' in enabled and taxonomy else b.text_input(field_label('subcategory','Subcategory')) if 'subcategory' in enabled else ''
            custom=custom_inputs(schema,'entry')
            refund=st.checkbox('Expense refund (reduces category spending)')
            split=st.checkbox('Split expense across two categories')
            a,b,c=st.columns(3)
            second_amount=a.text_input('Second split amount','0.00')
            second_cat=b.selectbox('Second category',choices,key='second_cat')
            second_sub=c.selectbox('Second subcategory',suboptions(taxonomy,tx,typ,second_cat)) if taxonomy else c.text_input('Second subcategory')
            submitted=st.button('Review transaction',type='primary')
            if submitted:
                try:
                    custom={f['key']:parse_custom(custom.get(f['key'],''),f['type']) for f in custom_definitions(schema)}
                    value=cents(val,curr=entry_curr)
                    if refund:
                        if typ!='expense': raise ValueError('Refund applies to expenses only.')
                        value=-value
                    row=valid_tx({'date':date.isoformat(),'type':typ,'amount':amount(value,entry_curr),'currency':entry_curr,'merchant':merchant,'description':description,'account':account,'category':cat,'subcategory':sub,'custom_fields':json.dumps(custom,ensure_ascii=False)})
                    rows=[row]
                    if split:
                        second=cents(second_amount,curr=entry_curr)
                        if typ!='expense' or refund or second<=0 or second>=value: raise ValueError('Split requires a positive expense and a second amount between zero and the total.')
                        rows=[valid_tx({**row,'amount':amount(value-second,entry_curr)}),valid_tx({**row,'id':'','amount':amount(second,entry_curr),'category':second_cat,'subcategory':second_sub})]
                    stage({'kind':'add','rows':rows},state)
                except ValueError as exc: st.error(str(exc))

elif page=='Transactions':
    st.title('Your confirmed transactions')
    a,b,c,d=st.columns(4)
    search=a.text_input('Search merchant, particulars or ID',key='tx_search')
    type_filter=b.selectbox('Type',['All','income','expense','transfer'],key='tx_type')
    category_filter=c.selectbox('Category',['All']+categories,key='tx_category')
    if 'tx_month_only' not in st.session_state: st.session_state.tx_month_only=True
    month_only=d.checkbox('Selected month only',key='tx_month_only')
    records=[t for t in tx if t['currency']==curr and (not month_only or t['date'][:7]==period) and (type_filter=='All' or t['type']==type_filter) and (category_filter=='All' or t['category']==category_filter) and (not search or search.casefold() in ' '.join(t.values()).casefold())]
    st.caption(f'{len(records)} records · {curr} · refunds appear as negative expenses')
    if records:
        records=sorted(records,key=lambda t:t['date'],reverse=True)
        st.dataframe(transaction_view(records),hide_index=True,width='stretch')
        st.download_button('Download filtered transactions CSV',csv_bytes(records,TX_FIELDS),'homeaccounts-transactions.csv','text/csv')
        id=st.selectbox('Record to edit / remove',[t['id'] for t in records],format_func=lambda id:next(f'{t["date"]} · {t["merchant"]} · {t["amount"]} · {id}' for t in records if t['id']==id))
        old=next(t for t in records if t['id']==id)
        with st.form('edit_'+id):
            fields=[f for f in TX_FIELDS if f not in ('source_ref','custom_fields')]
            edited=st.data_editor(frame([old],fields),disabled=['id'],hide_index=True,width='stretch',key='editor_'+id,column_config=field_labels)
            edited_custom=custom_inputs(schema,'edit_'+id,json.loads(old.get('custom_fields','{}') or '{}'))
            a,b=st.columns(2)
            edit=a.form_submit_button('Review changes'); remove=b.form_submit_button('Review removal')
            if edit:
                try:
                    values=json.loads(old.get('custom_fields','{}') or '{}')
                    values.update({f['key']:parse_custom(edited_custom.get(f['key'],''),f['type']) for f in custom_definitions(schema)})
                    row=valid_tx({**edited.to_dict('records')[0],'source_ref':old['source_ref'],'custom_fields':json.dumps(values,ensure_ascii=False)})
                    stage({'kind':'edit','before':[old],'rows':[row]},state)
                except ValueError as exc: st.error(str(exc))
            if remove: stage({'kind':'delete','before':[old],'rows':[]},state)
    else: st.info('No matching records. Adjust filters or import your data.')

elif page=='Budgets':
    st.title('Plan the month')
    st.caption('Category budgets include all their subcategories. A subcategory budget is a separate spending limit; parent and child limits are never added twice to the monthly total.')
    bs=[b for b in budgets if b['period']==period and b['currency']==curr]
    a,b,c=st.columns(3)
    planned=total_budget(budgets,period,curr); exp=spending(tx,period,curr)
    a.metric('Planned monthly budget',money(planned,curr)); b.metric('Net spending',money(exp,curr)); c.metric('Remaining',money(planned-exp,curr))
    report=[{'Category':b['category'],'Subcategory':b['subcategory'] or 'All','Budget':cents(b['amount'],curr=curr)/scale(curr),'Spent':spending(tx,period,curr,b['category'],b['subcategory'])/scale(curr),'Remaining':(cents(b['amount'],curr=curr)-spending(tx,period,curr,b['category'],b['subcategory']))/scale(curr)} for b in bs]
    if report: st.dataframe(frame(report),hide_index=True,width='stretch')
    if budgets: st.download_button('Download all budgets CSV',csv_bytes(budgets,BUDGET_FIELDS),'homeaccounts-budgets.csv','text/csv')
    with st.form('budget'):
        st.subheader('Add or adjust a budget')
        a,b,c=st.columns(3)
        budget_period=a.text_input('Month (YYYY-MM)',period)
        category=b.text_input('Category','Household')
        subcategory=c.text_input('Subcategory (blank = entire category)')
        a,b=st.columns(2)
        value=a.text_input('Budget amount','300.00'); budget_curr=b.text_input('Currency',curr)
        if st.form_submit_button('Review budget',type='primary'):
            try:
                new=valid_budget({'period':budget_period,'category':category,'subcategory':subcategory,'amount':value,'currency':budget_curr})
                old=next((b for b in budgets if budget_key(b)==budget_key(new)),None)
                if old: new['id']=old['id']; new['source_ref']=old['source_ref']
                stage({'kind':'budget','before':[old] if old else [],'rows':[new]},state)
            except ValueError as exc: st.error(str(exc))

elif page=='Coach':
    st.title('Talk through your money')
    available=configured()
    st.caption('OpenAI key: '+('available on this computer' if available else 'not configured')+' · Model: '+model_name())
    use_ai=st.checkbox('Enable connected OpenAI for this chat',value=False,disabled=not available,key='coach_use_ai')
    if use_ai:
        st.info('Connected mode sends your question, recent chat, verified totals, chosen categories and up to 50 records from the selected month/currency to OpenAI. API charges may apply. Every change is staged for review.')
    else: st.info('Local mode uses simple rules and confirmed records. No API call is made. Every change is staged for your review.')
    st.caption(f'Questions use {period} and {curr}. Change those in the sidebar.')
    with st.expander('Supported questions and actions'):
        st.write('Monthly summary · Household spending · Remaining budget')
        st.code(f'I spent 45 {curr} at a shop yesterday\nI earned 1000 yesterday\nset Household budget to 300 for {period}\nchange transaction FULL_ID amount to 20\ndelete transaction FULL_ID',language=None)
    a,b=st.columns(2)
    account=a.text_input('Account for proposed entries','Unspecified account',key='coach_account')
    reference=b.date_input('Today / reference date',value=dt.date.today(),key='coach_date')
    for message in st.session_state.get('chat',[]):
        with st.chat_message(message['role']): st.write(message['content'])
    text=st.chat_input('Ask about records or propose a change')
    if text:
        messages=st.session_state.setdefault('chat',[])
        messages.append({'role':'user','content':text})
        try:
            response,proposal=connected_coach(text,state,period,curr,account,reference,enabled=True,history=messages[:-1]) if use_ai else coach(text,state,period,curr,account,reference)
            messages.append({'role':'assistant','content':response})
            if proposal: stage({**proposal,'note':response},state)
            st.rerun()
        except ValueError as exc:
            messages.append({'role':'assistant','content':str(exc)}); st.rerun()

elif page=='Planning & Goals':
    try: show_planning(tx,period,curr)
    except ValueError as exc: st.error(str(exc))

# One shared confirmation gate for form, sentence, coach, imports and edits.
proposal=st.session_state.get('pending')
if proposal:
    st.divider()
    with st.container(border=True):
        st.subheader('Review before saving')
        st.caption('No changes have been saved yet. Correct the interpreted fields below, then confirm.')
        if proposal.get('note'): st.info(proposal['note'])
        kind=proposal['kind']
        if proposal.get('before'):
            st.write('Current record'); st.dataframe(frame(proposal['before']),hide_index=True,width='stretch')
        valid=True; rows=proposal.get('rows',[])
        if kind in ('add','edit','budget'):
            fields=BUDGET_FIELDS if kind=='budget' else TX_FIELDS
            edited=st.data_editor(frame(rows,fields),disabled=['id','source_ref'],hide_index=True,width='stretch',key=f'review_{st.session_state.review_key}',column_config=field_labels)
            try:
                rows=[(valid_budget if kind=='budget' else valid_tx)(r) for r in edited.to_dict('records')]
                if kind!='budget':
                    for row in rows:
                        values=json.loads(row['custom_fields'])
                        for f in custom_definitions(schema): values[f['key']]=parse_custom(values.get(f['key'],''),f['type'])
                        row['custom_fields']=json.dumps(values,ensure_ascii=False)
            except (ValueError,TypeError) as exc: st.error(str(exc)); valid=False
        elif kind=='import':
            st.write(f'Import {len(rows)} transactions and {len(proposal["budgets"])} budgets from {proposal["filename"]}.')
            with st.expander('Exact records to save',expanded=False):
                if rows: st.dataframe(frame(rows),hide_index=True,width='stretch')
                if proposal['budgets']: st.dataframe(frame(proposal['budgets']),hide_index=True,width='stretch')
        elif kind=='delete': st.warning('This will remove the displayed transaction. Undo remains available.')
        if valid and kind in ('add','edit'):
            replacement=proposal['before'][0]['id'] if kind=='edit' else None
            provisional={'transactions':tx,'budgets':budgets}
            for row in rows:
                impact=impacts(provisional,row,replacement)
                if impact:
                    st.write('Before-save category budget impact'); st.dataframe(frame(impact),hide_index=True,width='stretch')
                    if any(cents(i['over_budget'],curr=i['currency'])>0 for i in impact):
                        st.warning('This entry exceeds a budget. You can record the actual expense, revise the entry, review/reduce future spending, or cancel and propose a budget adjustment in Budgets. Budgets never increase automatically.')
                elif row['type']=='expense': st.caption(f'No matching monthly budget for {row["category"]}.')
                provisional={'transactions':[t for t in provisional['transactions'] if t['id']!=replacement]+[row],'budgets':budgets}; replacement=None
            if rows:
                p=rows[0]['date'][:7]; cu=rows[0]['currency']
                before=spending(tx,p,cu); after=spending(provisional['transactions'],p,cu)
                st.write(f'Overall {p}: net spending {money(before,cu)} → {money(after,cu)}; budget remains {money(total_budget(budgets,p,cu),cu)}.')
        if valid and kind=='budget':
            new=rows[0]
            after=[b for b in budgets if budget_key(b)!=budget_key(new)]+[new]
            before=total_budget(budgets,new['period'],new['currency']); planned=total_budget(after,new['period'],new['currency'])
            inc=income(tx,new['period'],new['currency'])
            st.write(f'Overall month {new["period"]}: planned budget {money(before,new["currency"])} → {money(planned,new["currency"])}. Recorded income less planned budget: {money(inc-planned,new["currency"])}.')
        possible=proposal.get('duplicates',False) or (kind=='add' and any(fingerprint(r)==fingerprint(t) for r in rows for t in tx))
        ack=True
        if possible: ack=st.checkbox('I reviewed possible duplicates and want to keep these records',key=f'dup_{st.session_state.review_key}')
        if any(r.get('category')=='Uncategorized' for r in rows): ack=st.checkbox('Save these records as Uncategorized (I can classify them later)',key=f'uncat_{st.session_state.review_key}') and ack
        stale=proposal['revision']!=state['revision']
        if stale: st.error('Saved data changed after this preview. Cancel and prepare a new review.')
        a,b=st.columns(2)
        if a.button('Confirm save' if kind!='delete' else 'Confirm delete',type='primary',disabled=not(valid and ack) or stale):
            try:
                apply_proposal(store,state,{**proposal,'rows':rows})
                st.session_state.pop('pending',None); st.session_state.notice='Confirmed changes saved. Undo is available in the sidebar.'; st.rerun()
            except (ValueError,OSError) as exc: st.error(str(exc))
        if b.button('Cancel proposal'):
            st.session_state.pop('pending',None); st.rerun()

st.divider()
st.caption('Home Accounts · Course prototype · Local CSV storage · Reports reflect confirmed records, with no currency conversion.')
