import os
import uuid
import boto3
from botocore.client import Config
from datetime import datetime, timezone, timedelta
import requests
import traceback

from utils.database import init_db, StudentContact, Invoice
from utils.whatsapp import send_whatsapp_message
from utils.logger import setup_logger
from api.sms_client import SMSClient
from config import get_config

logger = setup_logger(__name__)
config = get_config()

# AWS S3 client
s3 = boto3.client(
    's3',
    region_name='us-east-2',
    config=Config(signature_version='s3v4')
)
bucket_name = 'shining-smiles-invoices'

# School contact information
SCHOOL_INFO = {
    "name": "SHINING SMILES GROUP OF SCHOOLS",
    "email_info": "info@shiningsmilescollege.ac.zw",
    "email_admin": "admin@shiningsmilescollege.ac.zw",
    "tel": "0712222022",
    "bank_name": "FIRST CAPITAL BANK",
    "account_name": "SHINING SMILES GROUP OF SCHOOLS",
    "account_number": "19903853786",
    "currency": "USD"
}

# Branch addresses with school names
BRANCH_ADDRESSES = {
    "Hatfield Pre School": "39 Winson Road, Hatfield, Harare",  # Admin Office
    "Hatfield High School": "14 Alexandra Drive, Hatfield, Harare",  # Branch 1
    "Ziko": "1 Mudimu Village, Ziko, Chitungwiza",  # Branch 2
    "Ziko High School": "1 Mudimu Village, Ziko, Chitungwiza",  # Branch 2
    "Kilwinning": "142 Kilwinning Road, Hatfield, Harare",  # Branch 3
    "Alexandra": "50 Alexandra Drive, Hatfield, Harare",  # Branch 4
    "default": "39 Winson Road, Hatfield, Harare"  # Default to admin office
}


def is_hot_meals_mandatory(grade):
    """
    Determine if hot meals are mandatory based on student grade level.
    
    Args:
        grade (str): Student's grade level (e.g., "ECD A", "Grade 3", "Form 2")
    
    Returns:
        bool: True if hot meals are mandatory (ECD classes), False otherwise
    """
    if not grade:
        return False
    
    ecd_indicators = ["ECD", "RECEPTION", "KINDERGARTEN", "PRE-SCHOOL", "PRE SCHOOL"]
    
    # Normalize grade (case-insensitive)
    normalized_grade = grade.upper().strip()
    
    # Check if it's an ECD grade
    for indicator in ecd_indicators:
        if indicator in normalized_grade:
            return True
    
    return False


def generate_invoice_number(student_id, term, sequence=1):
    """
    Generate a unique invoice number.
    
    Format: INV-{TERM}-{STUDENT_ID}-{SEQUENCE}
    Example: INV-2026-1-SSC001-001
    
    Args:
        student_id (str): Student ID (e.g., "SSC001")
        term (str): Term code (e.g., "2026-1")
        sequence (int): Sequence number for this student/term combo
    
    Returns:
        str: Formatted invoice number
    """
    return f"INV-{term}-{student_id}-{sequence:03d}"


def get_invoice_line_items(student_id, term, sms_client, extra_log):
    """
    Fetch and categorize fee items for the invoice.
    
    Args:
        student_id (str): Student ID
        term (str): Term code
        sms_client (SMSClient): API client instance
        extra_log (dict): Logging context
    
    Returns:
        dict: Contains 'items' (list of line items), 'student_profile', and 'total_amount'
    """
    try:
        # Fetch data from School SMS API
        account_statement = sms_client.get_student_account_statement(student_id, term)
        billed_fees = sms_client.get_student_billed_fees(student_id, term)
        
        # Extract student info from account statement
        data = account_statement.get("data", {})
        raw_student_name = data.get("student_name", "Unknown")
        
        # Remove ID prefix from student name (e.g., "[SSC20246303] THANDO MUJENI" -> "THANDO MUJENI")
        import re
        student_name = re.sub(r'^\[\w+\]\s*', '', raw_student_name)
        
        grade = data.get("current_grade", "Unknown")
        
        # Parse billed fees
        fees_list = billed_fees.get("data", {}).get("bills", [])
        items = []
        total_amount = 0.0
        
        # Tuition - always mandatory
        tuition_fees = [f for f in fees_list if 'tuition' in f.get('fee_type', '').lower() or 'school fee' in f.get('fee_type', '').lower()]
        if tuition_fees:
            amount = float(tuition_fees[0]['amount'])
            items.append({
                "description": f"Tuition Fee - Term {term} ({grade})",
                "amount": amount,
                "mandatory": True,
                "qty": 1
            })
            total_amount += amount
        
        # Hot Meals - mandatory for ECD, optional for others
        hot_meals_fees = [f for f in fees_list if 'meal' in f.get('fee_type', '').lower() or 'hot meal' in f.get('fee_type', '').lower()]
        if hot_meals_fees:
            amount = float(hot_meals_fees[0]['amount'])
            mandatory = is_hot_meals_mandatory(grade)
            items.append({
                "description": "Hot Meals" + (" (Mandatory - ECD)" if mandatory else " (Optional)"),
                "amount": amount,
                "mandatory": mandatory,
                "qty": 1
            })
            total_amount += amount
        
        # Transport - always optional
        transport_fees = [f for f in fees_list if 'transport' in f.get('fee_type', '').lower()]
        if transport_fees:
            amount = float(transport_fees[0]['amount'])
            items.append({
                "description": "Transport Service (Optional)",
                "amount": amount,
                "mandatory": False,
                "qty": 1
            })
            total_amount += amount
        
        return {
            "student_profile": {
                "name": student_name,
                "student_id": student_id,
                "grade": grade
            },
            "items": items,
            "total_amount": total_amount
        }
    
    except Exception as e:
        logger.error(f"Error fetching invoice line items for {student_id}: {str(e)}", extra=extra_log)
        raise


def create_digital_stamp(pdf, x, y, issue_date):
    """
    Create a digital stamp that looks like a traditional ink stamp.
    Smaller rectangular stamp with authorization text and contact info.
    
    Args:
        pdf: FPDF object
        x: X position
        y: Y position
        issue_date: Date string for stamp
    """
    # Set stamp color (dark red/burgundy like traditional stamps)
    pdf.set_draw_color(139, 0, 0)  # Dark red
    pdf.set_text_color(139, 0, 0)
    
    # Rotate the entire stamp by -15 degrees for realistic look
    with pdf.rotation(angle=-15, x=x+25, y=y+17.5):
        # Draw multiple rectangles with slight variations for ink texture effect
        # Outer border (thicker) - SMALLER SIZE: 50x35
        pdf.set_line_width(0.7)
        pdf.rect(x, y, 50, 35, style='D')
        
        # Inner border for double-line effect
        pdf.set_line_width(0.35)
        pdf.rect(x+1.5, y+1.5, 47, 32, style='D')
        
        # Add small corner decorations
        pdf.set_line_width(0.25)
        corner_size = 2
        # Top-left
        pdf.line(x+3, y+3, x+3+corner_size, y+3)
        pdf.line(x+3, y+3, x+3, y+3+corner_size)
        # Top-right
        pdf.line(x+47-corner_size, y+3, x+47, y+3)
        pdf.line(x+47, y+3, x+47, y+3+corner_size)
        # Bottom-left
        pdf.line(x+3, y+32-corner_size, x+3, y+32)
        pdf.line(x+3, y+32, x+3+corner_size, y+32)
        # Bottom-right
        pdf.line(x+47, y+32-corner_size, x+47, y+32)
        pdf.line(x+47-corner_size, y+32, x+47, y+32)
        
        # Reset line width for text
        pdf.set_line_width(0.2)
        
        # Content - more compact
        pdf.set_font('Helvetica', 'B', 7)
        pdf.set_xy(x + 5, y + 4)
        pdf.cell(40, 3, "SHINING SMILES COLLEGE", 0, 0, 'C')
        
        # Separator
        pdf.set_line_width(0.25)
        pdf.line(x+8, y+8, x+42, y+8)
        
        # Date
        pdf.set_font('Helvetica', 'B', 8)
        pdf.set_xy(x + 5, y + 9.5)
        pdf.cell(40, 3, issue_date, 0, 0, 'C')
        
        # Separator
        pdf.line(x+8, y+13.5, x+42, y+13.5)
        
        # Authorization text
        pdf.set_font('Helvetica', '', 5)
        pdf.set_xy(x + 5, y + 15)
        pdf.cell(40, 2, "THIS IS AN AUTHORIZED", 0, 0, 'C')
        pdf.set_xy(x + 5, y + 17.5)
        pdf.cell(40, 2, "DIGITAL STAMP", 0, 0, 'C')
        
        # Separator
        pdf.line(x+8, y+21, x+42, y+21)
        
        # Contact info - more compact
        pdf.set_font('Helvetica', '', 4.5)
        pdf.set_xy(x + 5, y + 22)
        pdf.cell(40, 2, "info@shiningsmilescollege.ac.zw", 0, 0, 'C')
        
        pdf.set_xy(x + 5, y + 24.5)
        pdf.cell(40, 2, "Tel: 0712222022", 0, 0, 'C')
        
        pdf.set_font('Helvetica', 'B', 5)
        pdf.set_xy(x + 5, y + 27.5)
        pdf.cell(40, 2, "ADMIN OFFICE - HARARE", 0, 0, 'C')
    
    # Reset colors and line width
    pdf.set_draw_color(0, 0, 0)
    pdf.set_text_color(0, 0, 0)
    pdf.set_line_width(0.2)


def create_invoice_pdf(invoice_data, output_path, extra_log):
    """
    Generate a professional PDF invoice using fpdf2 library.
    
    Args:
        invoice_data (dict): Invoice details
        output_path (str): Local file path to save PDF
        extra_log (dict): Logging context
    
    Returns:
        str: Path to generated PDF file
    """
    try:
        from fpdf import FPDF
    except ImportError as e:
        logger.error(f"fpdf2 library not available: {str(e)}", extra=extra_log)
        raise Exception("PDF generation dependencies not available")
    
    try:
        pdf = FPDF()
        pdf.add_page()
        pdf.set_auto_page_break(auto=True, margin=15)
        
        # --- HEADER SECTION ---
        # School Logo (Top Left) - use same path as gatepasses
        logo_path = "static/school_logo.png"
        logo_exists = os.path.exists(logo_path)
        
        if logo_exists:
            pdf.image(logo_path, x=10, y=10, w=30)
            header_x = 50
        else:
            # If no logo, start header from left
            header_x = 10
        
        # School Name and Address
        pdf.set_xy(header_x, 10)
        pdf.set_font('Helvetica', 'B', 16)
        pdf.set_text_color(0, 0, 139)  # Dark blue
        pdf.cell(0, 6, SCHOOL_INFO["name"], ln=True)
        
        pdf.set_xy(header_x, 18)
        pdf.set_font('Helvetica', '', 9)
        pdf.set_text_color(0, 0, 0)
        pdf.cell(0, 5, invoice_data.get("branch_address", BRANCH_ADDRESSES["default"]), ln=True)
        
        pdf.set_xy(header_x, 23)
        pdf.cell(0, 5, f"Email: {SCHOOL_INFO['email_info']} | {SCHOOL_INFO['email_admin']}", ln=True)
        
        pdf.set_xy(header_x, 28)
        pdf.cell(0, 5, f"Tel: {SCHOOL_INFO['tel']}", ln=True)
        
        pdf.ln(20)
        
        # --- INVOICE TITLE ---
        pdf.set_font('Helvetica', 'B', 18)
        pdf.set_text_color(0, 0, 0)
        pdf.cell(0, 10, 'STUDENT FEES INVOICE', ln=True, align='C')
        pdf.ln(5)
        
        # --- INVOICE DETAILS (Two Columns) - Make key fields bold and visible ---
        y_start = pdf.get_y()
        
        # Left column - Invoice Number (BOLD)
        pdf.set_xy(10, y_start)
        pdf.set_font('Helvetica', 'B', 11)
        pdf.cell(30, 6, "Invoice No:", 0, 0)
        pdf.set_font('Helvetica', '', 11)
        pdf.cell(65, 6, invoice_data['invoice_number'], 0, 0)
        
        # Right column - Date (BOLD, right-aligned)
        pdf.set_font('Helvetica', 'B', 11)
        pdf.cell(0, 6, f"Date: {invoice_data['issued_date']}", 0, 1, 'R')
        
        # Due Date (BOLD)
        pdf.set_xy(10, pdf.get_y())
        pdf.set_font('Helvetica', 'B', 11)
        pdf.cell(30, 6, "Due Date:", 0, 0)
        pdf.set_font('Helvetica', '', 11)
        pdf.cell(0, 6, invoice_data['due_date'], 0, 1)
        
        pdf.ln(8)
        
        # --- BILL TO SECTION ---
        pdf.set_font('Helvetica', 'B', 11)
        pdf.cell(0, 6, "Bill To:", 0, 1)
        
        # Parent/Guardian with BOLD name (no student ID prefix)
        pdf.set_font('Helvetica', '', 10)
        pdf.cell(35, 6, "Parent/Guardian of ", 0, 0)
        pdf.set_font('Helvetica', 'B', 10)
        pdf.cell(0, 6, invoice_data['student_name'], 0, 1)
        
        # Student ID on its own line (BOLD)
        pdf.set_font('Helvetica', '', 10)
        pdf.cell(20, 6, "Student ID: ", 0, 0)
        pdf.set_font('Helvetica', 'B', 10)
        pdf.cell(0, 6, invoice_data['student_id'], 0, 1)
        
        # Class on its own line (BOLD)
        pdf.set_font('Helvetica', '', 10)
        pdf.cell(20, 6, "Class: ", 0, 0)
        pdf.set_font('Helvetica', 'B', 10)
        pdf.cell(0, 6, invoice_data['grade'], 0, 1)
        
        pdf.ln(8)
        
        # --- LINE ITEMS TABLE ---
        # Table Header
        pdf.set_font('Helvetica', 'B', 10)
        pdf.set_fill_color(200, 220, 255)  # Light blue
        pdf.set_draw_color(100, 100, 100)  # Grey borders
        
        pdf.cell(100, 8, "DESCRIPTION", 1, 0, "L", True)
        pdf.cell(30, 8, "QTY", 1, 0, "C", True)
        pdf.cell(50, 8, f"AMOUNT ({SCHOOL_INFO['currency']})", 1, 1, "R", True)
        
        # Line Items - keep original optional/mandatory indicators
        pdf.set_font('Helvetica', '', 10)
        for item in invoice_data['items']:
            pdf.cell(100, 8, f"  {item['description']}", 1, 0, "L")
            pdf.cell(30, 8, str(item['qty']), 1, 0, "C")
            pdf.cell(50, 8, f"${item['amount']:.2f}", 1, 1, "R")
        
        # TOTAL ROW
        pdf.set_font('Helvetica', 'B', 11)
        pdf.cell(130, 10, "TOTAL:", 1, 0, "R")
        pdf.cell(50, 10, f"${invoice_data['total_amount']:.2f}", 1, 1, "R")
        
        pdf.ln(10)
        
        # --- BANKING DETAILS ---
        pdf.set_font('Helvetica', 'B', 11)
        pdf.cell(0, 6, "Payment Details:", 0, 1)
        pdf.set_font('Helvetica', '', 10)
        pdf.cell(0, 5, f"Bank Name: {SCHOOL_INFO['bank_name']}", 0, 1)
        pdf.cell(0, 5, f"Account Name: {SCHOOL_INFO['account_name']}", 0, 1)
        pdf.cell(0, 5, f"Account Number: {SCHOOL_INFO['account_number']}", 0, 1)
        pdf.cell(0, 5, f"Currency: {SCHOOL_INFO['currency']}", 0, 1)
        
        pdf.ln(15)
        
        # --- AUTHORIZATION SECTION ---
        # Create digital stamp (looks like ink stamp)
        stamp_y = pdf.get_y()
        
        pdf.set_font('Helvetica', 'I', 9)
        pdf.cell(0, 5, "Authorized by:", 0, 1)
        
        # Create the digital stamp (smaller size: 50x35)
        create_digital_stamp(pdf, 10, stamp_y + 5, invoice_data['issued_date'])
        
        pdf.ln(45)  # Adjusted space for smaller stamp
        
        # --- FOOTER ---
        pdf.set_y(-30)
        pdf.set_font('Helvetica', 'I', 8)
        pdf.set_text_color(100, 100, 100)
        pdf.cell(0, 5, "This invoice is computer-generated and valid for company reimbursement purposes.", 0, 1, "C")
        pdf.cell(0, 5, f"For queries, contact {SCHOOL_INFO['email_admin']} or call {SCHOOL_INFO['tel']}", 0, 1, "C")
        
        # Save PDF
        pdf.output(output_path)
        
        if not os.path.exists(output_path):
            raise Exception("PDF generation failed - file not created")
        
        logger.info(f"Invoice PDF generated: {output_path}", extra=extra_log)
        return output_path
        
    except Exception as e:
        logger.error(f"PDF generation failed: {str(e)}", extra=extra_log)
        raise


def upload_invoice_to_s3(pdf_path, invoice_number, extra_log):
    """
    Upload invoice PDF to S3 bucket.
    
    Args:
        pdf_path (str): Local path to PDF file
        invoice_number (str): Invoice number for S3 key
        extra_log (dict): Logging context
    
    Returns:
        str: S3 key (path in bucket)
    """
    s3_key = f"invoices/{invoice_number}.pdf"
    
    try:
        s3.upload_file(
            pdf_path,
            bucket_name,
            s3_key,
            ExtraArgs={'ContentType': 'application/pdf'}
        )
        logger.info(f"Invoice uploaded to S3: s3://{bucket_name}/{s3_key}", extra=extra_log)
        return s3_key
    except Exception as e:
        logger.error(f"Failed to upload invoice to S3: {e}", extra=extra_log)
        raise


def generate_invoice(student_id, term, whatsapp_number, request_id=None):
    """
    Main function to generate and prepare an invoice for delivery.
    
    Args:
        student_id (str): Student ID
        term (str): Term code
        whatsapp_number (str): WhatsApp number for the requesting parent
        request_id (str): Request tracking ID
    
    Returns:
        tuple: (result_dict, http_status_code)
    
    Raises:
        ValueError: If no fees or invalid data
        Exception: If PDF generation or upload fails
    """
    session = init_db()
    extra_log = {"request_id": request_id, "student_id": student_id, "term": term}
    
    try:
        logger.info(f"Generating invoice for {student_id}, term {term}", extra=extra_log)
        
        # Initialize API client
        sms_client = SMSClient(request_id=request_id)
        
        # Check if invoice already exists for this student/term
        existing_invoice = session.query(Invoice).filter_by(
            student_id=student_id,
            term=term
        ).first()
        
        if existing_invoice:
            # Re-send existing invoice
            logger.info(f"Re-sending existing invoice: {existing_invoice.invoice_number}", extra=extra_log)
            
            # Generate presigned URL
            pdf_url = s3.generate_presigned_url(
                'get_object',
                Params={'Bucket': bucket_name, 'Key': existing_invoice.pdf_path},
                ExpiresIn=3600  # 1 hour
            )
            
            return {
                "invoice_number": existing_invoice.invoice_number,
                "pdf_url": pdf_url,
                "total_amount": existing_invoice.total_amount,
                "issued_date": existing_invoice.issued_date.strftime("%d %B %Y"),
                "due_date": existing_invoice.due_date.strftime("%d %B %Y"),
                "is_resend": True
            }, 200
        
        # Fetch invoice data
        try:
            invoice_info = get_invoice_line_items(student_id, term, sms_client, extra_log)
        except Exception as e:
            logger.error(f"Failed to fetch invoice data: {e}", extra=extra_log)
            raise ValueError("Unable to retrieve fee information from school system")
        
        # Validate that fees exist
        if not invoice_info['items']:
            raise ValueError("No fees recorded for this student and term")
        
        # Generate invoice number
        sequence = 1
        invoice_number = generate_invoice_number(student_id, term, sequence)
        
        # Calculate dates
        issued_date = datetime.now(timezone.utc)
        due_date = issued_date + timedelta(days=7)  # Due 7 days after generation
        
        # Prepare invoice data for PDF
        pdf_data = {
            "invoice_number": invoice_number,
            "issued_date": issued_date.strftime("%d %B %Y"),
            "due_date": due_date.strftime("%d %B %Y"),
            "student_name": invoice_info['student_profile']['name'],
            "student_id": student_id,
            "grade": invoice_info['student_profile']['grade'],
            "items": invoice_info['items'],
            "total_amount": invoice_info['total_amount'],
            "branch_address": BRANCH_ADDRESSES.get("Hatfield", BRANCH_ADDRESSES["default"])  # TODO: Detect branch from student data
        }
        
        # Generate PDF
        os.makedirs("/tmp", exist_ok=True)
        temp_pdf_path = f"/tmp/{invoice_number}.pdf"
        create_invoice_pdf(pdf_data, temp_pdf_path, extra_log)
        
        # Upload to S3
        s3_key = upload_invoice_to_s3(temp_pdf_path, invoice_number, extra_log)
        
        # Clean up temporary file
        try:
            os.remove(temp_pdf_path)
        except Exception as e:
            logger.warning(f"Failed to delete temp file {temp_pdf_path}: {e}", extra=extra_log)
        
        # Generate presigned URL
        pdf_url = s3.generate_presigned_url(
            'get_object',
            Params={'Bucket': bucket_name, 'Key': s3_key},
            ExpiresIn=3600
        )
        
        # Save invoice record to database
        new_invoice = Invoice(
            invoice_number=invoice_number,
            student_id=student_id,
            term=term,
            issued_date=issued_date,
            due_date=due_date,
            whatsapp_number=whatsapp_number,
            total_amount=invoice_info['total_amount'],
            pdf_path=s3_key
        )
        session.add(new_invoice)
        session.commit()
        
        logger.info(f"Invoice {invoice_number} generated successfully", extra=extra_log)
        
        return {
            "invoice_number": invoice_number,
            "pdf_url": pdf_url,
            "total_amount": invoice_info['total_amount'],
            "issued_date": pdf_data['issued_date'],
            "due_date": pdf_data['due_date'],
            "is_resend": False
        }, 200
    
    except ValueError as e:
        logger.error(f"Validation error: {str(e)}", extra=extra_log)
        return {"error": str(e)}, 400
    except Exception as e:
        logger.error(f"Unexpected error in invoice generation: {str(e)}\n{traceback.format_exc()}", extra=extra_log)
        return {"error": f"Internal server error: {str(e)}"}, 500
    finally:
        session.remove()
