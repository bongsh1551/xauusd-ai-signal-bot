import assert from 'node:assert/strict';
import { ingestWithAlerts, notifyAccepted } from './opportunity_alerts.js';

const now = Date.now();
const iso = (minutesAgo) => new Date(now - minutesAgo * 60000).toISOString();
const charts = [
  { interval: '5min', last_closed_candle_utc: iso(5), timestamp_stale: false, quality_review_required: false, quality_verdict: 'NO_NARROW_RUN_FLAG' },
  { interval: '15min', last_closed_candle_utc: iso(15), timestamp_stale: false, quality_review_required: false, quality_verdict: 'NO_NARROW_RUN_FLAG' },
  { interval: '1h', last_closed_candle_utc: iso(60), timestamp_stale: false, quality_review_required: false, quality_verdict: 'NO_NARROW_RUN_FLAG' }
];
const zone = {
  direction: 'BUY', zone_type: 'demand', low: 100, high: 101,
  entry_trigger: 'M5 bullish rejection and micro structure break',
  cancel_condition: 'M5 close below 99.5',
  scenario_id: 'BUY:M15:' + charts[1].last_closed_candle_utc,
  status: 'APPROACH', alert_allowed: true, close_through: false,
  scenario_state: 'ACTIVE', review_basis: 'offline verified fixture',
  reviewed_m5_start_utc: charts[0].last_closed_candle_utc,
  source_interval: '15min', source_candle_utc: charts[1].last_closed_candle_utc
};
const meta = {
  run_id: 'offline-run-1', created_at_utc: iso(1), analysis_usable: true,
  analysis_complete: true, analysis_status: 'APPROACH', mode: 'manual_signals',
  charts, current_price: 100.5, market_watch: { zones: [zone] },
  evidence_package: { zones: [{
    scenario_id: zone.scenario_id, direction: 'BUY', scenario_state: 'ACTIVE',
    status: 'APPROACH', alert_allowed: true, confirmation_verified: true,
    missing_confirmations: []
  }] }
};
const state = new Map([['last_usable_run_id', meta.run_id]]);
const db = {
  prepare(sql) {
    return {
      bind(...args) {
        return {
          async first() {
            return state.has(args[0]) ? { value: state.get(args[0]) } : null;
          },
          async run() {
            if (sql.startsWith('DELETE')) {
              if (state.get(args[0]) === args[1]) state.delete(args[0]);
              return { meta: { changes: 1 } };
            }
            if (sql.includes('CAST(app_state.value AS INTEGER) < ?')) {
              const existing = Number(state.get(args[0]) || 0);
              if (existing >= args[2]) return { meta: { changes: 0 } };
            }
            state.set(args[0], args[1]);
            return { meta: { changes: 1 } };
          }
        };
      }
    };
  }
};
const env = { DB: db, TELEGRAM_BOT_TOKEN: 'offline-token' };
const originalFetch = globalThis.fetch;
const requests = [];
globalThis.fetch = async (url, options) => {
  requests.push({ url, body: JSON.parse(options.body) });
  return new Response(JSON.stringify({ ok: true, result: { message_id: 1 } }), {
    status: 200, headers: { 'content-type': 'application/json' }
  });
};

try {
  const request = new Request('https://worker.example/ingest-analysis', {
    method: 'POST', headers: { 'content-type': 'application/json' }, body: JSON.stringify({ plan: 'WAIT', meta })
  });
  const original = {
    async fetch() {
      return new Response(JSON.stringify({ ok: true }), {
        status: 200, headers: { 'content-type': 'application/json' }
      });
    }
  };
  const response = await ingestWithAlerts(request, env, {}, original);
  const body = await response.json();
  assert.equal(body.ok, true);
  assert.equal(body.opportunity_alerts.sent, 1);
  assert.equal(requests.length, 1);
  assert.equal(requests[0].url, 'https://api.telegram.org/botoffline-token/sendMessage');
  assert.equal(requests[0].body.chat_id, '6772154791');
  assert.match(requests[0].body.text, /尚未确认，不要提前进场/);

  const duplicate = await notifyAccepted({ meta }, env);
  assert.equal(duplicate.sent, 0);
  assert.equal(requests.length, 1);

  const noToken = await notifyAccepted({ meta }, { DB: db });
  assert.equal(noToken.reason, 'TOKEN_MISSING');

  console.log('Cloudflare opportunity delivery mock tests passed');
} finally {
  globalThis.fetch = originalFetch;
}
