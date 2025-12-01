import os
import re
import uuid
import boto3
from botocore.client import Config
from datetime import datetime, timezone, timedelta
import requests
import traceback

# Lazy imports - only import when needed to avoid import errors
# from reportlab - imported in functions that need it
# import qrcode - imported in functions that need it

try:
    from flask import render_template, request, jsonify
except ImportError:
    # Flask not available in Lambda, that's OK
    render_template = None
    request = None
    jsonify = None

from utils.database import init_db, StudentContact, GatePass, GatePassScan
from utils.whatsapp import send_whatsapp_message
from utils.logger import setup_logger
from api.sms_client import SMSClient
from config import get_config

logger = setup_logger(__name__)
config = get_config()

# AWS S3 client
s3 = boto3.client(
    's3',
    aws_access_key_id=config.AWS_ACCESS_KEY_ID,
    aws_secret_access_key=config.AWS_SECRET_ACCESS_KEY,
    region_name='us-east-2',
    config=Config(signature_version='s3v4')
)
bucket_name = 'shining-smiles-gatepasses'

def calculate_expiry_date(term, payment_percentage, payment_date=None):
    now = payment_date or datetime.now(timezone.utc)
    term_end = config.TERM_END_DATES.get(term)
    if not term_end:
        logger.error(f"Invalid term: {term}. Configuration for TERM_END_DATES missing or incorrect.")
        return {"error": f"Invalid term: {term}. Please contact support."}, 400

    if term_end.tzinfo is None:
        term_end = term_end.replace(tzinfo=timezone.utc)

    if payment_percentage >= 100:
        return term_end
    elif payment_percentage >= 70:
        one_month_before = term_end - timedelta(days=30)
        return one_month_before if one_month_before > now else now + timedelta(days=1)
    elif payment_percentage >= 50:
        next_month = (now + timedelta(days=32)).replace(day=1, hour=0, minute=0, second=0, microsecond=0)
        last_day_of_month = (next_month.replace(day=28) + timedelta(days=4)).replace(day=1) - timedelta(days=1)
        last_day_of_month = last_day_of_month.replace(hour=23, minute=59, second=59, microsecond=999999, tzinfo=timezone.utc)
        return last_day_of_month if last_day_of_month > now else now + timedelta(days=1)
    else:
        logger.warning(f"Payment percentage {payment_percentage}% below 50%; no gate pass issued.")
        return None

def send_email_fallback(student_id, whatsapp_number, pass_id, expiry_date, s3_key):
    """Placeholder for sending gate pass via email (not implemented)."""
    try:
        session = init_db()
        contact = session.query(StudentContact).filter_by(student_id=student_id).first()
        if not contact or not contact.email:
            logger.error(f"No email found for student {student_id}", extra={"student_id": student_id})
            return False

        expiry_seconds = 3600
        presigned_url = s3.generate_presigned_url(
            'get_object',
            Params={'Bucket': bucket_name, 'Key': s3_key},
            ExpiresIn=expiry_seconds
        )
        email_body = (
            f"Dear {contact.firstname or 'Parent'} {contact.lastname or 'Guardian'},\n"
            f"Your gate pass for {student_id} is attached.\n"
            f"Pass ID: {pass_id}\n"
            f"Expires: {expiry_date.strftime('%Y-%m-%d')}\n"
            f"Download here: {presigned_url}\n"
            f"This pass is valid only for {whatsapp_number}. Do not share."
        )
        # Placeholder: Implement SES or other email service here
        logger.info(f"Email fallback would be sent to {contact.email} for student {student_id}", extra={"student_id": student_id})
        return False  # Email not implemented
    except Exception as e:
        logger.error(f"Failed to send email fallback for {student_id}: {str(e)}", extra={"student_id": student_id})
        return False
    finally:
        session.remove()

def generate_gatepass(student_id, term, payment_amount, total_fees, request_id, requesting_whatsapp_number=None):
    session = init_db()
    extra_log = {"request_id": request_id, "student_id": student_id}
    try:
        # Validate inputs
        if not student_id or not term:
            logger.error("Missing student_id or term", extra=extra_log)
            return {"error": "Both student_id and term are required"}, 400

        # Validate student_id format (e.g., SSC followed by numbers)
        if not re.match(r'^SSC\d+$', student_id.strip().upper()):
            logger.error(f"Invalid student_id format: {student_id}", extra=extra_log)
            return {"error": "Invalid student_id format (expected SSC followed by numbers)"}, 400

        # Validate term format (e.g., YYYY-N)
        if not re.match(r'^\d{4}-\d$', term):
            logger.error(f"Invalid term format: {term}", extra=extra_log)
            return {"error": "Invalid term format (expected YYYY-N, e.g., 2025-2)"}, 400

        if not total_fees or total_fees <= 0:
            logger.error(f"Invalid total_fees: {total_fees}", extra=extra_log)
            return {"error": "Total fees must be greater than 0"}, 400

        if payment_amount < 0:
            logger.error(f"Invalid payment_amount: {payment_amount}", extra=extra_log)
            return {"error": "Payment amount cannot be negative"}, 400

        contact = session.query(StudentContact).filter_by(student_id=student_id).first()
        if not contact:
            logger.error(f"No contact found for {student_id}", extra=extra_log)
            return {"error": "No contact found for student ID"}, 404

        # Use the requesting WhatsApp number if provided (the one the user is messaging from)
        # Otherwise fall back to database numbers
        whatsapp_number = requesting_whatsapp_number or contact.preferred_phone_number or contact.student_mobile
        if not whatsapp_number:
            logger.error(f"No valid WhatsApp number for {student_id}", extra=extra_log)
            return {"error": "No valid WhatsApp number found for this student"}, 400

        # Validate WhatsApp number format
        if not re.match(r'^\+\d{10,15}$', whatsapp_number):
            logger.error(f"Invalid WhatsApp number format: {whatsapp_number}", extra=extra_log)
            return {"error": f"Invalid WhatsApp number format for {whatsapp_number} (expected + followed by 10-15 digits)"}, 400

        # Check WhatsApp registration
        sms_client = SMSClient(request_id=request_id, use_cloud_api=True)
        if not sms_client.check_whatsapp_number(whatsapp_number):
            logger.error(f"Number {whatsapp_number} not registered with WhatsApp", extra=extra_log)
            return {"error": f"Number {whatsapp_number} is not registered with WhatsApp. Please register or contact support."}, 400

        payment_percentage = (payment_amount / total_fees) * 100
        expiry_date = calculate_expiry_date(term, payment_percentage)
        if isinstance(expiry_date, dict) and "error" in expiry_date:
            logger.error(f"Failed to calculate expiry date: {expiry_date['error']}", extra=extra_log)
            return expiry_date, 400

        if not expiry_date:
            logger.info(f"Payment {payment_percentage}% for {student_id} below 50%; no gate pass issued", extra=extra_log)
            return {"status": "No gate pass issued", "reason": "Payment below 50%"}, 200

        issued_date = datetime.now(timezone.utc)
        existing_pass = session.query(GatePass).filter(
            GatePass.student_id == student_id,
            GatePass.expiry_date >= issued_date
        ).first()

        if existing_pass and existing_pass.payment_percentage >= payment_percentage:
            logger.info(f"Existing gate pass for {student_id} is still valid until {existing_pass.expiry_date}", extra=extra_log)
            s3_key = existing_pass.pdf_path
            expiry_seconds = 3600  # 1 hour
            presigned_url = s3.generate_presigned_url(
                'get_object',
                Params={'Bucket': bucket_name, 'Key': s3_key},
                ExpiresIn=expiry_seconds
            )
            try:
                check = requests.get(presigned_url, stream=True, timeout=5)
                if check.status_code == 200:
                    message = (
                        f"Dear {contact.firstname or 'Parent'} {contact.lastname or 'Guardian'},\n"
                        f"You already have a valid gate pass.\n"
                        f"Pass ID: {existing_pass.pass_id}\n"
                        f"Expires: {existing_pass.expiry_date.strftime('%Y-%m-%d')}\n"
                        f"This pass is valid only for {whatsapp_number}. Do not share."
                    )
                    whatsapp_response = send_whatsapp_message(whatsapp_number, message, media_url=[presigned_url])
                    if whatsapp_response.get("status") != "sent":
                        logger.error(f"Failed to send WhatsApp message: {whatsapp_response.get('error', 'Unknown error')}", extra=extra_log)
                    logger.info(f"Re-sent existing gate pass to {whatsapp_number}", extra=extra_log)
                else:
                    raise Exception(f"Pre-signed URL not accessible: status {check.status_code}")
            except Exception as e:
                logger.error(f"Failed to resend existing gate pass to {whatsapp_number}: {str(e)}", extra=extra_log)
                fallback_msg = (
                    f"Dear {contact.firstname or 'Parent'} {contact.lastname or 'Guardian'},\n"
                    f"Gate Pass for {student_id}:\n"
                    f"Pass ID: {existing_pass.pass_id}\n"
                    f"Expires: {existing_pass.expiry_date.strftime('%Y-%m-%d')}\n"
                    f"Payment: {existing_pass.payment_percentage}%\n"
                    f"This pass is valid only for {whatsapp_number}. Do not share.\n"
                    f"Please contact support@shiningsmiles.com if you don't receive the PDF."
                )
                whatsapp_response = send_whatsapp_message(whatsapp_number, fallback_msg)
                if whatsapp_response.get("status") != "sent":
                    logger.error(f"Failed to send fallback WhatsApp message: {whatsapp_response.get('error', 'Unknown error')}", extra=extra_log)
                return {
                    "status": "Gate pass already valid and resent",
                    "pass_id": existing_pass.pass_id,
                    "expiry_date": existing_pass.expiry_date.isoformat(),
                    "whatsapp_number": whatsapp_number
                }, 200

            return {
                "status": "Gate pass already valid and resent",
                "pass_id": existing_pass.pass_id,
                "expiry_date": existing_pass.expiry_date.isoformat(),
                "whatsapp_number": whatsapp_number
            }, 200

        pass_id = str(uuid.uuid4())
        os.makedirs("/tmp", exist_ok=True)

        first = re.sub(r'\W+', '', (contact.firstname or "First")).strip().capitalize()
        last = re.sub(r'\W+', '', (contact.lastname or "Last")).strip().capitalize()
        student_id_clean = student_id.strip().upper()
        filename = f"gatepass_{student_id_clean}_{first}_{last}.pdf"
        pdf_path = f"/tmp/{filename}"
        qr_path = f"/tmp/qr_{pass_id}.png"

        # Lazy import segno (pure Python, no PIL needed)
        try:
            import segno
        except ImportError:
            logger.error("segno library not available", extra=extra_log)
            return {"error": "PDF generation dependencies not available"}, 500

        qr_url = f"{config.APP_BASE_URL}/verify-gatepass?pass_id={pass_id}&whatsapp_number={whatsapp_number}"
        try:
            # Generate QR code using segno (pure Python, no PIL dependency)
            qr = segno.make(qr_url)
            qr.save(qr_path, scale=10, border=4)
            
            if not os.path.exists(qr_path):
                raise Exception("QR code generation failed")
        except Exception as e:
            logger.error(f"QR code generation failed: {str(e)}", extra=extra_log)
            return {"error": "Failed to generate QR code"}, 500

        # Lazy import fpdf2 only when needed (pure Python, no PIL!)
        try:
            from fpdf import FPDF
        except ImportError as e:
            logger.error(f"fpdf2 library not available: {str(e)}", extra=extra_log)
            return {"error": f"PDF generation dependencies not available: {str(e)}"}, 500

        try:
            # Create PDF with fpdf2
            pdf = FPDF()
            pdf.add_page()
            pdf.set_auto_page_break(auto=True, margin=15)
            
            # Add school logo if exists
            logo_path = "static/school_logo.png"
            if os.path.exists(logo_path):
                pdf.image(logo_path, x=10, y=8, w=50)
                
            # Title
            pdf.set_font('Helvetica', 'B', 16)
            pdf.set_text_color(0, 0, 139)  # Dark blue
            pdf.cell(0, 10, 'SHINING SMILES GROUP OF SCHOOLS', ln=True, align='C')
            pdf.ln(10)
            
            # Info table with background color
            pdf.set_fill_color(250, 250, 210)  # Light goldenrod yellow
            pdf.set_draw_color(128, 128, 128)  # Grey borders
            pdf.set_font('Helvetica', 'B', 12)
            pdf.set_text_color(0, 0, 139)  # Dark blue
            
            # Table data
            table_data = [
                ("Student ID:", str(student_id)),
                ("Name:", f"{contact.firstname or 'N/A'} {contact.lastname or 'N/A'}"),
                ("Pass ID:", str(pass_id)),
                ("Issued:", issued_date.strftime('%Y-%m-%d')),
                ("Expires:", expiry_date.strftime('%Y-%m-%d')),
                ("Payment:", f"{payment_percentage:.1f}%"),
                ("Valid for:", str(whatsapp_number))
            ]
            
            for label, value in table_data:
                pdf.set_font('Helvetica', 'B', 12)
                pdf.cell(60, 10, label, border=1, fill=True)
                pdf.set_font('Helvetica', '', 12)
                pdf.cell(130, 10, value, border=1, fill=True, ln=True)
            
            pdf.ln(10)
            
            # QR Code
            if os.path.exists(qr_path):
                pdf.image(qr_path, x=80, y=pdf.get_y(), w=50, h=50)
                pdf.ln(55)
            
            # Signature if exists
            signature_path = "static/signature.png"
            if os.path.exists(signature_path):
                pdf.ln(5)
                pdf.set_font('Helvetica', '', 12)
                pdf.cell(0, 10, 'Authorized Signature', ln=True)
                pdf.image(signature_path, x=10, y=pdf.get_y(), w=50, h=12)
            else:
                pdf.set_font('Helvetica', '', 12)
                pdf.cell(0, 10, 'Authorized Signature', ln=True)
            
            # Save PDF
            pdf.output(pdf_path)
            
            if not os.path.exists(pdf_path):
                raise Exception("PDF generation failed")
                
        except Exception as e:
            logger.error(f"PDF generation failed: {str(e)}", extra=extra_log)
            return {"error": "Failed to generate PDF"}, 500

        try:
            s3_key = f"gatepasses/{filename}"
            s3.upload_file(pdf_path, bucket_name, s3_key,
                          ExtraArgs={'ContentType': 'application/pdf'})
        except Exception as e:
            logger.error(f"S3 upload failed: {str(e)}", extra=extra_log)
            return {"error": "Failed to upload to S3"}, 500
        finally:
            # Clean up temporary files
            for file_path in [pdf_path, qr_path]:
                if file_path and os.path.exists(file_path):
                    try:
                        os.remove(file_path)
                        logger.debug(f"Cleaned up temporary file: {file_path}", extra=extra_log)
                    except Exception as e:
                        logger.warning(f"Failed to delete temporary file {file_path}: {str(e)}", extra=extra_log)

        gate_pass = GatePass(
            student_id=student_id,
            pass_id=pass_id,
            issued_date=issued_date,
            expiry_date=expiry_date,
            payment_percentage=int(payment_percentage),
            whatsapp_number=whatsapp_number,
            last_updated=issued_date,
            pdf_path=s3_key,
            qr_path=None
        )
        session.add(gate_pass)
        session.commit()

        expiry_seconds = 3600
        presigned_url = s3.generate_presigned_url(
            'get_object',
            Params={'Bucket': bucket_name, 'Key': s3_key},
            ExpiresIn=expiry_seconds
        )

        try:
            check = requests.get(presigned_url, stream=True, timeout=5)
            if check.status_code != 200:
                raise Exception(f"Pre-signed URL inaccessible: status={check.status_code}")

            message = (
                f"Dear {contact.firstname or 'Parent'} {contact.lastname or 'Guardian'},\n"
                f"Your gate pass for {student_id} is attached.\n"
                f"Pass ID: {pass_id}\n"
                f"Expires: {expiry_date.strftime('%Y-%m-%d')}\n"
                f"This pass is valid only for {whatsapp_number}. Do not share."
            )
            whatsapp_response = send_whatsapp_message(whatsapp_number, message, media_url=[presigned_url])
            if whatsapp_response.get("status") != "sent":
                raise Exception(f"WhatsApp message failed: {whatsapp_response.get('error', 'Unknown error')}")
            logger.info(f"Gate pass PDF sent to {whatsapp_number}", extra=extra_log)
        except Exception as e:
            logger.error(f"Failed to send WhatsApp PDF to {whatsapp_number}: {str(e)}", extra=extra_log)
            text_message = (
                f"Dear {contact.firstname or 'Parent'} {contact.lastname or 'Guardian'},\n"
                f"Gate Pass for {student_id}:\n"
                f"Pass ID: {pass_id}\n"
                f"Issued: {issued_date.strftime('%Y-%m-%d')}\n"
                f"Expires: {expiry_date.strftime('%Y-%m-%d')}\n"
                f"Payment: {payment_percentage:.1f}%\n"
                f"This pass is valid only for {whatsapp_number}. Do not share.\n"
                f"Please contact support@shiningsmiles.com if you don't receive the PDF."
            )
            whatsapp_response = send_whatsapp_message(whatsapp_number, text_message)
            if whatsapp_response.get("status") != "sent":
                logger.error(f"Failed to send fallback WhatsApp message: {whatsapp_response.get('error', 'Unknown error')}", extra=extra_log)
            return {
                "status": "Gate pass issued (text fallback)",
                "pass_id": pass_id,
                "expiry_date": expiry_date.isoformat(),
                "whatsapp_number": whatsapp_number
            }, 200

        return {
            "status": "Gate pass issued",
            "pass_id": pass_id,
            "expiry_date": expiry_date.isoformat(),
            "whatsapp_number": whatsapp_number
        }, 200

    except Exception as e:
        logger.error(f"Error in generate_gatepass: {str(e)}\n{traceback.format_exc()}", extra=extra_log)
        return {"error": f"Internal server error: {str(e)}"}, 500
    finally:
        session.remove()

def verify_gatepass(pass_id, incoming_number):
    session = init_db()
    extra_log = {"pass_id": pass_id, "incoming_number": incoming_number}
    try:
        if not pass_id or not incoming_number:
            logger.error("Missing pass_id or whatsapp_number", extra=extra_log)
            if request.accept_mimetypes.accept_json:
                return {"error": "Missing pass ID or WhatsApp number"}, 400
            else:
                return render_template("error.html", message="Missing pass ID or WhatsApp number"), 400

        gate_pass = session.query(GatePass).filter_by(pass_id=pass_id).first()
        if not gate_pass:
            logger.error(f"Gate pass ID not found: {pass_id}", extra=extra_log)
            if request.accept_mimetypes.accept_json:
                return {"error": "Gate pass not found"}, 404
            else:
                return render_template("error.html", message="Gate pass not found"), 404
        
        expiry = gate_pass.expiry_date
        if expiry.tzinfo is None:
            expiry = expiry.replace(tzinfo=timezone.utc)

        if expiry < datetime.now(timezone.utc):
            logger.error(f"Gate pass {pass_id} expired on {expiry}", extra=extra_log)
            if request.accept_mimetypes.accept_json:
                return {"error": "Gate pass expired"}, 410
            else:
                return render_template("error.html", message="Gate pass expired"), 410

        student = session.query(StudentContact).filter_by(student_id=gate_pass.student_id).first()
        student_name = f"{student.firstname or ''} {student.lastname or ''}".strip() if student else "Unknown"

        scan = GatePassScan(
            pass_id=pass_id,
            scanned_at=datetime.now(timezone.utc),
            scanned_by_number=incoming_number,
            matched_registered_number=(gate_pass.whatsapp_number == incoming_number)
        )
        session.add(scan)
        session.commit()

        warning = None
        if gate_pass.whatsapp_number != incoming_number:
            logger.warning(f"Gate pass {pass_id} accessed by unregistered number {incoming_number}", extra=extra_log)
            warning = "This gate pass is not valid for your phone number."

        if request.accept_mimetypes.accept_json:
            return {
                "status": "valid",
                "student_id": gate_pass.student_id,
                "student_name": student_name,
                "issued_date": gate_pass.issued_date.strftime("%Y-%m-%d"),
                "expiry_date": expiry.strftime("%Y-%m-%d"),
                "registered_number": gate_pass.whatsapp_number,
                "accessing_number": incoming_number,
                "warning": warning
            }, 200
        else:
            return render_template(
                "verify_gatepass.html",
                status="valid",
                student_id=gate_pass.student_id,
                student_name=student_name,
                issued_date=gate_pass.issued_date.strftime("%Y-%m-%d"),
                expiry_date=expiry.strftime("%Y-%m-%d"),
                registered_number=gate_pass.whatsapp_number,
                accessing_number=incoming_number,
                warning=warning
            ), 200

    except Exception as e:
        logger.error(f"Error verifying gate pass: {str(e)}\n{traceback.format_exc()}", extra=extra_log)
        if request.accept_mimetypes.accept_json:
            return {"error": f"Internal Server Error: {str(e)}"}, 500
        return render_template("error.html", message=f"Internal Server Error: {str(e)}"), 500
    finally:
        session.remove()

def handle_message_status(message_sid, message_status):
    logger.info(f"Received message status update - SID: {message_sid}, Status: {message_status}")
    return {"status": "received", "message_sid": message_sid, "message_status": message_status}, 200