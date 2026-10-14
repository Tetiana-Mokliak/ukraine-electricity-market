import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
from urllib.error import HTTPError
from scripts.collect_nerc import select_latest, accept_payload, download
from test_updates import row

BASE = 'https://www.nerc.gov.ua/files/'
def link(date, suffix=''):
    return f'<a href="{BASE}Open_Data_During_the_War_{date}{suffix}.xlsx">data</a>'

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
            reader = lambda data, date: [row()]
            self.assertEqual(accept_payload(folder, 'url', '2026-09-01', b'a', reader)['status'], 'updated')
            with patch('scripts.collect_nerc.read_workbook', side_effect=AssertionError):
                self.assertEqual(accept_payload(folder, 'url', '2026-09-01', b'a', reader)['status'], 'unchanged')
            self.assertEqual(accept_payload(folder, 'url', '2026-09-01', b'b', reader)['status'], 'file_only_change')
    def test_partial_and_corrupt_keep_pointer(self):
        with tempfile.TemporaryDirectory() as folder:
            accept_payload(folder, 'url', '2026-09-01', b'a', lambda *_: [row()])
            p = Path(folder) / 'current.json'; before = p.read_bytes()
            with self.assertRaises(ValueError):
                accept_payload(folder, 'url', '2026-10-01', b'b', lambda *_: [row('Лютий')])
            self.assertEqual(p.read_bytes(), before)
            def broken(*_): raise ValueError('Corrupt workbook')
            with self.assertRaises(ValueError): accept_payload(folder, 'url', '2026-10-01', b'c', broken)
            self.assertEqual(p.read_bytes(), before)
    def test_write_failure_keeps_pointer(self):
        with tempfile.TemporaryDirectory() as folder:
            accept_payload(folder, 'url', '2026-09-01', b'a', lambda *_: [row()])
            p = Path(folder) / 'current.json'; before = p.read_bytes()
            with patch('scripts.collect_nerc.os.replace', side_effect=OSError('disk failure')):
                with self.assertRaises(OSError):
                    accept_payload(folder, 'url', '2026-10-01', b'b', lambda *_: [row(value=12)])
            self.assertEqual(p.read_bytes(), before)
    def test_old_version_rejected(self):
        with tempfile.TemporaryDirectory() as folder:
            accept_payload(folder, 'url', '2026-10-01', b'a', lambda *_: [row()])
            with self.assertRaisesRegex(ValueError, 'older'):
                accept_payload(folder, 'url', '2026-09-01', b'b', lambda *_: [row()])
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
