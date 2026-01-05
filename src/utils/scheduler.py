# src/utils/scheduler.py

import time
import datetime
from ratelimit import RateLimitException

from services.reminder_service import (
    send_balance_reminders,
    update_or_create_contact,
)
from services.payment_service import check_new_payments
from utils.logger import setup_logger
from utils.database import init_db, StudentContact
from api.sms_client import SMSClient
from config import Config

logger = setup_logger(__name__)


def send_all_reminders():
    """Send WhatsApp reminders for all students in debt."""
    session = init_db()
    try:
        # Dynamically get current term
        term = Config.get_current_term()
        if not term:
            # During break, use most recent completed term
            term = Config.get_most_recent_completed_term()
            logger.info(f"📅 School is on break, using most recent term: {term}")
        
        if not term:
            logger.error("❌ No valid term found, cannot send reminders")
            return
        
        client = SMSClient()
        logger.info(f"📦 Fetching students with outstanding balances for term {term}")
        debt_data = client.get_students_in_debt()
        students = debt_data.get("data", [])
        logger.info(f"📋 Found {len(students)} students in debt")

        for student in students:
            student_id = student["student"]["student_number"]
            try:
                result = send_balance_reminders(student_id, term, session=session)
                logger.debug(f"Reminder result for {student_id}: {result}")
                time.sleep(1)
            except Exception as e:
                logger.error(f"❌ Failed reminder for {student_id}: {str(e)}")
                session.rollback()

        logger.info(f"✅ Finished sending reminders for term {term}")

    except Exception as e:
        logger.error(f"💥 send_all_reminders() failed: {str(e)}")
        session.rollback()
    finally:
        session.close()
        logger.info("🧹 DB session closed after sending reminders")


def check_all_payments():
    """Check payments for all students in debt and update records."""
    session = init_db()
    try:
        # Dynamically get current term
        term = Config.get_current_term()
        if not term:
            # During break, use most recent completed term
            term = Config.get_most_recent_completed_term()
            logger.info(f"📅 School is on break, using most recent term: {term}")
        
        if not term:
            logger.error("❌ No valid term found, cannot check payments")
            return
        
        client = SMSClient()
        student_ids = set()

        logger.info(f"📦 Fetching students in debt for term {term}")
        debt_data = client.get_students_in_debt()
        students = debt_data.get("data", [])
        logger.info(f"📋 Found {len(students)} students")

        for student in students:
            student_id = student["student"]["student_number"]
            balance = student.get("outstanding_balance", 0)

            try:
                contact = session.query(StudentContact).filter_by(student_id=student_id).first()
                if not contact:
                    profile = client.get_student_profile(student_id)
                    if profile and "data" in profile:
                        profile_data = profile["data"]
                        contact = update_or_create_contact(session, student_id, profile_data, balance)
                        if not contact:
                            logger.warning(f"⚠️ Skipped student {student_id}: no valid phone numbers")
                            continue
                    else:
                        logger.warning(f"⚠️ No profile found for {student_id}")
                        continue
                else:
                    contact.outstanding_balance = balance
                    contact.last_updated = datetime.datetime.now(datetime.timezone.utc)
                    session.commit()
                    logger.debug(f"🔄 Updated balance for {student_id}: {balance}")

                student_ids.add(student_id)

            except Exception as e:
                logger.error(f"❌ Failed to process {student_id}: {str(e)}")
                session.rollback()

        # Batch check payments
        batch_size = 10
        batches = [list(student_ids)[i:i + batch_size] for i in range(0, len(student_ids), batch_size)]
        logger.info(f"💳 Checking payments for {len(student_ids)} students in {len(batches)} batches")

        for batch in batches:
            for student_id in batch:
                try:
                    contact = session.query(StudentContact).filter_by(student_id=student_id).first()

                    if contact and contact.last_updated > datetime.datetime.now(datetime.timezone.utc) - datetime.timedelta(days=1):
                        if contact.outstanding_balance is not None and contact.outstanding_balance <= 0:
                            logger.info(f"✅ Balance cleared for {student_id}, skipping")
                            continue

                    check_new_payments(student_id, term, session=session)

                except RateLimitException as e:
                    logger.warning(f"⏱️ Rate limit hit for {student_id}, sleeping {e.period_remaining}s")
                    time.sleep(e.period_remaining)
                    try:
                        check_new_payments(student_id, term, session=session)
                    except Exception as re:
                        logger.error(f"Retry failed for {student_id}: {str(re)}")
                        session.rollback()

                except Exception as e:
                    logger.error(f"❌ Error checking payments for {student_id}: {str(e)}")
                    session.rollback()

            logger.info("⏳ Sleeping between batches...")
            time.sleep(2)

        session.commit()
        logger.info(f"✅ Completed payment checks for term {term}")

    except Exception as e:
        logger.error(f"💥 check_all_payments() failed: {str(e)}")
        session.rollback()
    finally:
        session.close()
        logger.info("🧹 DB session closed after checking payments")
