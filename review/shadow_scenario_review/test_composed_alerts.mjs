import assert from 'node:assert/strict';
import { candidates } from '../../cloudflare/opportunity_alerts.js';
const now=Date.parse('2026-11-06T08:45:30Z');
const base={mode:'shadow',analysis_usable:true,analysis_complete:true,analysis_status:'WAIT',created_at_utc:'2026-11-06T08:45:00Z',current_price:4072.58,
 charts:[['5min','08:40'],['15min','08:30'],['1h','07:00']].map(([interval,t])=>({interval,last_closed_candle_utc:'2026-11-06T'+t+':00Z',timestamp_stale:false,quality_review_required:false,quality_verdict:'NO_NARROW_RUN_FLAG'})),
 market_watch:{zones:[{direction:'SELL',zone_type:'supply',low:4070.08,high:4072.82,status:'APPROACH',scenario_state:'ACTIVE',source_interval:'5min',source_candle_utc:'2026-11-06T08:35:00Z',reviewed_m5_start_utc:'2026-11-06T08:40:00Z',review_basis:'Synthetic fixture only',entry_trigger:'Synthetic confirmation',cancel_condition:'Synthetic cancellation',stop_loss:4073.82}]}};
let count=0;
function check(change,want){const m=structuredClone(base);change(m,m.market_watch.zones[0]);assert.equal(candidates(m,now).length,want);count++;}
check(()=>{},1);
check((m,z)=>z.status='WAIT',0);
check((m,z)=>z.scenario_state='PAUSED',0);
check((m,z)=>z.scenario_state='INVALIDATED',0);
check((m,z)=>delete z.scenario_state,0);
check((m,z)=>z.reviewed_m5_start_utc='2026-11-06T08:35:00Z',0);
check(m=>m.current_price=4074.53,0);
check(m=>m.analysis_usable=false,0);
check(m=>m.created_at_utc='2026-11-06T08:00:00Z',0);
const changed=structuredClone(base);changed.market_watch.zones[0].high+=0.1;
assert.equal(candidates(base,now)[0].key,candidates(changed,now)[0].key);count++;
console.log(JSON.stringify({composed_candidate_tests_passed:count,external_calls:0}));
