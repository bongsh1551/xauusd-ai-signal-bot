import argparse
from pathlib import Path

p = argparse.ArgumentParser(description='Prepare local Worker sources only; never deploys.')
p.add_argument('source', type=Path, help='Directory containing downloaded live original.js and chat_market_clock.js')
p.add_argument('destination', type=Path, help='New output directory')
a = p.parse_args()
original = (a.source / 'original.js').read_text()
clock = (a.source / 'chat_market_clock.js').read_text()
replacements = [("from './chat_market_clock.js'", "from './natural_chat.mjs'"), ("AND role = 'user' AND created_at >= ? AND created_at >= datetime('now', '-24 hours')", "AND role IN ('user', 'assistant') AND created_at >= ? AND created_at >= datetime('now', '-24 hours')"), ('const cutoff = Date.now() < todayEightMyt ? todayEightMyt - 24 * 3600 * 1000 : todayEightMyt;', 'const cutoff = Date.now() - 24 * 3600 * 1000;')]
for old, new in replacements:
    if original.count(old) != 1:
        raise SystemExit('Baseline mismatch; no output written: ' + old)
    original = original.replace(old, new, 1)
for marker in ['export function chatClock', 'export function fixedChatReply']:
    if marker not in clock:
        raise SystemExit('Clock baseline mismatch; no output written')
wrapper = (Path(__file__).resolve().parents[1] / 'cloudflare' / 'natural_chat.mjs').read_text()
a.destination.mkdir(parents=True, exist_ok=False)
(a.destination / 'original.js').write_text(original)
(a.destination / 'chat_market_clock_baseline.mjs').write_text(clock)
(a.destination / 'natural_chat.mjs').write_text(wrapper)
print('Prepared local sources only. Other Worker modules and all bindings must be preserved separately. No deployment performed.')
