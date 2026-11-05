import unittest
import json

from sensenova_runner import validate_analysis

NL = chr(10)

def analysis(status="WAIT", zones=None, plan=None):
    zones = [] if zones is None else zones
    text = "状态：" + status + NL
    text += "```market_watch" + NL + json.dumps({"zones": zones}, ensure_ascii=False) + NL + "```"
    if plan is not None:
        text += NL + "```trade_plan" + NL + json.dumps(plan, ensure_ascii=False) + NL + "```"
    return text

def valid_zone():
    return {"direction": "BUY", "zone_type": "demand", "low": 2300.0, "high": 2305.0,
            "status": "WAIT", "entry_trigger": "M5 rejection and MSS",
            "cancel_condition": "M15 closes below zone"}

def valid_plan():
    return {"status": "ENTRY_READY", "direction": "BUY", "zone": "2300-2305",
            "entry_trigger": "M5 displacement and MSS", "stop_loss": 2295.0,
            "take_profits": [2310.0], "confidence": "中",
            "reason": "Bullish structure continuation", "valid_minutes": 15}

class SenseNovaContractTests(unittest.TestCase):
    def test_wait_with_empty_zones_is_valid(self):
        self.assertEqual(validate_analysis(analysis()), "WAIT")

    def test_approach_with_valid_zone_is_valid(self):
        self.assertEqual(validate_analysis(analysis("APPROACH", [valid_zone()])), "APPROACH")

    def test_confirmed_with_valid_plan_is_valid(self):
        self.assertEqual(validate_analysis(analysis("CONFIRMED", [valid_zone()], valid_plan())), "CONFIRMED")

    def test_rejects_more_than_two_zones(self):
        with self.assertRaises(RuntimeError):
            validate_analysis(analysis("APPROACH", [valid_zone()] * 3))

    def test_rejects_inverted_zone_bounds(self):
        zone = valid_zone()
        zone["low"], zone["high"] = 2310.0, 2300.0
        with self.assertRaises(RuntimeError):
            validate_analysis(analysis("APPROACH", [zone]))

    def test_rejects_missing_zone_trigger(self):
        zone = valid_zone()
        zone["entry_trigger"] = ""
        with self.assertRaises(RuntimeError):
            validate_analysis(analysis("APPROACH", [zone]))

    def test_rejects_confirmed_without_plan(self):
        with self.assertRaises(RuntimeError):
            validate_analysis(analysis("CONFIRMED", [valid_zone()]))

    def test_rejects_plan_on_wait(self):
        with self.assertRaises(RuntimeError):
            validate_analysis(analysis("WAIT", [], valid_plan()))

    def test_rejects_buy_target_below_stop(self):
        plan = valid_plan()
        plan["take_profits"] = [2290.0]
        with self.assertRaises(RuntimeError):
            validate_analysis(analysis("CONFIRMED", [], plan))

    def test_rejects_non_numeric_stop_loss(self):
        plan = valid_plan()
        plan["stop_loss"] = "2295"
        with self.assertRaises(RuntimeError):
            validate_analysis(analysis("CONFIRMED", [], plan))

if __name__ == "__main__":
    unittest.main()
