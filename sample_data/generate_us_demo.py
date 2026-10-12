"""Rebuild the deterministic fictional US demo CSVs; never touches the local store."""
import calendar
import csv
from pathlib import Path

ROOT = Path(__file__).resolve().parent
FIELDS = ['date', 'particulars', 'merchant', 'category', 'expense_amount',
          'income_amount', 'currency', 'account', 'subcategory', 'monthly_budget',
          'budget_period', 'payment_method']

# All limits are fictional USD amounts in integer cents. Every expense pair has
# a matching monthly budget; there are no overlapping parent-category limits.
LIMITS = {
    ('Housing', 'Rent'): 210000,
    ('Utilities', 'Electricity'): 14500,
    ('Utilities', 'Water'): 4500,
    ('Utilities', 'Natural gas'): 6500,
    ('Utilities', 'Internet'): 7500,
    ('Utilities', 'Mobile phone'): 11000,
    ('Food', 'Groceries'): 65000,
    ('Food', 'Dining out'): 22000,
    ('Food', 'Coffee'): 4000,
    ('Transportation', 'Fuel'): 17000,
    ('Transportation', 'Public transit'): 7500,
    ('Transportation', 'Auto insurance'): 13000,
    ('Transportation', 'Maintenance'): 8500,
    ('Household', 'Supplies'): 9000,
    ('Household', 'Furniture'): 8000,
    ('Health', 'Pharmacy'): 3500,
    ('Health', 'Medical visits'): 8000,
    ('Health', 'Fitness'): 4500,
    ('Family', 'Childcare'): 48000,
    ('Family', 'School supplies'): 6000,
    ('Personal', 'Clothing'): 10000,
    ('Personal', 'Personal care'): 6500,
    ('Entertainment', 'Streaming'): 4000,
    ('Entertainment', 'Activities'): 10000,
    ('Giving', 'Charity'): 6000,
    ('Giving', 'Gifts'): 9000,
    ('Travel', 'Trips'): 25000,
}


def money(cents):
    sign = '-' if cents < 0 else ''
    return f'{sign}{abs(cents) // 100}.{abs(cents) % 100:02}'


def generate():
    transactions, budgets = [], []
    for index in range(12):
        # A complete year ending in October 2026, useful for the current demo.
        serial = 2025 * 12 + 10 + index
        year, month0 = divmod(serial, 12)
        month = month0 + 1
        period = f'{year}-{month:02}'

        def add(day, kind, value, category, subcategory, particulars, merchant,
                method='Demo debit'):
            row = dict.fromkeys(FIELDS, '')
            row.update(date=f'{period}-{min(day, calendar.monthrange(year, month)[1]):02}',
                       particulars='Fictional demo: ' + particulars, merchant=merchant,
                       category=category, subcategory=subcategory,
                       currency='USD', account='Demo household checking',
                       payment_method=method)
            row['income_amount' if kind == 'income' else 'expense_amount'] = money(value)
            transactions.append(row)

        def expense(day, value, category, subcategory, particulars, merchant):
            add(day, 'expense', value, category, subcategory, particulars, merchant)

        def varied(base, step, offset=0):
            return base + (((index + offset) % 5) - 2) * step

        for day in (1, 15):
            add(day, 'income', 225000, 'Employment', 'Salary',
                'Alex net paycheck', 'Example Studio Employer', 'Demo direct deposit')
        for day in (7, 21):
            add(day, 'income', 167500, 'Employment', 'Salary',
                'Jordan net paycheck', 'Example Learning Employer', 'Demo direct deposit')
        add(24, 'income', 20000 + index % 4 * 7500, 'Other income', 'Freelance',
            'Weekend design project', 'Example Freelance Client', 'Demo transfer')
        add(28, 'income', 850 + index * 35, 'Other income', 'Interest',
            'Interest received', 'Example Demo Bank', 'Demo bank credit')
        if month in (3, 6, 9, 12):
            add(20, 'income', 45000, 'Employment', 'Bonus',
                'Quarterly performance bonus', 'Example Studio Employer', 'Demo direct deposit')
        if month == 4:
            add(17, 'income', 68000, 'Other income', 'Refund',
                'Annual refund received', 'Fictional Refund Source', 'Demo transfer')

        expense(1, 210000, 'Housing', 'Rent', 'Monthly apartment rent', 'Example Demo Apartments')
        expense(3, 7500, 'Utilities', 'Internet', 'Home internet', 'Example Demo Broadband')
        expense(5, 11000, 'Utilities', 'Mobile phone', 'Household mobile plan', 'Example Demo Wireless')
        expense(9, 3900 + index % 4 * 425, 'Utilities', 'Water', 'Water bill', 'Example Demo Water')
        electric = 11500 + (6500 if month in (6, 7, 8) else 0) + index % 3 * 825
        expense(11, electric, 'Utilities', 'Electricity', 'Electricity bill', 'Example Demo Energy')
        expense(12, 9500 if month in (11, 12, 1, 2) else 3500, 'Utilities', 'Natural gas',
                'Natural gas bill', 'Example Demo Energy')
        for week, day in enumerate((4, 11, 18, 25)):
            expense(day, varied(15500, 1150, week), 'Food', 'Groceries',
                    f'Weekly groceries, shop {week + 1}', 'Maple Demo Market')
        for offset, day in enumerate((8, 22)):
            expense(day, varied(10200, 1550, offset), 'Food', 'Dining out',
                    'Family dinner', 'Juniper Demo Kitchen')
            expense(day + 1, varied(1850, 175, offset), 'Food', 'Coffee',
                    'Coffee and snacks', 'Oak Demo Cafe')
        for offset, day in enumerate((6, 20)):
            expense(day, varied(7800, 525, offset), 'Transportation', 'Fuel',
                    'Fuel fill-up', 'Example Demo Fuel')
        expense(2, 7200, 'Transportation', 'Public transit', 'Monthly transit pass', 'Example Demo Transit')
        expense(13, 12800, 'Transportation', 'Auto insurance', 'Auto insurance payment', 'Example Demo Insurance')
        if month in (1, 4, 7, 10):
            expense(16, 24000 + index % 3 * 8500, 'Transportation', 'Maintenance',
                    'Vehicle service', 'Cedar Demo Garage')
        expense(14, varied(8500, 700), 'Household', 'Supplies', 'Cleaning and household supplies', 'Harbor Demo Supplies')
        if month in (2, 6, 10):
            expense(19, 18500 + index % 3 * 7000, 'Household', 'Furniture', 'Home furnishing purchase', 'Example Demo Home')
        expense(5, varied(2800, 200), 'Health', 'Pharmacy', 'Pharmacy essentials', 'Example Demo Pharmacy')
        expense(17, 6500 if index % 3 else 11500, 'Health', 'Medical visits', 'Routine visit copay', 'Example Demo Clinic')
        expense(1, 4500, 'Health', 'Fitness', 'Monthly fitness membership', 'Example Demo Fitness')
        expense(2, 48000, 'Family', 'Childcare', 'After-school care', 'Example Demo Learning Club')
        expense(18, 14800 if month == 8 else varied(3600, 400), 'Family', 'School supplies',
                'School supplies', 'Example Demo School Store')
        expense(23, 22000 if month == 11 else varied(8800, 1000), 'Personal', 'Clothing',
                'Seasonal clothing', 'Example Demo Outfitters')
        expense(15, varied(5900, 450), 'Personal', 'Personal care', 'Haircut and personal care', 'Example Demo Care')
        expense(10, 1999, 'Entertainment', 'Streaming', 'Video subscription', 'Example Demo Video')
        expense(10, 1099, 'Entertainment', 'Streaming', 'Music subscription', 'Example Demo Music')
        expense(26, varied(9200, 1200), 'Entertainment', 'Activities', 'Family activity', 'Example Demo Recreation')
        expense(27, 6000, 'Giving', 'Charity', 'Community donation', 'Example Demo Community Fund')
        expense(24, 28500 if month == 12 else varied(6500, 900), 'Giving', 'Gifts', 'Gifts for family', 'Example Demo Gifts')
        if month in (7, 12):
            expense(14, 185000 if month == 7 else 110000, 'Travel', 'Trips',
                    'Fictional family trip lodging and transport', 'Example Demo Travel')
        if month in (2, 5, 8, 10):
            expense(27, -3200, 'Personal', 'Clothing', 'Clothing return refund', 'Example Demo Outfitters')

        for (category, subcategory), limit in LIMITS.items():
            budgets.append({'period': period, 'category': category,
                            'subcategory': subcategory, 'amount': money(limit), 'currency': 'USD'})

    transactions.sort(key=lambda row: (row['date'], row['category'], row['subcategory'], row['particulars']))
    for filename, rows, fields in [
        ('us_household_transactions.csv', transactions, FIELDS),
        ('us_household_budgets.csv', budgets, ['period', 'category', 'subcategory', 'amount', 'currency']),
    ]:
        with (ROOT / filename).open('w', encoding='utf-8', newline='') as handle:
            writer = csv.DictWriter(handle, fieldnames=fields)
            writer.writeheader()
            writer.writerows(rows)
    return transactions, budgets


if __name__ == '__main__':
    rows, limits = generate()
    print(f'Generated {len(rows)} fictional transactions and {len(limits)} budgets (USD).')
