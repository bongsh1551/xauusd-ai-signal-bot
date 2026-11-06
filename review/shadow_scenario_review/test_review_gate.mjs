import assert from 'node:assert/strict';
import { reviewAllowsAlert } from './scenario_review_gate.js';
const meta = {current_price:4072.58,charts:[
  {interval:'5min',last_closed_candle_utc:'2026-11-06T08:40:00Z'},
  {interval:'15min',last_closed_candle_utc:'2026-11-06T08:30:00Z'},
  {interval:'1h',last_closed_candle_utc:'2026-11-06T07:00:00Z'}]};
const zone = {direction:'SELL',status:'APPROACH',scenario_state:'ACTIVE',
  source_interval:'5min',source_candle_utc:'2026-11-06T08:35:00Z',
  reviewed_m5_start_utc:'2026-11-06T08:40:00Z',review_basis:'Synthetic test only',stop_loss:4073.82};
const results=[];
function check(name,change,expected){const z=structuredClone(zone),m=structuredClone(meta);change(z,m);assert.equal(reviewAllowsAlert(z,m),expected,name);results.push(name);}
check('ACTIVE APPROACH with current review',()=>{},true);
check('WAIT cannot be overridden by price',z=>z.status='WAIT',false);
check('PAUSED blocked',z=>z.scenario_state='PAUSED',false);
check('INVALIDATED blocked',z=>z.scenario_state='INVALIDATED',false);
check('legacy missing lifecycle blocked',z=>delete z.scenario_state,false);
check('old review blocked',z=>z.reviewed_m5_start_utc='2026-11-06T08:35:00Z',false);
check('equivalent UTC representation accepted',z=>z.reviewed_m5_start_utc='2026-11-06T08:40:00+00:00',true);
check('missing review reason blocked',z=>delete z.review_basis,false);
check('future origin blocked',z=>z.source_candle_utc='2026-11-06T09:00:00Z',false);
check('unknown source timeframe blocked',z=>z.source_interval='4h',false);
check('SELL beyond SL blocked',(z,m)=>m.current_price=4074.53,false);
check('BUY beyond SL blocked',(z,m)=>{z.direction='BUY';z.stop_loss=4073;m.current_price=4072;},false);
check('invalid source timestamp blocked',(z,m)=>m.charts[0].last_closed_candle_utc='bad',false);
check('null chart blocked',(z,m)=>m.charts[0]=null,false);
check('invalid current price blocked',(z,m)=>m.current_price=NaN,false);
assert.equal(reviewAllowsAlert(null,meta),false);results.push('null zone blocked');
console.log(JSON.stringify({passed:results.length,tests:results,external_calls:0}));
