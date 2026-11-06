"""Real provider-candle checks for manual signals; never places orders."""
from datetime import datetime, timezone
import math
PERIODS = {'5min': 5, '15min': 15, '1h': 60}
def stamp(value):
    t = datetime.fromisoformat(str(value).replace('Z', '+00:00'))
    if t.tzinfo is None:
        raise ValueError('Timezone required')
    return t.timestamp()
def execution_instruction():
    return ('\n\n【执行模式】正式人工交易信号服务。仅依据本轮供应商真实已收线图表和 OHLC，'
            '无机会 WAIT，情景有效且接近区域 APPROACH，已发生并可核实确认才 CONFIRMED。'
            '禁止自动下单，禁止为了发消息制造机会。未知资料保留未知，未独立认证不伪称已认证。'
            'CONFIRMED 的 trade_plan 必须增加 entry_low、entry_high、source_interval、source_candle_utc；'
            '来源须对应 ACTIVE 且本轮复核的 APPROACH zone。增加 confirmation 对象：'
            'kind 为 MSS 或 ENGULFING，candle_start_utc 为本轮最新已收线 M5 起始时间；'
            'MSS 还需 swing_candle_utc，引用最近40根输入中被本轮收盘首次突破的局部摆动点；'
            'ENGULFING 为本轮实体吞没前一根反向实体。程序核实价格事件不代表验证全部策略逻辑或收益。'
            '明确结构 SL/TP、取消条件及1至15分钟有效期；成本未知则实际 RR 待核算，不生成手数。'
            'WAIT 时所有 zone.status 必须为 WAIT；不把历史模式限制当作本轮指令。\n')
def quality_reasons(record, now, frame):
    charts = record.get('charts')
    if not isinstance(charts, list) or len(charts) != 3 or any(not isinstance(c, dict) for c in charts):
        return ['THREE_CHARTS_REQUIRED']
    if {c.get('interval') for c in charts} != set(PERIODS):
        return ['CHART_PERIODS_INVALID']
    reasons = []
    current = stamp(now)
    if datetime.fromtimestamp(current, timezone.utc).weekday() >= 5:
        reasons.append('WEEKEND_REVIEW_REQUIRED')
    for c in charts:
        p = c['interval']
        try:
            age = current - stamp(c['last_closed_candle_utc']) - PERIODS[p] * 60
            if age < 0 or age > max(15, PERIODS[p] * 2) * 60:
                reasons.append(p + ':STALE_OR_UNCLOSED')
        except (ValueError, TypeError, KeyError):
            reasons.append(p + ':INVALID_TIMESTAMP')
        if c.get('timestamp_stale') is not False or c.get('quality_review_required') is not False or c.get('quality_verdict') != 'NO_NARROW_RUN_FLAG':
            reasons.append(p + ':QUALITY_NOT_PASSED')
    if frame is None or len(frame) < 50:
        return reasons + ['M5_OHLC_REQUIRED']
    try:
        sample = frame.tail(40)
        if not all(math.isfinite(float(v)) and float(v) > 0 for v in sample[['Open','High','Low','Close']].to_numpy().flatten()):
            reasons.append('M5_NONFINITE_PRICE')
        if any(r.High < max(r.Open,r.Close,r.Low) or r.Low > min(r.Open,r.Close,r.High) for r in sample.itertuples()):
            reasons.append('M5_OHLC_ORDER_INVALID')
        if frame.index.has_duplicates or not frame.index.is_monotonic_increasing:
            reasons.append('M5_INDEX_INVALID')
        m5 = next(c for c in charts if c['interval'] == '5min')
        if stamp(frame.index[-1]) != stamp(m5['last_closed_candle_utc']):
            reasons.append('M5_DIAGNOSTIC_MISMATCH')
        if frame.High.iloc[-1] <= frame.Low.iloc[-1]:
            reasons.append('LATEST_M5_NO_PRICE_RANGE')
    except (ValueError, TypeError, KeyError, AttributeError):
        reasons.append('M5_OHLC_INVALID')
    return reasons

def confirmation_check(plan, frame):
    result = {'verified': False, 'scope': 'closed_M5_price_event_only'}
    if not isinstance(plan, dict) or plan.get('status') != 'ENTRY_READY':
        return {**result, 'reason': 'NO_CONFIRMED_PLAN'}
    try:
        frame = frame.tail(40)
        e, direction = plan['confirmation'], plan['direction']
        if direction not in ('BUY','SELL') or len(frame) < 3:
            return {**result, 'reason': 'INVALID_INPUT'}
        start = frame.index[-1].isoformat()
        if stamp(e['candle_start_utc']) != stamp(start):
            return {**result, 'reason': 'NOT_CURRENT_M5'}
        a,b = frame.iloc[-2],frame.iloc[-1]
        kind = e['kind']
        if kind == 'ENGULFING':
            ok = (b.Close>b.Open and a.Close<a.Open and b.Open<=a.Close and b.Close>=a.Open) if direction=='BUY' else (b.Close<b.Open and a.Close>a.Open and b.Open>=a.Close and b.Close<=a.Open)
        elif kind == 'MSS':
            indices = [i for i,t in enumerate(frame.index) if stamp(t)==stamp(e['swing_candle_utc'])]
            if len(indices)!=1 or not 1<=indices[0]<len(frame)-2:
                return {**result, 'reason': 'SWING_NOT_VERIFIABLE'}
            i=indices[0]
            left,swing,right=frame.iloc[i-1],frame.iloc[i],frame.iloc[i+1]
            ok = (swing.High>=max(left.High,right.High) and a.Close<=swing.High<b.Close) if direction=='BUY' else (swing.Low<=min(left.Low,right.Low) and a.Close>=swing.Low>b.Close)
        else:
            return {**result, 'reason': 'UNSUPPORTED_EVENT'}
        return {**result,'verified':bool(ok),'kind':kind,'candle_start_utc':start,'reason':'PRICE_EVENT_VERIFIED' if ok else 'PRICE_EVENT_NOT_VERIFIED'}
    except (ValueError,TypeError,KeyError,AttributeError,IndexError):
        return {**result, 'reason': 'INVALID_EVIDENCE'}
