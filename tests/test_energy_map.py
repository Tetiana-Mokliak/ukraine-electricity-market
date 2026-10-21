import json
from datetime import datetime, timezone
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
from scripts import collect_energy_map as em

CSV = b'date,hour,outage_use,outage_amount,number\n2026-06-30,00:00-01:00,no,,\n'


class EnergyMapTests(unittest.TestCase):
    def test_unchanged_preserves_snapshot_and_pending(self):
        with tempfile.TemporaryDirectory() as temporary:
            directory = Path(temporary)
            self.assertTrue(em.accept(CSV, directory, '2026-10-21T15:38:00+00:00'))
            snapshot = next((directory / 'raw').iterdir())
            mtime = snapshot.stat().st_mtime_ns
            self.assertFalse(em.accept(CSV, directory, '2026-11-05T08:37:00+00:00'))
            state = json.loads((directory / 'current.json').read_text())
            self.assertEqual(snapshot.stat().st_mtime_ns, mtime)
            self.assertEqual(state['data_end_date'], '2026-06-30')
            self.assertEqual(state['last_changed_at_utc'], '2026-10-21T15:38:00+00:00')
            self.assertTrue(state['preparation_pending'])

    def test_bad_payload_keeps_accepted_source(self):
        with tempfile.TemporaryDirectory() as temporary:
            directory = Path(temporary)
            em.accept(CSV, directory, '2026-10-21T15:38:00+00:00')
            before = (directory / 'current.json').read_bytes()
            with self.assertRaises(ValueError):
                em.accept(b'<html>login</html>', directory, '2026-11-05T08:37:00+00:00')
            self.assertEqual(before, (directory / 'current.json').read_bytes())

    def test_changed_archives_new_snapshot(self):
        with tempfile.TemporaryDirectory() as temporary:
            directory = Path(temporary)
            em.accept(CSV, directory, '2026-10-21T15:38:00+00:00')
            self.assertTrue(em.accept(CSV.replace(b'2026-06-30', b'2026-07-01'), directory, '2026-11-05T08:37:00+00:00'))
            self.assertEqual(len(list((directory / 'raw').iterdir())), 2)

    def test_month_guard_skips_without_network_or_token(self):
        with tempfile.TemporaryDirectory() as temporary:
            directory = Path(temporary)
            now = datetime.now(timezone.utc)
            em.accept(CSV, directory, now.isoformat())
            with patch('sys.argv', ['collector', '--data-dir', str(directory)]), patch.object(em, 'download') as fetch:
                em.main()
                fetch.assert_not_called()
            self.assertTrue(em.due(directory, datetime(now.year + 1, 1, 1, tzinfo=timezone.utc)))

    def test_source_defects_preserved_and_reported(self):
        payload = CSV + b',=B28442,no,,\n'
        result = em.inspect_csv(payload)
        self.assertEqual(result['missing_date_rows'], 1)
        self.assertEqual(result['formula_hour_rows'], 1)
        self.assertEqual(result['row_count'], 2)

    def test_redirect_not_followed(self):
        self.assertIsNone(em.NoRedirect().redirect_request(None, None, 302, '', {}, 'https://example.com'))

    def test_download_is_one_call_with_token_header(self):
        with patch.object(em, 'build_opener') as factory:
            response = factory.return_value.open.return_value.__enter__.return_value
            response.status = 200
            response.read.return_value = CSV
            self.assertEqual(em.download('test-only'), CSV)
            factory.return_value.open.assert_called_once()
            request = factory.return_value.open.call_args.args[0]
            self.assertEqual(request.get_header('Authorization'), 'Token test-only')

    def test_workflow_rerun_blocked(self):
        with tempfile.TemporaryDirectory() as temporary:
            with patch('sys.argv', ['collector', '--data-dir', temporary]), patch.dict('os.environ', {'GITHUB_RUN_ATTEMPT': '2'}), patch.object(em, 'download') as fetch:
                with self.assertRaises(ValueError):
                    em.main()
                fetch.assert_not_called()


if __name__ == '__main__':
    unittest.main()
