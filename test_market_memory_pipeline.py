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


if __name__ == '__main__':
    unittest.main()
