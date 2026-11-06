"""Add zone-specific provisional structural levels to the existing analysis input."""
from copy import deepcopy

ZONE_LEVEL_INSTRUCTION = """
【区域专属 SL/TP：主动预警输出补充】
每个 market_watch.zones 元素增加以下字段，不改变原有字段：
stop_loss：有输入 OHLC/结构依据的数值；无法核实则 null。
take_profits：一到两个有输入依据的结构/流动性目标；无法核实则 []。
sl_basis：简短说明结构失效边界，引用周期、K线 UTC 时间和价位。
tp_basis：简短说明每个目标的结构或流动性依据，引用周期、时间和价位。
levels_status：固定为 PROVISIONAL。这些是等待确认的情景参考，不代表已经发生进场确认。
BUY 的 SL 必须低于 zone.low，所有 TP 必须高于 zone.high；SELL 相反。
SL/TP 属于该 zone，不得把另一区域或另一方向的价位混用。不得为填字段编造价位。
止损依据真实结构失效，不固定增加 $1 缓冲，不采用固定 $50 或 $45–55 风险预算，不生成手数。
若确认尚未发生，写清具体等待条件；条件未发生不得声称已确认。SL/TP 必须随结构失效重新评估。
提供 SL/TP 参考不等于允许自动交易；是否下单始终由用户决定。
""".strip()

def enrich_kwargs(kwargs):
    options = deepcopy(kwargs)
    parts = options['json']['contents'][0]['parts']
    for part in parts:
        if isinstance(part, dict) and isinstance(part.get('text'), str):
            lines = part['text'].splitlines()
            part['text'] = '\n'.join(line for line in lines if not (
                line.startswith('SL 先给出结构失效边界，再按测试参数') or
                line.startswith('目标计划风险 $50'))).replace(
                'SL参考：结构边界、缓冲后区域；信息不足则待定',
                'SL参考：真实结构失效边界；信息不足则待定')
    parts.append({'text': ZONE_LEVEL_INSTRUCTION})
    return options

def install_zone_levels(runner):
    if getattr(runner, '_zone_levels_installed', False):
        return
    original = runner.post
    def post(url, **kwargs):
        if url.startswith('https://generativelanguage.googleapis.com/'):
            kwargs = enrich_kwargs(kwargs)
        return original(url, **kwargs)
    runner.post = post
    runner._zone_levels_installed = True
