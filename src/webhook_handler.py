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
import os
import logging
import hmac
import hashlib
import traceback
import uuid
import re
import requests
from flask import Flask, request, jsonify
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
        "──────────────\n"
        "➊ *View Balance*\n"
        "➋ *Request Statement*\n"
        "➌ *Get Gate Pass*\n"
        "──────────────\n"
        "_Reply 'menu' anytime to see options_"
    )
    
    def add_menu_if_needed(message, show_menu=False):
        """Only append menu when contextually appropriate"""
        if show_menu:
            return f"{message}\n\n{menu_text}"
        return message
    unregistered_menu_text = (
        "Reply with a number or keyword:\n"
        "➊ *About Our School* ✨\n"
        "➋ *Admissions Info* 📚\n"
        "➌ *Upcoming Events* 🎉\n"
        "➍ *Contact Us* 📞\n"
        "➎ *Help* ❓"
    )
    unregistered_prompt = (
        "*Welcome to Shining Smiles School!*\n"
        "I'm Mya, your assistant. I can help with questions about admissions, events, or general inquiries.\n\n"
        "Ask me anything or reply *menu* for options.\n"
        "For account-related queries, contact _admin@shiningsmilescollege.ac.zw_."
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
            
            return "How can I assist you today? Reply 'menu' for options or ask me anything about the school."

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
                return ai_response
            return "I'm here to help. Reply 'menu' for options."

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
            default_term = "2025-3"
            logger.warning(f"Invalid or unconfigured default term, using fallback: {default_term}", extra=extra_log)

        if user_state.state == "main_menu":
            if message_body == "menu":
                user_state.state = "main_menu"
                user_state.last_updated = current_time
                session.commit()
                return add_menu_if_needed(f"Hello, {fullname}.\nWhat can I help you with today?", show_menu=True)

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
                        combined_text = f"Account statement for term {default_term}:\n\n" + "\n\n".join(statement_texts)
                        if len(combined_text) > max_message_length:
                            combined_text = combined_text[:max_message_length] + "\n\n_Reply 'menu' for more options._"
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
                    term_end = config.TERM_END_DATES.get(default_term)
                    
                    if term_start and term_start.date() > current_date:
                        user_state.state = "awaiting_term_gatepass"
                        user_state.last_updated = current_time
                        session.commit()
                        return f"📅 *Hi {fullname},*\nTerm *{default_term}* has not started yet. Please select a current or past term (e.g., *2025-1*, *2025-2*) for all students.\n{menu_text}"

                    if term_end and current_date > term_end.date():
                        user_state.state = "main_menu"
                        user_state.last_updated = current_time
                        session.commit()
                        return f"⛔ *Hi {fullname},*\n*Gate Pass Request Denied.*\nTerm *{default_term}* ended on {term_end.strftime('%d %B %Y')}. Gate passes are only issued during active school terms.\n{menu_text}"

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
                        response_text = "Gate pass issued!\n\n" + "\n\n".join(gatepass_texts) + f"\n\n_If not received, ensure {whatsapp_number} is registered with WhatsApp._\n\n_Reply 'menu' for more options._"
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
                return add_menu_if_needed(f"Invalid input. Please try again.", show_menu=True)

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
                            response_text = "Balance for term " + term + ":\n\n" + "\n\n".join(balance_texts) + "\n\n_Reply 'menu' for more options._"
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
            return add_menu_if_needed(f"Invalid state. Please reply 'menu' to start over.", show_menu=True)

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
        
        # Provide instant feedback to user
        try:
            mark_message_as_read(message_id)
            react_to_message(from_number, message_id, emoji="⏳")
        except Exception as feedback_error:
            print(f"⚠️ Feedback functions failed (non-critical): {feedback_error}")

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
    
# ===== WHATSAPP FEEDBACK FUNCTIONS =====
def mark_message_as_read(message_id):
    """Mark incoming WhatsApp message as read (shows blue checkmarks)"""
    import os
    import requests
    
    token = os.getenv("WHATSAPP_CLOUD_API_TOKEN")
    phone_number_id = os.getenv("WHATSAPP_CLOUD_NUMBER")
    
    if not token or not phone_number_id:
        print("⚠️ Cannot mark as read: Missing credentials")
        return
    
    url = f"https://graph.facebook.com/v19.0/{phone_number_id}/messages"
    headers = {
        "Authorization": f"Bearer {token}",
        "Content-Type": "application/json"
    }
    payload = {
        "messaging_product": "whatsapp",
        "status": "read",
        "message_id": message_id
    }
    
    try:
        response = requests.post(url, headers=headers, json=payload, timeout=5)
        if response.status_code == 200:
            print(f"✓ Message {message_id} marked as read")
        else:
            print(f"⚠️ Failed to mark as read: {response.status_code} {response.text}")
    except Exception as e:
        print(f"⚠️ Exception marking message as read: {e}")

def react_to_message(to_number, message_id, emoji="⏳"):
    """React to a WhatsApp message with an emoji"""
    import os
    import requests
    
    token = os.getenv("WHATSAPP_CLOUD_API_TOKEN")
    phone_number_id = os.getenv("WHATSAPP_CLOUD_NUMBER")
    
    if not token or not phone_number_id:
        print("⚠️ Cannot react: Missing credentials")
        return
    
    url = f"https://graph.facebook.com/v19.0/{phone_number_id}/messages"
    headers = {
        "Authorization": f"Bearer {token}",
        "Content-Type": "application/json"
    }
    payload = {
        "messaging_product": "whatsapp",
        "recipient_type": "individual",
        "to": to_number,
        "type": "reaction",
        "reaction": {
            "message_id": message_id,
            "emoji": emoji
        }
    }
    
    try:
        response = requests.post(url, headers=headers, json=payload, timeout=5)
        if response.status_code == 200:
            print(f"✓ Reacted with {emoji} to message {message_id}")
        else:
            print(f"⚠️ Failed to react: {response.status_code} {response.text}")
    except Exception as e:
        print(f"⚠️ Exception reacting to message: {e}")

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
    
    # Check for Scheduled Event (EventBridge)
    if event.get("source") == "aws.events":
        action = event.get("action")
        print(f"⏰ Scheduled Event Triggered: {action}")
        
        try:
            if action == "check_payments":
                from utils.scheduler import check_all_payments
                check_all_payments()
                return {"statusCode": 200, "body": "Payment checks completed"}
                
            elif action == "send_reminders":
                from utils.scheduler import send_all_reminders
                send_all_reminders()
                return {"statusCode": 200, "body": "Reminders sent"}
                
            elif action == "sync_profiles":
                from services.profile_sync_service import sync_student_profiles
                import boto3
                
                # Get parameters from event
                # Get parameters from event
                start_page = event.get("start_page", 1)
                retry_count = event.get("retry_count", 0)
                time_limit = event.get("time_limit_seconds", 720)
                
                # Run sync with time limit (leave 2 mins buffer for Lambda timeout)
                # Assuming Lambda timeout is 15 mins (900s), we set internal limit to 12 mins (720s)
                result = sync_student_profiles(start_page=start_page, time_limit_seconds=time_limit)
                
                if result.get("status") == "partial":
                    next_page = result.get("next_page")
                    
                    # Determine if we are retrying the same page or moving forward
                    if next_page == start_page:
                        current_retry = retry_count + 1
                        if current_retry > 2: # Max 2 retries per page
                             print(f"🛑 Max retries reached for page {start_page}. Stopping recursion.")
                             return {"statusCode": 200, "body": f"Sync stopped: Max retries for page {start_page}"}
                        print(f"⚠️ Retrying page {next_page} (Attempt {current_retry}/2)")
                    else:
                        current_retry = 0 # Reset retry count if we advanced
                        print(f"🔄 Sync partial complete. Re-invoking for page {next_page}")
                    
                    # Re-invoke Lambda asynchronously
                    lambda_client = boto3.client('lambda')
                    new_payload = {
                        "source": "aws.events",
                        "action": "sync_profiles",
                        "start_page": next_page,
                        "retry_count": current_retry
                    }
                    lambda_client.invoke(
                        FunctionName=context.function_name,
                        InvocationType='Event', # Asynchronous
                        Payload=json.dumps(new_payload)
                    )
                    return {"statusCode": 200, "body": f"Sync continuing at page {next_page}"}
                
                return {"statusCode": 200, "body": f"Profiles synced: {result}"}

            elif action == "migrate":
                from utils.migration import run_migration_logic
                result = run_migration_logic()
                return {"statusCode": 200, "body": result}

            elif action == "check_health":
                # Imports available globally
                
                # 1. Check Internet
                try:
                    # Ping a reliable external site to verify NAT/Internet connectivity
                    response = requests.get("https://www.google.com", timeout=5)
                    if response.status_code == 200:
                        print("✅ Health Check Passed: Internet is accessible")
                    else:
                        raise Exception(f"Unexpected status code: {response.status_code}")
                except Exception as e:
                    print(f"❌ Health Check Failed (Internet): {str(e)}")
                    raise e

                # 2. Check S3 Write Access
                try:
                    s3_client = boto3.client('s3')
                    bucket_name = 'shining-smiles-gatepasses'
                    
                    # Create dummy file in /tmp
                    test_file_path = '/tmp/health_check.txt'
                    with open(test_file_path, 'w') as f:
                        f.write('ok')
                        
                    # Use upload_file with ExtraArgs, exactly like gatepass_service.py
                    s3_client.upload_file(
                        test_file_path, 
                        bucket_name, 
                        'health_check.txt',
                        ExtraArgs={'ContentType': 'text/plain'}
                    )
                    print("✅ Health Check Passed: S3 Write Access (upload_file)")
                    return {"statusCode": 200, "body": "Health Check Passed (Internet + S3 upload_file)"}
                except Exception as e:
                    print(f"❌ Health Check Failed (S3): {str(e)}")
                    # Return 500 with error message so we can see it in response body
                    return {"statusCode": 500, "body": f"Health Check Failed: S3 Error: {str(e)}"}
                
            elif action == "check_db_stats":
                from utils.database import init_db, StudentContact, FailedSync
                session = init_db()
                try:
                    total_students = session.query(StudentContact).count()
                    failed_syncs = session.query(FailedSync).count()
                    recent_failures = session.query(FailedSync).order_by(FailedSync.timestamp.desc()).limit(5).all()
                    
                    failure_details = [f"{f.student_id}: {f.error}" for f in recent_failures]
                    
                    stats = {
                        "total_students_in_db": total_students,
                        "total_failed_syncs": failed_syncs,
                        "recent_failure_reasons": failure_details
                    }
                    print(f"📊 DB Stats: {stats}")
                    return {"statusCode": 200, "body": json.dumps(stats)}
                except Exception as e:
                    return {"statusCode": 500, "body": f"Error checking stats: {str(e)}"}
                finally:
                    session.close()

            else:
                print(f"⚠️ Unknown scheduled action: {action}")
                return {"statusCode": 400, "body": f"Unknown action: {action}"}
        except Exception as e:
            print(f"❌ Error in scheduled task {action}: {str(e)}")
            traceback.print_exc()
            return {"statusCode": 500, "body": f"Error in {action}: {str(e)}"}

    # Get HTTP method from different possible locations
    http_method = event.get('httpMethod') 
    if not http_method:
        http_method = event.get('requestContext', {}).get('http', {}).get('method')
    
    print(f"🎯 DEBUG: HTTP Method: {http_method}")
    
    if http_method == 'GET':
        # Check for specific paths
        path = event.get('rawPath', '/')
        query = event.get('queryStringParameters', {}) or {}  # Fix: Ensure query is a dict
        
        # Admin Dashboard Routes
        if path == '/admin':
            print("🎯 DEBUG: Serve Admin Dashboard")
            try:
                with open(os.path.join(os.path.dirname(__file__), 'dashboard.html'), 'r') as f:
                    html_content = f.read()
                return {
                    'statusCode': 200,
                    'headers': {'Content-Type': 'text/html'},
                    'body': html_content
                }
            except Exception as e:
                return {'statusCode': 500, 'body': f"Error loading dashboard: {str(e)}"}

        if path == '/admin/stats':
            print("🎯 DEBUG: Admin Stats Request")
            # Auth Check
            admin_key = query.get('key')
            expected_key = os.getenv("ADMIN_SECRET", "admin123")
            if admin_key != expected_key:
                return {'statusCode': 401, 'body': 'Unauthorized'}

            from utils.database import init_db, StudentContact, FailedSync
            from sqlalchemy import func, distinct, text
            from datetime import datetime, timezone, timedelta

            session = init_db()
            try:
                # 1. Total Verified Students
                total_students = session.query(StudentContact).count()
                
                # 2. Unique Failures (Attention Needed)
                # We count distinct student_ids in FailedSync that are NOT in StudentContact (optional, or just distinct)
                # For safety/speed, let's just count distinct student_ids in FailedSync
                unique_failures_count = session.query(func.count(distinct(FailedSync.student_id))).scalar()
                
                # 3. Synced Today (Activity)
                today_start = datetime.now(timezone.utc).replace(hour=0, minute=0, second=0, microsecond=0)
                synced_today = session.query(StudentContact).filter(StudentContact.last_updated >= today_start).count()
                
                # 4. Recent Unique Failures
                recent_failures = session.query(FailedSync).order_by(FailedSync.timestamp.desc()).limit(200).all()
                
                seen_failed_ids = set()
                failure_details = []
                for f in recent_failures:
                    if f.student_id not in seen_failed_ids:
                        failure_details.append(f"{f.student_id}: {f.error}")
                        seen_failed_ids.add(f.student_id)
                    if len(failure_details) >= 50:
                        break
                
                # 5. Registration History (Last 30 Days)
                # Using pure SQL for date truncation as it's cleaner/faster
                history_query = text("""
                    SELECT date(timezone('Z', created_at)) as day, count(*) 
                    FROM student_contacts 
                    WHERE created_at >= NOW() - INTERVAL '30 days'
                    GROUP BY day 
                    ORDER BY day ASC;
                """)
                registration_history = []
                try:
                    result = session.execute(history_query).fetchall()
                    # Format as [{"date": "2024-01-01", "count": 5}, ...]
                    for row in result:
                         # pg8000 might return date object or string depending on driver version
                         day_val = row[0]
                         if isinstance(day_val, datetime): 
                             day_str = day_val.strftime("%Y-%m-%d")
                         else:
                             day_str = str(day_val)
                         
                         registration_history.append({
                             "date": day_str,
                             "count": row[1]
                         })
                except Exception as hist_e:
                    print(f"History query warning: {hist_e}")
                    # Fallback if created_at is missing (should not happen after migration)
                    pass

                stats = {
                    "total_students_in_db": total_students,
                    "total_failed_syncs": unique_failures_count, 
                    "students_synced_today": synced_today,
                    "date": today_start.strftime("%Y-%m-%d"),
                    "recent_failure_reasons": failure_details,
                    "registration_history": registration_history
                }
                return {
                    'statusCode': 200, 
                    'headers': {
                        'Content-Type': 'application/json',
                        'Access-Control-Allow-Origin': '*'
                    },
                    'body': json.dumps(stats, default=str)
                }
            except Exception as e:
                return {'statusCode': 500, 'body': f"Error: {str(e)}"}
            finally:
                session.close()

        if path == '/verify-gatepass':
            print("🎯 DEBUG: Handling Gate Pass Verification")
            from services.gatepass_service import verify_gatepass
            pass_id = query.get('pass_id')
            whatsapp_number = query.get('whatsapp_number')
            
            # verify_gatepass returns (response, status_code)
            response, status_code = verify_gatepass(pass_id, whatsapp_number)
            
            # If response is HTML (string), return text/html
            if isinstance(response, str):
                return {
                    'statusCode': status_code,
                    'headers': {'Content-Type': 'text/html'},
                    'body': response
                }
            # If response is JSON (dict), return application/json
            else:
                return {
                    'statusCode': status_code,
                    'headers': {'Content-Type': 'application/json'},
                    'body': json.dumps(response)
                }

        # Webhook verification - only for GET requests
        print("🎯 DEBUG: Handling GET request (webhook verification)")
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
        path = event.get('rawPath', '/')
        
        # Admin Sync Trigger
        if path == '/admin/trigger-sync':
            print("🎯 DEBUG: Admin Sync Trigger")
            try:
                body = json.loads(event.get('body', '{}'))
                admin_key = body.get('key')
                expected_key = os.getenv("ADMIN_SECRET", "admin123")
                
                if admin_key != expected_key:
                    return {'statusCode': 401, 'body': json.dumps({"error": "Unauthorized"})}
                
                # Trigger Sync asynchronously via Lambda invoke (same as scheduler)
                import boto3
                lambda_client = boto3.client('lambda')
                payload = {
                    "source": "aws.events",
                    "action": "sync_profiles"
                }
                lambda_client.invoke(
                    FunctionName=context.function_name,
                    InvocationType='Event', # Async
                    Payload=json.dumps(payload)
                )
                
                return {
                    'statusCode': 200, 
                    'headers': {'Content-Type': 'application/json'},
                    'body': json.dumps({"status": "started", "message": "Sync job triggered in background"})
                }
            except Exception as e:
                return {'statusCode': 500, 'body': json.dumps({"error": str(e)})}

        # Admin Migrate Schema
        if path == '/admin/migrate':
            print("🎯 DEBUG: Admin Schema Migration")
            try:
                body = json.loads(event.get('body', '{}'))
                admin_key = body.get('key')
                expected_key = os.getenv("ADMIN_SECRET", "admin123")
                
                if admin_key != expected_key:
                    return {'statusCode': 401, 'body': json.dumps({"error": "Unauthorized"})}
                
                from utils.database import init_db
                from sqlalchemy import text
                session = init_db()
                try:
                    # Check if column exists
                    check_query = text("SELECT column_name FROM information_schema.columns WHERE table_name='student_contacts' AND column_name='created_at';")
                    result = session.execute(check_query).fetchone()
                    
                    if not result:
                        print("Run migration: Adding created_at column")
                        session.execute(text("ALTER TABLE student_contacts ADD COLUMN created_at TIMESTAMPTZ DEFAULT NOW();"))
                        session.commit()
                        msg = "Migration successful: Added created_at column."
                    else:
                        msg = "Migration skipped: Column created_at already exists."
                        
                    return {
                        'statusCode': 200, 
                        'headers': {'Content-Type': 'application/json'},
                        'body': json.dumps({"status": "success", "message": msg})
                    }
                except Exception as db_err:
                    session.rollback()
                    return {'statusCode': 500, 'body': json.dumps({"error": f"DB Error: {str(db_err)}"}) }
                finally:
                    session.close()

            except Exception as e:
                return {'statusCode': 500, 'body': json.dumps({"error": str(e)})}

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
            traceback.print_exc()
            return {'statusCode': 500, 'body': 'Error'}

    else:
        print(f"🎯 DEBUG: Unsupported method: {http_method}")
        return {'statusCode': 405, 'body': 'Method not allowed'}