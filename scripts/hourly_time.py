"""Shared elapsed-hour calendar. UTC is the join key; Kyiv labels are display only."""
from collections import Counter, defaultdict, deque

import pandas as pd

TIMEZONE = 'Europe/Kyiv'


def hourly_calendar(day):
    day = pd.Timestamp(day).normalize()
    start = day.tz_localize(TIMEZONE).tz_convert('UTC')
    end = (day + pd.Timedelta(days=1)).tz_localize(TIMEZONE).tz_convert('UTC')
    utc = pd.date_range(start, end, freq='h', inclusive='left')
    local = utc.tz_convert(TIMEZONE)
    local_end = (utc + pd.Timedelta(hours=1)).tz_convert(TIMEZONE)
    return pd.DataFrame({
        'start_utc': utc, 'end_utc': utc + pd.Timedelta(hours=1),
        'start_local': local, 'end_local': local_end,
        'hour': local.strftime('%H:%M') + '-' + local_end.strftime('%H:%M'),
        'legacy_hour': local.strftime('%H:%M') + '-' +
            (local.tz_localize(None) + pd.Timedelta(hours=1)).strftime('%H:%M'),
    })


def normalize_hours(frame, group_columns=(), strict=False, allow_legacy_fall_partial=False):
    """Assign only complete, recognized daily calendars; never invent missing slots.

    Repeated legacy labels are assigned in source occurrence order. This is an
    explicit ordering assumption, recorded in time_status, not source confirmation.
    """
    result = frame.copy().reset_index(drop=True)
    if 'hour_original' not in result:
        result['hour_original'] = result['hour']
    result['time_status'] = 'unresolved_calendar'
    result['calendar_complete'] = False
    for column in ('start_utc', 'end_utc'):
        result[column] = pd.Series(pd.NaT, index=result.index, dtype='datetime64[ns, UTC]')
    calendars = {}
    assignments = []
    for _, group in result.groupby(['date', *group_columns], sort=False, dropna=False):
        day = group['date'].iloc[0]
        if day not in calendars:
            slots = hourly_calendar(day)
            calendars[day] = (slots, slots.to_dict('records'))
        slots, records = calendars[day]
        labels = list(group['hour'])
        counts = Counter(labels)
        field = next((name for name in ('hour', 'legacy_hour')
                      if counts == Counter(slots[name])), None)
        if field is None:
            # Only the exact reviewed legacy fall pattern: all 24 ordinary
            # labels present once. The single 03 label cannot identify a fold.
            ordinary = Counter(f'{h:02d}:00-{(h + 1) % 24:02d}:00' for h in range(24))
            if allow_legacy_fall_partial and len(slots) == 25 and counts == ordinary:
                by_label = {r['hour']: r for r in records
                            if r['hour'] not in ('03:00-03:00', '03:00-04:00')}
                for index, label in zip(group.index, labels):
                    if label == '03:00-04:00':
                        result.at[index, 'time_status'] = 'ambiguous_fall_single'
                    else:
                        assignments.append((index, by_label[label], 'calendar_matched_partial_day'))
                continue
            if strict:
                raise ValueError(f'Unresolved hourly calendar: {group["date"].iloc[0]}')
            continue
        queues = defaultdict(deque)
        for slot in records:
            queues[slot[field]].append(slot)
        result.loc[group.index, 'calendar_complete'] = True
        for index, label in zip(group.index, labels):
            slot = queues[label].popleft()
            assignments.append((index, slot,
                                'source_order_assumption' if counts[label] > 1 else 'calendar_matched'))
    if assignments:
        indices = [item[0] for item in assignments]
        result.loc[indices, 'hour'] = [item[1]['hour'] for item in assignments]
        result.loc[indices, 'time_status'] = [item[2] for item in assignments]
        for column in ('start_utc', 'end_utc'):
            result.loc[indices, column] = pd.array([item[1][column] for item in assignments],
                                                   dtype='datetime64[ns, UTC]')
    for name in ('start', 'end'):
        result[name + '_local'] = result[name + '_utc'].dt.tz_convert(TIMEZONE)
    return result


def csv_ready(frame):
    """Keep offsets and full timestamps: date_format must not truncate time fields."""
    result = frame.copy()
    result['date'] = pd.to_datetime(result['date']).dt.strftime('%Y-%m-%d')
    for column in ('start_utc', 'end_utc', 'start_local', 'end_local'):
        result[column] = result[column].map(lambda value: value.isoformat() if pd.notna(value) else '')
    return result
