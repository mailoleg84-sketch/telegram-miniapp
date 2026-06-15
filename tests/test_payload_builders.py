"""payload_builders._chat_usage_payload: суточный AI-лимит/расход в ответе."""
import unittest
from unittest.mock import patch

from webapp import payload_builders
from webapp.payload_builders import _chat_usage_payload


class ChatUsagePayloadTests(unittest.TestCase):
    def test_none_stats_unlimited_by_default(self):
        with patch.object(payload_builders, "AI_DAILY_MESSAGE_LIMIT", 0):
            p = _chat_usage_payload(None)
        self.assertEqual(p["used_today"], 0)
        self.assertTrue(p["unlimited"])
        self.assertIsNone(p["daily_limit"])
        self.assertIsNone(p["remaining_today"])
        self.assertFalse(p["limit_reached"])
        self.assertEqual(p["cost_usd_today"], 0.0)

    def test_counts_tokens_and_cost(self):
        with patch.object(payload_builders, "AI_DAILY_MESSAGE_LIMIT", 0):
            p = _chat_usage_payload({
                "requests": 5, "input_tokens": 100, "output_tokens": 50,
                "total_tokens": 150, "cost_usd": 0.0123,
            })
        self.assertEqual(p["used_today"], 5)
        self.assertEqual(p["total_tokens_today"], 150)
        self.assertEqual(p["cost_usd_today"], 0.0123)

    def test_limit_reached(self):
        with patch.object(payload_builders, "AI_DAILY_MESSAGE_LIMIT", 3):
            p = _chat_usage_payload({
                "requests": 5, "input_tokens": 0, "output_tokens": 0,
                "total_tokens": 0, "cost_usd": 0,
            })
        self.assertFalse(p["unlimited"])
        self.assertEqual(p["daily_limit"], 3)
        self.assertEqual(p["remaining_today"], 0)
        self.assertTrue(p["limit_reached"])


if __name__ == "__main__":
    unittest.main()
