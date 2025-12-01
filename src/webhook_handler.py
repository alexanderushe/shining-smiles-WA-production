# webhook_handler.py - WhatsApp Cloud API Webhook Handler for Lambda

# Add this at the VERY top of the file
import sys
import os
sys.path.insert(0, os.path.dirname(__file__))
# Add the current directory to Python path
current_dir = os.path.dirname(os.path.abspath(__file__))
if current_dir not in sys.path:
    sys.path.insert(0, current_dir)

print(f"🎯 DEBUG: Python path: {sys.path}")
print(f"🎯 DEBUG: Current directory: {current_dir}")
print(f"🎯 DEBUG: Files in current dir: {os.listdir(current_dir)}")
import json
import uuid
import re
import traceback
import requests
import config
from datetime import datetime, timezone, date

print("🎯 DEBUG: All imports successful!")

# Core imports (relative for Lambda bundle)
try:
    from utils.database import init_db, StudentContact, UserState
    from utils.whatsapp import send_whatsapp_message
    from utils.logger import setup_logger
    from api.sms_client import SMSClient, RateLimitException
    from utils.ai_client import generate_ai_response
    from config import get_config
    from services.gatepass_service import generate_gatepass
    print("🎯 DEBUG: All custom imports successful!")
except ImportError as e:
    print(f"🎯 DEBUG: Import error: {e}")
    traceback.print_exc()
    # Fallback for critical functions
    def send_whatsapp_message(to, message, use_cloud_api=True):
        print(f"🎯 FALLBACK: Would send to {to}: {message}")
        return {"status": "fallback"}
    
    # Fallback for generate_gatepass
    def generate_gatepass(student_id, term, payment_amount, total_fees, request_id, requesting_whatsapp_number=None):
        print(f"🎯 FALLBACK: generate_gatepass called for {student_id}")
        return {"error": "Gate pass service temporarily unavailable. Please try again later."}, 503
    
    logger = type('Logger', (), {'info': print, 'error': print, 'warning': print, 'debug': print})()
    config = type('Config', (), {})()
    print("🎯 DEBUG: Fallback imports created!")

logger = setup_logger(__name__) if 'setup_logger' in locals() else logger
config = get_config() if 'get_config' in locals() else config

print("🎯 DEBUG: Logger and config setup complete!")

def handle_whatsapp_message(whatsapp_number, message_body, session, sms_client, ai_response_function, request_id):
    """
    Handle WhatsApp message logic - extracted from src/routes/whatsapp.py
    Returns the response text to send back to the user
    """
    current_time = datetime.now(timezone.utc)
    extra_log = {"phone_number": whatsapp_number, "request_id": request_id}
    ai_client = ai_response_function

    menu_text = (
        "Reply with a number or keyword:\n"
        "➊ *View Balance*\n"
        "➋ *Request Statement*\n"
        "➌ *Get Gate Pass*\n"
    )
    unregistered_menu_text = (
        "Reply with a number or keyword:\n"
        "➊ *About Our School* ✨\n"
        "➋ *Admissions Info* 📚\n"
        "➌ *Upcoming Events* 🎉\n"
        "➍ *Contact Us* 📞\n"
        "➎ *Help* ❓"
    )
    unregistered_prompt = (
        "😊 *Welcome to Shining Smiles School!* I'm _Mya_, your friendly assistant here to help with questions about our school, admissions, events, or how to reach us. "
        "Ask me anything or reply *menu* for options. For account-related queries, contact _admin@shiningsmilescollege.ac.zw_. ✨"
    )

    if not re.match(r'^\+\d{10,15}$', whatsapp_number):
        logger.error(f"Invalid WhatsApp number format: {whatsapp_number}", extra={"request_id": request_id})
        return "⚠️ Invalid phone number format. Please contact support."

    # Handle case where database is not available
    if session is None:
        print("🎯 DEBUG: No database session, using fallback responses")
        if message_body in ["menu", "start"]:
            return f"{unregistered_prompt}\n\n{unregistered_menu_text}"
        elif "hello" in message_body or "hi" in message_body:
            return "Hello from Shining Smiles! 🎯 How can I help you today? Reply 'menu' for options."
        else:
            if ai_response_function and callable(ai_response_function):
                try:
                    ai_response = ai_response_function(message_body)
                    return f"🤖 {ai_response}"
                except Exception as e:
                    print(f"🎯 DEBUG: AI response error: {e}")
            
            # Fallback responses
            if "location" in message_body or "where" in message_body or "school" in message_body:
                return "📍 Shining Smiles College is located at 12 Churchill Avenue, Alexandra Park, Harare. From town, head north on Churchill Avenue past the Avenues area. We're about 2km from the city center with bright blue gates! 🎓"
            
            if "hi" in message_body or "hello" in message_body:
                return "Hello! 👋 Welcome to Shining Smiles College! How can I help you today?"
            
            return "Thanks for your message! How can I assist you? Reply 'menu' for options or ask me anything about our college. 😊"

    # Database is available - use full logic
    contacts = session.query(StudentContact).filter((StudentContact.student_mobile == whatsapp_number) |
                                                    (StudentContact.guardian_mobile_number == whatsapp_number) |
                                                    (StudentContact.preferred_phone_number == whatsapp_number)).all()

    user_state = session.query(UserState).filter_by(phone_number=whatsapp_number).first()

    if not user_state:
        user_state = UserState(
            phone_number=whatsapp_number,
            state="main_menu",
            query_count=0,
            last_updated=current_time
        )
        session.add(user_state)
        session.commit()

    current_date = current_time.date()
    extra_log = {"request_id": request_id, "whatsapp_number": whatsapp_number}

    # Rate limiting for unregistered users (if applicable)
    if user_state.state == "unregistered_menu":
        if hasattr(user_state, 'query_date') and user_state.query_date != current_date:
            user_state.query_count = 0
            user_state.query_date = current_date
            session.commit()
        if user_state.query_count >= 5:
            return f"⚠️ *Daily query limit reached.* Please try again tomorrow or contact _admin@shiningsmilescollege.ac.zw_.\n{unregistered_prompt}"

    # Query all contacts associated with the phone number
    contacts = session.query(StudentContact).filter((StudentContact.student_mobile == whatsapp_number) |
                                                    (StudentContact.guardian_mobile_number == whatsapp_number) |
                                                    (StudentContact.preferred_phone_number == whatsapp_number)).all()
    if not contacts:
        extra_log["student_id"] = None
        if message_body == "menu":
            return unregistered_menu_text

        elif message_body in ["1", "about", "about our school"]:
            logger.info(f"Processing 'about' query for {whatsapp_number}", extra=extra_log)
            user_state.query_count += 1
            user_state.last_updated = current_time
            session.commit()
            if ai_client:
                ai_response = ai_client("Tell me about Shining Smiles School.")
                return f"✨ {ai_response}"
            return "✨ Shining Smiles School is a vibrant learning community dedicated to nurturing young minds."

        elif message_body in ["2", "admissions", "admissions info"]:
            user_state.query_count += 1
            user_state.last_updated = current_time
            session.commit()
            if ai_client:
                ai_response = ai_client("Tell me about admissions at Shining Smiles School.")
                return f"📚 {ai_response}"
            return "📚 Admissions are open year-round. Contact admin@shiningsmilescollege.ac.zw for details."

        elif message_body in ["3", "events", "upcoming events"]:
            user_state.query_count += 1
            user_state.last_updated = current_time
            session.commit()
            if ai_client:
                ai_response = ai_client("What are the upcoming events at Shining Smiles School?")
                return f"🎉 {ai_response}"
            return "🎉 Upcoming: Parent-Teacher Meeting on Nov 15. Stay tuned!"

        elif message_body in ["4", "contact", "contact us"]:
            user_state.query_count += 1
            user_state.last_updated = current_time
            session.commit()
            if ai_client:
                ai_response = ai_client("How can I contact Shining Smiles School?")
                return f"📞 {ai_response}"
            return "📞 Email: admin@shiningsmilescollege.ac.zw | Phone: +263 123 4567"

        elif message_body in ["5", "help"]:
            return (
                f"❓ *Help*: Ask me anything about Shining Smiles School or reply *menu* for options. "
                f"For account-related queries, contact _admin@shiningsmilescollege.ac.zw_.\n{unregistered_menu_text}"
            )

        else:
            user_state.query_count += 1
            user_state.last_updated = current_time
            session.commit()
            if ai_client:
                ai_response = ai_client(message_body)
                return f"😊 {ai_response}"
            return "😊 I'm here to help! Reply 'menu' for options."

    # Handle registered users
    fullname = f"{contacts[0].firstname or 'Parent'} {contacts[0].lastname or ''}".strip()
    student_ids = [contact.student_id for contact in contacts if contact.student_id and re.match(r'^SSC\d+$', contact.student_id)]
    extra_log["student_ids"] = student_ids

    if not student_ids:
        user_state.state = "main_menu"
        user_state.last_updated = current_time
        session.commit()
        return f"👋 *Hi {fullname},*\nNo valid student IDs registered. Please contact _admin@shiningsmilescollege.ac.zw_.\n{menu_text}"

    try:
        default_term = next(
            (term for term, start in config.TERM_START_DATES.items() if start.date() <= current_date <= config.TERM_END_DATES[term].date()),
            None
        )
        if not default_term or not re.match(r'^\d{4}-\d$', default_term):
            default_term = "2025-2"
            logger.warning(f"Invalid or unconfigured default term, using fallback: {default_term}", extra=extra_log)

        if user_state.state == "main_menu":
            if message_body == "menu":
                user_state.state = "main_menu"
                user_state.last_updated = current_time
                session.commit()
                return f"👋 *Hi {fullname},*\n*Welcome to Shining Smiles School!* 😊\n{menu_text}"

            elif message_body in ["1", "balance", "view balance"]:
                user_state.state = "awaiting_term_balance"
                user_state.last_updated = current_time
                session.commit()
                return f"📊 *Hi {fullname},*\nPlease reply with a valid term (e.g., *2025-1*, *2025-2*, *2025-3*) for all students."

            elif message_body in ["2", "statement", "request statement"]:
                try:
                    if not re.match(r'^\d{4}-\d$', default_term) or default_term not in config.TERM_START_DATES:
                        logger.error(f"Invalid or unconfigured default term: {default_term}", extra=extra_log)
                        user_state.state = "awaiting_term_statement"
                        user_state.last_updated = current_time
                        session.commit()
                        return f"📊 *Hi {fullname},*\nPlease reply with a valid term (e.g., *2025-1*, *2025-2*, *2025-3*) for all students.\n{menu_text}"

                    term_start = config.TERM_START_DATES.get(default_term)
                    if term_start and term_start.date() > current_date:
                        user_state.state = "main_menu"
                        user_state.last_updated = current_time
                        session.commit()
                        return f"📅 *Hi {fullname},*\nTerm *{default_term}* has not started yet. Please select a current or past term (e.g., *2025-1*, *2025-2*) for all students.\n{menu_text}"

                    statement_texts = []
                    max_message_length = 4000  # Higher limit for WhatsApp
                    for student_id in student_ids:
                        start_time = datetime.now(timezone.utc)
                        account = sms_client.get_student_account_statement(student_id, default_term)
                        billed_fees = sms_client.get_student_billed_fees(student_id, default_term)
                        payments = sms_client.get_student_payments(student_id, default_term)
                        elapsed_time = (datetime.now(timezone.utc) - start_time).total_seconds()
                        if elapsed_time > 25:
                            logger.warning(f"API calls for statement took {elapsed_time}s, risking timeout for {student_id}", extra=extra_log)

                        logger.debug(f"Account Statement for {student_id}, Term {default_term}: "
                                     f"API account data: {account}, "
                                     f"Billed fees: {billed_fees}, "
                                     f"Payments: {payments}", extra=extra_log)

                        total_fees = sum(float(bill["amount"]) for bill in billed_fees.get("data", {}).get("bills", [])) if billed_fees.get("data", {}).get("bills") else 0.0
                        total_paid = sum(float(p["amount"]) for p in payments.get("data", {}).get("payments", [])) if payments.get("data", {}).get("payments") else 0.0
                        balance = total_fees - total_paid

                        student_name = next((f"{c.firstname or ''} {c.lastname or ''}".strip() for c in contacts if c.student_id == student_id), "Unknown")
                        if not billed_fees.get("data", {}).get("bills"):
                            statement_text = f"*No fees recorded for {student_id} ({student_name}) in term {default_term}.*"
                        else:
                            payment_details = (
                                "\n".join(
                                    [f"- *${p['amount']:.2f}* on _{p.get('date', 'N/A')}_ ({p.get('fee_type', 'N/A')})" for p in payments.get("data", {}).get("payments", [])]
                                )
                                if payments.get("data", {}).get("payments")
                                else "No payments recorded."
                            )
                            fee_details = (
                                "\n".join(
                                    [f"- *${b['amount']:.2f}* on _{b.get('date', 'N/A')}_ ({b.get('fee_type', 'N/A')})" for b in billed_fees.get("data", {}).get("bills", [])]
                                )
                                if billed_fees.get("data", {}).get("bills")
                                else "No fees recorded."
                            )
                            statement_text = (
                                f"*Account Statement for {student_id} ({student_name}, Term {default_term})*:\n"
                                f"*Total Fees*: ${total_fees:.2f}\n"
                                f"*Total Paid*: ${total_paid:.2f}\n"
                                f"*Balance Owed*: ${balance:.2f}\n"
                                f"*Fees Charged*:\n{fee_details}\n"
                                f"*Payments*:\n{payment_details}"
                            ) if balance != 0.0 or total_fees <= 0.0 else (
                                f"*Account Statement for {student_id} ({student_name}, Term {default_term})*:\n"
                                f"*Great news!* Balance is *fully paid*.\n"
                                f"*Total Fees*: ${total_fees:.2f}\n"
                                f"*Total Paid*: ${total_paid:.2f}\n"
                                f"*Balance Owed*: ${balance:.2f}\n"
                                f"*Fees Charged*:\n{fee_details}\n"
                                f"*Payments*:\n{payment_details}"
                            )

                            # Truncate if too long
                            if len(statement_text) > max_message_length:
                                statement_text = statement_text[:max_message_length - 50] + "\n*Note*: Statement truncated due to length. Contact admin for full details."
                        statement_texts.append(statement_text)

                    if not statement_texts:
                        user_state.state = "main_menu"
                        user_state.last_updated = current_time
                        session.commit()
                        return f"📊 *Hi {fullname},*\nNo account statements found for any students in term *{default_term}*. Please contact _admin@shiningsmilescollege.ac.zw_.\n{menu_text}"
                    else:
                        combined_text = f"📊 *Hi {fullname},*\n" + "\n\n".join(statement_texts) + f"\n{menu_text}"
                        if len(combined_text) > max_message_length:
                            # For simplicity, truncate; in production, split and send multiple
                            combined_text = combined_text[:max_message_length] + "\n*Note*: Full statement available via admin.\n{menu_text}"
                        user_state.state = "main_menu"
                        user_state.last_updated = current_time
                        session.commit()
                        return combined_text

                except RateLimitException:
                    logger.warning(f"Rate limit hit while fetching statements for {student_ids}, term {default_term}", extra=extra_log)
                    user_state.state = "main_menu"
                    user_state.last_updated = current_time
                    session.commit()
                    return f"⚠️ *Hi {fullname},*\n*Too many requests.* Please try again shortly.\n{menu_text}"
                except ValueError as e:
                    logger.error(f"Account statement error for {student_ids}, term {default_term}: {str(e)}\n{traceback.format_exc()}", extra=extra_log)
                    user_state.state = "main_menu"
                    user_state.last_updated = current_time
                    session.commit()
                    return f"⚠️ *Hi {fullname},*\nNo account statements found for students in term *{default_term}*. Please contact _admin@shiningsmilescollege.ac.zw_.\n{menu_text}"
                except requests.RequestException as e:
                    logger.error(f"Failed to fetch statements for {student_ids}, term {default_term}: {str(e)}\n{traceback.format_exc()}", extra=extra_log)
                    user_state.state = "main_menu"
                    user_state.last_updated = current_time
                    session.commit()
                    return f"⚠️ *Hi {fullname},*\nError fetching statements for term *{default_term}*. Please contact _admin@shiningsmilescollege.ac.zw_.\n{menu_text}"
                except Exception as e:
                    logger.error(f"Unexpected error in statement generation for {student_ids}, term {default_term}: {str(e)}\n{traceback.format_exc()}", extra=extra_log)
                    user_state.state = "main_menu"
                    user_state.last_updated = current_time
                    session.commit()
                    return f"⚠️ *Hi {fullname},*\n*An unexpected error occurred.* Please contact _admin@shiningsmilescollege.ac.zw_.\n{menu_text}"

            elif message_body in ["3", "gate pass", "get gate pass"]:
                try:
                    logger.debug(f"Attempting gate passes for student_ids: {student_ids}, term: {default_term}", extra=extra_log)
                    if not default_term:
                        next_term = min(
                            (term for term, start in config.TERM_START_DATES.items() if start.date() > current_date),
                            key=lambda t: config.TERM_START_DATES[t].date(),
                            default=None
                        )
                        next_term_date = config.TERM_START_DATES[next_term].date().strftime("%d %B %Y") if next_term else "a future date"
                        user_state.state = "main_menu"
                        user_state.last_updated = current_time
                        session.commit()
                        return f"📅 *Hi {fullname},*\nGate passes are only issued during active school terms. Schools reopen on {next_term_date} for Term {next_term or '3'}. Please try again then.\n{menu_text}"

                    if not re.match(r'^\d{4}-\d$', default_term) or default_term not in config.TERM_START_DATES:
                        logger.error(f"Invalid or unconfigured default term: {default_term}", extra=extra_log)
                        user_state.state = "awaiting_term_gatepass"
                        user_state.last_updated = current_time
                        session.commit()
                        return f"📅 *Hi {fullname},*\nPlease reply with a valid term (e.g., *2025-1*, *2025-2*, *2025-3*) for all students.\n{menu_text}"

                    term_start = config.TERM_START_DATES.get(default_term)
                    if term_start and term_start.date() > current_date:
                        user_state.state = "awaiting_term_gatepass"
                        user_state.last_updated = current_time
                        session.commit()
                        return f"📅 *Hi {fullname},*\nTerm *{default_term}* has not started yet. Please select a current or past term (e.g., *2025-1*, *2025-2*) for all students.\n{menu_text}"

                    gatepass_texts = []
                    for student_id in student_ids:
                        billed_fees = sms_client.get_student_billed_fees(student_id, default_term)
                        total_fees = sum(float(bill["amount"]) for bill in billed_fees.get("data", {}).get("bills", [])) if billed_fees.get("data", {}).get("bills") else 0.0
                        payments = sms_client.get_student_payments(student_id, default_term)
                        total_paid = sum(float(p["amount"]) for p in payments.get("data", {}).get("payments", [])) if payments.get("data", {}).get("payments") else 0.0

                        logger.debug(f"[GatePass] {student_id} - Paid: {total_paid}, Total Fees: {total_fees}, Term: {default_term}", extra=extra_log)

                        # Call the gatepass service directly instead of HTTP request
                        try:
                            result, status_code = generate_gatepass(
                                student_id=student_id,
                                term=default_term,
                                payment_amount=total_paid,
                                total_fees=total_fees,
                                request_id=request_id,
                                requesting_whatsapp_number=whatsapp_number  # Pass the validated WhatsApp number
                            )

                            logger.debug(f"[GatePass Response] {student_id} - {status_code} - {result}", extra=extra_log)

                            status_msg = result.get("status", "").lower() if isinstance(result, dict) else ""

                            student_name = next((f"{c.firstname or ''} {c.lastname or ''}".strip() for c in contacts if c.student_id == student_id), "Unknown")
                            
                            if status_code == 200:
                                if "already valid" in status_msg or "resent" in status_msg:
                                    gatepass_texts.append(
                                        f"*Gate Pass for {student_id} ({student_name})*:\n"
                                        f"You *already have a valid gate pass*.\n"
                                        f"*Pass ID*: {result.get('pass_id')}\n"
                                        f"*Expires*: _{result.get('expiry_date')}_\n"
                                        f"*PDF re-sent to*: {result.get('whatsapp_number')}"
                                    )
                                else:
                                    gatepass_texts.append(
                                        f"*Gate Pass for {student_id} ({student_name})*:\n"
                                        f"*Gate Pass Issued!* 🎉\n"
                                        f"*Pass ID*: {result.get('pass_id')}\n"
                                        f"*Expires*: _{result.get('expiry_date')}_\n"
                                        f"*Sent to*: {result.get('whatsapp_number')}"
                                    )
                            else:
                                error_msg = result.get("error", "Could not issue gate pass.") if isinstance(result, dict) else "Could not issue gate pass."
                                gatepass_texts.append(
                                    f"*Gate Pass for {student_id} ({student_name})*:\n"
                                    f"*{error_msg}*"
                                )

                        except Exception as e:
                            logger.error(f"Gate pass service error for {student_id}: {str(e)}", extra=extra_log)
                            # student_name must be defined before accessing it in exception handler
                            student_name = next((f"{c.firstname or ''} {c.lastname or ''}".strip() for c in contacts if c.student_id == student_id), "Unknown")
                            gatepass_texts.append(
                                f"*Gate Pass for {student_id} ({student_name})*:\n"
                                f"*Service temporarily unavailable*"
                            )


                    if not gatepass_texts:
                        user_state.state = "main_menu"
                        user_state.last_updated = current_time
                        session.commit()
                        return f"⚠️ *Hi {fullname},*\n*No gate passes issued.* Please contact _admin@shiningsmilescollege.ac.zw_.\n{menu_text}"
                    else:
                        response_text = f"✅ *Hi {fullname},*\n" + "\n\n".join(gatepass_texts) + f"\nIf not received, ensure *{whatsapp_number}* is registered with WhatsApp or contact _admin@shiningsmilescollege.ac.zw_.\n{menu_text}"
                        user_state.state = "main_menu"
                        user_state.last_updated = current_time
                        session.commit()
                        return response_text

                except RateLimitException:
                    logger.warning(f"Rate limit hit while fetching gate pass data for {student_ids}, term {default_term}", extra=extra_log)
                    user_state.state = "main_menu"
                    user_state.last_updated = current_time
                    session.commit()
                    return f"⚠️ *Hi {fullname},*\n*Too many requests.* Please try again shortly.\n{menu_text}"
                except ValueError as e:
                    logger.error(f"Gate pass error for {student_ids}, term {default_term}: {str(e)}\n{traceback.format_exc()}", extra=extra_log)
                    user_state.state = "main_menu"
                    user_state.last_updated = current_time
                    session.commit()
                    return f"⚠️ *Hi {fullname},*\n*No financial data found* for students in term *{default_term}*. Please contact _admin@shiningsmilescollege.ac.zw_.\n{menu_text}"
                except requests.RequestException as e:
                    logger.error(f"Failed to generate gate passes for {student_ids}, term {default_term}: {str(e)}\n{traceback.format_exc()}", extra=extra_log)
                    user_state.state = "main_menu"
                    user_state.last_updated = current_time
                    session.commit()
                    return f"❌ *Hi {fullname},*\n*Failed to generate gate passes* for term *{default_term}*. Please contact _admin@shiningsmilescollege.ac.zw_.\n{menu_text}"
                except Exception as e:
                    logger.error(f"Unexpected error in gate pass generation for {student_ids}, term {default_term}: {str(e)}\n{traceback.format_exc()}", extra=extra_log)
                    user_state.state = "main_menu"
                    user_state.last_updated = current_time
                    session.commit()
                    return f"⚠️ *Hi {fullname},*\n*An unexpected error occurred.* Please contact _admin@shiningsmilescollege.ac.zw_.\n{menu_text}"

            elif message_body == "help":
                user_state.state = "main_menu"
                user_state.last_updated = current_time
                session.commit()
                return f"❓ *Hi {fullname},*\n*Help*: Reply with *menu* to see options or contact _admin@shiningsmilescollege.ac.zw_ for account issues.\n{menu_text}"

            else:
                return f"⚠️ *Hi {fullname},*\n*Invalid input.* Please reply with a valid option.\n{menu_text}"

        elif user_state.state in ["awaiting_term_balance", "awaiting_term_statement", "awaiting_term_gatepass"]:
            if message_body in config.TERM_START_DATES.keys():
                term = message_body
                try:
                    term_start = config.TERM_START_DATES.get(term)
                    if term_start and term_start.date() > current_date:
                        user_state.state = "main_menu"
                        user_state.last_updated = current_time
                        session.commit()
                        return f"📅 *Hi {fullname},*\nTerm *{term}* has not started yet. Please select a current or past term.\n{menu_text}"

                    # Handle based on state
                    if user_state.state == "awaiting_term_balance":
                        balance_texts = []
                        for student_id in student_ids:
                            account = sms_client.get_student_account_statement(student_id, term)
                            billed_fees = sms_client.get_student_billed_fees(student_id, term)
                            payments = sms_client.get_student_payments(student_id, term)

                            total_fees = sum(float(bill["amount"]) for bill in billed_fees.get("data", {}).get("bills", [])) if billed_fees.get("data", {}).get("bills") else 0.0
                            total_paid = sum(float(p["amount"]) for p in payments.get("data", {}).get("payments", [])) if payments.get("data", {}).get("payments") else 0.0
                            balance = total_fees - total_paid

                            student_name = next((f"{c.firstname or ''} {c.lastname or ''}".strip() for c in contacts if c.student_id == student_id), "Unknown")
                            if not billed_fees.get("data", {}).get("bills"):
                                balance_texts.append(f"*No fees recorded for {student_id} ({student_name}) in term {term}.*")
                            elif balance == 0.0 and total_fees > 0.0:
                                balance_texts.append(
                                    f"*Balance for {student_id} ({student_name}, Term {term})*:\n"
                                    f"*Great news!* Balance is *fully paid*.\n"
                                    f"*Total Fees*: ${total_fees:.2f}\n"
                                    f"*Total Paid*: ${total_paid:.2f}\n"
                                    f"*Balance Owed*: ${balance:.2f}"
                                )
                            else:
                                balance_texts.append(
                                    f"*Balance for {student_id} ({student_name}, Term {term})*:\n"
                                    f"*Total Fees*: ${total_fees:.2f}\n"
                                    f"*Total Paid*: ${total_paid:.2f}\n"
                                    f"*Balance Owed*: ${balance:.2f}"
                                )

                        if not balance_texts:
                            response_text = f"📊 *Hi {fullname},*\nNo fees recorded for any students in term *{term}*. Please contact _admin@shiningsmilescollege.ac.zw_.\n{menu_text}"
                        else:
                            response_text = f"📊 *Hi {fullname},*\n" + "\n\n".join(balance_texts) + f"\n{menu_text}"
                        user_state.state = "main_menu"
                        user_state.last_updated = current_time
                        session.commit()
                        return response_text
                    # Similar handling for other states (statement, gatepass) can be added here
                    # For now, fallback to balance logic or extend as needed

                except Exception as e:
                    logger.error(f"Error in term-specific handling for {term}: {str(e)}", extra=extra_log)
                    user_state.state = "main_menu"
                    user_state.last_updated = current_time
                    session.commit()
                    return f"⚠️ *Hi {fullname},*\nError fetching for term *{term}*. Please try again.\n{menu_text}"
            else:
                return f"📅 *Hi {fullname},*\n*Invalid term.* Please reply with a valid term (e.g., *2025-1*, *2025-2*, *2025-3*)."

        else:
            user_state.state = "main_menu"
            user_state.last_updated = current_time
            session.commit()
            return f"⚠️ *Hi {fullname},*\n*Invalid state.* Please reply with *menu* to start over.\n{menu_text}"

    except Exception as e:
        logger.error(f"[WhatsApp Menu Fatal Error] {str(e)}\n{traceback.format_exc()}", extra=extra_log)
        user_state.state = "main_menu"
        user_state.last_updated = current_time
        session.commit()
        return f"⚠️ *Hi {fullname},*\n*An unexpected error occurred.* Please contact _admin@shiningsmilescollege.ac.zw_.\n{menu_text}"

def process_cloud_api_message(message, metadata):
    """Process incoming WhatsApp Cloud API message using existing logic"""
    print("🎯 DEBUG: process_cloud_api_message ENTERED!")
    session = None
    try:
        request_id = str(uuid.uuid4())
        print("🎯 DEBUG: Initializing database...")
        
        # Try to initialize database, but continue even if it fails
        try:
            print("🎯 DEBUG: Testing init_db only...")
            session = init_db()
            print("🎯 DEBUG: init_db succeeded")
        except Exception as db_error:
            print(f"🎯 DEBUG: init_db failed: {db_error}")
            session = None
    
        
        # Test SMSClient separately
        try:
            print("🎯 DEBUG: Testing SMSClient only...")
            sms_client = SMSClient(request_id=request_id, use_cloud_api=True)
            print("🎯 DEBUG: SMSClient succeeded")
        except Exception as sms_error:
            print(f"🎯 DEBUG: SMSClient failed: {sms_error}")
            # Don't create a broken fallback - let it fail properly
            raise

        from_number = f"+{message.get('from')}"
        message_id = message.get("id")
        timestamp = message.get("timestamp")
        message_type = message.get("type")

        if message_type == "text":
            message_body = message.get("text", {}).get("body", "").strip().lower()
        else:
            print(f"🎯 DEBUG: Unsupported message type: {message_type}")
            return

        print(f"🎯 DEBUG: Processing message from {from_number}: '{message_body}'")

        try:
            from utils.ai_client import generate_ai_response
            ai_response_function = generate_ai_response
            print("✅ AI client initialized successfully")
        except Exception as ai_error:
            print(f"❌ AI client failed: {ai_error}")
            ai_response_function = None

        response_text = handle_whatsapp_message(
            from_number, message_body, session, sms_client, ai_response_function, request_id
        )

        print(f"🎯 DEBUG: Response generated: '{response_text}'")

        # Send response using Cloud API
        if response_text:
            print(f"🎯 DEBUG: Sending response to {from_number}")
            result = send_whatsapp_message_real(
                to=from_number,
                message=response_text
            )
            print(f"🎯 DEBUG: WhatsApp Response sent: {result}")

        if session:
            session.close()
        print("🎯 DEBUG: Message processing COMPLETED!")

    except Exception as e:
        print(f"🎯 DEBUG: ERROR in process_cloud_api_message: {e}")
        traceback.print_exc()
        if session:
            session.close()
    
# ===== REAL WHATSAPP SENDER =====
def send_whatsapp_message_real(to: str, message: str):
    import os
    import requests

    token = os.getenv("WHATSAPP_CLOUD_API_TOKEN")
    phone_number_id = os.getenv("WHATSAPP_CLOUD_NUMBER")
    
    # FIX: Add safety checks
    if token:
        print(f"USING PHONE NUMBER ID: {phone_number_id}")
        print(f"USING TOKEN: {token[:20]}...")
    else:
        print("❌ ERROR: Missing WHATSAPP_CLOUD_API_TOKEN")
        return {"error": "missing credentials"}

    if not token or not phone_number_id:
        print("ERROR: Missing WHATSAPP_CLOUD_API_TOKEN or WHATSAPP_CLOUD_NUMBER")
        return {"error": "missing credentials"}

    url = f"https://graph.facebook.com/v19.0/{phone_number_id}/messages"
    payload = {
        "messaging_product": "whatsapp",
        "to": to,
        "type": "text",
        "text": {"body": message}
    }
    headers = {
        "Authorization": f"Bearer {token}",
        "Content-Type": "application/json"
    }

    try:
        response = requests.post(url, json=payload, headers=headers, timeout=15)
        print(f"WhatsApp API → {response.status_code} {response.text}")
        if response.status_code == 200:
            return {"status": "sent", "data": response.json()}
        else:
            return {"error": f"HTTP {response.status_code}", "response": response.json()}
    except Exception as e:
        print(f"Exception sending WhatsApp message: {e}")
        return {"error": str(e)}

def lambda_handler(event, context):
    print("🎯 DEBUG: Lambda handler started")
    print("🎯 DEBUG: Event keys:", list(event.keys()))
    
    # Get HTTP method from different possible locations
    http_method = event.get('httpMethod') 
    if not http_method:
        http_method = event.get('requestContext', {}).get('http', {}).get('method')
    
    print(f"🎯 DEBUG: HTTP Method: {http_method}")
    
    if http_method == 'GET':
        # Webhook verification - only for GET requests
        print("🎯 DEBUG: Handling GET request (webhook verification)")
        query = event.get('queryStringParameters', {})
        verify_token = query.get('hub.verify_token')
        challenge = query.get('hub.challenge')
        
        expected_token = os.getenv("WHATSAPP_VERIFY_TOKEN")
        print(f"🎯 DEBUG: Expected token: {expected_token}, Received token: {verify_token}")
        
        if verify_token == expected_token:
            print("🎯 DEBUG: Webhook verification SUCCESS")
            return {
                'statusCode': 200,
                'headers': {'Content-Type': 'text/plain'},
                'body': challenge
            }
        else:
            print("🎯 DEBUG: Webhook verification FAILED")
            return {'statusCode': 403, 'body': 'Verification failed'}

    elif http_method == 'POST':
        # Message processing - no verification needed for POST
        print("🎯 DEBUG: Handling POST request (message processing)")
        try:
            # Parse the body
            body = event.get('body')
            if isinstance(body, str):
                body = json.loads(body)
            
            print("🎯 DEBUG: Parsed body:", json.dumps(body, default=str))
            
            if not body or body.get("object") != "whatsapp_business_account":
                print("🎯 DEBUG: Invalid body, returning OK")
                return {'statusCode': 200, 'body': 'OK'}

            print("🎯 DEBUG: Valid WhatsApp message received")
            
            # Process messages
            for entry in body.get("entry", []):
                for change in entry.get("changes", []):
                    value = change.get("value", {})
                    
                    # Skip status updates (read, delivered, etc.)
                    if "statuses" in value:
                        print("DEBUG: Ignoring status update")
                        continue
                        
                    if "messages" in value:
                        messages = value["messages"]
                        for message in messages:
                            process_cloud_api_message(message, value.get("metadata", {}))
            
            print("🎯 DEBUG: All messages processed, returning OK")
            return {'statusCode': 200, 'body': 'OK'}

        except json.JSONDecodeError as e:
            print("🎯 DEBUG: JSON decode error:", str(e))
            return {'statusCode': 400, 'body': 'Invalid JSON'}
        except Exception as e:
            print("🎯 DEBUG: Error in POST handler:", str(e))
            import traceback
            traceback.print_exc()
            return {'statusCode': 500, 'body': 'Error'}

    else:
        print(f"🎯 DEBUG: Unsupported method: {http_method}")
        return {'statusCode': 405, 'body': 'Method not allowed'}