import unittest
from copy import deepcopy
import pandas as pd
import formal_signal_checks as f
class FormalChecks(unittest.TestCase):
    def setUp(self):
        self.index=pd.date_range('2026-11-06T04:30:00Z',periods=51,freq='5min')
        self.frame=pd.DataFrame({'Open':100.,'High':102.,'Low':98.,'Close':101.},index=self.index)
        self.frame.iloc[-2]=[101,102,98,99]
        self.frame.iloc[-1]=[98,103,97,102]
        self.now=pd.Timestamp('2026-11-06T08:45:30Z')
        self.plan={'status':'ENTRY_READY','direction':'BUY','confirmation':{'kind':'ENGULFING','candle_start_utc':self.index[-1].isoformat()}}
        self.charts=[{'interval':p,'last_closed_candle_utc':t,'timestamp_stale':False,'quality_review_required':False,'quality_verdict':'NO_NARROW_RUN_FLAG','market_session_verified':False} for p,t in [('5min',self.index[-1].isoformat()),('15min','2026-11-06T08:30:00Z'),('1h','2026-11-06T07:00:00Z')]]
    def test_current_engulfing(self):
        self.assertTrue(f.confirmation_check(self.plan,self.frame)['verified'])
    def test_wrong_direction(self):
        self.assertFalse(f.confirmation_check({**self.plan,'direction':'SELL'},self.frame)['verified'])
    def test_old_confirmation(self):
        p=deepcopy(self.plan);p['confirmation']['candle_start_utc']=self.index[-2].isoformat()
        self.assertFalse(f.confirmation_check(p,self.frame)['verified'])
    def test_no_plan(self):
        self.assertFalse(f.confirmation_check(None,self.frame)['verified'])
    def test_fresh_schema_not_fabricated_certification(self):
        self.assertEqual(f.quality_reasons({'charts':self.charts},self.now,self.frame),[])
        self.assertTrue(all(c['market_session_verified'] is False for c in self.charts))
    def test_stale(self):
        self.assertTrue(f.quality_reasons({'charts':self.charts},self.now+pd.Timedelta(hours=1),self.frame))
    def test_missing_chart(self):
        self.assertTrue(f.quality_reasons({'charts':self.charts[:2]},self.now,self.frame))
    def test_missing_prices(self):
        self.assertTrue(f.quality_reasons({'charts':self.charts},self.now,None))
    def test_flat_latest(self):
        self.frame.iloc[-1]=[100,100,100,100]
        self.assertIn('LATEST_M5_NO_PRICE_RANGE',f.quality_reasons({'charts':self.charts},self.now,self.frame))
    def test_quality_failure(self):
        self.charts[1]['quality_review_required']=True
        self.assertTrue(f.quality_reasons({'charts':self.charts},self.now,self.frame))
    def test_mss(self):
        self.frame.iloc[-5]=[100,103,98,101]
        self.frame.iloc[-4]=[101,105,98,102]
        self.frame.iloc[-3]=[102,103,98,100]
        self.frame.iloc[-1]=[100,108,99,107]
        p={'status':'ENTRY_READY','direction':'BUY','confirmation':{'kind':'MSS','candle_start_utc':self.index[-1].isoformat(),'swing_candle_utc':self.index[-4].isoformat()}}
        self.assertTrue(f.confirmation_check(p,self.frame)['verified'])
    def test_mss_source_outside_input(self):
        p=deepcopy(self.plan);p['confirmation']={'kind':'MSS','candle_start_utc':self.index[-1].isoformat(),'swing_candle_utc':self.index[1].isoformat()}
        self.assertFalse(f.confirmation_check(p,self.frame)['verified'])
if __name__=='__main__':unittest.main()
