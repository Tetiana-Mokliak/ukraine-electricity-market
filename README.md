# Ukraine Electricity Market

Дослідження місячної динаміки ринку електроенергії України: імпорт/експорт, середньозважені ціни, структура виробництва та споживання, частки ВДЕ.

## Поточний стан

Планування проєкту та перевірка джерела. Автоматичне оновлення даних і Power BI ще не реалізовано.

- У Colab підтверджено завантаження XLSX та знаходження посилання на сторінці НКРЕКП.
- Додано ручний тест GitHub Actions. Результат виконання у GitHub ще потрібно перевірити.
- Розклад запусків вимкнений. Тест не змінює дані репозиторію.

## Запуск тесту

Actions → Test NКРЕКП source → Run workflow.

Тест знаходить файл, перевіряє формат XLSX, читає аркуш Base_opt та перевіряє колонки. Підсумок зберігається як тимчасовий артефакт. Якщо знайдено кілька версій або змінилася структура, тест завершується помилкою; він не вгадує актуальний файл. Правила вибору версій та об’єднання історії будуть визначені до реалізації збирача.

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

This repository is currently at the planning and source-validation stage. A manually triggered GitHub Actions test downloads and validates the source workbook. Scheduled collection, revision handling, and dashboard refresh are not implemented yet.
