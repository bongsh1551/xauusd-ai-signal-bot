import json
import re
import sys
import uuid
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import dual_ai_eval as base
import dual_ai_eval_v2 as v2

RULES = '''【候选修复规则，仅隔离验证】
H1 bias 是方向背景，不是绝对禁止逆势交易；逆势须额外证据，不得写成绝对禁令。
结构曾确认不代表当前可入场。价格不在计划入场区、仍等待回调或额外确认时，不输出 ENTRY_READY 或 trade_plan；本轮用 WAIT/APPROACH，并分别说明历史确认与当前准备度。
OHLC 时间为 UTC 起始时间。M5 收盘时间=起始时间+5分钟；03:10 起始的K线在03:15收盘，不可称03:10收盘。没有时区依据不转换。
不得把 WAIT/APPROACH 并列当作当前状态。聊天只引用报告头部当前状态；正文和JSON冲突须指出冲突，不自行选一个或升级。
未提供 volume 时，不以放量/缩量作为已发生事实或确认条件。
未确认的 engulfing 明确说暂无经核实的形态，不编造K线。
EURUSD 上涨表示美元兑欧元走弱，USDJPY 上涨表示美元兑日元走强；分歧为 MIXED，不代表黄金必然方向。程序已提供强弱状态时不得擅自改写。
没有输入或明确计算依据，不新增精确结构价位。SL 若由结构边界推导，标注推导方法，不能冒充OHLC高低点。
'''
old_analyst = base.call_analyst
old_chat = base.call_chat
old_post = base.post_json

def analyst(prompt, text):
    return old_analyst(prompt + '\n' + RULES, text)

def chat(prompt):
    return old_chat(RULES + '\n' + prompt)

def post(*args, **kwargs):
    data = old_post(*args, **kwargs)
    if isinstance(data, dict) and isinstance(data.get('choices'), list):
        base.OUT.mkdir(exist_ok=True)
        saved = [{'finish_reason': c.get('finish_reason'), 'content': c.get('message', {}).get('content')} for c in data['choices']]
        (base.OUT / ('analyst-response-' + uuid.uuid4().hex + '.json')).write_text(json.dumps(saved, ensure_ascii=False), encoding='utf-8')
    return data

old_check = base.check_analyst

def check(kind, status, watch, plan, out):
    if kind != 'C':
        return old_check(kind, status, watch, plan, out)
    failures = old_check('B', status, watch, plan, out)
    if status not in ('WAIT', 'APPROACH'):
        failures.append('等待回调案例不得标为当前 CONFIRMED/ENTRY_READY')
    return failures

def main():
    base.call_analyst = analyst
    base.call_chat = chat
    base.post_json = post
    base.check_analyst = check
    base.MISS = re.compile(base.MISS.pattern + '|暂无')
    c = next(c for c in base.CASES if c['id'].startswith('C_'))
    c['title'] = '结构已确认但现价低于计划区域；必须等待回调，当前不可入场'
    c['expect'] = 'WAIT/APPROACH；无 trade_plan；明确区分历史确认与当前准备度'
    c['context'] += '\nCurrent entry readiness: false. Current price 4074.50 is outside planned entry zone 4078.00-4081.50. Historical structure confirmation is not current entry permission.'
    base.LIMITS.append('v3 loads candidate rule amendment for BOTH models; NOT deployed rules. Prior C expectation corrected. No in-zone ENTRY_READY positive case yet. Time/price provenance still requires manual review.')
    base.OUT.mkdir(exist_ok=True)
    (base.OUT / 'candidate-rules.txt').write_text(RULES, encoding='utf-8')
    return v2.main()

if __name__ == '__main__':
    sys.exit(main())
