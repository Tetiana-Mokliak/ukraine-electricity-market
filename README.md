# Ukraine Electricity Market

Дослідження місячної динаміки ринку електроенергії України: імпорт/експорт, середньозважені ціни, структура виробництва та споживання, частки ВДЕ.

## Поточний стан

Реалізовано контрольований ручний збір: пошук найновішого XLSX, архів оригіналу, погоджені адресні реконструкції, перевірка унікальності та порівняння версій. Розклад і автоматичний запис даних з Actions ще не ввімкнені; Power BI не підключений.

16.10.2026 успішно виконано повний ручний збір файлу від 01.09.2026. Прийнято 4566 рядків; усі 162 місячні підсумки імпорту/експорту точно узгоджуються. Перевірено аудит, оригінал і повторне приймання незміненого файлу. Пройшли 48 локальних тестів.

Поточну версію визначає [`data/current.json`](data/current.json); CSV і аудит розміщені у відповідному `data/snapshots/<sha256>/`. Оригінал також зберігається в `data/raw/<sha256>/`.

- [Правила й обмеження реконструкцій](docs/corrections.md) — це припущення проєкту, а не офіційні виправлення НКРЕКП.
- [Підсумок перевірки та ручного збору](docs/collector_status.md).
- [Зовнішня перевірка серпня 2022](docs/diagnostics/2026-10-16-august-2022.md).
- [Фінальна діагностика всього джерела](docs/diagnostics/2026-10-16-final.json).

Відсутні записи країн не замінено нулями. Точні суми не доводять повноти розподілу чи незалежної достовірності джерела. Історичні діагностичні файли описують стан на відповідному етапі; актуальний стан наведено вище.

## Запуск

Ручний збір: `python -m scripts.collect_nerc`.

Тести: `python -m unittest discover -s tests -v`.

Actions → Test NКРЕКП source → Run workflow — окремий тест доступності та структури джерела, який не публікує робочі дані. Локальний збирач обирає найновішу дату назви файлу; за неоднозначності або невідповідності структури відхиляє результат. Попередня прийнята версія зберігається.

## Джерело та обмеження

Джерело: [НКРЕКП — відкриті дані оптового ринку](https://www.nerc.gov.ua/monitoring-rinku-elektrichnoyi-energiyi/indykatory-ta-pokaznyky-monitorynhu-rynku-elektrychnoi-enerhii-shcho-pidliahaiut-rozkryttiu-pid-chas-dii-voiennoho-stanu/vidkryti-dani).

У перевіреному файлі від 01.09.2026:
- структура виробництва і споживання наведена у відсотках, а не абсолютних обсягах;
- місячні ряди структури закінчуються березнем 2026;
- є також квартальні показники: зерно даних потрібно враховувати окремо;
- первинні значення можуть переглядатися НКРЕКП;
- місячні імпорт/експорт не встановлюють одночасність експорту та відключень.

## English

Monthly Ukrainian electricity market research covering trade flows, prices, generation and consumption mix, and renewable energy shares.

Controlled manual collection, revision comparison, source archiving and explicitly reviewed analytical corrections are implemented. On 16 October 2026, a complete manual run accepted 4,566 observations from the workbook dated 1 September 2026; all 162 monthly trade totals reconcile exactly and 48 local tests pass. Scheduled collection and automatic repository writes are not enabled. Missing country records are not imputed as zero; corrections are project assumptions, not official NERC amendments.
