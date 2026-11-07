import { reviewAllowsAlert } from './scenario_review_gate.js';
const CHAT_ID = '6772154791';
export function candidates(meta, now = Date.now()) {
  if (!meta || meta.analysis_usable !== true || meta.analysis_complete !== true ||
      !['WAIT','APPROACH','CONFIRMED'].includes(meta.analysis_status) ||
      !['shadow','manual_signals'].includes(meta.mode)) return [];
  const created=Date.parse(meta.created_at_utc);
  if(!Number.isFinite(created)||created>now+60000||now-created>15*60000)return [];
  const charts=meta.charts;
  if(!Array.isArray(charts)||charts.length!==3)return [];
  const periods={'5min':5,'15min':15,'1h':60};
  if(new Set(charts.map(c=>c.interval)).size!==3)return [];
  for(const c of charts){
    const minutes=periods[c.interval],start=Date.parse(c.last_closed_candle_utc);
    if(!minutes||!Number.isFinite(start)||c.timestamp_stale!==false||
       c.quality_review_required!==false||c.quality_verdict!=='NO_NARROW_RUN_FLAG')return [];
    const close=start+minutes*60000;
    if(close>now+60000||now-close>Math.max(15,minutes*2)*60000)return [];
  }
  const price=meta.current_price;
  if(typeof price!=='number'||!Number.isFinite(price)||price<=0)return [];
  const zones=meta.market_watch?.zones;
  if(!Array.isArray(zones)||zones.length>2)return [];
  return zones.filter(z=>reviewAllowsAlert(z,meta)&&['BUY','SELL'].includes(z.direction)&&
    ['demand','supply','ob','fvg','liquidity'].includes(z.zone_type)&&
    typeof z.low==='number'&&typeof z.high==='number'&&
    Number.isFinite(z.low)&&Number.isFinite(z.high)&&z.low>0&&z.high>=z.low&&
    typeof z.entry_trigger==='string'&&z.entry_trigger.trim()&&
    typeof z.cancel_condition==='string'&&z.cancel_condition.trim()&&
    typeof z.scenario_id==='string'&&z.scenario_id.trim()&&
    z.status==='APPROACH'&&z.alert_allowed===true&&z.close_through===false&&
    (price>=z.low&&price<=z.high||z.status==='APPROACH')).map(z=>({
      key:'opportunity:approach:v3:'+new Date(created+8*3600000).toISOString().slice(0,10)+':'+
        z.scenario_id+':APPROACH',
      text:'XAUUSD 机会预警｜尚未确认进场\n方向：'+z.direction+
        '\n关注区域：'+z.low.toFixed(2)+'–'+z.high.toFixed(2)+' '+z.zone_type+
        '\n本轮 M5 收盘参考：'+price.toFixed(2)+
        levelText(z)+'\n等待确认：'+z.entry_trigger+'\n取消条件：'+z.cancel_condition+
        '\n数据对应 M5 K线起始时间（UTC）：'+charts.find(c=>c.interval==='5min').last_closed_candle_utc+
        '\n当前未确认，不是立即进场指令；是否交易由你决定。'
    })).filter(a=>a.text.length<=3500);
}
export async function notifyAccepted(body, env) {
  if(!env.TELEGRAM_BOT_TOKEN)return {sent:0,reason:'TOKEN_MISSING'};
  const meta=body?.meta;
  const items=candidates(meta);
  if(!items.length)return {sent:0};
  const latest=await env.DB.prepare('SELECT value FROM app_state WHERE key=?').bind('last_usable_run_id').first();
  if(latest?.value!==meta.run_id)return {sent:0,reason:'NOT_CURRENT_USABLE_RUN'};
  let sent=0;
  for(const item of items){
    const prior=await env.DB.prepare('SELECT value FROM app_state WHERE key=?').bind(item.key).first();
    if(prior?.value&&Date.now()-Date.parse(prior.value)<30*60000)continue;
    const lock=item.key+':lease',now=Date.now();
    const lease=await env.DB.prepare('INSERT INTO app_state(key,value) VALUES(?,?) ON CONFLICT(key) DO UPDATE SET value=excluded.value,updated_at=CURRENT_TIMESTAMP WHERE CAST(app_state.value AS INTEGER) < ?').bind(lock,String(now+60000),now).run();
    if(!lease.meta?.changes)continue;
    try{
      const current=await env.DB.prepare('SELECT value FROM app_state WHERE key=?').bind('last_usable_run_id').first();
      if(current?.value!==meta.run_id)continue;
      const response=await fetch('https://api.telegram.org/bot'+env.TELEGRAM_BOT_TOKEN+'/sendMessage',{
        method:'POST',headers:{'content-type':'application/json'},
        body:JSON.stringify({chat_id:CHAT_ID,text:item.text}),signal:AbortSignal.timeout(15000)});
      const result=await response.json();
      if(!response.ok||result.ok!==true)throw new Error('TELEGRAM_SEND_FAILED');
      await env.DB.prepare('INSERT INTO app_state(key,value) VALUES(?,?) ON CONFLICT(key) DO UPDATE SET value=excluded.value,updated_at=CURRENT_TIMESTAMP').bind(item.key,new Date().toISOString()).run();
      sent++;
    }finally{
      await env.DB.prepare('DELETE FROM app_state WHERE key=? AND value=?').bind(lock,String(now+60000)).run();
    }
  }
  return {sent};
}
export async function ingestWithAlerts(request,env,ctx,original){
  const url=new URL(request.url);
  if(request.method!=='POST'||url.pathname!=='/ingest-analysis')return original.fetch(request,env,ctx);
  const copy=request.clone();
  const response=await original.fetch(request,env,ctx);
  if(!response.ok)return response;
  const accepted=await response.clone().json();
  if(accepted.ok!==true)return response;
  let alerts;
  try{alerts=await notifyAccepted(await copy.json(),env);}
  catch(e){alerts={sent:0,error:'OPPORTUNITY_DELIVERY_FAILED'};console.error('opportunity_delivery_failed');}
  const headers=new Headers(response.headers);headers.delete('content-length');
  return new Response(JSON.stringify({...accepted,opportunity_alerts:alerts}),{status:response.status,headers});
}

function levelText(z) {
 const sl=z.stop_loss,tp=z.take_profits;
 const valid=z.levels_status==='PROVISIONAL'&&typeof sl==='number'&&Number.isFinite(sl)&&sl>0&&
  Array.isArray(tp)&&tp.length>=1&&tp.length<=2&&tp.every(v=>typeof v==='number'&&Number.isFinite(v)&&v>0)&&
  typeof z.sl_basis==='string'&&z.sl_basis.trim()&&typeof z.tp_basis==='string'&&z.tp_basis.trim()&&
  (z.direction==='BUY'?sl<z.low&&tp.every(v=>v>z.high)&&(tp.length===1||tp[1]>tp[0]):
   z.direction==='SELL'&&sl>z.high&&tp.every(v=>v<z.low)&&(tp.length===1||tp[1]<tp[0]));
 if(!valid)return '\nSL/TP参考：待定（本轮未提供完整、方向一致的区域专属价位与依据；不要据此进场）';
 return '\n结构性 SL参考：'+sl.toFixed(2)+'\nTP1参考：'+tp[0].toFixed(2)+
  (tp.length>1?'\nTP2参考：'+tp[1].toFixed(2):'')+
  '\nSL依据：'+z.sl_basis.slice(0,400)+'\nTP依据：'+z.tp_basis.slice(0,400)+
  '\n以上为等待确认的情景价位，未计实际成交、点差和滑点；不是已确认进场。';
}
