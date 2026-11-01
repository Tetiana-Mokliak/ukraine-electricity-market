from pathlib import Path
import tempfile
import unittest

import pandas as pd

from scripts.entsoe_hourly_check import read_hourly_xml, compare_hourly
from scripts.prepare_hourly_trade import remove_reviewed_zeros


class HourlyReconciliationTests(unittest.TestCase):
    def read(self, periods, curve='A03', unit='MAW'):
        xml = f'<root xmlns="urn:test"><TimeSeries><curveType>{curve}</curveType><quantity_Measure_Unit.name>{unit}</quantity_Measure_Unit.name>{periods}</TimeSeries></root>'
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / 'response.xml'
            path.write_text(xml)
            return read_hourly_xml(path)

    def period(self, start, end, points):
        return f'<Period><timeInterval><start>{start}</start><end>{end}</end></timeInterval><resolution>PT60M</resolution>' + ''.join(f'<Point><position>{p}</position><quantity>{v}</quantity></Point>' for p, v in points) + '</Period>'

    def test_sparse_changes_and_period_boundaries(self):
        one = self.period('2021-10-01T00:00Z', '2021-10-01T04:00Z', [(1, 84), (3, 75)])
        two = self.period('2021-10-01T04:00Z', '2021-10-01T06:00Z', [(2, 10)])
        result = self.read(one + two)
        self.assertEqual(result.entsoe_value.iloc[:4].tolist(), [84, 84, 75, 75])
        self.assertTrue(pd.isna(result.entsoe_value.iloc[4]))
        self.assertEqual(result.entsoe_value.iloc[5], 10)
        self.assertTrue(pd.isna(self.read(one, curve='A01').entsoe_value.iloc[1]))
        with self.assertRaises(ValueError):
            self.read(one + one)
        with self.assertRaises(ValueError):
            self.read(one, unit='MWH')

    def test_comparison_does_not_join_unknown_times_or_hide_missing(self):
        route = {'country': 'Польща', 'energy_system': 'ОЕС України', 'customs_regime': 'експорт'}
        left = pd.DataFrame([dict(route, start_utc='2021-10-01T00:00Z', amount=10),
                             dict(route, start_utc=None, amount=0)])
        right = pd.DataFrame([dict(route, start_utc='2021-10-01T00:00Z', entsoe_value=11),
                              dict(route, start_utc='2021-10-01T01:00Z', entsoe_value=0)])
        differences, unresolved = compare_hourly(left, right)
        self.assertEqual(len(differences), 2)
        self.assertEqual(len(unresolved), 1)
        self.assertEqual(left.amount.tolist(), [10, 0])

    def test_reviewed_cleanup_only_and_no_value_changes(self):
        from scripts.hourly_time import hourly_calendar
        rows = []
        routes = [('ОЕС України', 'Польща'), ('ОЕС України', 'Молдова'),
                  ('Бурштинський енергоострів', 'Румунія'),
                  ('Бурштинський енергоострів', 'Словаччина'), ('Бурштинський енергоострів', 'Угорщина')]
        rules = []
        for day in pd.date_range('2021-10-01', '2021-10-31'):
            date = day.strftime('%Y-%m-%d')
            for zone, country in routes:
                base = dict(date=date, energy_system=zone, country=country, customs_regime='експорт')
                for hour in hourly_calendar(day).legacy_hour:
                    rows.append(dict(base, hour=hour, amount=41.0))
                if day.day < 31:
                    rows.append(dict(base, hour='03:00-04:00', amount=0.0))
                    rules.append(dict(base, hour='03:00-04:00', expected_day_rows=25,
                                      expected_label_rows=2, reason='reviewed_zero', decision_basis='author'))
        raw = pd.DataFrame(rows)
        clean, removed = remove_reviewed_zeros(raw, rules)
        self.assertEqual(len(removed), 150)
        self.assertEqual(len(raw) - len(clean), 150)
        self.assertEqual(clean.amount.sum(), raw.amount.sum())
        self.assertEqual(len(clean[clean.date.eq('2021-10-31')]), 125)
        self.assertEqual(len(clean[clean.date.eq('2021-10-19') & clean.country.eq('Румунія')]), 24)
        with self.assertRaises(ValueError):
            remove_reviewed_zeros(raw.iloc[1:], rules)


if __name__ == '__main__':
    unittest.main()
