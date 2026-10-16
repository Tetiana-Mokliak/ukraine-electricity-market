import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
from urllib.error import HTTPError
from scripts.collect_nerc import select_latest, accept_payload, download, check_trade_totals
from test_updates import row

BASE = 'https://www.nerc.gov.ua/files/'
def link(date, suffix=''):
    return f'<a href="{BASE}Open_Data_During_the_War_{date}{suffix}.xlsx">data</a>'

def trade_fixture(month='Січень', value=10):
    return [row(month, value), row(month, value, Категорія='Словаччина')]

class Collector(unittest.TestCase):
    def test_latest_not_page_order(self):
        html = link('01.10.2026') + link('01.09.2026')
        self.assertEqual(select_latest(html)[1], '2026-10-01')
    def test_duplicate_links_ok(self):
        self.assertEqual(select_latest(link('01.09.2026') * 2)[1], '2026-09-01')
    def test_ambiguous_latest(self):
        with self.assertRaisesRegex(ValueError, 'Multiple'):
            select_latest(link('01.09.2026') + link('01.09.2026', '_copy'))
    def test_unknown_date_and_no_links(self):
        for html in [link('latest'), '', link('31.02.2026')]:
            with self.assertRaises(ValueError): select_latest(html)
    def test_other_domain_ignored(self):
        with self.assertRaises(ValueError): select_latest(link('01.09.2026').replace('www.nerc.gov.ua', 'example.com'))
    def test_hash_shortcut_and_format_change(self):
        with tempfile.TemporaryDirectory() as folder:
            reader = lambda data, date: trade_fixture()
            self.assertEqual(accept_payload(folder, 'url', '2026-09-01', b'a', reader)['status'], 'updated')
            with patch('scripts.collect_nerc.read_workbook', side_effect=AssertionError):
                self.assertEqual(accept_payload(folder, 'url', '2026-09-01', b'a', reader)['status'], 'unchanged')
            self.assertEqual(accept_payload(folder, 'url', '2026-09-01', b'b', reader)['status'], 'file_only_change')
    def test_identical_content_at_new_url_creates_no_files_and_skips_reader(self):
        with tempfile.TemporaryDirectory() as folder:
            accept_payload(folder, 'url', '2026-09-01', b'a', lambda *_: trade_fixture())
            before = {str(p.relative_to(folder)): p.read_bytes() for p in Path(folder).rglob('*') if p.is_file()}
            def fail_reader(*_): raise AssertionError('Same content must not be reprocessed')
            result = accept_payload(folder, 'different-url', '2026-09-01', b'a', fail_reader)
            self.assertEqual(result['status'], 'unchanged')
            after = {str(p.relative_to(folder)): p.read_bytes() for p in Path(folder).rglob('*') if p.is_file()}
            self.assertEqual(before, after)
    def test_new_content_same_name_preserves_history_and_audits_revision(self):
        with tempfile.TemporaryDirectory() as folder:
            first = accept_payload(folder, 'same-url', '2026-09-01', b'a', lambda *_: trade_fixture())
            previous = Path(folder) / 'snapshots' / first['sha256'] / 'audit.json'
            original_audit = previous.read_bytes()
            result = accept_payload(folder, 'same-url', '2026-09-01', b'b', lambda *_: trade_fixture(value=12))
            self.assertEqual(result['status'], 'updated')
            self.assertEqual(len(result['revised']), 2)
            self.assertEqual(result['quality']['trade_groups_checked'], 1)
            self.assertEqual(original_audit, previous.read_bytes())
            self.assertEqual(len(list((Path(folder) / 'snapshots').iterdir())), 2)
    def test_return_to_archived_content_does_not_overwrite_old_audit(self):
        with tempfile.TemporaryDirectory() as folder:
            accept_payload(folder, 'url', '2026-09-01', b'a', lambda *_: trade_fixture())
            accept_payload(folder, 'url', '2026-09-01', b'b', lambda *_: trade_fixture(value=12))
            before = {str(p.relative_to(folder)): p.read_bytes() for p in Path(folder).rglob('*') if p.is_file()}
            with self.assertRaisesRegex(ValueError, 'Previously archived'):
                accept_payload(folder, 'url', '2026-09-01', b'a', lambda *_: trade_fixture())
            after = {str(p.relative_to(folder)): p.read_bytes() for p in Path(folder).rglob('*') if p.is_file()}
            self.assertEqual(before, after)
    def test_new_total_mismatch_keeps_current_pointer(self):
        with tempfile.TemporaryDirectory() as folder:
            accept_payload(folder, 'url', '2026-09-01', b'a', lambda *_: trade_fixture())
            pointer = Path(folder) / 'current.json'; before = pointer.read_bytes()
            broken = trade_fixture(); broken[-1]['Значення'] = 9.999
            with self.assertRaisesRegex(ValueError, 'reconcile exactly'):
                accept_payload(folder, 'url', '2026-09-01', b'b', lambda *_: broken)
            self.assertEqual(pointer.read_bytes(), before)
    def test_zero_total_without_country_rows_is_not_imputed(self):
        rows = [row(value=0, Показник='Експорт')]
        quality = check_trade_totals(rows)
        self.assertEqual(len(rows), 1)
        self.assertEqual(len(quality['export_coverage_warnings'][0]['missing_categories']), 5)
    def test_invalid_trade_unit_negative_or_missing_total_rejected(self):
        for rows in ([row(value=10, Категорія='Словаччина')],
                     [row(value=-1), row(value=-1, Категорія='Словаччина')],
                     [row(value=0, **{'Одиниці виміру': 'МВт×год'})]):
            with self.assertRaises(ValueError): check_trade_totals(rows)
    def test_partial_and_corrupt_keep_pointer(self):
        with tempfile.TemporaryDirectory() as folder:
            accept_payload(folder, 'url', '2026-09-01', b'a', lambda *_: trade_fixture())
            p = Path(folder) / 'current.json'; before = p.read_bytes()
            with self.assertRaises(ValueError):
                accept_payload(folder, 'url', '2026-10-01', b'b', lambda *_: trade_fixture('Лютий'))
            self.assertEqual(p.read_bytes(), before)
            def broken(*_): raise ValueError('Corrupt workbook')
            with self.assertRaises(ValueError): accept_payload(folder, 'url', '2026-10-01', b'c', broken)
            self.assertEqual(p.read_bytes(), before)
    def test_write_failure_keeps_pointer(self):
        with tempfile.TemporaryDirectory() as folder:
            accept_payload(folder, 'url', '2026-09-01', b'a', lambda *_: trade_fixture())
            p = Path(folder) / 'current.json'; before = p.read_bytes()
            with patch('scripts.collect_nerc.os.replace', side_effect=OSError('disk failure')):
                with self.assertRaises(OSError):
                    accept_payload(folder, 'url', '2026-10-01', b'b', lambda *_: trade_fixture(value=12))
            self.assertEqual(p.read_bytes(), before)
    def test_old_version_rejected(self):
        with tempfile.TemporaryDirectory() as folder:
            accept_payload(folder, 'url', '2026-10-01', b'a', lambda *_: trade_fixture())
            with self.assertRaisesRegex(ValueError, 'older'):
                accept_payload(folder, 'url', '2026-09-01', b'b', lambda *_: trade_fixture())
    def test_forbidden_not_retried(self):
        calls = []
        def opener(*a, **kw):
            calls.append(1); raise HTTPError('url', 403, 'Forbidden', {}, None)
        with self.assertRaises(HTTPError): download('url', opener, lambda _: None)
        self.assertEqual(len(calls), 1)
    def test_server_error_three_attempts(self):
        calls = []
        def opener(*a, **kw):
            calls.append(1); raise HTTPError('url', 503, 'Unavailable', {}, None)
        with self.assertRaises(HTTPError): download('url', opener, lambda _: None)
        self.assertEqual(len(calls), 3)

if __name__ == '__main__': unittest.main()
