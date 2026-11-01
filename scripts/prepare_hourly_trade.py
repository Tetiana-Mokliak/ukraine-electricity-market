"""Offline hourly trade preparation; atomic snapshots and accepted-history gate."""
import argparse
import gzip
import hashlib
import json
import os
from pathlib import Path
import shutil
import tempfile

import pandas as pd

from scripts.hourly_time import normalize_hours, csv_ready, TIMEZONE
from scripts.hourly_trade_updates import (COLUMNS, ROUTE, ReviewRequired,
                                         validate_source, accept_history)

ROOT = Path(__file__).resolve().parents[1]
REVIEWED_SHA256 = '9d9ef435aa5c97199f6c24a9dbb49b13a95570fae2c286a7b355a37f98223b0f'
PROCESSOR_VERSION = '6'
ROUTE_KEYS = ROUTE
GROUP_KEYS = ['date', *ROUTE]
RULES_PATH = ROOT / 'data/hourly_trade/rules.json'


def sha256(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def remove_reviewed_zeros(frame, rules=None):
    """Only scoped author-approved rules; no generic zero/dedup removal."""
    if rules is None:
        rules = json.loads(RULES_PATH.read_text())['rules']
    result = frame.copy().reset_index(drop=True)
    if 'source_row' not in result:
        result['source_row'] = result.index
    grouped = result.groupby(GROUP_KEYS, sort=False).indices
    deleted, reasons, bases = [], [], []
    for rule in rules:
        key = tuple(rule[k] for k in GROUP_KEYS)
        if key not in grouped:
            raise ReviewRequired(f'Reviewed correction day missing: {key}')
        day = result.iloc[grouped[key]]
        matches = day.loc[day.hour.eq(rule['hour'])]
        zero = matches.loc[matches.amount.eq(0)]
        if (len(day) != rule['expected_day_rows']
                or len(matches) != rule['expected_label_rows'] or zero.empty):
            raise ReviewRequired(f'Reviewed extra-zero pattern changed: {key}')
        deleted.append(zero.index[0])
        reasons.append(rule['reason'])
        bases.append(rule['decision_basis'])
    if len(set(deleted)) != len(deleted):
        raise ReviewRequired('Overlapping correction rules')
    removed = result.loc[deleted].copy()
    removed['correction_reason'], removed['decision_basis'] = reasons, bases
    clean = result.drop(index=deleted).copy()
    pd.testing.assert_series_equal(result.groupby(GROUP_KEYS).amount.sum(),
                                   clean.groupby(GROUP_KEYS).amount.sum())
    pd.testing.assert_frame_equal(clean, result.loc[clean.index])
    return clean, removed


def validate_prepared(raw, clean, removed, history_end):
    if len(raw) != len(clean) + len(removed) or not removed.amount.eq(0).all():
        raise ReviewRequired('Unexpected row loss or nonzero removal')
    if not clean.source_row.is_unique:
        raise ReviewRequired('Source row links are not unique')
    defined = clean.loc[clean.start_utc.notna()]
    if defined.duplicated([*ROUTE, 'start_utc']).any():
        raise ReviewRequired('Duplicate UTC route key')
    if not (defined.end_utc - defined.start_utc).eq(pd.Timedelta(hours=1)).all():
        raise ReviewRequired('Interval is not one elapsed hour')
    if clean.time_status.eq('unresolved_calendar').any():
        raise ReviewRequired('Unknown daily calendar pattern')
    if not clean.loc[clean.date.gt(history_end), 'calendar_complete'].all():
        raise ReviewRequired('New dates must contain complete recognized calendars')
    new = clean.loc[clean.date.gt(history_end)]
    if not new.empty:
        expected_days = pd.date_range(pd.Timestamp(history_end) + pd.Timedelta(days=1), new.date.max())
        if set(expected_days.strftime('%Y-%m-%d')) != set(new.date):
            raise ReviewRequired('New period has missing calendar dates')
        active = set(map(tuple, clean.loc[clean.date.eq(history_end), ROUTE].drop_duplicates().to_numpy()))
        for day, group in new.groupby('date'):
            if set(map(tuple, group[ROUTE].drop_duplicates().to_numpy())) != active:
                raise ReviewRequired(f'New date has changed active route coverage: {day}')
    pd.testing.assert_series_equal(raw.groupby(GROUP_KEYS).amount.sum(), clean.groupby(GROUP_KEYS).amount.sum())
    origin, retained = raw.set_index('source_row'), clean.set_index('source_row')
    pd.testing.assert_frame_equal(retained[COLUMNS[2:]], origin.loc[retained.index, COLUMNS[2:]])


def write_json(path, value):
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')


def save_gzip(frame, path):
    frame.to_csv(path, index=False, encoding='utf-8', compression={'method': 'gzip', 'mtime': 0})


def prepare(source, output_dir=ROOT / 'data/hourly_trade'):
    source, output_dir = Path(source), Path(output_dir)
    digest = sha256(source)
    pointer = output_dir / 'current.json'
    old_state = json.loads(pointer.read_text()) if pointer.exists() else None
    if (old_state and old_state['source_sha256'] == digest
            and old_state['processor_version'] == PROCESSOR_VERSION
            and old_state.get('rules_sha256') == sha256(RULES_PATH)):
        snapshot = output_dir / old_state['snapshot']
        if not all((snapshot / name).is_file() and sha256(snapshot / name) == checksum
                   for name, checksum in old_state['files'].items()):
            raise ReviewRequired('Accepted snapshot failed integrity check')
        audit = json.loads((snapshot / 'audit.json').read_text())
        print('Hourly trade: unchanged source and processor; verified snapshot retained.')
        return audit
    incoming = validate_source(pd.read_csv(source))
    if old_state:
        previous_path = output_dir / old_state['snapshot'] / 'source.csv.gz'
        if sha256(previous_path) != old_state['files']['source.csv.gz']:
            raise ReviewRequired('Accepted source ledger failed integrity check')
        previous = validate_source(pd.read_csv(previous_path))
        raw, changes = accept_history(previous, incoming)
        history_end = previous.date.max()
    else:
        if digest != REVIEWED_SHA256:
            raise ReviewRequired('Initial baseline must be the reviewed Energy Map file')
        raw = incoming.assign(source_row=range(len(incoming)))
        changes = {'accepted': True, 'initial_baseline': True,
                   'history_start': incoming.date.min(), 'history_end': incoming.date.max(),
                   'history_rows': len(incoming), 'new_rows': 0}
        history_end = incoming.date.max()
    clean, removed = remove_reviewed_zeros(raw)
    clean = normalize_hours(clean, ROUTE, allow_legacy_fall_partial=True)
    # Scope and evidence labels do not contain external source values.
    clean['external_check_status'] = 'private_comparison_not_published'
    assumption = removed.loc[removed.decision_basis.eq('user_approved_pattern_assumption_no_external_confirmation'), GROUP_KEYS]
    assumption_keys = set(map(tuple, assumption.to_numpy()))
    clean['calendar_mapping_basis'] = [
        'author_approved_pattern_assumption' if key in assumption_keys else 'calendar_or_recorded_time_status'
        for key in map(tuple, clean[GROUP_KEYS].to_numpy())]
    validate_prepared(raw, clean, removed, history_end)
    audit = {
        'processor_version': PROCESSOR_VERSION, 'source_sha256': digest,
        'source_rows': len(raw), 'output_rows': len(clean), 'removed_zero_rows': len(removed),
        'data_start_date': raw.date.min(), 'data_end_date': raw.date.max(),
        'timezone': TIMEZONE, 'time_key': [*ROUTE, 'start_utc'],
        'time_status_counts': {str(k): int(v) for k,v in clean.time_status.value_counts().items()},
        'incomplete_day_route_count': int(clean.loc[~clean.calendar_complete, GROUP_KEYS].drop_duplicates().shape[0]),
        'undefined_utc_rows': int(clean.start_utc.isna().sum()),
        'daily_sums_preserved': True, 'retained_values_preserved': True,
        'source_values': 'Energy Map only; private external comparison is not published',
        'spring_pattern_assumption_rows': int(removed.decision_basis.eq('user_approved_pattern_assumption_no_external_confirmation').sum()),
        'repeated_hour_assumption': 'Accepted source occurrence order; retained across reordered history',
    }
    version = hashlib.sha256((digest + PROCESSOR_VERSION + sha256(RULES_PATH)).encode()).hexdigest()[:24]
    relative = f'snapshots/{version}'
    final = output_dir / relative
    output_dir.mkdir(parents=True, exist_ok=True)
    stage = Path(tempfile.mkdtemp(prefix='.pending-', dir=output_dir))
    try:
        serial = csv_ready(clean)
        save_gzip(serial, stage / 'trade.csv.gz')
        save_gzip(raw[COLUMNS], stage / 'source.csv.gz')
        # Exact original CSV bytes, compressed for transfer; source_row indexes this file.
        with source.open('rb') as src, (stage / 'input.csv.gz').open('wb') as dest:
            with gzip.GzipFile(fileobj=dest, filename='', mode='wb', mtime=0) as compressed:
                shutil.copyfileobj(src, compressed)
        removed.to_csv(stage / 'removed_rows.csv', index=False, encoding='utf-8')
        serial.loc[clean.start_utc.isna()].to_csv(stage / 'unresolved_time.csv', index=False, encoding='utf-8')
        serial.loc[~clean.calendar_complete, GROUP_KEYS].drop_duplicates().to_csv(stage / 'incomplete_days.csv', index=False)
        write_json(stage / 'audit.json', audit)
        write_json(stage / 'changes.json', changes)
        back = pd.read_csv(stage / 'trade.csv.gz', keep_default_na=False)
        if len(back) != len(clean) or not back.source_row.equals(serial.source_row.reset_index(drop=True)):
            raise ReviewRequired('Saved table failed row/provenance roundtrip')
        pd.testing.assert_series_equal(back.amount, clean.amount.reset_index(drop=True), check_names=False)
        files = {path.name: sha256(path) for path in sorted(stage.iterdir())}
        if final.exists():
            actual = {path.name: sha256(path) for path in sorted(final.iterdir())}
            if actual != files:
                raise ReviewRequired('Existing immutable snapshot differs; review before replacement')
            shutil.rmtree(stage)
        else:
            final.parent.mkdir(exist_ok=True)
            os.replace(stage, final)
        state = {'snapshot': relative, 'processor_version': PROCESSOR_VERSION,
                 'rules_sha256': sha256(RULES_PATH),
                 'source_sha256': digest, 'data_end_date': raw.date.max(), 'files': files}
        temp_pointer = output_dir / '.current.json.tmp'
        write_json(temp_pointer, state)
        os.replace(temp_pointer, pointer)
    finally:
        if stage.exists():
            shutil.rmtree(stage)
    print(json.dumps(audit, ensure_ascii=False, indent=2))
    return audit


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('source', type=Path)
    parser.add_argument('--output-dir', type=Path, default=ROOT / 'data/hourly_trade')
    args = parser.parse_args()
    try:
        prepare(args.source, args.output_dir)
    except ReviewRequired as exc:
        print(json.dumps({'error':str(exc), 'changes':exc.report}, ensure_ascii=False, indent=2))
        raise SystemExit(2)
