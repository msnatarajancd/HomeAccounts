"""Illustrative planning arithmetic; no market data or investment recommendations."""
import math
from core import cents
from currencies import scale

def finite(value, label):
    try: n=float(value)
    except (ValueError,TypeError): raise ValueError(f'{label} must be numeric.')
    if not math.isfinite(n): raise ValueError(f'{label} must be finite.')
    return n

def compound_growth(principal, contribution, years, annual_rate, periods=1, frequency='Annual', timing='End', inflation=0, curr=None):
    principal=cents(principal,curr=curr)/scale(curr); contribution=cents(contribution,curr=curr)/scale(curr)
    rate=finite(annual_rate,'Return')/100; inf=finite(inflation,'Inflation')/100
    if not isinstance(years,int) or not 0<=years<=100: raise ValueError('Years must be an integer between 0 and 100.')
    if not isinstance(periods,int) or not 1<=periods<=365: raise ValueError('Compounding periods must be between 1 and 365.')
    if not -1<rate<=1: raise ValueError('Return must be greater than -100% and at most 100%.')
    if not -1<inf<=1: raise ValueError('Inflation must be greater than -100% and at most 100%.')
    if frequency not in ('Annual','Monthly') or timing not in ('Beginning','End'): raise ValueError('Invalid contribution frequency or timing.')
    steps=12 if frequency=='Monthly' else 1
    step_rate=(1+rate/periods)**(periods/steps)-1
    balance=principal; paid=principal
    rows=[{'Year':0,'Contributions':principal,'Growth':0.,'Projected value':principal,'Inflation-adjusted value':principal}]
    for year in range(1,years+1):
        for _ in range(steps):
            if timing=='Beginning': balance+=contribution
            balance*=1+step_rate
            if timing=='End': balance+=contribution
            paid+=contribution
        rows.append({'Year':year,'Contributions':paid,'Growth':balance-paid,'Projected value':balance,'Inflation-adjusted value':balance/(1+inf)**year})
    return rows

def fire_target(annual_expenses, withdrawal_rate,curr=None):
    expenses=cents(annual_expenses,curr=curr)/scale(curr)
    rate=finite(withdrawal_rate,'Withdrawal rate')
    if not 0<rate<=100: raise ValueError('Withdrawal rate must be greater than 0% and at most 100%.')
    return expenses/(rate/100)

def variance(budget,actual,curr=None):
    budget=cents(budget,curr=curr); actual=cents(actual,True,curr)
    difference=actual-budget
    return {'difference':difference/scale(curr),'percent':difference/budget*100 if budget else None,'label':'Over budget' if difference>0 else 'Under budget' if difference<0 else 'On budget'}
