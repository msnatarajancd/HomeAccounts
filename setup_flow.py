"""Two-path onboarding and persisted, functional optional field definitions."""
import datetime as dt
from decimal import Decimal, InvalidOperation
import json
import os
import re
import uuid
from pathlib import Path
import pandas as pd
import streamlit as st
from currencies import CODES,label as currency_label
from core import MONTHS, read_tables, csv_bytes
from categories import STARTER,reconcile

from schema import BASE,ALIASES,schema_path,load_schema,suggested_schema,interpret_fields,validate_schema,save_schema,custom_definitions,parse_custom

def custom_inputs(schema,prefix,values=None):
    values=values or {}; out={}
    for field in custom_definitions(schema):
        key=field['key']; old=values.get(key,''); widget=prefix+'_'+key
        if field['type']=='Boolean': value=st.checkbox(field['label'],value=old is True,key=widget)
        elif field['type']=='Date':
            value=st.date_input(field['label'],value=dt.date.fromisoformat(str(old)) if old else None,key=widget)
            value=value.isoformat() if value else ''
        else: value=st.text_input(field['label'],value=str(old),key=widget)
        out[key]=value
    return out

def show_setup(store,revisit=False):
    st.markdown('<div class="welcome-hero"><h1>Home Accounts</h1><h3>Understand your spending.<br>Build a budget. Plan your future.</h3></div>',unsafe_allow_html=True)
    st.write('Start with your household data, or tell us what you want to track. You’ll review and confirm the suggested fields first.')
    if revisit and st.button('Return to your workspace'):
        st.session_state.revisit_setup=False; st.session_state.pop('setup_proposal',None); st.rerun()
    if revisit: st.caption('Changing field setup will not clear or relabel your saved records. Values in removed optional fields stay in existing records.')
    upload_tab,fields_tab=st.tabs(['Upload a file','Describe your fields'])
    with upload_tab:
        st.write('A full history, a few recent records, or sample data all work. Your file might include dates, particulars, income/expense amounts, categories or optional budgets.')
        upload=st.file_uploader('Upload your household transactions',type=['csv','tsv','xlsx'],key='welcome_upload')
        if upload and upload.size>10_000_000: st.error('Please use a file smaller than 10 MB.')
        if upload and upload.size<=10_000_000 and st.button('Suggest fields from this file',type='primary'):
            try:
                data=upload.getvalue(); tables=read_tables(data,upload.name)
                sheet=next((s for s in MONTHS if s in tables and tables[s]),next((s for s in tables if tables[s]),None))
                if sheet is None: raise ValueError('This file is empty. Add headers and at least a sample row, or describe fields instead.')
                header=tables[sheet][0]
                rows,notes=suggested_schema(header)
                st.session_state.setup_proposal={'fields':rows,'notes':notes,'filename':upload.name,'data':data,'preview':tables[sheet][1:6],'headers':header}
            except (ValueError,OSError,UnicodeError) as exc: st.error(str(exc))
        with st.expander('Template and fictional demo data'):
            st.download_button('Download a blank CSV template',csv_bytes([],['date','type','amount','currency','particulars','category']),'homeaccounts-template.csv','text/csv')
            sample=Path(__file__).resolve().parent/'sample_data'/'household_demo.csv'
            if sample.exists():
                st.caption('Bundled demo data is entirely fictional. The household file contains EUR and INR records; the second file is a snapshot, not transaction history.')
                st.download_button('Download fictional household demo',sample.read_bytes(),sample.name,'text/csv')
                snapshot=sample.with_name('balances_wishlist_demo.csv')
                st.download_button('Download fictional balances & wishes',snapshot.read_bytes(),snapshot.name,'text/csv')
                if st.button('Try demo data'):
                    data=sample.read_bytes(); tables=read_tables(data,sample.name)
                    rows,notes=suggested_schema(tables['CSV'][0])
                    st.session_state.setup_proposal={'fields':rows,'notes':notes,'filename':sample.name,'data':data,'preview':tables['CSV'][1:6],'headers':tables['CSV'][0]}
    with fields_tab:
        from ai_client import configured,field_suggestions,model_name
        st.caption('Local field interpreter · optional connected AI')
        with st.expander('Optional OpenAI field suggestions'):
            available=configured()
            st.caption('OpenAI key: '+('available on this computer' if available else 'not configured')+' · Model: '+model_name())
            use_ai=st.checkbox('Use OpenAI to interpret my field description',value=False,disabled=not available,key='setup_use_ai')
            st.caption('When enabled, only the description you enter here is sent to OpenAI; API charges may apply. Uploaded files are interpreted locally. Suggestions still require your confirmation.')
        text=st.text_area('What would you like to track?',placeholder='date, category, particulars, expense amount, income amount, monthly budget, payment method')
        if st.button('Suggest fields from my description',type='primary'):
            try:
                rows,notes=field_suggestions(text,enabled=True) if use_ai else interpret_fields(text)
                st.session_state.setup_proposal={'fields':rows,'notes':notes,'filename':'','headers':[]}
            except ValueError as exc: st.error(str(exc))
    proposal=st.session_state.get('setup_proposal')
    if proposal:
        st.divider()
        st.caption('STEP 2 OF 3 · REVIEW YOUR FIELDS → CONFIRM → OPEN YOUR WORKSPACE')
        st.subheader('Here are the fields I suggest using')
        if st.button('Back to the starting options'):
            st.session_state.pop('setup_proposal',None); st.session_state.pop('setup_currency',None); st.rerun()
        st.caption('Rename displayed names, choose custom field types, uncheck optional fields, or add/remove optional rows. Date, type, amount and currency are needed to calculate reports. Custom values are saved with your records.')
        for note in proposal['notes']: st.info(note)
        edited=st.data_editor(pd.DataFrame(proposal['fields']),disabled=['key','required'],num_rows='dynamic',hide_index=True,width='stretch',column_config={'type':st.column_config.SelectboxColumn('Type',options=['Text','Number','Date','Boolean']),'included':st.column_config.CheckboxColumn('Include'),'label':'Field name','source':'Source column / interpretation'},key='schema_editor_'+proposal.get('filename','')+str(proposal['fields']))
        common=['INR','EUR','USD','GBP','CAD','AUD','JPY','CNY','CHF','SGD','NZD']
        choices=['(Choose currency)']+common+[c for c in CODES if c not in common]
        suggested=None
        if proposal.get('preview'):
            header=[str(h).strip().casefold() for h in proposal['headers']]
            if 'currency' in header:
                col=header.index('currency')
                found=[str(r[col]).strip().upper() for r in proposal['preview'] if len(r)>col and str(r[col]).strip().upper() in CODES]
                if found: suggested=max(set(found),key=found.count)
        if suggested: st.caption('Suggested from the file’s sample rows: '+suggested+'. You can choose another default.')
        curr=st.selectbox('Default currency (required)',choices,index=choices.index(suggested) if suggested else 0,format_func=lambda code:currency_label(code) if code in CODES else code,key='setup_currency',help='Needed for new records and any file row missing currency. This does not convert existing amounts.')
        st.caption('Existing currency codes are preserved. Choosing a default does not convert or relabel saved records.')
        if proposal.get('preview'):
            st.write('Source sample'); st.dataframe(pd.DataFrame(proposal['preview']),hide_index=True,width='stretch')
        valid=True
        try: proposed=validate_schema(edited.to_dict('records'))
        except ValueError as exc: st.error(str(exc)); valid=False; proposed=[]
        if proposed:
            st.write('Entry screen preview: '+', '.join(f['label'] for f in proposed if f['included'])+'.')
            st.caption('Reports will show income, expenses and monthly/category trends. Budgets and planning are optional. Custom fields appear in entry, record review and CSV exports; they do not create new calculations.')
        taxonomy=None
        with st.expander('Optional household category suggestions'):
            st.write('These are editable suggestions, not a universal standard. Existing imported classifications will stay unchanged. Removing a referenced category archives it rather than deleting its records.')
            apply=st.checkbox('Apply this category and subcategory list for new entries',key='apply_taxonomy')
            if apply:
                current=load_schema(store).get('taxonomy',[])
                table=st.data_editor(pd.DataFrame(current or STARTER),num_rows='dynamic',hide_index=True,width='stretch',column_config={'type':st.column_config.SelectboxColumn('Type',options=['income','expense','transfer']),'active':st.column_config.CheckboxColumn('Available for new entries')},key='taxonomy_editor')
                taxonomy=table.to_dict('records')
                st.caption('Confirming below also accepts this list and enables category/subcategory inputs. Edit, add or remove rows as you prefer. Transfers are separate from consumption; refunds reduce expenses.')
                try:
                    state=store.load(); reconcile(taxonomy,current,state['transactions'],state['budgets'])
                except ValueError as exc: st.error(str(exc)); valid=False
        if curr not in CODES:
            st.warning('One step left: choose a default currency above to enable Confirm fields & continue.')
        elif not valid:
            st.warning('Fix the field error shown above to enable confirmation.')
        else:
            st.success('Your fields and currency are ready. Confirm below to open the workspace. Uploaded records will still be reviewed before saving.')
        if st.button('Confirm fields & continue',type='primary',disabled=not valid or curr not in CODES):
            save_schema(store,proposed,curr,taxonomy)
            st.session_state.pop('active_currency',None)
            st.session_state.revisit_setup=False
            st.session_state.manual_start=True
            if proposal.get('data'):
                st.session_state.onboarding_file=(proposal['filename'],proposal['data'])
                st.session_state.page='Import & review'
            else: st.session_state.page='Add transaction'
            st.session_state.pop('setup_proposal',None)
            st.session_state.notice='Fields confirmed. Review an import or add your first record; nothing has been imported yet.'
            st.rerun()
    st.caption('Runs on this computer. No API key is required for local mode. Optional connected AI sends only the disclosed context when enabled.')
