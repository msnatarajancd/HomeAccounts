"""Catalog integrity uses only temporary fictional records; no provider calls."""
import base64
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from categories import STARTER, catalog, key
from core import valid_tx, valid_budget
from local_api import Service
from schema import suggested_schema


class SharedCatalogTests(unittest.TestCase):
    def setUp(self):
        self.folder = tempfile.TemporaryDirectory()
        self.api = Service(Path(self.folder.name) / 'fictional', backup=False)
        self.fields, _ = suggested_schema(['date', 'type', 'amount', 'currency', 'category', 'subcategory'])
        self.setup(STARTER)

    def tearDown(self):
        self.folder.cleanup()

    def setup(self, taxonomy):
        self.api.dispatch('/api/setup', {'fields': self.fields, 'currency': 'EUR', 'taxonomy': taxonomy})

    def row(self, **values):
        return {'date': '2026-10-11', 'type': 'expense', 'amount': '12', 'currency': 'EUR',
                'category': 'Food', 'subcategory': 'Groceries', 'account': 'Fictional', **values}

    def review(self, **values):
        return self.api.dispatch('/api/proposal', {'kind': 'add', 'rows': [self.row(**values)]})

    def confirm(self, review, **values):
        return self.api.confirm({'token': review['token'], **values})

    def test_catalog_union_is_read_only_and_shared_with_budget_only_pairs(self):
        old = valid_tx(self.row(category='Legacy food', subcategory='Frozen'))
        budget = valid_budget({'period': '2026-10', 'amount': '100', 'currency': 'EUR',
                               'category': 'Travel', 'subcategory': 'Flights'})
        self.api.store.commit([old], [budget], '', 'fictional legacy records')
        before = {p: p.read_bytes() for p in self.api.store.path.rglob('*') if p.is_file()}
        choices = self.api.state()['category_catalog']
        self.assertIn(('expense', 'Legacy food', 'Frozen'), {key(r) for r in choices})
        self.assertIn(('expense', 'Travel', 'Flights'), {key(r) for r in choices})
        self.assertIn(('expense', 'Travel', ''), {key(r) for r in choices})
        self.assertEqual(before, {p: p.read_bytes() for p in before})
        self.assertEqual(self.review(category='Travel', subcategory='Flights')['category_additions'], [])
        review = self.api.dispatch('/api/proposal', {'kind': 'budget', 'rows': [
            {'period': '2026-11', 'amount': '20', 'currency': 'EUR', 'category': 'Legacy food', 'subcategory': 'Frozen'}]})
        self.assertEqual(review['category_additions'], [])

    def test_unknown_pair_requires_literal_ack_and_preserves_exact_identity(self):
        review = self.review(category='Pets', subcategory='Veterinary')
        self.assertEqual(review['category_additions'], [{'type': 'expense', 'category': 'Pets', 'subcategory': 'Veterinary'}])
        self.assertEqual(self.api.store.load()['transactions'], [])
        for value in (None, False, 'true', 1):
            with self.subTest(value=value), self.assertRaisesRegex(ValueError, 'acknowledge'):
                self.confirm(review, accept_categories=value)
        self.confirm(review, accept_categories=True, rows=[self.row(category='Ignored')])
        self.assertIn(('expense', 'Pets', 'Veterinary'), {key(r) for r in self.api.state()['category_catalog']})
        self.assertEqual(self.review(category='Pets', subcategory='Veterinary')['category_additions'], [])

    def test_wrong_parent_wrong_type_and_case_variants_are_not_silently_accepted(self):
        with self.assertRaisesRegex(ValueError, 'belongs to Food'):
            self.review(category='Housing', subcategory='Groceries')
        with self.assertRaisesRegex(ValueError, 'spelling'):
            self.review(category='food', subcategory='Fresh')
        with self.assertRaisesRegex(ValueError, 'spelling'):
            self.review(subcategory='groceries')
        # A category on an income transaction does not become an expense choice.
        review = self.review(category='Employment', subcategory='Salary')
        self.assertEqual(review['category_additions'][0]['type'], 'expense')
        with self.assertRaisesRegex(ValueError, 'acknowledge'):
            self.confirm(review)

    def test_corrections_recompute_additions_and_cannot_cross_parent(self):
        review = self.review()
        with self.assertRaisesRegex(ValueError, 'belongs to Food'):
            self.api.correct({'token': review['token'], 'rows': [{'category': 'Housing'}]})
        corrected = self.api.correct({'token': review['token'], 'rows': [{'category': 'Pets', 'subcategory': 'Food'}]})
        self.assertEqual(corrected['category_additions'][0]['category'], 'Pets')
        with self.assertRaisesRegex(ValueError, 'acknowledge'):
            self.confirm(corrected)
        with self.assertRaisesRegex(ValueError, 'expired'):
            self.confirm(review)

    def test_archived_pair_can_be_edited_unchanged_but_not_added(self):
        review = self.review()
        self.confirm(review)
        saved = self.api.store.load()['transactions'][0]
        self.setup([{**r, 'active': False} if key(r) == ('expense', 'Food', 'Groceries') else r for r in STARTER])
        with self.assertRaisesRegex(ValueError, 'archived'):
            self.review()
        edit = self.api.dispatch('/api/proposal', {'kind': 'edit', 'id': saved['id'], 'rows': [{'amount': '15'}]})
        self.confirm(edit)
        self.assertEqual(self.api.store.load()['transactions'][0]['subcategory'], 'Groceries')

    def test_category_definition_change_invalidates_pending_confirmation(self):
        review = self.review()
        self.setup([r for r in STARTER if key(r) != ('expense', 'Housing', 'Rent')])
        with self.assertRaisesRegex(ValueError, 'choices changed'):
            self.confirm(review)
        self.assertEqual(self.api.store.load()['transactions'], [])

    def test_import_preserves_custom_parent_pair_but_requires_acknowledgement(self):
        raw = b'date,amount,category,subcategory\n2026-10-11,13,Legacy household,Groceries\n'
        uploaded = self.api.upload({'filename': 'fictional.csv', 'data': base64.b64encode(raw).decode()})
        result = self.api.import_preview({'file_token': uploaded['file_token'], 'selected': ['CSV'], 'currency': 'EUR',
            'mapping': {'date': 'date', 'expense': 'amount', 'category': 'category', 'subcategory': 'subcategory'}})
        review = result['review']
        self.assertEqual(review['category_additions'][0]['category'], 'Legacy household')
        with self.assertRaisesRegex(ValueError, 'acknowledge'):
            self.confirm(review)
        self.confirm(review, accept_categories=True)
        row = self.api.store.load()['transactions'][0]
        self.assertEqual((row['category'], row['subcategory']), ('Legacy household', 'Groceries'))
        self.assertEqual(self.review(category='Legacy household')['category_additions'], [])

    def test_clear_keeps_confirmed_choices_and_undo_restores_prior_catalog(self):
        first = self.review()
        self.confirm(first)
        original = self.api.store.load()
        added = self.review(category='Pets', subcategory='Veterinary')
        self.confirm(added, accept_categories=True)
        before_clear = self.api.state()['category_catalog']
        clear = self.api.dispatch('/api/transactions/clear/review', {})
        self.confirm(clear, confirm_clear=True)
        self.assertEqual(self.api.state()['category_catalog'], before_clear)
        self.api.store.undo(self.api.store.load()['revision'])
        self.api.store.undo(self.api.store.load()['revision'])
        self.assertEqual(self.api.store.load(), original)
        self.assertNotIn(('expense', 'Pets', 'Veterinary'), {key(r) for r in self.api.state()['category_catalog']})

    def test_live_voice_route_forwards_only_allowlisted_context_without_records(self):
        with patch('local_api.live_voice.create_session', return_value={'sdp': 'fictional answer'}) as create:
            result = self.api.dispatch('/api/voice/session', {'sdp': 'fictional offer', 'live_consent': True,
                'provider_endpoint': 'fixture endpoint', 'context': {'page': '/overview', 'records': [self.row()]}})
            self.assertEqual(result, {'sdp': 'fictional answer'})
            create.assert_called_once_with('fictional offer', enabled=True, provider_endpoint='fixture endpoint', page='/overview', scope={})


if __name__ == '__main__':
    unittest.main()
