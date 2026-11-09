import base64
import hashlib
import hmac
import json
import unittest
from types import SimpleNamespace
from unittest.mock import MagicMock

from app import create_app, line_text


class WebhookTests(unittest.TestCase):
    def setUp(self):
        self.line = MagicMock()
        self.ai = MagicMock()
        self.ai.responses.create.return_value = SimpleNamespace(output_text="請與班導討論。")
        self.client = create_app({
            "LINE_CHANNEL_ACCESS_TOKEN": "test-token", "LINE_CHANNEL_SECRET": "test-secret",
            "OPENAI_API_KEY": "test-key", "TEACHER_LINE_ID": "Uteacher",
            "OPENAI_MODEL": "gpt-5.5",
        }, self.line, self.ai).test_client()

    def send(self, message=None, signature=None):
        events = [] if message is None else [{
            "type": "message", "message": {"type": "text", "id": "123", "text": message, "quoteToken": "quote-token"},
            "timestamp": 1793923200000, "source": {"type": "user", "userId": "Uparent"},
            "replyToken": "reply-token", "webhookEventId": "event-123",
            "deliveryContext": {"isRedelivery": False}, "mode": "active",
        }]
        body = json.dumps({"destination": "Ubot", "events": events}, ensure_ascii=False)
        digest = base64.b64encode(hmac.new(b"test-secret", body.encode(), hashlib.sha256).digest()).decode()
        return self.client.post("/webhook", data=body.encode(), content_type="application/json",
                                headers={"X-Line-Signature": signature or digest})

    def text(self):
        return self.line.reply_message.call_args.args[0].messages[0].text

    def test_faq_skips_ai(self):
        for question, answer in [("我要請假", "8 點前"), ("段考", "班級行事曆"),
                                 ("家長日", "你的時程"), ("學費", "[銀行帳號]")]:
            with self.subTest(question=question):
                self.assertEqual(self.send(question).status_code, 200)
                self.assertIn(answer, self.text())
        self.ai.responses.create.assert_not_called()
        self.line.push_message.assert_not_called()

    def test_ai_fallback(self):
        self.assertEqual(self.send("孩子如何培養閱讀習慣？").status_code, 200)
        self.assertTrue(self.text().startswith("以下為 AI 回覆"))
        params = self.ai.responses.create.call_args.kwargs
        self.assertEqual(params["model"], "gpt-5.5")
        self.assertFalse(params["store"])

    def test_ga700_manual_reply_uses_parameter_sections_and_pages(self):
        self.ai.responses.create.return_value.output_text = "頻率顯示用 o1-03 [1]。"
        self.assertEqual(self.send("GA700單位設定").status_code, 200)
        request = self.ai.responses.create.call_args.kwargs
        passages = json.loads(request["input"])["passages"]
        self.assertTrue(any(p["page"] == 416 and p["text"].startswith("■o1-03") for p in passages))
        self.assertTrue(any(p["page"] == 417 and p["text"].startswith("■o1-04") for p in passages))
        self.assertIn("PDF 第 416 頁", self.text())
        self.line.push_message.assert_not_called()

    def test_manual_no_match_never_asks_ai_to_guess(self):
        for message in ("GA700 世界盃冠軍", "查手冊 GA500 單位設定"):
            self.assertEqual(self.send(message).status_code, 200)
            self.assertIn("手冊未找到", self.text())
        self.ai.responses.create.assert_not_called()

    def test_manual_reply_shows_source_excerpt_when_ai_is_unavailable(self):
        self.ai.responses.create.side_effect = RuntimeError("simulated")
        self.assertEqual(self.send("GA700 o1-03").status_code, 200)
        self.assertIn("手冊原文節錄", self.text())
        self.assertIn("PDF 第 416 頁", self.text())
        self.assertIn("PDF 第 417 頁", self.text())

    def test_sensitive_precedes_faq_and_has_two_paths(self):
        self.assertEqual(self.send("因霸凌想死，明天請假").status_code, 200)
        notice = self.line.push_message.call_args.args[0]
        self.assertEqual(notice.to, "Uteacher")
        self.assertIn("Uparent", notice.messages[0].text)
        self.assertIn("因霸凌想死，明天請假", notice.messages[0].text)
        self.assertIn("+08:00", notice.messages[0].text)
        self.assertIn("已通知班導", self.text())
        self.ai.responses.create.assert_not_called()

    def test_all_sensitive_words(self):
        for word in ("霸凌", "自殺", "自傷", "被打", "不想活", "想死", "緊急", "自 傷"):
            with self.subTest(word=word):
                self.assertEqual(self.send(word).status_code, 200)
                self.assertIn("已通知班導", self.text())

    def test_push_failure_still_replies_truthfully(self):
        self.line.push_message.side_effect = RuntimeError("simulated")
        self.assertEqual(self.send("孩子被打").status_code, 200)
        self.assertIn("無法確認", self.text())
        self.assertNotIn("我已通知", self.text())

    def test_emergency_contact_keeps_placeholder(self):
        self.assertEqual(self.send("緊急聯絡").status_code, 200)
        self.assertIn("[班導手機]", self.text())

    def test_ai_failure_and_empty_output(self):
        self.ai.responses.create.side_effect = RuntimeError("simulated")
        self.assertEqual(self.send("閱讀").status_code, 200)
        self.assertIn("暫時無法回覆", self.text())
        self.ai.responses.create.side_effect = None
        self.ai.responses.create.return_value.output_text = " "
        self.assertEqual(self.send("閱讀").status_code, 200)
        self.assertIn("暫時無法回覆", self.text())

    def test_bad_signature_has_no_side_effects(self):
        self.assertEqual(self.send("自傷", signature="invalid").status_code, 400)
        self.line.push_message.assert_not_called()
        self.line.reply_message.assert_not_called()
        self.ai.responses.create.assert_not_called()

    def test_missing_signature(self):
        self.assertEqual(self.client.post("/webhook", json={"events": []}).status_code, 400)

    def test_verify_empty_events_and_health(self):
        self.assertEqual(self.send().status_code, 200)
        self.assertEqual(self.client.get("/healthz").json, {"status": "ok"})

    def test_reply_failure_returns_retryable_error(self):
        self.line.reply_message.side_effect = RuntimeError("simulated")
        self.assertEqual(self.send("請假").status_code, 500)

    def test_utf16_length(self):
        self.assertLessEqual(len(line_text("😀" * 5000).encode("utf-16-le")) // 2, 5000)


if __name__ == "__main__":
    unittest.main()
