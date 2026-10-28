"""Prepare the saved Energy Map snapshot, without any network requests."""
import argparse
from collections import Counter
from datetime import datetime, timedelta, timezone
import hashlib
import json
from pathlib import Path
import re
from zoneinfo import ZoneInfo

import numpy as np
import pandas as pd

from scripts.collect_energy_map import COLUMNS, ROOT

PROCESSOR_VERSION = '1'
ZONE = ZoneInfo('Europe/Kyiv')


def restore_known_dates(frame):
    """Apply the agreed April 2026 assumption only to the recognized source defect."""
    result = frame.copy().reset_index(drop=True)
    result['date'] = pd.to_datetime(result['date'], format='%Y-%m-%d', errors='raise')
    result['datetime_reconstructed'] = False
    missing = result['date'].isna()
    if not missing.any():
        return result  # Provider corrected the file, or it covers another period.
    before = np.flatnonzero((result['date'] == '2026-03-31') & (result['hour'] == '23:00-00:00'))
    after = np.flatnonzero((result['date'] == '2026-04-14') & (result['hour'] == '16:00-17:00'))
    if len(before) != 1 or len(after) != 1:
        raise ValueError('Missing dates: April block boundaries are not unique; review source.')
    index = result.index[before[0] + 1:after[0]]
    hours = pd.date_range('2026-04-01 00:00', '2026-04-14 15:00', freq='h')
    block = result.loc[index]
    formulas = pd.to_numeric(block['hour'].str.extract(r'^=B(\d+)$', expand=False), errors='coerce')
    if not (len(index) == len(hours) and block['date'].isna().all()
            and formulas.notna().all() and formulas.diff().iloc[1:].eq(1).all()):
        raise ValueError('April block differs from reviewed 328-row defect; review source.')
    if missing.sum() != len(index):
        raise ValueError('Additional missing dates outside April block; review source.')
    result.loc[index, 'date'] = hours.normalize()
    result.loc[index, 'hour'] = (hours.strftime('%H:%M') + '-'
                               + (hours + pd.Timedelta(hours=1)).strftime('%H:%M'))
    result.loc[index, 'datetime_reconstructed'] = True
    return result


def parse_outage_amount(value):
    """Keep unknowns; 'до N' uses the agreed analytical lower bound of zero."""
    if pd.isna(value):
        return np.nan, np.nan
    value = str(value).strip().replace(',', '.')
    number = r'(\d+(?:\.\d+)?)'
    if match := re.fullmatch(r'від\s+' + number + r'\s+до\s+' + number, value):
        lower, upper = map(float, match.groups())
    elif match := re.fullmatch(r'до\s+' + number, value):
        lower, upper = 0.0, float(match[1])
    elif re.fullmatch(number, value):
        lower = upper = float(value)
    else:
        raise ValueError(f'Unknown outage_amount format: {value!r}')
    if lower > upper:
        raise ValueError('Reversed outage amount interval')
    return lower, upper


def classify_outage_intensity(min_value, max_value):
    if pd.isna(min_value) or pd.isna(max_value):
        return 'Невідомо'
    if min_value == 0 and max_value == 0:
        return 'Без обмежень'
    if min_value > 0 and max_value <= 1:
        return 'Низька'
    if min_value > 1 and max_value <= 2:
        return 'Помірна'
    if min_value > 2:
        return 'Висока'
    return 'Змінна'


def expected_hours(day):
    """Enumerate real Kyiv hours through UTC; preserve the repeated autumn hour."""
    start = day.to_pydatetime().replace(tzinfo=ZONE).astimezone(timezone.utc)
    end = (day + pd.Timedelta(days=1)).to_pydatetime().replace(tzinfo=ZONE).astimezone(timezone.utc)
    slots = []
    while start < end:
        local = start.astimezone(ZONE)
        # Source labels an hourly slot by its wall-clock start + one hour,
        # including 03:00-04:00 twice on the autumn transition day.
        slots.append(local.strftime('%H:%M') + '-' + (local.replace(tzinfo=None) + timedelta(hours=1)).strftime('%H:%M'))
        start += timedelta(hours=1)
    return Counter(slots)


def validate_calendar(frame):
    if frame.empty or frame['date'].isna().any():
        raise ValueError('Empty dataset or unresolved missing dates')
    days = pd.date_range(frame['date'].min(), frame['date'].max())
    if len(days.difference(frame['date'])):
        raise ValueError('Calendar contains missing days')
    for day, group in frame.groupby('date', sort=True):
        if Counter(group['hour']) != expected_hours(day):
            raise ValueError(f'Unexpected hourly slots on {day:%Y-%m-%d}; review source/DST rules.')


def clean_outages(frame):
    if list(frame.columns) != COLUMNS:
        raise ValueError('Unexpected source columns')
    if not frame['outage_use'].isin(['так', 'ні']).all():
        raise ValueError('Missing or unexpected outage_use')
    result = restore_known_dates(frame)
    validate_calendar(result)
    no_outage = result['outage_use'].eq('ні')
    result.loc[no_outage & result['outage_amount'].isna(), 'outage_amount'] = '0'
    amounts = result['outage_amount'].apply(parse_outage_amount)
    result[['outage_amount_min', 'outage_amount_max']] = pd.DataFrame(amounts.tolist(), index=result.index)
    if (result.loc[no_outage, ['outage_amount_min', 'outage_amount_max']] != 0).any().any():
        raise ValueError('No-outage status conflicts with positive amount')
    result.loc[no_outage & result['number'].isna(), 'number'] = 'не застосовувались'
    result = result.rename(columns={'number': 'outage_coverage'})
    result['outage_intensity'] = result.apply(
        lambda row: classify_outage_intensity(row['outage_amount_min'], row['outage_amount_max']), axis=1)
    return result


def prepare(directory=ROOT / 'data/energy_map'):
    """Commit metadata last; failed validation leaves the prior processed files untouched."""
    directory = Path(directory)
    state_path = directory / 'current.json'
    state = json.loads(state_path.read_text(encoding='utf-8'))
    source = directory / state['file']
    payload = source.read_bytes()
    if hashlib.sha256(payload).hexdigest() != state['sha256']:
        raise ValueError('Source SHA-256 mismatch')
    output = directory / 'processed/outages.csv'
    audit_path = directory / 'processed/audit.json'
    if (not state.get('preparation_pending', True)
            and state.get('processed_sha256') == state['sha256']
            and state.get('processor_version') == PROCESSOR_VERSION
            and output.exists() and audit_path.exists()
            and hashlib.sha256(output.read_bytes()).hexdigest() == state.get('processed_file_sha256')):
        print('Energy Map preparation: unchanged; skipped (no API requests).')
        return False
    raw = pd.read_csv(source, dtype='string')
    clean = clean_outages(raw)
    audit = {
        'source_sha256': state['sha256'], 'processor_version': PROCESSOR_VERSION,
        'row_count': len(clean), 'data_start_date': clean['date'].min().strftime('%Y-%m-%d'),
        'data_end_date': clean['date'].max().strftime('%Y-%m-%d'),
        'reconstructed_rows': int(clean['datetime_reconstructed'].sum()),
        'reconstruction_assumption': 'April 2026 hours assigned by source row order; not provider-confirmed.',
        'intensity_counts': {str(k): int(v) for k, v in clean['outage_intensity'].value_counts().items()},
        'unknown_amount_rows': int(clean['outage_amount'].isna().sum()),
        'calendar_timezone': 'Europe/Kyiv', 'calendar_validated': True,
        'source_url': state['source_url'],
    }
    output.parent.mkdir(parents=True, exist_ok=True)
    temporary = output.with_suffix('.csv.tmp')
    clean.to_csv(temporary, index=False, date_format='%Y-%m-%d', encoding='utf-8-sig')
    audit_tmp = audit_path.with_suffix('.json.tmp')
    audit_tmp.write_text(json.dumps(audit, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
    state.update(processed_sha256=state['sha256'], processor_version=PROCESSOR_VERSION,
                 processed_file='processed/outages.csv', preparation_pending=False,
                 processed_file_sha256=hashlib.sha256(temporary.read_bytes()).hexdigest(),
                 last_prepared_at_utc=datetime.now(timezone.utc).isoformat())
    state_tmp = state_path.with_suffix('.json.tmp')
    state_tmp.write_text(json.dumps(state, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
    temporary.replace(output)
    audit_tmp.replace(audit_path)
    state_tmp.replace(state_path)
    print(f'Energy Map preparation: {len(clean)} rows; {audit["reconstructed_rows"]} reconstructed.')
    return True


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--data-dir', type=Path, default=ROOT / 'data/energy_map')
    args = parser.parse_args()
    prepare(args.data_dir)


if __name__ == '__main__':
    main()
