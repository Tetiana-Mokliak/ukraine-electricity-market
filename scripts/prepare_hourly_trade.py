"""Offline preparation of the reviewed Energy Map hourly trade CSV.

No ENTSO-E values are substituted. External comparison evidence remains private.
"""
import argparse
import hashlib
import json
from pathlib import Path

import pandas as pd

from scripts.hourly_time import normalize_hours, csv_ready

REVIEWED_SHA256 = '9d9ef435aa5c97199f6c24a9dbb49b13a95570fae2c286a7b355a37f98223b0f'
ROUTE_KEYS = ['energy_system', 'country', 'customs_regime']
GROUP_KEYS = ['date', *ROUTE_KEYS]


def remove_reviewed_zeros(frame):
    """Remove one zero per confirmed pair, excluding unresolved Romania 19 October."""
    result = frame.copy().reset_index(drop=True)
    result['source_row'] = result.index
    route = ((result['energy_system'].eq('ОЕС України') & result['country'].isin(['Польща', 'Молдова']))
             | (result['energy_system'].eq('Бурштинський енергоострів')
                & result['country'].isin(['Румунія', 'Словаччина', 'Угорщина'])))
    mask = (result['date'].between('2021-10-01', '2021-10-30') & route
            & result['customs_regime'].eq('експорт') & result['hour'].eq('03:00-04:00')
            & ~(result['country'].eq('Румунія') & result['date'].eq('2021-10-19')))
    candidates = result.loc[mask]
    sizes = candidates.groupby(GROUP_KEYS).size()
    if len(sizes) != 149 or not sizes.eq(2).all():
        raise ValueError('Reviewed duplicate pattern changed; manual review required')
    removed = candidates[candidates['amount'].eq(0)].groupby(GROUP_KEYS).head(1).copy()
    if len(removed) != 149:
        raise ValueError('Reviewed zero pattern changed; manual review required')
    removed['correction_reason'] = 'Extra zero: October 2021 private ENTSO-E reconciliation; excludes Romania 19 October'
    clean = result.drop(index=removed.index).copy()
    pd.testing.assert_series_equal(
        result.groupby(GROUP_KEYS)['amount'].sum(), clean.groupby(GROUP_KEYS)['amount'].sum())
    return clean, removed


def prepare(source, output_dir):
    source, output_dir = Path(source), Path(output_dir)
    digest = hashlib.sha256(source.read_bytes()).hexdigest()
    if digest != REVIEWED_SHA256:
        raise ValueError('Unreviewed source version: do not reuse the October correction automatically')
    raw = pd.read_csv(source)
    clean, removed = remove_reviewed_zeros(raw)
    clean = normalize_hours(clean, ROUTE_KEYS)
    audit = {'source_sha256': digest, 'source_rows': len(raw), 'output_rows': len(clean),
             'removed_zero_rows': len(removed), 'timezone': 'Europe/Kyiv', 'time_key': 'start_utc',
             'reference_policy': 'ENTSO-E for import/export reconciliation; see docs/hourly_time.md',
             'time_status_counts': clean['time_status'].value_counts().to_dict(),
             'known_value_discrepancy': 'Romania export, 2021-10-19/20: retained Energy Map values',
             'repeated_hour_assumption': 'Repeated legacy labels assigned in source occurrence order'}
    output_dir.mkdir(parents=True, exist_ok=True)
    csv_ready(clean).to_csv(output_dir / 'trade.csv', index=False, encoding='utf-8-sig')
    removed.to_csv(output_dir / 'removed_rows.csv', index=False, encoding='utf-8-sig')
    clean.loc[clean['start_utc'].isna()].to_csv(output_dir / 'unresolved_time.csv', index=False, encoding='utf-8-sig')
    (output_dir / 'audit.json').write_text(json.dumps(audit, ensure_ascii=False, indent=2) + '\n')
    print(json.dumps(audit, ensure_ascii=False, indent=2))


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('source', type=Path)
    parser.add_argument('--output-dir', type=Path, default=Path('outputs/hourly_trade'))
    args = parser.parse_args()
    prepare(args.source, args.output_dir)
