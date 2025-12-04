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
    page = start_page
    page_size = 60
    
    logger.info(f"Starting sync at page {page} with time limit {time_limit_seconds}s")

    try:
        # We need to manually control the loop to handle pagination state
        while True:
            # Check time limit before fetching next page
            elapsed_time = time.time() - start_time
            if elapsed_time > time_limit_seconds:
                logger.warning(f"Time limit reached ({elapsed_time:.2f}s). Stopping at page {page}.")
                return {
                    "status": "partial",
                    "updated": total_updated,
                    "failed": total_failed,
                    "next_page": page,
                    "reason": "time_limit"
                }

            logger.info(f"Fetching page {page}...")
            # Fetch one page at a time
            students_on_page = []
            try:
                # We use a generator, but we only want one page worth
                # The client.get_all_students yields students across pages, which is hard to interrupt cleanly
                # So we will use a modified approach or just use the existing client but break after one page
                # Actually, the client.get_all_students iterates automatically. 
                # Let's use the client's internal logic but strictly for one page if possible, 
                # OR we just iterate and break when the page changes.
                # BUT client.get_all_students abstracts the page.
                # Let's rely on the fact that we can pass 'page' to it.
                # We will call it for ONE page.
                
                # To do this efficiently without modifying the client too much, we can just instantiate a new generator for each page
                # The client.get_all_students loop: `while url:` -> `for student in data...`
                # If we break the loop, we stop.
                
                # Let's try to fetch just the specific page using the client's logic
                # We'll use a specific method if we can, or just use get_all_students and break after the first page's worth of items?
                # No, get_all_students follows 'next' link.
                
                # Let's peek at client.get_all_students again.
                # It takes page=1.
                # It loops `while url`.
                # We can just break after the first yield loop finishes? No, it yields individual students.
                
                # Better approach: We will use the client to fetch *just* this page.
                # But the client doesn't expose "get_page".
                # We will use `get_all_students(page=page)` and break when we detect we've processed `page_size` items?
                # Or better, we modify the client? No, let's avoid modifying the client if possible.
                
                # Actually, looking at client.get_all_students:
                # It does `params = {"page": page...}` inside the loop.
                # If we pass `page`, it starts there.
                # We can just iterate, and check time inside the loop.
                # But we need to know the CURRENT page to resume.
                # The client doesn't yield the page number.
                
                # OK, we need to be careful.
                # If we use `get_all_students(page=start_page)`, it will start at `start_page` and keep going.
                # We can just track how many we processed.
                # `current_page = start_page + (total_processed // page_size)`?
                # That assumes pages are full.
                
                # Let's just put the time check INSIDE the loop.
                # And we need to know which page we are on.
                # The client yields `student`. It doesn't tell us the page.
                
                # Alternative: We modify the client to return page info, OR we just trust that we can resume.
                # If we stop after X seconds, we might be in the middle of a page.
                # Resuming from the *start* of that page is safe (idempotent updates), just slightly wasteful.
                
                # So:
                # 1. Call `get_all_students(page=start_page)`
                # 2. Iterate.
                # 3. Check time every N records.
                # 4. If time up, calculate `next_page = start_page + (records_processed // page_size)`.
                # 5. Return `next_page`.
                
                records_processed_in_run = 0
                
                for student in client.get_all_students(page=start_page, page_size=page_size):
                    # Check time every 10 records
                    if records_processed_in_run % 10 == 0:
                        if time.time() - start_time > time_limit_seconds:
                            # Calculate roughly where we are
                            # We might be in the middle of a page.
                            # Safest is to resume from the page we are currently on.
                            # current_virtual_page = start_page + (records_processed_in_run // page_size)
                            # actually, get_all_students handles the pagination.
                            # If we break here, we need to know the page.
                            
                            # Since we can't easily know the exact page from the generator,
                            # Let's estimate.
                            pages_advanced = records_processed_in_run // page_size
                            resume_page = start_page + pages_advanced
                            
                            logger.warning(f"Time limit reached. Processed {records_processed_in_run} records. Resuming at page {resume_page}.")
                            return {
                                "status": "partial",
                                "updated": total_updated,
                                "failed": total_failed,
                                "next_page": resume_page,
                                "reason": "time_limit"
                            }

                    if max_records and total_updated + total_failed >= max_records:
                        logger.info(f"Reached max records limit ({max_records})")
                        return {"status": "success", "updated": total_updated, "failed": total_failed}

                    student_id = student.get("student_number")
                    if not student_id:
                        # ... (existing logic)
                        total_failed += 1
                        records_processed_in_run += 1
                        continue

                    try:
                        # ... (existing logic for update/insert)
                        # Copying the core logic here for brevity in thought, but will include full code in replacement
                        
                        # Check recently synced
                        contact = session.query(StudentContact).filter_by(student_id=student_id).first()
                        if contact and contact.last_api_sync and (datetime.datetime.now(datetime.timezone.utc) - contact.last_api_sync).total_seconds() < min_update_interval_hours * 3600:
                            # logger.debug(f"Skipping {student_id}: recently synced")
                            pass # Just continue
                        else:
                            # Extract and Update
                            firstname = student.get("firstname")
                            lastname = student.get("lastname")
                            student_mobile = student.get("student_mobile")
                            guardian_mobile = student.get("guardian_mobile_number")

                            if student_mobile == "nan" or not student_mobile:
                                session.add(FailedSync(student_id=student_id, error="No valid student_mobile"))
                                session.commit()
                                total_failed += 1
                                records_processed_in_run += 1
                                continue
                                
                            if not student_mobile.startswith("+"):
                                student_mobile = f"+263{student_mobile.lstrip('0')}"

                            if guardian_mobile == "nan" or not guardian_mobile:
                                guardian_mobile = None
                            if guardian_mobile and not guardian_mobile.startswith("+"):
                                guardian_mobile = f"+263{guardian_mobile.lstrip('0')}"
                            preferred_phone = student_mobile

                            if contact:
                                contact.firstname = firstname or contact.firstname
                                contact.lastname = lastname or contact.lastname
                                contact.student_mobile = student_mobile
                                contact.guardian_mobile_number = guardian_mobile or contact.guardian_mobile_number
                                contact.preferred_phone_number = preferred_phone
                                contact.last_updated = datetime.datetime.now(datetime.timezone.utc)
                                contact.last_api_sync = datetime.datetime.now(datetime.timezone.utc)
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
                            
                            session.commit()
                            total_updated += 1
                            
                    except Exception as e:
                        logger.error(f"Error syncing profile for {student_id}: {str(e)}")
                        session.add(FailedSync(student_id=student_id, error=str(e)))
                        session.commit()
                        total_failed += 1
                        session.rollback()
                    
                    records_processed_in_run += 1
                    # time.sleep(0.05) # Reduced sleep for speed

                # If loop finishes naturally
                logger.info(f"Sync completed naturally: {total_updated} updated, {total_failed} failed")
                return {"status": "success", "updated": total_updated, "failed": total_failed}
                
            except Exception as inner_e:
                logger.error(f"Error during iteration: {inner_e}")
                raise inner_e
                
            break # Should not be reached if loop finishes, but safety

    except Exception as e:
        logger.error(f"Sync failed: {str(e)}")
        return {"status": "error", "error": str(e)}
    finally:
        session.close()