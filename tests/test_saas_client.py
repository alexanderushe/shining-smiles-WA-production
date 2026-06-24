"""SaaSClient bot<->SaaS contract test.

Mocks the SaaS integration API HTTP responses and asserts SaaSClient reshapes
them into the legacy bot-friendly shapes the rest of the bot still expects.
No network. Run:  venv/bin/python tests/test_saas_client.py
"""
import os
import sys
import unittest
from unittest.mock import MagicMock, patch

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))
os.environ.setdefault("SMS_API_BASE_URL", "http://saas.local/api/v1/integrations/whatsapp/")
os.environ.setdefault("SMS_API_KEY", "testkey")
os.environ.setdefault("USE_CLOUD_API", "true")

from api.sms_client import SaaSClient  # noqa: E402

PROFILE = {"data": {"student_id": "S1", "firstname": "Tariro", "lastname": "M",
                    "current_grade": "grade-3", "status": "active"}}
STATEMENT = {"student": {"student_number": "S1", "current_grade": "grade-3"},
             "outstanding_balance": "400.00", "available_credit": "0",
             "invoices": [{"term": "Term-1", "academic_year": 2026,
                           "total_amount": "500", "balance": "400", "status": "pending"}]}
PAYMENTS = {"student_id": 1, "payments": [{"id": 1, "amount": "100", "term": "Term-1"}]}
BILLED = {"student_id": 1, "invoices": [{"term": "Term-1", "academic_year": 2026,
          "total_amount": "500",
          "items": [{"description": "Tuition", "amount": "450"},
                    {"description": "Meals", "amount": "50"}]}]}


def _resp(payload):
    r = MagicMock()
    r.status_code = 200
    r.json.return_value = payload
    r.text = str(payload)
    r.raise_for_status.return_value = None
    return r


def _dispatch(url, **kwargs):
    if "/statement/" in url:
        return _resp(STATEMENT)
    if "/profile/" in url:
        return _resp(PROFILE)
    if "/payments/" in url:
        return _resp(PAYMENTS)
    if "/billed-fees/" in url:
        return _resp(BILLED)
    return _resp({})


class SaaSClientContract(unittest.TestCase):
    def setUp(self):
        self.client = SaaSClient(
            tenant_config={"sms_api_base_url": "http://saas.local/api/v1/integrations/whatsapp/",
                           "sms_api_key": "k", "school_id": "alpha"},
            use_cloud_api=True,
        )

    def test_term_param_conversion(self):
        self.assertEqual(self.client._term_params("2026-1"),
                         {"academic_year": "2026", "term": "Term-1"})
        self.assertEqual(self.client._term_params("Term-2"), {"term": "Term-2"})

    @patch("api.sms_client.requests.get", side_effect=_dispatch)
    def test_profile_passthrough(self, _g):
        out = self.client.get_student_profile("S1")
        self.assertEqual(out["data"]["firstname"], "Tariro")
        self.assertEqual(out["data"]["current_grade"], "grade-3")

    @patch("api.sms_client.requests.get", side_effect=_dispatch)
    def test_statement_reshape(self, _g):
        out = self.client.get_student_account_statement("S1", "2026-1")["data"]
        self.assertEqual(out["total_fees"], 500.0)         # summed invoice totals
        self.assertEqual(out["balance"], 400.0)            # canonical outstanding
        self.assertEqual(out["student_name"], "[S1] Tariro M")
        self.assertEqual(out["current_grade"], "grade-3")
        self.assertEqual(len(out["invoices"]), 1)

    @patch("api.sms_client.requests.get", side_effect=_dispatch)
    def test_payments_legacy_collection(self, _g):
        out = self.client.get_student_payments("S1", "2026-1")
        self.assertEqual(out["payments"], PAYMENTS["payments"])
        # legacy callers do `.get("payments")` on the data object
        self.assertEqual(out["data"].get("payments"), PAYMENTS["payments"])
        self.assertEqual(len(out["data"]), 1)

    @patch("api.sms_client.requests.get", side_effect=_dispatch)
    def test_billed_fees_reshape(self, _g):
        out = self.client.get_student_billed_fees("S1", "2026-1")
        bills = out["bills"]
        self.assertEqual(len(bills), 2)                    # one per invoice item
        self.assertEqual(bills[0]["fee_type"], "Tuition")
        self.assertEqual(bills[0]["amount"], "450")
        self.assertEqual(out["data"].get("bills"), bills)  # legacy alias


if __name__ == "__main__":
    unittest.main(verbosity=2)
