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


class ImportCorrections(unittest.TestCase):
    def fixture(self, year):
        from scripts.corrections import IMPORT_RULES
        _, months, moves = next(x for x in IMPORT_RULES if x[0] == year)
        totals = {'Серпень': '0', 'Вересень': '0.187', 'Жовтень': '1.492'} if year == 2022 else {'Липень': '73.298', 'Серпень': '115.596', 'Вересень': '23.824', 'Жовтень': '17.207'}
        rows = []
        for month in months:
            categories = ['Білорусь', 'Румунія', 'Словаччина', 'Угорщина']
            if year == 2023: categories += ['Молдова', 'Польща']
            elif month != 'Серпень': categories += ['Молдова']
            for category in categories + ['усього']:
                rows.append({'Рік': year, 'Квартал': 'IV' if month == 'Жовтень' else 'ІІІ',
                             'Місяць': month, 'Показник': 'Імпорт', 'Категорія': category,
                             'Одиниці виміру': 'тис. МВт×год',
                             'Значення': totals[month] if category in ('Словаччина', 'усього') else '0'})
        for amount, old, new in moves:
            r = next(r for r in rows if r['Категорія'] == 'усього' and r['Місяць'] == new)
            r['Місяць'], r['Квартал'] = old, 'ІІІ'
        return rows

    def test_both_blocks_exact_and_idempotent(self):
        rows = self.fixture(2022) + self.fixture(2023)
        original = copy.deepcopy(rows)
        fixed, log = apply_reviewed_corrections(rows)
        self.assertEqual(rows, original)
        self.assertEqual(sum(x['status'] == 'applied' for x in log), 5)
        normalize(fixed)
        again, log = apply_reviewed_corrections(fixed)
        self.assertEqual(again, fixed)
        self.assertTrue(all(x['status'] == 'already_corrected' for x in log))

    def test_one_thousandth_difference_rejected_without_mutation(self):
        for year in (2022, 2023):
            rows = self.fixture(year)
            rows[0]['Значення'] = '0.001'
            original = copy.deepcopy(rows)
            with self.assertRaisesRegex(ValueError, 'reconcile'): apply_reviewed_corrections(rows)
            self.assertEqual(rows, original)

    def test_duplicate_or_missing_country_rejected(self):
        for year in (2022, 2023):
            rows = self.fixture(year)
            with self.assertRaises(ValueError): apply_reviewed_corrections(rows + [copy.deepcopy(rows[0])])
            with self.assertRaises(ValueError): apply_reviewed_corrections(rows[1:])

    def test_partial_official_fix(self):
        rows = self.fixture(2023)
        r = next(r for r in rows if r['Категорія'] == 'усього' and r['Значення'] == '115.596')
        r['Місяць'] = 'Серпень'
        fixed, log = apply_reviewed_corrections(rows)
        normalize(fixed)
        self.assertEqual(sum(x['status'] == 'applied' for x in log), 2)


EXPORT_2024_SOURCE = [{'Рік': 2024,
  'Квартал': 'ІІІ',
  'Місяць': 'Серпень',
  'Показник': 'Експорт',
  'Категорія': 'Молдова',
  'Одиниці виміру': 'тис. МВт×год',
  'Значення': 0},
 {'Рік': 2024,
  'Квартал': 'ІІІ',
  'Місяць': 'Серпень',
  'Показник': 'Експорт',
  'Категорія': 'Польща',
  'Одиниці виміру': 'тис. МВт×год',
  'Значення': 0.619},
 {'Рік': 2024,
  'Квартал': 'ІІІ',
  'Місяць': 'Серпень',
  'Показник': 'Експорт',
  'Категорія': 'Румунія',
  'Одиниці виміру': 'тис. МВт×год',
  'Значення': 0},
 {'Рік': 2024,
  'Квартал': 'ІІІ',
  'Місяць': 'Серпень',
  'Показник': 'Експорт',
  'Категорія': 'Румунія',
  'Одиниці виміру': 'тис. МВт×год',
  'Значення': 0.029},
 {'Рік': 2024,
  'Квартал': 'ІІІ',
  'Місяць': 'Серпень',
  'Показник': 'Експорт',
  'Категорія': 'Словаччина',
  'Одиниці виміру': 'тис. МВт×год',
  'Значення': 0},
 {'Рік': 2024,
  'Квартал': 'ІІІ',
  'Місяць': 'Серпень',
  'Показник': 'Експорт',
  'Категорія': 'Словаччина',
  'Одиниці виміру': 'тис. МВт×год',
  'Значення': 0},
 {'Рік': 2024,
  'Квартал': 'ІІІ',
  'Місяць': 'Серпень',
  'Показник': 'Експорт',
  'Категорія': 'Угорщина',
  'Одиниці виміру': 'тис. МВт×год',
  'Значення': 0},
 {'Рік': 2024,
  'Квартал': 'ІІІ',
  'Місяць': 'Серпень',
  'Показник': 'Експорт',
  'Категорія': 'усього',
  'Одиниці виміру': 'тис. МВт×год',
  'Значення': 0},
 {'Рік': 2024,
  'Квартал': 'ІІІ',
  'Місяць': 'Вересень',
  'Показник': 'Експорт',
  'Категорія': 'Молдова',
  'Одиниці виміру': 'тис. МВт×год',
  'Значення': 3.501},
 {'Рік': 2024,
  'Квартал': 'ІІІ',
  'Місяць': 'Вересень',
  'Показник': 'Експорт',
  'Категорія': 'Польща',
  'Одиниці виміру': 'тис. МВт×год',
  'Значення': 7.359},
 {'Рік': 2024,
  'Квартал': 'ІІІ',
  'Місяць': 'Вересень',
  'Показник': 'Експорт',
  'Категорія': 'Румунія',
  'Одиниці виміру': 'тис. МВт×год',
  'Значення': 15.556},
 {'Рік': 2024,
  'Квартал': 'ІІІ',
  'Місяць': 'Вересень',
  'Показник': 'Експорт',
  'Категорія': 'Словаччина',
  'Одиниці виміру': 'тис. МВт×год',
  'Значення': 14.398},
 {'Рік': 2024,
  'Квартал': 'ІІІ',
  'Місяць': 'Вересень',
  'Показник': 'Експорт',
  'Категорія': 'Угорщина',
  'Одиниці виміру': 'тис. МВт×год',
  'Значення': 0.043},
 {'Рік': 2024,
  'Квартал': 'ІІІ',
  'Місяць': 'Вересень',
  'Показник': 'Експорт',
  'Категорія': 'Угорщина',
  'Одиниці виміру': 'тис. МВт×год',
  'Значення': 20.267},
 {'Рік': 2024,
  'Квартал': 'ІІІ',
  'Місяць': 'Вересень',
  'Показник': 'Експорт',
  'Категорія': 'усього',
  'Одиниці виміру': 'тис. МВт×год',
  'Значення': 0.691},
 {'Рік': 2024,
  'Квартал': 'IV',
  'Місяць': 'Жовтень',
  'Показник': 'Експорт',
  'Категорія': 'усього',
  'Одиниці виміру': 'тис. МВт×год',
  'Значення': 61.081}]


class ReviewedCleanup(unittest.TestCase):
    def fixture(self):
        rows = []
        for year, month, values in (
            (2022, 'Вересень', [111.470, 105.290, 82.303, 120.716, 0, 419.779]),
            (2024, 'Липень', [0, 0, 0, 0, 0, 0]),
            (2022, 'Жовтень', [34.735, 53.010, 35.511, 35.892, None, 159.148]),
        ):
            for category, value in zip(['Молдова', 'Польща', 'Румунія', 'Словаччина', 'Угорщина', 'усього'], values):
                if value is None:
                    continue
                rows.append({'Рік': year, 'Місяць': month, 'Квартал': 'IV' if month == 'Жовтень' and category in ('Словаччина', 'усього') else 'ІІІ',
                             'Показник': 'Експорт', 'Категорія': category,
                             'Одиниці виміру': 'тис. МВт×год', 'Значення': value})
                if (year, month, category) in ((2022, 'Вересень', 'Угорщина'), (2024, 'Липень', 'Молдова'), (2024, 'Липень', 'Польща')):
                    rows.append(copy.deepcopy(rows[-1]))
        return rows

    def test_only_approved_actions_and_no_mutation(self):
        rows = self.fixture(); original = copy.deepcopy(rows)
        fixed, log = apply_reviewed_corrections(rows)
        self.assertEqual(rows, original)
        self.assertEqual(len(fixed), len(rows) - 3)
        self.assertEqual(sum(x['status'] == 'applied' for x in log), 6)
        normalize(fixed)
        self.assertTrue(all(r['Квартал'] == 'IV' for r in fixed if r['Місяць'] == 'Жовтень'))

    def test_idempotence_and_partial_official_fix(self):
        rows = self.fixture()
        rows.remove(next(r for r in rows if r['Рік'] == 2024 and r['Категорія'] == 'Молдова'))
        next(r for r in rows if r['Місяць'] == 'Жовтень' and r['Категорія'] == 'Польща')['Квартал'] = 'IV'
        fixed, log = apply_reviewed_corrections(rows)
        self.assertEqual(sum(x['status'] == 'applied' for x in log), 4)
        again, log = apply_reviewed_corrections(fixed)
        self.assertEqual(again, fixed)
        self.assertTrue(all(x['status'] == 'already_corrected' for x in log))

    def test_nonzero_or_nonidentical_copy_rejected(self):
        for field, value in (('Значення', 0.001), ('Квартал', 'II')):
            rows = self.fixture(); rows[4][field] = value
            original = copy.deepcopy(rows)
            with self.assertRaises(ValueError): apply_reviewed_corrections(rows)
            self.assertEqual(rows, original)

    def test_changed_total_by_one_thousandth_rejected(self):
        rows = self.fixture()
        next(r for r in rows if r['Рік'] == 2022 and r['Місяць'] == 'Вересень' and r['Категорія'] == 'усього')['Значення'] = 419.780
        with self.assertRaises(ValueError): apply_reviewed_corrections(rows)

    def test_october_changed_value_or_ambiguous_row_rejected(self):
        rows = self.fixture()
        row = next(r for r in rows if r['Місяць'] == 'Жовтень' and r['Категорія'] == 'Молдова')
        with self.assertRaises(ValueError): apply_reviewed_corrections(rows + [copy.deepcopy(row)])
        row['Значення'] = 34.736
        with self.assertRaises(ValueError): apply_reviewed_corrections(rows)

    def test_incomplete_august_block_rejected(self):
        row = {'Рік': 2022, 'Місяць': 'Серпень', 'Квартал': 'ІІІ', 'Показник': 'Експорт',
               'Категорія': 'Молдова', 'Одиниці виміру': 'тис. МВт×год', 'Значення': 106.275}
        rows = [row, copy.deepcopy(row)]
        with self.assertRaises(ValueError): apply_reviewed_corrections(rows)


class August2022Copies(unittest.TestCase):
    def fixture(self):
        rows = []
        for country, value in (('Молдова', 106.275), ('Польща', 152.845),
                               ('Румунія', 92.611), ('Словаччина', 90.626), ('усього', 442.357)):
            row = {'Рік': 2022, 'Місяць': 'Серпень', 'Квартал': 'ІІІ', 'Показник': 'Експорт',
                   'Категорія': country, 'Одиниці виміру': 'тис. МВт×год', 'Значення': value}
            rows.append(row)
            if country in ('Молдова', 'Польща'): rows.append(copy.deepcopy(row))
        return rows

    def test_exact_cleanup_no_input_mutation_and_idempotence(self):
        rows = self.fixture(); original = copy.deepcopy(rows)
        fixed, log = apply_reviewed_corrections(rows)
        self.assertEqual(rows, original)
        self.assertEqual(len(normalize(fixed)), 5)
        self.assertEqual(sum(x['status'] == 'applied' for x in log), 2)
        again, log = apply_reviewed_corrections(fixed)
        self.assertEqual(again, fixed)
        self.assertTrue(all(x['status'] == 'already_corrected' for x in log))

    def test_partial_source_fix(self):
        rows = self.fixture(); del rows[1]
        fixed, log = apply_reviewed_corrections(rows)
        normalize(fixed)
        self.assertEqual(sum(x['status'] == 'applied' for x in log), 1)

    def test_changed_total_unit_country_or_copy_rejected(self):
        for field, value, index in (('Значення', 442.358, -1),
                                    ('Одиниці виміру', 'МВт×год', 0),
                                    ('Категорія', 'Угорщина', 4),
                                    ('Квартал', 'IV', 1),
                                    ('Значення', 106.276, 1)):
            rows = self.fixture(); rows[index][field] = value
            original = copy.deepcopy(rows)
            with self.assertRaises(ValueError): apply_reviewed_corrections(rows)
            self.assertEqual(rows, original)

    def test_third_copy_or_duplicate_other_country_rejected(self):
        for index in (0, 4):
            rows = self.fixture(); rows.append(copy.deepcopy(rows[index]))
            with self.assertRaises(ValueError): apply_reviewed_corrections(rows)


class Export2024Corrections(unittest.TestCase):
    def test_real_block_and_idempotence(self):
        rows = copy.deepcopy(EXPORT_2024_SOURCE)
        fixed, log = apply_reviewed_corrections(rows)
        self.assertEqual(rows, EXPORT_2024_SOURCE)
        normalize(fixed)
        self.assertEqual(sum(x['status'] == 'applied' for x in log), 8)
        self.assertEqual(len([r for r in fixed if r['Місяць'] == 'Вересень']), 4)
        self.assertTrue(any(x['status'] == 'coverage_warning' for x in log))
        again, log = apply_reviewed_corrections(fixed)
        self.assertEqual(again, fixed)
        self.assertFalse(any(x['status'] == 'applied' for x in log))
    def test_each_month_total_difference_rejected(self):
        for month in ('Серпень', 'Вересень', 'Жовтень'):
            rows = copy.deepcopy(EXPORT_2024_SOURCE)
            r = next(r for r in rows if r['Місяць'] == month and r['Категорія'] == 'усього')
            r['Значення'] += 0.001
            original = copy.deepcopy(rows)
            with self.assertRaises(ValueError): apply_reviewed_corrections(rows)
            self.assertEqual(rows, original)
    def test_ambiguous_move_rejected(self):
        rows = copy.deepcopy(EXPORT_2024_SOURCE)
        rows.append(copy.deepcopy(next(r for r in rows if r['Значення'] == 20.267)))
        with self.assertRaises(ValueError): apply_reviewed_corrections(rows)
    def test_partial_official_fix(self):
        rows = copy.deepcopy(EXPORT_2024_SOURCE)
        r = next(r for r in rows if r['Значення'] == 20.267)
        r['Місяць'], r['Квартал'] = 'Жовтень', 'IV'
        fixed, log = apply_reviewed_corrections(rows)
        normalize(fixed)
        self.assertEqual(sum(x['status'] == 'applied' for x in log), 7)
