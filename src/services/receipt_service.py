"""Payment-receipt PDFs sent to parents over WhatsApp.

A payment is recorded in the SaaS, the SaaS pushes the details to the bot
(/payment-receipt), and this module renders a branded PDF receipt, uploads it to
object storage (R2), and returns a presigned link for delivery.

Self-contained generation: shares the school branding (logo, SCHOOL_INFO) used by
the invoice PDFs.
"""
import os
from datetime import datetime, timezone

from config import make_s3_client, Config as AppConfig
from services.invoice_service import SCHOOL_INFO
from utils.logger import setup_logger

logger = setup_logger(__name__)

s3 = make_s3_client()
bucket_name = AppConfig.RECEIPT_S3_BUCKET

_BLUE = (0, 0, 139)


def _money(currency, amount):
    try:
        return f"{currency}{float(amount):,.2f}"
    except (TypeError, ValueError):
        return f"{currency}{amount}"


def generate_receipt_pdf(data, output_path, extra_log=None):
    """Render a branded payment receipt to output_path. Returns the path.

    data keys: student_name, student_id, reference, date (str), currency,
    amount, items [{description, amount}], balance_after, payer_name.
    """
    extra_log = extra_log or {}
    try:
        from fpdf import FPDF
    except ImportError as e:
        logger.error(f"fpdf2 not available: {e}", extra=extra_log)
        raise Exception("PDF generation dependencies not available")

    currency = data.get("currency") or "$"
    pdf = FPDF()
    pdf.add_page()
    pdf.set_auto_page_break(auto=True, margin=15)

    # --- Header: logo + school identity ---
    logo_path = "static/school_logo.png"
    if os.path.exists(logo_path):
        pdf.image(logo_path, x=10, y=10, w=28)
        hx = 45
    else:
        hx = 10
    pdf.set_xy(hx, 12)
    pdf.set_font("Helvetica", "B", 16)
    pdf.set_text_color(*_BLUE)
    pdf.cell(0, 7, SCHOOL_INFO.get("name", "SHINING SMILES COLLEGE"), ln=True)
    pdf.set_xy(hx, 20)
    pdf.set_font("Helvetica", "", 9)
    pdf.set_text_color(0, 0, 0)
    pdf.cell(0, 5, f"Email: {SCHOOL_INFO.get('email_admin', '')}", ln=True)
    pdf.set_xy(hx, 25)
    pdf.cell(0, 5, f"Tel: {SCHOOL_INFO.get('tel', '')}", ln=True)
    pdf.ln(16)

    # --- Title ---
    pdf.set_font("Helvetica", "B", 18)
    pdf.set_text_color(30, 132, 73)  # green = paid
    pdf.cell(0, 10, "PAYMENT RECEIPT", ln=True, align="C")
    pdf.ln(2)

    # --- Meta row (receipt # + date) ---
    pdf.set_font("Helvetica", "", 10)
    pdf.set_text_color(0, 0, 0)
    pdf.cell(95, 6, f"Receipt No: {data.get('reference', '-')}", border=0)
    pdf.cell(0, 6, f"Date: {data.get('date', datetime.now(timezone.utc).strftime('%d %b %Y'))}", ln=True, align="R")
    pdf.cell(95, 6, f"Student: {data.get('student_name', '-')}", border=0)
    pdf.cell(0, 6, f"ID: {data.get('student_id', '-')}", ln=True, align="R")
    if data.get("payer_name"):
        pdf.cell(0, 6, f"Received from: {data['payer_name']}", ln=True)
    pdf.ln(4)

    # --- Line items table ---
    pdf.set_font("Helvetica", "B", 10)
    pdf.set_fill_color(*_BLUE)
    pdf.set_text_color(255, 255, 255)
    pdf.cell(130, 8, "  Description", border=0, fill=True)
    pdf.cell(0, 8, "Amount  ", border=0, fill=True, ln=True, align="R")
    pdf.set_text_color(0, 0, 0)
    pdf.set_font("Helvetica", "", 10)
    items = data.get("items") or [{"description": "Payment received", "amount": data.get("amount", 0)}]
    fill = False
    for it in items:
        pdf.set_fill_color(245, 247, 249)
        pdf.cell(130, 8, "  " + str(it.get("description", "Payment")), border="B", fill=fill)
        pdf.cell(0, 8, _money(currency, it.get("amount", 0)) + "  ", border="B", fill=fill, ln=True, align="R")
        fill = not fill

    # --- Total paid + balance ---
    pdf.ln(2)
    pdf.set_font("Helvetica", "B", 12)
    pdf.cell(130, 9, "  TOTAL PAID", border=0)
    pdf.set_text_color(30, 132, 73)
    pdf.cell(0, 9, _money(currency, data.get("amount", 0)) + "  ", ln=True, align="R")
    pdf.set_text_color(0, 0, 0)
    if data.get("balance_after") is not None:
        pdf.set_font("Helvetica", "", 11)
        pdf.cell(130, 8, "  Outstanding balance", border=0)
        pdf.cell(0, 8, _money(currency, data.get("balance_after")) + "  ", ln=True, align="R")

    # --- Footer ---
    pdf.ln(12)
    pdf.set_font("Helvetica", "I", 9)
    pdf.set_text_color(120, 120, 120)
    pdf.multi_cell(0, 5, "This is an official computer-generated receipt from Shining Smiles College. "
                         "Thank you for your payment.", align="C")

    pdf.output(output_path)
    return output_path


def upload_and_sign(local_path, reference, extra_log=None):
    """Upload the receipt to R2 and return a presigned GET url (valid ~1h)."""
    extra_log = extra_log or {}
    key = f"receipts/{reference}_{datetime.now(timezone.utc).strftime('%Y%m%d%H%M%S')}.pdf"
    s3.upload_file(local_path, bucket_name, key, ExtraArgs={"ContentType": "application/pdf"})
    url = s3.generate_presigned_url("get_object", Params={"Bucket": bucket_name, "Key": key}, ExpiresIn=3600)
    logger.info(f"Receipt uploaded: s3://{bucket_name}/{key}", extra=extra_log)
    return url
