"""Prepare review outputs locally; never uploads, deploys or sends messages."""
from pathlib import Path
import hashlib
import re
import sys

BASE_PROMPT_BLOB = 'cbd336dac27030b8a4b684c5c01919106dfc6235'

DYNAMIC_REVIEW = '【结构、动能与历史情景的动态复核】\nH1 定方向背景，M15 找关键区域，M5 观察行为与确认。低周期反向 CHoCH/MSS 不自动推翻高周期 Bias，也不自动删除全部高周期区域。\n每轮用最新已收线 OHLC 判断旧情景应保留、暂停、调整或失效。反向位移出现时重新评估；动能冲突或依据不足则暂停预警，不必自动改成反方向交易。\n区域失效须说明来源周期、失效边界或被破坏的结构假设，以及对应 K 线时间与价位。区分影线、收盘突破、延续和回测，不统一套用一种判据。\n局部高低点不能只因价格接近就成为 Supply/Demand/OB；说明形成依据，无法核实则不输出候选。\n历史记录保留失效原因，但暂停或失效情景不作为当前机会重复提醒。\n\n【Market Watch 情景复核字段】\n保留原 JSON 字段，status 仍仅为 WAIT / APPROACH。每个 zone 增加：\nscenario_state：ACTIVE / PAUSED / INVALIDATED，表示交易情景状态，不等于整个高周期区域状态。\nsource_interval：5min / 15min / 1h，区域来源周期。\nsource_candle_utc：区域形成依据的 K 线 UTC 起始时间。同一区域调整边界时保留来源，不为绕过冷却改写。\nreviewed_m5_start_utc：本轮输入最新已收线 M5 的 UTC 起始时间，不是抓取时间或当前时间。\nreview_basis：本轮新证据、旧情景是否仍合理及动能冲突的简短复核。\nAPPROACH 必须同时满足情景 ACTIVE、区域本轮复核有效及价格接近或进入。触区本身不足以构成预警。\nPAUSED/INVALIDATED 的 status 必须为 WAIT。没有可核实区域则输出空 zones，不为填字段编造。\n历史记忆中的旧预算、旧缓冲说法只是旧记录，不是本轮指令；旧复核时间不得冒充本轮时间。\n'

def replace_line(text, prefix, replacement):
    pattern = '^' + re.escape(prefix) + '.*$'
    result, count = re.subn(pattern, lambda _: replacement, text, flags=re.M)
    if count != 1:
        raise ValueError('Expected exactly one line: ' + prefix)
    return result

def revise_prompt(data):
    blob = hashlib.sha1(b'blob ' + str(len(data)).encode() + b'\0' + data).hexdigest()
    if blob != BASE_PROMPT_BLOB:
        raise ValueError('Prompt baseline changed; reread before revising')
    text = data.decode('utf-8')
    text = replace_line(text, 'SL 先给出结构失效边界，再按测试参数', 'SL 依据当前交易假设的真实结构失效位置确定，引用周期、时间与价位。执行成本、点差、滑点和报价差异分开说明；资料不足则待核实，不机械增加固定金额。')
    text = replace_line(text, '目标计划风险 $50', '本轮不指定固定美元风险预算，不自行生成手数。仅在用户另行要求并提供真实参数后由外部程序核算。实际 entry、SL、费用或目标不足时，RR 待核算，不假装通过。')
    replacements = [
        ('按缓冲后的 SL 与可得费用估算', '按结构性 SL、实际 entry 与可得费用核算；资料不足时 RR 待核算'),
        ('SL参考：结构边界、缓冲后区域；信息不足则待定', 'SL参考：真实结构失效边界及证据；信息不足则待定'),
        ('3. WAIT 表示价格未接近；APPROACH 表示价格已接近或进入 zone。', '3. WAIT 包括未接近、情景暂停或证据不足；APPROACH 要求情景及区域本轮复核有效，且价格接近或进入。'),
        ('trade_plan.status 必须为 WAIT，不得生成 ENTRY_READY。', '分析状态必须为 WAIT，省略 trade_plan JSON，不得生成 ENTRY_READY。')
    ]
    for old, new in replacements:
        if text.count(old) != 1:
            raise ValueError('Prompt fragment changed: ' + old)
        text = text.replace(old, new, 1)
    text = text.rstrip() + '\n\n' + DYNAMIC_REVIEW
    if any(value in text for value in ('$1.00', '$0.60', '$50', '$45', '缓冲后')):
        raise ValueError('Legacy budget or buffer remains')
    return text

def revise_worker(source):
    changes = [
        ("const CHAT_ID = '6772154791';", "import { reviewAllowsAlert } from './scenario_review_gate.js';\nconst CHAT_ID = '6772154791';"),
        ("return zones.filter(z=>['BUY','SELL'].includes(z.direction)&&", "return zones.filter(z=>reviewAllowsAlert(z,meta)&&['BUY','SELL'].includes(z.direction)&&"),
        ("key:'opportunity:approach:v1:'", "key:'opportunity:approach:v2:'"),
        ("z.direction+':'+z.zone_type+':'+z.low.toFixed(2)+':'+z.high.toFixed(2)", "z.direction+':'+z.zone_type+':'+z.source_interval+':'+Date.parse(z.source_candle_utc)"),
        ("try{\n      const response=await fetch('https://api.telegram.org/bot'", "try{\n      const current=await env.DB.prepare('SELECT value FROM app_state WHERE key=?').bind('last_usable_run_id').first();\n      if(current?.value!==meta.run_id)continue;\n      const response=await fetch('https://api.telegram.org/bot'")
    ]
    for old, new in changes:
        if source.count(old) != 1:
            raise ValueError('Worker baseline changed: ' + old[:60])
        source = source.replace(old, new, 1)
    return source

if __name__ == '__main__':
    if len(sys.argv) != 4 or sys.argv[1] not in ('prompt', 'worker'):
        raise SystemExit('Usage: prepare.py prompt|worker INPUT OUTPUT')
    source, target = Path(sys.argv[2]), Path(sys.argv[3])
    if source.resolve() == target.resolve():
        raise ValueError('Write to a separate review output, not the source')
    result = revise_prompt(source.read_bytes()) if sys.argv[1] == 'prompt' else revise_worker(source.read_text(encoding='utf-8'))
    target.write_text(result, encoding='utf-8')
