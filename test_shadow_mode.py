import unittest

import publication_guard


class ShadowPublicationTests(unittest.TestCase):
    def record(self, **overrides):
        value = {
            'mode': 'shadow',
            'safety_gate': {'passed': False, 'reasons': ['shadow mode: live publication disabled']},
            'trade_plan': None,
        }
        value.update(overrides)
        return value

    def test_shadow_wait_observation_may_be_sent(self):
        self.assertTrue(publication_guard.shadow_telegram_allowed(self.record()))

    def test_shadow_entry_ready_plan_is_never_sent(self):
        self.assertFalse(publication_guard.shadow_telegram_allowed(
            self.record(trade_plan={'status': 'ENTRY_READY'})))

    def test_live_record_does_not_use_shadow_exception(self):
        self.assertFalse(publication_guard.shadow_telegram_allowed(
            self.record(mode='live')))

    def test_shadow_requires_explicit_safety_block_reason(self):
        self.assertFalse(publication_guard.shadow_telegram_allowed(
            self.record(safety_gate={'passed': False, 'reasons': []})))


if __name__ == '__main__':
    unittest.main()
