"""Private, offline ENTSO-E reconciliation helpers. No API calls or substitutions."""
import xml.etree.ElementTree as ET

import numpy as np
import pandas as pd

from scripts.hourly_time import TIMEZONE

ROUTE_KEYS = ['energy_system', 'country', 'customs_regime']


def read_hourly_xml(path):
    """Expand A03 changes within each Period, preserving absent periods as absent."""
    root = ET.parse(path).getroot()
    for element in root.iter():
        element.tag = element.tag.rsplit('}', 1)[-1]
    series = root.findall('.//TimeSeries')
    if len(series) != 1:
        raise ValueError('Expected exactly one reviewed route/time series')
    ts = series[0]
    if ts.findtext('curveType') not in ('A01', 'A03'):
        raise ValueError('Unsupported curve type')
    if ts.findtext('quantity_Measure_Unit.name') != 'MAW':
        raise ValueError('Expected ENTSO-E MW unit MAW')
    frames = []
    for period in ts.findall('Period'):
        if period.findtext('resolution') != 'PT60M':
            raise ValueError('Only hourly resolution has been reviewed')
        start = pd.Timestamp(period.findtext('timeInterval/start'))
        end = pd.Timestamp(period.findtext('timeInterval/end'))
        if start.tzinfo is None or end.tzinfo is None or end <= start:
            raise ValueError('Invalid UTC period boundaries')
        if (end - start) % pd.Timedelta(hours=1):
            raise ValueError('Period does not contain whole elapsed hours')
        utc = pd.date_range(start.tz_convert('UTC'), end.tz_convert('UTC'), freq='h', inclusive='left')
        points = {}
        for point in period.findall('Point'):
            position = int(point.findtext('position'))
            value = float(point.findtext('quantity'))
            if position in points or not 1 <= position <= len(utc) or not np.isfinite(value) or value < 0:
                raise ValueError('Invalid or duplicate point')
            points[position] = value
        values = pd.Series(points, dtype=float).reindex(range(1, len(utc) + 1))
        if ts.findtext('curveType') == 'A03':
            values = values.ffill()  # No backfill; reset at each Period.
        frames.append(pd.DataFrame({'start_utc': utc, 'entsoe_value': values.to_numpy()}))
    if not frames:
        raise ValueError('No periods in response')
    result = pd.concat(frames, ignore_index=True).sort_values('start_utc')
    if result.start_utc.duplicated().any():
        raise ValueError('Overlapping periods')
    result['end_utc'] = result.start_utc + pd.Timedelta(hours=1)
    result['start_local'] = result.start_utc.dt.tz_convert(TIMEZONE)
    result['end_local'] = result.end_utc.dt.tz_convert(TIMEZONE)
    result['date'] = result.start_local.dt.strftime('%Y-%m-%d')
    result['hour'] = result.start_local.dt.strftime('%H:%M') + '-' + result.end_local.dt.strftime('%H:%M')
    return result


def compare_hourly(energy_map, entsoe, *, atol=1e-6):
    """Both inputs must cover the intended routes/window; return differences + unresolved rows.

    Add explicit ROUTE_KEYS to each XML result before concatenating routes.
    Date/hour text is never used as the join key.
    """
    left, right = energy_map.copy(), entsoe.copy()
    for frame in (left, right):
        frame['start_utc'] = pd.to_datetime(frame['start_utc'], utc=True)
    unresolved = left.loc[left.start_utc.isna()].copy()
    left = left.loc[left.start_utc.notna()]
    keys = [*ROUTE_KEYS, 'start_utc']
    check = left.merge(right[keys + ['entsoe_value']], on=keys, how='outer',
                       validate='one_to_one', indicator=True)
    check['difference'] = check['amount'] - check['entsoe_value']
    mismatch = (check['_merge'].ne('both') | check[['amount', 'entsoe_value']].isna().any(axis=1)
                | ~np.isclose(check['amount'], check['entsoe_value'], atol=atol, rtol=0))
    return check.loc[mismatch].copy(), unresolved
