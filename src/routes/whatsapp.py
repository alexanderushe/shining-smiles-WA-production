from flask import Blueprint, request, Response, jsonify
from twilio.twiml.messaging_response import MessagingResponse
from datetime import datetime, timezone, date
import requests
import json
from utils.database import init_db, StudentContact, UserState, GatePass
from utils.whatsapp import send_whatsapp_message
from utils.logger import setup_logger
from api.sms_client import SMSClient, RateLimitException
from utils.ai_client import AIClient
from config import get_config
import uuid
import re
import traceback
import os

whatsapp_bp = Blueprint('whatsapp', __name__)
logger = setup_logger(__name__)
config = get_config()

@whatsapp_bp.route("/webhook", methods=["GET", "POST"])
def whatsapp_cloud_webhook():
    """WhatsApp Cloud API webhook endpoint"""
    if request.method == "GET":
        # Webhook verification
        verify_token = request.args.get("hub.verify_token")
        challenge = request.args.get("hub.challenge")
        if verify_token == os.getenv("WHATSAPP_VERIFY_TOKEN"):
            logger.info("Webhook verified successfully")
            return challenge
        else:
            logger.error("Webhook verification failed")
            return "Verification failed", 403

    elif request.method == "POST":
        # Handle incoming messages
        try:
            data = request.get_json()
            logger.info(f"Received webhook payload: {data}")

            if not data or data.get("object") != "whatsapp_business_account":
                return "OK", 200

            for entry in data.get("entry", []):
                for change in entry.get("changes", []):
                    value = change.get("value", {})

                    if "messages" in value:
                        for message in value["messages"]:
                            process_cloud_api_message(message, value.get("metadata", {}))

            return "OK", 200

        except Exception as e:
            logger.error(f"Error processing webhook: {str(e)}")
            return "Error", 500

def process_cloud_api_message(message, metadata):
    """Process incoming WhatsApp Cloud API message"""
    try:
        request_id = str(uuid.uuid4())
        session = init_db()
        sms_client = SMSClient(request_id=request_id)
        ai_client = AIClient(request_id=request_id)

        # Extract message details
        from_number = f"+{message.get('from')}"
        message_id = message.get("id")
        timestamp = message.get("timestamp")
        message_type = message.get("type")

        if message_type == "text":
            message_body = message.get("text", {}).get("body", "").strip().lower()
        else:
            logger.info(f"Unsupported message type: {message_type}")
            return

        logger.info(f"Processing message from {from_number}: {message_body}")

        # Process the message using the same logic as Twilio webhook
        response_text = handle_whatsapp_message(
            from_number, message_body, session, sms_client, ai_client, request_id
        )

        # Send response using Cloud API
        if response_text:
            send_whatsapp_message(
                to=from_number,
                message=response_text,
                use_cloud_api=True
            )

    except Exception as e:
        logger.error(f"Error processing Cloud API message: {str(e)}")
        traceback.print_exc()
    finally:
        if 'session' in locals():
            session.close()

def handle_whatsapp_message(whatsapp_number, message_body, session, sms_client, ai_client, request_id):
    """
    Handle WhatsApp message logic - extracted for reuse between Twilio and Cloud API
    Returns the response text to send back to the user
    """
    current_time = datetime.now(timezone.utc)
    extra_log = {"phone_number": whatsapp_number, "request_id": request_id}

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

    contacts = session.query(StudentContact).filter_by(phone_number=whatsapp_number).all()
    user_state = session.query(UserState).filter_by(phone_number=whatsapp_number).first()

    if not user_state:
        user_state = UserState(
            phone_number=whatsapp_number,
            query_count=0,
            last_updated=current_time
        )
        session.add(user_state)
        session.commit()

    # Handle unregistered users
    if not contacts:
        logger.debug(f"No contacts found for {whatsapp_number}, treating as unregistered", extra=extra_log)

        if message_body in ["menu", "start"]:
            return f"{unregistered_prompt}\n\n{unregistered_menu_text}"

        elif message_body in ["1", "about", "about our school"]:
            logger.info(f"Processing 'about' query for {whatsapp_number}", extra=extra_log)
            user_state.query_count += 1
            user_state.last_updated = current_time
            session.commit()
            response_text = ai_client.get_ai_response("Tell me about Shining Smiles School")
            return response_text

        elif message_body in ["2", "admissions", "admissions info"]:
            user_state.query_count += 1
            user_state.last_updated = current_time
            session.commit()
            response_text = ai_client.get_ai_response("What are the admissions requirements for Shining Smiles School?")
            return response_text

        elif message_body in ["3", "events", "upcoming events"]:
            user_state.query_count += 1
            user_state.last_updated = current_time
            session.commit()
            response_text = ai_client.get_ai_response("What upcoming events does Shining Smiles School have?")
            return response_text

        elif message_body in ["4", "contact", "contact us"]:
            user_state.query_count += 1
            user_state.last_updated = current_time
            session.commit()
            response_text = ai_client.get_ai_response("How can I contact Shining Smiles School?")
            return response_text

        elif message_body in ["5", "help"]:
            return (
                f"❓ *Help*: Ask me anything about Shining Smiles School or reply *menu* for options. "
                f"For account-related queries, contact _admin@shiningsmilescollege.ac.zw_."
            )

        else:
            user_state.query_count += 1
            user_state.last_updated = current_time
            session.commit()
            response_text = ai_client.get_ai_response(message_body)
            return response_text

    # Handle registered users (rest of the original logic would go here)
    # For brevity, I'll just return a basic response for now
    fullname = f"{contacts[0].firstname or 'Parent'} {contacts[0].lastname or ''}".strip()

    if message_body in ["menu", "start"]:
        return f"👋 *Hi {fullname}!*\nWelcome back to Shining Smiles School.\n\n{menu_text}"

@whatsapp_bp.route("/whatsapp-incoming", methods=["POST"])
def whatsapp_menu():
    request_id = str(uuid.uuid4())
    session = init_db()
    sms_client = SMSClient(request_id=request_id)
    ai_client = AIClient(request_id=request_id)
    response = MessagingResponse()

    message_body = request.form.get("Body", "").strip().lower()
    raw_from = request.form.get("From", "")
    logger.debug(f"Raw From field: {raw_from}", extra={"request_id": request_id})

    whatsapp_number = raw_from.replace("whatsapp:", "").strip()
    if not whatsapp_number.startswith('+'):
        whatsapp_number = f'+{whatsapp_number}'
        logger.debug(f"Added '+' to whatsapp_number: {whatsapp_number}", extra={"request_id": request_id})

    if not sms_client.check_whatsapp_number(whatsapp_number):
        logger.warning(f"Number {whatsapp_number} not registered on WhatsApp", extra={"request_id": request_id})
        response.message(
            f"⚠️ *Your number {whatsapp_number} is not registered on WhatsApp.* "
            f"Please use a WhatsApp-enabled number or contact _admin@shiningsmilescollege.ac.zw_.\n{unregistered_prompt}"
        )
        session.close()
        return Response(str(response), mimetype="application/xml")

    user_state = session.query(UserState).filter_by(phone_number=whatsapp_number).first()
    if not user_state:
        user_state = UserState(phone_number=whatsapp_number, state="unregistered_menu", query_count=0, query_date=date.today())
        session.add(user_state)
        session.commit()
        # Send introduction for new unregistered users
        response.message(unregistered_prompt)
        logger.info(f"Sending intro to {whatsapp_number}: {unregistered_prompt}", extra={"request_id": request_id})
        session.close()
        return Response(str(response), mimetype="application/xml")

    current_time = datetime.now(timezone.utc)
    current_date = current_time.date()
    extra_log = {"request_id": request_id, "whatsapp_number": whatsapp_number}

    # Rate limiting for unregistered users
    if user_state.state == "unregistered_menu":
        if user_state.query_date != current_date:
            user_state.query_count = 0
            user_state.query_date = current_date
            session.commit()
        if user_state.query_count >= 5:
            response_message = response.message(
                f"⚠️ *Daily query limit reached.* Please try again tomorrow or contact _admin@shiningsmilescollege.ac.zw_.\n{unregistered_prompt}"
            )
            logger.info(f"Sending rate limit response to {whatsapp_number}: {response_message.body}", extra=extra_log)
            session.close()
            return Response(str(response), mimetype="application/xml")

    # Query all contacts associated with the phone number
    contacts = session.query(StudentContact).filter_by(preferred_phone_number=whatsapp_number).all()
    if not contacts:
        extra_log["student_id"] = None
        if message_body == "menu":
            response_message = response.message(unregistered_menu_text)
            logger.info(f"Sending unregistered menu to {whatsapp_number}: {response_message.body}", extra=extra_log)
            session.close()
            return Response(str(response), mimetype="application/xml")

        elif message_body in ["1", "about", "about our school"]:
            logger.info(f"Processing 'about' query for {whatsapp_number}", extra=extra_log)
            user_state.query_count += 1
            user_state.last_updated = current_time
            session.commit()
            ai_response = ai_client.generate_response("Tell me about Shining Smiles School.")
            response_message = response.message(f"✨ {ai_response}")
            logger.info(f"Sending AI about response to {whatsapp_number}: {response_message.body}", extra=extra_log)
            session.close()
            return Response(str(response), mimetype="application/xml")

        elif message_body in ["2", "admissions", "admissions info"]:
            user_state.query_count += 1
            user_state.last_updated = current_time
            session.commit()
            ai_response = ai_client.generate_response("Tell me about admissions at Shining Smiles School.")
            response_message = response.message(f"📚 {ai_response}")
            logger.info(f"Sending AI admissions response to {whatsapp_number}: {response_message.body}", extra=extra_log)
            session.close()
            return Response(str(response), mimetype="application/xml")

        elif message_body in ["3", "events", "upcoming events"]:
            user_state.query_count += 1
            user_state.last_updated = current_time
            session.commit()
            ai_response = ai_client.generate_response("What are the upcoming events at Shining Smiles School?")
            response_message = response.message(f"🎉 {ai_response}")
            logger.info(f"Sending AI events response to {whatsapp_number}: {response_message.body}", extra=extra_log)
            session.close()
            return Response(str(response), mimetype="application/xml")

        elif message_body in ["4", "contact", "contact us"]:
            user_state.query_count += 1
            user_state.last_updated = current_time
            session.commit()
            ai_response = ai_client.generate_response("How can I contact Shining Smiles School?")
            response_message = response.message(f"📞 {ai_response}")
            logger.info(f"Sending AI contact response to {whatsapp_number}: {response_message.body}", extra=extra_log)
            session.close()
            return Response(str(response), mimetype="application/xml")

        elif message_body in ["5", "help"]:
            response_message = response.message(
                f"❓ *Help*: Ask me anything about Shining Smiles School or reply *menu* for options. "
                f"For account-related queries, contact _admin@shiningsmilescollege.ac.zw_.\n{unregistered_menu_text}"
            )
            logger.info(f"Sending help response to {whatsapp_number}: {response_message.body}", extra=extra_log)
            session.close()
            return Response(str(response), mimetype="application/xml")

        else:
            user_state.query_count += 1
            user_state.last_updated = current_time
            session.commit()
            ai_response = ai_client.generate_response(message_body)
            response_message = response.message(f"😊 {ai_response}")
            logger.info(f"Sending AI response to {whatsapp_number}: {response_message.body}", extra=extra_log)
            session.close()
            return Response(str(response), mimetype="application/xml")

    # Determine the parent's name (use the first contact's name, assuming consistency across contacts)
    fullname = f"{contacts[0].firstname or 'Parent'} {contacts[0].lastname or ''}".strip()
    student_ids = [contact.student_id for contact in contacts if contact.student_id and re.match(r'^SSC\d+$', contact.student_id)]
    extra_log["student_ids"] = student_ids

    if not student_ids:
        response_message = response.message(
            f"👋 *Hi {fullname},*\nNo valid student IDs registered. Please contact _admin@shiningsmilescollege.ac.zw_.\n{menu_text}"
        )
        logger.info(f"Sending response to {whatsapp_number}: {response_message.body}", extra=extra_log)
        user_state.state = "main_menu"
        user_state.last_updated = current_time
        session.commit()
        session.close()
        return Response(str(response), mimetype="application/xml")

    try:
        current_date = current_time.date()
        default_term = next(
            (term for term, start in config.TERM_START_DATES.items() if start.date() <= current_date <= config.TERM_END_DATES[term].date()),
            None
        )
        if not default_term or not re.match(r'^\d{4}-\d$', default_term):
            default_term = "2025-2"
            logger.warning(f"Invalid or unconfigured default term, using fallback: {default_term}", extra=extra_log)

        if user_state.state == "main_menu":
            if message_body == "menu":
                response_message = response.message(
                    f"👋 *Hi {fullname},*\n*Welcome to Shining Smiles School!* 😊\n{menu_text}"
                )
                logger.info(f"Sending response to {whatsapp_number}: {response_message.body}", extra=extra_log)
                session.close()
                return Response(str(response), mimetype="application/xml")

            elif message_body in ["1", "balance", "view balance"]:
                # Auto-detect current term
                term = config.get_current_term()
                
                if not term:
                    # School is on break
                    next_term = config.get_next_term()
                    term = config.get_most_recent_completed_term()
                    
                    if next_term and config.TERM_START_DATES.get(next_term):
                        next_term_date = config.TERM_START_DATES[next_term].strftime("%B %d, %Y")
                        break_message = (
                            f"🏫 *School is currently on break!*\n"
                            f"Term {next_term} begins on *{next_term_date}*.\n\n"
                        )
                    else:
                        break_message = "🏫 *School is currently on break!*\n\n"
                    
                    if not term:
                        response_message = response.message( f"{break_message}"
                            f"No previous term data available. Please contact _admin@shiningsmilescollege.ac.zw_.\n{menu_text}"
                        )
                        logger.info(f"Sending response to {whatsapp_number}: {response_message.body}", extra=extra_log)
                        session.close()
                        return Response(str(response), mimetype="application/xml")
                    
                    prefix_message = f"{break_message}*Your last term balance (Term {term}):*\n"
                else:
                    prefix_message = f"📊 *Current Balance (Term {term}):*\n"
                
                # Fetch balance for all students
                try:
                    balance_texts = []
                    for student_id in student_ids:
                        start_time = datetime.now(timezone.utc)
                        billed_fees = sms_client.get_student_billed_fees(student_id, term)
                        payments = sms_client.get_student_payments(student_id, term)
                        elapsed_time = (datetime.now(timezone.utc) - start_time).total_seconds()
                        if elapsed_time > 25:
                            logger.warning(f"API calls for balance took {elapsed_time}s, risking timeout for {student_id}", extra=extra_log)

                        logger.debug(f"Balance for {student_id}, Term {term}: "
                                     f"Billed fees: {billed_fees}, "
                                     f"Payments: {payments}", extra=extra_log)

                        total_fees = sum(float(bill["amount"]) for bill in billed_fees.get("data", {}).get("bills", [])) if billed_fees.get("data", {}).get("bills") else 0.0
                        total_paid = sum(float(p["amount"]) for p in payments.get("data", {}).get("payments", [])) if payments.get("data", {}).get("payments") else 0.0
                        balance = total_fees - total_paid

                        student_name = next((f"{c.firstname or ''} {c.lastname or ''}".strip() for c in contacts if c.student_id == student_id), "Unknown")
                        if not billed_fees.get("data", {}).get("bills"):
                            balance_texts.append(
                                f"*{student_id} ({student_name})*: No fees recorded"
                            )
                        elif balance == 0.0 and total_fees > 0.0:
                            balance_texts.append(
                                f"*{student_id} ({student_name})*: Fully paid ✅\n"
                                f"  Total Fees: ${total_fees:.2f}\n"
                                f"  Total Paid: ${total_paid:.2f}"
                            )
                        else:
                            balance_texts.append(
                                f"*{student_id} ({student_name})*:\n"
                                f"  Total Fees: ${total_fees:.2f}\n"
                                f"  Total Paid: ${total_paid:.2f}\n"
                                f"  Balance Owed: ${balance:.2f}"
                            )

                    if not balance_texts:
                        response_text = (
                            f"📊 *Hi {fullname},*\n"
                            f"{prefix_message}"
                            f"No fees recorded for any students in term *{term}*. Please contact _admin@shiningsmilescollege.ac.zw_.\n\n"
                            f"💡 View other terms? Reply with term code (e.g., *2026-1*, *2025-3*)\n{menu_text}"
                        )
                    else:
                        response_text = (
                            f"📊 *Hi {fullname},*\n"
                            f"{prefix_message}\n"
                            f"\n\n".join(balance_texts) + 
                            f"\n\n💡 View other terms? Reply with term code (e.g., *2026-1*, *2025-3*)\n{menu_text}"
                        )
                    
                    response_message = response.message(response_text)
                    logger.info(f"Sending response to {whatsapp_number}: {response_message.body}", extra=extra_log)
                    user_state.state = "main_menu"
                    user_state.last_updated = current_time
                    session.commit()
                    session.close()
                    return Response(str(response), mimetype="application/xml")

                except RateLimitException:
                    logger.warning(f"Rate limit hit while fetching balance for {student_ids}, term {term}", extra=extra_log)
                    response_message = response.message(
                        f"⚠️ *Hi {fullname},*\n*Too many requests.* Please try again shortly.\n{menu_text}"
                    )
                    user_state.state = "main_menu"
                    user_state.last_updated = current_time
                    session.commit()
                    logger.info(f"Sending response to {whatsapp_number}: {response_message.body}", extra=extra_log)
                    session.close()
                    return Response(str(response), mimetype="application/xml")
                except Exception as e:
                    logger.error(f"Unexpected error in balance retrieval for {student_ids}, term {term}: {str(e)}\n{traceback.format_exc()}", extra=extra_log)
                    response_message = response.message(
                        f"⚠️ *Hi {fullname},*\n"
                        f"*An unexpected error occurred.* Please contact _admin@shiningsmilescollege.ac.zw_.\n{menu_text}"
                    )
                    user_state.state = "main_menu"
                    user_state.last_updated = current_time
                    session.commit()
                    logger.info(f"Sending response to {whatsapp_number}: {response_message.body}", extra=extra_log)
                    session.close()
                    return Response(str(response), mimetype="application/xml")

            elif message_body in ["2", "statement", "request statement"]:
                try:
                    if not re.match(r'^\d{4}-\d$', default_term) or default_term not in config.TERM_START_DATES:
                        logger.error(f"Invalid or unconfigured default term: {default_term}", extra=extra_log)
                        response_message = response.message(
                            f"📊 *Hi {fullname},*\nPlease reply with a valid term (e.g., *2025-1*, *2025-2*, *2025-3*) for all students.\n{menu_text}"
                        )
                        user_state.state = "awaiting_term_statement"
                        user_state.last_updated = current_time
                        session.commit()
                        logger.info(f"Sending response to {whatsapp_number}: {response_message.body}", extra=extra_log)
                        session.close()
                        return Response(str(response), mimetype="application/xml")

                    current_date = current_time.date()
                    term_start = config.TERM_START_DATES.get(default_term)
                    if term_start and term_start.date() > current_date:
                        response_message = response.message(
                            f"📅 *Hi {fullname},*\nTerm *{default_term}* has not started yet. Please select a current or past term (e.g., *2025-1*, *2025-2*) for all students.\n{menu_text}"
                        )
                        logger.info(f"Sending response to {whatsapp_number}: {response_message.body}", extra=extra_log)
                        user_state.state = "main_menu"
                        user_state.last_updated = current_time
                        session.commit()
                        session.close()
                        return Response(str(response), mimetype="application/xml")

                    statement_texts = []
                    max_message_length = 1400  # Buffer below Twilio's 1600-character limit
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
                                    [f"- *${b['amount']:.2f}* on _{b.get('date', 'N/A')}_ ({b.get('fee_type', 'N/A')})" for b in billed_fees.get("data", {}).get("bills")]
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

                            # Truncate individual statement if too long
                            if len(statement_text) > max_message_length:
                                statement_text = statement_text[:max_message_length - 50] + "\n*Note*: Statement truncated due to length. Contact admin for full details."
                        statement_texts.append(statement_text)

                    if not statement_texts:
                        statement_text = (
                            f"📊 *Hi {fullname},*\n"
                            f"No account statements found for any students in term *{default_term}*. Please contact _admin@shiningsmilescollege.ac.zw_.\n{menu_text}"
                        )
                        whatsapp_response = send_whatsapp_message(whatsapp_number, statement_text)
                        if whatsapp_response.get("status") != "sent":
                            logger.error(f"Failed to send statement: {whatsapp_response.get('error', 'Unknown error')}", extra=extra_log)
                            response_message = response.message(
                                f"⚠️ *Hi {fullname},*\n*Failed to send statements.* Please try again or contact _admin@shiningsmilescollege.ac.zw_.\n{menu_text}"
                            )
                        else:
                            response_message = response.message(
                                f"📨 *Hi {fullname},*\n*Statements have been sent for all students.*\n{menu_text}"
                            )
                    else:
                        # Check combined length
                        combined_text = f"📊 *Hi {fullname},*\n" + "\n\n".join(statement_texts) + f"\n{menu_text}"
                        if len(combined_text) > max_message_length:
                            # Send individual messages
                            for statement in statement_texts:
                                full_message = f"📊 *Hi {fullname},*\n{statement}\n{menu_text}"
                                if len(full_message) > max_message_length:
                                    full_message = full_message[:max_message_length - 50] + "\n*Note*: Statement truncated. Contact admin for full details.\n{menu_text}"
                                whatsapp_response = send_whatsapp_message(whatsapp_number, full_message)
                                if whatsapp_response.get("status") != "sent":
                                    logger.error(f"Failed to send statement for {whatsapp_number}: {whatsapp_response.get('error', 'Unknown error')}", extra=extra_log)
                                    response_message = response.message(
                                        f"⚠️ *Hi {fullname},*\n*Failed to send statements.* Please try again or contact _admin@shiningsmilescollege.ac.zw_.\n{menu_text}"
                                    )
                                    user_state.state = "main_menu"
                                    user_state.last_updated = current_time
                                    session.commit()
                                    session.close()
                                    return Response(str(response), mimetype="application/xml")
                            response_message = response.message(
                                f"📨 *Hi {fullname},*\n*Statements have been sent for all students.*\n{menu_text}"
                            )
                        else:
                            # Send combined message
                            statement_text = combined_text
                            whatsapp_response = send_whatsapp_message(whatsapp_number, statement_text)
                            if whatsapp_response.get("status") != "sent":
                                logger.error(f"Failed to send statement: {whatsapp_response.get('error', 'Unknown error')}", extra=extra_log)
                                response_message = response.message(
                                    f"⚠️ *Hi {fullname},*\n*Failed to send statements.* Please try again or contact _admin@shiningsmilescollege.ac.zw_.\n{menu_text}"
                                )
                            else:
                                response_message = response.message(
                                    f"📨 *Hi {fullname},*\n*Statements have been sent for all students.*\n{menu_text}"
                                )

                    logger.info(f"Sending response to {whatsapp_number}: {response_message.body}", extra=extra_log)
                    user_state.state = "main_menu"
                    user_state.last_updated = current_time
                    session.commit()
                    session.close()
                    return Response(str(response), mimetype="application/xml")

                except RateLimitException:
                    logger.warning(f"Rate limit hit while fetching statements for {student_ids}, term {default_term}", extra=extra_log)
                    response_message = response.message(
                        f"⚠️ *Hi {fullname},*\n*Too many requests.* Please try again shortly.\n{menu_text}"
                    )
                    user_state.state = "main_menu"
                    user_state.last_updated = current_time
                    session.commit()
                    logger.info(f"Sending response to {whatsapp_number}: {response_message.body}", extra=extra_log)
                    session.close()
                    return Response(str(response), mimetype="application/xml")
                except ValueError as e:
                    logger.error(f"Account statement error for {student_ids}, term {default_term}: {str(e)}\n{traceback.format_exc()}", extra=extra_log)
                    response_message = response.message(
                        f"⚠️ *Hi {fullname},*\n"
                        f"No account statements found for students in term *{default_term}*. "
                        f"Please contact _admin@shiningsmilescollege.ac.zw_.\n{menu_text}"
                    )
                    user_state.state = "main_menu"
                    user_state.last_updated = current_time
                    session.commit()
                    logger.info(f"Sending response to {whatsapp_number}: {response_message.body}", extra=extra_log)
                    session.close()
                    return Response(str(response), mimetype="application/xml")
                except requests.RequestException as e:
                    logger.error(f"Failed to fetch statements for {student_ids}, term {default_term}: {str(e)}\n{traceback.format_exc()}", extra=extra_log)
                    response_message = response.message(
                        f"⚠️ *Hi {fullname},*\n"
                        f"Error fetching statements for term *{default_term}*. Please contact _admin@shiningsmilescollege.ac.zw_.\n{menu_text}"
                    )
                    user_state.state = "main_menu"
                    user_state.last_updated = current_time
                    session.commit()
                    logger.info(f"Sending response to {whatsapp_number}: {response_message.body}", extra=extra_log)
                    session.close()
                    return Response(str(response), mimetype="application/xml")
                except Exception as e:
                    logger.error(f"Unexpected error in statement generation for {student_ids}, term {default_term}: {str(e)}\n{traceback.format_exc()}", extra=extra_log)
                    response_message = response.message(
                        f"⚠️ *Hi {fullname},*\n"
                        f"*An unexpected error occurred.* Please contact _admin@shiningsmilescollege.ac.zw_.\n{menu_text}"
                    )
                    user_state.state = "main_menu"
                    user_state.last_updated = current_time
                    session.commit()
                    logger.info(f"Sending response to {whatsapp_number}: {response_message.body}", extra=extra_log)
                    session.close()
                    return Response(str(response), mimetype="application/xml")

            elif message_body in ["3", "gate pass", "get gate pass"]:
                try:
                    logger.debug(f"Attempting gate passes for student_ids: {student_ids}, term: {default_term}", extra=extra_log)
                    current_date = current_time.date()
                    default_term = next(
                        (term for term, start in config.TERM_START_DATES.items() if start.date() <= current_date <= config.TERM_END_DATES[term].date()),
                        None
                    )
                    if not default_term:
                        next_term = min(
                            (term for term, start in config.TERM_START_DATES.items() if start.date() > current_date),
                            key=lambda t: config.TERM_START_DATES[t].date(),
                            default=None
                        )
                        next_term_date = config.TERM_START_DATES[next_term].date().strftime("%d %B %Y") if next_term else "a future date"
                        response_message = response.message(
                            f"📅 *Hi {fullname},*\n"
                            f"Gate passes are only issued during active school terms. Schools reopen on {next_term_date} for Term {next_term or '3'}. Please try again then.\n{menu_text}"
                        )
                        logger.info(f"Sending holiday response to {whatsapp_number}: {response_message.body}", extra=extra_log)
                        user_state.state = "main_menu"
                        user_state.last_updated = current_time
                        session.commit()
                        session.close()
                        return Response(str(response), mimetype="application/xml")

                    if not re.match(r'^\d{4}-\d$', default_term) or default_term not in config.TERM_START_DATES:
                        logger.error(f"Invalid or unconfigured default term: {default_term}", extra=extra_log)
                        response_message = response.message(
                            f"📅 *Hi {fullname},*\n"
                            f"Please reply with a valid term (e.g., *2025-1*, *2025-2*, *2025-3*) for all students.\n{menu_text}"
                        )
                        user_state.state = "awaiting_term_gatepass"
                        user_state.last_updated = current_time
                        session.commit()
                        logger.info(f"Sending response to {whatsapp_number}: {response_message.body}", extra=extra_log)
                        session.close()
                        return Response(str(response), mimetype="application/xml")

                    term_start = config.TERM_START_DATES.get(default_term)
                    if term_start and term_start.date() > current_date:
                        response_message = response.message(
                            f"📅 *Hi {fullname},*\n"
                            f"Term *{default_term}* has not started yet. Please select a current or past term (e.g., *2025-1*, *2025-2*) for all students.\n{menu_text}"
                        )
                        user_state.state = "awaiting_term_gatepass"
                        user_state.last_updated = current_time
                        session.commit()
                        logger.info(f"Sending response to {whatsapp_number}: {response_message.body}", extra=extra_log)
                        session.close()
                        return Response(str(response), mimetype="application/xml")

                    gatepass_texts = []
                    for student_id in student_ids:
                        billed_fees = sms_client.get_student_billed_fees(student_id, default_term)
                        total_fees = sum(float(bill["amount"]) for bill in billed_fees.get("data", {}).get("bills", [])) if billed_fees.get("data", {}).get("bills") else 0.0
                        payments = sms_client.get_student_payments(student_id, default_term)
                        total_paid = sum(float(p["amount"]) for p in payments.get("data", {}).get("payments", [])) if payments.get("data", {}).get("payments") else 0.0
                        payment_percentage = (total_paid / total_fees) * 100 if total_fees > 0 else 0

                        logger.debug(f"[GatePass] {student_id} - Paid: {total_paid}, Total Fees: {total_fees}, Term: {default_term}, Percentage: {payment_percentage}%", extra=extra_log)

                        student_name = next((f"{c.firstname or ''} {c.lastname or ''}".strip() for c in contacts if c.student_id == student_id), "Unknown")
                        
                        # PRE-FLIGHT CHECK: Don't issue gate pass if fees not posted
                        if total_fees <= 0:
                            gatepass_texts.append(
                                f"*Gate Pass for {student_id} ({student_name})*:\n"
                                f"⏳ *Fees Not Yet Posted*\n"
                                f"Term *{default_term}* fees are being processed.\n"
                                f"Please check back in 1-2 days or contact _admin@shiningsmilescollege.ac.zw_."
                            )
                            continue  # Skip gate pass generation for this student

                        gatepass_url = f"{config.APP_BASE_URL}/generate-gatepass"
                        payload = {
                            "student_id": student_id,
                            "term": default_term,
                            "payment_amount": total_paid,
                            "total_fees": total_fees,
                            "request_id": request_id
                        }

                        gatepass_res = requests.post(gatepass_url, json=payload, timeout=10)
                        logger.debug(f"[GatePass Response] {student_id} - {gatepass_res.status_code} - {gatepass_res.text}", extra=extra_log)

                        data = gatepass_res.json()
                        status_msg = data.get("status", "").lower()

                        student_name = next((f"{c.firstname or ''} {c.lastname or ''}".strip() for c in contacts if c.student_id == student_id), "Unknown")
                        if gatepass_res.status_code == 200:
                            if "already valid" in status_msg or "resent" in status_msg:
                                gatepass_texts.append(
                                    f"*Gate Pass for {student_id} ({student_name})*:\n"
                                    f"You *already have a valid gate pass*.\n"
                                    f"*Pass ID*: {data.get('pass_id')}\n"
                                    f"*Expires*: _{data.get('expiry_date')}_\n"
                                    f"*PDF re-sent to*: {data.get('whatsapp_number')}"
                                )
                            else:
                                gatepass_texts.append(
                                    f"*Gate Pass for {student_id} ({student_name})*:\n"
                                    f"*Gate Pass Issued!* 🎉\n"
                                    f"*Pass ID*: {data.get('pass_id')}\n"
                                    f"*Expires*: _{data.get('expiry_date')}_\n"
                                    f"*Sent to*: {data.get('whatsapp_number')}"
                                )
                        else:
                            error_msg = data.get("error", "Could not issue gate pass.")
                            gatepass_texts.append(
                                f"*Gate Pass for {student_id} ({student_name})*:\n"
                                f"*{error_msg}*"
                            )

                    if not gatepass_texts:
                        response_message = response.message(
                            f"⚠️ *Hi {fullname},*\n*No gate passes issued.* Please contact _admin@shiningsmilescollege.ac.zw_.\n{menu_text}"
                        )
                    else:
                        # Check if any actual gate passes were issued (vs just "fees not posted" messages)
                        has_actual_pass = any("Gate Pass Issued" in text or "already have a valid" in text for text in gatepass_texts)
                        
                        if has_actual_pass:
                            header = "✅ *Gate pass issued!*\n\n"
                        else:
                            header = "📋 *Gate Pass Status:*\n\n"
                        
                        response_text = (
                            f"*Hi {fullname},*\n"
                            f"{header}"
                            f"\n\n".join(gatepass_texts) +
                            f"\n\nIf not received, ensure *{whatsapp_number}* is registered with WhatsApp or contact _admin@shiningsmilescollege.ac.zw_.\n{menu_text}"
                        )
                        response_message = response.message(response_text)

                    logger.info(f"Sending response to {whatsapp_number}: {response_message.body}", extra=extra_log)
                    user_state.state = "main_menu"
                    user_state.last_updated = current_time
                    session.commit()
                    session.close()
                    return Response(str(response), mimetype="application/xml")

                except RateLimitException:
                    logger.warning(f"Rate limit hit while fetching gate pass data for {student_ids}, term {default_term}", extra=extra_log)
                    response_message = response.message(
                        f"⚠️ *Hi {fullname},*\n*Too many requests.* Please try again shortly.\n{menu_text}"
                    )
                    user_state.state = "main_menu"
                    user_state.last_updated = current_time
                    session.commit()
                    logger.info(f"Sending response to {whatsapp_number}: {response_message.body}", extra=extra_log)
                    session.close()
                    return Response(str(response), mimetype="application/xml")
                except ValueError as e:
                    logger.error(f"Gate pass error for {student_ids}, term {default_term}: {str(e)}\n{traceback.format_exc()}", extra=extra_log)
                    response_message = response.message(
                        f"⚠️ *Hi {fullname},*\n"
                        f"*No financial data found* for students in term *{default_term}*. Please contact _admin@shiningsmilescollege.ac.zw_.\n{menu_text}"
                    )
                    user_state.state = "main_menu"
                    user_state.last_updated = current_time
                    session.commit()
                    logger.info(f"Sending response to {whatsapp_number}: {response_message.body}", extra=extra_log)
                    session.close()
                    return Response(str(response), mimetype="application/xml")
                except requests.RequestException as e:
                    logger.error(f"Failed to generate gate passes for {student_ids}, term {default_term}: {str(e)}\n{traceback.format_exc()}", extra=extra_log)
                    response_message = response.message(
                        f"❌ *Hi {fullname},*\n"
                        f"*Failed to generate gate passes* for term *{default_term}*. Please contact _admin@shiningsmilescollege.ac.zw_.\n{menu_text}"
                    )
                    user_state.state = "main_menu"
                    user_state.last_updated = current_time
                    session.commit()
                    logger.info(f"Sending response to {whatsapp_number}: {response_message.body}", extra=extra_log)
                    session.close()
                    return Response(str(response), mimetype="application/xml")
                except Exception as e:
                    logger.error(f"Unexpected error in gate pass generation for {student_ids}, term {default_term}: {str(e)}\n{traceback.format_exc()}", extra=extra_log)
                    response_message = response.message(
                        f"⚠️ *Hi {fullname},*\n"
                        f"*An unexpected error occurred.* Please contact _admin@shiningsmilescollege.ac.zw_.\n{menu_text}"
                    )
                    user_state.state = "main_menu"
                    user_state.last_updated = current_time
                    session.commit()
                    logger.info(f"Sending response to {whatsapp_number}: {response_message.body}", extra=extra_log)
                    session.close()
                    return Response(str(response), mimetype="application/xml")

            elif message_body == "help":
                response_message = response.message(
                    f"❓ *Hi {fullname},*\n"
                    f"*Help*: Reply with *menu* to see options or contact _admin@shiningsmilescollege.ac.zw_ for account issues.\n{menu_text}"
                )
                logger.info(f"Sending response to {whatsapp_number}: {response_message.body}", extra=extra_log)
                user_state.state = "main_menu"
                user_state.last_updated = current_time
                session.commit()
                session.close()
                return Response(str(response), mimetype="application/xml")

            elif message_body in config.TERM_START_DATES.keys():
                # User entered a term code directly - show balance and offer statements
                term = message_body
                try:
                    current_date = current_time.date()
                    term_start = config.TERM_START_DATES.get(term)
                    if term_start and term_start.date() > current_date:
                        response_message = response.message(
                            f"📅 *Hi {fullname},*\n"
                            f"Term *{term}* has not started yet. Please select a current or past term (e.g., *2025-1*, *2025-2*).\n{menu_text}"
                        )
                        logger.info(f"Sending response to {whatsapp_number}: {response_message.body}", extra=extra_log)
                        session.close()
                        return Response(str(response), mimetype="application/xml")

                    balance_texts = []
                    for student_id in student_ids:
                        start_time = datetime.now(timezone.utc)
                        billed_fees = sms_client.get_student_billed_fees(student_id, term)
                        payments = sms_client.get_student_payments(student_id, term)
                        elapsed_time = (datetime.now(timezone.utc) - start_time).total_seconds()
                        if elapsed_time > 25:
                            logger.warning(f"API calls for balance took {elapsed_time}s, risking timeout for {student_id}", extra=extra_log)

                        logger.debug(f"Balance for {student_id}, Term {term}: "
                                     f"Billed fees: {billed_fees}, "
                                     f"Payments: {payments}", extra=extra_log)

                        total_fees = sum(float(bill["amount"]) for bill in billed_fees.get("data", {}).get("bills", [])) if billed_fees.get("data", {}).get("bills") else 0.0
                        total_paid = sum(float(p["amount"]) for p in payments.get("data", {}).get("payments", [])) if payments.get("data", {}).get("payments") else 0.0
                        balance = total_fees - total_paid

                        student_name = next((f"{c.firstname or ''} {c.lastname or ''}".strip() for c in contacts if c.student_id == student_id), "Unknown")
                        if not billed_fees.get("data", {}).get("bills"):
                            balance_texts.append(
                                f"*{student_id} ({student_name})*: No fees recorded"
                            )
                        elif balance == 0.0 and total_fees > 0.0:
                            balance_texts.append(
                                f"*{student_id} ({student_name})*: Fully paid ✅\n"
                                f"  Total Fees: ${total_fees:.2f}\n"
                                f"  Total Paid: ${total_paid:.2f}"
                            )
                        else:
                            balance_texts.append(
                                f"*{student_id} ({student_name})*:\n"
                                f"  Total Fees: ${total_fees:.2f}\n"
                                f"  Total Paid: ${total_paid:.2f}\n"
                                f"  Balance Owed: ${balance:.2f}"
                            )

                    if not balance_texts:
                        response_text = (
                            f"📊 *Hi {fullname},*\n"
                            f"No fees recorded for any students in term *{term}*. Please contact _admin@shiningsmilescollege.ac.zw_.\n\n"
                            f"💡 View other terms? Reply with term code (e.g., *2026-1*, *2025-3*)\n{menu_text}"
                        )
                    else:
                        response_text = (
                            f"📊 *Hi {fullname},*\n"
                            f"📊 *Balance for Term {term}:*\n\n"
                            f"\n\n".join(balance_texts) + 
                            f"\n\n💬 *Want detailed statements?* Reply *statement {term}*\n"
                            f"💡 View other terms? Reply with term code (e.g., *2026-1*, *2025-3*)\n{menu_text}"
                        )
                    
                    response_message = response.message(response_text)
                    logger.info(f"Sending response to {whatsapp_number}: {response_message.body}", extra=extra_log)
                    user_state.state = "main_menu"
                    user_state.last_updated = current_time
                    session.commit()
                    session.close()
                    return Response(str(response), mimetype="application/xml")

                except RateLimitException:
                    logger.warning(f"Rate limit hit while fetching balance for {student_ids}, term {term}", extra=extra_log)
                    response_message = response.message(
                        f"⚠️ *Hi {fullname},*\n*Too many requests.* Please try again shortly.\n{menu_text}"
                    )
                    user_state.state = "main_menu"
                    user_state.last_updated = current_time
                    session.commit()
                    logger.info(f"Sending response to {whatsapp_number}: {response_message.body}", extra=extra_log)
                    session.close()
                    return Response(str(response), mimetype="application/xml")
                except Exception as e:
                    logger.error(f"Unexpected error in balance retrieval for {student_ids}, term {term}: {str(e)}\n{traceback.format_exc()}", extra=extra_log)
                    response_message = response.message(
                        f"⚠️ *Hi {fullname},*\n"
                        f"*An unexpected error occurred.* Please contact _admin@shiningsmilescollege.ac.zw_.\n{menu_text}"
                    )
                    user_state.state = "main_menu"
                    user_state.last_updated = current_time
                    session.commit()
                    logger.info(f"Sending response to {whatsapp_number}: {response_message.body}", extra=extra_log)
                    session.close()
                    return Response(str(response), mimetype="application/xml")

            elif message_body.startswith("statement ") and len(message_body.split()) == 2:
                # User typed "statement 2025-1" to get statement for specific term
                _, term = message_body.split()
                if term in config.TERM_START_DATES.keys():
                    try:
                        current_date = current_time.date()
                        term_start = config.TERM_START_DATES.get(term)
                        if term_start and term_start.date() > current_date:
                            response_message = response.message(
                                f"📅 *Hi {fullname},*\n"
                                f"Term *{term}* has not started yet. Please select a current or past term (e.g., *2025-1*, *2025-2*).\n{menu_text}"
                            )
                            logger.info(f"Sending response to {whatsapp_number}: {response_message.body}", extra=extra_log)
                            user_state.state = "main_menu"
                            user_state.last_updated = current_time
                            session.commit()
                            session.close()
                            return Response(str(response), mimetype="application/xml")

                        statement_texts = []
                        max_message_length = 1400
                        for student_id in student_ids:
                            start_time = datetime.now(timezone.utc)
                            account = sms_client.get_student_account_statement(student_id, term)
                            billed_fees = sms_client.get_student_billed_fees(student_id, term)
                            payments = sms_client.get_student_payments(student_id, term)
                            elapsed_time = (datetime.now(timezone.utc) - start_time).total_seconds()
                            if elapsed_time > 25:
                                logger.warning(f"API calls for statement took {elapsed_time}s, risking timeout for {student_id}", extra=extra_log)

                            logger.debug(f"Account Statement for {student_id}, Term {term}: "
                                         f"API account data: {account}, "
                                         f"Billed fees: {billed_fees}, "
                                         f"Payments: {payments}", extra=extra_log)

                            total_fees = sum(float(bill["amount"]) for bill in billed_fees.get("data", {}).get("bills", [])) if billed_fees.get("data", {}).get("bills") else 0.0
                            total_paid = sum(float(p["amount"]) for p in payments.get("data", {}).get("payments", [])) if payments.get("data", {}).get("payments") else 0.0
                            balance = total_fees - total_paid

                            student_name = next((f"{c.firstname or ''} {c.lastname or ''}".strip() for c in contacts if c.student_id == student_id), "Unknown")
                            if not billed_fees.get("data", {}).get("bills"):
                                statement_text = f"*No fees recorded for {student_id} ({student_name}) in term {term}.*"
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
                                        [f"- *${b['amount']:.2f}* on _{b.get('date', 'N/A')}_ ({b.get('fee_type', 'N/A')})" for b in billed_fees.get("data", {}).get("bills")]
                                    )
                                    if billed_fees.get("data", {}).get("bills")
                                    else "No fees recorded."
                                )
                                statement_text = (
                                    f"*Account Statement for {student_id} ({student_name}, Term {term})*:\n"
                                    f"*Total Fees*: ${total_fees:.2f}\n"
                                    f"*Total Paid*: ${total_paid:.2f}\n"
                                    f"*Balance Owed*: ${balance:.2f}\n"
                                    f"*Fees Charged*:\n{fee_details}\n"
                                    f"*Payments*:\n{payment_details}"
                                ) if balance != 0.0 or total_fees <= 0.0 else (
                                    f"*Account Statement for {student_id} ({student_name}, Term {term})*:\n"
                                    f"*Great news!* Balance is *fully paid*.\n"
                                    f"*Total Fees*: ${total_fees:.2f}\n"
                                    f"*Total Paid*: ${total_paid:.2f}\n"
                                    f"*Balance Owed*: ${balance:.2f}\n"
                                    f"*Fees Charged*:\n{fee_details}\n"
                                    f"*Payments*:\n{payment_details}"
                                )

                                if len(statement_text) > max_message_length:
                                    statement_text = statement_text[:max_message_length - 50] + "\n*Note*: Statement truncated due to length. Contact admin for full details."
                            statement_texts.append(statement_text)

                        if not statement_texts:
                            statement_text = (
                                f"📊 *Hi {fullname},*\n"
                                f"No account statements found for any students in term *{term}*. Please contact _admin@shiningsmilescollege.ac.zw_.\n{menu_text}"
                            )
                            whatsapp_response = send_whatsapp_message(whatsapp_number, statement_text)
                            if whatsapp_response.get("status") != "sent":
                                logger.error(f"Failed to send statement: {whatsapp_response.get('error', 'Unknown error')}", extra=extra_log)
                                response_message = response.message(
                                    f"⚠️ *Hi {fullname},*\n*Failed to send statements.* Please try again or contact _admin@shiningsmilescollege.ac.zw_.\n{menu_text}"
                                )
                            else:
                                response_message = response.message(
                                    f"📨 *Hi {fullname},*\n*Statements have been sent for all students.*\n{menu_text}"
                                )
                        else:
                            combined_text = f"📊 *Hi {fullname},*\n" + "\n\n".join(statement_texts) + f"\n{menu_text}"
                            if len(combined_text) > max_message_length:
                                for statement in statement_texts:
                                    full_message = f"📊 *Hi {fullname},*\n{statement}\n{menu_text}"
                                    if len(full_message) > max_message_length:
                                        full_message = full_message[:max_message_length - 50] + "\n*Note*: Statement truncated. Contact admin for full details.\n{menu_text}"
                                    whatsapp_response = send_whatsapp_message(whatsapp_number, full_message)
                                    if whatsapp_response.get("status") != "sent":
                                        logger.error(f"Failed to send statement for {whatsapp_number}: {whatsapp_response.get('error', 'Unknown error')}", extra=extra_log)
                                        response_message = response.message(
                                            f"⚠️ *Hi {fullname},*\n*Failed to send statements.* Please try again or contact _admin@shiningsmilescollege.ac.zw_.\n{menu_text}"
                                        )
                                        user_state.state = "main_menu"
                                        user_state.last_updated = current_time
                                        session.commit()
                                        session.close()
                                        return Response(str(response), mimetype="application/xml")
                                response_message = response.message(
                                    f"📨 *Hi {fullname},*\n*Statements have been sent for all students.*\n{menu_text}"
                                )
                            else:
                                statement_text = combined_text
                                whatsapp_response = send_whatsapp_message(whatsapp_number, statement_text)
                                if whatsapp_response.get("status") != "sent":
                                    logger.error(f"Failed to send statement: {whatsapp_response.get('error', 'Unknown error')}", extra=extra_log)
                                    response_message = response.message(
                                        f"⚠️ *Hi {fullname},*\n*Failed to send statements.* Please try again or contact _admin@shiningsmilescollege.ac.zw_.\n{menu_text}"
                                    )
                                else:
                                    response_message = response.message(
                                        f"📨 *Hi {fullname},*\n*Statements have been sent for all students.*\n{menu_text}"
                                    )

                        logger.info(f"Sending response to {whatsapp_number}: {response_message.body}", extra=extra_log)
                        user_state.state = "main_menu"
                        user_state.last_updated = current_time
                        session.commit()
                        session.close()
                        return Response(str(response), mimetype="application/xml")

                    except RateLimitException:
                        logger.warning(f"Rate limit hit while fetching statement for {student_ids}, term {term}", extra=extra_log)
                        response_message = response.message(
                            f"⚠️ *Hi {fullname},*\n*Too many requests.* Please try again shortly.\n{menu_text}"
                        )
                        user_state.state = "main_menu"
                        user_state.last_updated = current_time
                        session.commit()
                        logger.info(f"Sending response to {whatsapp_number}: {response_message.body}", extra=extra_log)
                        session.close()
                        return Response(str(response), mimetype="application/xml")
                    except Exception as e:
                        logger.error(f"Unexpected error in statement generation for {student_ids}, term {term}: {str(e)}\n{traceback.format_exc()}", extra=extra_log)
                        response_message = response.message(
                            f"⚠️ *Hi {fullname},*\n"
                            f"*An unexpected error occurred.* Please contact _admin@shiningsmilescollege.ac.zw_.\n{menu_text}"
                        )
                        user_state.state = "main_menu"
                        user_state.last_updated = current_time
                        session.commit()
                        logger.info(f"Sending response to {whatsapp_number}: {response_message.body}", extra=extra_log)
                        session.close()
                        return Response(str(response), mimetype="application/xml")


            else:
                response_message = response.message(
                    f"⚠️ *Hi {fullname},*\n"
                    f"*Invalid input.* Please reply with a valid option.\n{menu_text}"
                )
                logger.info(f"Sending response to {whatsapp_number}: {response_message.body}", extra=extra_log)
                session.close()
                return Response(str(response), mimetype="application/xml")

        elif user_state.state == "awaiting_term_balance":
            if message_body in config.TERM_START_DATES.keys():
                term = message_body
                try:
                    current_date = current_time.date()
                    term_start = config.TERM_START_DATES.get(term)
                    if term_start and term_start.date() > current_date:
                        response_message = response.message(
                            f"📅 *Hi {fullname},*\n"
                            f"Term *{term}* has not started yet. Please select a current or past term (e.g., *2025-1*, *2025-2*) for all students.\n{menu_text}"
                        )
                        logger.info(f"Sending response to {whatsapp_number}: {response_message.body}", extra=extra_log)
                        user_state.state = "main_menu"
                        user_state.last_updated = current_time
                        session.commit()
                        session.close()
                        return Response(str(response), mimetype="application/xml")

                    balance_texts = []
                    for student_id in student_ids:
                        start_time = datetime.now(timezone.utc)
                        account = sms_client.get_student_account_statement(student_id, term)
                        billed_fees = sms_client.get_student_billed_fees(student_id, term)
                        payments = sms_client.get_student_payments(student_id, term)
                        elapsed_time = (datetime.now(timezone.utc) - start_time).total_seconds()
                        if elapsed_time > 25:
                            logger.warning(f"API calls for balance took {elapsed_time}s, risking timeout for {student_id}", extra=extra_log)

                        logger.debug(f"Balance for {student_id}, Term {term}: "
                                     f"API account data: {account}, "
                                     f"Billed fees: {billed_fees}, "
                                     f"Payments: {payments}", extra=extra_log)

                        total_fees = sum(float(bill["amount"]) for bill in billed_fees.get("data", {}).get("bills", [])) if billed_fees.get("data", {}).get("bills") else 0.0
                        total_paid = sum(float(p["amount"]) for p in payments.get("data", {}).get("payments", [])) if payments.get("data", {}).get("payments") else 0.0
                        balance = total_fees - total_paid

                        student_name = next((f"{c.firstname or ''} {c.lastname or ''}".strip() for c in contacts if c.student_id == student_id), "Unknown")
                        if not billed_fees.get("data", {}).get("bills"):
                            balance_texts.append(
                                f"*No fees recorded for {student_id} ({student_name}) in term {term}.*"
                            )
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
                        response_message = response.message(
                            f"📊 *Hi {fullname},*\n"
                            f"No fees recorded for any students in term *{term}*. Please contact _admin@shiningsmilescollege.ac.zw_.\n{menu_text}"
                        )
                    else:
                        response_text = (
                            f"📊 *Hi {fullname},*\n"
                            f"\n\n".join(balance_texts) + f"\n{menu_text}"
                        )
                        response_message = response.message(response_text)

                    logger.info(f"Sending response to {whatsapp_number}: {response_message.body}", extra=extra_log)
                    user_state.state = "main_menu"
                    user_state.last_updated = current_time
                    session.commit()
                    session.close()
                    return Response(str(response), mimetype="application/xml")

                except RateLimitException:
                    logger.warning(f"Rate limit hit while fetching balance for {student_ids}, term {term}", extra=extra_log)
                    response_message = response.message(
                        f"⚠️ *Hi {fullname},*\n*Too many requests.* Please try again shortly.\n{menu_text}"
                    )
                    user_state.state = "main_menu"
                    user_state.last_updated = current_time
                    session.commit()
                    logger.info(f"Sending response to {whatsapp_number}: {response_message.body}", extra=extra_log)
                    session.close()
                    return Response(str(response), mimetype="application/xml")
                except ValueError as e:
                    logger.error(f"Account statement error for {student_ids}, term {term}: {str(e)}\n{traceback.format_exc()}", extra=extra_log)
                    response_message = response.message(
                        f"⚠️ *Hi {fullname},*\n"
                        f"No account statements found for students in term *{term}*. "
                        f"Please contact _admin@shiningsmilescollege.ac.zw_.\n{menu_text}"
                    )
                    user_state.state = "main_menu"
                    user_state.last_updated = current_time
                    session.commit()
                    logger.info(f"Sending response to {whatsapp_number}: {response_message.body}", extra=extra_log)
                    session.close()
                    return Response(str(response), mimetype="application/xml")
                except requests.RequestException as e:
                    logger.error(f"Failed to fetch balance for {student_ids}, term {term}: {str(e)}\n{traceback.format_exc()}", extra=extra_log)
                    response_message = response.message(
                        f"⚠️ *Hi {fullname},*\n"
                        f"Error fetching balances for term *{term}*. Please contact _admin@shiningsmilescollege.ac.zw_.\n{menu_text}"
                    )
                    user_state.state = "main_menu"
                    user_state.last_updated = current_time
                    session.commit()
                    logger.info(f"Sending response to {whatsapp_number}: {response_message.body}", extra=extra_log)
                    session.close()
                    return Response(str(response), mimetype="application/xml")
                except Exception as e:
                    logger.error(f"Unexpected error in balance retrieval for {student_ids}, term {term}: {str(e)}\n{traceback.format_exc()}", extra=extra_log)
                    response_message = response.message(
                        f"⚠️ *Hi {fullname},*\n"
                        f"*An unexpected error occurred.* Please contact _admin@shiningsmilescollege.ac.zw_.\n{menu_text}"
                    )
                    user_state.state = "main_menu"
                    user_state.last_updated = current_time
                    session.commit()
                    logger.info(f"Sending response to {whatsapp_number}: {response_message.body}", extra=extra_log)
                    session.close()
                    return Response(str(response), mimetype="application/xml")

            else:
                response_message = response.message(
                    f"📅 *Hi {fullname},*\n"
                    f"*Invalid term.* Please reply with a valid term (e.g., *2025-1*, *2025-2*, *2025-3*) for all students."
                )
                logger.info(f"Sending response to {whatsapp_number}: {response_message.body}", extra=extra_log)
                session.close()
                return Response(str(response), mimetype="application/xml")

        elif user_state.state == "awaiting_term_statement":
            if message_body in config.TERM_START_DATES.keys():
                term = message_body
                try:
                    current_date = current_time.date()
                    term_start = config.TERM_START_DATES.get(term)
                    if term_start and term_start.date() > current_date:
                        response_message = response.message(
                            f"📅 *Hi {fullname},*\n"
                            f"Term *{term}* has not started yet. Please select a current or past term (e.g., *2025-1*, *2025-2*) for all students.\n{menu_text}"
                        )
                        logger.info(f"Sending response to {whatsapp_number}: {response_message.body}", extra=extra_log)
                        user_state.state = "main_menu"
                        user_state.last_updated = current_time
                        session.commit()
                        session.close()
                        return Response(str(response), mimetype="application/xml")

                    statement_texts = []
                    max_message_length = 1400  # Buffer below Twilio's 1600-character limit
                    for student_id in student_ids:
                        start_time = datetime.now(timezone.utc)
                        account = sms_client.get_student_account_statement(student_id, term)
                        billed_fees = sms_client.get_student_billed_fees(student_id, term)
                        payments = sms_client.get_student_payments(student_id, term)
                        elapsed_time = (datetime.now(timezone.utc) - start_time).total_seconds()
                        if elapsed_time > 25:
                            logger.warning(f"API calls for statement took {elapsed_time}s, risking timeout for {student_id}", extra=extra_log)

                        logger.debug(f"Account Statement for {student_id}, Term {term}: "
                                     f"API account data: {account}, "
                                     f"Billed fees: {billed_fees}, "
                                     f"Payments: {payments}", extra=extra_log)

                        total_fees = sum(float(bill["amount"]) for bill in billed_fees.get("data", {}).get("bills", [])) if billed_fees.get("data", {}).get("bills") else 0.0
                        total_paid = sum(float(p["amount"]) for p in payments.get("data", {}).get("payments", [])) if payments.get("data", {}).get("payments") else 0.0
                        balance = total_fees - total_paid

                        student_name = next((f"{c.firstname or ''} {c.lastname or ''}".strip() for c in contacts if c.student_id == student_id), "Unknown")
                        if not billed_fees.get("data", {}).get("bills"):
                            statement_text = f"*No fees recorded for {student_id} ({student_name}) in term {term}.*"
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
                                    [f"- *${b['amount']:.2f}* on _{b.get('date', 'N/A')}_ ({b.get('fee_type', 'N/A')})" for b in billed_fees.get("data", {}).get("bills")]
                                )
                                if billed_fees.get("data", {}).get("bills")
                                else "No fees recorded."
                            )
                            statement_text = (
                                f"*Account Statement for {student_id} ({student_name}, Term {term})*:\n"
                                f"*Total Fees*: ${total_fees:.2f}\n"
                                f"*Total Paid*: ${total_paid:.2f}\n"
                                f"*Balance Owed*: ${balance:.2f}\n"
                                f"*Fees Charged*:\n{fee_details}\n"
                                f"*Payments*:\n{payment_details}"
                            ) if balance != 0.0 or total_fees <= 0.0 else (
                                f"*Account Statement for {student_id} ({student_name}, Term {term})*:\n"
                                f"*Great news!* Balance is *fully paid*.\n"
                                f"*Total Fees*: ${total_fees:.2f}\n"
                                f"*Total Paid*: ${total_paid:.2f}\n"
                                f"*Balance Owed*: ${balance:.2f}\n"
                                f"*Fees Charged*:\n{fee_details}\n"
                                f"*Payments*:\n{payment_details}"
                            )

                            # Truncate individual statement if too long
                            if len(statement_text) > max_message_length:
                                statement_text = statement_text[:max_message_length - 50] + "\n*Note*: Statement truncated due to length. Contact admin for full details."
                        statement_texts.append(statement_text)

                    if not statement_texts:
                        statement_text = (
                            f"📊 *Hi {fullname},*\n"
                            f"No account statements found for any students in term *{term}*. Please contact _admin@shiningsmilescollege.ac.zw_.\n{menu_text}"
                        )
                        whatsapp_response = send_whatsapp_message(whatsapp_number, statement_text)
                        if whatsapp_response.get("status") != "sent":
                            logger.error(f"Failed to send statement: {whatsapp_response.get('error', 'Unknown error')}", extra=extra_log)
                            response_message = response.message(
                                f"⚠️ *Hi {fullname},*\n*Failed to send statements.* Please try again or contact _admin@shiningsmilescollege.ac.zw_.\n{menu_text}"
                            )
                        else:
                            response_message = response.message(
                                f"📨 *Hi {fullname},*\n*Statements have been sent for all students.*\n{menu_text}"
                            )
                    else:
                        # Check combined length
                        combined_text = f"📊 *Hi {fullname},*\n" + "\n\n".join(statement_texts) + f"\n{menu_text}"
                        if len(combined_text) > max_message_length:
                            # Send individual messages
                            for statement in statement_texts:
                                full_message = f"📊 *Hi {fullname},*\n{statement}\n{menu_text}"
                                if len(full_message) > max_message_length:
                                    full_message = full_message[:max_message_length - 50] + "\n*Note*: Statement truncated. Contact admin for full details.\n{menu_text}"
                                whatsapp_response = send_whatsapp_message(whatsapp_number, full_message)
                                if whatsapp_response.get("status") != "sent":
                                    logger.error(f"Failed to send statement for {whatsapp_number}: {whatsapp_response.get('error', 'Unknown error')}", extra=extra_log)
                                    response_message = response.message(
                                        f"⚠️ *Hi {fullname},*\n*Failed to send statements.* Please try again or contact _admin@shiningsmilescollege.ac.zw_.\n{menu_text}"
                                    )
                                    user_state.state = "main_menu"
                                    user_state.last_updated = current_time
                                    session.commit()
                                    session.close()
                                    return Response(str(response), mimetype="application/xml")
                            response_message = response.message(
                                f"📨 *Hi {fullname},*\n*Statements have been sent for all students.*\n{menu_text}"
                            )
                        else:
                            # Send combined message
                            statement_text = combined_text
                            whatsapp_response = send_whatsapp_message(whatsapp_number, statement_text)
                            if whatsapp_response.get("status") != "sent":
                                logger.error(f"Failed to send statement: {whatsapp_response.get('error', 'Unknown error')}", extra=extra_log)
                                response_message = response.message(
                                    f"⚠️ *Hi {fullname},*\n*Failed to send statements.* Please try again or contact _admin@shiningsmilescollege.ac.zw_.\n{menu_text}"
                                )
                            else:
                                response_message = response.message(
                                    f"📨 *Hi {fullname},*\n*Statements have been sent for all students.*\n{menu_text}"
                                )

                    logger.info(f"Sending response to {whatsapp_number}: {response_message.body}", extra=extra_log)
                    user_state.state = "main_menu"
                    user_state.last_updated = current_time
                    session.commit()
                    session.close()
                    return Response(str(response), mimetype="application/xml")

                except RateLimitException:
                    logger.warning(f"Rate limit hit while fetching statement for {student_ids}, term {term}", extra=extra_log)
                    response_message = response.message(
                        f"⚠️ *Hi {fullname},*\n*Too many requests.* Please try again shortly.\n{menu_text}"
                    )
                    user_state.state = "main_menu"
                    user_state.last_updated = current_time
                    session.commit()
                    logger.info(f"Sending response to {whatsapp_number}: {response_message.body}", extra=extra_log)
                    session.close()
                    return Response(str(response), mimetype="application/xml")
                except ValueError as e:
                    logger.error(f"Account statement error for {student_ids}, term {term}: {str(e)}\n{traceback.format_exc()}", extra=extra_log)
                    response_message = response.message(
                        f"⚠️ *Hi {fullname},*\n"
                        f"No account statements found for students in term *{term}*. "
                        f"Please contact _admin@shiningsmilescollege.ac.zw_.\n{menu_text}"
                    )
                    user_state.state = "main_menu"
                    user_state.last_updated = current_time
                    session.commit()
                    logger.info(f"Sending response to {whatsapp_number}: {response_message.body}", extra=extra_log)
                    session.close()
                    return Response(str(response), mimetype="application/xml")
                except requests.RequestException as e:
                    logger.error(f"Failed to fetch statement for {student_ids}, term {term}: {str(e)}\n{traceback.format_exc()}", extra=extra_log)
                    response_message = response.message(
                        f"⚠️ *Hi {fullname},*\n"
                        f"Error fetching statements for term *{term}*. Please contact _admin@shiningsmilescollege.ac.zw_.\n{menu_text}"
                    )
                    user_state.state = "main_menu"
                    user_state.last_updated = current_time
                    session.commit()
                    logger.info(f"Sending response to {whatsapp_number}: {response_message.body}", extra=extra_log)
                    session.close()
                    return Response(str(response), mimetype="application/xml")
                except Exception as e:
                    logger.error(f"Unexpected error in statement generation for {student_ids}, term {term}: {str(e)}\n{traceback.format_exc()}", extra=extra_log)
                    response_message = response.message(
                        f"⚠️ *Hi {fullname},*\n"
                        f"*An unexpected error occurred.* Please contact _admin@shiningsmilescollege.ac.zw_.\n{menu_text}"
                    )
                    user_state.state = "main_menu"
                    user_state.last_updated = current_time
                    session.commit()
                    logger.info(f"Sending response to {whatsapp_number}: {response_message.body}", extra=extra_log)
                    session.close()
                    return Response(str(response), mimetype="application/xml")

            else:
                response_message = response.message(
                    f"📅 *Hi {fullname},*\n"
                    f"*Invalid term.* Please reply with a valid term (e.g., *2025-1*, *2025-2*, *2025-3*) for all students."
                )
                logger.info(f"Sending response to {whatsapp_number}: {response_message.body}", extra=extra_log)
                session.close()
                return Response(str(response), mimetype="application/xml")

        elif user_state.state == "awaiting_term_gatepass":
            if message_body in config.TERM_START_DATES.keys():
                term = message_body
                try:
                    current_date = current_time.date()
                    term_start = config.TERM_START_DATES.get(term)
                    term_end = config.TERM_END_DATES.get(term)
                    if term_start and term_end and not (term_start.date() <= current_date <= term_end.date()):
                        next_term = min(
                            (t for t, start in config.TERM_START_DATES.items() if start.date() > current_date),
                            key=lambda t: config.TERM_START_DATES[t].date(),
                            default=None
                        )
                        next_term_date = config.TERM_START_DATES[next_term].date().strftime("%d %B %Y") if next_term else "a future date"
                        response_message = response.message(
                            f"📅 *Hi {fullname},*\n"
                            f"Gate passes are only issued during active school terms. Term *{term}* is not active. Schools reopen on {next_term_date} for Term {next_term or '3'}. Please try again then.\n{menu_text}"
                        )
                        logger.info(f"Sending holiday response to {whatsapp_number}: {response_message.body}", extra=extra_log)
                        user_state.state = "main_menu"
                        user_state.last_updated = current_time
                        session.commit()
                        session.close()
                        return Response(str(response), mimetype="application/xml")

                    gatepass_texts = []
                    for student_id in student_ids:
                        billed_fees = sms_client.get_student_billed_fees(student_id, term)
                        total_fees = sum(float(bill["amount"]) for bill in billed_fees.get("data", {}).get("bills", [])) if billed_fees.get("data", {}).get("bills") else 0.0
                        payments = sms_client.get_student_payments(student_id, term)
                        total_paid = sum(float(p["amount"]) for p in payments.get("data", {}).get("payments", [])) if payments.get("data", {}).get("payments") else 0.0
                        payment_percentage = (total_paid / total_fees) * 100 if total_fees > 0 else 0

                        logger.debug(f"[GatePass] {student_id} - Paid: {total_paid}, Total Fees: {total_fees}, Term: {term}, Percentage: {payment_percentage}%", extra=extra_log)

                        gatepass_url = f"{config.APP_BASE_URL}/generate-gatepass"
                        payload = {
                            "student_id": student_id,
                            "term": term,
                            "payment_amount": total_paid,
                            "total_fees": total_fees,
                            "request_id": request_id
                        }

                        gatepass_res = requests.post(gatepass_url, json=payload, timeout=10)
                        logger.debug(f"[GatePass Response] {student_id} - {gatepass_res.status_code} - {gatepass_res.text}", extra=extra_log)

                        data = gatepass_res.json()
                        status_msg = data.get("status", "").lower()

                        student_name = next((f"{c.firstname or ''} {c.lastname or ''}".strip() for c in contacts if c.student_id == student_id), "Unknown")
                        if gatepass_res.status_code == 200:
                            if "already valid" in status_msg or "resent" in status_msg:
                                gatepass_texts.append(
                                    f"*Gate Pass for {student_id} ({student_name})*:\n"
                                    f"You *already have a valid gate pass*.\n"
                                    f"*Pass ID*: {data.get('pass_id')}\n"
                                    f"*Expires*: _{data.get('expiry_date')}_\n"
                                    f"*PDF re-sent to*: {data.get('whatsapp_number')}"
                                )
                            else:
                                gatepass_texts.append(
                                    f"*Gate Pass for {student_id} ({student_name})*:\n"
                                    f"*Gate Pass Issued!* 🎉\n"
                                    f"*Pass ID*: {data.get('pass_id')}\n"
                                    f"*Expires*: _{data.get('expiry_date')}_\n"
                                    f"*Sent to*: {data.get('whatsapp_number')}"
                                )
                        else:
                            error_msg = data.get("error", "Could not issue gate pass.")
                            gatepass_texts.append(
                                f"*Gate Pass for {student_id} ({student_name})*:\n"
                                f"*{error_msg}*"
                            )

                    if not gatepass_texts:
                        response_message = response.message(
                            f"⚠️ *Hi {fullname},*\n*No gate passes issued.* Please contact _admin@shiningsmilescollege.ac.zw_.\n{menu_text}"
                        )
                    else:
                        response_text = (
                            f"✅ *Hi {fullname},*\n"
                            f"\n\n".join(gatepass_texts) +
                            f"\nIf not received, ensure *{whatsapp_number}* is registered with WhatsApp or contact _admin@shiningsmilescollege.ac.zw_.\n{menu_text}"
                        )
                        response_message = response.message(response_text)

                    logger.info(f"Sending response to {whatsapp_number}: {response_message.body}", extra=extra_log)
                    user_state.state = "main_menu"
                    user_state.last_updated = current_time
                    session.commit()
                    session.close()
                    return Response(str(response), mimetype="application/xml")

                except RateLimitException:
                    logger.warning(f"Rate limit hit while fetching gate pass data for {student_ids}, term {term}", extra=extra_log)
                    response_message = response.message(
                        f"⚠️ *Hi {fullname},*\n*Too many requests.* Please try again shortly.\n{menu_text}"
                    )
                    user_state.state = "main_menu"
                    user_state.last_updated = current_time
                    session.commit()
                    logger.info(f"Sending response to {whatsapp_number}: {response_message.body}", extra=extra_log)
                    session.close()
                    return Response(str(response), mimetype="application/xml")
                except ValueError as e:
                    logger.error(f"Gate pass error for {student_ids}, term {term}: {str(e)}\n{traceback.format_exc()}", extra=extra_log)
                    response_message = response.message(
                        f"⚠️ *Hi {fullname},*\n"
                        f"*No financial data found* for students in term *{term}*. Please contact _admin@shiningsmilescollege.ac.zw_.\n{menu_text}"
                    )
                    user_state.state = "main_menu"
                    user_state.last_updated = current_time
                    session.commit()
                    logger.info(f"Sending response to {whatsapp_number}: {response_message.body}", extra=extra_log)
                    session.close()
                    return Response(str(response), mimetype="application/xml")
                except requests.RequestException as e:
                    logger.error(f"Failed to generate gate passes for {student_ids}, term {term}: {str(e)}\n{traceback.format_exc()}", extra=extra_log)
                    response_message = response.message(
                        f"❌ *Hi {fullname},*\n"
                        f"*Failed to generate gate passes* for term *{term}*. Please contact _admin@shiningsmilescollege.ac.zw_.\n{menu_text}"
                    )
                    user_state.state = "main_menu"
                    user_state.last_updated = current_time
                    session.commit()
                    logger.info(f"Sending response to {whatsapp_number}: {response_message.body}", extra=extra_log)
                    session.close()
                    return Response(str(response), mimetype="application/xml")
                except Exception as e:
                    logger.error(f"Unexpected error in gate pass generation for {student_ids}, term {term}: {str(e)}\n{traceback.format_exc()}", extra=extra_log)
                    response_message = response.message(
                        f"⚠️ *Hi {fullname},*\n"
                        f"*An unexpected error occurred.* Please contact _admin@shiningsmilescollege.ac.zw_.\n{menu_text}"
                    )
                    user_state.state = "main_menu"
                    user_state.last_updated = current_time
                    session.commit()
                    logger.info(f"Sending response to {whatsapp_number}: {response_message.body}", extra=extra_log)
                    session.close()
                    return Response(str(response), mimetype="application/xml")

            else:
                response_message = response.message(
                    f"📅 *Hi {fullname},*\n"
                    f"*Invalid term.* Please reply with a valid term (e.g., *2025-1*, *2025-2*, *2025-3*) for all students."
                )
                logger.info(f"Sending response to {whatsapp_number}: {response_message.body}", extra=extra_log)
                session.close()
                return Response(str(response), mimetype="application/xml")

        else:
            response_message = response.message(
                f"⚠️ *Hi {fullname},*\n"
                f"*Invalid state.* Please reply with *menu* to start over.\n{menu_text}"
            )
            logger.info(f"Sending response to {whatsapp_number}: {response_message.body}", extra=extra_log)
            user_state.state = "main_menu"
            user_state.last_updated = current_time
            session.commit()
            session.close()
            return Response(str(response), mimetype="application/xml")

    except Exception as e:
        logger.error(f"[WhatsApp Menu Fatal Error] {str(e)}\n{traceback.format_exc()}", extra=extra_log)
        response_message = response.message(
            f"⚠️ *Hi {fullname},*\n*An unexpected error occurred.* Please contact _admin@shiningsmilescollege.ac.zw_.\n{menu_text}"
        )
        logger.info(f"Sending response to {whatsapp_number}: {response_message.body}", extra=extra_log)
        if user_state:
            user_state.state = "main_menu"
            user_state.last_updated = current_time
            session.commit()
        session.close()
        return Response(str(response), mimetype="application/xml")
    finally:
        session.close()
