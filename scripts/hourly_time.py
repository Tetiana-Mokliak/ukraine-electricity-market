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


def normalize_hours(frame, group_columns=(), strict=False):
    """Assign only complete, recognized daily calendars; never invent missing slots.

    Repeated legacy labels are assigned in source occurrence order. This is an
    explicit ordering assumption, recorded in time_status, not source confirmation.
    """
    result = frame.copy().reset_index(drop=True)
    if 'hour_original' not in result:
        result['hour_original'] = result['hour']
    result['time_status'] = 'unresolved_calendar'
    for column in ('start_utc', 'end_utc'):
        result[column] = pd.Series(pd.NaT, index=result.index, dtype='datetime64[ns, UTC]')
    for _, group in result.groupby(['date', *group_columns], sort=False, dropna=False):
        slots = hourly_calendar(group['date'].iloc[0])
        labels = list(group['hour'])
        counts = Counter(labels)
        field = next((name for name in ('hour', 'legacy_hour')
                      if counts == Counter(slots[name])), None)
        if field is None:
            if strict:
                raise ValueError(f'Unresolved hourly calendar: {group["date"].iloc[0]}')
            continue
        queues = defaultdict(deque)
        for slot in slots.to_dict('records'):
            queues[slot[field]].append(slot)
        for index, label in zip(group.index, labels):
            slot = queues[label].popleft()
            result.at[index, 'hour'] = slot['hour']
            for column in ('start_utc', 'end_utc'):
                result.at[index, column] = slot[column]
            result.at[index, 'time_status'] = (
                'source_order_assumption' if counts[label] > 1 else 'calendar_matched')
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
