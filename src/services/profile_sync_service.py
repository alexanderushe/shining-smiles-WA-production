# src/services/profile_sync_service.py
from api.sms_client import SMSClient
from utils.database import init_db, StudentContact, FailedSync
from utils.logger import setup_logger
import datetime
import time

logger = setup_logger(__name__)

def sync_student_profiles(max_records=None, min_update_interval_hours=24):
    """Sync student profiles from /school/students/data/ with pagination."""
    session = init_db()
    client = SMSClient()
    total_updated = 0
    total_failed = 0
    page = 1
    page_size = 60

    try:
        for student in client.get_all_students(page=page, page_size=page_size):
            if max_records and total_updated + total_failed >= max_records:
                logger.info(f"Reached max records limit ({max_records})")
                break

            student_id = student.get("student_number")
            if not student_id:
                logger.warning(f"Skipping student with no student_number: {student}")
                session.add(FailedSync(student_id="unknown", error="Missing student_number"))
                session.commit()
                total_failed += 1
                continue

            try:
                # Check if student was recently synced
                contact = session.query(StudentContact).filter_by(student_id=student_id).first()
                if contact and contact.last_api_sync and (datetime.datetime.now(datetime.timezone.utc) - contact.last_api_sync).total_seconds() < min_update_interval_hours * 3600:
                    logger.debug(f"Skipping {student_id}: recently synced")
                    continue

                # Extract student data
                firstname = student.get("firstname")
                lastname = student.get("lastname")
                student_mobile = student.get("student_mobile")
                guardian_mobile = student.get("guardian_mobile_number")

                # Handle 'nan' and normalize phone numbers
                if student_mobile == "nan" or not student_mobile:
                    logger.warning(f"No valid student_mobile for {student_id}")
                    session.add(FailedSync(student_id=student_id, error="No valid student_mobile"))
                    session.commit()
                    total_failed += 1
                    continue
                if not student_mobile.startswith("+"):
                    student_mobile = f"+263{student_mobile.lstrip('0')}"

                if guardian_mobile == "nan" or not guardian_mobile:
                    guardian_mobile = None
                if guardian_mobile and not guardian_mobile.startswith("+"):
                    guardian_mobile = f"+263{guardian_mobile.lstrip('0')}"
                preferred_phone = student_mobile  # Prioritize student_mobile

                # Update or insert contact
                if contact:
                    contact.firstname = firstname or contact.firstname
                    contact.lastname = lastname or contact.lastname
                    contact.student_mobile = student_mobile
                    contact.guardian_mobile_number = guardian_mobile or contact.guardian_mobile_number
                    contact.preferred_phone_number = preferred_phone
                    contact.last_updated = datetime.datetime.now(datetime.timezone.utc)
                    contact.last_api_sync = datetime.datetime.now(datetime.timezone.utc)
                    logger.info(f"Updated profile for {student_id}")
                else:
                    contact = StudentContact(
                        student_id=student_id,
                        firstname=firstname,
                        lastname=lastname,
                        student_mobile=student_mobile,
                        guardian_mobile_number=guardian_mobile,
                        preferred_phone_number=preferred_phone,
                        last_updated=datetime.datetime.now(datetime.timezone.utc),
                        last_api_sync=datetime.datetime.now(datetime.timezone.utc)
                    )
                    session.add(contact)
                    logger.info(f"Added profile for {student_id}")

                session.commit()
                total_updated += 1
            except Exception as e:
                logger.error(f"Error syncing profile for {student_id}: {str(e)}")
                session.add(FailedSync(student_id=student_id, error=str(e)))
                session.commit()
                total_failed += 1
                session.rollback()
            time.sleep(0.1)  # Rate limit delay

        logger.info(f"Sync completed: {total_updated} updated, {total_failed} failed")
        return {"status": "success", "updated": total_updated, "failed": total_failed}
    except Exception as e:
        logger.error(f"Sync failed: {str(e)}")
        return {"status": "error", "error": str(e)}
    finally:
        session.close()