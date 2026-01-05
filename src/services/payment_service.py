# src/services/payment_service.py
from api.sms_client import SMSClient
from utils.whatsapp import send_whatsapp_message
from utils.logger import setup_logger
from utils.database import init_db, StudentContact, FailedSync
from config import Config
import datetime
from flask import current_app
from ratelimit import RateLimitException
import time

logger = setup_logger(__name__)

def check_new_payments(student_id, term, phone_number=None, session=None, test_mode=False, test_payment_percentage=50):
    """Check for new payments, send confirmation, and generate gate pass if applicable."""
    owns_session = False
    if session is None:
        session = init_db()
        owns_session = True

    try:
        client = SMSClient()
        logger.debug(f"Processing payment check for {student_id} (test_mode={test_mode})")

        # Validate term
        if term not in Config.TERM_END_DATES:
            logger.error(f"Invalid term: {term}")
            return {"error": f"Invalid term: {term}"}, 400
        if datetime.datetime.now(datetime.timezone.utc) > Config.TERM_END_DATES[term]:
            logger.error(f"Term {term} has ended")
            return {"error": f"Term {term} has ended"}, 400

        # Get contact and cached balance
        contact = session.query(StudentContact).filter_by(student_id=student_id).first()
        if contact:
            phone_number = contact.preferred_phone_number or contact.student_mobile
            fullname = f"{contact.firstname} {contact.lastname}".strip() if contact.firstname and contact.lastname else "Parent/Guardian"
            cached_balance = contact.outstanding_balance
            logger.info(f"Found DB contact for {student_id}: {phone_number}, cached_balance: {cached_balance}")
            if cached_balance is not None and contact.last_updated > datetime.datetime.now(datetime.timezone.utc) - datetime.timedelta(days=1):
                if cached_balance <= 0:
                    logger.info(f"No outstanding balance for {student_id}, skipping payment check")
                    return {"status": f"No outstanding balance for {student_id}"}, 200
        else:
            logger.debug(f"No contact in DB, fetching via API for {student_id}")
            try:
                profile = client.get_student_profile(student_id)
                if not profile or "data" not in profile:
                    logger.error(f"No profile found for {student_id} in API")
                    session.add(FailedSync(student_id=student_id, error="Profile not found in API"))
                    session.commit()
                    return {"error": "Profile not found"}, 404
                profile_data = profile["data"]
                firstname = profile_data.get("firstname")
                lastname = profile_data.get("lastname")
                student_mobile = profile_data.get("student_mobile")
                guardian_mobile = profile_data.get("guardian_mobile_number")

                if student_mobile == "nan" or not student_mobile:
                    logger.error(f"No valid student_mobile for {student_id}")
                    session.add(FailedSync(student_id=student_id, error="No valid student_mobile"))
                    session.commit()
                    return {"error": "No valid student_mobile in profile"}, 400

                if not student_mobile.startswith("+"):
                    student_mobile = f"+263{student_mobile.lstrip('0')}"
                if guardian_mobile == "nan" or not guardian_mobile:
                    guardian_mobile = None
                if guardian_mobile and not guardian_mobile.startswith("+"):
                    guardian_mobile = f"+263{guardian_mobile.lstrip('0')}"

                phone_number = student_mobile
                fullname = f"{firstname} {lastname}".strip() if firstname and lastname else "Parent/Guardian"

                contact = StudentContact(
                    student_id=student_id,
                    firstname=firstname,
                    lastname=lastname,
                    student_mobile=student_mobile,
                    guardian_mobile_number=guardian_mobile,
                    preferred_phone_number=phone_number,
                    outstanding_balance=None,
                    last_updated=datetime.datetime.now(datetime.timezone.utc),
                    last_api_sync=datetime.datetime.now(datetime.timezone.utc)
                )
                session.add(contact)
                session.commit()
                logger.info(f"Cached contact for {student_id}: {phone_number}")
            except RateLimitException as e:
                logger.warning(f"Rate limit hit fetching profile for {student_id}, retrying after {e.period_remaining} seconds")
                time.sleep(e.period_remaining)
                profile = client.get_student_profile(student_id)
                # Repeat profile processing logic
                if not profile or "data" not in profile:
                    logger.error(f"No profile found for {student_id} in API after retry")
                    session.add(FailedSync(student_id=student_id, error="Profile not found in API after retry"))
                    session.commit()
                    return {"error": "Profile not found after retry"}, 404
                profile_data = profile["data"]
                firstname = profile_data.get("firstname")
                lastname = profile_data.get("lastname")
                student_mobile = profile_data.get("student_mobile")
                guardian_mobile = profile_data.get("guardian_mobile_number")

                if student_mobile == "nan" or not student_mobile:
                    logger.error(f"No valid student_mobile for {student_id}")
                    session.add(FailedSync(student_id=student_id, error="No valid student_mobile"))
                    session.commit()
                    return {"error": "No valid student_mobile in profile"}, 400

                if not student_mobile.startswith("+"):
                    student_mobile = f"+263{student_mobile.lstrip('0')}"
                if guardian_mobile == "nan" or not guardian_mobile:
                    guardian_mobile = None
                if guardian_mobile and not guardian_mobile.startswith("+"):
                    guardian_mobile = f"+263{guardian_mobile.lstrip('0')}"

                phone_number = student_mobile
                fullname = f"{firstname} {lastname}".strip() if firstname and lastname else "Parent/Guardian"

                contact = StudentContact(
                    student_id=student_id,
                    firstname=firstname,
                    lastname=lastname,
                    student_mobile=student_mobile,
                    guardian_mobile_number=guardian_mobile,
                    preferred_phone_number=phone_number,
                    outstanding_balance=None,
                    last_updated=datetime.datetime.now(datetime.timezone.utc),
                    last_api_sync=datetime.datetime.now(datetime.timezone.utc)
                )
                session.add(contact)
                session.commit()
                logger.info(f"Cached contact for {student_id}: {phone_number}")
            except Exception as e:
                logger.error(f"Failed to fetch profile for {student_id}: {str(e)}")
                session.add(FailedSync(student_id=student_id, error=f"Failed to fetch profile: {str(e)}"))
                session.commit()
                return {"error": f"Failed to fetch profile: {str(e)}"}, 500

        if not phone_number:
            logger.error(f"No phone number available for {student_id}")
            session.add(FailedSync(student_id=student_id, error="No phone number available"))
            session.commit()
            return {"error": "Phone number required"}, 400

        # Fetch payments (or use test data)
        if test_mode:
            total_paid = test_payment_percentage * 10
            total_fees = 1000.0
            balance = total_fees - total_paid
            payment_data = {"data": [{"amount": total_paid}]}
        else:
            try:
                payment_data = client.get_student_payments(student_id, term)
                logger.debug(f"Raw payment response: {payment_data}")

                if not isinstance(payment_data, dict):
                    logger.error(f"Expected dict for payments, got {type(payment_data)}: {payment_data}")
                    return {"error": f"Invalid payment data: expected dict, got {type(payment_data)}"}, 400

                if "data" not in payment_data:
                    logger.error(f"Missing 'data' key in payments for {student_id}")
                    return {"error": "Missing 'data' key in payment response"}, 400
            except RateLimitException as e:
                logger.warning(f"Rate limit hit fetching payments for {student_id}, retrying after {e.period_remaining} seconds")
                time.sleep(e.period_remaining)
                payment_data = client.get_student_payments(student_id, term)
                if not isinstance(payment_data, dict):
                    logger.error(f"Expected dict for payments after retry, got {type(payment_data)}: {payment_data}")
                    return {"error": f"Invalid payment data: expected dict, got {type(payment_data)}"}, 400
                if "data" not in payment_data:
                    logger.error(f"Missing 'data' key in payments for {student_id} after retry")
                    return {"error": "Missing 'data' key in payment response"}, 400
            except Exception as e:
                if "404 Client Error" in str(e):
                    logger.info(f"No payments found for {student_id} in term {term}")
                    return {"status": f"No payments found for {student_id}"}, 200
                logger.error(f"Failed to fetch payments for {student_id}: {str(e)}")
                return {"error": f"Failed to fetch payments: {str(e)}"}, 500

            if not payment_data.get("data"):
                logger.info(f"No new payments found for {student_id}")
                return {"status": f"No new payments for {student_id}"}, 200

            # Calculate total paid
            try:
                valid_payments = [
                    payment for payment in payment_data["data"]
                    if isinstance(payment, dict) and "amount" in payment
                ]
                if not valid_payments:
                    logger.warning(f"Payment data contains no valid 'amount' fields: {payment_data['data']}")
                    return {"status": f"No valid payments for {student_id}"}, 200
                total_paid = sum(float(payment["amount"]) for payment in valid_payments)
            except Exception as e:
                logger.error(f"Error processing payments for {student_id}: {str(e)}")
                return {"error": f"Error calculating total payments: {str(e)}"}, 500

            if total_paid <= 0:
                logger.info(f"Payments exist but none are valid (> 0) for {student_id}")
                return {"status": f"No valid payments for {student_id}"}, 200

            # Fetch account statement
            try:
                statement = client.get_student_account_statement(student_id, term)
                logger.debug(f"Statement for {student_id}: {statement}")
                if not isinstance(statement, dict) or "data" not in statement:
                    logger.error(f"Invalid statement format for {student_id}: {statement}")
                    return {"error": "Invalid account statement format"}, 400
                total_fees = float(statement.get("data", {}).get("total_fees", 1000.0))
                balance = float(statement.get("data", {}).get("balance", 0))
            except RateLimitException as e:
                logger.warning(f"Rate limit hit fetching account statement for {student_id}, retrying after {e.period_remaining} seconds")
                time.sleep(e.period_remaining)
                statement = client.get_student_account_statement(student_id, term)
                if not isinstance(statement, dict) or "data" not in statement:
                    logger.error(f"Invalid statement format for {student_id}: {statement}")
                    return {"error": "Invalid account statement format"}, 400
                total_fees = float(statement.get("data", {}).get("total_fees", 1000.0))
                balance = float(statement.get("data", {}).get("balance", 0))
            except Exception as e:
                logger.error(f"Failed to fetch account statement: {str(e)}")
                return {"error": f"Failed to fetch account statement: {str(e)}"}, 500

            # Update cached balance
            if contact:
                contact.outstanding_balance = balance
                contact.last_updated = datetime.datetime.now(datetime.timezone.utc)
                session.commit()

        # Send payment confirmation ONLY if new payment detected
        last_paid = contact.last_total_paid or 0.0
        if total_paid > last_paid:
            payment_percentage = (total_paid / total_fees) * 100
            message = (
                f"Dear {fullname}, thank you for your payment of ${total_paid - last_paid} for {student_id} (Term {term}). "
                f"Total paid: ${total_paid}. Your current balance is ${balance}."
            )
            try:
                send_whatsapp_message(phone_number, message)
                logger.info(f"Sent payment confirmation for {student_id} to {phone_number}")
                
                # Update last_total_paid to prevent duplicate messages
                contact.last_total_paid = total_paid
                session.commit()
            except Exception as e:
                logger.error(f"Failed to send WhatsApp message for {student_id}: {str(e)}")
                return {"error": f"Failed to send payment confirmation: {str(e)}"}, 500
        else:
            logger.info(f"No new payments for {student_id} (Total: {total_paid}, Last Ack: {last_paid})")
            payment_percentage = (total_paid / total_fees) * 100

        # Generate gate pass if payment meets threshold
        if payment_percentage >= 50:
            with current_app.test_client() as client:
                response = client.post(
                    f"/generate-gatepass?student_id={student_id}&term={term}&payment_amount={total_paid}&total_fees={total_fees}"
                )
                if response.status_code != 200:
                    logger.error(f"Failed to generate gate pass for {student_id}: {response.json}")
                    return {"error": f"Failed to generate gate pass: {response.json.get('error', 'Unknown error')}"}, response.status_code
                logger.info(f"Gate pass generated for {student_id}: {response.json}")
                gate_pass_data = response.json
                # Send additional gate pass notification
                message = (
                    f"Dear {fullname}, a gate pass has been issued for {student_id} (Term {term}). "
                    f"Payment: {payment_percentage:.2f}%. Expiry: {gate_pass_data.get('expiry_date')}. "
                    f"Check your WhatsApp for the PDF."
                )
                try:
                    send_whatsapp_message(phone_number, message)
                    logger.info(f"Sent gate pass notification for {student_id} to {phone_number}")
                except Exception as e:
                    logger.error(f"Failed to send gate pass notification for {student_id}: {str(e)}")
                    return {"error": f"Failed to send gate pass notification: {str(e)}"}, 500

        return {"status": "Payment processed", "phone_number": phone_number, "payment_percentage": payment_percentage}, 200

    except Exception as e:
        logger.error(f"Unhandled error in check_new_payments for {student_id}: {str(e)}")
        return {"error": f"Unhandled error: {str(e)}"}, 500
    finally:
        if owns_session:
            session.remove()