import hashlib
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

import pandas as pd

from scripts import prepare_hourly_trade as prep
from scripts.hourly_time import hourly_calendar
from scripts.hourly_trade_updates import COLUMNS, ReviewRequired, history_changes, validate_source


class HourlyTradeUpdateTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.output = self.root / 'data'
        self.source = self.root / 'source.csv'
        base = {'energy_system':'ОЕС України','country':'Польща','customs_regime':'експорт'}
        rows = []
        for day in ('2021-10-30','2021-10-31'):
            for i, hour in enumerate(hourly_calendar(day).legacy_hour):
                rows.append(dict(base,date=day,hour=hour,amount=float(i+1)))
        rows.insert(4, dict(base,date='2021-10-30',hour='03:00-04:00',amount=0.0))
        self.raw = pd.DataFrame(rows)[COLUMNS]
        self.raw.to_csv(self.source,index=False)
        self.rulepath = self.root / 'rules.json'
        self.rulepath.write_text(json.dumps({'rules':[dict(base,date='2021-10-30',hour='03:00-04:00',
            expected_day_rows=25,expected_label_rows=2,reason='reviewed',decision_basis='author')]}))
        self.patchers = [patch.object(prep,'RULES_PATH',self.rulepath),
                         patch.object(prep,'REVIEWED_SHA256',hashlib.sha256(self.source.read_bytes()).hexdigest())]
        for p in self.patchers:
            p.start()
            self.addCleanup(p.stop)

    def initial(self):
        return prep.prepare(self.source,self.output)

    def state(self):
        return json.loads((self.output/'current.json').read_text())

    def table(self):
        return pd.read_csv(self.output/self.state()['snapshot']/'trade.csv.gz')

    def future(self,day='2021-11-01'):
        base=self.raw.iloc[0].to_dict()
        return pd.DataFrame([dict(base,date=day,hour=h,amount=2.0) for h in hourly_calendar(day).hour])[COLUMNS]

    def test_unchanged_is_identical_and_reordered_history_keeps_fold_values(self):
        audit=self.initial()
        state_before=(self.output/'current.json').read_bytes()
        table_before=self.table()
        self.assertEqual(prep.prepare(self.source,self.output),audit)
        self.assertEqual((self.output/'current.json').read_bytes(),state_before)
        self.raw.sample(frac=1,random_state=11).to_csv(self.source,index=False)
        prep.prepare(self.source,self.output)
        after=self.table()
        columns=['date','hour','amount','start_utc','end_utc','time_status']
        pd.testing.assert_frame_equal(table_before[columns],after[columns])
        self.assertNotEqual(after.source_row.tolist(),table_before.source_row.tolist())
        self.assertEqual(after.hour_original.tolist(),table_before.hour_original.tolist())

    def test_complete_new_date_accepted_then_becomes_protected_history(self):
        self.initial()
        incoming=pd.concat([self.raw,self.future()],ignore_index=True)
        incoming.to_csv(self.source,index=False)
        audit=prep.prepare(self.source,self.output)
        self.assertEqual(audit['output_rows'],73)
        self.assertEqual(self.state()['data_end_date'],'2021-11-01')
        incoming.loc[incoming.date.eq('2021-11-01'),'amount']=9
        incoming.to_csv(self.source,index=False)
        before=(self.output/'current.json').read_bytes()
        with self.assertRaisesRegex(ReviewRequired,'historical'):
            prep.prepare(self.source,self.output)
        self.assertEqual((self.output/'current.json').read_bytes(),before)

    def test_added_deleted_and_changed_history_detected_even_with_same_daily_sum(self):
        self.initial()
        before=(self.output/'current.json').read_bytes()
        broken=self.raw.copy()
        broken.loc[0,'amount']+=1
        broken.loc[1,'amount']-=1
        report=history_changes(self.raw,broken)
        self.assertEqual(report['changed_value_keys'],2)
        for candidate in (broken,self.raw.iloc[1:],pd.concat([self.raw,self.raw.iloc[[0]]],ignore_index=True)):
            candidate.to_csv(self.source,index=False)
            with self.assertRaises(ReviewRequired):
                prep.prepare(self.source,self.output)
            self.assertEqual((self.output/'current.json').read_bytes(),before)
        self.assertGreater(history_changes(self.raw,self.raw.iloc[1:])['removed_historical_rows'],0)
        self.assertGreater(history_changes(self.raw,pd.concat([self.raw,self.raw.iloc[[0]]]))['added_historical_rows'],0)

    def test_unknown_schema_and_bad_new_calendars_rejected(self):
        self.initial()
        before=(self.output/'current.json').read_bytes()
        cases=[self.raw.assign(unexpected='x'),
               pd.concat([self.raw,self.future().iloc[1:]],ignore_index=True),
               pd.concat([self.raw,self.future('2021-11-02')],ignore_index=True)]
        for candidate in cases:
            candidate.to_csv(self.source,index=False)
            with self.assertRaises(ReviewRequired):
                prep.prepare(self.source,self.output)
            self.assertEqual((self.output/'current.json').read_bytes(),before)

    def test_serialization_failure_leaves_pointer_and_last_table_untouched(self):
        self.initial()
        before=(self.output/'current.json').read_bytes()
        table=self.table()
        pd.concat([self.raw,self.future()],ignore_index=True).to_csv(self.source,index=False)
        with patch.object(prep,'save_gzip',side_effect=OSError('simulated disk failure')):
            with self.assertRaises(OSError):
                prep.prepare(self.source,self.output)
        self.assertEqual((self.output/'current.json').read_bytes(),before)
        pd.testing.assert_frame_equal(table,self.table())
        self.assertFalse(list(self.output.glob('.pending-*')))

    def test_negative_missing_and_unknown_direction_rejected(self):
        for column,value in [('amount',-1),('amount',float('nan')),('customs_regime','транзит')]:
            candidate=self.raw.copy()
            candidate.loc[0,column]=value
            with self.assertRaises(ReviewRequired):
                validate_source(candidate)


if __name__=='__main__':
    unittest.main()
