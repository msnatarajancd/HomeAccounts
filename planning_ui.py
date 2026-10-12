import datetime as dt
import pandas as pd
import plotly.express as px
import streamlit as st
from core import cents, amount, spending, income
from planning import compound_growth, fire_target, variance
from currencies import scale, digits

def show_planning(tx,period,curr):
    precision=digits(curr)
    def monetary_input(parent,title,**kwargs):
        return parent.number_input(title+' ('+curr+')',format='%.'+str(precision)+'f',**kwargs)
    st.title('Planning & Goals')
    st.write('Expense tracking comes first. Budgets are optional. Use your records to explore savings goals and future scenarios.')
    st.info('These are illustrative calculations using your assumptions. Recorded surplus is not automatically saved or invested. Portfolio assets are entered separately from cash balances and income.')
    inc=income(tx,period,curr); exp=spending(tx,period,curr)
    a,b=st.columns(2)
    a.metric('Recorded monthly surplus',f'{curr} {amount(inc-exp,curr)}')
    verified=b.text_input('Verified invested contributions this month (optional)',placeholder='Enter only an amount you actually invested')
    if verified:
        try: st.caption(f'User-confirmed invested contributions: {curr} {amount(cents(verified,curr=curr),curr)}. This is separate from recorded surplus and does not create a transaction.')
        except ValueError as exc: st.error(str(exc))
    else: st.caption('Imported records do not identify invested contributions. No invested amount is inferred.')
    goals,fire,growth,quick,learn=st.tabs(['Savings goals','FIRE scenario','Compound growth','Budget variance','Learn'])
    with goals:
        st.subheader('A goal you choose')
        name=st.text_input('Optional saving goal',placeholder='Emergency fund, a course, a home…')
        a,b,c=st.columns(3)
        target=monetary_input(a,'Goal amount',min_value=0.,value=0.,step=100.)
        saved=monetary_input(b,'Cash already saved toward this goal',min_value=0.,value=0.,step=100.)
        horizon=c.number_input('Goal horizon in months',min_value=1,max_value=1200,value=12)
        pct=st.slider('Desired percentage of recorded income to save/invest',0,100,20)
        planned=inc/scale(curr)*pct/100
        st.write(f'{pct}% of recorded {period} income is {curr} {planned:,.{precision}f}. This is a plan, not evidence of a contribution.')
        if inc-exp<round(planned*scale(curr)): st.caption('Recorded surplus is below this planned allocation. Review expenses or adjust the scenario; no budget or transaction is changed.')
        if name and target:
            st.progress(min(saved/target,1.))
            st.write(f'{name}: {curr} {max(0,target-saved):,.{precision}f} remaining; {curr} {max(0,target-saved)/horizon:,.{precision}f} per month to close the gap over {horizon} months, before interest.')
        st.caption('Planning inputs stay in the current browser session. Cash-goal progress and portfolio progress are separate.')
    with fire:
        st.subheader('Explore a financial independence target')
        years=sorted({t['date'][:4] for t in tx if t['currency']==curr},reverse=True) or [str(dt.date.today().year)]
        year=st.selectbox('Observed year for an expense estimate',years)
        source=[t for t in tx if t['currency']==curr and t['date'].startswith(year)]
        transfer_cats=st.multiselect('Also exclude categories that represent transfers',sorted({t['category'] for t in source}),default=['ATM Withdrawal'] if any(t['category']=='ATM Withdrawal' for t in source) else [])
        expenses=[t for t in source if t['type']=='expense' and t['category'] not in transfer_cats]
        months=sorted({t['date'][:7] for t in source})
        net=sum(cents(t['amount'],True,curr) for t in expenses)
        estimate=net/scale(curr)*12/len(months) if months else 0
        if source:
            dates=sorted(t['date'] for t in source)
            st.caption(f'Observed records: {dates[0]} to {dates[-1]}, {len(months)} months with entries. Net expense after refunds and transfer exclusions: {curr} {net/scale(curr):,.{precision}f}.')
            st.warning(f'Annualized estimate: {curr} {estimate:,.{precision}f} = observed net expense ÷ {len(months)} observed months × 12. This is not a complete-year total. Partial months and missing records can distort it; override the estimate below.')
        else: st.caption('No observed records. Enter your own annual expense assumption.')
        a,b,c=st.columns(3)
        annual=monetary_input(a,'Expected annual expenses (today’s money)',min_value=0.,value=max(0.,round(estimate,precision)),step=100.,key=f'annual_{curr}_{year}_{len(transfer_cats)}')
        withdrawal=b.number_input('Chosen withdrawal rate (%)',min_value=0.1,max_value=100.,value=4.,step=0.1)
        portfolio=monetary_input(c,'Current invested portfolio assets',min_value=0.,value=0.,step=1000.)
        target=fire_target(annual,withdrawal,curr)
        a,b,c=st.columns(3)
        a.metric('Illustrative target today',f'{curr} {target:,.{precision}f}')
        b.metric('Expense multiple',f'{100/withdrawal:.2f}×')
        c.metric('Portfolio progress',f'{portfolio/target*100:.1f}%' if target else 'Enter annual expenses')
        if target: st.progress(min(portfolio/target,1.))
        st.caption('Target = annual expenses ÷ withdrawal rate. At 4%, this equals 25× annual expenses. This adjustable heuristic is not a guarantee or a recommendation to stop work. Taxes, fees, market volatility, retirement duration and other income are not modeled.')
        st.markdown('[Learn about withdrawal-rate assumptions at Fidelity](https://www.fidelity.com/viewpoints/retirement/how-long-will-savings-last)')
        a,b,c=st.columns(3)
        addition=monetary_input(a,'Planned portfolio contribution',min_value=0.,value=0.,step=100.,key='fire_addition_'+curr)
        frequency=b.selectbox('Contribution frequency',['Monthly','Annual'],key='fire_frequency')
        horizon=c.number_input('Planning horizon in years',min_value=0,max_value=100,value=10,key='fire_horizon')
        a,b=st.columns(2)
        rate=a.number_input('Assumed annual return (%)',min_value=-99.,max_value=100.,value=5.,step=0.5,key='fire_return')
        inflation=b.number_input('Assumed annual inflation (%)',min_value=-99.,max_value=100.,value=2.,step=0.5,key='fire_inflation')
        result=compound_growth(portfolio,addition,int(horizon),rate,1,frequency,'End',inflation,curr)[-1]
        horizon_target=target*(1+inflation/100)**horizon
        st.write(f'At the chosen horizon, projected nominal portfolio: {curr} {result["Projected value"]:,.{precision}f}; inflation-adjusted portfolio in today’s money: {curr} {result["Inflation-adjusted value"]:,.{precision}f}; target inflated to that year: {curr} {horizon_target:,.{precision}f}.')
        if st.checkbox('Compare a second return assumption'):
            other=st.number_input('Second annual return assumption (%)',min_value=-99.,max_value=100.,value=3.,step=0.5)
            comparison=[]
            for chosen in (rate,other):
                row=compound_growth(portfolio,addition,int(horizon),chosen,1,frequency,'End',inflation,curr)[-1]
                comparison.append({'Annual return assumption %':chosen,'Inflation %':inflation,'Years':horizon,'Contribution':addition,'Frequency':frequency,'Nominal portfolio':row['Projected value'],'Portfolio in today’s money':row['Inflation-adjusted value'],'Horizon target':horizon_target})
            st.dataframe(pd.DataFrame(comparison),hide_index=True,width='stretch')
        st.caption('Scenario uses annual compounding, end-of-period contributions and a fixed rate every year. Contributions are planned, not confirmed. Market returns are not promised.')
    with growth:
        st.subheader('Compound-growth calculator')
        a,b,c=st.columns(3)
        principal=monetary_input(a,'Principal',min_value=0.,value=1000.,step=100.)
        contribution=monetary_input(b,'Contribution per chosen period',min_value=0.,value=100.,step=10.)
        frequency=c.selectbox('Contribution mode',['Annual','Monthly'])
        a,b,c=st.columns(3)
        horizon=a.number_input('Years',min_value=0,max_value=100,value=10)
        rate=b.number_input('Annual rate (%)',min_value=-99.,max_value=100.,value=5.,step=0.5)
        periods=c.number_input('Compounding periods per year',min_value=1,max_value=365,value=1)
        a,b=st.columns(2)
        timing=a.selectbox('Contribution timing',['End','Beginning'])
        inflation=b.number_input('Inflation for today’s-money view (%)',min_value=-99.,max_value=100.,value=2.,step=0.5)
        rows=compound_growth(principal,contribution,int(horizon),rate,int(periods),frequency,timing,inflation,curr)
        final=rows[-1]; a,b,c=st.columns(3)
        a.metric('Projected future value',f'{curr} {final["Projected value"]:,.{precision}f}')
        b.metric('Principal + contributions',f'{curr} {final["Contributions"]:,.{precision}f}')
        c.metric('Modeled growth / loss',f'{curr} {final["Growth"]:,.{precision}f}')
        st.caption(f'Assumptions: {curr}; {rate}% nominal annual rate; {periods} compounding periods/year; {contribution:,.{precision}f} contributed {frequency.lower()} at the {timing.lower()}; {horizon} years; inflation {inflation}%. No fees, taxes or variable returns.')
        real=st.checkbox('Show inflation-adjusted value on chart')
        chart_fields=['Projected value','Contributions']+(['Inflation-adjusted value'] if real else [])
        st.plotly_chart(px.line(pd.DataFrame(rows),x='Year',y=chart_fields,labels={'value':curr},color_discrete_sequence=['#167b6b','#dfa164','#6973b4']),width='stretch')
        st.dataframe(pd.DataFrame(rows).round(precision),hide_index=True,width='stretch')
        st.caption('Growth uses (1 + annual rate / compounding periods) raised to compounding periods per contribution interval. Monthly deposits use the equivalent monthly rate; annual additions use the annual effective rate. Zero years makes no additions.')
        st.markdown('[Investor.gov compound-interest calculator](https://www.investor.gov/financial-tools-calculators/calculators/compound-interest-calculator) · [Moneychimp calculator inspiration](https://www.moneychimp.com/calculator/compound_interest_calculator.htm)')
    with quick:
        st.subheader('Quick budget variance')
        a,b=st.columns(2)
        planned=monetary_input(a,'Budget for comparison',min_value=0.,value=300.,step=10.)
        actual=monetary_input(b,'Actual spending, net of refunds',value=315.,step=10.)
        row=variance(planned,actual,curr)
        st.metric(row['label'],f'{curr} {abs(row["difference"]):,.{precision}f}',f'{row["percent"]:+.2f}%' if row['percent'] is not None else 'Percentage undefined for zero budget',delta_color='off')
        st.caption('Difference = actual − budget. Percentage = (actual − budget) ÷ budget × 100. Positive is over budget; negative is under. A zero budget has no defined percentage.')
        if row['difference']>0: st.write('Actual spending exceeds this comparison amount. Review the records, consider future spending, or propose an intentional budget adjustment in Budgets.')
        elif row['difference']<0: st.write('Actual spending is below this comparison amount. This difference is not proof that money was saved or invested.')
        else: st.write('Actual spending matches the comparison amount.')
        st.caption('This calculator does not save or change budgets.')
    with learn:
        st.subheader('Learn one concept at a time')
        st.write('Tracking gives you information to make your next decision. Start with a clear record, then choose a goal you can revisit.')
        st.markdown('**Surplus:** recorded income minus net expenses. It does not prove a transfer to savings or investments. **Compound growth:** prior growth becomes part of the amount that grows next. **Inflation:** a way to express a future amount in today’s purchasing power. **FIRE target:** an adjustable expense-based scenario, separate from cash balances and annual salary.')
        st.markdown('Book to explore: **The Millionaire Next Door: The Surprising Secrets of America’s Wealthy**, by **Thomas J. Stanley and William D. Danko**. [Publisher details](https://www.simonandschuster.net/books/The-Millionaire-Next-Door/Thomas-J-Stanley/9781630762506).')
        st.markdown('- [Investor.gov: compound-interest calculator](https://www.investor.gov/financial-tools-calculators/calculators/compound-interest-calculator)\n- [Morningstar: personal finance learning](https://www.morningstar.com/personal-finance)\n- [NerdWallet: compound interest explained](https://www.nerdwallet.com/banking/learn/what-is-compound-interest)\n- [Fidelity: withdrawal-rate assumptions](https://www.fidelity.com/viewpoints/retirement/how-long-will-savings-last)')
        st.caption('External links are learning resources, not product endorsements or promises. Concepts, return assumptions and plans are distinct from confirmed transactions.')
