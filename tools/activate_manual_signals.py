"""Apply the formal manual-signal release; exact baselines or abort."""
from pathlib import Path
import hashlib
import ast

EXPECTED = {
 'main.py':'158b781038af3c66635113d4992029e164ef361a',
 'daily_memory.py':'56972d5f61f54fdb3c7eb1239e16b7ac91e28635',
 'publication_guard.py':'1727f9cbf2e891b2a7b1b1e1edf785c828dadb9f',
 '.github/workflows/run.yml':'232ab1f02164d1d72ffaa012ecd2c4c2b42d282d'}

def replace(text, old, new, count=1):
    if text.count(old) != count:
        raise ValueError('Baseline fragment changed: '+old[:80])
    return text.replace(old,new)

def transform(files):
    m=files['main.py']
    m=replace(m,"import daily_memory", "import daily_memory\nimport formal_signal_checks")
    m=replace(m,"{'historical_test', 'shadow'}", "{'historical_test', 'shadow', 'manual_signals'}")
    m=replace(m,"ANALYSIS_MODE must be historical_test or shadow", "Unsupported analysis mode; formal manual-only service uses manual_signals")
    m=replace(m,"HEADER = (", "HEADER = ('XAUUSD 正式人工交易信号服务' if ANALYSIS_MODE == 'manual_signals' else ")
    m=replace(m,"if ANALYSIS_MODE == 'shadow' else '\n\n【执行模式】仅历史分析测试，不是实时交易。\n')".replace('\n','\\n'),"if ANALYSIS_MODE == 'shadow' else formal_signal_checks.execution_instruction() if ANALYSIS_MODE == 'manual_signals' else '\n\n【执行模式】仅历史分析测试，不是实时交易。\n')".replace('\n','\\n'))
    m=replace(m,"title=f'XAU/USD {interval} | MYT UTC+8 | HISTORICAL TEST ONLY',", "title=(f'XAU/USD {interval} | MYT UTC+8' if ANALYSIS_MODE == 'manual_signals' else f'XAU/USD {interval} | MYT UTC+8 | HISTORICAL TEST ONLY'),")
    m=replace(m,"'data_validation_status': 'UNVERIFIED_TEST_ONLY',", "'data_validation_status': 'PROVIDER_OHLC_SCHEMA_CHECKED' if ANALYSIS_MODE == 'manual_signals' else 'UNVERIFIED_TEST_ONLY',")
    marker="        safety_gate = {'passed': not safety_reasons, 'reasons': safety_reasons}"
    block=r"""        if ANALYSIS_MODE == 'manual_signals':
            data_reasons = formal_signal_checks.quality_reasons(record, now, m5_frame)
            record['manual_data_quality_reasons'] = data_reasons
            record['confirmation_check'] = formal_signal_checks.confirmation_check(trade_plan, m5_frame)
            safety_reasons = list(data_reasons)
            if isinstance(trade_plan, dict) and trade_plan.get('status') == 'ENTRY_READY' and not record['confirmation_check']['verified']:
                safety_reasons.append('M5_CONFIRMATION_NOT_VERIFIED')
            model_states = re.findall(r'^\s*状态\s*[:：]\s*(WAIT|APPROACH|CONFIRMED)\b', analysis.replace('**', ''), re.M)
            if model_states == ['WAIT'] and any(z.get('status') == 'APPROACH' for z in (market_watch or {}).get('zones', [])):
                safety_reasons.append('INCONSISTENT_WAIT_ZONE_STATUS')
"""
    m=replace(m,marker,block+marker)
    m=replace(m,"'trade_plan': record.get('trade_plan'),", "'trade_plan': record.get('trade_plan'),\n        'confirmation_check': record.get('confirmation_check'),",2)
    m=replace(m,"    usable = not quality_reasons", "    quality_reasons.extend(record.get('manual_data_quality_reasons', []))\n    usable = not quality_reasons")
    m=replace(m,"record.get('mode') == 'live',", "record.get('mode') in ('live', 'manual_signals'),")
    m=replace(m,"        if ANALYSIS_MODE == 'shadow':\n            # Shadow analysis is delivered to Cloudflare only.", "        if ANALYSIS_MODE in {'shadow', 'manual_signals'}:\n            # Analysis is delivered to Cloudflare; it alone handles conditional notifications.")
    m=replace(m,"'reason': 'SHADOW_ANALYSIS_SENT_TO_CLOUDFLARE_ONLY'", "'reason': 'FORMAL_ANALYSIS_SYNCED' if ANALYSIS_MODE == 'manual_signals' else 'SHADOW_ANALYSIS_SENT_TO_CLOUDFLARE_ONLY'")
    m=replace(m,"'reason': 'SHADOW_MODE_NO_PLAN_UPLOAD'", "'reason': 'LEGACY_ENDPOINT_DISABLED' if ANALYSIS_MODE == 'manual_signals' else 'SHADOW_MODE_NO_PLAN_UPLOAD'")
    m=replace(m,"Shadow analysis delivered to Cloudflare; no routine Telegram message; no plan upload or trade execution; Journal:", "Analysis synced; conditional manual-signal delivery handled by Cloudflare; no trade execution; Journal:")
    files['main.py']=m
    files['daily_memory.py']=replace(files['daily_memory.py'],"('historical_test', 'shadow', 'live')", "('historical_test', 'shadow', 'live', 'manual_signals')")
    g=files['publication_guard.py']
    marker='    runner.pipeline.upload_plan = guarded_upload'
    g=replace(g,marker,"    if runner.pipeline.ANALYSIS_MODE == 'manual_signals':\n        install(runner)\n        install_zone_levels(runner)\n        return runner.main()\n"+marker)
    files['publication_guard.py']=g
    w=files['.github/workflows/run.yml']
    w=replace(w,'Run signal bot with SenseNova (shadow mode)','Run formal XAUUSD manual signal service')
    w=replace(w,'ANALYSIS_MODE: shadow','ANALYSIS_MODE: manual_signals')
    w=replace(w,'MARKET_MEMORY_MODE: shadow','MARKET_MEMORY_MODE: manual_signals')
    w=w.replace('daily-market-memory-','daily-market-memory-manual-')
    files['.github/workflows/run.yml']=w
    for name,text in files.items():
        if name.endswith('.py'):ast.parse(text,filename=name)
    return files

if __name__=='__main__':
    files={}
    for name,expected in EXPECTED.items():
        data=Path(name).read_bytes()
        blob=hashlib.sha1(b'blob '+str(len(data)).encode()+b'\0'+data).hexdigest()
        if blob!=expected:raise ValueError('File changed; reread before activation: '+name)
        files[name]=data.decode('utf-8')
    for name,text in transform(files).items():Path(name).write_text(text,encoding='utf-8')
