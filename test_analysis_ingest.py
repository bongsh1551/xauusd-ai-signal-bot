import unittest

from main import build_analysis_ingest_payload


class AnalysisIngestPayloadTests(unittest.TestCase):
    def setUp(self):
        self.record = {
            'run_id': 'run-001',
            'created_at_utc': '2026-11-05T07:00:00+00:00',
            'created_at_myt': '2026-11-05T15:00:00+08:00',
            'mode': 'manual_signals',
            'code_commit': 'abc123',
            'charts': [{'interval': '5min', 'quality_review_required': False}],
            'fundamentals': {'calendar_coverage': 'partial'},
            'trade_plan': None,
            'market_watch': {'zones': []},
            'current_price': 4000.0,
        }
        self.analysis = '状态：WAIT\n观察市场，不存在有效进场条件。'
        self.safety_gate = {'passed': True, 'reasons': []}

    def test_wait_in_manual_signals_is_ingestable_context_and_publish_permission_follows_gate(self):
        payload = build_analysis_ingest_payload(
            self.record, self.analysis, self.safety_gate,
            {'timestamp_stale': False, 'last_closed_candle_utc': '2026-11-05T06:55:00+00:00'})
        meta = payload['meta']
        self.assertEqual(meta['analysis_status'], 'WAIT')
        self.assertTrue(meta['analysis_usable'])
        self.assertEqual(meta['quality_status'], 'USABLE_CONTEXT')
        self.assertTrue(meta['publish_allowed'])
        self.assertEqual(meta['data_as_of_utc'], '2026-11-05T06:55:00+00:00')

    def test_quality_flag_does_not_overwrite_trusted_context(self):
        self.record['charts'][0]['quality_review_required'] = True
        payload = build_analysis_ingest_payload(
            self.record, self.analysis, self.safety_gate,
            {'timestamp_stale': False, 'last_closed_candle_utc': '2026-11-05T06:55:00+00:00'})
        self.assertFalse(payload['meta']['analysis_usable'])
        self.assertIn('CHART_QUALITY_REVIEW_REQUIRED', payload['meta']['quality_reasons'])

    def test_stale_or_missing_m5_is_not_usable(self):
        payload = build_analysis_ingest_payload(
            self.record, self.analysis, self.safety_gate,
            {'timestamp_stale': True, 'last_closed_candle_utc': '2026-11-05T06:40:00+00:00'})
        self.assertFalse(payload['meta']['analysis_usable'])
        self.assertIn('M5_DATA_STALE_OR_MISSING', payload['meta']['quality_reasons'])

    def test_ambiguous_status_is_not_usable(self):
        payload = build_analysis_ingest_payload(
            self.record, '状态：WAIT\n状态：APPROACH',
            self.safety_gate,
            {'timestamp_stale': False, 'last_closed_candle_utc': '2026-11-05T06:55:00+00:00'})
        self.assertFalse(payload['meta']['analysis_usable'])
        self.assertEqual(payload['meta']['analysis_status'], 'INVALID')


if __name__ == '__main__':
    unittest.main()
