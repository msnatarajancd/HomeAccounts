"""The public US demo exercises the same reviewed importer as a user file."""
import tempfile
import unittest
from pathlib import Path

from core import income, spending, total_budget
from local_api import Service


class USDemoTests(unittest.TestCase):
    def test_demo_import_is_reviewed_consistent_and_repeat_safe(self):
        with tempfile.TemporaryDirectory() as folder:
            api = Service(Path(folder) / 'fictional', backup=False)
            tx_file = api.dispatch('/api/demo', {'filename': 'us_household_transactions.csv'})
            tx_body = {'file_token': tx_file['file_token'], 'selected': ['CSV'], 'currency': 'USD',
                       'mapping': {'date': 'date', 'description': 'particulars', 'merchant': 'merchant',
                                   'category': 'category', 'subcategory': 'subcategory',
                                   'expense': 'expense_amount', 'income': 'income_amount',
                                   'currency': 'currency', 'account': 'account'}}
            preview = api.import_preview(tx_body)
            self.assertEqual(preview['issues'], [])
            self.assertEqual(preview['conflicts'], [])
            self.assertEqual(len(preview['transactions']), 462)
            self.assertEqual(api.store.load()['transactions'], [])
            api.confirm({'token': preview['review']['token'], 'accept_categories': True})

            budget_file = api.dispatch('/api/demo', {'filename': 'us_household_budgets.csv'})
            limits = api.import_preview({'file_token': budget_file['file_token'], 'selected': ['CSV'],
                'currency': 'USD', 'kind': 'Budgets', 'mapping': {'period': 'period', 'budget': 'amount',
                'category': 'category', 'subcategory': 'subcategory', 'currency': 'currency'}})
            self.assertEqual(limits['issues'], [])
            self.assertEqual(limits['conflicts'], [])
            self.assertEqual(len(limits['budgets']), 324)
            # Expense pairs imported first already belong to the shared catalog.
            self.assertEqual(limits['review']['category_additions'], [])
            api.confirm({'token': limits['review']['token']})
            saved = api.store.load()
            transactions, budgets = saved['transactions'], saved['budgets']
            pairs = {(b['period'], b['category'], b['subcategory']) for b in budgets}
            self.assertTrue(all((t['date'][:7], t['category'], t['subcategory']) in pairs
                                for t in transactions if t['type'] == 'expense'))
            self.assertEqual({t['currency'] for t in transactions}, {'USD'})
            self.assertEqual(len({t['date'][:7] for t in transactions}), 12)
            self.assertEqual(sum(t['amount'].startswith('-') for t in transactions), 4)
            self.assertEqual(income(transactions, '2026-10', 'USD'), 828735)
            self.assertEqual(spending(transactions, '2026-10', 'USD'), 550923)
            self.assertEqual(total_budget(budgets, '2026-10', 'USD'), 548500)
            self.assertGreater(total_budget(budgets, '2025-11', 'USD'), spending(transactions, '2025-11', 'USD'))
            self.assertGreater(spending(transactions, '2026-07', 'USD'), total_budget(budgets, '2026-07', 'USD'))
            repeated = api.import_preview(tx_body)
            self.assertEqual(repeated['transactions'], [])
            self.assertEqual(repeated['repeated'], 462)


if __name__ == '__main__':
    unittest.main()
