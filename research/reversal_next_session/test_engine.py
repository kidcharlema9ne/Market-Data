import unittest
import numpy as np
import pandas as pd
from engine import entries_and_outcomes

def fixture():
    p=pd.DataFrame(dict(open=100., high=101., low=99., close=100.,tick=.25,cot_index=80.),index=pd.bdate_range('2020-01-01',periods=30))
    p.iloc[16,p.columns.get_indexer(['open','high','low','close'])]=[100,102,98,99]
    p.iloc[17,p.columns.get_indexer(['open','high','low','close'])]=[100,104,97,103]
    return p

class EntryTests(unittest.TestCase):
    def trade(self,p):
        e,_=entries_and_outcomes(p)
        return e[e.setup.eq(p.index[16])]
    def test_long_high_and_day_one(self):
        p=fixture();r=self.trade(p).set_index('horizon');a=(13*2+4)/14
        self.assertAlmostEqual(r.loc[1,'fill'],102.25)
        self.assertAlmostEqual(r.loc[1,'atr'],a)
        self.assertAlmostEqual(r.loc[1,'return_atr'],.75/a)
        self.assertEqual(r.loc[1,'end'],p.index[17])
        self.assertEqual(r.loc[10,'end'],p.index[26])
    def test_exact_short_mirror(self):
        p=fixture();q=p.copy();q['open']=200-p.open;q['close']=200-p.close;q['high']=200-p.low;q['low']=200-p.high;q['cot_index']=20
        a=self.trade(p);b=self.trade(q)
        self.assertTrue((b.side==-1).all());self.assertAlmostEqual(b.fill.iloc[0],97.75)
        for c in ['return_atr','mfe_atr','mae_lower_atr','mae_upper_atr']:
            np.testing.assert_allclose(a[c],b[c])
    def test_expire_never_day_two(self):
        p=fixture();p.loc[p.index[17],['open','high','low','close']]=[100,102,97,100]
        p.loc[p.index[18],['open','high','low','close']]=[100,110,99,109]
        self.assertTrue(self.trade(p).empty)
    def test_low_break_not_long_entry(self):
        p=fixture();p.loc[p.index[17],['open','high','low','close']]=[100,101,90,91]
        self.assertTrue(self.trade(p).empty)
    def test_gap_fills_open(self):
        p=fixture();p.loc[p.index[17],['open','high','low','close']]=[105,106,103,104]
        r=self.trade(p);self.assertTrue(r.gap_fill.all());self.assertEqual(r.fill.iloc[0],105)
        np.testing.assert_allclose(r.mae_lower_atr,r.mae_upper_atr)
    def test_intraday_mae_bounds(self):
        r=self.trade(fixture()).iloc[0]
        self.assertEqual(r.mae_lower_atr,0);self.assertGreater(r.mae_upper_atr,0)
    def test_threshold_and_strict_reversal(self):
        p=fixture();p['cot_index']=79.999;self.assertTrue(self.trade(p).empty)
        p=fixture();p.loc[p.index[16],'close']=100;self.assertTrue(self.trade(p).empty)
    def test_missing_next_session_never_skipped(self):
        p=fixture();p.loc[p.index[17],['open','high','low','close']]=np.nan
        self.assertTrue(self.trade(p).empty)
    def test_entry_bar_does_not_change_atr(self):
        p=fixture();a=self.trade(p).atr.iloc[0];p.loc[p.index[17],'high']=1000
        self.assertEqual(self.trade(p).atr.iloc[0],a)
    def test_bad_future_bar_does_not_remove_day_one(self):
        p=fixture();p.loc[p.index[18],['open','high','low','close']]=np.nan
        r=self.trade(p);self.assertEqual(r.horizon.tolist(),[1])

if __name__=='__main__': unittest.main(verbosity=2)
