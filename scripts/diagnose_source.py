"""Read-only whole-workbook diagnostics after approved corrections.

python -m scripts.diagnose_source source.xlsx --version 2026-09-01 --output report.json
Never accepts a snapshot, deduplicates published rows, or changes correction rules.
"""
import argparse
from collections import Counter, defaultdict
from decimal import Decimal
import hashlib
import json
from pathlib import Path

from scripts.collect_nerc import read_workbook
from scripts.corrections import apply_reviewed_corrections, number
from scripts.updates import MONTHS, normalize


def diagnose(payload, version):
    raw = read_workbook(payload, version)
    rows, journal = apply_reviewed_corrections(raw)
    groups, keys, series = defaultdict(list), defaultdict(list), defaultdict(set)
    invalid = []
    for row in rows:
        # Singleton validation avoids stopping the investigation at the first duplicate.
        try:
            normalize([row])
        except ValueError as error:
            invalid.append({'row': row, 'error': str(error)})
        year, month, indicator = row['Рік'], row['Місяць'], row['Показник'].strip()
        category = (row['Категорія'] or '').strip()
        quarter = str(row['Квартал']).replace('I', 'І')
        period = month if month != 'не застосовується' else quarter
        keys[year, period, indicator, category].append(row)
        groups[year, month, indicator].append(row)
        if month in MONTHS:
            series[indicator, category].add(year * 12 + MONTHS.index(month))
    duplicates = [dict(key=list(key), rows=value, identical=all(r == value[0] for r in value))
                  for key, value in keys.items() if len(value) > 1]
    trade, structures, coverage = [], [], []
    for (year, month, indicator), values in groups.items():
        if indicator in ('Експорт', 'Імпорт'):
            totals = [r for r in values if r['Категорія'].strip() == 'усього']
            details = [r for r in values if r['Категорія'].strip() != 'усього']
            total = number(totals[0]['Значення']) if len(totals) == 1 else None
            actual = sum((number(r['Значення']) for r in details), Decimal(0))
            # Counterfactual only: explicitly NOT a transformation of rows.
            unique = {tuple(r.items()): r for r in details}.values()
            once = sum((number(r['Значення']) for r in unique), Decimal(0))
            trade.append(dict(year=year, month=month, indicator=indicator,
                              total_count=len(totals), total=str(total),
                              detail_sum=str(actual), exact_match=total == actual,
                              hypothetical_sum_identical_rows_once=str(once)))
            if indicator == 'Експорт':
                expected = {'Молдова', 'Польща', 'Румунія', 'Словаччина', 'Угорщина'}
                missing = sorted(expected - {r['Категорія'].strip() for r in details})
                if missing:
                    coverage.append(dict(year=year, month=month, missing=missing,
                                         note='Comparison to five-country analytical reference; absence is not proof of error or zero'))
        if indicator.startswith('Структура'):
            total = sum((Decimal(str(r['Значення'])) for r in values), Decimal(0))
            structures.append(dict(year=year, month=month, indicator=indicator,
                                   sum=str(total), residual_from_100=str(total - 100)))
    gaps = []
    for (indicator, category), dates in series.items():
        missing = sorted(set(range(min(dates), max(dates) + 1)) - dates)
        if missing:
            gaps.append(dict(indicator=indicator, category=category,
                             missing=[dict(year=d // 12, month=MONTHS[d % 12]) for d in missing]))
    profile = []
    for indicator in sorted({r['Показник'].strip() for r in rows}):
        values = [r for r in rows if r['Показник'].strip() == indicator]
        profile.append(dict(indicator=indicator, rows=len(values),
                            units=sorted({r['Одиниці виміру'] for r in values}),
                            categories=sorted({(r['Категорія'] or '').strip() for r in values})))
    vde = []
    for (year, month, indicator), values in groups.items():
        if indicator == 'Структура виробництва':
            production = next(Decimal(str(r['Значення'])) for r in values if r['Категорія'].strip() == 'ВДЕ')
            shares = groups[year, month, 'Частка ВДЕ у загальній структурі виробленої електричної енергії']
            total = sum((Decimal(str(r['Значення'])) for r in shares), Decimal(0))
            vde.append(dict(year=year, month=month, components=len(shares),
                            residual=str(total-production)))
    try:
        normalize(rows)
        accepted = True
    except ValueError:
        accepted = False
    return dict(version=version, sha256=hashlib.sha256(payload).hexdigest(),
                raw_rows=len(raw), corrected_rows=len(rows),
                correction_statuses=dict(Counter(j['status'] for j in journal)),
                corrections=journal, profile=profile,
                null_counts={c: sum(r[c] is None for r in rows) for c in rows[0]},
                negative_rows=[r for r in rows if r['Значення'] < 0],
                invalid_share_rows=[r for r in rows if r['Одиниці виміру'] == '%'
                                    and (r['Показник'].startswith('Структура') or r['Показник'].startswith('Частка'))
                                    and not 0 <= r['Значення'] <= 100],
                volatility_over_100=[r for r in rows if r['Показник'] == 'Волатильність' and r['Значення'] > 100],
                duplicate_keys=duplicates, invalid_rows=invalid,
                trade_checks=trade, structure_checks=structures,
                vde_crosschecks=vde, internal_series_gaps=gaps,
                export_coverage_warnings=coverage, normalization_passed=accepted,
                note='Read-only diagnosis. Hypothetical sums do not authorize duplicate removal. No external validation in this run.')


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('workbook', type=Path)
    parser.add_argument('--version', required=True)
    parser.add_argument('--output', required=True, type=Path)
    args = parser.parse_args()
    result = diagnose(args.workbook.read_bytes(), args.version)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(result, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
    print(json.dumps({k: result[k] for k in ('raw_rows', 'corrected_rows', 'normalization_passed')}, ensure_ascii=False))


if __name__ == '__main__':
    main()
