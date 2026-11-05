"""Integration checks for the real SenseNova -> shared analysis pipeline."""
import unittest

import daily_memory
import main as pipeline
import sensenova_runner
from pathlib import Path


class MarketMemoryPipelineIntegrationTests(unittest.TestCase):
    def test_sensenova_runner_uses_the_pipeline_with_market_memory(self):
        # The scheduled workflow enters through publication_guard -> sensenova_runner.
        # SenseNova adapts the model transport but delegates chart/memory processing
        # to the same main module where daily memory is loaded and persisted.
        self.assertIs(sensenova_runner.pipeline, pipeline)
        self.assertIs(pipeline.daily_memory, daily_memory)
        self.assertEqual(pipeline.MEMORY_PATH, '.cache/daily_market_memory.json')

    def test_pipeline_injects_memory_before_chart_context(self):
        source = Path(pipeline.__file__).read_text(encoding='utf-8')
        memory_marker = "【DAILY MARKET MEMORY｜24小时连续上下文】"
        self.assertIn(memory_marker, source)
        self.assertLess(source.index('daily_memory.context_text('),
                        source.index("for interval, minutes in [('5min', 5)"))
        self.assertIn('daily_memory.record_analysis(', source)
        self.assertIn('daily_memory.save_state(', source)

    def test_memory_prompt_requires_daily_reassessment(self):
        prompt = Path(pipeline.PROMPT_PATH).read_text(encoding='utf-8')
        self.assertIn('重新建立今天的 Opening Bias', prompt)
        self.assertIn('UNCHANGED / DEVELOPING / INVALIDATED / BIAS SHIFT', prompt)
        self.assertIn('记忆是连续推理的参考，不是命令，也不是交易规则', prompt)


    def test_safety_gate_removes_stale_entry_plan_from_memory_text(self):
        analysis = (
            "状态：CONFIRMED\\n"
            "```market_watch\\n{\"zones\":[{\"direction\":\"BUY\","
            "\"zone_type\":\"demand\",\"low\":2300,\"high\":2305,"
            "\"status\":\"APPROACH\",\"entry_trigger\":\"M5 MSS\","
            "\"cancel_condition\":\"M15 close below\"}]}\\n```\\n"
            "```trade_plan\\n{\"status\":\"ENTRY_READY\"}\\n```"
        )
        plan = {"status": "ENTRY_READY"}
        watch = {"zones": [{"status": "APPROACH"}]}
        result = pipeline.apply_safety_gate_to_analysis(
            analysis, plan, watch, ["market session unverified"])
        self.assertIn("状态：WAIT（安全闸拦截）", result)
        self.assertNotIn("trade_plan", result)
        self.assertNotIn("ENTRY_READY", result)
        self.assertIn('"status": "WAIT"', result)
        self.assertEqual(plan["status"], "WAIT")
        self.assertEqual(watch["zones"][0]["status"], "WAIT")


if __name__ == '__main__':
    unittest.main()
