// Review gate only; the host candidates() retains freshness and quality checks.
export function reviewAllowsAlert(z, meta) {
  if (!z || typeof z !== 'object' || !meta || z.status !== 'APPROACH' ||
      z.scenario_state !== 'ACTIVE' || typeof z.review_basis !== 'string' ||
      !z.review_basis.trim()) return false;
  const evidence = (meta.evidence_package?.zones || []).find(
    item => item && item.scenario_id === z.scenario_id
  );
  if (!evidence) return false;
  if (evidence.direction !== z.direction) return false;
  if (evidence.scenario_state !== 'ACTIVE') return false;
  if (evidence.status !== 'APPROACH') return false;
  if (evidence.alert_allowed !== true) return false;
  if (evidence.confirmation_verified !== true) return false;
  if (!Array.isArray(evidence.missing_confirmations) || evidence.missing_confirmations.length) return false;
  const charts = meta.charts;
  if (!Array.isArray(charts) || charts.some(c => !c || typeof c !== 'object')) return false;
  const m5 = charts.find(c => c.interval === '5min');
  if (!m5 || typeof z.reviewed_m5_start_utc !== 'string') return false;
  const reviewed = Date.parse(z.reviewed_m5_start_utc);
  if (!Number.isFinite(reviewed) || reviewed !== Date.parse(m5.last_closed_candle_utc)) return false;
  if (!['5min', '15min', '1h'].includes(z.source_interval) ||
      typeof z.source_candle_utc !== 'string') return false;
  const source = charts.find(c => c.interval === z.source_interval);
  const origin = Date.parse(z.source_candle_utc);
  if (!source || !Number.isFinite(origin) || origin > Date.parse(source.last_closed_candle_utc) ||
      !Number.isFinite(Date.parse(source.last_closed_candle_utc))) return false;
  const price = meta.current_price, sl = z.stop_loss;
  if (typeof price !== 'number' || !Number.isFinite(price) || price <= 0) return false;
  if (typeof sl === 'number' && Number.isFinite(sl) && sl > 0) {
    if (z.direction === 'SELL' && price >= sl) return false;
    if (z.direction === 'BUY' && price <= sl) return false;
  }
  return true;
}
