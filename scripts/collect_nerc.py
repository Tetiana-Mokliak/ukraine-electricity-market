"""Controlled collector: immutable snapshots, hash deduplication, atomic pointer."""
import csv
import hashlib
import json
import os
import re
import tempfile
import time
from datetime import datetime, timezone
from collections import defaultdict
from decimal import Decimal
from html.parser import HTMLParser
from io import BytesIO
from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.parse import unquote, urljoin, urlsplit
from urllib.request import urlopen
from zipfile import ZipFile, is_zipfile
from scripts.updates import COLUMNS, normalize, plan_update
from scripts.corrections import apply_reviewed_corrections, number, COUNTRIES

PAGE_URL = ('https://www.nerc.gov.ua/monitoring-rinku-elektrichnoyi-energiyi/'
            'indykatory-ta-pokaznyky-monitorynhu-rynku-elektrychnoi-enerhii-'
            'shcho-pidliahaiut-rozkryttiu-pid-chas-dii-voiennoho-stanu/vidkryti-dani')

class Links(HTMLParser):
    def __init__(self):
        super().__init__(); self.urls = []
    def handle_starttag(self, tag, attrs):
        href = dict(attrs).get('href', '')
        if tag == 'a':
            url = urljoin(PAGE_URL, href)
            if (urlsplit(url).hostname == 'www.nerc.gov.ua'
                and urlsplit(url).path.lower().endswith('.xlsx')
                and 'open_data_during_the_war' in unquote(url).lower()):
                self.urls.append(url)

def select_latest(html):
    parser = Links(); parser.feed(html)
    candidates = []
    for url in sorted(set(parser.urls)):
        dates = re.findall(r'(?<!\d)(\d{2}\.\d{2}\.\d{4})(?!\d)', unquote(urlsplit(url).path))
        if len(dates) != 1:
            raise ValueError('Unknown file date; manual review required')
        candidates.append((datetime.strptime(dates[0], '%d.%m.%Y').date(), url))
    if not candidates:
        raise ValueError('No matching source files')
    latest = max(d for d, _ in candidates)
    winners = [u for d, u in candidates if d == latest]
    if len(winners) != 1:
        raise ValueError('Multiple files with latest date; manual review required')
    return winners[0], latest.isoformat()

def download(url, opener=urlopen, sleep=time.sleep):
    for attempt in range(3):
        try:
            with opener(url, timeout=30) as response:
                final = response.geturl()
                if urlsplit(final).hostname != 'www.nerc.gov.ua':
                    raise ValueError('Unexpected redirect destination')
                payload = response.read(20_000_001)
                if len(payload) > 20_000_000:
                    raise ValueError('Source exceeds 20 MB limit')
                return payload
        except HTTPError as error:
            if error.code not in (429, 500, 502, 503, 504) or attempt == 2:
                raise
        except (URLError, TimeoutError):
            if attempt == 2: raise
        sleep(2 ** attempt)

def read_workbook(payload, filename_date):
    import pandas as pd
    if not is_zipfile(BytesIO(payload)):
        raise ValueError('Not an XLSX file')
    with ZipFile(BytesIO(payload)) as archive:
        if 'xl/workbook.xml' not in archive.namelist():
            raise ValueError('Not an Excel workbook')
        if sum(i.file_size for i in archive.infolist()) > 100_000_000:
            raise ValueError('Workbook decompressed size exceeds limit')
    header = pd.read_excel(BytesIO(payload), sheet_name='Base_opt', header=None, nrows=3)
    declared = pd.to_datetime(header.iloc[1, 7], errors='raise').date().isoformat()
    if declared != filename_date:
        raise ValueError('Filename date and workbook update date disagree')
    frame = pd.read_excel(BytesIO(payload), sheet_name='Base_opt', header=2)
    columns = [c for c in frame.columns if not str(c).startswith('Unnamed')]
    if columns != list(COLUMNS): raise ValueError('Unexpected workbook columns')
    rows = frame[columns].astype(object).where(pd.notna(frame[columns]), None).to_dict('records')
    return rows

def atomic_json(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    descriptor, name = tempfile.mkstemp(dir=path.parent, prefix='.pending-')
    try:
        with os.fdopen(descriptor, 'w', encoding='utf-8') as f:
            json.dump(value, f, ensure_ascii=False, indent=2, allow_nan=False)
            f.flush(); os.fsync(f.fileno())
        os.replace(name, path)
    finally:
        if os.path.exists(name): os.unlink(name)


def check_trade_totals(rows):
    """Block new arithmetic defects; report missing countries without imputation."""
    groups = defaultdict(list)
    for row in rows:
        if row['Показник'] in ('Імпорт', 'Експорт'):
            groups[row['Рік'], row['Місяць'], row['Показник']].append(row)
    warnings = []
    for (year, month, indicator), group in groups.items():
        if month == 'не застосовується':
            raise ValueError('Unexpected quarterly trade grain; manual review required')
        if any(r['Одиниці виміру'] != 'тис. МВт×год' for r in group):
            raise ValueError('Trade units changed; manual review required')
        totals = [r for r in group if r['Категорія'] == 'усього']
        details = [r for r in group if r['Категорія'] != 'усього']
        if any(number(r['Значення']) < 0 for r in group):
            raise ValueError('Negative trade value; manual review required')
        if (len(totals) != 1 or sum((number(r['Значення']) for r in details), Decimal(0))
                != number(totals[0]['Значення'])):
            raise ValueError(f'Trade total does not reconcile exactly: {year} {month} {indicator}')
        if indicator == 'Експорт':
            missing = sorted(COUNTRIES - {r['Категорія'] for r in details})
            if missing:
                warnings.append(dict(year=year, month=month, indicator=indicator,
                                     missing_categories=missing,
                                     basis='Five-country analytical reference; absence does not establish zero or source error'))
    return dict(trade_groups_checked=len(groups), exact_trade_totals=True,
                export_coverage_warnings=warnings)

def accept_payload(root, url, version, payload, reader=read_workbook):
    root = Path(root)
    pointer = root / 'current.json'
    old = json.loads(pointer.read_text(encoding='utf-8')) if pointer.exists() else None
    digest = hashlib.sha256(payload).hexdigest()
    if old and version < old['version_date']:
        raise ValueError('Source version older than current version')
    if old and digest == old['sha256']:
        return {'status': 'unchanged', 'sha256': digest}
    if (root / 'snapshots' / digest).exists():
        raise ValueError('Previously archived source reappeared; manual review required')
    # Preserve source even when validation rejects it. This is not published data.
    raw = root / 'raw' / digest
    raw.mkdir(parents=True, exist_ok=True)
    (raw / 'source.xlsx').write_bytes(payload)
    incoming, corrections = apply_reviewed_corrections(reader(payload, version))
    atomic_json(raw / 'corrections.json', corrections)
    incoming = list(normalize(incoming).values())
    quality = check_trade_totals(incoming)
    previous = []
    if old:
        previous = json.loads((root / old['snapshot'] / 'rows.json').read_text(encoding='utf-8'))
    update = plan_update(previous, incoming)
    if update['requires_review']:
        # No current data or pointer changes; do not silently infer partial publication.
        raise ValueError(f"Missing {len(update['missing'])} prior keys; manual review required")
    relative = Path('snapshots') / digest
    snapshot = root / relative
    snapshot.mkdir(parents=True, exist_ok=True)
    (snapshot / 'source.xlsx').write_bytes(payload)
    atomic_json(snapshot / 'rows.json', update['rows'])
    with (snapshot / 'data.csv').open('w', encoding='utf-8-sig', newline='') as f:
        writer = csv.DictWriter(f, fieldnames=COLUMNS)
        writer.writeheader(); writer.writerows(update['rows'])
    audit = {k: v for k, v in update.items() if k != 'rows'}
    audit.update({'status': 'updated' if update['changed'] else 'file_only_change',
                  'quality': quality,
                  'corrections': corrections,
                  'source_url': url, 'version_date': version, 'sha256': digest,
                  'previous_sha256': old['sha256'] if old else None,
                  'retrieved_at': datetime.now(timezone.utc).isoformat()})
    atomic_json(snapshot / 'audit.json', audit)
    atomic_json(pointer, {'snapshot': relative.as_posix(), 'sha256': digest,
                          'version_date': version, 'source_url': url})
    return audit

def main():
    try:
        url, version = select_latest(download(PAGE_URL).decode('utf-8'))
        result = accept_payload('data', url, version, download(url))
    except Exception as error:
        atomic_json(Path('outputs/collection_failure.json'),
                    {'status': 'rejected', 'error': str(error),
                     'retrieved_at': datetime.now(timezone.utc).isoformat()})
        raise
    atomic_json(Path('outputs/collection_result.json'), result)
    summary = {k: result[k] for k in ('status', 'sha256', 'version_date') if k in result}
    for key in ('added', 'revised', 'missing'):
        if key in result:
            summary[key] = len(result[key])
    print(json.dumps(summary, ensure_ascii=False, indent=2))

if __name__ == '__main__': main()
