"""Explicit reviewed month corrections; never infer arbitrary replacements."""
from copy import deepcopy
from decimal import Decimal

RULE_ID = 'export-2025-jul-oct-month-shifts-v1'
MOVES = (
    ('Угорщина', '171.657', 'Липень', 'Серпень'),
    ('Молдова', '179.136', 'Серпень', 'Вересень'),
    ('Молдова', '31.135', 'Вересень', 'Жовтень'),
    ('Польща', '105.821', 'Серпень', 'Вересень'),
    ('Польща', '4.030', 'Вересень', 'Жовтень'),
    ('Румунія', '14.896', 'Вересень', 'Жовтень'),
)
PERIODS = ('Липень', 'Серпень', 'Вересень', 'Жовтень')
COUNTRIES = {'Молдова', 'Польща', 'Румунія', 'Словаччина', 'Угорщина'}

def number(value):
    # Excel binary floating point artifacts are not substantive source differences.
    n = Decimal(str(value))
    rounded = n.quantize(Decimal('0.001'))
    if abs(n - rounded) > Decimal('0.000000001'):
        raise ValueError('Correction rule requires values at source 0.001 precision')
    return rounded

def apply_export_corrections(rows):
    prepared = deepcopy(rows)
    block = [r for r in prepared if r['Рік'] == 2025
             and r['Показник'].strip() == 'Експорт' and r['Місяць'] in PERIODS]
    if not block:
        return prepared, []
    relevant = [r for r in block if r['Категорія'].strip() in COUNTRIES | {'усього'}]
    if len(relevant) != len(block):
        raise ValueError('Reviewed export block has unknown categories')
    if any(r['Одиниці виміру'].strip() != 'тис. МВт×год' for r in block):
        raise ValueError('Reviewed export block unit changed')
    journal = []
    for country, amount, old_month, new_month in MOVES:
        matching = [r for r in block if r['Категорія'].strip() == country
                    and number(r['Значення']) == Decimal(amount)]
        source = [r for r in matching if r['Місяць'] == old_month]
        destination = [r for r in matching if r['Місяць'] == new_month]
        if len(source) == 1 and not destination:
            record = source[0]
            journal.append({'rule_id': RULE_ID, 'year': 2025, 'indicator': 'Експорт',
                            'category': country, 'value': amount,
                            'old_month': old_month, 'new_month': new_month,
                            'old_quarter': record['Квартал'],
                            'new_quarter': 'IV' if new_month == 'Жовтень' else 'ІІІ',
                            'status': 'applied', 'basis': 'Reviewed reconstruction; all four monthly totals reconcile'})
            record['Місяць'] = new_month
            record['Квартал'] = journal[-1]['new_quarter']
        elif not source and len(destination) == 1:
            journal.append({'rule_id': RULE_ID, 'category': country, 'value': amount,
                            'new_month': new_month, 'status': 'already_corrected'})
        else:
            raise ValueError(f'Reviewed correction no longer matches source: {country} {amount}')
    for month in PERIODS:
        monthly = [r for r in block if r['Місяць'] == month]
        totals = [r for r in monthly if r['Категорія'].strip() == 'усього']
        details = [r for r in monthly if r['Категорія'].strip() != 'усього']
        if len(totals) != 1 or len(details) != 5 or {r['Категорія'].strip() for r in details} != COUNTRIES:
            raise ValueError(f'Correction leaves incomplete or duplicated countries: {month}')
        if sum((number(r['Значення']) for r in details), Decimal(0)) != number(totals[0]['Значення']):
            raise ValueError(f'Correction does not reconcile monthly total: {month}')
    return prepared, journal


IMPORT_RULES = (
    (2022, ('Серпень', 'Вересень', 'Жовтень'),
     (('0.187', 'Серпень', 'Вересень'), ('1.492', 'Вересень', 'Жовтень'))),
    (2023, PERIODS,
     (('115.596', 'Липень', 'Серпень'), ('23.824', 'Серпень', 'Вересень'),
      ('17.207', 'Вересень', 'Жовтень'))),
)


def apply_existing_corrections(rows):
    prepared, journal = apply_export_corrections(rows)
    for year, months, moves in IMPORT_RULES:
        block = [r for r in prepared if r['Рік'] == year
                 and r['Показник'].strip() == 'Імпорт' and r['Місяць'] in months]
        if not block:
            continue
        expected = {'Білорусь', 'Румунія', 'Словаччина', 'Угорщина'}
        if year == 2023:
            expected |= {'Молдова', 'Польща'}
        for month in months:
            details = [r for r in block if r['Місяць'] == month and r['Категорія'].strip() != 'усього']
            categories = [r['Категорія'].strip() for r in details]
            required = expected | ({'Молдова'} if year == 2022 and month != 'Серпень' else set())
            if len(categories) != len(required) or set(categories) != required:
                raise ValueError(f'Reviewed import countries incomplete or duplicated: {year} {month}')
        if any(r['Одиниці виміру'].strip() != 'тис. МВт×год' for r in block):
            raise ValueError('Reviewed import block unit changed')
        rule_id = f'import-{year}-monthly-total-shifts-v1'
        for amount, old, new in moves:
            matching = [r for r in block if r['Категорія'].strip() == 'усього'
                        and number(r['Значення']) == Decimal(amount)]
            source = [r for r in matching if r['Місяць'] == old]
            destination = [r for r in matching if r['Місяць'] == new]
            if len(source) == 1 and not destination:
                record = source[0]
                quarter = 'IV' if new == 'Жовтень' else 'ІІІ'
                journal.append({'rule_id': rule_id, 'year': year, 'indicator': 'Імпорт',
                                'category': 'усього', 'value': amount,
                                'old_month': old, 'new_month': new,
                                'old_quarter': record['Квартал'], 'new_quarter': quarter,
                                'status': 'applied',
                                'basis': 'Reviewed reconstruction; all affected monthly totals reconcile exactly'})
                record['Місяць'], record['Квартал'] = new, quarter
            elif not source and len(destination) == 1:
                journal.append({'rule_id': rule_id, 'category': 'усього', 'value': amount,
                                'new_month': new, 'status': 'already_corrected'})
            else:
                raise ValueError(f'Reviewed import correction ambiguous or changed: {year} {amount}')
        for month in months:
            monthly = [r for r in block if r['Місяць'] == month]
            totals = [r for r in monthly if r['Категорія'].strip() == 'усього']
            details = [r for r in monthly if r['Категорія'].strip() != 'усього']
            if len(totals) != 1 or sum((number(r['Значення']) for r in details), Decimal(0)) != number(totals[0]['Значення']):
                raise ValueError(f'Import correction does not reconcile monthly total: {year} {month}')
    return prepared, journal


EXPORT_2024_MOVES = (
    ('Польща', '0.619', 'Серпень', 'Вересень'),
    ('Румунія', '0.029', 'Серпень', 'Вересень'),
    ('Молдова', '3.501', 'Вересень', 'Жовтень'),
    ('Польща', '7.359', 'Вересень', 'Жовтень'),
    ('Румунія', '15.556', 'Вересень', 'Жовтень'),
    ('Словаччина', '14.398', 'Вересень', 'Жовтень'),
    ('Угорщина', '20.267', 'Вересень', 'Жовтень'),
)


def apply_reviewed_corrections(rows):
    prepared, journal = apply_existing_corrections(rows)
    months = ('Серпень', 'Вересень', 'Жовтень')
    block = [r for r in prepared if r['Рік'] == 2024
             and r['Показник'].strip() == 'Експорт' and r['Місяць'] in months]
    if not block:
        return prepared, journal
    rule_id = 'export-2024-aug-oct-mathematical-assumption-v1'
    basis = 'Our mathematical assumption, not an official correction; exact sums in all affected months; missing countries are not imputed'
    if any(r['Одиниці виміру'].strip() != 'тис. МВт×год' for r in block):
        raise ValueError('Reviewed export 2024 unit changed')
    # Only the specifically reviewed identical Slovakia zero duplicate may be removed.
    zeros = [r for r in block if r['Місяць'] == 'Серпень'
             and r['Категорія'].strip() == 'Словаччина' and number(r['Значення']) == 0]
    if len(zeros) == 2 and zeros[0] == zeros[1]:
        duplicate = zeros[1]
        prepared = [r for r in prepared if r is not duplicate]
        block = [r for r in block if r is not duplicate]
        journal.append({'rule_id': rule_id, 'status': 'applied',
                        'action': 'remove_reviewed_identical_duplicate', 'year': 2024,
                        'indicator': 'Експорт', 'category': 'Словаччина',
                        'old_month': 'Серпень', 'value': '0.000', 'basis': basis})
    elif len(zeros) != 1:
        raise ValueError('Reviewed Slovakia zero duplicate changed')
    for country, amount, old, new in EXPORT_2024_MOVES:
        matching = [r for r in block if r['Категорія'].strip() == country
                    and number(r['Значення']) == Decimal(amount)]
        source = [r for r in matching if r['Місяць'] == old]
        destination = [r for r in matching if r['Місяць'] == new]
        if len(source) == 1 and not destination:
            record = source[0]
            quarter = 'IV' if new == 'Жовтень' else 'ІІІ'
            journal.append({'rule_id': rule_id, 'status': 'applied', 'action': 'move_month',
                            'year': 2024, 'indicator': 'Експорт', 'category': country,
                            'value': amount, 'old_month': old, 'new_month': new,
                            'old_quarter': record['Квартал'], 'new_quarter': quarter, 'basis': basis})
            record['Місяць'], record['Квартал'] = new, quarter
        elif not source and len(destination) == 1:
            journal.append({'rule_id': rule_id, 'status': 'already_corrected',
                            'category': country, 'value': amount, 'new_month': new, 'basis': basis})
        else:
            raise ValueError(f'Reviewed export 2024 move ambiguous or changed: {country} {amount}')
    for month, expected_total in zip(months, ('0.000', '0.691', '61.081')):
        monthly = [r for r in block if r['Місяць'] == month]
        totals = [r for r in monthly if r['Категорія'].strip() == 'усього']
        details = [r for r in monthly if r['Категорія'].strip() != 'усього']
        expected = {'Польща', 'Румунія', 'Угорщина'} if month == 'Вересень' else (COUNTRIES - {'Польща'} if month == 'Серпень' else COUNTRIES)
        categories = [r['Категорія'].strip() for r in details]
        if len(categories) != len(expected) or set(categories) != expected:
            raise ValueError(f'Reviewed export 2024 category coverage changed: {month}')
        if len(totals) != 1 or number(totals[0]['Значення']) != Decimal(expected_total) or sum((number(r['Значення']) for r in details), Decimal(0)) != Decimal(expected_total):
            raise ValueError(f'Export 2024 correction does not reconcile exactly: {month}')
    journal.append({'rule_id': rule_id, 'status': 'coverage_warning', 'year': 2024,
                    'indicator': 'Експорт', 'month': 'Серпень',
                    'missing_categories': ['Польща'], 'basis': basis})
    journal.append({'rule_id': rule_id, 'status': 'coverage_warning', 'year': 2024,
                    'indicator': 'Експорт', 'month': 'Вересень',
                    'missing_categories': ['Молдова', 'Словаччина'], 'basis': basis})
    return prepared, journal
