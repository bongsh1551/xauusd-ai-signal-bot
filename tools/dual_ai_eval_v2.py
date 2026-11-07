import copy
import json
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import dual_ai_eval as base
from fundamentals import currency_strength

base.MISS = re.compile(base.MISS.pattern + '|未记录|尚未形成|尚未确认|未确认|尚无')
original_check_chat = base.check_chat

def check_chat(kind, reply, analysis):
    failures = original_check_chat(kind, reply, analysis)
    if kind == 'B' and not base.MISS.search(reply):
        failures.append('需要明确说明尚无已验证 engulfing，人工复核原文')
    if re.search(r'WAIT\s*[/／]\s*APPROACH|APPROACH\s*[/／]\s*WAIT', reply):
        failures.append('混写 WAIT/APPROACH，人工复核是否错误描述当前状态')
    return failures

def main():
    base.check_chat = check_chat
    strength = currency_strength(
        {'change_4h_pct': 0.21, 'stale': False},
        {'change_4h_pct': 0.34, 'stale': False})
    assert strength['status'] == 'MIXED'
    raw = next(c for c in base.CASES if c['id'].startswith('E_'))
    paired = copy.deepcopy(raw)
    paired['id'] = 'E_production_mixed_context'
    paired['title'] = '同题加生产 currency_strength() 结果；与原始涨幅题分开评分'
    paired['context'] += '\nProgram-computed Currency Strength: ' + json.dumps(strength)
    base.CASES.append(paired)
    base.LIMITS.append('v2 is diagnostic only; no production prompt changes. Raw E remains unchanged. Mixed-status screening can require human review. Timestamp and invented-level checks remain manual.')
    return base.main()

if __name__ == '__main__':
    sys.exit(main())
