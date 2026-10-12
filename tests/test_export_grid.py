"""The exported transaction CSV follows the visible grid, using fictional data."""
import csv
import io
import json
from pathlib import Path
import tempfile
import threading
import unittest
import urllib.error
import urllib.parse
import urllib.request

from core import valid_tx, TX_FIELDS
from local_api import make_server
from schema import save_schema, suggested_schema


class ExportGridTests(unittest.TestCase):
    def setUp(self):
        self.folder = tempfile.TemporaryDirectory()
        self.server = make_server(0, self.folder.name, False)
        self.api = self.server.service
        fields, _ = suggested_schema(['date', 'type', 'amount', 'currency', 'category', 'subcategory', 'payment', 'score', 'hidden'])
        for field in fields:
            if field['key'] == 'custom_score': field['type'] = 'Number'
            if field['key'] == 'custom_hidden': field['included'] = False
        save_schema(self.api.store, fields, 'USD')
        self.rows = [self.row('a', '2026-10-02', '100', '10', 'Debit'),
                     self.row('b', '2026-10-03', '20', '2', 'debit'),
                     self.row('c', '2026-10-01', '3', '', 'Cash'),
                     self.row('d', '2026-09-01', '5', 'NaN', 'Debit'),
                     self.row('e', '2026-10-04', '200', '100', 'Debit', currency='EUR'),
                     self.row('f', '2026-10-05', '30', '7', 'Debit', type='income')]
        self.api.store.commit(self.rows, [], '', 'fictional export fixture')
        self.before = self.api.store.load()
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start()
        self.url = f'http://127.0.0.1:{self.server.server_port}'

    def tearDown(self):
        self.server.shutdown()
        self.server.server_close()
        self.thread.join()
        self.folder.cleanup()

    def row(self, id, date, amount, score, payment, **values):
        return valid_tx({'id': id, 'date': date, 'amount': amount, 'type': 'expense', 'currency': 'USD',
            'description': 'Fictional market, household', 'category': 'Household', 'subcategory': 'Supplies',
            'account': 'Demo checking', 'custom_fields': json.dumps({'custom_payment': payment, 'custom_score': score,
                                                                   'custom_hidden': 'not selectable'}), **values})

    def export(self, **query):
        with urllib.request.urlopen(self.url + '/api/export?' + urllib.parse.urlencode(query)) as response:
            self.assertEqual(response.headers['Content-Type'], 'text/csv; charset=utf-8')
            raw = response.read()
        self.assertTrue(raw.startswith(b'\xef\xbb\xbf'))
        reader = csv.DictReader(io.StringIO(raw.decode('utf-8-sig')))
        self.assertEqual(reader.fieldnames, TX_FIELDS)
        return list(reader)

    def test_combined_column_and_scope_filters_export_the_same_subset_in_numeric_order(self):
        rows = self.export(currency='USD', month='2026-10', category='Household', type='expense', search='FICTIONAL',
            column_description=' MARKET, ', column_category=' HOUSE ', column_subcategory=' SUPP ',
            column_currency=' usd ', column_account=' checking ', column_type=' EXP ',
            column_date=' 2026-10 ', column_amount=' 0 ', column_custom_payment=' DEBIT ', sort='amount', sort_dir='asc')
        self.assertEqual([row['id'] for row in rows], ['b', 'a'])
        self.assertEqual(rows[0]['description'], self.rows[1]['description'])
        self.assertEqual(json.loads(rows[0]['custom_fields'])['custom_payment'], 'debit')
        self.assertEqual(self.api.store.load(), self.before)

    def test_default_date_order_and_custom_number_order_put_missing_legacy_values_last(self):
        rows = self.export(currency='USD', type='expense')
        self.assertEqual([row['id'] for row in rows], ['b', 'a', 'c', 'd'])
        ascending = self.export(currency='USD', type='expense', sort='custom_score', sort_dir='asc')
        descending = self.export(currency='USD', type='expense', sort='custom_score', sort_dir='desc')
        self.assertEqual([row['id'] for row in ascending[:2]], ['b', 'a'])
        self.assertEqual([row['id'] for row in descending[:2]], ['a', 'b'])
        self.assertEqual({row['id'] for row in ascending[2:]}, {'c', 'd'})
        self.assertEqual({row['id'] for row in descending[2:]}, {'c', 'd'})
        text = self.export(currency='USD', type='expense', sort='custom_payment', sort_dir='asc')
        self.assertEqual(text[0]['id'], 'c')

    def test_unsupported_columns_and_sort_values_return_clear_errors(self):
        for query in ({'column_missing': 'x'}, {'column_custom_hidden': 'x'}, {'sort': 'custom_hidden'},
                      {'sort': 'id'}, {'sort_dir': 'random'}):
            with self.subTest(query=query), self.assertRaises(urllib.error.HTTPError) as raised:
                urllib.request.urlopen(self.url + '/api/export?' + urllib.parse.urlencode(query))
            self.assertEqual(raised.exception.code, 400)
            self.assertIn('export', json.load(raised.exception)['error'].lower())
        self.assertEqual(len(self.export(unrelated='ignored')), len(self.rows))
        self.assertEqual(self.api.store.load(), self.before)

    def test_us_sample_downloads_are_allowlisted_and_path_traversal_is_rejected(self):
        for name in ('us_household_transactions.csv', 'us_household_budgets.csv'):
            with urllib.request.urlopen(self.url + '/samples/' + name) as response:
                self.assertIn('text/csv', response.headers['Content-Type'])
                rows = list(csv.DictReader(io.StringIO(response.read().decode('utf-8-sig'))))
                self.assertTrue(rows)
                self.assertEqual({row['currency'] for row in rows}, {'USD'})
        with self.assertRaises(urllib.error.HTTPError) as raised:
            urllib.request.urlopen(self.url + '/samples/../local_api.py')
        self.assertEqual(raised.exception.code, 404)


if __name__ == '__main__':
    unittest.main()
