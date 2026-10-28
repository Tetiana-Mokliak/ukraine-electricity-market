"""Monthly Energy Map download. No retries, redirects, or analytical transforms."""
import argparse
import csv
import hashlib
import io
import json
import os
from pathlib import Path
import sys
from datetime import date, datetime, timezone
from urllib.request import Request, build_opener, HTTPRedirectHandler
from urllib.error import HTTPError, URLError

ROOT = Path(__file__).resolve().parents[1]
DATASET = '0f8f9882-1fb2-47c6-81dc-31fbad914f16'
SOURCE_URL = f'https://energy-map.info/uk/datasets/{DATASET}'
DOWNLOAD_URL = f'https://energy-map.info/api/v1/resources/{DATASET}/download/?format=csv&language=uk'
COLUMNS = ['date', 'hour', 'outage_use', 'outage_amount', 'number']


class NoRedirect(HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None


def inspect_csv(payload):
    """Validate transport/schema and derive coverage; do not alter source data."""
    reader = csv.reader(io.StringIO(payload.decode('utf-8-sig')), strict=True)
    if next(reader, None) != COLUMNS:
        raise ValueError('Unexpected CSV columns')
    dates = []
    row_count = missing_dates = formula_hours = 0
    for row in reader:
        if len(row) != len(COLUMNS):
            raise ValueError('Unexpected CSV row width')
        row_count += 1
        formula_hours += row[1].startswith('=')
        if row[0]:
            dates.append(date.fromisoformat(row[0]))
        else:
            missing_dates += 1
    if not dates:
        raise ValueError('Empty dataset')
    return {'data_start_date': min(dates).isoformat(),
            'data_end_date': max(dates).isoformat(), 'row_count': row_count,
            'missing_date_rows': missing_dates, 'formula_hour_rows': formula_hours}


def accept(payload, directory, checked_at):
    coverage = inspect_csv(payload)  # Reject error pages before replacing anything.
    current_path = directory / 'current.json'
    previous = json.loads(current_path.read_text()) if current_path.exists() else {}
    digest = hashlib.sha256(payload).hexdigest()
    snapshot = directory / 'raw' / f'{digest}.csv'
    changed = digest != previous.get('sha256')
    if snapshot.exists() and snapshot.read_bytes() != payload:
        raise ValueError('Stored snapshot does not match its hash')
    snapshot.parent.mkdir(parents=True, exist_ok=True)
    if not snapshot.exists():
        snapshot.write_bytes(payload)
    state = {**previous, 'dataset_id': DATASET, 'source_url': SOURCE_URL,
             'sha256': digest, 'file': f'raw/{digest}.csv',
             'last_checked_at_utc': checked_at, 'last_check_changed': changed,
             'last_changed_at_utc': checked_at if changed else previous.get('last_changed_at_utc'),
             'size_bytes': len(payload), **coverage,
             'preparation_pending': changed or previous.get('preparation_pending', False)}
    temporary = directory / 'current.json.tmp'
    temporary.write_text(json.dumps(state, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
    temporary.replace(current_path)
    return changed


def due(directory, now):
    state_path = directory / 'current.json'
    if not state_path.exists():
        return True
    state = json.loads(state_path.read_text())
    checked = datetime.fromisoformat(state['last_checked_at_utc'])
    return (checked.year, checked.month) < (now.year, now.month)


def download(token):
    request = Request(DOWNLOAD_URL, headers={'Authorization': f'Token {token}'})
    # urllib does not retry HTTP failures here; redirect handler blocks extra GETs.
    with build_opener(NoRedirect()).open(request, timeout=60) as response:
        if response.status != 200:
            raise ValueError('Unexpected HTTP status')
        return response.read()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--from-file', type=Path, help='Offline replay: never calls API')
    parser.add_argument('--data-dir', type=Path, default=ROOT / 'data/energy_map')
    args = parser.parse_args()
    now = datetime.now(timezone.utc)
    if args.from_file:
        payload = args.from_file.read_bytes()
    else:
        if not due(args.data_dir, now):
            print('Already checked this UTC calendar month; no API request.')
            return
        if int(os.environ.get('GITHUB_RUN_ATTEMPT', '1')) > 1:
            raise ValueError('Workflow rerun blocked to protect API quota')
        token = os.environ.get('ENERGY_MAP_TOKEN', '').strip()
        if not token:
            raise ValueError('Missing ENERGY_MAP_TOKEN repository secret')
        payload = download(token)
    changed = accept(payload, args.data_dir, now.isoformat())
    result = 'changed' if changed else 'unchanged'
    print(f'Energy Map source: {result}; preparation status saved.')
    if output := os.environ.get('GITHUB_OUTPUT'):
        with open(output, 'a', encoding='utf-8') as stream:
            stream.write(f'changed={str(changed).lower()}\n')


if __name__ == '__main__':
    try:
        main()
    except (ValueError, OSError, UnicodeError, csv.Error, HTTPError, URLError) as error:
        # Do not print request headers, tokens, or arbitrary server bodies.
        print(f'Energy Map failed ({type(error).__name__}); no automatic retry.', file=sys.stderr)
        sys.exit(1)
