import unittest

import pandas as pd

from scripts.hourly_time import hourly_calendar, normalize_hours, csv_ready


class HourlyTimeTests(unittest.TestCase):
    def test_elapsed_hours_and_transition_labels(self):
        for day, count in [('2021-10-01', 24), ('2025-03-30', 23), ('2021-10-31', 25)]:
            slots = hourly_calendar(day)
            self.assertEqual(len(slots), count)
            self.assertTrue((slots.end_utc - slots.start_utc).eq(pd.Timedelta(hours=1)).all())
            self.assertTrue(slots.start_utc.is_unique)
        self.assertIn('02:00-04:00', hourly_calendar('2025-03-30').hour.tolist())
        self.assertIn('03:00-03:00', hourly_calendar('2021-10-31').hour.tolist())

    def test_legacy_and_canonical_produce_same_utc(self):
        for day in ['2025-03-30', '2021-10-31']:
            slots = hourly_calendar(day)
            legacy = pd.DataFrame({'date': day, 'hour': slots.legacy_hour, 'amount': range(len(slots))})
            canonical = legacy.assign(hour=slots.hour)
            a, b = normalize_hours(legacy), normalize_hours(canonical)
            pd.testing.assert_series_equal(a.start_utc, b.start_utc)
            self.assertEqual(a.amount.tolist(), legacy.amount.tolist())
            self.assertEqual(a.hour_original.tolist(), legacy.hour.tolist())
            if len(slots) == 25:
                self.assertEqual(a.time_status.eq('source_order_assumption').sum(), 2)

    def test_incomplete_and_extra_rows_remain_unresolved(self):
        slots = hourly_calendar('2021-10-31')
        frame = pd.DataFrame({'date': '2021-10-31', 'hour': slots.legacy_hour}).iloc[1:]
        self.assertTrue(normalize_hours(frame).start_utc.isna().all())
        with self.assertRaises(ValueError):
            normalize_hours(frame, strict=True)

    def test_serialization_preserves_distinct_offsets(self):
        slots = hourly_calendar('2021-10-31')
        frame = normalize_hours(pd.DataFrame({'date': '2021-10-31', 'hour': slots.legacy_hour}))
        serialized = csv_ready(frame)
        self.assertEqual(serialized.loc[3, 'start_local'], '2021-10-31T03:00:00+03:00')
        self.assertEqual(serialized.loc[4, 'start_local'], '2021-10-31T03:00:00+02:00')
        self.assertTrue(pd.to_datetime(serialized.start_utc, utc=True).is_unique)


if __name__ == '__main__':
    unittest.main()
