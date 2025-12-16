# src/services/profile_sync_service.py
from api.sms_client import SMSClient
from utils.database import init_db, StudentContact, FailedSync
from utils.logger import setup_logger
import datetime
import time

logger = setup_logger(__name__)

def sync_student_profiles(max_records=None, min_update_interval_hours=24, start_page=1, time_limit_seconds=800):
    """
    Sync student profiles from /school/students/data/ with pagination and time limits.
    Returns a dict with status and next_page if applicable.
    """
    start_time = time.time()
    session = init_db()
    client = SMSClient()
    total_updated = 0
    total_failed = 0
    total_skipped = 0
    page = start_page
    page_size = 60
    
    logger.info(f"Starting sync at page {page} with time limit {time_limit_seconds}s")

    final_status = "success"
    exit_reason = None
    next_page_val = None

    def sanitize_phone_number(phone):
        if not phone or phone == "nan":
            return None
        # Remove spaces, dashes, brackets
        cleaned = "".join(c for c in str(phone) if c.isdigit() or c == '+')
        if not cleaned:
            return None
        # Ensure +263 format
        if not cleaned.startswith("+"):
            if cleaned.startswith("0"):
                cleaned = "+263" + cleaned[1:]
            elif len(cleaned) == 9: # e.g. 771234567
                cleaned = "+263" + cleaned
        return cleaned

    try:
        while True:
            # Check time limit before starting a new page
            elapsed_time = time.time() - start_time
            if elapsed_time > time_limit_seconds:
                exit_reason = "time_limit"
                final_status = "partial"
                next_page_val = page
                logger.warning(f"Time limit reached ({elapsed_time:.2f}s). Stopping at page {page}.")
                break

            logger.info(f"Fetching page {page}...")
            
            try:
                # Fetch one page of students
                # Note: get_all_students is a generator, so we iterate through it. 
                # We expect the client to yield students for the requested page.
                students_generator = client.get_all_students(page=page, page_size=page_size)
                
                records_in_page = 0
                has_data = False

                for student in students_generator:
                    has_data = True
                    records_in_page += 1
                    
                    # Periodic time check within page to be responsive
                    if records_in_page % 10 == 0:
                        if time.time() - start_time > time_limit_seconds:
                            # We stop mid-page. The next run should resume from this page.
                            # Since we don't have sub-page cursors, we re-process the whole page next time.
                            # Logic handles duplicates so this is safe.
                            raise TimeoutError("Time limit reached mid-page")

                    if max_records and total_updated + total_failed + total_skipped >= max_records:
                        logger.info(f"Reached max records limit ({max_records})")
                        break
                    
                    try:
                        student_number = student.get("student_number") or student.get("student_id")
                        if not student_number:
                            total_failed += 1
                            continue

                        # Check if recently synced
                        contact = session.query(StudentContact).filter_by(student_id=student_number).first()
                        if contact and contact.last_api_sync and (datetime.datetime.now(datetime.timezone.utc) - contact.last_api_sync).total_seconds() < min_update_interval_hours * 3600:
                            total_skipped += 1
                            continue
                        
                        # Extract data
                        firstname = student.get("firstname", "")
                        lastname = student.get("lastname", "")
                        raw_mobile = student.get("student_mobile") or student.get("student_mobile_number")
                        raw_guardian = student.get("guardian_mobile_number")
                        
                        student_mobile = sanitize_phone_number(raw_mobile)
                        guardian_mobile = sanitize_phone_number(raw_guardian)

                        if not student_mobile:
                            session.add(FailedSync(student_id=student_number, error="No valid student_mobile"))
                            session.commit()
                            total_failed += 1
                        else:
                            if contact:
                                contact.firstname = firstname or contact.firstname
                                contact.lastname = lastname or contact.lastname
                                # Only update if we have new valid values, or keep existing
                                contact.student_mobile = student_mobile
                                if guardian_mobile:
                                    contact.guardian_mobile_number = guardian_mobile
                                contact.preferred_phone_number = student_mobile
                                contact.last_updated = datetime.datetime.now(datetime.timezone.utc)
                                contact.last_api_sync = datetime.datetime.now(datetime.timezone.utc)
                            else:
                                contact = StudentContact(
                                    student_id=student_number,
                                    firstname=firstname,
                                    lastname=lastname,
                                    student_mobile=student_mobile,
                                    guardian_mobile_number=guardian_mobile,
                                    preferred_phone_number=student_mobile,
                                    last_updated=datetime.datetime.now(datetime.timezone.utc),
                                    last_api_sync=datetime.datetime.now(datetime.timezone.utc),
                                    created_at=datetime.datetime.now(datetime.timezone.utc)
                                )
                                session.add(contact)
                            
                            session.commit()
                            total_updated += 1
                            
                    except Exception as inner_e:
                        logger.error(f"Error processing record {student.get('student_number', 'unknown')}: {inner_e}")
                        session.rollback()
                        total_failed += 1
                
                # End of page loop
                if not has_data:
                    logger.info("No more students found (empty page). Sync complete.")
                    final_status = "success"
                    break
                
                if max_records and total_updated + total_failed + total_skipped >= max_records:
                     break
                     
                page += 1

            except TimeoutError:
                # Caught from inner loop
                exit_reason = "time_limit"
                final_status = "partial"
                next_page_val = page
                logger.warning(f"Time limit reached mid-page {page}.")
                break
                
            except Exception as page_error:
                # CRITICAL: If a page fetch fails (API error), we mark as partial 
                # and return the current page so it gets retried by the webhook handler.
                logger.error(f"Failed to fetch/process page {page}: {page_error}")
                exit_reason = f"error_retry_page_{page}"
                final_status = "partial" # Using 'partial' ensures the webhook handler triggers a retry
                next_page_val = page # Retry THIS page
                break # Break main loop to return context

    except Exception as e:
        logger.error(f"Critical error in sync_student_profiles: {e}")
        final_status = "error"
        exit_reason = str(e)
        # For critical setup errors, we don't retry locally
        
    finally:
        logger.info(f"Sync run finished: {total_updated} updated, {total_skipped} skipped, {total_failed} failed. Status: {final_status}")
        try:
            session.close()
        except:
            pass

    result = {
        "status": final_status,
        "updated": total_updated,
        "skipped": total_skipped,
        "failed": total_failed
    }
    if next_page_val:
        result["next_page"] = next_page_val
    if exit_reason:
        result["reason"] = exit_reason
        
    return result