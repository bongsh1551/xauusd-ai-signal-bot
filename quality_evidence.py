"""Read-only quality evidence; never changes quality or publication decisions."""
from functools import wraps

def window_evidence(frame, threshold, minutes):
    bars = []
    runs, gaps, active = [], [], []
    previous = None
    for stamp, row in frame.iterrows():
        close = stamp + __import__('datetime').timedelta(minutes=minutes)
        bars.append([stamp.isoformat(), float(row.Open), float(row.High), float(row.Low), float(row.Close)])
        if previous is not None and (stamp - previous).total_seconds() != minutes * 60:
            gaps.append({'before_start_utc': previous.isoformat(), 'after_start_utc': stamp.isoformat(), 'seconds': (stamp-previous).total_seconds()})
            if active:
                runs.append(active)
                active = []
        if float(row.High - row.Low) <= threshold:
            active.append((stamp, close, float(row.High - row.Low)))
        elif active:
            runs.append(active)
            active = []
        previous = stamp
    if active:
        runs.append(active)
    count = sum(len(r) for r in runs)
    return {'bars': len(bars), 'columns': ['start_utc','open','high','low','close'], 'ohlc_rows': bars,
            'narrow_count': count, 'narrow_ratio': count / len(bars) if bars else 0,
            'longest_contiguous_run': max((len(r) for r in runs), default=0),
            'flat_runs': [{'start_utc': r[0][0].isoformat(), 'last_start_utc': r[-1][0].isoformat(),
                           'end_close_utc': r[-1][1].isoformat(), 'bars': len(r),
                           'max_range': max(v[2] for v in r)} for r in runs], 'gaps': gaps}

def enrich(frame, diagnostic, minutes):
    threshold = diagnostic['diagnostic_narrow_range_threshold_usd']
    evidence = {'version': 1, 'threshold_usd': threshold, 'cause': 'UNKNOWN',
                'market_session_verified': False, 'decision_changed': False}
    for n in (40, 120):
        evidence['window_' + str(n)] = window_evidence(frame.tail(n), threshold, minutes)
    def old_trigger(prefix):
        return diagnostic[prefix + 'ratio'] >= 0.25 and diagnostic[prefix + 'longest_run'] >= 6
    recent = old_trigger('recent_narrow_range_')
    historical = old_trigger('chart_window_narrow_range_')
    evidence['trigger_scope'] = 'RECENT_AND_WINDOW' if recent and historical else 'RECENT' if recent else 'HISTORICAL_WINDOW_ONLY' if historical else 'NONE'
    diagnostic['quality_evidence'] = evidence
    return diagnostic

def install_quality_evidence(pipeline):
    original = pipeline.fetch_chart
    if getattr(original, '_quality_evidence_v1', False):
        return
    original_payload = pipeline.build_analysis_ingest_payload
    evidence = {}
    @wraps(original)
    def fetch_chart(key, interval, minutes, now, folder):
        frame, image, diagnostic = original(key, interval, minutes, now, folder)
        detail = enrich(frame, dict(diagnostic), minutes)['quality_evidence']
        evidence[interval] = (diagnostic.get('last_closed_candle_utc'), detail)
        return frame, image, diagnostic
    @wraps(original_payload)
    def build_payload(*args, **kwargs):
        import copy
        payload = original_payload(*args, **kwargs)
        charts = copy.deepcopy(payload.get('meta', {}).get('charts', []))
        for chart in charts:
            item = evidence.get(chart.get('interval'))
            if item and item[0] == chart.get('last_closed_candle_utc'):
                chart['quality_evidence'] = item[1]
        payload['meta']['charts'] = charts
        return payload
    fetch_chart._quality_evidence_v1 = True
    pipeline.fetch_chart = fetch_chart
    pipeline.build_analysis_ingest_payload = build_payload
