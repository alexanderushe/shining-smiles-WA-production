# src/services/reminder_service.py
import datetime
import time

from twilio.base.exceptions import TwilioRestException
from sqlalchemy.exc import IntegrityError

from api.sms_client import SMSClient
from utils.whatsapp import send_whatsapp_message
from utils.logger import setup_logger
from utils.database import init_db, StudentContact, UserState
from services.reminder_logic import should_send_reminder, generate_reminder_message
from config import get_config

logger = setup_logger(__name__)
cfg = get_config()


def sanitize_phone_number(phone):
    """Sanitize phone number, converting invalid or 'nan' values to None."""
    if not phone or str(phone).lower() in ["nan", "null", "", "none"]:
        return None
    return str(phone).strip()


def update_or_create_contact(session, student_id, profile_data, balance):
    """Update or create a StudentContact record, avoiding duplicates."""
    try:
        contact = session.query(StudentContact).filter_by(student_id=student_id).first()
        firstname = profile_data.get("firstname")
        lastname = profile_data.get("lastname")
        student_mobile = sanitize_phone_number(profile_data.get("student_mobile"))
        guardian_mobile = sanitize_phone_number(profile_data.get("guardian_mobile_number"))

        # 💡 Clean numbers: must not contain `'`, letters, or be too short
        def normalize(phone):
            if not phone:
                return None
            phone = phone.strip().replace("'", "")
            if not phone.startswith("+263"):
                phone = f"+263{phone.lstrip('0')}"
            return phone if phone[1:].isdigit() and len(phone) >= 10 else None

        student_mobile = normalize(student_mobile)
        guardian_mobile = normalize(guardian_mobile)
        preferred_phone = student_mobile or guardian_mobile

        # 💣 Abort early if student_mobile is null and DB requires it
        if not student_mobile:
            logger.warning(f"⚠️ Skipping student {student_id}: no valid student_mobile (required by schema)")
            return None

        if contact:
            # Update existing contact
            contact.firstname = firstname
            contact.lastname = lastname
            contact.student_mobile = student_mobile
            contact.guardian_mobile_number = guardian_mobile
            contact.preferred_phone_number = preferred_phone
            contact.outstanding_balance = balance
            contact.last_updated = datetime.datetime.now(datetime.timezone.utc)
            contact.last_api_sync = datetime.datetime.now(datetime.timezone.utc)
            logger.debug(f"🔄 Updated contact for {student_id}: {preferred_phone}, balance: {balance}")
        else:
            # Create new contact
            contact = StudentContact(
                student_id=student_id,
                firstname=firstname,
                lastname=lastname,
                student_mobile=student_mobile,
                guardian_mobile_number=guardian_mobile,
                preferred_phone_number=preferred_phone,
                outstanding_balance=balance,
                last_updated=datetime.datetime.now(datetime.timezone.utc),
                last_api_sync=datetime.datetime.now(datetime.timezone.utc)
            )
            session.add(contact)
            logger.debug(f"🆕 Created contact for {student_id}: {preferred_phone}, balance: {balance}")
        
        session.commit()
        return contact

    except IntegrityError as e:
        logger.error(f"❌ IntegrityError for {student_id}: {str(e)}")
        session.rollback()
        contact = session.query(StudentContact).filter_by(student_id=student_id).first()
        return contact if contact else None

    except Exception as e:
        logger.error(f"❌ Error updating/creating contact for {student_id}: {str(e)}")
        session.rollback()
        return None



def send_balance_reminders(student_id, term, phone_number=None, session=None):
    """Send reminders for outstanding balances and update user_states."""
    close_session = False
    try:
        client = SMSClient()

        if term not in cfg.TERM_START_DATES:
            logger.error(f"Invalid term: {term}")
            return {"error": f"Invalid term: {term}"}
        if datetime.datetime.now(datetime.timezone.utc) > cfg.TERM_END_DATES[term]:
            logger.error(f"Term {term} has ended")
            return {"error": f"Term {term} has ended"}

        if session is None:
            session = init_db()
            close_session = True

        logger.debug(f"Database session initialized for {student_id}: {session}")
        contact = session.query(StudentContact).filter_by(student_id=student_id).first()

        if contact and contact.last_updated > datetime.datetime.now(datetime.timezone.utc) - datetime.timedelta(days=1):
            phone_number = contact.preferred_phone_number
            fullname = f"{contact.firstname} {contact.lastname}".strip() if contact.firstname and contact.lastname else "Parent/Guardian"
            cached_balance = contact.outstanding_balance
            logger.info(f"Using cached contact for {student_id}: {phone_number}, balance: {cached_balance}")
        else:
            logger.debug(f"No contact or stale data for {student_id}, fetching from API")
            profile = client.get_student_profile(student_id)
            if not profile or "data" not in profile:
                logger.error(f"No profile data for {student_id}")
                return {"error": "No profile data found"}

            profile_data = profile["data"]
            debt_data = client.get_students_in_debt(student_id=student_id)
            cached_balance = 0
            for student in debt_data.get("data", []):
                if student["student"]["student_number"] == student_id:
                    cached_balance = student["outstanding_balance"]
                    break

            contact = update_or_create_contact(session, student_id, profile_data, cached_balance)
            if not contact:
                logger.warning(f"Skipping {student_id} due to missing phone numbers")
                return {"error": "No valid contact info"}

            phone_number = contact.preferred_phone_number
            fullname = f"{contact.firstname} {contact.lastname}".strip() if contact.firstname and contact.lastname else "Parent/Guardian"

        if not phone_number:
            logger.error(f"No valid phone number for {student_id}")
            return {"error": "No valid phone number found"}

        if cached_balance <= 0:
            logger.info(f"No outstanding balance for {student_id}")
            return {"status": f"No outstanding balance for {student_id}"}

        user_state = session.query(UserState).filter_by(phone_number=phone_number).first()
        if not should_send_reminder(user_state, term):
            logger.info(f"Skipping reminder for {student_id}: throttled")
            return {"status": "Reminder skipped due to throttling"}

        message = generate_reminder_message(fullname, student_id, cached_balance, term)

        # Send WhatsApp with retry
        max_retries = 3
        for attempt in range(max_retries):
            try:
                response = send_whatsapp_message(phone_number, message)
                logger.info(f"Message status for {student_id}: {response.get('status', 'unknown')}")
                time.sleep(1)
                break
            except TwilioRestException as e:
                if e.code == 429 and attempt < max_retries - 1:
                    logger.warning(f"Twilio rate limit for {student_id}, retrying...")
                    time.sleep(60)
                else:
                    logger.error(f"Twilio error for {student_id}: {str(e)}")
                    return {"error": f"Twilio error: {str(e)}"}
            except Exception as e:
                logger.error(f"Unexpected error sending message for {student_id}: {str(e)}")
                return {"error": f"Unexpected error: {str(e)}"}

        try:
            if user_state:
                user_state.state = "reminder_sent"
                user_state.student_id = student_id
                user_state.last_updated = datetime.datetime.now(datetime.timezone.utc)
                user_state.reminder_count = (user_state.reminder_count or 0) + 1
            else:
                user_state = UserState(
                    phone_number=phone_number,
                    state="reminder_sent",
                    student_id=student_id,
                    last_updated=datetime.datetime.now(datetime.timezone.utc),
                    reminder_count=1
                )
                session.add(user_state)
            session.commit()
            logger.info(f"Updated user state for {student_id}: reminder sent")

        except Exception as e:
            logger.error(f"Failed to update user state for {student_id}: {str(e)}")
            session.rollback()
            return {"error": f"Failed to update user_states: {str(e)}"}

        return {"status": "Balance reminder sent", "phone_number": phone_number}

    except Exception as e:
        logger.error(f"Error sending reminder for {student_id}: {str(e)}")
        session.rollback()
        return {"error": str(e)}

    finally:
        if close_session and session:
            session.close()
            logger.info("🧹 Reminder job DB session closed (internal)")
