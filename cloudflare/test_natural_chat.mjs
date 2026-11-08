import assert from 'node:assert/strict';
import {mkdtemp,copyFile,writeFile,rm} from 'node:fs/promises';
import {tmpdir} from 'node:os';
import {join} from 'node:path';
import {pathToFileURL} from 'node:url';
const dir=await mkdtemp(join(tmpdir(),'goldscalp-chat-'));
try {
 await copyFile(new URL('./natural_chat.mjs',import.meta.url),join(dir,'natural_chat.mjs'));
 await writeFile(join(dir,'chat_market_clock_baseline.mjs'),`export function chatClock(meta){return meta||{status:'INVALID'};} export function fixedChatReply(){return 'TIME_FROM_BASELINE';}`);
 const m=await import(pathToFileURL(join(dir,'natural_chat.mjs')));
 for(const status of ['STALE','DELAYED','INVALID','OUTSIDE_SERVICE']){const c={status};assert.equal(m.fixedChatReply(c,'哈哈'),null);assert.equal(m.fixedChatReply(c,'解释 MSS'),null);assert.ok(m.fixedChatReply(c,'现在能买吗'));assert.ok(m.fixedChatReply(c,'那可以了吗'));assert.ok(!m.finishChatReply('BUY 9999',c,'现在能买吗').includes('9999'));}
 assert.equal(m.finishChatReply('我在呢。',null,'哈哈'),'我在呢。');
 assert.equal(m.fixedChatReply({status:'STALE'},'最新图是什么时间'),'TIME_FROM_BASELINE');
 assert.equal(m.intent('现在复盘后能买了吗'),'MARKET');
 assert.equal(m.intent('刚才为什么等'),'REVIEW');
 assert.ok(!m.chatPrompt({status:'STALE'},'PRIVATE_PRICE_9999','','解释 MSS').includes('PRIVATE_PRICE_9999'));
 assert.ok(m.finishChatReply('等确认。',{status:'FRESH',m5_close_myt:'TEST_TIME'},'现在行情呢').includes('TEST_TIME'));
 console.log('Natural-chat wrapper tests passed. Mock clock only; no model, DB, Telegram, or deployment exercised.');
} finally {await rm(dir,{recursive:true,force:true});}
