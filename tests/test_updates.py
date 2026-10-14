"""Synthetic CSV files exercise update rules; no real dataset is modified."""
import csv
import copy
import tempfile
import unittest
from pathlib import Path
from scripts.updates import COLUMNS, plan_update

def row(month='Січень', value=10, **changes):
    r = dict(zip(COLUMNS, [2026, 'І', month, 'Імпорт', 'усього', 'тис. МВт×год', value]))
    r.update(changes)
    return r

class Updates(unittest.TestCase):
    def file_roundtrip(self, rows):
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / 'synthetic.csv'
            with path.open('w', encoding='utf-8', newline='') as f:
                w = csv.DictWriter(f, fieldnames=COLUMNS); w.writeheader(); w.writerows(rows)
            with path.open(encoding='utf-8', newline='') as f:
                return list(csv.DictReader(f))

    def test_identical_file(self):
        r = [row()]
        self.assertFalse(plan_update(r, self.file_roundtrip(r))['changed'])

    def test_new_month_and_repeat(self):
        result = plan_update([row()], self.file_roundtrip([row(), row('Лютий', 20)]))
        self.assertEqual(len(result['added']), 1)
        self.assertEqual(len(result['rows']), 2)
        self.assertFalse(plan_update(result['rows'], result['rows'])['changed'])

    def test_revision_audit(self):
        result = plan_update([row()], [row(value=12)])
        self.assertEqual(result['revised'][0]['before'], 10)
        self.assertEqual(result['revised'][0]['after'], 12)
        self.assertEqual(len(result['rows']), 1)

    def test_partial_history_preserved_and_flagged(self):
        result = plan_update([row()], [row('Лютий', 20)])
        self.assertEqual(len(result['rows']), 2)
        self.assertTrue(result['requires_review'])
        self.assertEqual(len(result['missing']), 1)

    def test_order_and_whitespace(self):
        old = [row(), row('Лютий', 20)]
        new = [row('Лютий', 20), row(**{'Категорія': ' усього '})]
        self.assertFalse(plan_update(old, new)['changed'])

    def test_duplicate_rejected(self):
        with self.assertRaisesRegex(ValueError, 'Duplicate'):
            plan_update([], [row(), row(value=12)])

    def test_units_rejected(self):
        for new in [row(**{'Одиниці виміру': 'МВт·год'}), row('Лютий', **{'Одиниці виміру': 'МВт·год'})]:
            with self.assertRaisesRegex(ValueError, 'Unit'):
                plan_update([row()], [new])

    def test_schema_rejected(self):
        r = row(); del r['Значення']
        with self.assertRaisesRegex(ValueError, 'columns'):
            plan_update([], [r])

    def test_empty_and_missing_values(self):
        for rows in [[], [row(value=None)], [row(value=float('nan'))]]:
            with self.assertRaises(ValueError): plan_update([], rows)

    def test_quarter_is_not_month(self):
        result = plan_update([], [row(), row('не застосовується', 30)])
        self.assertEqual(len(result['rows']), 2)

    def test_period_mismatch(self):
        with self.assertRaisesRegex(ValueError, 'mismatch'):
            plan_update([], [row('Квітень')])

    def test_failure_does_not_mutate_input(self):
        old = [row()]; before = copy.deepcopy(old)
        with self.assertRaises(ValueError): plan_update(old, [row(value='bad')])
        self.assertEqual(old, before)

if __name__ == '__main__': unittest.main()
