"""Currency codes and standard accounting precision from Babel/CLDR."""
from decimal import Decimal
from babel.numbers import list_currencies, get_currency_name, get_currency_precision, format_currency
from babel import Locale
from babel.core import get_global

CODES=sorted(c for c in list_currencies() if c not in ('XXX','XTS'))
_territories = Locale('en').territories
_countries = {}
for _territory, _entries in get_global('territory_currencies').items():
    for _code, _start, _end, _tender in _entries:
        if _end is None and _tender:
            _countries.setdefault(_code, []).append(_territories.get(_territory, _territory))

def search_terms(code):
    """Local CLDR names; country search never contacts a third party."""
    return ' '.join(_countries.get(code, []))

def validate(code):
    code=str(code).strip().upper()
    if code not in CODES: raise ValueError('Choose a supported ISO currency code, such as INR, EUR or JPY.')
    return code

def digits(code=None): return get_currency_precision(validate(code)) if code else 2
def scale(code=None): return 10**digits(code)
def label(code): return f'{code} — {get_currency_name(code,locale="en")}'
def display(value,code):
    return format_currency(Decimal(str(value)),validate(code),'¤¤ #,##0.00',locale='en_US')
def display_minor(value,code): return display(Decimal(value)/scale(code),code)
