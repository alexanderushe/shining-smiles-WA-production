import unittest
from unittest.mock import MagicMock, patch
import sys
import os
import datetime

# Add src to path
sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), '../src')))

from services.reminder_logic import should_send_reminder, generate_reminder_message
from services.payment_service import check_new_payments
from services.reminder_service import send_balance_reminders
from utils.database import UserState

class TestServices(unittest.TestCase):

    def setUp(self):
        # Mock config
        self.config_patcher = patch('services.reminder_logic.get_config')
        self.mock_config = self.config_patcher.start()
        
        # Setup mock config values
        self.mock_config.return_value.TERM_START_DATES = {"2025-1": datetime.datetime(2025, 1, 1, tzinfo=datetime.timezone.utc)}
        self.mock_config.return_value.TERM_END_DATES = {"2025-1": datetime.datetime(2025, 3, 31, tzinfo=datetime.timezone.utc)}
        self.mock_config.return_value.weeks_remaining.return_value = 5
        self.mock_config.return_value.weeks_elapsed.return_value = 2
        self.mock_config.return_value.term_end_date.return_value = datetime.datetime(2025, 3, 31, tzinfo=datetime.timezone.utc)

    def tearDown(self):
        self.config_patcher.stop()

    def test_reminder_logic_should_send(self):
        print("\nTesting reminder_logic.should_send_reminder...")
        # Case 1: No user state -> Should send
        self.assertTrue(should_send_reminder(None, "2025-1"))
        
        # Case 2: Throttled
        user_state = MagicMock(spec=UserState)
        user_state.last_updated = datetime.datetime.now(datetime.timezone.utc)
        self.assertFalse(should_send_reminder(user_state, "2025-1"))

    def test_reminder_logic_message(self):
        print("\nTesting reminder_logic.generate_reminder_message...")
        msg = generate_reminder_message("John Doe", "S123", 100, "2025-1")
        self.assertIn("John Doe", msg)
        self.assertIn("S123", msg)
        self.assertIn("100", msg)

    @patch('services.payment_service.init_db')
    @patch('services.payment_service.SMSClient')
    @patch('services.payment_service.send_whatsapp_message')
    @patch('services.payment_service.TERM_END_DATES', {"2025-1": datetime.datetime(2099, 12, 31, tzinfo=datetime.timezone.utc)})
    def test_payment_service_check_new_payments(self, mock_send_whatsapp, mock_sms_client, mock_init_db):
        print("\nTesting payment_service.check_new_payments...")
        
        # Mock DB session
        mock_session = MagicMock()
        mock_init_db.return_value = mock_session
        
        # Mock Contact query to return None so it fetches from API (or just mock it to return a contact)
        # Let's mock a contact exists
        mock_contact = MagicMock()
        mock_contact.preferred_phone_number = "+263771234567"
        mock_contact.firstname = "Parent"
        mock_contact.lastname = "One"
        mock_contact.outstanding_balance = 500.0
        mock_contact.last_updated = datetime.datetime.now(datetime.timezone.utc)
        
        mock_session.query.return_value.filter_by.return_value.first.return_value = mock_contact

        # Run in test mode
        result, status_code = check_new_payments("S123", "2025-1", test_mode=True, test_payment_percentage=10)
        
        print(f"Payment Result: {result}, Status: {status_code}")
        self.assertEqual(status_code, 200)
        self.assertEqual(result['status'], "Payment processed")
        self.assertTrue(mock_send_whatsapp.called)

    @patch('services.reminder_service.init_db')
    @patch('services.reminder_service.SMSClient')
    @patch('services.reminder_service.send_whatsapp_message')
    @patch('services.reminder_service.should_send_reminder')
    @patch('services.reminder_service.cfg')
    def test_reminder_service_send_balance_reminders(self, mock_cfg, mock_should_send, mock_send_whatsapp, mock_sms_client, mock_init_db):
        print("\nTesting reminder_service.send_balance_reminders...")
        
        # Mock config for reminder service
        mock_cfg.TERM_START_DATES = ["2025-1"]
        mock_cfg.TERM_END_DATES = {"2025-1": datetime.datetime(2099, 12, 31, tzinfo=datetime.timezone.utc)}

        # Mock DB
        mock_session = MagicMock()
        mock_init_db.return_value = mock_session
        
        # Mock Contact
        mock_contact = MagicMock()
        mock_contact.preferred_phone_number = "+263771234567"
        mock_contact.firstname = "Parent"
        mock_contact.lastname = "One"
        mock_contact.outstanding_balance = 100.0
        mock_contact.last_updated = datetime.datetime.now(datetime.timezone.utc)
        
        mock_session.query.return_value.filter_by.return_value.first.return_value = mock_contact
        
        # Mock should send
        mock_should_send.return_value = True
        
        # Execute
        result = send_balance_reminders("S123", "2025-1")
        
        print(f"Reminder Result: {result}")
        self.assertEqual(result.get('status'), "Balance reminder sent")
        self.assertTrue(mock_send_whatsapp.called)

if __name__ == '__main__':
    unittest.main()
