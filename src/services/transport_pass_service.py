import os
import re
import uuid
import boto3
from botocore.client import Config
from datetime import datetime, timezone, timedelta
import requests
import traceback

try:
    from flask import render_template, request, jsonify
except ImportError:
    render_template = None
    request = None
    jsonify = None

from utils.database import init_db, StudentContact, TransportPass, TransportPassRequestLog, get_student_contact, resolve_school_id, school_scoped_query
from utils.whatsapp import send_whatsapp_message
from utils.logger import setup_logger
from api.sms_client import SMSClient
from config import get_config, make_s3_client, Config as AppConfig

logger = setup_logger(__name__)
config = get_config()

# Object storage client (AWS S3, or Cloudflare R2 when S3_ENDPOINT_URL is set)
s3 = make_s3_client()
bucket_name = AppConfig.TRANSPORT_S3_BUCKET

def check_and_update_transport_rate_limit(session, student_id, extra_log, school_id=None):
    """
    Check and update the weekly rate limit for transport pass requests.
    Returns a tuple: (request_count, tier)
    - request_count: Current number of requests this week (before incrementing)
    - tier: 'pdf' (1-3), 'text' (4-5), or 'block' (6+)
    """
    now = datetime.now(timezone.utc)
    # Get Monday of the current week
    week_start = (now - timedelta(days=now.weekday())).replace(hour=0, minute=0, second=0, microsecond=0)
    
    # Find or create log entry for this student+week
    school_id = resolve_school_id(school_id)
    log_entry = school_scoped_query(session, TransportPassRequestLog, school_id).filter(
        TransportPassRequestLog.student_id == student_id,
        TransportPassRequestLog.week_start_date == week_start
    ).first()
    
    if not log_entry:
        log_entry = TransportPassRequestLog(
            school_id=school_id,
            student_id=student_id,
            week_start_date=week_start,
            request_count=1,
            last_request_date=now
        )
        session.add(log_entry)
        session.commit()
        logger.info(f"Created new transport rate limit log for {student_id}, week {week_start.date()}", extra=extra_log)
        return 1, 'pdf'
    
    current_count = log_entry.request_count
    
    # Determine tier before incrementing
    if current_count < 3:
        tier = 'pdf'
    elif current_count < 5:
        tier = 'text'
    else:
        tier = 'block'
    
    # Increment counter
    log_entry.request_count += 1
    log_entry.last_request_date = now
    session.commit()
    
    logger.info(f"Transport rate limit check for {student_id}: {current_count + 1} requests this week, tier={tier}", extra=extra_log)
    
    return current_count + 1, tier

def parse_and_validate_transport_fee(fee_type, amount):
    """
    Parse transport fee type and validate payment amount.
    Returns: (route_type, service_type, is_fully_paid, expected_amount) or None if invalid
    """
    # Normalize fee type
    fee_type_normalized = fee_type.lower()
    
    # Extract route and service
    if "hatfield" in fee_type_normalized or "local" in fee_type_normalized:
        route_type = "local"
    elif "chitungwiza" in fee_type_normalized:
        route_type = "chitungwiza"
    elif "cbd" in fee_type_normalized:
        route_type = "cbd"
    else:
        return None  # Unknown route
    
    # Extract service type - first try explicit indicators
    service_type = None
    if "2 way" in fee_type_normalized or "two way" in fee_type_normalized:
        service_type = "2_way"
    elif "1 way" in fee_type_normalized or "one way" in fee_type_normalized:
        service_type = "1_way"
    elif route_type == "cbd":
        service_type = "either_way"
    
    # Fallback: Use amount to determine service type if not explicitly mentioned
    if service_type is None:
        # Get all possible service types for this route
        route_config = AppConfig.TRANSPORT_ROUTES.get(route_type, {})
        
        # Try to match amount to a service type (with small tolerance for rounding)
        for svc_type, svc_config in route_config.items():
            if abs(amount - svc_config["price"]) < 0.01:
                service_type = svc_type
                break
        
        # If still no match, default to 2_way for local/chitungwiza
        if service_type is None:
            if route_type in ["local", "chitungwiza"]:
                service_type = "2_way"  # Default assumption
            else:
                return None  # Unknown service for CBD (should not happen)
    
    # Get expected amount
    expected_amount = AppConfig.TRANSPORT_ROUTES[route_type][service_type]["price"]
    
    # Validate payment (allow small tolerance for rounding)
    is_fully_paid = amount >= (expected_amount - 0.01)
    
    return (route_type, service_type, is_fully_paid, expected_amount)


def generate_transport_pass(student_id, term, route_type, service_type, amount_paid, 
                            request_id, whatsapp_number=None, skip_whatsapp=False):
    """
    Generate a transport pass for a student.
    
    Args:
        student_id: Student ID (e.g., SSC20246303)
        term: Term code (e.g., "2026-1")
        route_type: Route type ("local", "chitungwiza", "cbd")
        service_type: Service type ("2_way", "1_way", "either_way")
        amount_paid: Amount paid for transport
        request_id: Unique request ID for logging
        whatsapp_number: WhatsApp number to send pass to
        skip_whatsapp: If True, generates pass but doesn't send via WhatsApp
        
    Returns:
        (result_dict, status_code)
    """
    session = init_db()
    school_id = resolve_school_id()
    extra_log = {"request_id": request_id, "student_id": student_id, "route": route_type, "service": service_type, "school_id": school_id}
    
    try:
        # Validate inputs
        if not student_id or not term or not route_type or not service_type:
            logger.error("Missing required parameters", extra=extra_log)
            return {"error": "Missing required parameters"}, 400
        
        # Validate payment amount
        try:
            expected_price = AppConfig.TRANSPORT_ROUTES[route_type][service_type]["price"]
        except KeyError:
            logger.error(f"Invalid route/service combination: {route_type}/{service_type}", extra=extra_log)
            return {"error": f"Invalid transport route or service type"}, 400
        
        if amount_paid < expected_price:
            logger.warning(f"Partial payment detected: {amount_paid} of {expected_price}", extra=extra_log)
            return {
                "error": "Partial payment",
                "paid": amount_paid,
                "required": expected_price,
                "outstanding": expected_price - amount_paid
            }, 402  # Payment Required
        
        # Get student contact
        contact = get_student_contact(session, student_id, school_id=school_id)
        if not contact:
            logger.error(f"Student {student_id} not found in database", extra=extra_log)
            return {"error": "Student not found"}, 404
        
        # Determine WhatsApp number
        if not whatsapp_number:
            whatsapp_number = contact.preferred_phone_number or contact.student_mobile
        
        if not whatsapp_number and not skip_whatsapp:
            logger.error(f"No valid WhatsApp number for {student_id}", extra=extra_log)
            return {"error": "No valid WhatsApp number found for this student"}, 400
        
        # Check rate limit (only for WhatsApp requests, not admin-generated)
        if not skip_whatsapp:
            request_count, tier = check_and_update_transport_rate_limit(session, student_id, extra_log, school_id=school_id)
            
            if tier == 'block':
                logger.warning(f"Rate limit exceeded for {student_id}: {request_count} requests this week", extra=extra_log)
                return {
                    "status": "Rate limit exceeded",
                    "message": "You have reached the weekly limit for transport pass requests. Please use the pass sent previously or contact admin@shiningsmilescollege.ac.zw if you need assistance."
                }, 429
        else:
            # For admin requests, use None tier to always send PDF
            tier = None
        
        # Check if transport pass already exists for this term and route
        existing_pass = school_scoped_query(session, TransportPass, school_id).filter(
            TransportPass.student_id == student_id,
            TransportPass.term == term,
            TransportPass.route_type == route_type,
            TransportPass.service_type == service_type,
            TransportPass.status == 'active'
        ).first()
        
        if existing_pass:
            logger.info(f"Existing transport pass found for {student_id} - {route_type}/{service_type}", extra=extra_log)
            
            # Resend existing pass
            if not skip_whatsapp and existing_pass.pdf_path:
                try:
                    route_display = route_type.capitalize()
                    service_display = service_type.replace("_", " ").title()
                    
                    # Tier 2: Send text-only (no PDF) to save bandwidth
                    if tier == 'text':
                        logger.info(f"Tier 2: Sending text-only transport pass details for {student_id}", extra=extra_log)
                        message = (
                            f"Dear {contact.firstname or 'Parent'} {contact.lastname or 'Guardian'},\n"
                            f"You already have a valid transport pass.\n\n"
                            f"📋 *Pass Details:*\n"
                            f"Route: {route_display} - {service_display}\n"
                            f"Valid until: {existing_pass.expiry_date.strftime('%Y-%m-%d')}\n\n"
                            f"⚠️ *Note:* You've requested this pass multiple times this week. To save data, we're sending details only.\n"
                            f"The PDF was sent with your previous request. If you need the PDF again, contact admin@shiningsmilescollege.ac.zw."
                        )
                        send_whatsapp_message(whatsapp_number, message)
                        return {
                            "status": "Transport pass valid (text-only sent)",
                            "pass_id": existing_pass.pass_id,
                            "expiry_date": existing_pass.expiry_date.isoformat(),
                            "whatsapp_number": whatsapp_number,
                            "tier": "text"
                        }, 200
                    
                    # Tier 1: Send PDF as usual
                    expiry_seconds = 3600
                    presigned_url = s3.generate_presigned_url(
                        'get_object',
                        Params={'Bucket': bucket_name, 'Key': existing_pass.pdf_path},
                        ExpiresIn=expiry_seconds
                    )
                    
                    message = (
                        f"Dear {contact.firstname or 'Parent'} {contact.lastname or 'Guardian'},\n"
                        f"You already have a valid transport pass.\n\n"
                        f"Route: {route_display} - {service_display}\n"
                        f"Valid until: {existing_pass.expiry_date.strftime('%Y-%m-%d')}\n"
                        f"This pass is valid only for {whatsapp_number}."
                    )
                    
                    send_whatsapp_message(whatsapp_number, message, media_url=presigned_url, filename=os.path.basename(existing_pass.pdf_path))
                    logger.info(f"Resent existing transport pass to {whatsapp_number}", extra=extra_log)
                except Exception as e:
                    logger.error(f"Failed to resend transport pass: {str(e)}", extra=extra_log)
            
            return {
                "status": "Transport pass already exists",
                "pass_id": existing_pass.pass_id,
                "expiry_date": existing_pass.expiry_date.isoformat(),
                "whatsapp_number": whatsapp_number
            }, 200
        
        # Generate new pass
        pass_id = str(uuid.uuid4())
        issued_date = datetime.now(timezone.utc)
        
        # Transport passes are valid until end of term
        try:
            expiry_date = AppConfig.term_end_date(term)
        except ValueError as e:
            logger.error(f"Invalid term: {term}", extra=extra_log)
            return {"error": f"Invalid term: {term}"}, 400
        
        # Generate PDF
        os.makedirs("/tmp", exist_ok=True)
        
        first = re.sub(r'\\W+', '', (contact.firstname or "First")).strip().capitalize()
        last = re.sub(r'\\W+', '', (contact.lastname or "Last")).strip().capitalize()
        student_id_clean = student_id.strip().upper()
        
        route_display = route_type.capitalize()
        service_display = service_type.replace("_", " ").title()
        filename = f"transportpass_{student_id_clean}_{first}_{last}.pdf"
        pdf_path = f"/tmp/{filename}"
        qr_path = f"/tmp/qr_{pass_id}.png"
        
        # Generate QR code
        try:
            import segno
            qr_url = f"{config.APP_BASE_URL}/verify-transport-pass?pass_id={pass_id}&whatsapp_number={whatsapp_number}"
            qr = segno.make(qr_url)
            qr.save(qr_path, scale=10, border=4)
            
            if not os.path.exists(qr_path):
                raise Exception("QR code generation failed")
        except Exception as e:
            logger.error(f"QR code generation failed: {str(e)}", extra=extra_log)
            return {"error": "Failed to generate QR code"}, 500
        
        # Generate PDF
        try:
            from fpdf import FPDF
            
            pdf = FPDF()
            pdf.add_page()
            pdf.set_auto_page_break(auto=True, margin=15)
            
            # Header
            logo_path = "static/school_logo.png"
            if os.path.exists(logo_path):
                pdf.image(logo_path, x=85, y=10, w=40)
            
            pdf.set_y(55)
            
            # Title
            pdf.set_font('Helvetica', 'B', 18)
            pdf.set_text_color(0, 0, 139)
            pdf.cell(0, 10, 'SHINING SMILES GROUP OF SCHOOLS', ln=True, align='C')
            
            pdf.set_font('Helvetica', 'B', 14)
            pdf.set_text_color(34, 139, 34)  # Green for transport
            pdf.cell(0, 10, 'TRANSPORT PASS', ln=True, align='C')
            
            pdf.ln(10)
            
            # Table
            pdf.set_fill_color(240, 255, 240)  # Light green
            pdf.set_draw_color(100, 100, 100)
            
            table_data = [
                ("Student ID", str(student_id)),
                ("Student Name", f"{contact.firstname or 'N/A'} {contact.lastname or 'N/A'}"),
                ("Pass ID", str(pass_id)),
                ("Route", f"{route_display} - {service_display}"),
                ("Amount Paid", f"${amount_paid:.2f}"),
                ("Term", term),
                ("Issued Date", issued_date.strftime('%Y-%m-%d')),
                ("Valid Until", expiry_date.strftime('%Y-%m-%d')),
                ("Authorized Number", str(whatsapp_number) if whatsapp_number else "N/A")
            ]
            
            for label, value in table_data:
                pdf.set_font('Helvetica', 'B', 11)
                pdf.set_text_color(50, 50, 50)
                pdf.cell(60, 12, f"  {label}", border=1, fill=True)
                
                pdf.set_font('Helvetica', '', 11)
                pdf.set_text_color(0, 0, 0)
                pdf.cell(130, 12, f"  {value}", border=1, fill=False, ln=True)
            
            pdf.ln(15)
            
            # Footer with signature and QR
            y_position = pdf.get_y()
            
            signature_path = "static/signature.png"
            if os.path.exists(signature_path):
                pdf.set_font('Helvetica', 'I', 10)
                pdf.text(20, y_position - 2, "Authorized Signature:")
                pdf.image(signature_path, x=20, y=y_position, w=50)
                pdf.line(20, y_position + 15, 70, y_position + 15)
            
            if os.path.exists(qr_path):
                pdf.image(qr_path, x=140, y=y_position - 5, w=45, h=45)
                pdf.set_font('Helvetica', '', 8)
                pdf.text(145, y_position + 42, "Scan to Verify")
            
            pdf.output(pdf_path)
            
            if not os.path.exists(pdf_path):
                raise Exception("PDF generation failed")
                
        except Exception as e:
            logger.error(f"PDF generation failed: {str(e)}", extra=extra_log)
            return {"error": "Failed to generate PDF"}, 500
        
        # Upload to S3
        try:
            s3_key = f"transport_passes/{filename}"
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
                    except Exception as e:
                        logger.warning(f"Failed to delete temp file {file_path}: {str(e)}", extra=extra_log)
        
        # Save to database
        transport_pass = TransportPass(
            school_id=school_id,
            pass_id=pass_id,
            student_id=student_id,
            term=term,
            route_type=route_type,
            service_type=service_type,
            amount_paid=amount_paid,
            issued_date=issued_date,
            expiry_date=expiry_date,
            whatsapp_number=whatsapp_number or "ADMIN_GENERATED",
            pdf_path=s3_key,
            qr_path=None,
            status='active'
        )
        session.add(transport_pass)
        session.commit()
        
        logger.info(f"Transport pass generated: {pass_id}", extra=extra_log)
        
        # Send via WhatsApp
        if not skip_whatsapp and whatsapp_number:
            try:
                expiry_seconds = 3600
                presigned_url = s3.generate_presigned_url(
                    'get_object',
                    Params={'Bucket': bucket_name, 'Key': s3_key},
                    ExpiresIn=expiry_seconds
                )
                
                message = (
                    f"Dear {contact.firstname or 'Parent'} {contact.lastname or 'Guardian'},\n"
                    f"Your transport pass for {student_id} is attached.\n\n"
                    f"Route: {route_display} - {service_display}\n"
                    f"Pass ID: {pass_id}\n"
                    f"Valid until: {expiry_date.strftime('%Y-%m-%d')}\n\n"
                    f"This pass is valid only for {whatsapp_number}."
                )
                
                whatsapp_response = send_whatsapp_message(whatsapp_number, message, media_url=presigned_url, filename=os.path.basename(s3_key))
                if whatsapp_response.get("status") != "sent":
                    logger.error(f"Failed to send WhatsApp message: {whatsapp_response.get('error')}", extra=extra_log)
                else:
                    logger.info(f"Transport pass sent to {whatsapp_number}", extra=extra_log)
                    
            except Exception as e:
                logger.error(f"Failed to send transport pass: {str(e)}", extra=extra_log)
        
        return {
            "status": "Transport pass issued",
            "pass_id": pass_id,
            "route": f"{route_display} - {service_display}",
            "expiry_date": expiry_date.isoformat(),
            "whatsapp_number": whatsapp_number,
            "amount_paid": amount_paid
        }, 200
        
    except Exception as e:
        logger.error(f"Error in generate_transport_pass: {str(e)}\\n{traceback.format_exc()}", extra=extra_log)
        return {"error": f"Internal server error: {str(e)}"}, 500
    finally:
        session.remove()


def verify_transport_pass(pass_id, whatsapp_number, return_json=True):
    """
    Verify a transport pass by pass ID and WhatsApp number.
    """
    session = init_db()
    extra_log = {"pass_id": pass_id, "whatsapp_number": whatsapp_number}
    
    try:
        if not pass_id or not whatsapp_number:
            logger.error("Missing pass_id or whatsapp_number", extra=extra_log)
            return {"error": "Missing pass ID or WhatsApp number"}, 400
        
        school_id = resolve_school_id()
        transport_pass = school_scoped_query(session, TransportPass, school_id).filter_by(pass_id=pass_id).first()
        if not transport_pass:
            logger.error(f"Transport pass not found: {pass_id}", extra=extra_log)
            return {"error": "Transport pass not found"}, 404
        
        # Check if expired
        expiry = transport_pass.expiry_date
        if expiry.tzinfo is None:
            expiry = expiry.replace(tzinfo=timezone.utc)
        
        if expiry < datetime.now(timezone.utc):
            logger.error(f"Transport pass {pass_id} expired on {expiry}", extra=extra_log)
            return {"error": "Transport pass expired"}, 410
        
        # Check if revoked
        if transport_pass.status != 'active':
            logger.error(f"Transport pass {pass_id} has status: {transport_pass.status}", extra=extra_log)
            return {"error": f"Transport pass is {transport_pass.status}"}, 403
        
        # Get student info
        student = get_student_contact(session, transport_pass.student_id, school_id=school_id)
        student_name = f"{student.firstname or ''} {student.lastname or ''}".strip() if student else "Unknown"
        
        # Check number match
        warning = None
        if transport_pass.whatsapp_number != whatsapp_number:
            logger.warning(f"Transport pass {pass_id} accessed by unregistered number {whatsapp_number}", extra=extra_log)
            warning = "This transport pass is not valid for your phone number."
        
        route_display = transport_pass.route_type.capitalize()
        service_display = transport_pass.service_type.replace("_", " ").title()
        
        return {
            "status": "valid",
            "student_id": transport_pass.student_id,
            "student_name": student_name,
            "route": f"{route_display} - {service_display}",
            "amount_paid": transport_pass.amount_paid,
            "issued_date": transport_pass.issued_date.strftime("%Y-%m-%d"),
            "expiry_date": expiry.strftime("%Y-%m-%d"),
            "registered_number": transport_pass.whatsapp_number,
            "accessing_number": whatsapp_number,
            "warning": warning
        }, 200
        
    except Exception as e:
        logger.error(f"Error verifying transport pass: {str(e)}\\n{traceback.format_exc()}", extra=extra_log)
        return {"error": f"Internal server error: {str(e)}"}, 500
    finally:
        session.remove()


def get_student_transport_passes(student_id, term):
    """
    Get all transport passes for a student for a given term.
    Returns list of passes.
    """
    session = init_db()
    try:
        school_id = resolve_school_id()
        passes = school_scoped_query(session, TransportPass, school_id).filter(
            TransportPass.student_id == student_id,
            TransportPass.term == term,
            TransportPass.status == 'active'
        ).all()
        
        return passes
    except Exception as e:
        logger.error(f"Error fetching transport passes for {student_id}: {str(e)}")
        return []
    finally:
        session.remove()
