"""Read-only dashboard with explicit scope and working record drilldowns."""
import pandas as pd
import plotly.express as px
import streamlit as st
from core import income,spending,total_budget
from currencies import scale,display_minor

def navigate(page, curr=None, month=None, category='All'):
    st.session_state.page=page
    if curr and month: st.session_state['report_month_'+curr]=month
    if page=='Transactions':
        st.session_state.tx_category=category
        st.session_state.tx_type='All'
        st.session_state.tx_search=''
        st.session_state.tx_month_only=True

def show_overview(tx,budgets,period,curr,transaction_view):
    st.markdown('<div class="hero"><h2>Your month at a glance.</h2><p>See confirmed income, spending and budget progress, then open the records behind each total.</p></div>',unsafe_allow_html=True)
    st.write('This dashboard summarizes your confirmed records. Add or correct records in Transactions, and set limits in Budgets. Nothing is saved by viewing a report.')
    scoped=[t for t in tx if t['date'][:7]==period and t['currency']==curr]
    bs=[b for b in budgets if b['period']==period and b['currency']==curr]
    currency_records=[t for t in tx if t['currency']==curr]
    st.caption(f'Reporting: {period} · {curr} · {len(scoped)} confirmed transactions. Change currency and month in the sidebar.')
    a,b,c=st.columns(3)
    a.button('View this month’s transactions',on_click=navigate,args=('Transactions',curr,period),disabled=not scoped,width='stretch')
    b.button('Add an entry',on_click=navigate,args=('Add transaction',),width='stretch')
    c.button('Import transactions',on_click=navigate,args=('Import & review',),width='stretch')
    if not scoped:
        if not tx:
            st.info('You have not confirmed any transactions yet. Confirming fields creates your workspace; it does not import your uploaded records. Open Import transactions, prepare and review the import, then Confirm save. You can also add an entry.')
        elif not currency_records:
            populated=sorted({t['currency'] for t in tx})
            st.info(f'No confirmed transactions use {curr}. Your records use '+', '.join(populated)+'. Choose one of those currencies in the sidebar, or add/import records in '+curr+'.')
        else:
            latest=max(t['date'][:7] for t in currency_records)
            st.info(f'No confirmed {curr} transactions for {period}. Other recorded months are '+', '.join(sorted({t['date'][:7] for t in currency_records},reverse=True))+'.')
            st.button('Show latest recorded month',on_click=navigate,args=('Overview',curr,latest),type='primary')
        if bs:
            st.metric('Planned budget for this selection',display_minor(total_budget(bs,period,curr),curr))
            st.caption('Spending cannot be assessed until transactions are confirmed for this month/currency.')
        st.button('Set or review budgets',on_click=navigate,args=('Budgets',))
        return
    inc=income(tx,period,curr); exp=spending(tx,period,curr); planned=total_budget(bs,period,curr)
    a,b,c,d=st.columns(4)
    a.metric('Confirmed income',display_minor(inc,curr),help='Sum of confirmed income records in the chosen month and currency.')
    b.metric('Net expenses',display_minor(exp,curr),help='Expense amounts minus negative expense refunds. Transfers are excluded.')
    c.metric('Income minus expenses',display_minor(inc-exp,curr),help='Recorded surplus, not proof of saving or investing.')
    d.metric('Budget remaining',display_minor(planned-exp,curr) if bs else 'Not set',help='Planned monthly budget minus all net expenses. Parent and child limits are not added twice.')
    st.caption('Expenses include refunds; transfers are excluded from income and spending. Surplus = income − net expenses. '+
        (f'Planned budget: {display_minor(planned,curr)}. Remaining = planned budget − net expenses; negative means overspent.' if bs else 'No budget for this selection. Set a budget below to compare a plan with spending.'))
    st.button('Set or review budgets',on_click=navigate,args=('Budgets',))
    left,right=st.columns([1.25,1])
    with left:
        st.subheader('Monthly income & expenses')
        st.caption(f'All recorded months in {curr}. Hover for amounts; select a bar to open that month’s records.')
        months=sorted({t['date'][:7] for t in currency_records})
        chart=[{'Month':m,'Income':income(tx,m,curr)/scale(curr),'Net expenses':spending(tx,m,curr)/scale(curr)} for m in months]
        fig=px.bar(pd.DataFrame(chart),x='Month',y=['Income','Net expenses'],custom_data=['Month'],barmode='group',
            color_discrete_sequence=['#188774','#edac72'],labels={'value':curr,'variable':'Type'})
        fig.update_layout(plot_bgcolor='white',paper_bgcolor='rgba(0,0,0,0)',legend_title_text='',margin=dict(l=0,r=0,t=15,b=0))
        event=st.plotly_chart(fig,width='stretch',on_select='rerun',selection_mode='points',key='overview_month_'+curr)
        points=event.selection.points
        if points:
            selected=points[0].get('customdata',[''])[0]
            if selected in months: st.button('Open transactions for '+selected,on_click=navigate,args=('Transactions',curr,selected))
    with right:
        st.subheader('Category spending & budget')
        st.caption(f'{period} · {curr}. Select a category bar to open its records. Missing budgets are not spending limits.')
        cats=sorted({t['category'] for t in scoped if t['type']=='expense'}|{b['category'] for b in bs})
        if cats:
            chart=[{'Category':cat,'Budget':total_budget([b for b in bs if b['category']==cat],period,curr)/scale(curr),
                'Net expenses':spending(tx,period,curr,cat)/scale(curr)} for cat in cats]
            fig=px.bar(pd.DataFrame(chart),x=['Budget','Net expenses'],y='Category',custom_data=['Category'],barmode='group',orientation='h',
                color_discrete_sequence=['#b7d8d1','#188774'],labels={'value':curr})
            fig.update_layout(height=max(350,len(cats)*35),plot_bgcolor='white',paper_bgcolor='rgba(0,0,0,0)',legend_title_text='',margin=dict(l=0,r=0,t=15,b=0))
            event=st.plotly_chart(fig,width='stretch',on_select='rerun',selection_mode='points',key='overview_category_'+curr+period)
            points=event.selection.points
            if points:
                selected=points[0].get('customdata',[''])[0]
                if selected in cats: st.button('Open '+selected+' transactions',on_click=navigate,args=('Transactions',curr,period,selected))
            with st.expander('View category amounts and open records'):
                st.dataframe(pd.DataFrame(chart),hide_index=True,width='stretch')
                category=st.selectbox('Category to inspect',cats,key='overview_inspect_'+curr+period)
                st.button('View selected category records',on_click=navigate,args=('Transactions',curr,period,category))
        else: st.info('This selection has no expenses or category budgets yet. Income and transfers appear in Transactions.')
    st.subheader('Recent activity in this selection')
    st.dataframe(transaction_view(sorted(scoped,key=lambda t:t['date'],reverse=True)[:8]),hide_index=True,width='stretch')
