"""Pure update rules. No network, scheduling or production writes."""
import math

COLUMNS = ('Рік', 'Квартал', 'Місяць', 'Показник', 'Категорія', 'Одиниці виміру', 'Значення')
MONTHS = ('Січень', 'Лютий', 'Березень', 'Квітень', 'Травень', 'Червень', 'Липень', 'Серпень', 'Вересень', 'Жовтень', 'Листопад', 'Грудень')
QUARTERS = ('І', 'ІІ', 'ІІІ', 'IV')

def normalize(rows):
    result = {}
    for source in rows:
        if set(source) != set(COLUMNS):
            raise ValueError('Unexpected columns')
        r = {k: (v.strip() if isinstance(v, str) else v) for k, v in source.items()}
        try:
            year = float(r['Рік'])
            value = float(r['Значення'])
        except (TypeError, ValueError):
            raise ValueError('Missing or non-numeric year/value')
        if not year.is_integer() or not 1900 <= year <= 2100 or not math.isfinite(value):
            raise ValueError('Invalid year/value')
        r['Рік'], r['Значення'] = int(year), value
        quarter = r['Квартал']
        # Source uses both Cyrillic and Latin Roman numerals.
        quarter = str(quarter).replace('I', 'І').replace('V', 'V')
        qmap = {'І': 1, 'ІІ': 2, 'ІІІ': 3, 'ІV': 4, 'IV': 4}
        if quarter not in qmap:
            raise ValueError('Unknown quarter')
        q = qmap[quarter]
        month = r['Місяць']
        if month == 'не застосовується':
            period = ('quarter', q)
        elif month in MONTHS:
            m = MONTHS.index(month) + 1
            if (m - 1) // 3 + 1 != q:
                raise ValueError('Month/quarter mismatch')
            period = ('month', m)
        else:
            raise ValueError('Unknown period')
        for field in ('Показник', 'Одиниці виміру'):
            if not isinstance(r[field], str) or not r[field]:
                raise ValueError('Missing indicator/unit')
        r['Категорія'] = r['Категорія'] or ''
        key = (r['Рік'], *period, r['Показник'], r['Категорія'])
        if key in result:
            raise ValueError('Duplicate observation key')
        result[key] = r
    if not result:
        raise ValueError('Empty dataset')
    return result

def plan_update(previous, incoming):
    """Return candidate + audit; callers must review missing keys before publishing."""
    old = normalize(previous) if previous else {}
    new = normalize(incoming)
    added, revised = [], []
    candidate = dict(old)
    for key, row in new.items():
        if key not in old:
            # Unit changes across periods also need explicit review.
            units = {r['Одиниці виміру'] for k, r in old.items() if k[3:] == key[3:]}
            if units and row['Одиниці виміру'] not in units:
                raise ValueError('Unit changed')
            added.append(key)
        else:
            if old[key]['Одиниці виміру'] != row['Одиниці виміру']:
                raise ValueError('Unit changed')
            if old[key]['Значення'] != row['Значення']:
                revised.append({'key': key, 'before': old[key]['Значення'], 'after': row['Значення']})
        candidate[key] = row
    missing = sorted(set(old) - set(new))
    return {'rows': [candidate[k] for k in sorted(candidate)], 'added': added,
            'revised': revised, 'missing': missing, 'requires_review': bool(missing),
            'changed': bool(added or revised)}
