"""POST /learning-digest: authenticated, template-safe, never logs the message."""
import os
import sys
import unittest
from unittest.mock import patch

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

from flask import Flask

from config import Config
from routes.learning_digest import learning_digest_bp, template_param

MESSAGE = "Shining Smiles — Learning update, Thu 08 Oct\n\nTariro (Grade 5 Gold):\n• Due tomorrow: Maths — Fractions"
BODY = {"school_id": 3, "phone": "+263771234567", "school_name": "Shining Smiles", "day_label": "Thu 08 Oct",
        "message": MESSAGE, "summary": "Tariro: due tomorrow — Maths — Fractions", "children": [{"name": "Tariro"}]}


class LearningDigestRoute(unittest.TestCase):
    def setUp(self):
        app = Flask(__name__)
        app.register_blueprint(learning_digest_bp)
        self.client = app.test_client()
        patcher = patch.multiple(Config, RECEIPT_WEBHOOK_SECRET="shh", LEARNING_DIGEST_TEMPLATE_NAME="",
                                 LEARNING_DIGEST_TEMPLATE_LANG="en_US")
        patcher.start()
        self.addCleanup(patcher.stop)

    def post(self, body=BODY, key="shh"):
        return self.client.post("/learning-digest", json=body, headers={"X-Receipt-Key": key} if key else {})

    def test_rejects_without_the_shared_secret(self):
        with patch("routes.learning_digest.send_whatsapp_message") as text:
            self.assertEqual(self.post(key=None).status_code, 401)
            self.assertEqual(self.post(key="wrong").status_code, 401)
        text.assert_not_called()

    def test_refuses_when_no_secret_is_configured(self):
        with patch.object(Config, "RECEIPT_WEBHOOK_SECRET", ""), patch("routes.learning_digest.send_whatsapp_message") as text:
            self.assertEqual(self.post(key="").status_code, 401)
        text.assert_not_called()

    def test_needs_a_phone_and_a_message(self):
        with patch("routes.learning_digest.send_whatsapp_message") as text:
            self.assertEqual(self.post({**BODY, "phone": " "}).status_code, 400)
            self.assertEqual(self.post({**BODY, "message": ""}).status_code, 400)
        text.assert_not_called()

    def test_without_a_template_sends_the_full_text(self):
        with patch("routes.learning_digest.send_whatsapp_message", return_value={"ok": True}) as text:
            response = self.post()
        self.assertEqual(response.status_code, 200)
        text.assert_called_once_with(to="+263771234567", message=MESSAGE)

    def test_with_a_template_sends_one_line_parameters(self):
        with patch.object(Config, "LEARNING_DIGEST_TEMPLATE_NAME", "learning_digest"), \
                patch("routes.learning_digest.send_whatsapp_template", return_value={"ok": True}) as tpl, \
                patch("routes.learning_digest.send_whatsapp_message") as text:
            response = self.post({**BODY, "summary": "Tariro:\tdue\n\ntomorrow      Maths"})
        self.assertEqual(response.status_code, 200)
        text.assert_not_called()
        kwargs = tpl.call_args.kwargs
        self.assertEqual(kwargs["template_name"], "learning_digest")
        self.assertEqual(kwargs["body_params"], ["Shining Smiles", "Thu 08 Oct", "Tariro: due tomorrow Maths"])
        for param in kwargs["body_params"]:
            self.assertNotRegex(param, r"[\n\t]| {5,}")

    def test_send_failure_is_a_500_and_the_message_is_never_logged(self):
        with patch("routes.learning_digest.send_whatsapp_message", side_effect=RuntimeError("Fractions boom")), \
                self.assertLogs("routes.learning_digest", level="INFO") as logs:
            response = self.post()
        self.assertEqual(response.status_code, 500)
        self.assertNotIn("Fractions", response.get_data(as_text=True))
        joined = "\n".join(logs.output)
        self.assertNotIn("Fractions", joined)
        self.assertNotIn("+263771234567", joined)

    def test_long_summaries_are_cut_to_the_template_limit(self):
        self.assertEqual(len(template_param("x" * 2000)), 900)
        self.assertTrue(template_param("x" * 2000).endswith("…"))


if __name__ == "__main__":
    unittest.main()
