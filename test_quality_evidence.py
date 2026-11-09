import unittest
from types import SimpleNamespace
import pandas as pd
from quality_evidence import window_evidence, enrich, install_quality_evidence

class EvidenceTests(unittest.TestCase):
    def frame(self, n=120):
        idx = pd.date_range('2026-11-06', periods=n, freq='15min', tz='UTC')
        return pd.DataFrame({'Open':4000.,'High':4000.1,'Low':4000.,'Close':4000.05},index=idx)
    def diag(self, recent=False, window=True):
        return {'quality_review_required':window or recent,'quality_verdict':'REVIEW_REQUIRED',
                'diagnostic_narrow_range_threshold_usd':.3,'recent_narrow_range_ratio':.2 if not recent else .8,
                'recent_narrow_range_longest_run':4 if not recent else 26,
                'chart_window_narrow_range_ratio':.7 if window else 0,
                'chart_window_narrow_range_longest_run':63 if window else 0}
    def test_history_scope_does_not_change_gate(self):
        f=self.frame(); f.loc[f.index[-40:],'High']=4002.
        d=self.diag(); before=dict(d); enrich(f,d,15)
        self.assertEqual({k:d[k] for k in before},before)
        self.assertEqual(d['quality_evidence']['trigger_scope'],'HISTORICAL_WINDOW_ONLY')
        self.assertEqual(d['quality_evidence']['window_40']['narrow_count'],0)
        self.assertEqual(d['quality_evidence']['window_120']['narrow_count'],80)
    def test_recent_scope(self):
        d=enrich(self.frame(),self.diag(True),15)
        self.assertEqual(d['quality_evidence']['trigger_scope'],'RECENT_AND_WINDOW')
    def test_gaps_break_runs(self):
        f=self.frame(8).drop(self.frame(8).index[4]); e=window_evidence(f,.3,15)
        self.assertEqual(e['longest_contiguous_run'],4)
        self.assertEqual(len(e['gaps']),1)
    def test_close_timestamp(self):
        e=window_evidence(self.frame(1),.3,15)
        self.assertEqual(e['flat_runs'][0]['end_close_utc'],'2026-11-06T00:15:00+00:00')
    def test_empty(self):
        self.assertEqual(window_evidence(self.frame(0),.3,15)['narrow_count'],0)
    def test_installed_wrapper_preserves_return(self):
        f=self.frame(); image=b'image'; d=self.diag(); d.update(interval='15min',last_closed_candle_utc='2026-11-06T00:00:00+00:00')
        p=SimpleNamespace(fetch_chart=lambda *args:(f,image,d),build_analysis_ingest_payload=lambda *a:{'meta':{'charts':[d]}})
        install_quality_evidence(p); wrapped=p.fetch_chart; install_quality_evidence(p)
        self.assertIs(p.fetch_chart,wrapped)
        actual=p.fetch_chart('redacted','15min',15,None,None)
        self.assertIs(actual[0],f); self.assertIs(actual[1],image)
        self.assertTrue(actual[2]['quality_review_required'])
        self.assertNotIn('quality_evidence',d)
        payload=p.build_analysis_ingest_payload()
        self.assertIn('quality_evidence',payload['meta']['charts'][0])
        self.assertIsNot(payload['meta']['charts'][0],d)

if __name__=='__main__': unittest.main()
