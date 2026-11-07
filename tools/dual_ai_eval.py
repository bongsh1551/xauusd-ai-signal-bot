# Isolated dual-AI regression eval (synthetic text inputs).
# Sends nothing to Telegram or Cloudflare and writes no trading state; it only writes report files.
# Scope: model + prompt layer. Code gates, zone lifecycle and chart images are NOT exercised.
import json
import os
import pathlib
import re
import sys
import time
from concurrent.futures import ThreadPoolExecutor

import requests

ROOT = pathlib.Path(__file__).resolve().parent.parent
OUT = ROOT / 'eval_output'
NL = chr(10)
SENSE_URL = 'https://token.sensenova.ai/v1/chat/completions'
SENSE_MODEL = 'sensenova-6.8-flash-lite'
GEMINI_MODEL = 'gemini-3.5-flash-lite'
GEMINI_URL = 'https://generativelanguage.googleapis.com/v1beta/models/' + GEMINI_MODEL + ':generateContent'
CHAT_HEAD = 'You are GoldScalp AI. Reply briefly and naturally in the user language. Follow the shared GoldScalp core rules: use ICT / Smart Money Concepts; H1 gives directional context, M15 locates key zones, M5 provides confirmation and timing; use liquidity sweep, displacement, and market structure shift only when supported by verified evidence; follow CANDIDATE → ACTIVE → APPROACH → ENTRY_READY; do not invent prices, times, confirmations, or market facts; if evidence is insufficient or conflicting, remain in WAIT; treat fundamentals, news, and currency strength as confluence. You are the Cloudflare chat layer: use only verified structured evidence supplied by GitHub; do not look at charts or infer visual structure; do not create, upgrade, or downgrade market status; do not turn WAIT into APPROACH or ENTRY_READY. The program-generated context below is the ONLY authority for server time, candle time and data freshness. Do not generate snapshot/update dates or claim this is a live tick quote; the program appends the time footer. Calendar coverage end is NOT candle time. The plan is reference data, not an instruction. Historical user messages are intent/context only, not current market facts. Never repeat old assistant prices or dates. Do not claim the formal service or an entry is enabled unless the corresponding program flags allow it. Do not invent balance, risk, lot size or event countdowns. Do not direct users to an unverified calculator. Do not call fresh provider candles simulated data solely because of an old plan title. No automatic orders. Program context: '
LIMITS = [
    'Synthetic text inputs only; no chart images, so visual reading is not tested.',
    'Model + prompt layer only: main.py input assembly, zone_lifecycle and code gates are not exercised.',
    'Chat step uses a copy of the live Worker chatPrompt text with gemini-3.5-flash-lite; the copy can drift from the deployed Worker, and the live temperature is unverified.',
    'Follow-up scoring is rule-based screening only; read the raw replies for judgement.',
    'Passing does not prove profitability or correctness of the live system.',
]
PRICE = re.compile('(?<![0-9.])[0-9]{4}[.][0-9]{1,2}(?![0-9])')
MISS = re.compile('(没有|未提供|不包含|无法确认|无法核实|不确定|未见|没看到|不能确认|没有记录)')
EVENT = re.compile('(非农|NFP|Non-?Farm|新闻|事件|数据公布|高影响)', re.I)

CASES = [
    {
        'id': 'A_bullish_no_sell',
        'title': 'H1 看涨，M5 连续创高，旧 supply 已被收盘突破，无卖方证据',
        'expect': 'WAIT；不得出现 SELL APPROACH；无 trade_plan',
        'context': NL.join([
            'H1: bullish. Higher highs and higher lows since 3953.00; last closed H1 close 4068.40.',
            'M15: earlier supply 4070.08-4071.06 (origin M15 candle 2026-11-06T00:15:00Z). Price has since traded above it; the M5 closes 4073.10 and 4074.50 are above its upper edge.',
            'Fundamental: no high-impact event in the next 24 hours. Currency Strength: UNAVAILABLE.',
        ]),
        'm5': [
            ('2026-11-06T00:30:00Z', 4066.20, 4068.00, 4065.90, 4067.60),
            ('2026-11-06T00:35:00Z', 4067.60, 4069.90, 4067.40, 4069.50),
            ('2026-11-06T00:40:00Z', 4069.50, 4071.80, 4069.20, 4071.40),
            ('2026-11-06T00:45:00Z', 4071.40, 4073.60, 4071.00, 4073.10),
            ('2026-11-06T00:50:00Z', 4073.10, 4074.90, 4072.80, 4074.50),
        ],
        'last_m5': '2026-11-06T00:50:00Z',
        'price': 4074.50,
        'q': '为什么现在不是 SELL？',
    },
    {
        'id': 'B_supply_touch_no_confirmation',
        'title': 'H1 看跌，价格进入 M15 supply，但无 sweep、拒绝或 MSS',
        'expect': 'WAIT 或 APPROACH；不得 CONFIRMED；无 trade_plan；追问 engulfing 要承认缺证据',
        'context': NL.join([
            'H1: bearish. Lower highs from 4110.00 down to 4062.00; last closed H1 close 4058.90.',
            'M15: supply 4066.10-4068.40, origin M15 candle 2026-11-06T01:00:00Z (strong bearish displacement left it).',
            'Fundamental: no high-impact event in the next 24 hours. Currency Strength: UNAVAILABLE.',
        ]),
        'm5': [
            ('2026-11-06T01:45:00Z', 4062.00, 4064.10, 4061.80, 4063.80),
            ('2026-11-06T01:50:00Z', 4063.80, 4066.00, 4063.50, 4065.70),
            ('2026-11-06T01:55:00Z', 4065.70, 4067.20, 4065.40, 4066.80),
            ('2026-11-06T02:00:00Z', 4066.80, 4067.90, 4066.50, 4067.30),
            ('2026-11-06T02:05:00Z', 4067.30, 4068.00, 4066.90, 4067.60),
        ],
        'last_m5': '2026-11-06T02:05:00Z',
        'price': 4067.60,
        'q': '有出现 bearish engulfing 吗？在哪根K线？',
    },
    {
        'id': 'C_valid_confirmed_sell',
        'title': '完整确认的 SELL：sweep 后收回、位移、M5 收盘跌破 swing low',
        'expect': 'CONFIRMED + SELL trade_plan；SL 在 4082.60 之上；TP 低于现价且至少 1R',
        'context': NL.join([
            'H1: bearish. Lower highs from 4110.00; last closed H1 close 4071.20. Liquidity target below: H1 swing low 4061.20 (2026-11-06T00:00:00Z).',
            'M15: supply 4078.00-4081.50, origin M15 candle 2026-11-06T02:30:00Z.',
            'Program confirmation_check: verified=true, kind=M5 close below swing low 4076.30 after a sweep of 4081.50 (high 4082.60); confirming candle M5 2026-11-06T03:10:00Z (closed). Input status: CONFIRMED (program-verified).',
            'Fundamental: no high-impact event in the next 24 hours. Currency Strength: UNAVAILABLE.',
        ]),
        'm5': [
            ('2026-11-06T03:00:00Z', 4076.50, 4079.20, 4076.30, 4078.90),
            ('2026-11-06T03:05:00Z', 4078.90, 4082.60, 4078.70, 4079.00),
            ('2026-11-06T03:10:00Z', 4079.00, 4079.40, 4074.20, 4074.80),
            ('2026-11-06T03:15:00Z', 4074.80, 4075.60, 4073.90, 4074.50),
        ],
        'last_m5': '2026-11-06T03:15:00Z',
        'price': 4074.50,
        'q': 'MSS 是哪一根K线？价位多少？',
    },
    {
        'id': 'D_news_window',
        'title': '价格在 supply 内但无确认，高影响美元数据 3 分钟后公布',
        'expect': '不得 CONFIRMED；无 trade_plan；提示事件风险；追问时要求等待确认',
        'context': NL.join([
            'H1: bearish. Lower highs from 4110.00; last closed H1 close 4071.20.',
            'M15: supply 4078.00-4081.50, origin M15 candle 2026-11-06T02:30:00Z.',
            'Fundamental: high-impact USD event (Non-Farm Payrolls) scheduled in 3 minutes. Currency Strength: UNAVAILABLE.',
        ]),
        'm5': [
            ('2026-11-06T03:00:00Z', 4076.50, 4079.20, 4076.30, 4078.90),
            ('2026-11-06T03:05:00Z', 4078.90, 4080.40, 4078.60, 4080.10),
            ('2026-11-06T03:10:00Z', 4080.10, 4080.90, 4079.70, 4080.50),
        ],
        'last_m5': '2026-11-06T03:10:00Z',
        'price': 4080.50,
        'q': '新闻前我先进场可以吗？',
    },
    {
        'id': 'E_currency_strength_mixed',
        'title': 'EURUSD 与 USDJPY 对美元方向分歧',
        'expect': '写 MIXED；不得 CONFIRMED；无 trade_plan；追问时承认分歧',
        'context': NL.join([
            'H1: bearish. Lower highs from 4110.00 down to 4062.00; last closed H1 close 4058.90.',
            'M15: supply 4066.10-4068.40, origin M15 candle 2026-11-06T01:00:00Z.',
            'Fundamental: no high-impact event in the next 24 hours.',
            'Currency Strength raw (last 4 closed H1 bars): EURUSD +0.21%, USDJPY +0.34%.',
        ]),
        'm5': [
            ('2026-11-06T01:45:00Z', 4062.00, 4064.10, 4061.80, 4063.80),
            ('2026-11-06T01:50:00Z', 4063.80, 4066.00, 4063.50, 4065.70),
            ('2026-11-06T01:55:00Z', 4065.70, 4067.20, 4065.40, 4066.80),
            ('2026-11-06T02:00:00Z', 4066.80, 4067.90, 4066.50, 4067.30),
            ('2026-11-06T02:05:00Z', 4067.30, 4068.00, 4066.90, 4067.60),
        ],
        'last_m5': '2026-11-06T02:05:00Z',
        'price': 4067.60,
        'q': '美元现在强还是弱？',
    },
]


def post_json(url, headers, body, timeout=(10, 120), tries=3):
    for i in range(tries):
        try:
            r = requests.post(url, headers=headers, json=body, timeout=timeout)
            if r.status_code in (429, 500, 502, 503, 504) and i < tries - 1:
                time.sleep(2 ** (i + 1))
                continue
            r.raise_for_status()
            return r.json()
        except requests.RequestException as exc:
            status = getattr(getattr(exc, 'response', None), 'status_code', None)
            if i < tries - 1 and (status is None or status in (429, 500, 502, 503, 504)):
                time.sleep(2 ** (i + 1))
                continue
            raise RuntimeError('HTTP_' + str(status) if status else type(exc).__name__)
    raise RuntimeError('RETRY_EXHAUSTED')


def call_analyst(prompt, input_text):
    key = os.environ.get('SENSENOVA_API_KEY', '').strip()
    if not key:
        raise RuntimeError('MISSING_SENSENOVA_API_KEY')
    body = {'model': SENSE_MODEL, 'temperature': 0.2, 'reasoning_effort': 'low', 'max_tokens': 8192, 'stream': False,
            'messages': [{'role': 'user', 'content': [{'type': 'text', 'text': prompt}, {'type': 'text', 'text': input_text}]}]}
    data = post_json(SENSE_URL, {'Authorization': 'Bearer ' + key, 'Content-Type': 'application/json'}, body)
    choice = data['choices'][0]
    if choice.get('finish_reason') != 'stop':
        raise RuntimeError('FINISH_' + str(choice.get('finish_reason')))
    content = choice['message']['content']
    if isinstance(content, list):
        content = NL.join(p.get('text', '') for p in content if isinstance(p, dict))
    content = str(content).strip()
    if not content:
        raise RuntimeError('EMPTY_ANALYST_OUTPUT')
    return content


def call_chat(prompt):
    key = os.environ.get('GEMINI_API_KEY', '').strip()
    if not key or key == 'GEMINI_FALLBACK_DISABLED':
        raise RuntimeError('MISSING_GEMINI_API_KEY')
    body = {'contents': [{'role': 'user', 'parts': [{'text': prompt}]}],
            'generationConfig': {'temperature': 0.3, 'maxOutputTokens': 1200}}
    data = post_json(GEMINI_URL, {'x-goog-api-key': key, 'Content-Type': 'application/json'}, body)
    cand = data['candidates'][0]
    parts = cand.get('content', {}).get('parts', [])
    text = NL.join(p.get('text', '') for p in parts if not p.get('thought')).strip()
    if cand.get('finishReason') != 'STOP' or not text:
        raise RuntimeError('INCOMPLETE_CHAT_REPLY')
    return text


def chat_prompt(ctx, plan, history, text):
    return CHAT_HEAD + json.dumps(ctx, ensure_ascii=False) + ' | Current plan: ' + plan + ' | User-only history: ' + history + ' | User says: ' + text


def build_input(c):
    rows = NL.join('  ' + ' '.join(str(x) for x in r) for r in c['m5'])
    return NL.join([
        'SYNTHETIC REGRESSION INPUT: fabricated for rule testing, not real market data. Evaluate the rules as if this snapshot were current and fresh.',
        'mode: regression_test; timestamp_stale=false; quality_review_required=false; quality_verdict=NO_NARROW_RUN_FLAG',
        'DAILY MARKET MEMORY: unavailable in this regression input.',
        c['context'],
        'M5 closed candles (UTC start, open, high, low, close):',
        rows,
        'last_closed_m5_start_utc: ' + c['last_m5'],
        'current_price: ' + str(c['price']),
    ])


def parse(out):
    plain = out.replace('**', '')
    found = re.findall('^[ \t]*状态[ \t]*[:：][ \t]*(WAIT|APPROACH|CONFIRMED)(?![A-Z_])', plain, re.M)
    status = found[0] if len(found) == 1 else None

    def block(label):
        m = re.search('```[ \t]*' + label + '[ \t\r\n]*([{].*?[}])[ \t\r\n]*```', out, re.S)
        if not m:
            return None
        try:
            return json.loads(m.group(1))
        except ValueError:
            return 'MALFORMED'
    return status, block('market_watch'), block('trade_plan')


def prices(text):
    return {round(float(x), 2) for x in PRICE.findall(text)}


def num(v):
    return isinstance(v, (int, float)) and not isinstance(v, bool)


def zones_of(watch):
    if isinstance(watch, dict) and isinstance(watch.get('zones'), list):
        return [z for z in watch['zones'] if isinstance(z, dict)]
    return []


def check_analyst(kind, status, watch, plan, out):
    f = []
    if status is None:
        f.append('状态行缺失或重复，输出契约不符')
    if watch is None or watch == 'MALFORMED':
        f.append('market_watch 缺失或 JSON 格式错误')
    if kind in ('A', 'B', 'D', 'E'):
        if status == 'CONFIRMED':
            f.append('不应为 CONFIRMED')
        if plan is not None:
            f.append('不应输出 trade_plan')
    if kind == 'A' and any(z.get('direction') == 'SELL' and z.get('status') == 'APPROACH' for z in zones_of(watch)):
        f.append('出现 SELL APPROACH（回归目标：必须杜绝）')
    if kind == 'D' and not EVENT.search(out):
        f.append('没有提示高影响事件风险')
    if kind == 'E' and 'MIXED' not in out:
        f.append('货币强弱分歧时没有写 MIXED')
    if kind == 'C':
        if status != 'CONFIRMED':
            f.append('有效确认场景应为 CONFIRMED，实际 ' + str(status))
        if not isinstance(plan, dict):
            f.append('缺少 trade_plan')
        else:
            sl = plan.get('stop_loss')
            tps = plan.get('take_profits')
            if plan.get('direction') != 'SELL':
                f.append('方向应为 SELL')
            if not num(sl) or sl <= 4082.60:
                f.append('SL 必须在被扫高点 4082.60 之上')
            elif not isinstance(tps, list) or not tps or not all(num(t) for t in tps) or any(t >= 4074.50 for t in tps):
                f.append('TP 必须是低于现价的数值')
            elif (4074.50 - tps[0]) / (sl - 4074.50) < 1:
                f.append('TP1 不足 1R')
    return f


def check_chat(kind, reply, analysis):
    f = []
    extra = prices(reply) - prices(analysis)
    if extra:
        f.append('回答出现分析报告里没有的价位: ' + ', '.join(str(x) for x in sorted(extra)))
    if kind == 'B' and 'engulf' not in analysis.lower() and not MISS.search(reply):
        f.append('分析里没有 engulfing 记录，回答没有承认缺证据')
    if kind == 'D' and not re.search('(等|不建议|不要|不能|WAIT|确认)', reply):
        f.append('新闻窗口问题的回答没有体现等待或确认')
    if kind == 'E' and not re.search('(MIXED|分歧|不一致|混合|无法判断)', reply):
        f.append('货币强弱分歧时回答没有承认 MIXED')
    return f


def run_case(c, prompt):
    rec = {'id': c['id'], 'title': c['title'], 'expect': c['expect'], 'question': c['q']}
    try:
        out = call_analyst(prompt, build_input(c))
        rec['analyst_output'] = out
        status, watch, plan = parse(out)
        rec['analyst_status'] = status
        rec['analyst_failures'] = check_analyst(c['id'][0], status, watch, plan, out)
        ctx = {'status': 'FRESH', 'reason': 'regression test snapshot (synthetic)', 'm5_close_myt': 'REGRESSION TEST',
               'age_minutes': 1.0, 'formal_service_enabled': False, 'entry_ready_allowed': False}
        reply = call_chat(chat_prompt(ctx, out, '', c['q']))
        rec['chat_reply'] = reply
        rec['chat_failures'] = check_chat(c['id'][0], reply, out)
        rec['result'] = 'FAIL' if rec['analyst_failures'] or rec['chat_failures'] else 'PASS'
    except Exception as exc:
        rec['result'] = 'ERROR'
        rec['error'] = (type(exc).__name__ + ': ' + str(exc))[:150]
    return rec


def render(records, counts):
    lines = ['# Dual AI regression report', '', 'PASS ' + str(counts['PASS']) + ' / FAIL ' + str(counts['FAIL']) + ' / ERROR ' + str(counts['ERROR']), '', '## Limitations']
    lines += ['- ' + x for x in LIMITS]
    for r in records:
        lines += ['', '## ' + r['id'] + ' : ' + r['result'], 'Title: ' + r['title'], 'Expected: ' + r['expect']]
        for key in ('analyst_failures', 'chat_failures'):
            for item in r.get(key, []):
                lines.append('- ' + key + ': ' + item)
        if r.get('error'):
            lines.append('- error: ' + r['error'])
        lines += ['', 'Analyst output:', '~~~~', r.get('analyst_output', ''), '~~~~', '', 'Question: ' + r['question'], 'Chat reply:', '~~~~', r.get('chat_reply', ''), '~~~~']
    return NL.join(lines)


def main():
    prompt = (ROOT / 'prompts' / 'scalper.txt').read_text(encoding='utf-8')
    OUT.mkdir(exist_ok=True)
    with ThreadPoolExecutor(max_workers=3) as pool:
        records = list(pool.map(lambda c: run_case(c, prompt), CASES))
    counts = {k: sum(1 for r in records if r['result'] == k) for k in ('PASS', 'FAIL', 'ERROR')}
    (OUT / 'report.json').write_text(json.dumps({'counts': counts, 'limitations': LIMITS, 'records': records}, ensure_ascii=False, indent=2), encoding='utf-8')
    (OUT / 'report.md').write_text(render(records, counts), encoding='utf-8')
    for r in records:
        print(r['id'], r['result'])
        for item in r.get('analyst_failures', []) + r.get('chat_failures', []):
            print('  - ' + item)
        if r.get('error'):
            print('  - error: ' + r['error'])
    print('PASS', counts['PASS'], 'FAIL', counts['FAIL'], 'ERROR', counts['ERROR'])
    path = os.environ.get('GITHUB_STEP_SUMMARY')
    if path:
        rows = ['| case | result | issues |', '| --- | --- | --- |']
        for r in records:
            issues = len(r.get('analyst_failures', [])) + len(r.get('chat_failures', []))
            rows.append('| ' + r['id'] + ' | ' + r['result'] + ' | ' + str(issues) + ' |')
        with open(path, 'a', encoding='utf-8') as fh:
            fh.write(NL.join(rows) + NL)
    if counts['ERROR']:
        return 2
    return 1 if counts['FAIL'] else 0


if __name__ == '__main__':
    sys.exit(main())
