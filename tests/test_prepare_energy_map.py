import hashlib
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

import pandas as pd

from scripts import collect_energy_map as collector
from scripts import prepare_energy_map as prep

ROOT = Path(__file__).resolve().parents[1]
SOURCE = ROOT / 'data/energy_map/raw/8f5f35d119a9453172e7ee5a48e1a7a08241d0077fa3d8a664772c2b519b63b4.csv'


class PrepareEnergyMapTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.raw = pd.read_csv(SOURCE, dtype='string')
        cls.clean = prep.clean_outages(cls.raw)

    def test_reviewed_snapshot(self):
        self.assertEqual(len(self.clean), 30647)
        self.assertEqual(int(self.clean['datetime_reconstructed'].sum()), 328)
        self.assertEqual(int(self.clean['outage_amount'].isna().sum()), 3831)
        self.assertEqual(self.clean['outage_intensity'].value_counts().to_dict(), {
            'Без обмежень': 24527, 'Невідомо': 3831, 'Кілька рівнів': 894,
            'Висока': 482, 'Помірна': 457, 'Низька': 456})
        self.assertEqual(int(self.raw['date'].isna().sum()), 328)

    def test_provider_corrected_dates_are_not_reconstructed(self):
        fixed = self.raw.copy()
        index = self.clean.index[self.clean['datetime_reconstructed']]
        fixed.loc[index, 'date'] = self.clean.loc[index, 'date'].dt.strftime('%Y-%m-%d')
        fixed.loc[index, 'hour'] = self.clean.loc[index, 'hour']
        self.assertFalse(prep.clean_outages(fixed)['datetime_reconstructed'].any())

    def test_defect_detection_does_not_depend_on_index_labels(self):
        shifted = self.raw.copy()
        shifted.index += 100
        self.assertEqual(int(prep.clean_outages(shifted)['datetime_reconstructed'].sum()), 328)

    def test_unknown_missing_date_rejected(self):
        broken = self.raw.copy()
        broken.loc[10, 'date'] = pd.NA
        with self.assertRaises(ValueError):
            prep.clean_outages(broken)

    def test_changed_formula_sequence_rejected(self):
        broken = self.raw.copy()
        broken.loc[28470, 'hour'] = '=B1'
        with self.assertRaises(ValueError):
            prep.clean_outages(broken)

    def test_new_amount_and_conflicting_status_rejected(self):
        with self.assertRaises(ValueError):
            prep.parse_outage_amount('понад 3')
        broken = self.raw.copy()
        broken.loc[0, 'outage_amount'] = '2'
        with self.assertRaises(ValueError):
            prep.clean_outages(broken)

    def test_missing_and_duplicated_slots_cannot_cancel_out(self):
        broken = self.raw.copy()
        broken.loc[1, 'hour'] = broken.loc[0, 'hour']
        with self.assertRaises(ValueError):
            prep.clean_outages(broken)

    def test_dst_and_no_april_requirement_for_future_only_source(self):
        for day, count in [('2023-03-26', 23), ('2023-10-29', 25), ('2026-04-14', 24)]:
            self.assertEqual(sum(prep.expected_hours(pd.Timestamp(day)).values()), count)
        future = self.raw[self.raw['date'].eq('2026-06-30')].copy()
        self.assertEqual(len(prep.clean_outages(future)), 24)

    def test_saved_output_skips_and_failed_update_preserves_previous_clean(self):
        with tempfile.TemporaryDirectory() as temporary:
            directory = Path(temporary)
            collector.accept(SOURCE.read_bytes(), directory, '2026-10-21T15:38:00+00:00')
            with patch.object(collector, 'download', side_effect=AssertionError('No network')):
                self.assertTrue(prep.prepare(directory))
                self.assertFalse(prep.prepare(directory))
                output = directory / 'processed/outages.csv'
                old_output = output.read_bytes()
                old_state = json.loads((directory / 'current.json').read_text())
                broken = self.raw.copy()
                broken.loc[0, 'date'] = pd.NA
                collector.accept(broken.to_csv(index=False).encode(), directory, '2026-11-05T08:37:00+00:00')
                with self.assertRaises(ValueError):
                    prep.prepare(directory)
                new_state = json.loads((directory / 'current.json').read_text())
                self.assertTrue(new_state['preparation_pending'])
                self.assertEqual(new_state['processed_sha256'], old_state['processed_sha256'])
                self.assertEqual(output.read_bytes(), old_output)
                self.assertNotEqual(new_state['sha256'], hashlib.sha256(SOURCE.read_bytes()).hexdigest())


if __name__ == '__main__':
    unittest.main()
