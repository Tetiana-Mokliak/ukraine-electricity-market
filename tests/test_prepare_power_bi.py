"""Regression checks against the accepted source and unsafe input changes."""
import json
from pathlib import Path
import unittest

import pandas as pd

from scripts.prepare_power_bi import prepare


class PreparationTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        data = Path(__file__).resolve().parent.parent / 'data'
        pointer = json.loads((data / 'current.json').read_text())
        cls.df = pd.read_csv(data / pointer['snapshot'] / 'data.csv')

    def test_country_gaps_are_not_invented(self):
        tables = prepare(self.df)
        coverage = tables['trade_coverage']
        gaps = coverage[coverage['Кількість_країн_у_джерелі'].eq(0)]
        self.assertFalse(gaps.empty)
        for date, direction in gaps[['Дата', 'Напрямок']].itertuples(index=False, name=None):
            countries = tables['trade_countries']
            self.assertFalse((countries['Дата'].eq(date) & countries['Напрямок'].eq(direction)).any())
        self.assertNotIn('усього', tables['trade_countries']['Країна'].tolist())

    def test_rejects_duplicates(self):
        row = self.df[self.df['Показник'].eq('Імпорт')].iloc[[0]]
        with self.assertRaisesRegex(ValueError, 'Duplicate'):
            prepare(pd.concat([self.df, row]))

    def test_rejects_unit_drift(self):
        bad = self.df.copy()
        bad.loc[bad['Показник'].eq('Середньозважена ціна'), 'Одиниці виміру'] = 'грн/кВт∙год'
        with self.assertRaisesRegex(ValueError, 'units'):
            prepare(bad)

    def test_rejects_broken_shares(self):
        bad = self.df.copy()
        index = bad[bad['Показник'].eq('Структура виробництва')].index[0]
        bad.loc[index, 'Значення'] += 0.001
        with self.assertRaises(ValueError):
            prepare(bad)
