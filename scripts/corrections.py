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

def apply_reviewed_corrections(rows):
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
