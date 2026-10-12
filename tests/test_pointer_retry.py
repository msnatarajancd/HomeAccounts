"""Transient Windows sharing failures must not expose partial account states."""
import errno
import tempfile
import unittest
from pathlib import Path
from unittest.mock import call, patch

from core import Store, valid_budget, valid_tx
import core


class PointerRetryTests(unittest.TestCase):
    def setUp(self):
        self.folder = tempfile.TemporaryDirectory()
        self.store = Store(self.folder.name)
        self.row = valid_tx({'date': '2026-10-11', 'type': 'expense', 'amount': '10',
                            'currency': 'USD', 'account': 'Fictional', 'category': 'Household'})
        self.budget = valid_budget({'period': '2026-10', 'amount': '100', 'currency': 'USD',
                                   'category': 'Household'})
        self.first = self.store.commit([self.row], [self.budget], '', 'fictional first revision')
        self.original = self.store.load()
        self.updated_row = {**self.row, 'amount': '20'}
        self.updated_budget = {**self.budget, 'amount': '200'}
        self.store.commit([self.updated_row], [self.updated_budget], self.first, 'fictional second revision')

    def tearDown(self):
        self.folder.cleanup()

    def windows_error(self, code):
        failure = PermissionError(errno.EACCES, 'Simulated Windows sharing failure')
        failure.winerror = code
        return failure

    def assert_no_temporary_pointer_or_lock(self):
        self.assertEqual(list(Path(self.folder.name).glob('*.tmp')), [])
        self.assertFalse((Path(self.folder.name) / 'write.lock').exists())

    def test_undo_retries_windows_sharing_errors_then_atomically_restores_prior_state(self):
        real_replace = core.os.replace
        for code in (5, 32, 33):
            with self.subTest(winerror=code):
                before = self.store.load()
                attempts = []
                def temporarily_blocked(source, destination):
                    attempts.append((source, destination))
                    self.assertEqual(self.store.load(), before)
                    if len(attempts) <= 3: raise self.windows_error(code)
                    return real_replace(source, destination)
                with patch('core.os.replace', side_effect=temporarily_blocked) as replace, patch('core.time.sleep') as sleep:
                    self.store.undo(before['revision'])
                self.assertEqual(replace.call_count, 4)
                self.assertEqual(sleep.call_args_list, [call(.02), call(.04), call(.08)])
                self.assertEqual(self.store.load(), self.original)
                self.assert_no_temporary_pointer_or_lock()
                self.store.commit([self.updated_row], [self.updated_budget], self.first, 'fictional second revision')

    def test_terminal_windows_failure_keeps_old_pointer_and_both_csvs(self):
        before = self.store.load()
        pointer = Path(self.folder.name) / 'current.json'
        old_bytes = pointer.read_bytes()
        with patch('core.os.replace', side_effect=self.windows_error(5)) as replace, patch('core.time.sleep') as sleep:
            with self.assertRaises(PermissionError):
                self.store.commit([self.row], [], before['revision'], 'fictional failed revision')
        self.assertEqual(replace.call_count, 6)
        self.assertEqual(sleep.call_args_list, [call(.02), call(.04), call(.08), call(.16), call(.32)])
        self.assertEqual(pointer.read_bytes(), old_bytes)
        self.assertEqual(self.store.load(), before)
        self.assert_no_temporary_pointer_or_lock()

    def test_non_windows_or_unrelated_permission_error_is_not_retried(self):
        for failure in (PermissionError(errno.EACCES, 'Simulated POSIX permission denial'), self.windows_error(87)):
            with self.subTest(failure=failure):
                before = self.store.load()
                with patch('core.os.replace', side_effect=failure) as replace, patch('core.time.sleep') as sleep:
                    with self.assertRaises(PermissionError): self.store.undo(before['revision'])
                replace.assert_called_once()
                sleep.assert_not_called()
                self.assertEqual(self.store.load(), before)
                self.assert_no_temporary_pointer_or_lock()


if __name__ == '__main__':
    unittest.main()
