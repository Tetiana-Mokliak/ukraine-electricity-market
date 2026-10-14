import copy
import unittest
from scripts.corrections import apply_reviewed_corrections, MOVES
from scripts.updates import normalize

def fixture():
    values = {
        'Липень': [115.690, 12.284, 36.757, 28.273, 93.054, 286.058],
        'Серпень': [128.829, 22.835, 64.961, 64.834, 171.657, 453.116],
        'Вересень': [179.136, 105.821, 103.227, 1.080, 254.329, 643.593],
        'Жовтень': [31.135, 4.030, 14.896, 1.884, 39.324, 91.269],
    }
    rows = []
    for month, numbers in values.items():
        for country, value in zip(['Молдова', 'Польща', 'Румунія', 'Словаччина', 'Угорщина', 'усього'], numbers):
            rows.append({'Рік': 2025, 'Квартал': 'IV' if month == 'Жовтень' else 'ІІІ',
                         'Місяць': month, 'Показник': 'Експорт', 'Категорія': country,
                         'Одиниці виміру': 'тис. МВт×год', 'Значення': value})
    return rows

def broken_fixture():
    rows = fixture()
    for country, amount, old, new in MOVES:
        r = next(r for r in rows if r['Категорія'] == country and r['Місяць'] == new and abs(r['Значення'] - float(amount)) < 1e-9)
        r['Місяць'] = old; r['Квартал'] = 'ІІІ'
    return rows

class Corrections(unittest.TestCase):
    def test_six_moves_and_no_source_mutation(self):
        rows = broken_fixture(); original = copy.deepcopy(rows)
        fixed, log = apply_reviewed_corrections(rows)
        self.assertEqual(rows, original)
        self.assertEqual(len(normalize(fixed)), 24)
        self.assertEqual(sum(x['status'] == 'applied' for x in log), 6)
        self.assertEqual(fixed, fixture())
    def test_already_fixed_and_idempotent(self):
        fixed, _ = apply_reviewed_corrections(broken_fixture())
        again, log = apply_reviewed_corrections(fixed)
        self.assertEqual(again, fixed)
        self.assertTrue(all(x['status'] == 'already_corrected' for x in log))
    def test_partial_official_fix(self):
        rows = broken_fixture()
        r = next(r for r in rows if r['Категорія'] == 'Угорщина' and abs(r['Значення'] - 171.657) < 1e-9)
        r['Місяць'] = 'Серпень'
        fixed, log = apply_reviewed_corrections(rows)
        self.assertEqual(fixed, fixture())
        self.assertEqual(sum(x['status'] == 'applied' for x in log), 5)
    def test_changed_total_rejected(self):
        rows = broken_fixture(); rows[-1]['Значення'] += 1
        with self.assertRaisesRegex(ValueError, 'reconcile'): apply_reviewed_corrections(rows)
    def test_changed_value_rejected(self):
        rows = broken_fixture(); rows[10]['Значення'] += 1
        with self.assertRaises(ValueError): apply_reviewed_corrections(rows)
    def test_ambiguous_value_rejected(self):
        rows = broken_fixture(); rows.append(copy.deepcopy(rows[10]))
        with self.assertRaises(ValueError): apply_reviewed_corrections(rows)
    def test_unrelated_period_unchanged(self):
        rows = fixture()
        for r in rows: r['Рік'] = 2026
        fixed, log = apply_reviewed_corrections(rows)
        self.assertEqual(fixed, rows); self.assertEqual(log, [])

if __name__ == '__main__': unittest.main()
