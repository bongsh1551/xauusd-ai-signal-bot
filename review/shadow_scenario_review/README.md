# Shadow scenario review patch set (not activated)

Target: bongsh1551/xauusd-ai-signal-bot, fix/shadow-scenario-review-20261106.
Baseline: 9254df113dcafd2328561465fa3ed3a38d2c616c.

This commit stores reproducible patch preparation and isolated tests only. It does NOT modify prompts/scalper.txt, the runtime entrypoint, main, workflows, or the deployed Worker. Do not describe this commit as a live fix.

prepare.py prompt INPUT OUTPUT verifies the exact original prompt Git blob, removes fixed budget/buffer instructions, resolves the WAIT/trade_plan contradiction and appends dynamic review fields. It writes a separate review output.
prepare.py worker INPUT OUTPUT applies exact-once changes to the reviewed opportunity_alerts.js: import the gate, require the explicit current review, use source-origin dedup and recheck current usable run before sending. A baseline mismatch aborts. Deployment must include scenario_review_gate.js alongside the patched module and preserve all unrelated modules/settings.

Run isolated gate tests: node --experimental-default-type=module review/shadow_scenario_review/test_review_gate.mjs

Retained: existing JSON status enums, Shadow analysis, chart freshness and quality checks in the host module, existing TTL/cooldown policy. New lifecycle fields are separate from status. Missing lifecycle fields deliberately suppress alerts after integration. Preserve source origin when refining a zone. The model supplies origin and review evidence; this is not independently verified market structure.

The provisional SL price check only blocks a scenario already beyond its supplied SL; it is not an OHLC structural-invalidation engine. The extra latest-run read reduces but does not eliminate concurrent-send races. No persistent lifecycle event ledger is added. No live cancellation notification is sent by this draft.

Prior evidence: the earlier full prompt transformation matched Git blob cbd336dac27030b8a4b684c5c01919106dfc6235; earlier draft passed 23 mocked-module tests and 11 isolated validator compatibility cases. This packaged revision has its own isolated gate tests. Those counts are separate and are not the repository suite or historical replay. The prompt preparation wording is revised here, so earlier exact output hashes do not apply to this revision.

Before activation: apply against freshly read source, inspect full generated diffs, test the composed Worker and repository, validate actual model requests/outputs, replay captured artifacts when available, then obtain explicit approval for integration/deployment. No real AI calls, Telegram sends, D1 writes, scheduler changes, Live enablement or automatic trades are authorized by this package.

Preparation script: prompt/worker exact-match fixture transformations, baseline rejection and duplicate-patch rejection were locally checked. These are fixture checks, not full generated-prompt/Worker integration tests.
