"""Order-independent history gate for Energy Map hourly trade; no network."""
import numpy as np
import pandas as pd

COLUMNS = ['date', 'hour', 'energy_system', 'country', 'customs_regime', 'amount']
KEYS = COLUMNS[:-1]
ROUTE = ['energy_system', 'country', 'customs_regime']


class ReviewRequired(ValueError):
    def __init__(self, message, report=None):
        super().__init__(message)
        self.report = report or {'accepted': False, 'reason': message}


def validate_source(frame):
    if list(frame) != COLUMNS or frame.empty:
        raise ReviewRequired('Unknown or empty source structure; expected six Energy Map columns')
    result = frame.copy().reset_index(drop=True)
    if result.isna().any().any():
        raise ReviewRequired('Missing source fields; manual review required')
    for name in COLUMNS[:-1]:
        if not result[name].map(lambda x: isinstance(x, str) and bool(x) and x == x.strip()).all():
            raise ReviewRequired(f'Invalid text field: {name}')
    try:
        dates = pd.to_datetime(result.date, format='%Y-%m-%d', errors='raise')
        result['amount'] = pd.to_numeric(result.amount, errors='raise').astype(float)
    except (ValueError, TypeError) as exc:
        raise ReviewRequired('Invalid date or nonnumeric amount') from exc
    if not dates.dt.strftime('%Y-%m-%d').eq(result.date).all():
        raise ReviewRequired('Dates must use YYYY-MM-DD')
    if not result.hour.str.fullmatch(r'\d{2}:00-\d{2}:00').all():
        raise ReviewRequired('Unknown hourly label format')
    if not np.isfinite(result.amount).all() or result.amount.lt(0).any():
        raise ReviewRequired('Amounts must be finite and nonnegative')
    if not result.customs_regime.isin(['експорт', 'імпорт']).all():
        raise ReviewRequired('Unknown trade direction')
    return result


def history_changes(previous, incoming):
    """Compare multisets of all six fields, retaining repeated identical rows."""
    end = previous.date.max()
    historical = incoming.loc[incoming.date.le(end)]
    old = previous.groupby(COLUMNS, dropna=False).size().rename('old_count')
    new = historical.groupby(COLUMNS, dropna=False).size().rename('new_count')
    delta = pd.concat([old, new], axis=1).fillna(0).astype(int)
    delta['delta'] = delta.new_count - delta.old_count
    changed = delta.loc[delta.delta.ne(0)].reset_index()
    removed = changed.loc[changed.delta.lt(0)]
    added = changed.loc[changed.delta.gt(0)]
    old_keys = set(map(tuple, removed[KEYS].to_numpy()))
    new_keys = set(map(tuple, added[KEYS].to_numpy()))
    return {
        'accepted': changed.empty, 'history_start': previous.date.min(), 'history_end': end,
        'history_rows': len(previous),
        'added_historical_rows': int(added.delta.sum()),
        'removed_historical_rows': int(-removed.delta.sum()),
        'changed_value_keys': len(old_keys & new_keys),
        'details_truncated': len(changed) > 1000,
        'details': changed.head(1000).to_dict('records'),
        'new_rows': int(incoming.date.gt(end).sum()),
    }


def accept_history(previous, incoming):
    """Keep accepted occurrence order for legacy folds, track incoming row links.

    Matching includes value and occurrence number, so reordering the incoming file
    cannot reassign distinct values between two previously accepted autumn slots.
    Identical rows are physically indistinguishable; their multiplicity is checked.
    """
    report = history_changes(previous, incoming)
    if not report['accepted']:
        raise ReviewRequired('Accepted historical records changed; manual review required', report)
    for column in ('energy_system', 'country'):
        if not incoming[column].isin(previous[column].unique()).all():
            raise ReviewRequired(f'New {column}; manual review required')
    known_routes = set(map(tuple, previous[ROUTE].drop_duplicates().to_numpy()))
    if not set(map(tuple, incoming[ROUTE].drop_duplicates().to_numpy())).issubset(known_routes):
        raise ReviewRequired('New route combination; manual review required')
    incoming = incoming.copy()
    incoming['source_row'] = range(len(incoming))
    hist = incoming.loc[incoming.date.le(previous.date.max())].copy()
    hist['_occurrence'] = hist.groupby(COLUMNS, sort=False).cumcount()
    old = previous.copy()
    old['_occurrence'] = old.groupby(COLUMNS, sort=False).cumcount()
    old['_accepted_order'] = range(len(old))
    hist = hist.merge(old[COLUMNS + ['_occurrence', '_accepted_order']],
                      on=COLUMNS + ['_occurrence'], validate='one_to_one')
    hist = hist.sort_values('_accepted_order').drop(columns=['_occurrence', '_accepted_order'])
    extra = incoming.loc[incoming.date.gt(previous.date.max())]
    return pd.concat([hist, extra], ignore_index=True), report
