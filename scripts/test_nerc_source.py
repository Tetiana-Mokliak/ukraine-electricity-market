"""Read-only NКРЕКП source test. Does not update or merge project data."""
from html.parser import HTMLParser
from urllib.request import urlopen
from urllib.parse import urljoin, urlsplit, unquote
from io import BytesIO
from pathlib import Path
from zipfile import is_zipfile, ZipFile
import json
import pandas as pd

PAGE_URL = (
    "https://www.nerc.gov.ua/monitoring-rinku-elektrichnoyi-energiyi/"
    "indykatory-ta-pokaznyky-monitorynhu-rynku-elektrychnoi-enerhii-"
    "shcho-pidliahaiut-rozkryttiu-pid-chas-dii-voiennoho-stanu/vidkryti-dani"
)

class Links(HTMLParser):
    def __init__(self):
        super().__init__()
        self.urls = []
    def handle_starttag(self, tag, attrs):
        href = dict(attrs).get("href", "")
        if tag == "a" and urlsplit(href).path.lower().endswith(".xlsx"):
            url = urljoin(PAGE_URL, href)
            if (urlsplit(url).hostname == "www.nerc.gov.ua"
                and "open_data_during_the_war" in unquote(url).lower()):
                self.urls.append(url)

def main():
    with urlopen(PAGE_URL, timeout=30) as response:
        parser = Links()
        parser.feed(response.read().decode("utf-8"))
    urls = sorted(set(parser.urls))
    print("Matching files:", urls)
    if len(urls) != 1:
        raise ValueError(
            f"Expected one source file, found {len(urls)}. "
            "Review source selection; no file will be chosen silently."
        )
    with urlopen(urls[0], timeout=30) as response:
        data = response.read()
        print("HTTP:", response.status)
    if not is_zipfile(BytesIO(data)):
        raise ValueError("Response is not an XLSX archive")
    with ZipFile(BytesIO(data)) as archive:
        if "xl/workbook.xml" not in archive.namelist():
            raise ValueError("Response is not an Excel workbook")
    frame = pd.read_excel(BytesIO(data), sheet_name="Base_opt", header=2)
    expected = ["Рік", "Квартал", "Місяць", "Показник",
                "Категорія", "Одиниці виміру", "Значення"]
    actual = [c for c in frame.columns if not str(c).startswith("Unnamed")]
    if actual != expected:
        raise ValueError(f"Unexpected columns: {actual}")
    frame = frame[expected]
    if frame.empty:
        raise ValueError("Source table is empty")
    summary = {"source_url": urls[0], "bytes": len(data),
               "rows": len(frame), "columns": actual}
    output = Path("outputs")
    output.mkdir(exist_ok=True)
    (output / "source_test.json").write_text(
        json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(summary, ensure_ascii=False, indent=2))
    print("Source test passed. No production data changed.")

if __name__ == "__main__":
    main()
