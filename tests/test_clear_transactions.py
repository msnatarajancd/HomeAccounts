import unittest
import tempfile
from pathlib import Path

from core import valid_tx, valid_budget
from local_api import Service


class ClearTransactionsTests(unittest.TestCase):
    def setUp(self):
        self.folder = tempfile.TemporaryDirectory()
        self.api = Service(Path(self.folder.name) / 'records', backup=False)
        self.rows = [valid_tx({'date': date, 'type': kind, 'amount': value,
                              'currency': currency, 'account': 'Fictional',
                              'category': 'Household', 'source_ref': f'fictional:{index}'})
                     for index, (date, kind, value, currency) in enumerate([
                         ('2026-09-01', 'expense', '20', 'EUR'),
                         ('2026-10-01', 'income', '100', 'INR'),
                         ('2026-10-02', 'transfer', '5', 'EUR')])]
        self.budgets = [valid_budget({'period': '2026-10', 'amount': '50',
                                     'currency': 'EUR', 'category': 'Household'})]
        self.api.store.commit(self.rows, self.budgets, '', 'fictional fixture')

    def tearDown(self):
        self.folder.cleanup()

    def review(self):
        return self.api.dispatch('/api/transactions/clear/review', {})

    def test_clear_requires_review_and_acknowledgement_and_preserves_settings(self):
        before = self.api.store.load()
        settings = self.api.settings_path.read_bytes()
        review = self.review()
        self.assertEqual(review['proposal']['clear_count'], 3)
        self.assertEqual(review['proposal']['before'], self.rows)
        self.assertEqual(self.api.store.load(), before)
        for value in (None, False, 'true', 1):
            with self.subTest(value=value), self.assertRaisesRegex(ValueError, 'Acknowledge'):
                self.api.confirm({'token': review['token'], 'confirm_clear': value})
        self.api.confirm({'token': review['token'], 'confirm_clear': True, 'rows': self.rows})
        after = self.api.store.load()
        self.assertEqual(after['transactions'], [])
        self.assertEqual(after['budgets'], self.budgets)
        self.assertEqual(after['imported_refs'], [])
        self.assertEqual(self.api.settings_path.read_bytes(), settings)
        self.assertEqual(after['history'], before['history'] + [before['revision']])
        self.api.store.undo(after['revision'])
        self.assertEqual(self.api.store.load(), before)

    def test_stale_clear_and_empty_clear_are_rejected(self):
        review = self.review()
        before = self.api.store.load()
        self.api.store.commit(self.rows, self.budgets, before['revision'], 'another save')
        with self.assertRaisesRegex(ValueError, 'changed'):
            self.api.confirm({'token': review['token'], 'confirm_clear': True})
        self.assertEqual(self.api.store.load()['transactions'], self.rows)
        current = self.review()
        self.api.confirm({'token': current['token'], 'confirm_clear': True})
        with self.assertRaisesRegex(ValueError, 'no transactions'):
            self.review()

    def test_clear_allows_reimport_and_undo_restores_import_tracking(self):
        file = self.api.dispatch('/api/demo', {})
        body = {'file_token': file['file_token'], 'selected': ['CSV'], 'currency': 'EUR',
                'mapping': {'date': 'date', 'description': 'particulars', 'merchant': 'merchant',
                            'category': 'category', 'subcategory': 'subcategory',
                            'expense': 'expense_amount', 'income': 'income_amount',
                            'currency': 'currency', 'account': 'account'}}
        imported = self.api.import_preview(body)
        self.api.confirm({'token': imported['review']['token'], 'accept_categories': True})
        self.assertEqual(self.api.import_preview(body)['transactions'], [])
        before = self.api.store.load()
        review = self.review()
        self.api.confirm({'token': review['token'], 'confirm_clear': True})
        self.assertEqual(len(self.api.import_preview(body)['transactions']), 12)
        self.api.store.undo(self.api.store.load()['revision'])
        self.assertEqual(self.api.store.load(), before)
        self.assertEqual(self.api.import_preview(body)['transactions'], [])


if __name__ == '__main__':
    unittest.main()
