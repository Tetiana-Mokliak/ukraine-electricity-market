"""Prepare monthly Power BI tables from the accepted snapshot. No source repairs here."""
import json
from pathlib import Path

import numpy as np
import pandas as pd

MONTHS = dict(zip(
    ['Січень', 'Лютий', 'Березень', 'Квітень', 'Травень', 'Червень',
     'Липень', 'Серпень', 'Вересень', 'Жовтень', 'Листопад', 'Грудень'],
    range(1, 13),
))
RENEWABLE_MIX = 'Структура ВДЕ (по відношення до обсягу виробленої електричної енергії з ВДЕ)'
RENEWABLE_SHARE = 'Частка ВДЕ у загальній структурі виробленої електричної енергії'
UNITS = {
    'Імпорт': 'тис. МВт×год', 'Експорт': 'тис. МВт×год',
    'Обсяг': 'тис. МВт×год', 'Середньозважена ціна': 'грн/МВт∙год',
    'Обсяг придбаної електричної енергії за "зеленим" тарифом': 'тис. МВт×год',
    'Середньозважений "зелений" тариф': 'грн/кВт∙год',
    'Структура виробництва': '%', 'Структура споживання': '%',
    RENEWABLE_MIX: '%', RENEWABLE_SHARE: '%',
}
# Percentage points: covers observed source precision, not trade reconciliation.
SHARE_ATOL = 1e-6


def prepare(df):
    """Build and validate everything before writing any output."""
    if not set(UNITS).issubset(set(df['Показник'])):
        raise ValueError('Missing required monthly indicators')
    df = df[df['Показник'].isin(UNITS)].copy()
    if df.isna().any().any():
        raise ValueError('Missing source values')
    if not df['Одиниці виміру'].eq(df['Показник'].map(UNITS)).all():
        raise ValueError('Unexpected units')
    month_number = df['Місяць'].map(MONTHS)
    if month_number.isna().any():
        raise ValueError('Unknown month')
    df['Дата'] = pd.to_datetime(dict(year=df['Рік'], month=month_number, day=1))
    if not np.isfinite(df['Значення']).all():
        raise ValueError('Non-finite source values')
    if df.duplicated(['Дата', 'Показник', 'Категорія']).any():
        raise ValueError('Duplicate monthly keys')
    trade = df[df['Показник'].isin(['Імпорт', 'Експорт'])].copy()
    trade_totals = trade[trade['Категорія'] == 'усього'].copy()
    trade_countries = trade[trade['Категорія'] != 'усього'].copy()
    trade_countries = trade_countries[['Дата', 'Показник', 'Категорія', 'Значення']].copy()
    trade_countries = trade_countries.rename(columns={'Показник': 'Напрямок', 'Категорія': 'Країна', 'Значення': 'Обсяг_тис_МВт·год'})
    country_counts = trade_countries.groupby(['Дата', 'Напрямок'])['Країна'].nunique().reset_index(name='Кількість_країн_у_джерелі')
    trade_coverage = trade_totals[['Дата', 'Показник', 'Значення']].rename(columns={'Показник': 'Напрямок'}).copy()
    trade_coverage = trade_coverage.merge(country_counts, on=['Дата', 'Напрямок'], how='left', validate='one_to_one')
    trade_coverage['Кількість_країн_у_джерелі'] = trade_coverage['Кількість_країн_у_джерелі'].fillna(0).astype('int64')
    trade_coverage['Підтверджений_нульовий_підсумок'] = trade_coverage['Значення'] == 0
    trade_coverage = trade_coverage.drop(columns=['Значення'])
    market = df[df['Показник'].isin(['Середньозважена ціна', 'Обсяг'])].copy()
    market_wide = market.pivot(index=['Дата', 'Категорія'], columns='Показник', values='Значення').reset_index()
    market_wide = market_wide.rename(columns={'Категорія': 'Сегмент_ринку', 'Обсяг': 'Обсяг_тис_МВт·год', 'Середньозважена ціна': 'Ціна_грн_МВт·год'})
    green = df[df['Показник'].isin(['Обсяг придбаної електричної енергії за "зеленим" тарифом', 'Середньозважений "зелений" тариф'])].copy()
    green_wide = green.pivot(index=['Дата', 'Категорія'], columns='Показник', values='Значення').reset_index()
    green_wide = green_wide.rename(columns={'Категорія': 'Група_виробників', 'Обсяг придбаної електричної енергії за "зеленим" тарифом': 'Придбаний_обсяг_тис_МВт·год', 'Середньозважений "зелений" тариф': 'Тариф_грн_кВт·год'})
    generation = df[df['Показник'] == 'Структура виробництва'].copy()
    generation = generation[['Дата', 'Категорія', 'Значення']].copy().rename(columns={'Категорія': 'Тип_генерації', 'Значення': 'Частка_виробництва_%'})
    consumption = df[df['Показник'] == 'Структура споживання'].copy()
    consumption = consumption[['Дата', 'Категорія', 'Значення']].copy().rename(columns={'Категорія': 'Категорія_споживання', 'Значення': 'Частка_споживання_%'})
    renewables = df[df['Показник'].isin(['Структура ВДЕ (по відношення до обсягу виробленої електричної енергії з ВДЕ)', 'Частка ВДЕ у загальній структурі виробленої електричної енергії'])].copy()
    renewables_wide = renewables.pivot(index=['Дата', 'Категорія'], columns='Показник', values='Значення').reset_index()
    renewables_wide = renewables_wide.rename(columns={'Категорія': 'Тип_ВДЕ', 'Структура ВДЕ (по відношення до обсягу виробленої електричної енергії з ВДЕ)': 'Частка_серед_ВДЕ_%', 'Частка ВДЕ у загальній структурі виробленої електричної енергії': 'Частка_в_загальному_виробництві_%'}).copy()

    calendar = pd.DataFrame({'Дата': pd.date_range(df['Дата'].min(), df['Дата'].max(), freq='MS')})
    calendar['Рік'] = calendar['Дата'].dt.year
    calendar['Номер_місяця'] = calendar['Дата'].dt.month
    calendar['Місяць'] = calendar['Номер_місяця'].map({v: k for k, v in MONTHS.items()})
    calendar['Квартал'] = calendar['Дата'].dt.quarter
    tables = {
        'trade_countries': trade_countries, 'trade_coverage': trade_coverage,
        'market': market_wide, 'green': green_wide,
        'generation': generation, 'consumption': consumption,
        'renewables': renewables_wide, 'calendar': calendar,
    }
    for name, table in tables.items():
        if table.empty or table.isna().any().any():
            raise ValueError(f'{name}: empty table or missing values')
        table.columns.name = None
        table.sort_values(list(table.columns[:2]), inplace=True, ignore_index=True)
    for table, column in [
        (generation, 'Частка_виробництва_%'),
        (consumption, 'Частка_споживання_%'),
        (renewables_wide, 'Частка_серед_ВДЕ_%'),
    ]:
        if not table[column].between(0, 100).all():
            raise ValueError(f'{column}: values outside 0–100')
        if not np.allclose(table.groupby('Дата')[column].sum(), 100, atol=SHARE_ATOL, rtol=0):
            raise ValueError(f'{column}: monthly shares do not sum to 100')
    if not renewables_wide['Частка_в_загальному_виробництві_%'].between(0, 100).all():
        raise ValueError('Renewable shares outside 0–100')
    detailed = renewables_wide.groupby('Дата')['Частка_в_загальному_виробництві_%'].sum()
    total = generation[generation['Тип_генерації'].eq('ВДЕ')].set_index('Дата')['Частка_виробництва_%']
    detailed, total = detailed.align(total)
    if detailed.isna().any() or total.isna().any() or not np.allclose(detailed, total, atol=SHARE_ATOL, rtol=0):
        raise ValueError('Renewable totals disagree between tables')
    return tables


def main():
    root = Path(__file__).resolve().parent.parent
    data = root / 'data'
    current = json.loads((data / 'current.json').read_text(encoding='utf-8'))
    tables = prepare(pd.read_csv(data / current['snapshot'] / 'data.csv'))
    output = data / 'power_bi'
    output.mkdir(exist_ok=True)
    # Stable paths; deterministic bytes mean unchanged tables create no git diff.
    for name, table in tables.items():
        table.to_csv(output / f'{name}.csv', index=False, encoding='utf-8-sig', date_format='%Y-%m-%d')
    print(json.dumps({name: len(table) for name, table in tables.items()}))


if __name__ == '__main__':
    main()
