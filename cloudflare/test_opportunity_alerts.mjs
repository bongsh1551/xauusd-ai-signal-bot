import assert from 'node:assert/strict';
import { candidates } from './opportunity_alerts.js';

const now = Date.parse('2026-11-09T01:00:00Z');
const charts = [
  { interval: '5min', last_closed_candle_utc: '2026-11-09T00:55:00Z', timestamp_stale: false, quality_review_required: false, quality_verdict: 'NO_NARROW_RUN_FLAG' },
  { interval: '15min', last_closed_candle_utc: '2026-11-09T00:45:00Z', timestamp_stale: false, quality_review_required: false, quality_verdict: 'NO_NARROW_RUN_FLAG' },
  { interval: '1h', last_closed_candle_utc: '2026-11-09T00:00:00Z', timestamp_stale: false, quality_review_required: false, quality_verdict: 'NO_NARROW_RUN_FLAG' }
];
const baseZone = {
  direction: 'SELL', zone_type: 'supply', low: 100, high: 101,
  entry_trigger: 'bearish confirmation', cancel_condition: 'M5 close above high',
  scenario_id: 'SELL:M15:2026-11-09T00:45:00Z', status: 'APPROACH',
  alert_allowed: true, close_through: false, scenario_state: 'ACTIVE',
  bearish_confirmation_verified: true,
  review_basis: 'verified evidence', reviewed_m5_start_utc: '2026-11-09T00:55:00Z',
  source_interval: '15min', source_candle_utc: '2026-11-09T00:45:00Z'
};
const buyZone = {
  ...baseZone,
  direction: 'BUY', zone_type: 'demand',
  entry_trigger: 'bullish confirmation', cancel_condition: 'M5 close below low',
  scenario_id: 'BUY:M15:2026-11-09T00:45:00Z',
  bullish_confirmation_verified: true
};
const meta = { analysis_usable: true, analysis_complete: true, analysis_status: 'APPROACH', mode: 'shadow', created_at_utc: '2026-11-09T00:59:00Z', charts, current_price: 100.5, market_watch: { zones: [baseZone] } };

assert.equal(candidates(meta, now).length, 1);

const noAlert = { ...baseZone, alert_allowed: false };
assert.equal(candidates({ ...meta, market_watch: { zones: [noAlert] } }, now).length, 0);

const closedThrough = { ...baseZone, close_through: true };
assert.equal(candidates({ ...meta, market_watch: { zones: [closedThrough] } }, now).length, 0);

const buyMeta = { ...meta, market_watch: { zones: [buyZone] } };
assert.equal(candidates(buyMeta, now).length, 1);

const buyUnverified = { ...buyZone, bullish_confirmation_verified: false };
assert.equal(candidates({ ...meta, market_watch: { zones: [buyUnverified] } }, now).length, 0);

const sellUnverified = { ...baseZone, bearish_confirmation_verified: false };
assert.equal(candidates({ ...meta, market_watch: { zones: [sellUnverified] } }, now).length, 0);

console.log('opportunity alert replay tests passed');
