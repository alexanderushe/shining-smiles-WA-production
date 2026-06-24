"""Regression for live Lambda webhook resolve-by-phone fallback."""
import json
import os
import sys
import unittest
from unittest.mock import patch

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

from utils.database import Base, StudentContact, UserState

USER_NUMBER = "+263779453582"
SCHOOL_ID = "school-3"
PHONE_NUMBER_ID = "PHONE_NUMBER_ID"


class FakeSMSClient:
    def __init__(self, *args, **kwargs):
        pass

    def resolve_by_phone(self, phone_number):
        if phone_number != USER_NUMBER:
            return {"count": 0, "students": [], "data": []}
        return {
            "count": 1,
            "students": [
                {
                    "student_id": "SSC20246303",
                    "firstname": "Testy",
                    "lastname": "Parent",
                    "current_grade": "grade-3",
                    "status": "active",
                    "outstanding_balance": "400.00",
                    "preferred_phone_number": USER_NUMBER,
                }
            ],
            "data": [],
        }

    def get_student_profile(self, student_id):
        return {
            "data": {
                "student_id": student_id,
                "firstname": "Testy",
                "lastname": "Parent",
                "student_mobile": USER_NUMBER,
                "guardian_mobile_number": USER_NUMBER,
                "preferred_phone_number": USER_NUMBER,
                "current_grade": "grade-3",
                "status": "active",
            }
        }


class ResolveFallbackWebhookTest(unittest.TestCase):
    def setUp(self):
        os.environ["WHATSAPP_DEFAULT_SCHOOL_ID"] = SCHOOL_ID
        self.engine = create_engine("sqlite://")
        Base.metadata.create_all(self.engine)
        self.Session = sessionmaker(bind=self.engine)

        session = self.Session()
        session.add(UserState(
            school_id=SCHOOL_ID,
            phone_number=USER_NUMBER,
            state="unregistered_menu",
            query_count=0,
        ))
        session.commit()
        session.close()

    def tearDown(self):
        os.environ.pop("WHATSAPP_DEFAULT_SCHOOL_ID", None)
        self.engine.dispose()

    def _new_session(self):
        return self.Session()

    @patch("webhook_handler.send_whatsapp_message_real")
    @patch("webhook_handler.react_to_message")
    @patch("webhook_handler.mark_message_as_read")
    @patch("webhook_handler.reset_current_tenant")
    @patch("webhook_handler.set_current_tenant")
    @patch("webhook_handler.resolve_tenant_config")
    @patch("webhook_handler.SMSClient", FakeSMSClient)
    @patch("webhook_handler.init_db")
    def test_lambda_webhook_resolves_and_caches_contact(
        self,
        mock_init_db,
        mock_resolve_tenant_config,
        mock_set_current_tenant,
        mock_reset_current_tenant,
        mock_mark_read,
        mock_react,
        mock_send,
    ):
        import webhook_handler

        mock_init_db.side_effect = self._new_session
        mock_resolve_tenant_config.return_value = {
            "school_id": SCHOOL_ID,
            "phone_number_id": PHONE_NUMBER_ID,
        }
        mock_set_current_tenant.return_value = object()
        mock_send.return_value = {"status": "sent"}

        event = {
            "httpMethod": "POST",
            "body": json.dumps({
                "object": "whatsapp_business_account",
                "entry": [
                    {
                        "changes": [
                            {
                                "value": {
                                    "metadata": {
                                        "display_phone_number": "263771234567",
                                        "phone_number_id": PHONE_NUMBER_ID,
                                    },
                                    "messages": [
                                        {
                                            "from": USER_NUMBER.replace("+", ""),
                                            "id": "wamid.test-message",
                                            "timestamp": "1710000000",
                                            "text": {"body": "menu"},
                                            "type": "text",
                                        }
                                    ],
                                }
                            }
                        ]
                    }
                ],
            }),
        }

        response = webhook_handler.lambda_handler(event, context=None)

        self.assertEqual(response["statusCode"], 200)
        mock_mark_read.assert_called_once_with("wamid.test-message")
        mock_react.assert_called_once()
        mock_send.assert_called_once()

        outbound = mock_send.call_args.kwargs
        self.assertEqual(outbound["to"], USER_NUMBER)
        self.assertIn("What can I help you with today?", outbound["message"])
        self.assertIn("View Balance", outbound["message"])
        self.assertNotIn("About Our School", outbound["message"])

        verify_session = self.Session()
        try:
            contact = verify_session.query(StudentContact).filter_by(
                school_id=SCHOOL_ID,
                student_id="SSC20246303",
            ).first()
            self.assertIsNotNone(contact)
            self.assertEqual(contact.preferred_phone_number, USER_NUMBER)

            state = verify_session.query(UserState).filter_by(
                school_id=SCHOOL_ID,
                phone_number=USER_NUMBER,
            ).first()
            self.assertEqual(state.state, "main_menu")
        finally:
            verify_session.close()


if __name__ == "__main__":
    unittest.main(verbosity=2)
